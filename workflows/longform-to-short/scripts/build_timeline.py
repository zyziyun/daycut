#!/usr/bin/env python3
"""Step 5: master edit decision -> timeline.json.

Inputs: keep_list.json (each segment's cleaned ``keep`` pieces from build_keep_list.py: 气口 / filler / repeat
cuts and config.cuts already applied, word-safe), hook_edges.json (word-safe hook ranges, optional),
crop_spans.json, zoom_windows.json (optional) + config:
  hook.src [t0,t1]              cold-open clip (source s), overlaid with hook_overlay.png
  episodes.items[i].hook        {"src": [t0,t1], "lines": [..]} per-episode cold open (slice jobs): placed
                                right before episode i's first chapter card (hook_overlay_ep<i+1>.png); the
                                episode then starts at its hook. Item 0's hook replaces hook.src.
  cuts [[a,b,"why"],...]        word-level deletions (applied by build_keep_list.py; only used here for an
                                old keep_list.json without ``keep`` pieces)
  freezes [[a,b],...]           hold the frame before an accidental flash, audio keeps rolling
  pitches.windows [[a,b],...]   pitch-shift a participant's voice (anonymise), video untouched
  pitches.semitones (-3)
  speeds.lecture/demo/hook      (persona longform.speed.* -> 1.2 / 1.3 / 1.1)
  zoom.box [w,h]                source window for code zoom cut-ins (smaller = stronger push-in)
  share [x0,y0,x1,y1]           main share region (zoom clamp + fallback crop)
  demo.enabled/rec/keep_idx     swap video of those keep-list segments for a re-recorded demo
  cards.dur (1.6)

Item kinds: card {png,dur,title} | clip {t0,t1,speed,crop,demo_slice,overlay,cont_in,cont_out,
pitch?} | freeze (clip + still_at). cont_in/cont_out mark audio-continuous joins (zoom/pitch/freeze
splits) so render skips the afade there and the cut-in is seamless; a join at a real cut (cleanup or
config.cuts) is not continuous, so it gets the 30 ms / 40 ms fades.

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
HOOK_EDGES = _lfc.load_json("hook_edges.json") if os.path.exists("hook_edges.json") else {}


def hook_src(key, src):
    """The word-safe hook range from build_keep_list.py (hook_edges.json) when it was made for this src."""
    e = HOOK_EDGES.get(key)
    if e and [float(x) for x in e["src"]] == [float(x) for x in src]:
        return e["edge"]
    return src


def keep_pieces(seg):
    """Kept source pieces of a keep-list segment: build_keep_list's cleaned ``keep`` (word-safe, nothing
    dropped), else the legacy subtraction of config.cuts."""
    if "keep" in seg:
        return [tuple(p) for p in seg["keep"]]
    return subtract_cuts(seg["t0"], seg["t1"])


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


def hook_item(src, overlay, ep=None, lines=None, key="hook"):
    src = hook_src(key, src)
    it = {"kind": "clip", "t0": src[0], "t1": src[1], "speed": HOOK,
          "crop": crop_for((src[0] + src[1]) / 2), "demo_slice": None,
          "overlay": overlay, "hook": True, "cont_in": False, "cont_out": False}
    if ep is not None:                       # per-episode cold open (episodes.items[].hook)
        it.update(hook_ep=ep, hook_lines=list(lines or []))
    return it


# per-episode hooks: episodes.items[i].hook {"src": [t0, t1], "lines": [l1, l2]} -> a cold open placed right
# before that episode's first chapter card (episode 1: at the very start, replacing the global hook)
EP_HOOKS = {}
for i, item in enumerate(cfg.get("episodes.items") or []):
    h = item.get("hook")
    if h and h.get("src"):
        EP_HOOKS[1 if i == 0 else int(item["chapters"][0])] = (i + 1, h)


def ep_hook(n, h):
    return hook_item(h["src"], f"hook_overlay_ep{n}.png", n, h.get("lines"), key=f"ep{n}")

timeline = []
hook = cfg.get("hook.src")
if 1 in EP_HOOKS:
    n, h = EP_HOOKS.pop(1)
    if hook:
        print("WARN episodes.items[0].hook replaces the global hook.src")
    timeline.append(ep_hook(n, h))
elif hook:
    timeline.append(hook_item(hook, "hook_overlay.png"))

rec_dur = media.duration(cfg.path_of(cfg.get("demo.rec"))) if DEMO_ON else 0.0
rec_cursor = float(cfg.get("demo.rec_in", 0.0))
chapter_no = 0
for i, seg in enumerate(keep):
    if seg.get("chapter"):
        chapter_no += 1
        if chapter_no in EP_HOOKS:
            n, h = EP_HOOKS.pop(chapter_no)
            timeline.append(ep_hook(n, h))
        timeline.append({"kind": "card", "png": f"cards/card_{chapter_no:02d}.png",
                         "dur": CARD_DUR, "title": seg["chapter"]})
    if i in DEMO_IDX:
        pcs = keep_pieces(seg)
        total = sum(b - a for a, b in pcs)
        if i == DEMO_IDX[-1] and len(DEMO_IDX) > 1 and cfg.get("demo.align_last_to_end", True):
            rec_cursor = max(0.0, rec_dur - total)  # end the demo exactly on the recording's end
        for j, (a, b) in enumerate(pcs):
            timeline.append({"kind": "clip", "t0": round(a, 2), "t1": round(b, 2), "speed": DEMO,
                             "crop": None, "demo_slice": [round(rec_cursor, 3)], "overlay": None,
                             "cont_in": False, "cont_out": False})
            rec_cursor += b - a
        continue
    pieces = []
    for a, b in keep_pieces(seg):
        sub = list(split_windows(a, b))
        # a split inside one kept piece is audio-continuous; the join between two pieces is a real cut
        pieces += [(x, y, hits, k > 0, k < len(sub) - 1) for k, (x, y, hits) in enumerate(sub)]
    for a, b, hits, cin, cout in pieces:
        it = {"kind": "clip", "t0": round(a, 3), "t1": round(b, 3), "speed": LECTURE,
              "crop": crop_for((a + b) / 2), "demo_slice": None, "overlay": None,
              "cont_in": cin, "cont_out": cout}
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
for c, (n, _) in EP_HOOKS.items():
    print(f"WARN episodes.items[{n - 1}].hook: chapter {c} not found; hook skipped")
_lfc.dump_json(timeline, "timeline.json")
print(f"items={len(timeline)} total={cur/60:.2f}min  speeds lecture={LECTURE} demo={DEMO} hook={HOOK}")
for t, title in chapters:
    print(f"  {_lfc.mmss(t)}  {title}")
