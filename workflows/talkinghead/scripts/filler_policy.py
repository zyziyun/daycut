"""Compatibility shim. The filler policy (confidence tiers, the CONFIRM list, the post-cut content check) moved
into the ONE shared speech-cleanup tool, ``vstudio.cleanup`` (references/CLEANUP.md): detection, scoring and
the auto / confirm / keep tiers are ``cleanup.detect``; the lost-word check is ``cleanup.content_check`` /
``cleanup.verify``. Nothing in the repo imports this module any more; it only keeps old notebooks working.

  content_check(expected, got, fillers=())  -> cleanup.content_check
  split_tiers(edits)                        -> (auto, confirm, keep) cleanup edits
  print_flags(flags, label="")
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from vstudio import cleanup  # noqa: E402

HESITATION = cleanup.HESITATION
SOFT = cleanup.SOFT


def content_check(expected, got, fillers=(), min_chars=2):
    """Lost / changed content between the words that should remain and a fresh ASR of the cut."""
    fl = (set(fillers) | HESITATION) if fillers else None
    return cleanup.content_check(expected, got, fillers=fl, min_chars=min_chars)


def split_tiers(edits):
    """cleanup edits -> (auto, confirm, keep) lists by their ``action``."""
    return tuple([e for e in edits if e.get("action") == a] for a in ("auto", "confirm", "keep"))


def print_flags(flags, label=""):
    if not flags:
        print(f"content check{label}: OK - every kept content word is still in the cut")
        return
    print(f"content check{label}: {len(flags)} span(s) to listen to (missing words = a cut ate speech):")
    for f in flags:
        extra = f"  (cut ASR heard '{f['got']}')" if f["got"] else ""
        print(f"  ! {f['kind']:<8} @{f.get('t', f.get('t_src', 0.0)):7.2f}s  '{f['text']}'{extra}")
