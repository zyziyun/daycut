"""Auto-trim / editor-cut profiles for call-clips.

``classic`` (DEFAULT, restored): the call-clips editor defaults from the original workflow.
  pause   silence > 0.75 s with no word midpoint inside -> cut, keep 0.30 s (0.15 s each side)
  editor  when an editor pass is applied (``extra_cuts``), pauses > 0.50 s are cut too, keeping 0.25 s
  edges   restart / repeat / filler / editor cuts snap BACKWARD to the quietest 20 ms frame within
          0.15 s before each edge (the cut never reaches into the next kept word's onset)
``word``: what ``vstudio.cut.find_cuts`` does (the phase-2 behaviour): pauses > 0.60 s keep 0.36 s,
  edges snapped to the quietest frame between the neighbouring words' midpoints.

Choose per recording with clips.json ``"cut_profile"``, per run with ``--cut-profile``, or per creator
with persona ``call_clips.cut_profile``. Restart / repeat / filler detection (Mandarin FILLERS /
EMPHASIS lists) is shared with vstudio.cut in both profiles.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio import cut as C
from vstudio.config import persona

PROFILES = {
    "classic": dict(pause_min=0.75, pause_keep=0.30, editor_pause_min=0.50, editor_pause_keep=0.25,
                    snap="back", snap_reach=0.15),
    "word": dict(pause_min=C.PAUSE_MIN, pause_keep=2 * C.PAUSE_EDGE, snap="word"),
}
DEFAULT = "classic"


def default_profile():
    return (persona().get("call_clips") or {}).get("cut_profile", DEFAULT)


def find_cuts(audio, segs, lo, hi, extra=None, profile=None):
    """Cut intervals [[a, b, why], ...] in source seconds inside [lo, hi] for ``profile``."""
    name = profile or default_profile()
    if name not in PROFILES:
        sys.exit(f"cut profile {name!r}: one of {', '.join(PROFILES)}")
    if name == "word":
        return C.find_cuts(audio, segs, lo, hi, extra)
    P = PROFILES[name]
    editor = bool(extra)
    pmin = P["editor_pause_min"] if editor else P["pause_min"]
    edge = (P["editor_pause_keep"] if editor else P["pause_keep"]) / 2
    cuts = []
    AW = C.all_words(segs)
    for a, b in audio.silences(lo, hi):
        if b - a < pmin:
            continue
        if any(a < (w["s"] + w["e"]) / 2 < b for w in AW if w["e"] > a - 1 and w["s"] < b + 1):
            continue
        ca, cb = a + edge, b - edge
        if cb - ca >= 0.2:
            cuts.append((ca, cb, "pause"))

    inside = [s for s in segs if s["start"] >= lo - 0.05 and s["end"] <= hi + 0.05]
    for s in inside:
        if C.norm(s["text"]) in C.FILLERS:
            cuts.append((s["start"], s["end"], f"filler:{C.norm(s['text'])}"))
    for A, B in zip(inside, inside[1:]):
        ta, tb = C.norm(A["text"]), C.norm(B["text"])
        if len(ta) >= 2 and tb.startswith(ta) and B["start"] - A["end"] < 1.5:
            cuts.append((A["start"], B["start"], f"restart:{ta}"))
    W = C.words_in(segs, lo, hi)
    i = 0
    while i < len(W):
        hit = None
        for n in range(1, 7):
            if i + 2 * n > len(W):
                break
            u1 = "".join(w["t"] for w in W[i:i + n])
            u2 = "".join(w["t"] for w in W[i + n:i + 2 * n])
            if u1 == u2 and 2 <= len(u1) <= 10 and u1 not in C.EMPHASIS \
                    and W[i + n]["s"] - W[i + n - 1]["e"] < 1.2:
                if n == 1 and W[i]["seg"] != W[i + n]["seg"]:
                    continue
                hit = n
        if hit:
            n, k = hit, i + hit
            unit = "".join(w["t"] for w in W[i:i + n])
            while k + n <= len(W) and "".join(w["t"] for w in W[k:k + n]) == unit:
                k += n
            cuts.append((W[i]["s"], W[k - n]["s"], "repeat:" + unit))
            i = k
        else:
            i += 1

    def snap(t):
        return audio.snap_back(t, P["snap_reach"])

    snapped = []
    kept_onsets = [b for a, b, why in cuts if why.startswith(("repeat", "restart"))]
    for a, b, why in (extra or []):
        if any(abs(a - k) < 0.05 for k in kept_onsets):
            continue
        if lo <= a < b <= hi:
            a, b = max(snap(a), lo + 0.05), min(snap(b), hi - 0.05)
            if b - a >= 0.12:
                snapped.append([a, b, "edit:" + why[:40]])
    for a, b, why in cuts:
        if why != "pause":
            a, b = snap(a), snap(b)
        a, b = max(a, lo + 0.05), min(b, hi - 0.05)
        if b - a >= C.MIN_CUT:
            snapped.append([a, b, why])
    snapped.sort()
    merged = []
    for c in snapped:
        if merged and c[0] <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], c[1])
            merged[-1][2] += "+" + c[2]
        else:
            merged.append(c)
    return merged
