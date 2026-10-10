"""Speech recognition with word timestamps, cached, plus the term-fix pass.

    from vstudio import asr
    tr = asr.transcribe("talk.mp4", language="zh", prompt="Claude Code, HyperFrames")
    tr["words"]     -> [{"w": "我们", "t": 1.02, "te": 1.31}, ...]       (flat, term-fixed)
    tr["segments"]  -> whisper shape [{start, end, text, words: [{word, start, end}]}]
    asr.apply_term_fixes("cloud code 很好用")                        -> persona + generic fixes

Backends (``backend=``, or persona ``asr.backend`` / env VSTUDIO_ASR_BACKEND; "auto" = first available):
  mlx                mlx_whisper (Apple Silicon, local)
  faster             faster_whisper (CTranslate2, local, any OS)
  openai             OpenAI ``whisper-1`` (only if OPENAI_API_KEY is set in the environment; the key is never read
                     from files)
  openai-compatible  any self-hosted ``/v1/audio/transcriptions`` server (faster-whisper-server / speaches,
                     whisper.cpp ``server --inference-path /v1/audio/transcriptions``, LocalAI, a GPU box):
                     persona ``asr.base_url`` / env VSTUDIO_ASR_BASE_URL, optional key env name ``asr.api_key_env`` /
                     VSTUDIO_ASR_API_KEY_ENV, model ``asr.model`` / VSTUDIO_ASR_MODEL. Never picked by "auto".
                     A server that returns no word timestamps gets evenly spread words (``approx_words``).
  auto order: mlx -> faster -> openai. ``providers()`` / ``python -m vstudio.llm providers`` list what works here. Settings that matter on long/noisy speech: no conditioning on previous text and (for
recordings > 10 min only, see ``skip_silence``) a hallucination-silence threshold, else whisper loops
("嗯嗯嗯") over silence.

Results are cached in a sidecar ``<input>.asr.json`` keyed by the file's content hash + settings,
so re-running a pipeline never re-transcribes unchanged audio. Each one is also listed in a content index
(``<cache>/asr/index/<sha1 of the audio>.json`` -> the sidecar), so ``cached(path)`` - which reads the caches
without transcribing - finds a transcript made from the same bytes anywhere (a CLI run's ``work/audio.wav`` is the
same audio the planner extracts from the recording).

``transcribe(progress=fn)``: ``fn(done_s, total_s)`` while the local backends decode (mlx: its frame counter,
faster-whisper: each finished segment); the API backends report nothing until they return.

Unified from talkinghead ``asr.transcribe``, promo-recut ``common.transcribe/words_of``, call-clips
``transcribe.run_mlx/run_faster`` + ``build_subs.fix/TERM_FIX``, longform ``transcribe.py`` +
``subs_lib.term_fixes/GENERIC_TERM_FIXES/make_clean``, photo-story ``tts.Transcriber/align``.
"""
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import types

from . import media

MLX_REPO = os.environ.get("VSTUDIO_WHISPER_MLX", "mlx-community/whisper-large-v3-turbo")
FW_MODEL = os.environ.get("VSTUDIO_WHISPER_FW", "large-v3-turbo")
CACHE_VERSION = 1

# Common tech-talk mis-hearings that are safe for anyone (regex -> replacement). Creator-specific
# fixes belong in persona.local.yaml subtitles.term_fixes; per-recording ones at the call site.
# NB: \b does not work next to CJK (CJK counts as \w), so latin words are delimited with lookarounds.
GENERIC_TERM_FIXES = [
    (r"(?i)(?<![a-z])(?:lit|leet|lead) ?code(?![a-z])", "LeetCode"),
    (r"(?i)(?<![a-z])git ?hub(?![a-z])", "GitHub"),
    (r"(?i)(?<![a-z])open ?ai(?![a-z])", "OpenAI"),
    (r"(?i)(?<![a-z])(?:chat|challet) ?gpt(?![a-z])", "ChatGPT"),
    (r"[Ll]ong ?chain|[Ll]ung ?chain", "LangChain"),
    (r"[Ll]ong ?graph|[Ll]ung ?graph", "LangGraph"),
    (r"(?i)(?<![a-z])(?:pg ?vector|pd vector)(?![a-z])", "pgvector"),
    (r"system problem", "system prompt"),
    (r"field shot|feel shot", "few-shot"),
    (r"半tune", "fine-tune"),
    (r"[Ff]acefulness", "faithfulness"),
    (r"[Bb]anjmark", "benchmark"),
    (r"(?<![A-Za-z])REG(?![A-Za-z])", "RAG"),
    (r"readnning|readning", "reasoning"),
    (r"思维导徒", "思维导图"),
    (r"favor out|figur out", "figure out"),
    (r"(?i)(?<![a-z])(?:re[ae]l-?fold|reel fold)(?![a-z])", "Reelfold"),  # this app's own name ("Realfold", "Reel fold")
]


# ------------------------------------------------------------------ term fixes
def _persona_fixes():
    try:
        from .config import persona
        return ((persona().get("subtitles") or {}).get("term_fixes")) or {}
    except Exception:
        return {}


def persona_terms():
    """Her glossary: the words she says that a speech model gets wrong (her brand, product and people names) -
    persona ``subtitles.terms`` [str]. Whisper is primed with them and a near-miss spelling is put right."""
    try:
        from .config import persona
        t = (persona().get("subtitles") or {}).get("terms") or []
        return [str(x).strip() for x in t if str(x).strip()] if isinstance(t, list) else []
    except Exception:  # noqa: BLE001
        return []


def _edits(a, b):
    """Levenshtein distance (short words: the glossary check)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def apply_terms(text, terms=None):
    """A near-miss of one of her glossary words -> the word as she spells it ("Realfold" -> "Reelfold", "reel fold" ->
    "Reelfold"): latin terms of 5+ letters, same first letter, at most 1 edit (2 from 9 letters on), whole words only;
    a common English word is never respelt."""
    from .en_common import is_common
    terms = persona_terms() if terms is None else terms
    for term in terms:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.+-]{4,}", term):
            continue
        tl = term.lower()
        lim = 2 if len(term) >= 9 else 1

        def near(k):
            return k[:1] == tl[:1] and abs(len(k) - len(tl)) <= lim and _edits(k, tl) <= lim

        def two(m):                                   # "reel fold" / "Real-fold": one word misheard as two
            k = (m.group(1) + m.group(2)).lower()
            if is_common(m.group(1).lower()) or is_common(m.group(2).lower()):
                return term if k == tl else m.group(0)    # "a real fold" stays; only "reel fold" itself joins
            return term if near(k) else m.group(0)

        def one(m):
            w = m.group(0)
            k = w.lower()
            if k == tl or not near(k) or is_common(k):
                return w
            return term
        text = re.sub(r"(?<![A-Za-z])([A-Za-z]{2,})[ -]([A-Za-z]{2,})(?![A-Za-z])", two, text)
        text = re.sub(r"(?<![A-Za-z])[A-Za-z]{4,}(?![A-Za-z])", one, text)
    return text


def _compile_fixes(extra=None, generic=True):
    fixes = []
    if isinstance(extra, dict):                      # {"heard": "meant"}: literal, case-insensitive
        fixes += [(re.compile(re.escape(k), re.I), v) for k, v in extra.items()]
    elif extra:                                      # [[regex, replacement], ...]
        fixes += [(re.compile(p), r) for p, r in extra]
    fixes += [(re.compile(re.escape(k), re.I), v) for k, v in _persona_fixes().items()]
    if generic:
        fixes += [(re.compile(p), r) for p, r in GENERIC_TERM_FIXES]
    return fixes


def apply_term_fixes(text, extra=None, generic=True, clean=True):
    """Correct ASR mis-hearings in ``text``.

    Order: ``extra`` (call-site / per-recording: dict = literal case-insensitive, list of
    [regex, repl] = regex) -> persona ``subtitles.term_fixes`` (literal, case-insensitive) ->
    GENERIC_TERM_FIXES (if generic). clean: collapse whitespace, drop 嗯嗯 runs and 5+ repeated-char
    hallucination runs. Returns the fixed string.
    From longform ``subs_lib.term_fixes/make_clean``, call-clips ``build_subs.fix``, talkinghead ``asr._fix``.
    """
    for pat, rep in _compile_fixes(extra, generic):
        text = pat.sub(rep, text)
    text = apply_terms(text)                          # her glossary: near-miss spellings of her own words
    if clean:
        text = re.sub(r"嗯{2,}", "", text)
        text = re.sub(r"(.)\1{4,}", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


# ------------------------------------------------------------------ backends
BACKENDS = ("mlx", "faster", "openai", "openai-compatible")
ALIASES = {"mlx-whisper": "mlx", "mlx_whisper": "mlx", "faster-whisper": "faster", "faster_whisper": "faster",
           "whisper-1": "openai", "whisper-server": "openai-compatible", "compatible": "openai-compatible",
           "self-hosted": "openai-compatible", "local-server": "openai-compatible"}


def _asr_cfg():
    try:
        from .config import persona
        return persona().get("asr") or {}
    except Exception:  # noqa: BLE001
        return {}


def server_config():
    """The openai-compatible ASR server: dict(base_url, api_key_env, model) from env / persona ``asr``."""
    c = _asr_cfg()
    return dict(base_url=os.environ.get("VSTUDIO_ASR_BASE_URL") or c.get("base_url"),
                api_key_env=os.environ.get("VSTUDIO_ASR_API_KEY_ENV") or c.get("api_key_env"),
                model=os.environ.get("VSTUDIO_ASR_MODEL") or c.get("model"))


def resolve_backend(name="auto"):
    """The ASR backend ``transcribe(backend=name)`` would use: "mlx" | "faster" | "openai" | "openai-compatible"
    (probes imports / OPENAI_API_KEY for "auto"; raises RuntimeError if none). Lets callers pick a
    per-backend model before transcribing."""
    return _backend(name)


def _backend(name="auto"):
    name = ALIASES.get(str(name or "auto").lower(), str(name or "auto").lower())
    if name == "auto":
        conf = os.environ.get("VSTUDIO_ASR_BACKEND") or _asr_cfg().get("backend")
        if conf and str(conf).lower() != "auto":
            name = ALIASES.get(str(conf).lower(), str(conf).lower())
    if name != "auto":
        if name not in BACKENDS:
            raise ValueError(f"unknown ASR backend {name!r}: auto | {' | '.join(BACKENDS)}")
        return name
    try:
        import mlx_whisper  # noqa: F401
        return "mlx"
    except ImportError:
        pass
    try:
        import faster_whisper  # noqa: F401
        return "faster"
    except ImportError:
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError("no ASR backend: pip install mlx-whisper (Apple Silicon) or faster-whisper, "
                       "or set OPENAI_API_KEY for whisper-1, or point VSTUDIO_ASR_BASE_URL at a whisper server")


def providers(probe=True):
    """[{provider, kind, ready, detail}] for every ASR backend on this machine (no audio is sent)."""
    import importlib.util
    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    rows = [dict(provider="mlx", kind="local", ready=has("mlx_whisper"),
                 detail=f"mlx_whisper, {MLX_REPO}" if has("mlx_whisper") else "pip install mlx-whisper (Apple Silicon)"),
            dict(provider="faster", kind="local", ready=has("faster_whisper"),
                 detail=f"faster_whisper, {FW_MODEL}" if has("faster_whisper") else "pip install faster-whisper"),
            dict(provider="openai", kind="api", ready=bool(os.environ.get("OPENAI_API_KEY")) and has("openai"),
                 detail="whisper-1, key set" if os.environ.get("OPENAI_API_KEY") else "needs OPENAI_API_KEY")]
    sc = server_config()
    if sc["base_url"]:
        up = False
        if probe:
            from .llm import _probe_url
            up = _probe_url(sc["base_url"].rstrip("/") + "/models", strict=False)[0]
        rows.append(dict(provider="openai-compatible", kind="local", ready=up,
                         detail=f"{sc['base_url']}: " + ("up" if up else "no server answering" if probe else "not probed")))
    else:
        rows.append(dict(provider="openai-compatible", kind="local", ready=False,
                         detail="set VSTUDIO_ASR_BASE_URL (faster-whisper-server, whisper.cpp server, ...)"))
    return rows


_STATS = ("no_speech_prob", "avg_logprob", "compression_ratio")


def _stats(seg):
    """Whisper's per-segment confidence numbers (dict or object), rounded; missing ones omitted."""
    out = {}
    for k in _STATS:
        v = seg.get(k) if isinstance(seg, dict) else getattr(seg, k, None)
        if v is not None:
            try:
                out[k] = round(float(v), 4)
            except (TypeError, ValueError):
                pass
    return out


# the running ``transcribe(progress=)`` callback; module state (not a ``_RUN`` argument) so backends replaced by tests
# keep their signature. One transcription at a time per process is how every caller uses this module.
_PROGRESS = None


def _report(done_s, total_s=None):
    fn = _PROGRESS
    if fn is None:
        return
    try:
        fn(float(done_s), float(total_s) if total_s else None)
    except Exception:  # noqa: BLE001 - a progress consumer never breaks a transcription
        pass


class _MlxBar:
    """Stands in for the ``tqdm.tqdm`` bar mlx_whisper counts decoded mel frames on (100 per second of audio)."""

    def __init__(self, total=None, **_kw):
        self.total, self.n = float(total or 0), 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def update(self, n=1):
        self.n += n
        _report(self.n / 100.0, self.total / 100.0 or None)


def _mlx_progress(on):
    """Context: mlx_whisper's progress bar reports through ``_report`` (restored afterwards)."""
    import contextlib
    mod = sys.modules.get("mlx_whisper.transcribe")
    if not on or mod is None or not hasattr(mod, "tqdm"):
        return contextlib.nullcontext()

    @contextlib.contextmanager
    def swap():
        old = mod.tqdm
        mod.tqdm = types.SimpleNamespace(tqdm=_MlxBar)
        try:
            yield
        finally:
            mod.tqdm = old
    return swap()


def _run_mlx(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
    import mlx_whisper
    kw = {"temperature": 0.0} if greedy else {}
    with _mlx_progress(_PROGRESS is not None):
        r = mlx_whisper.transcribe(wav, path_or_hf_repo=model or MLX_REPO, language=language, **kw,
                                   word_timestamps=word_timestamps, initial_prompt=prompt or None,
                                   condition_on_previous_text=False,
                                   hallucination_silence_threshold=hst if word_timestamps else None, verbose=None)
    return [dict(start=s["start"], end=s["end"], text=s["text"], **_stats(s),
                 words=[dict(word=w["word"], start=w["start"], end=w["end"], p=w.get("probability"))
                        for w in s.get("words", []) or []]) for s in r["segments"]]


def faster_device(env=None, platform=None, cuda_count=None):
    """(device, compute_type) for faster-whisper.

    ``VSTUDIO_WHISPER_DEVICE`` = cpu | cuda | auto picks the device (``VSTUDIO_WHISPER_COMPUTE`` the compute type).
    Default: the CPU on Windows - ctranslate2 sees an NVIDIA driver there even when the CUDA 12 cuBLAS / cuDNN DLLs
    it needs are not installed (they are not in the wheel) and then fails mid-run; elsewhere "auto" (CUDA when a GPU
    is visible). There is no silent switch: a CUDA run that fails raises with how to pick the CPU."""
    env = os.environ if env is None else env
    platform = os.name if platform is None else platform
    want = (env.get("VSTUDIO_WHISPER_DEVICE") or "").strip().lower() or ("cpu" if platform == "nt" else "auto")
    compute = (env.get("VSTUDIO_WHISPER_COMPUTE") or "").strip().lower() or None
    if want not in ("cpu", "cuda"):
        if cuda_count is None:
            try:
                import ctranslate2
                cuda_count = ctranslate2.get_cuda_device_count()
            except Exception:  # noqa: BLE001
                cuda_count = 0
        want = "cuda" if cuda_count else "cpu"
    return want, compute or ("int8" if want == "cpu" else "float16")


def _run_faster(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
    from faster_whisper import WhisperModel
    device, compute = faster_device()
    try:
        m = WhisperModel(model or FW_MODEL, device=device, compute_type=compute)
        kw = {"temperature": 0.0} if greedy else {}
        # the samples, not the path: faster-whisper decodes a path with PyAV, whose API moves under it (faster-whisper
        # 1.2.1 + PyAV 19: open() no longer takes metadata_errors); our wav is already 16 kHz mono from ffmpeg
        import soundfile as sf
        audio, sr = sf.read(wav, dtype="float32", always_2d=False)
        if sr != 16000 or getattr(audio, "ndim", 1) != 1:
            raise RuntimeError(f"faster-whisper needs 16 kHz mono audio, got {sr} Hz / {getattr(audio, 'ndim', 1)} dims")
        segs, info = m.transcribe(audio, language=language, word_timestamps=word_timestamps,
                                  initial_prompt=prompt or None, **kw, condition_on_previous_text=False,
                                  hallucination_silence_threshold=hst if word_timestamps else None, vad_filter=False)
        total = getattr(info, "duration", None) or len(audio) / 16000.0
        out = []
        for s in segs:                                     # lazy: each segment is decoded as it is read
            out.append(dict(start=s.start, end=s.end, text=s.text, **_stats(s),
                            words=[dict(word=w.word, start=w.start, end=w.end, p=w.probability)
                                   for w in (s.words or [])]))
            _report(s.end, total)
        return out
    except RuntimeError as e:
        if device == "cuda" and re.search(r"cuda|cublas|cudnn", str(e), re.I):
            raise RuntimeError(f"faster-whisper could not run on the GPU ({str(e).splitlines()[0][:200]}). Install the "
                               "CUDA 12 cuBLAS + cuDNN libraries, or set VSTUDIO_WHISPER_DEVICE=cpu") from e
        raise


def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


def _spread_words(seg):
    """Evenly timed words for a segment a server returned without word timestamps (CJK per character)."""
    toks = re.findall(r"[A-Za-z0-9'’\-]+|[⺀-鿿豈-﫿]|[^\sA-Za-z0-9⺀-鿿豈-﫿]+", seg["text"] or "")
    toks = [t for t in toks if re.search(r"[A-Za-z0-9⺀-鿿豈-﫿]", t)]
    if not toks:
        return []
    a, b = float(seg["start"]), float(seg["end"])
    step = (b - a) / len(toks)
    return [dict(word=(" " + t if re.match(r"[A-Za-z0-9]", t) else t), start=round(a + k * step, 3),
                 end=round(a + (k + 1) * step, 3)) for k, t in enumerate(toks)]


def _openai_api(wav, language, prompt, word_timestamps, model, base_url=None, key=None):
    from openai import OpenAI
    kw = dict(api_key=key)
    if base_url:
        kw["base_url"] = base_url
    # whisper-1 caps uploads at 25 MB: send 32 kbps mono mp3 (~14 MB per hour)
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "a.mp3")
        media.run(["ffmpeg", "-y", "-i", wav, "-ac", "1", "-ar", "16000", "-b:a", "32k", mp3])
        with open(mp3, "rb") as f:
            r = OpenAI(**kw).audio.transcriptions.create(
                model=model or "whisper-1", file=f, language=language, prompt=prompt or None,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"] if word_timestamps else ["segment"])
    words = [dict(word=" " + _g(w, "word") if not re.match(r"[⺀-￿]", _g(w, "word") or "") else _g(w, "word"),
                  start=_g(w, "start"), end=_g(w, "end")) for w in (_g(r, "words") or [])]
    out = []
    for s in _g(r, "segments") or []:
        st, en = _g(s, "start"), _g(s, "end")
        ws = [w for w in words if st - 0.01 <= (w["start"] + w["end"]) / 2 < en + 0.01]
        stats = {k: round(float(_g(s, k)), 4) for k in _STATS if _g(s, k) is not None}
        seg = dict(start=st, end=en, text=_g(s, "text"), **stats, words=ws)
        if word_timestamps and not ws and not words:
            seg["words"], seg["approx_words"] = _spread_words(seg), True
        out.append(seg)
    return out


def _run_openai(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    return _openai_api(wav, language, prompt, word_timestamps, model, key=key)


def _run_compatible(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
    sc = server_config()
    if not sc["base_url"]:
        raise RuntimeError("ASR backend openai-compatible needs VSTUDIO_ASR_BASE_URL (or persona asr.base_url)")
    key = os.environ.get(sc["api_key_env"]) if sc["api_key_env"] else None
    if sc["api_key_env"] and not key:
        raise RuntimeError(f"ASR backend openai-compatible needs {sc['api_key_env']}")
    return _openai_api(wav, language, prompt, word_timestamps, model or sc["model"] or "whisper-1",
                       base_url=sc["base_url"], key=key or "not-needed")


def _detect_mlx(wav, model):
    import mlx_whisper
    r = mlx_whisper.transcribe(wav, path_or_hf_repo=model or MLX_REPO, language=None, word_timestamps=False,
                               condition_on_previous_text=False, verbose=None)
    return r.get("language")


def _detect_faster(wav, model):
    from faster_whisper import WhisperModel
    m = WhisperModel(model or FW_MODEL, device="auto", compute_type="auto")
    _segs, info = m.transcribe(wav, language=None)          # segments are lazy: only the detection runs
    return getattr(info, "language", None)


_DETECT = {"mlx": _detect_mlx, "faster": _detect_faster}


def detect_language(path, backend="auto", model=None, seconds=30.0):
    """Spoken language of ``path`` (ISO code such as "en" / "zh") from its first ``seconds`` of audio, or None
    when the backend cannot tell (the cloud backends) or detection fails. Local backends only."""
    be = _backend(backend)
    fn = _DETECT.get(be)
    if fn is None:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "lang16.wav")
            media.run([media.ffmpeg_bin(), "-v", "error", "-y", "-i", str(path), "-t", f"{seconds:.1f}", "-vn",
                       "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
            lang = fn(wav, model)
        return str(lang).lower() if lang else None
    except Exception:  # noqa: BLE001 - detection is a hint; the caller falls back to its default
        return None


def _persona_language():
    try:
        from .config import persona
        return (persona().get("creator") or {}).get("language") or "zh"
    except Exception:  # noqa: BLE001
        return "zh"


def default_language():
    """The language ``transcribe(language=None)`` uses: $VSTUDIO_ASR_LANGUAGE (e.g. "auto" = detect per file, what
    the desk app sets for a creator without a persona), else persona ``creator.language``, else "zh"."""
    env = (os.environ.get("VSTUDIO_ASR_LANGUAGE") or "").strip().lower()
    return env or _persona_language()


_RUN = {"mlx": _run_mlx, "faster": _run_faster, "openai": _run_openai, "openai-compatible": _run_compatible}


def loop_score(segs):
    """How much of a transcript is a whisper repetition loop ("区区区区", "uffle uffle ..."): the number
    of characters inside runs of one 1-6 char unit repeated >= 5 times."""
    txt = re.sub(r"\s+", "", "".join(s.get("text", "") for s in segs))
    return sum(len(m.group(0)) for m in re.finditer(r"(.{1,6}?)\1{4,}", txt))


# ------------------------------------------------------------------ cache
def file_hash(path, chunk=1 << 20):
    """sha1 of a file's bytes (streamed)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _cache_path(path):
    """Sidecar ``<path>.asr.json``; when the media's folder is not writable (read-only source drive,
    another user's Downloads) fall back to ``<cache>/asr/`` (``config.cache_dir``: ``$VSTUDIO_CACHE``, default
    ~/.cache/video-studio; a file left in the legacy ~/.cache/vstudio/asr/ is still used)."""
    from .config import cache_dir, cache_dirs
    side = path + ".asr.json"
    if os.access(os.path.dirname(os.path.abspath(side)) or ".", os.W_OK) or os.path.exists(side):
        return side
    name = hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:16] + ".asr.json"
    for d in cache_dirs("asr"):
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    return os.path.join(cache_dir("asr"), name)


def _cache_key(fh, language, prompt, word_timestamps, model, be, hst):
    return hashlib.sha1(json.dumps([CACHE_VERSION, fh, language, prompt, word_timestamps, model, be] +
                                   ([hst] if hst != 2.0 else []) +
                                   ([server_config()["base_url"]] if be == "openai-compatible" else []),
                                   ensure_ascii=False).encode()).hexdigest()


def _hst(path, skip_silence):
    if skip_silence == "auto":
        try:
            skip_silence = 2.0 if media.duration(path) > HALLUCINATION_SILENCE_AUTO_MIN_S else None
        except Exception:  # noqa: BLE001
            skip_silence = None
    return float(skip_silence) if skip_silence else None


def _index_path(fh, create=False):
    from .config import cache_dir, cache_dirs
    return os.path.join(cache_dir("asr", "index") if create else cache_dirs("asr", "index")[0], f"{fh}.json")


def index_sidecar(cp, fh=None, keys=None):
    """Record that sidecar ``cp`` holds transcripts of audio whose bytes hash to ``fh`` (default: its entries'
    ``source_sha1``; for a sidecar written before those existed pass ``fh=file_hash(<the audio>)``), so ``cached``
    finds them from any copy of the same audio - the planner's own extraction of a recording a CLI run transcribed
    from ``work/audio.wav`` has the same bytes. ``keys``: only these entries. -> the hashes indexed."""
    try:
        with open(cp, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError):
        return []
    by = {}
    for k, v in (store.items() if isinstance(store, dict) else []):
        h = fh or (v.get("source_sha1") if isinstance(v, dict) else None)
        if h and isinstance(v, dict) and v.get("segments") and (keys is None or k in keys):
            by.setdefault(h, []).append(k)
    cp = os.path.abspath(cp)
    for h, ks in by.items():
        ip = _index_path(h, create=True)
        try:
            with open(ip, encoding="utf-8") as f:
                rows = json.load(f).get("entries") or []
        except (OSError, ValueError, AttributeError):
            rows = []
        rows = [r for r in rows if isinstance(r, dict) and r.get("sidecar") and not
                (r["sidecar"] == cp and r.get("key") in ks)] + [dict(sidecar=cp, key=k) for k in ks]
        try:
            with open(ip + ".tmp", "w", encoding="utf-8") as f:
                json.dump(dict(entries=rows[-20:]), f, ensure_ascii=False)
            os.replace(ip + ".tmp", ip)
        except OSError:
            pass
    return list(by)


def _lang_ok(entry, language):
    return language == "auto" or entry.get("language") in (language, None)


def cached(path, language=None, prompt=None, word_timestamps=True, model=None, backend="auto", fh=None,
           fix_terms=True, drop_hallucinated=True):
    """The transcript of ``path`` already in an ASR cache, or None. Never transcribes and never writes. Looks at
    ``path``'s own sidecar (the exact settings' entry first, else the newest entry recorded for the same bytes,
    ``source_sha1``), then at the content index (``index_sidecar``): a sidecar anywhere that was made from the same
    bytes. Another prompt / model still heard the same words; another language did not. ``fh``: the file's
    ``file_hash`` when the caller has it."""
    if not fh and not os.path.isfile(path):
        return None
    if language is None:
        language = default_language()
    fh = fh or file_hash(path)
    hit = None
    cp = _cache_path(path)
    store = _read_store(cp)
    if store:
        try:
            key = _cache_key(fh, language, prompt, word_timestamps, model, _backend(backend), _hst(path, "auto"))
        except RuntimeError:                               # no backend here: only the content match can hit
            key = None
        hit = store.get(key) if key else None
        if not isinstance(hit, dict):
            same = [v for v in store.values() if isinstance(v, dict) and v.get("segments") and
                    v.get("source_sha1") == fh and _lang_ok(v, language)]
            hit = same[-1] if same else None
    if hit is None:
        try:
            with open(_index_path(fh), encoding="utf-8") as f:
                rows = json.load(f).get("entries") or []
        except (OSError, ValueError, AttributeError):
            rows = []
        for r in reversed(rows):
            v = (_read_store(r.get("sidecar")) or {}).get(r.get("key")) if isinstance(r, dict) else None
            if isinstance(v, dict) and v.get("segments") and _lang_ok(v, language):
                hit = v
                break
    return _finish(hit, None, fix_terms, drop_hallucinated) if hit else None


def _read_store(cp):
    if not cp or not os.path.exists(cp):
        return None
    try:
        with open(cp, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError):
        return None
    return store if isinstance(store, dict) else None


# ------------------------------------------------------------------ public
# hallucination_silence_threshold skips "silent" stretches where whisper might loop; on real short
# talking-head speech it also silently DROPS spoken phrases (a 1-2 s clause after a pause, measured on
# an 87 s recording: 6 words lost in 2 places, which the tight cut then removed as "pauses"). So
# "auto" only enables it for long recordings (meetings / lectures), where the loops actually happen.
HALLUCINATION_SILENCE_AUTO_MIN_S = 600.0


def transcribe(path, language=None, prompt=None, word_timestamps=True, model=None, backend="auto",
               cache=True, term_fixes=None, fix_terms=True, skip_silence="auto", drop_hallucinated=True,
               progress=None):
    """Transcribe audio/video ``path`` with word timestamps.

    Args:
      language: ISO code, or "auto" = detect it from the audio (local backends; else the persona's); default
        ``default_language()`` ($VSTUDIO_ASR_LANGUAGE, persona creator.language, else "zh").
      prompt: initial_prompt with domain terms (fixes English terms in Chinese speech).
      model: backend model id (mlx HF repo / faster-whisper size / openai model).
      backend: "auto" | "mlx" | "faster" | "openai" | "openai-compatible" (a self-hosted whisper server).
      cache: reuse/write the sidecar ``<path>.asr.json`` keyed by content hash + settings.
      term_fixes: call-site fixes passed to ``apply_term_fixes`` (dict literal or [[regex, repl]]).
      fix_terms: apply term fixes to segment and word text (word count/indices unchanged).
      skip_silence: whisper hallucination_silence_threshold in s; "auto" = 2 for recordings longer
        than 10 min, else off (it drops real phrases on short clips); None/0 = off.
      drop_hallucinated: run ``drop_hallucinations`` on the result (default True): segments whisper
        invents over music / silence ("字幕志愿者…", "请不吝点赞订阅…", "Thanks for watching") are
        removed and listed in ``tr["dropped"]``. False = raw whisper output.
      progress: ``fn(done_s, total_s)`` while a local backend decodes (not called on a cache hit).
    Returns dict: language, backend, text, segments (whisper shape: start, end, text, words[{word,
    start, end}]), words (flat [{"w", "t", "te"}], stripped). Zero-length repeated words (whisper's
    tail hallucination, talkinghead ``strict_pass``) are dropped before indexing.
    """
    from .batch.livestatus import heartbeat
    heartbeat("asr", message=os.path.basename(str(path)))          # desk 进行中 lane (no-op outside a job folder)
    if language is None:
        language = default_language()
    if not prompt and persona_terms():
        prompt = ", ".join(persona_terms())           # whisper hears her glossary words as she spells them
    be = _backend(backend)
    hst = _hst(path, skip_silence)
    key = fh = None
    if cache:
        fh = file_hash(path)
        key = _cache_key(fh, language, prompt, word_timestamps, model, be, hst)
        cp = _cache_path(path)
        if os.path.exists(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    store = json.load(f)
                if key in store:
                    return _finish(store[key], term_fixes, fix_terms, drop_hallucinated)
            except (OSError, ValueError):
                pass
    global _PROGRESS
    prev, _PROGRESS = _PROGRESS, progress
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "a16.wav")
            media.extract_wav(path, wav, sr=16000, channels=1)
            if language == "auto":
                language = detect_language(wav, be, model) or _persona_language()
            segs = _RUN[be](wav, language, prompt, word_timestamps, model, hst)
            if be not in ("openai", "openai-compatible") and loop_score(segs):
                # Temperature fallback (up to 1.0) on hard audio - short cut files, mumbles - can end in a
                # repetition loop over the whole clip; plain greedy decoding is usually clean there.
                _PROGRESS = None                           # a second pass: progress already said "all heard"
                alt = _RUN[be](wav, language, prompt, word_timestamps, model, hst, greedy=True)
                if loop_score(alt) < loop_score(segs):
                    segs = alt
    finally:
        _PROGRESS = prev
    raw = dict(language=language, backend=be, segments=segs)
    if cache:
        raw["source_sha1"] = fh                            # lets ``cached`` find it under other settings
        cp = _cache_path(path)
        store = {}
        if os.path.exists(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    store = json.load(f)
            except (OSError, ValueError):
                store = {}
        store[key] = raw
        try:
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False)
            index_sidecar(cp, fh, keys=[key])
        except OSError as e:   # never lose a finished transcription to a cache write
            print(f"asr: cache not written ({e})")
    return _finish(raw, term_fixes, fix_terms, drop_hallucinated)


def _finish(raw, term_fixes, fix_terms, drop_hallucinated=False):
    segs = json.loads(json.dumps(raw["segments"]))
    for s in segs:
        ws, keep = s.get("words") or [], []
        for k, w in enumerate(ws):
            if k and w["end"] - w["start"] < 0.02 and w["word"] == ws[k - 1]["word"]:
                continue
            keep.append(w)
        s["words"] = keep
        if fix_terms:
            s["text"] = apply_term_fixes(s["text"], term_fixes)
            for w in keep:
                lead = " " if w["word"][:1].isspace() else ""
                w["word"] = lead + apply_term_fixes(w["word"], term_fixes)
    out = dict(raw, segments=segs)
    out["text"] = "".join(s["text"] for s in segs).strip()
    out["words"] = words_of(out)
    return drop_hallucinations(out) if drop_hallucinated else out


# ------------------------------------------------------------------ hallucination filter
# Text whisper produces from its training captions when there is no speech (music beds, ride/park
# template music, room tone). STRONG = never a real spoken line: dropped wherever it appears in a
# segment. WEAK = could be said for real ("谢谢观看" at the end of a vlog): dropped only when the
# segment is essentially just that phrase AND the decoder was not confident about it.
HALLUCINATION_STRONG = [
    "字幕志愿者", "字幕志願者", "字幕提供", "字幕by", "字幕由amara", "字幕組", "中文字幕志愿者",
    "请不吝点赞", "請不吝點贊", "请不吝點讚", "點贊訂閱", "点赞订阅", "订阅转发", "訂閱轉發", "打赏支持", "打賞支持",
    "明镜与点点", "明鏡與點點", "優優獨播劇場", "优优独播剧场", "amaraorg",
    "subtitlesby", "subtitledby", "transcribedby", "captionsby", "translatedby", "subtitlesbytheamaraorgcommunity",
]
HALLUCINATION_WEAK = [
    "谢谢观看", "謝謝觀看", "感谢观看", "感謝觀看", "谢谢大家观看", "谢谢收看", "謝謝收看", "请订阅", "請訂閱",
    "thanksforwatching", "thankyouforwatching", "pleasesubscribe", "likeandsubscribe", "seeyounexttime",
    "thankyou", "byebye", "ご視聴ありがとうございました",
]


def _norm(text):
    return re.sub(r"[\W_]+", "", (text or "").lower())


def _seg_reason(seg, phrases, no_speech, logprob, compression, loops):
    """Why ``seg`` looks hallucinated (str), or None if it looks like real speech."""
    t = _norm(seg.get("text") or "".join(w.get("word", "") for w in seg.get("words") or []))
    if not t:
        return None
    for ph in phrases:
        if _norm(ph) and _norm(ph) in t:
            return f"phrase:{ph}"
    nsp, alp, cr = (seg.get(k) for k in _STATS)
    ps = [w.get("p") for w in seg.get("words") or [] if w.get("p") is not None]
    mean_p = sum(ps) / len(ps) if ps else None
    for ph in HALLUCINATION_WEAK:
        n = _norm(ph)
        if n and n in t and len(n) >= 0.6 * len(t):
            unsure = ((nsp is not None and nsp >= 0.2) or (alp is not None and alp < -0.5)
                      or (mean_p is not None and mean_p < 0.6)
                      or (nsp is None and alp is None and mean_p is None))
            if unsure:
                return f"phrase?:{ph}"
    if nsp is not None and alp is not None and nsp > no_speech and alp < logprob:
        return f"no_speech:{nsp:.2f}/logprob:{alp:.2f}"
    if cr is not None and cr > compression and (alp is None or alp < -0.5):
        return f"compression:{cr:.2f}"
    if loops and len(t) >= 10 and loop_score([dict(text=t)]) >= 0.5 * len(t):
        return "loop"
    return None


def drop_hallucinations(transcript, phrases=None, no_speech=0.6, logprob=-1.0, compression=2.4, loops=True):
    """Remove segments whisper invented over music / silence.

    A segment is dropped when (first match wins): its text contains a HALLUCINATION_STRONG phrase
    (or one of ``phrases``); it is essentially just a HALLUCINATION_WEAK phrase ("Thanks for watching",
    "谢谢观看") and the decoder was unsure (no_speech_prob >= 0.2, avg_logprob < -0.5 or mean word
    p < 0.6; no stats at all counts as unsure); whisper's own silence rule (no_speech_prob > no_speech
    AND avg_logprob < logprob); compression_ratio > compression with a weak avg_logprob; or a
    repetition loop (``loop_score``) covering >= half of a >= 10-char segment.

    ``transcript``: a ``transcribe`` dict (returns a copy with segments/text/words rebuilt and the
    removed ones in ``"dropped"`` [{start, end, text, reason}]) or a bare segment list (returns the
    kept list). Segments without confidence stats (old caches, other tools) are judged on text only.
    """
    segs = transcript["segments"] if isinstance(transcript, dict) else (transcript or [])
    extra = HALLUCINATION_STRONG + list(phrases or [])
    keep, dropped = [], []
    for s in segs:
        why = _seg_reason(s, extra, no_speech, logprob, compression, loops)
        if why:
            dropped.append(dict(start=s.get("start"), end=s.get("end"), text=(s.get("text") or "").strip(),
                                reason=why))
        else:
            keep.append(s)
    if not isinstance(transcript, dict):
        return keep
    out = dict(transcript, segments=keep)
    out["text"] = "".join(s.get("text", "") for s in keep).strip()
    out["words"] = words_of(out)
    out["dropped"] = list(transcript.get("dropped") or []) + dropped
    return out


def has_speech(transcript, min_words=4):
    """True when ``transcript`` (``transcribe`` dict, segment list, or flat [{"w",...}] word list)
    still has >= ``min_words`` words after ``drop_hallucinations`` - i.e. the clip really talks and
    its audio/captions are worth keeping. A music-only clip that whisper "heard" as
    "字幕志愿者…" returns False. CJK words count per whisper token (usually 1-2 characters)."""
    if not transcript:
        return False
    if isinstance(transcript, list) and isinstance(transcript[0], dict) and "w" in transcript[0]:
        words = [w for w in transcript if (w.get("w") or "").strip()]
        segs = [dict(text="".join(w["w"] for w in words),
                     words=[dict(word=w["w"], start=w.get("t", 0), end=w.get("te", 0)) for w in words])]
        return len(drop_hallucinations(segs)) > 0 and len(words) >= min_words
    t = drop_hallucinations(transcript)
    segs = t["segments"] if isinstance(t, dict) else t
    return len(words_of(segs)) >= min_words


def to_hyperframes_transcript(tr, path=None, words=None):
    """Transcript (``transcribe`` result, or a flat [{"w","t","te"}] list) -> the HyperFrames
    ``transcript.json`` word shape [{"text", "start", "end", "id": "w0"}, ...]; written to ``path``
    (UTF-8 JSON, indent 2) if given. Returns the list. From explainer ``transcribe.py``."""
    ws = words if words is not None else (tr["words"] if isinstance(tr, dict) else tr)
    out = [{"text": w["w"], "start": w["t"], "end": w["te"], "id": f"w{k}"} for k, w in enumerate(ws)]
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    return out


def words_of(transcript):
    """Flatten a whisper-shaped transcript to [{"w", "t", "te"}] (stripped text, empty words dropped).
    From promo-recut ``common.words_of`` / talkinghead ``strict_pass`` word list."""
    segs = transcript["segments"] if isinstance(transcript, dict) else transcript
    return [dict(w=w["word"].strip(), t=round(float(w["start"]), 3), te=round(float(w["end"]), 3))
            for s in segs for w in (s.get("words") or []) if w["word"].strip()]


def _latin_end(text):
    return bool(text) and text[-1].isascii() and text[-1].isalnum()


def join_subwords(words, max_gap=0.02):
    """Whisper-shaped words of ONE segment ([{"word", "start", "end", "probability"?}], raw text with whisper's
    leading space) -> the same with sub-word tokens joined into words. Chinese / Japanese transcripts are split per
    token, so an English term inside Chinese speech comes out as "s" "au" "ce," or "E" "mb" "ed" "ded": a Latin token
    with no leading space that starts exactly where the Latin token before it ends (whisper's sub-tokens of one word
    touch; separate words written without spaces keep a gap) belongs to the same word. A token after CJK
    text, or with whisper's leading space, starts a new word; nothing else changes."""
    out = []
    for w in words or []:
        raw = str(w.get("word", ""))
        core = raw.strip()
        prev = out[-1] if out else None
        if (prev is not None and core and not raw[:1].isspace() and core[0].isascii() and (core[0].isalnum() or core[0] == "'")
                and _latin_end(str(prev.get("word", "")).strip())
                and float(w.get("start", 0)) - float(prev.get("end", 0)) <= max_gap):
            prev["word"] = str(prev["word"]) + core
            prev["end"] = w.get("end", prev.get("end"))
            for k in ("probability", "p"):
                if w.get(k) is not None and prev.get(k) is not None:
                    prev[k] = min(float(prev[k]), float(w[k]))
            continue
        out.append(dict(w))
    return out


_TOK = lambda s: re.findall(r"[a-z0-9]+|[⺀-鿿豈-﫿]", s.lower().replace("’", "").replace("'", ""))


def align_script(texts, words, dur):
    """Map script cues onto ASR word timestamps (difflib on normalised tokens; CJK per character).

    Args: texts = [cue text, ...] in reading order; words = [{"w","t","te"}] or [(word, start, end)];
    dur = audio length (bounds interpolation). Unmatched tokens are interpolated between neighbours.
    Returns [{"start", "end"}] per cue. From photo-story ``tts.align`` (TTS narration timing).
    """
    ws = [(w["w"], w["t"], w["te"]) if isinstance(w, dict) else tuple(w) for w in words]
    exp, owner = [], []
    for ci, t in enumerate(texts):
        for tok in _TOK(t):
            exp.append(tok); owner.append(ci)
    got, gt = [], []
    for wd, s, e in ws:
        for tok in _TOK(wd):
            got.append(tok); gt.append((s, e))
    tmap = [None] * len(exp)
    for blk in difflib.SequenceMatcher(None, exp, got, autojunk=False).get_matching_blocks():
        for j in range(blk.size):
            tmap[blk.a + j] = gt[blk.b + j]
    for j in range(len(exp)):
        if tmap[j] is None:
            prev = next((tmap[x][1] for x in range(j - 1, -1, -1) if tmap[x]), 0.0)
            nxt = next((tmap[x][0] for x in range(j + 1, len(exp)) if tmap[x]), dur)
            tmap[j] = (prev, max(prev, nxt))
    out = []
    for ci in range(len(texts)):
        idx = [j for j in range(len(exp)) if owner[j] == ci]
        if idx:
            out.append(dict(start=round(tmap[idx[0]][0], 3), end=round(tmap[idx[-1]][1], 3)))
        else:
            t = out[-1]["end"] if out else 0.0
            out.append(dict(start=t, end=t))
    return out
