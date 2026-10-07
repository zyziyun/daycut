"""Speed ramps for screen recordings: real UI recordings wait (a plan being made, a render finishing). The idle
stretches play fast, the actions play at normal speed, so a 20 s take reads in 8 s without speeding up typing.

    spans = idle_spans(shot)                         # [(t0, t1)] frozen stretches (ffmpeg freezedetect), cached
    segs = segments(0.0, 18.3, spans, rate=1.0)     # [(m0, m1, rate)] covering [0, 18.3]
    segs = fit(segs, 8.0)                            # faster everywhere when the scene is shorter than the ramped take
    to_scene(segs, 13.7)                             # media second -> scene second
"""
import json
import os
import re
import subprocess

IDLE_RATE = 4.0          # how fast a frozen stretch plays
KEEP = 0.35              # of every frozen stretch, this much still plays at normal speed (the result is seen)
MIN_IDLE = 0.8           # shorter pauses are part of the action
NOISE = 0.00002          # freezedetect noise: UI typing changes few pixels, so the threshold is very low


def idle_spans(shot):
    """Frozen stretches of a video shot -> [(t0, t1)]; cached next to the file (``<file>.idle.json``)."""
    f = shot["file"]
    if shot.get("kind") == "image":
        return []
    if shot.get("idle") is not None:
        return [tuple(x) for x in shot["idle"]]
    cache = f + ".idle.json"
    try:
        with open(cache, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("mtime") == os.path.getmtime(f) and c.get("noise") == NOISE:
            return [tuple(x) for x in c["spans"]]
    except (OSError, ValueError):
        pass
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", f, "-vf", f"freezedetect=n={NOISE}:d={MIN_IDLE}",
                        "-map", "0:v", "-f", "null", "-"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"freezedetect failed on {f}: {r.stderr[-400:]}")
    starts = [float(x) for x in re.findall(r"freeze_start: ([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([0-9.]+)", r.stderr)]
    dur = float(shot.get("duration") or 0)
    spans = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else dur
        if spans and s - spans[-1][1] < 0.05:                 # freezedetect splits one long freeze in two
            spans[-1] = (spans[-1][0], e)
        else:
            spans.append((s, e))
    spans = [(round(a, 3), round(b, 3)) for a, b in spans if b - a >= MIN_IDLE]
    try:
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(dict(mtime=os.path.getmtime(f), noise=NOISE, spans=spans), fh)
    except OSError:
        pass
    return spans


def segments(a, b, spans, rate=1.0, idle_rate=IDLE_RATE):
    """[a, b] media seconds -> [(m0, m1, rate)]: idle spans (minus a KEEP lead-in) at idle_rate, the rest at rate."""
    out, t = [], a
    for s0, s1 in spans:
        s0, s1 = max(s0 + KEEP, a), min(s1, b)
        if s1 - s0 < 0.3:
            continue
        if s0 > t:
            out.append((t, s0, rate))
        out.append((s0, s1, max(rate, idle_rate)))
        t = s1
    if b > t:
        out.append((t, b, rate))
    return [(round(m0, 3), round(m1, 3), r) for m0, m1, r in out if m1 - m0 > 1e-3]


def length(segs):
    return sum((m1 - m0) / r for m0, m1, r in segs)


def fit(segs, dur):
    """Scale every rate up when the ramped take is longer than ``dur`` (never slows down)."""
    n = length(segs)
    if n <= dur or n <= 0:
        return segs
    k = n / dur
    return [(m0, m1, round(r * k, 4)) for m0, m1, r in segs]


def to_scene(segs, t):
    """Media second -> scene second (clamped to the segments)."""
    acc = 0.0
    for m0, m1, r in segs:
        if t <= m1:
            return acc + max(0.0, t - m0) / r
        acc += (m1 - m0) / r
    return acc
