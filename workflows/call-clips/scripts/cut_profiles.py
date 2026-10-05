"""Auto-trim for call-clips = the shared speech-cleanup tool (``vstudio.cleanup``, references/CLEANUP.md).

No detection or cut logic lives here any more: each keep-window goes through
``cleanup.clean(words, audio, lo, hi, profile)`` (气口 squeezed, fillers / stammers / repeats /
restarts found, word-safe edges), or - when the creator reviewed a sheet - through the decisions of a
``cleanup analyze --ranges`` EDL (``find_disfluencies.py``; clips.json ``"cleanup_edl"`` +
``"cleanup_reply"``). Editor cuts (``extra_cuts``: ``[onset of first dropped word, onset of next kept
word, why]``) go through ``cleanup.clean(extra=)`` / ``cleanup.snap_cuts`` (word-safe ``snap_cut``): a cut never
ends inside a kept word and never starts before the previous kept word's sounding end.

Profiles are the cleanup profiles; the old call-clips names stay as aliases:
  classic -> gentle    (was: pauses > 0.75 s keep 0.30 s; now gentle: > 0.80 s, kept 0.35-0.70 s,
                        breaths kept, auto only from confidence 0.92) - DEFAULT, as before
  word    -> standard  (was: pauses > 0.60 s keep 0.36 s; now standard: > 0.45 s, kept 0.18-0.40 s)
  gentle | standard | tight  as in references/CLEANUP.md

Choose per recording with clips.json ``"cut_profile"``, per run with ``--cut-profile``, per creator with
persona ``call_clips.cut_profile`` (else persona ``cleanup.profile``, else classic = gentle).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio import cleanup
from vstudio.config import persona

ALIASES = {"classic": "gentle", "word": "standard"}
PROFILES = {**{k: k for k in cleanup.PROFILES}, **ALIASES}       # every accepted name -> cleanup profile
DEFAULT = "classic"


def default_profile():
    p = persona()
    return (p.get("call_clips") or {}).get("cut_profile") or (p.get("cleanup") or {}).get("profile") or DEFAULT


def resolve(name=None):
    """call-clips / cleanup profile name -> cleanup profile name."""
    name = name or default_profile()
    if name not in PROFILES:
        sys.exit(f"cut profile {name!r}: one of {', '.join(PROFILES)}")
    return PROFILES[name]


def words_of(segs):
    """Whisper segments (or any transcript shape) -> cleanup word dicts."""
    return cleanup.load_words(segs)


def energy(audio, words, ranges=None, profile=None):
    """Calibrated ``cleanup.Energy`` from a wav path (or an Energy already made); None stays None."""
    if audio is None or isinstance(audio, cleanup.Energy):
        return audio
    return cleanup.energy_of(audio, words, ranges, resolve(profile))


def editor_cut(words, en, a, b, pad=None):
    """An editor cut [a, b] -> word-safe (a', b') or None: ``cleanup.snap_cut`` (the words whose midpoint is
    inside go; never into the previous word's sounding end or the next kept word's onset)."""
    return cleanup.snap_cut(words, en, a, b, pad)


def editor_cuts(words, en, extra, lo, hi):
    """Editor cuts touching [lo, hi], word-safe: [[a, b, "edit: why"], ...] (``cleanup.snap_cuts``)."""
    return cleanup.snap_cuts(words, en, extra, [(lo, hi)])


def window(words, en, lo, hi, extra=None, profile=None, edits=None, approve=(), keep=(), all_confirm=False):
    """One keep-window -> dict(keep=[(a, b)], cuts=[[a, b, why]], edits). ``edits``: the window's edits from a
    reviewed EDL (creator decisions ``approve`` / ``keep`` / ``all_confirm`` by EDL id); None = a fresh
    ``cleanup.clean`` with only its AUTO edits applied."""
    if edits is None:
        res = cleanup.clean(words, None, lo, hi, resolve(profile), energy=en, extra=extra or ())
        return dict(keep=res["keep"], cuts=sorted(res["cuts"]), edits=res["edits"])
    edits = [e for e in edits if e["t1"] > lo and e["t0"] < hi]
    ed = editor_cuts(words, en, extra, lo, hi)
    win = [w for w in words if lo <= (w["t"] + w["te"]) / 2 <= hi]
    kp = cleanup.keep_segments(edits, [(lo, hi)], approve, keep, all_confirm, extra=ed, words=win)
    cuts = sorted(cleanup.as_cuts(edits, approve, keep, all_confirm) + ed)
    return dict(keep=kp, cuts=cuts, edits=edits)


def find_cuts(audio, segs, lo, hi, extra=None, profile=None):
    """Cut intervals [[a, b, why], ...] (source s) inside [lo, hi]: ``cleanup.clean(...)["cuts"]`` (AUTO
    edits of ``profile``) + the word-safe editor cuts. audio: wav path or ``cleanup.Energy``."""
    W = words_of(segs)
    return window(W, energy(audio, W, [(lo, hi)], profile), lo, hi, extra, profile)["cuts"]
