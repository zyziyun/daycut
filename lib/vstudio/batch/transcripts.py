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
