"""Speech recognition with word timestamps, cached, plus the term-fix pass.

    from vstudio import asr
    tr = asr.transcribe("talk.mp4", language="zh", prompt="Claude Code, HyperFrames")
    tr["words"]     -> [{"w": "我们", "t": 1.02, "te": 1.31}, ...]       (flat, term-fixed)
    tr["segments"]  -> whisper shape [{start, end, text, words: [{word, start, end}]}]
    asr.apply_term_fixes("cloud code 很好用")                        -> persona + generic fixes

Backends, first available wins (or pass backend=): mlx_whisper (Apple Silicon) -> faster_whisper ->
OpenAI ``whisper-1`` (only if OPENAI_API_KEY is set in the environment; the key is never read
from files). Settings that matter on long/noisy speech: no conditioning on previous text and (for
recordings > 10 min only, see ``skip_silence``) a hallucination-silence threshold, else whisper loops
("嗯嗯嗯") over silence.

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
def resolve_backend(name="auto"):
    """The ASR backend ``transcribe(backend=name)`` would use: "mlx" | "faster" | "openai" (probes
    imports / OPENAI_API_KEY for "auto"; raises RuntimeError if none). Lets callers pick a
    per-backend model before transcribing."""
    return _backend(name)


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


def _run_mlx(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
    import mlx_whisper
    kw = {"temperature": 0.0} if greedy else {}
    r = mlx_whisper.transcribe(wav, path_or_hf_repo=model or MLX_REPO, language=language, **kw,
                               word_timestamps=word_timestamps, initial_prompt=prompt or None,
                               condition_on_previous_text=False,
                               hallucination_silence_threshold=hst if word_timestamps else None, verbose=None)
    return [dict(start=s["start"], end=s["end"], text=s["text"], **_stats(s),
                 words=[dict(word=w["word"], start=w["start"], end=w["end"], p=w.get("probability"))
                        for w in s.get("words", []) or []]) for s in r["segments"]]


def _run_faster(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
    from faster_whisper import WhisperModel
    m = WhisperModel(model or FW_MODEL, device="auto", compute_type="auto")
    kw = {"temperature": 0.0} if greedy else {}
    segs, _ = m.transcribe(wav, language=language, word_timestamps=word_timestamps, initial_prompt=prompt or None, **kw,
                           condition_on_previous_text=False,
                           hallucination_silence_threshold=hst if word_timestamps else None, vad_filter=False)
    return [dict(start=s.start, end=s.end, text=s.text, **_stats(s),
                 words=[dict(word=w.word, start=w.start, end=w.end, p=w.probability) for w in (s.words or [])])
            for s in segs]


def _run_openai(wav, language, prompt, word_timestamps, model, hst=None, greedy=False):
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
        out.append(dict(start=s.start, end=s.end, text=s.text, **_stats(s), words=ws))
    return out


_RUN = {"mlx": _run_mlx, "faster": _run_faster, "openai": _run_openai}


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
    another user's Downloads) fall back to ``$VSTUDIO_CACHE`` or ``~/.cache/vstudio/asr/``."""
    side = path + ".asr.json"
    if os.access(os.path.dirname(os.path.abspath(side)) or ".", os.W_OK) or os.path.exists(side):
        return side
    root = os.environ.get("VSTUDIO_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "vstudio")
    os.makedirs(os.path.join(root, "asr"), exist_ok=True)
    return os.path.join(root, "asr", hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:16] + ".asr.json")


# ------------------------------------------------------------------ public
# hallucination_silence_threshold skips "silent" stretches where whisper might loop; on real short
# talking-head speech it also silently DROPS spoken phrases (a 1-2 s clause after a pause, measured on
# an 87 s recording: 6 words lost in 2 places, which the tight cut then removed as "pauses"). So
# "auto" only enables it for long recordings (meetings / lectures), where the loops actually happen.
HALLUCINATION_SILENCE_AUTO_MIN_S = 600.0


def transcribe(path, language=None, prompt=None, word_timestamps=True, model=None, backend="auto",
               cache=True, term_fixes=None, fix_terms=True, skip_silence="auto", drop_hallucinated=True):
    """Transcribe audio/video ``path`` with word timestamps.

    Args:
      language: ISO code (default persona creator.language, else "zh").
      prompt: initial_prompt with domain terms (fixes English terms in Chinese speech).
      model: backend model id (mlx HF repo / faster-whisper size / openai model).
      backend: "auto" | "mlx" | "faster" | "openai".
      cache: reuse/write the sidecar ``<path>.asr.json`` keyed by content hash + settings.
      term_fixes: call-site fixes passed to ``apply_term_fixes`` (dict literal or [[regex, repl]]).
      fix_terms: apply term fixes to segment and word text (word count/indices unchanged).
      skip_silence: whisper hallucination_silence_threshold in s; "auto" = 2 for recordings longer
        than 10 min, else off (it drops real phrases on short clips); None/0 = off.
      drop_hallucinated: run ``drop_hallucinations`` on the result (default True): segments whisper
        invents over music / silence ("字幕志愿者…", "请不吝点赞订阅…", "Thanks for watching") are
        removed and listed in ``tr["dropped"]``. False = raw whisper output.
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
    if skip_silence == "auto":
        try:
            skip_silence = 2.0 if media.duration(path) > HALLUCINATION_SILENCE_AUTO_MIN_S else None
        except Exception:  # noqa: BLE001
            skip_silence = None
    hst = float(skip_silence) if skip_silence else None
    key = None
    if cache:
        key = hashlib.sha1(json.dumps([CACHE_VERSION, file_hash(path), language, prompt, word_timestamps,
                                       model, be] + ([hst] if hst != 2.0 else []),
                                      ensure_ascii=False).encode()).hexdigest()
        cp = _cache_path(path)
        if os.path.exists(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    store = json.load(f)
                if key in store:
                    return _finish(store[key], term_fixes, fix_terms, drop_hallucinated)
            except (OSError, ValueError):
                pass
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a16.wav")
        media.extract_wav(path, wav, sr=16000, channels=1)
        segs = _RUN[be](wav, language, prompt, word_timestamps, model, hst)
        if be != "openai" and loop_score(segs):
            # Temperature fallback (up to 1.0) on hard audio - short cut files, mumbles - can end in a
            # repetition loop over the whole clip; plain greedy decoding is usually clean there.
            alt = _RUN[be](wav, language, prompt, word_timestamps, model, hst, greedy=True)
            if loop_score(alt) < loop_score(segs):
                segs = alt
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
        try:
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False)
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
