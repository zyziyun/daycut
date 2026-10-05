"""Speech recognition with word timestamps, cached, plus the term-fix pass.

    from vstudio import asr
    tr = asr.transcribe("talk.mp4", language="zh", prompt="Claude Code, HyperFrames")
    tr["words"]     -> [{"w": "我们", "t": 1.02, "te": 1.31}, ...]       (flat, term-fixed)
    tr["segments"]  -> whisper shape [{start, end, text, words: [{word, start, end}]}]
    asr.apply_term_fixes("cloud code 很好用")                        -> persona + generic fixes

Backends, first available wins (or pass backend=): mlx_whisper (Apple Silicon) -> faster_whisper ->
OpenAI ``whisper-1`` (only if OPENAI_API_KEY is set in the environment; the key is never read
from files). Settings that matter on long/noisy speech: no conditioning on previous text and a
hallucination-silence threshold, else whisper loops ("嗯嗯嗯") over silence.

Results are cached in a sidecar ``<input>.asr.json`` keyed by the file's content hash + settings,
so re-running a pipeline never re-transcribes unchanged audio.

Unified from talkinghead ``asr.transcribe``, promo-recut ``common.transcribe/words_of``, call-clips
``transcribe.run_mlx/run_faster`` + ``build_subs.fix/TERM_FIX``, longform ``transcribe.py`` +
``subs_lib.term_fixes/GENERIC_TERM_FIXES/make_clean``, photo-story ``tts.Transcriber/align``.
"""
import difflib
import hashlib
import json
import os
import re
import tempfile

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
]


# ------------------------------------------------------------------ term fixes
def _persona_fixes():
    try:
        from .config import persona
        return ((persona().get("subtitles") or {}).get("term_fixes")) or {}
    except Exception:
        return {}


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
    if clean:
        text = re.sub(r"嗯{2,}", "", text)
        text = re.sub(r"(.)\1{4,}", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


# ------------------------------------------------------------------ backends
def _backend(name="auto"):
    if name != "auto":
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
                       "or set OPENAI_API_KEY for whisper-1")


def _run_mlx(wav, language, prompt, word_timestamps, model):
    import mlx_whisper
    r = mlx_whisper.transcribe(wav, path_or_hf_repo=model or MLX_REPO, language=language,
                               word_timestamps=word_timestamps, initial_prompt=prompt or None,
                               condition_on_previous_text=False,
                               hallucination_silence_threshold=2 if word_timestamps else None, verbose=None)
    return [dict(start=s["start"], end=s["end"], text=s["text"],
                 words=[dict(word=w["word"], start=w["start"], end=w["end"], p=w.get("probability"))
                        for w in s.get("words", []) or []]) for s in r["segments"]]


def _run_faster(wav, language, prompt, word_timestamps, model):
    from faster_whisper import WhisperModel
    m = WhisperModel(model or FW_MODEL, device="auto", compute_type="auto")
    segs, _ = m.transcribe(wav, language=language, word_timestamps=word_timestamps, initial_prompt=prompt or None,
                           condition_on_previous_text=False,
                           hallucination_silence_threshold=2 if word_timestamps else None, vad_filter=False)
    return [dict(start=s.start, end=s.end, text=s.text,
                 words=[dict(word=w.word, start=w.start, end=w.end, p=w.probability) for w in (s.words or [])])
            for s in segs]


def _run_openai(wav, language, prompt, word_timestamps, model):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    from openai import OpenAI
    # whisper-1 caps uploads at 25 MB: send 32 kbps mono mp3 (~14 MB per hour)
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "a.mp3")
        media.run(["ffmpeg", "-y", "-i", wav, "-ac", "1", "-ar", "16000", "-b:a", "32k", mp3])
        with open(mp3, "rb") as f:
            r = OpenAI(api_key=key).audio.transcriptions.create(
                model=model or "whisper-1", file=f, language=language, prompt=prompt or None,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"] if word_timestamps else ["segment"])
    words = [dict(word=" " + w.word if not re.match(r"[⺀-￿]", w.word or "") else w.word,
                  start=w.start, end=w.end) for w in (getattr(r, "words", None) or [])]
    out = []
    for s in getattr(r, "segments", None) or []:
        ws = [w for w in words if s.start - 0.01 <= (w["start"] + w["end"]) / 2 < s.end + 0.01]
        out.append(dict(start=s.start, end=s.end, text=s.text, words=ws))
    return out


_RUN = {"mlx": _run_mlx, "faster": _run_faster, "openai": _run_openai}


# ------------------------------------------------------------------ cache
def file_hash(path, chunk=1 << 20):
    """sha1 of a file's bytes (streamed)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _cache_path(path):
    return path + ".asr.json"


# ------------------------------------------------------------------ public
def transcribe(path, language=None, prompt=None, word_timestamps=True, model=None, backend="auto",
               cache=True, term_fixes=None, fix_terms=True):
    """Transcribe audio/video ``path`` with word timestamps.

    Args:
      language: ISO code (default persona creator.language, else "zh").
      prompt: initial_prompt with domain terms (fixes English terms in Chinese speech).
      model: backend model id (mlx HF repo / faster-whisper size / openai model).
      backend: "auto" | "mlx" | "faster" | "openai".
      cache: reuse/write the sidecar ``<path>.asr.json`` keyed by content hash + settings.
      term_fixes: call-site fixes passed to ``apply_term_fixes`` (dict literal or [[regex, repl]]).
      fix_terms: apply term fixes to segment and word text (word count/indices unchanged).
    Returns dict: language, backend, text, segments (whisper shape: start, end, text, words[{word,
    start, end}]), words (flat [{"w", "t", "te"}], stripped). Zero-length repeated words (whisper's
    tail hallucination, talkinghead ``strict_pass``) are dropped before indexing.
    """
    if language is None:
        try:
            from .config import persona
            language = (persona().get("creator") or {}).get("language") or "zh"
        except Exception:
            language = "zh"
    be = _backend(backend)
    key = None
    if cache:
        key = hashlib.sha1(json.dumps([CACHE_VERSION, file_hash(path), language, prompt, word_timestamps,
                                       model, be], ensure_ascii=False).encode()).hexdigest()
        cp = _cache_path(path)
        if os.path.exists(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    store = json.load(f)
                if key in store:
                    return _finish(store[key], term_fixes, fix_terms)
            except (OSError, ValueError):
                pass
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a16.wav")
        media.extract_wav(path, wav, sr=16000, channels=1)
        segs = _RUN[be](wav, language, prompt, word_timestamps, model)
    raw = dict(language=language, backend=be, segments=segs)
    if cache:
        cp = _cache_path(path)
        store = {}
        if os.path.exists(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    store = json.load(f)
            except (OSError, ValueError):
                store = {}
        store[key] = raw
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False)
    return _finish(raw, term_fixes, fix_terms)


def _finish(raw, term_fixes, fix_terms):
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
    return out


def words_of(transcript):
    """Flatten a whisper-shaped transcript to [{"w", "t", "te"}] (stripped text, empty words dropped).
    From promo-recut ``common.words_of`` / talkinghead ``strict_pass`` word list."""
    segs = transcript["segments"] if isinstance(transcript, dict) else transcript
    return [dict(w=w["word"].strip(), t=round(float(w["start"]), 3), te=round(float(w["end"]), 3))
            for s in segs for w in (s.get("words") or []) if w["word"].strip()]


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
