"""One transcript per source recording, shared by ``plan-segments`` and the batch ``asr`` stage.

Keyed by the source file's content hash (``vstudio.asr.file_hash``) + language / prompt / backend, stored under
``<cache>/transcripts/`` (``vstudio.config.cache_dir()``). ``plan-segments`` transcribes a recording once; the batch
planned from its draft then finds the same transcript instead of running whisper again.
"""
import json
import os

from .util import read_json, sha1_json, write_json


def _root():
    from vstudio.config import cache_dir
    return cache_dir("transcripts")


def _key(sha1, language=None, prompt=None, backend=None):
    return sha1_json([sha1, language or None, prompt or None, (backend or "auto")], 24)


def lookup(sha1, language=None, prompt=None, backend=None):
    """-> (path, transcript) or (None, None)."""
    if not sha1:
        return None, None
    try:
        from vstudio.config import cache_dirs
        roots = cache_dirs("transcripts")
    except ImportError:
        roots = [_root()]
    for root in roots:
        p = os.path.join(root, _key(sha1, language, prompt, backend) + ".json")
        tr = read_json(p)
        if tr:
            return p, tr
    return None, None


def save(sha1, transcript, language=None, prompt=None, backend=None):
    p = os.path.join(_root(), _key(sha1, language, prompt, backend) + ".json")
    try:
        write_json(p, transcript)
    except OSError:
        return None
    return p


def load_any(path):
    """A transcript file: whisper / vstudio.asr dict, a flat word list, or a ``vstudio.asr`` cache file
    ({hash: transcript}) -> the transcript (the newest entry of a cache file)."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and not any(k in d for k in ("segments", "words", "text")):
        vals = [v for v in d.values() if isinstance(v, dict) and ("segments" in v or "words" in v)]
        if vals:
            return vals[-1]
    return d


# --------------------------------------------------------------------------- words of a finished cut, without ASR
def job_dir_of(path, depth=5):
    """The batch job folder a stage file belongs to (``jobs/<id>/<stage>/...``: the nearest parent holding
    ``job.json`` and an ``apply`` stage) -> path or None."""
    d = os.path.dirname(os.path.abspath(path))
    for _ in range(depth):
        if os.path.isfile(os.path.join(d, "job.json")) and os.path.isdir(os.path.join(d, "apply")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None


def _sidecar_words(path):
    s = read_json(path) if path and os.path.isfile(path) else None
    if not isinstance(s, dict):
        return None, None
    W = [w for w in s.get("words") or [] if isinstance(w, dict) and str(w.get("w", "")).strip()
         and w.get("t") is not None and w.get("te") is not None]
    return W, float(s.get("duration") or 0)


def mapped_words(path, duration=None, tol=0.35):
    """Word timings of a speech-pipeline cut (the export / master of a batch job), WITHOUT hearing it again.

    The ``apply`` stage already re-timed the source transcript onto the cut (``<part>.cleanup.json`` -> ``words``,
    cut seconds); ``compose`` played the hook (at ``hook_speed``) then the body (at ``speed``). This replays that:
    [{"w","t","te"}] on ``path``'s timeline, or None when ``path`` is not a pipeline cut, the sidecars are gone,
    or the cut's length does not match ``duration`` within ``tol`` seconds (a shorter platform variant, a file
    edited since) - the caller then transcribes as before."""
    jd = job_dir_of(path)
    if not jd:
        return None
    job = read_json(os.path.join(jd, "job.json")) or {}
    p = job.get("params") if isinstance(job.get("params"), dict) else {}
    try:
        s = float(p.get("speed") or 1.0)
        hs = float(p.get("hook_speed") or s)
    except (TypeError, ValueError):
        return None
    if s <= 0 or hs <= 0:
        return None
    out, t = [], 0.0
    hook, hdur = _sidecar_words(os.path.join(jd, "apply", "hook.cleanup.json"))
    body, bdur = _sidecar_words(os.path.join(jd, "apply", "body.cleanup.json"))
    if body is None:
        return None
    if hook is not None and hdur:
        out += [dict(w=str(w["w"]).strip(), t=round(float(w["t"]) / hs, 3), te=round(float(w["te"]) / hs, 3))
                for w in hook]
        t = hdur / hs
    out += [dict(w=str(w["w"]).strip(), t=round(t + float(w["t"]) / s, 3), te=round(t + float(w["te"]) / s, 3))
            for w in body]
    total = t + (bdur or 0) / s
    if duration and total and abs(float(duration) - total) > tol:
        return None
    out.sort(key=lambda w: w["t"])
    return out or None
