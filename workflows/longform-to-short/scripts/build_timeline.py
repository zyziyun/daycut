#!/usr/bin/env python3
"""Step 5: master edit decision -> timeline.json.

Inputs: keep_list.json, crop_spans.json, zoom_windows.json (optional) + config:
  hook.src [t0,t1]              cold-open clip (source s), overlaid with hook_overlay.png
  cuts [[a,b,"why"],...]        word-level deletions inside kept segments (video+audio)
  freezes [[a,b],...]           hold the frame before an accidental flash, audio keeps rolling
  pitches.windows [[a,b],...]   pitch-shift a participant's voice (anonymise), video untouched
  pitches.semitones (-3)
  speeds.lecture/demo/hook      (persona longform.speed.* -> 1.2 / 1.3 / 1.1)
  zoom.box [w,h]                source window for code zoom cut-ins (smaller = stronger push-in)
  share [x0,y0,x1,y1]           main share region (zoom clamp + fallback crop)
  demo.enabled/rec/keep_idx     swap video of those keep-list segments for a re-recorded demo
  cards.dur (1.6)

Item kinds: card {png,dur,title} | clip {t0,t1,speed,crop,demo_slice,overlay,cont_in,cont_out,
pitch?} | freeze (clip + still_at). cont_in/cont_out mark audio-continuous joins (zoom/pitch
splits) so render skips the afade there and the cut-in is seamless.

Usage: python3 build_timeline.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import _lfc
from vstudio import media

cfg, _ = _lfc.load(description=__doc__)
LECTURE = _lfc.speed(cfg, "lecture", 1.2)
DEMO = _lfc.speed(cfg, "demo", 1.3)
HOOK = _lfc.speed(cfg, "hook", 1.1)
SHARE = cfg.get("share")
DEFAULT_CROP = cfg.get("default_crop") or (
    [SHARE[2] - SHARE[0], SHARE[3] - SHARE[1], SHARE[0], SHARE[1]] if SHARE else None)
ZW, ZH = cfg.get("zoom.box", [736, 336])
CARD_DUR = cfg.get("cards.dur", 1.6)
CUTS = [tuple(c[:2]) for c in cfg.get("cuts", [])]
FREEZES = [tuple(f[:2]) for f in cfg.get("freezes", [])]
PITCHES = [tuple(p[:2]) for p in cfg.get("pitches.windows", [])]
PITCH_RATIO = 2 ** (cfg.get("pitches.semitones", -3) / 12.0)
DEMO_ON = bool(cfg.get("demo.enabled") and cfg.get("demo.rec"))
DEMO_IDX = list(cfg.get("demo.keep_idx", [])) if DEMO_ON else []

keep = _lfc.load_json("keep_list.json")
spans = _lfc.load_json("crop_spans.json") if os.path.exists("crop_spans.json") else []
zooms = _lfc.load_json("zoom_windows.json") if os.path.exists("zoom_windows.json") else []


def subtract_cuts(t0, t1):
    pieces = [(t0, t1)]
    for ca, cb in CUTS:
        nxt = []
        for a, b in pieces:
            if cb <= a or ca >= b:
                nxt.append((a, b))
                continue
            if a < ca:
                nxt.append((a, ca))
            if cb < b:
                nxt.append((cb, b))
        pieces = nxt
    return [(a, b) for a, b in pieces if b - a > 0.15]


def crop_for(t):
    for sp in spans:
        if sp["t0"] <= t < sp["t1"] and sp["crop"]:
            return sp["crop"]
    return DEFAULT_CROP


def zoom_crop(z):
    x0, y0, x1, y1 = SHARE
    x = min(max(z["cx"] - ZW // 2, x0), x1 - ZW)
    y = min(max(z["cy"] - ZH // 2, y0), y1 - ZH)
    return [ZW, ZH, int(x), int(y)]


def split_windows(t0, t1):
    """Yield (a, b, mark); mark None | ('zoom', z) | ('freeze', fa) | ('pitch', None)."""
    cuts, marks = [t0, t1], []
    for z in zooms:
        a, b = max(t0, z["t0"]), min(t1, z["t1"])
        if b - a > 3:
            cuts += [a, b]
            marks.append((a, b, ("zoom", z)))
    for fa, fb in FREEZES:
        a, b = max(t0, fa), min(t1, fb)
        if b - a > 0.3:
            cuts += [a, b]
            marks.append((a, b, ("freeze", fa)))
    for pa, pb in PITCHES:
        a, b = max(t0, pa), min(t1, pb)
        if b - a > 0.2:
            cuts += [a, b]
            marks.append((a, b, ("pitch", None)))
    cuts = sorted(set(cuts))
    for a, b in zip(cuts, cuts[1:]):
        hits = [m for (ma, mb, m) in marks if ma <= a and b <= mb]
        yield a, b, hits


timeline = []
hook = cfg.get("hook.src")
if hook:
    timeline.append({"kind": "clip", "t0": hook[0], "t1": hook[1], "speed": HOOK,
                     "crop": crop_for((hook[0] + hook[1]) / 2), "demo_slice": None,
                     "overlay": "hook_overlay.png", "hook": True, "cont_in": False, "cont_out": False})

rec_dur = media.duration(cfg.path_of(cfg.get("demo.rec"))) if DEMO_ON else 0.0
rec_cursor = float(cfg.get("demo.rec_in", 0.0))
chapter_no = 0
for i, seg in enumerate(keep):
    if seg.get("chapter"):
        chapter_no += 1
        timeline.append({"kind": "card", "png": f"cards/card_{chapter_no:02d}.png",
                         "dur": CARD_DUR, "title": seg["chapter"]})
    if i in DEMO_IDX:
        pcs = subtract_cuts(seg["t0"], seg["t1"])
        total = sum(b - a for a, b in pcs)
        if i == DEMO_IDX[-1] and len(DEMO_IDX) > 1 and cfg.get("demo.align_last_to_end", True):
            rec_cursor = max(0.0, rec_dur - total)  # end the demo exactly on the recording's end
        for j, (a, b) in enumerate(pcs):
            timeline.append({"kind": "clip", "t0": round(a, 2), "t1": round(b, 2), "speed": DEMO,
                             "crop": None, "demo_slice": [round(rec_cursor, 3)], "overlay": None,
                             "cont_in": j > 0, "cont_out": j < len(pcs) - 1})
            rec_cursor += b - a
        continue
    pieces = []
    for a, b in subtract_cuts(seg["t0"], seg["t1"]):
        pieces.extend(split_windows(a, b))
    for j, (a, b, hits) in enumerate(pieces):
        it = {"kind": "clip", "t0": round(a, 2), "t1": round(b, 2), "speed": LECTURE,
              "crop": crop_for((a + b) / 2), "demo_slice": None, "overlay": None,
              "cont_in": j > 0, "cont_out": j < len(pieces) - 1}
        for kind, val in hits:
            if kind == "zoom" and SHARE:
                it["crop"] = zoom_crop(val)
            elif kind == "freeze":
                it["kind"] = "freeze"
                it["still_at"] = val - 0.4  # frame just before the flash
            elif kind == "pitch":
                it["pitch"] = PITCH_RATIO
        if it["crop"] is None:
            sys.exit(f"no crop for {a:.1f}s: set config.share or default_crop")
        timeline.append(it)

cur, chapters = 0.0, []
for it in timeline:
    it["final_t0"] = round(cur, 3)
    if it["kind"] == "card":
        chapters.append((cur, it["title"]))
        cur += it["dur"]
    else:
        cur += (it["t1"] - it["t0"]) / it["speed"]
_lfc.dump_json(timeline, "timeline.json")
print(f"items={len(timeline)} total={cur/60:.2f}min  speeds lecture={LECTURE} demo={DEMO} hook={HOOK}")
for t, title in chapters:
    print(f"  {_lfc.mmss(t)}  {title}")
