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

DEFAULT_VOICE = {"openai": "cedar", "kokoro": "af_heart", "edge": "en-US-AriaNeural"}
DEFAULT_MODEL = {"openai": "gpt-4o-mini-tts", "kokoro": "mlx-community/Kokoro-82M-bf16", "edge": None}
SR = 48000


def _cache_dir():
    try:
        from .config import CACHE
    except Exception:
        CACHE = os.path.expanduser("~/.cache/video-studio")
    d = os.path.join(CACHE, "tts")
    os.makedirs(d, exist_ok=True)
    return d


def pick_engine(name="auto"):
    """Engine to use: ``name`` unless "auto" -> kokoro (Apple Silicon + mlx_audio) -> edge -> openai
    (OPENAI_API_KEY set). Raises RuntimeError if none. From preproduction ``make_drill.pick_engine``."""
    if name != "auto":
        return name
    if platform.system() == "Darwin" and platform.machine() == "arm64" and importlib.util.find_spec("mlx_audio"):
        return "kokoro"
    if importlib.util.find_spec("edge_tts") or shutil.which("edge-tts"):
        return "edge"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError("no TTS engine: pip install mlx-audio (Apple Silicon) | edge-tts | openai (+OPENAI_API_KEY)")


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
    return v or DEFAULT_VOICE[engine]


def cache_key(text, engine, voice, speed, instructions, model):
    return hashlib.sha1(json.dumps([engine, model, voice, round(float(speed), 4), instructions or "", text],
                                   ensure_ascii=False).encode()).hexdigest()


def _openai(text, voice, speed, instructions, model, dst):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    body = {"model": model, "voice": voice, "input": text, "speed": speed, "response_format": "wav"}
    if instructions and not model.startswith("tts-1"):
        body["instructions"] = instructions
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as f:
        f.write(r.read())


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


def synth(text, engine="openai", voice=None, speed=1.0, instructions=None, out=None, model=None, cache=True):
    """Synthesise ``text`` -> 48 kHz mono wav; returns the wav path (``out`` if given, else the cache file).

    Args: engine "openai" | "kokoro" | "edge" | "auto"; voice (default persona tts.<engine>_voice);
    speed (1.0 = normal; openai 0.25-4, edge as +-% rate); instructions = delivery direction (openai
    gpt-4o-* only); model overrides DEFAULT_MODEL; cache=False forces a new take (still cached after).
    """
    engine = pick_engine(engine)
    if engine not in DEFAULT_VOICE:
        raise ValueError(f"unknown TTS engine {engine!r}")
    voice = _voice(engine, voice)
    model = model or DEFAULT_MODEL[engine]
    key = cache_key(text, engine, voice, speed, instructions, model)
    cpath = os.path.join(_cache_dir(), f"{key}.wav")
    if not (cache and os.path.exists(cpath)):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "raw" + (".mp3" if engine == "edge" else ".wav"))
            if engine == "openai":
                _openai(text, voice, speed, instructions, model, raw)
            elif engine == "kokoro":
                _kokoro(text, voice, speed, model, raw, tmp)
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
