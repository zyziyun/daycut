"""Text-to-speech with a content-addressed cache.

    from vstudio import tts
    wav = tts.synth("Welcome back.", engine="openai", voice="cedar", out="audio/vo/line01.wav")
    wav = tts.synth("Repeat after me.", engine="kokoro", speed=0.85)       # Apple Silicon, offline
    tts.pick_engine()                                                       # first available

Engines (all optional imports, nothing is needed until you call one):
  openai  gpt-4o-mini-tts (supports ``instructions`` = delivery direction). Key from the
          OPENAI_API_KEY environment variable ONLY. ``openai`` package if installed, else plain HTTPS.
  kokoro  Kokoro-82M via ``mlx_audio`` (Apple Silicon, offline).
  edge    Microsoft Edge neural voices via ``edge_tts`` (needs network, no key).
  clone   your OWN voice, cloned from a short reference recording: Qwen3-TTS (Base) via ``mlx_audio``
          (Apple Silicon, offline). Needs ``ref_wav`` (5-15 s of clean speech) + ``ref_text`` (its exact
          transcript), passed as arguments or set in persona.local.yaml (never commit the recording):
              tts:
                clone:
                  ref_wav: ~/voice/ref.wav
                  ref_text: "exact words spoken in ref.wav"
                  model: mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16    # optional
                  language: English                                     # optional (auto from text)
          ``seed`` makes a take reproducible; retries with different seeds = different takes. The loaded
          model stays in memory for the process. Cache key includes a hash of the reference audio + text.
  openai-compatible  any self-hosted ``/v1/audio/speech`` server (Kokoro-FastAPI, openedai-speech, LocalAI, ...):
          env VSTUDIO_TTS_BASE_URL or persona ``tts.server.base_url``, optional ``api_key_env`` (env var NAME),
          ``model``, ``voice`` (persona ``tts.server.*``; env VSTUDIO_TTS_API_KEY_ENV / VSTUDIO_TTS_MODEL).
  elevenlabs  ElevenLabs API (optional): ELEVENLABS_API_KEY from the environment ONLY; voice = a voice id
          (persona ``tts.elevenlabs_voice``), model eleven_multilingual_v2; speed 0.7-1.2.
"auto" = persona ``tts.engine`` / env VSTUDIO_TTS_ENGINE, else kokoro (Apple Silicon) -> edge -> openai.
``providers()`` (and ``python -m vstudio.llm providers``) lists what works on this machine.
Output is always 48 kHz mono 16-bit wav. Cache: ``$VSTUDIO_CACHE/tts/<sha1>.wav`` keyed by
engine+model+voice+speed+instructions+text, so re-running a script never pays twice.
Voice defaults: persona ``tts.<engine>_voice`` else DEFAULT_VOICE.
Unified from preproduction ``make_drill.tts/pick_engine/to_wav``, explainer ``tts.py`` (urllib
OpenAI call with per-line direction), photo-story ``tts.main.synth`` (cache by text+voice+instructions).
"""
import asyncio
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from . import media

DEFAULT_VOICE = {"openai": "cedar", "kokoro": "af_heart", "edge": "en-US-AriaNeural", "clone": "ref",
                 "openai-compatible": "af_heart", "elevenlabs": "21m00Tcm4TlvDq8ikWAM"}
DEFAULT_MODEL = {"openai": "gpt-4o-mini-tts", "kokoro": "mlx-community/Kokoro-82M-bf16", "edge": None,
                 "clone": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16", "openai-compatible": "kokoro",
                 "elevenlabs": "eleven_multilingual_v2"}
ENGINES = ("openai", "kokoro", "edge", "clone", "openai-compatible", "elevenlabs")
ALIASES = {"compatible": "openai-compatible", "tts-server": "openai-compatible", "eleven": "elevenlabs",
           "11labs": "elevenlabs", "edge-tts": "edge", "qwen3-clone": "clone"}
LANG_NAMES = {"en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German", "fr": "French",
              "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ru": "Russian"}
_CLONE_MODELS = {}
SR = 48000


def _cache_dir():
    try:
        from .config import CACHE
    except Exception:
        CACHE = os.path.expanduser("~/.cache/video-studio")
    d = os.path.join(CACHE, "tts")
    os.makedirs(d, exist_ok=True)
    return d


def _tts_cfg():
    try:
        from .config import persona
        return persona().get("tts") or {}
    except Exception:  # noqa: BLE001
        return {}


def server_config():
    """The openai-compatible TTS server: dict(base_url, api_key_env, model, voice) from env / persona tts.server."""
    c = _tts_cfg().get("server") or {}
    return dict(base_url=os.environ.get("VSTUDIO_TTS_BASE_URL") or c.get("base_url"),
                api_key_env=os.environ.get("VSTUDIO_TTS_API_KEY_ENV") or c.get("api_key_env"),
                model=os.environ.get("VSTUDIO_TTS_MODEL") or c.get("model"), voice=c.get("voice"))


def pick_engine(name="auto"):
    """Engine to use: ``name`` unless "auto" -> persona ``tts.engine`` / env VSTUDIO_TTS_ENGINE -> kokoro (Apple
    Silicon + mlx_audio) -> edge -> openai (OPENAI_API_KEY set). Raises RuntimeError if none. From preproduction
    ``make_drill.pick_engine``."""
    name = ALIASES.get(str(name or "auto").lower(), str(name or "auto").lower())
    if name == "auto":
        conf = os.environ.get("VSTUDIO_TTS_ENGINE") or _tts_cfg().get("engine")
        if conf and str(conf).lower() != "auto":
            name = ALIASES.get(str(conf).lower(), str(conf).lower())
    if name != "auto":
        return name
    if platform.system() == "Darwin" and platform.machine() == "arm64" and importlib.util.find_spec("mlx_audio"):
        return "kokoro"
    if importlib.util.find_spec("edge_tts") or shutil.which("edge-tts"):
        return "edge"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError("no TTS engine: pip install mlx-audio (Apple Silicon) | edge-tts | openai (+OPENAI_API_KEY)")


def providers(probe=True):
    """[{provider, kind, ready, detail}] for every TTS engine on this machine (nothing is synthesised)."""
    mac_arm = platform.system() == "Darwin" and platform.machine() == "arm64"
    mlx = bool(importlib.util.find_spec("mlx_audio"))
    edge = bool(importlib.util.find_spec("edge_tts") or shutil.which("edge-tts"))
    try:
        clone_ok, clone_d = True, "reference set in persona tts.clone"
        clone_config()
    except RuntimeError:
        clone_ok, clone_d = False, "needs persona tts.clone.ref_wav + ref_text"
    rows = [dict(provider="openai", kind="api", ready=bool(os.environ.get("OPENAI_API_KEY")),
                 detail="gpt-4o-mini-tts, key set" if os.environ.get("OPENAI_API_KEY") else "needs OPENAI_API_KEY"),
            dict(provider="kokoro", kind="local", ready=mac_arm and mlx,
                 detail="mlx-audio Kokoro-82M" if mac_arm and mlx else "pip install mlx-audio (Apple Silicon)"),
            dict(provider="edge", kind="api (no key)", ready=edge,
                 detail="edge-tts (Microsoft online voices, no key)" if edge else "pip install edge-tts"),
            dict(provider="clone", kind="local", ready=mac_arm and mlx and clone_ok,
                 detail=("mlx-audio Qwen3-TTS; " if mac_arm and mlx else "needs mlx-audio (Apple Silicon); ") + clone_d),
            dict(provider="elevenlabs", kind="api", ready=bool(os.environ.get("ELEVENLABS_API_KEY")),
                 detail="key set" if os.environ.get("ELEVENLABS_API_KEY") else "needs ELEVENLABS_API_KEY (optional)")]
    sc = server_config()
    if sc["base_url"]:
        up = False
        if probe:
            from .llm import _probe_url
            up = _probe_url(sc["base_url"].rstrip("/") + "/models", strict=False)[0] or \
                _probe_url(sc["base_url"].rstrip("/") + "/audio/voices", strict=False)[0]
        rows.append(dict(provider="openai-compatible", kind="local", ready=up,
                         detail=f"{sc['base_url']}: " + ("up" if up else "no server answering" if probe else "not probed")))
    else:
        rows.append(dict(provider="openai-compatible", kind="local", ready=False,
                         detail="set VSTUDIO_TTS_BASE_URL (Kokoro-FastAPI, openedai-speech, LocalAI, ...)"))
    return rows


def default_voice(engine="auto"):
    """The voice ``synth`` uses for ``engine`` when none is passed (persona tts.<engine>_voice, else
    DEFAULT_VOICE) - for logging. engine "auto" resolves through ``pick_engine``."""
    return _voice(pick_engine(engine), None)


def _voice(engine, voice):
    if voice:
        return voice
    try:
        from .config import persona
        v = (persona().get("tts") or {}).get(f"{engine}_voice")
    except Exception:
        v = None
    if not v and engine == "openai-compatible":
        v = server_config()["voice"]
    return v or DEFAULT_VOICE[engine]


def cache_key(text, engine, voice, speed, instructions, model):
    return hashlib.sha1(json.dumps([engine, model, voice, round(float(speed), 4), instructions or "", text],
                                   ensure_ascii=False).encode()).hexdigest()


def _speech_http(url, body, headers, dst, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(headers, **{
        "Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dst, "wb") as f:
        f.write(r.read())


def _openai(text, voice, speed, instructions, model, dst):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    body = {"model": model, "voice": voice, "input": text, "speed": speed, "response_format": "wav"}
    if instructions and not model.startswith("tts-1"):
        body["instructions"] = instructions
    _speech_http("https://api.openai.com/v1/audio/speech", body, {"Authorization": f"Bearer {key}"}, dst)


def _compatible(text, voice, speed, instructions, model, dst):
    sc = server_config()
    if not sc["base_url"]:
        raise RuntimeError("TTS engine openai-compatible needs VSTUDIO_TTS_BASE_URL (or persona tts.server.base_url)")
    key = os.environ.get(sc["api_key_env"]) if sc["api_key_env"] else None
    if sc["api_key_env"] and not key:
        raise RuntimeError(f"TTS engine openai-compatible needs {sc['api_key_env']}")
    body = {"model": model, "voice": voice, "input": text, "speed": speed, "response_format": "wav"}
    if instructions:
        body["instructions"] = instructions
    _speech_http(sc["base_url"].rstrip("/") + "/audio/speech", body,
                 {"Authorization": f"Bearer {key}"} if key else {}, dst)


def _elevenlabs(text, voice, speed, model, dst):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set in the environment")
    body = {"text": text, "model_id": model, "voice_settings": {"speed": max(0.7, min(1.2, float(speed)))}}
    _speech_http(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128", body,
                 {"xi-api-key": key, "Accept": "audio/mpeg"}, dst)


def _kokoro(text, voice, speed, model, dst, tmp):
    if not importlib.util.find_spec("mlx_audio"):
        raise RuntimeError("kokoro needs mlx-audio (pip install mlx-audio; Apple Silicon)")
    r = subprocess.run([sys.executable, "-m", "mlx_audio.tts.generate", "--model", model, "--text", text,
                        "--voice", voice, "--speed", str(speed), "--join_audio", "--audio_format", "wav",
                        "--output_path", tmp, "--file_prefix", "k"], capture_output=True, text=True)
    tail = lambda: "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-15:])
    if r.returncode != 0:
        raise RuntimeError(f"mlx_audio failed (exit {r.returncode}):\n{tail()}")
    cands = [f for f in os.listdir(tmp) if f.startswith("k") and f.endswith(".wav")]
    if not cands:
        # mlx_audio prints the real error (bad voice, model download) to stdout and exits 0
        raise RuntimeError(f"mlx_audio produced no wav; its output:\n{tail()}")
    shutil.move(os.path.join(tmp, sorted(cands)[0]), dst)


def clone_config(ref_wav=None, ref_text=None, model=None, language=None):
    """Resolve the clone engine's reference + model: arguments first, then persona ``tts.clone.*``.
    Returns dict(ref_wav, ref_text, model, language, ref_hash). Raises RuntimeError when the reference
    is missing."""
    try:
        from .config import persona
        pc = (persona().get("tts") or {}).get("clone") or {}
    except Exception:
        pc = {}
    ref_wav = ref_wav or pc.get("ref_wav")
    ref_text = ref_text if ref_text is not None else pc.get("ref_text")
    if not ref_wav or not os.path.exists(os.path.expanduser(str(ref_wav))):
        raise RuntimeError("clone engine needs a reference recording: pass ref_wav= or set persona "
                           f"tts.clone.ref_wav in persona.local.yaml (got {ref_wav!r})")
    if not ref_text:
        raise RuntimeError("clone engine needs ref_text (the exact transcript of ref_wav): pass ref_text= "
                           "or set persona tts.clone.ref_text")
    ref_wav = os.path.abspath(os.path.expanduser(str(ref_wav)))
    h = hashlib.sha1()
    with open(ref_wav, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    h.update(str(ref_text).encode())
    lang = language or pc.get("language")
    lang = LANG_NAMES.get(str(lang).lower(), lang) if lang else None
    return dict(ref_wav=ref_wav, ref_text=str(ref_text), model=model or pc.get("model") or DEFAULT_MODEL["clone"],
                language=lang, ref_hash=h.hexdigest()[:16])


def _guess_language(text):
    return "Chinese" if any("\u4e00" <= c <= "\u9fff" for c in text) else "English"


def _clone_model(model):
    """Load (once per process) a Qwen3-TTS model through mlx_audio."""
    if model not in _CLONE_MODELS:
        if not importlib.util.find_spec("mlx_audio"):
            raise RuntimeError("clone engine needs mlx-audio (pip install mlx-audio; Apple Silicon) and the "
                               f"model {model} (downloaded by Hugging Face on first use, several GB)")
        from mlx_audio.tts.utils import load_model
        _CLONE_MODELS[model] = load_model(model)
    return _CLONE_MODELS[model]


def _clone(text, cfg, dst, seed=None):
    import numpy as np
    import soundfile as sf
    m = _clone_model(cfg["model"])
    if seed is not None:
        try:
            import mlx.core as mx
            mx.random.seed(int(seed))
        except ImportError:
            pass
    res = list(m.generate(text=text, ref_audio=cfg["ref_wav"], ref_text=cfg["ref_text"],
                          language=cfg["language"] or _guess_language(text)))
    if not res:
        raise RuntimeError("clone engine produced no audio")
    a = np.concatenate([np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in res])
    sf.write(dst, a, int(getattr(m, "sample_rate", 24000)))


def _edge(text, voice, speed, dst):
    rate = f"{int(round((speed - 1) * 100)):+d}%"
    if importlib.util.find_spec("edge_tts"):
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(dst))
    elif shutil.which("edge-tts"):
        subprocess.run(["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", dst],
                       check=True, capture_output=True)
    else:
        raise RuntimeError("edge engine needs edge-tts (pip install edge-tts)")


def synth(text, engine="openai", voice=None, speed=1.0, instructions=None, out=None, model=None, cache=True,
          ref_wav=None, ref_text=None, language=None, seed=None):
    """Synthesise ``text`` -> 48 kHz mono wav; returns the wav path (``out`` if given, else the cache file).

    Args: engine "openai" | "kokoro" | "edge" | "clone" | "openai-compatible" | "elevenlabs" | "auto"; voice (default persona tts.<engine>_voice);
    speed (1.0 = normal; openai 0.25-4, edge as +-% rate; ignored by clone); instructions = delivery direction
    (openai gpt-4o-* only); model overrides DEFAULT_MODEL; cache=False forces a new take (still cached after).
    clone only: ref_wav / ref_text / language (default persona tts.clone.*), seed (reproducible take; part
    of the cache key).
    """
    engine = pick_engine(engine)
    if engine not in DEFAULT_VOICE:
        raise ValueError(f"unknown TTS engine {engine!r}")
    ccfg = None
    if engine == "clone":
        ccfg = clone_config(ref_wav, ref_text, model, language)
        model = ccfg["model"]
        voice = f"ref:{ccfg['ref_hash']}:{ccfg['language'] or 'auto'}:{seed if seed is not None else '-'}"
    else:
        voice = _voice(engine, voice)
        model = model or (server_config()["model"] if engine == "openai-compatible" else None) or DEFAULT_MODEL[engine]
    key = cache_key(text, engine, voice, speed, instructions,
                    f"{server_config()['base_url']}#{model}" if engine == "openai-compatible" else model)
    cpath = os.path.join(_cache_dir(), f"{key}.wav")
    if not (cache and os.path.exists(cpath)):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "raw" + (".mp3" if engine in ("edge", "elevenlabs") else ".wav"))
            if engine == "openai":
                _openai(text, voice, speed, instructions, model, raw)
            elif engine == "openai-compatible":
                _compatible(text, voice, speed, instructions, model, raw)
            elif engine == "elevenlabs":
                _elevenlabs(text, voice, speed, model, raw)
            elif engine == "kokoro":
                _kokoro(text, voice, speed, model, raw, tmp)
            elif engine == "clone":
                _clone(text, ccfg, raw, seed)
            else:
                _edge(text, voice, speed, raw)
            part = cpath + ".part.wav"
            media.run(["ffmpeg", "-y", "-i", raw, "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", part])
            os.replace(part, cpath)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        shutil.copyfile(cpath, out)
        return out
    return cpath
