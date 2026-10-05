#!/usr/bin/env python3
"""Step 2b: keep_list.json from reviewed block-ID ranges, cleaned by the shared speech-cleanup tool.

config.keep.ranges   [[a, z], ...] inclusive block ids to KEEP
config.keep.chapters {block_id: "chapter title"}  a chapter card goes before that block
Adjacent kept blocks with a gap <= keep.merge_gap merge into one segment (natural pacing);
larger gaps are cut. A chapter start always begins a new segment.

Every segment is a hand-written range, so its edges go through ``vstudio.cleanup.snap_range`` (start
before its first word's onset, end over its last word's real tail, never into a neighbouring dropped
word), widened by keep.pad_in / pad_out up to the neighbours, and its end through
``cleanup.extend_end`` (the 40 ms fade-out at the cut lands after the last word's tail). config.cuts
(hand-written word-level deletions) split a segment into sub-ranges that are snapped the same way.
Then ``cleanup.clean`` runs per sub-range (气口 squeezed, fillers / stammers / repeats removed;
profile = config cleanup.profile, else persona cleanup.profile, else standard) and the kept pieces
go into keep_list.json as ``keep`` (build_timeline.py turns each piece into a clip).

Creator-confirm loop (references/CLEANUP.md): one review sheet per episode (episodes.items chapter
ranges; one sheet for the whole cut without items) -> work/cleanup_review.ep<N>.md (+ cleanup.ep<N>.json).
Only AUTO edits are applied until the creator replies; put the reply in config
``cleanup.reply: {"<N>": "确认 3,5,9 / 保留 7"}`` (or a plain string when there is one sheet) or pass
``--reply N:"确认 3,5"`` and re-run. ``cleanup.enabled: false`` keeps the plain (snapped) segments.

Hook clips (hook.src, episodes.items[i].hook.src) are hand-written ranges too: snapped + end extended
over the last word at the hook speed -> work/hook_edges.json (read by build_timeline.py).

Usage: python3 build_keep_list.py work/config.py [--reply 2:"确认 3 / 保留 5"]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import json
import os

import _lfc
from vstudio import cleanup


def _extra(ap):
    ap.add_argument("--reply", action="append", default=[],
                    help='creator reply for one episode sheet, e.g. 2:"确认 3,5 / 保留 7" (N: omitted = sheet 1)')


cfg, ARGS = _lfc.load(description=__doc__, extra=_extra)
MERGE_GAP = cfg.get("keep.merge_gap", 1.5)
PAD_IN, PAD_OUT = cfg.get("keep.pad_in", 0.15), cfg.get("keep.pad_out", 0.25)
RANGES = cfg.get("keep.ranges") or sys.exit("config keep.ranges is empty; review blocks.txt first")
CHAPTERS = {int(k): v for k, v in (cfg.get("keep.chapters") or {}).items()}
CUTS = sorted((float(c[0]), float(c[1])) for c in cfg.get("cuts", []))
CLEAN = cfg.get("cleanup.enabled", True)
PROFILE = cfg.get("cleanup.profile")                  # None -> persona cleanup.profile -> standard
OVERRIDES = cfg.get("cleanup.overrides") or None
AUDIO = cfg.path_of(cfg.get("cleanup.audio", "audio16k.wav"))
LECTURE = _lfc.speed(cfg, "lecture", 1.2)
HOOK = _lfc.speed(cfg, "hook", 1.1)
FADE_OUT = 0.04                                       # render.py afade at a real cut

blocks = {b["id"]: b for b in _lfc.load_json("blocks.json")}
kept = [blocks[i] for a, z in RANGES for i in range(a, z + 1) if i in blocks]

segments = []
for b in kept:
    ch = CHAPTERS.get(b["id"])
    if segments and b["t0"] - segments[-1]["t1"] <= MERGE_GAP and not ch:
        segments[-1]["t1"] = b["t1"]
        segments[-1]["ids"].append(b["id"])
    else:
        segments.append({"t0": b["t0"], "t1": b["t1"], "ids": [b["id"]], "chapter": ch})

W = cleanup.load_words(_lfc.load_json("audio16k.json")) if os.path.exists("audio16k.json") else []
HAS_AUDIO = bool(W) and AUDIO and os.path.exists(AUDIO)
if not W:
    print("WARN no audio16k.json (transcribe.py): segment edges are not word-safe and no cleanup runs")
elif not HAS_AUDIO:
    print(f"WARN {AUDIO} missing: cleanup from whisper timing only (pauses never auto)")


def energy(ranges):
    return cleanup.energy_of(AUDIO, W, ranges, PROFILE, OVERRIDES) if HAS_AUDIO else None


def snap(t0, t1, en, pad_in=0.0, pad_out=0.0):
    """Hand-written keep range -> word-safe (a, b), widened by the pads but never into a neighbour word."""
    if not W:
        return max(0.0, t0 - pad_in), t1 + pad_out
    lo, hi = cleanup.word_limits(W, t0, t1)
    sa, sb = cleanup.snap_range(W, t0, t1, en)
    a = min(sa, max(t0 - pad_in, lo, 0.0))
    b = max(sb, min(t1 + pad_out, hi - 0.03))
    return a, b


def sub_ranges(a, b):
    """[a, b] minus config.cuts, each remaining piece re-snapped (the cut words go with the cut)."""
    out, cur = [], a
    for ca, cb in CUTS:
        if cb <= cur or ca >= b:
            continue
        if ca > cur:
            out.append((cur, ca))
        cur = max(cur, cb)
    if cur < b:
        out.append((cur, b))
    return out


# ------------------------------------------------------------------ episode groups (one review sheet each)
items = cfg.get("episodes.items") or []
chapter_no, group_of = 0, []
for s in segments:
    if s["chapter"]:
        chapter_no += 1
    g = 1
    for i, it in enumerate(items):
        first, last = it["chapters"]
        if first <= max(chapter_no, 1) <= last:
            g = i + 1
    group_of.append(g)

replies = cfg.get("cleanup.reply") or {}
if isinstance(replies, str):
    replies = {"1": replies}
replies = {str(k): v for k, v in replies.items()}
for r in ARGS.reply:
    n, sep, txt = r.partition(":")
    if sep and n.strip().isdigit():
        replies[n.strip()] = txt
    else:
        replies["1"] = r

total_auto = total_conf = 0
for g in sorted(set(group_of)):
    segs = [s for s, gg in zip(segments, group_of) if gg == g]
    en = energy([(s["t0"] - PAD_IN, s["t1"] + PAD_OUT) for s in segs]) if W else None
    dec = cleanup.parse_reply(replies.get(str(g), ""))
    edits, ranges = [], []
    for s in segs:
        a, b = snap(s["t0"], s["t1"], en, PAD_IN, PAD_OUT)
        if W:
            b, _, info = cleanup.extend_end(W, en, a, b, FADE_OUT, LECTURE)
        s["t0"], s["t1"] = round(a, 3), round(b, 3)
        pieces = []
        for k, (ra, rb) in enumerate(sub_ranges(a, b)):
            if k or rb < b:                                   # a hand cut made this edge: snap it too
                ra, rb = snap(ra, rb, en) if W else (ra, rb)
                ra, rb = max(ra, a), min(rb, b)
            if rb - ra < 0.06:
                continue
            if not (CLEAN and W):
                pieces.append((round(ra, 3), round(rb, 3)))
                continue
            res = cleanup.clean(W, None, ra, rb, PROFILE, OVERRIDES, energy=en,
                                id_offset=len(edits))      # episode-wide numbering for the review sheet
            edits += res["edits"]
            win = [w for w in W if ra <= (w["t"] + w["te"]) / 2 <= rb]
            pieces += cleanup.keep_segments(res["edits"], [(ra, rb)], dec["approve"], dec["keep"],
                                            dec["all_confirm"], words=win)
            ranges.append((ra, rb))
        s["keep"] = [[round(x, 3), round(y, 3)] for x, y in pieces]
        s["episode"] = g
    if not edits:
        continue
    lang = cleanup.detect_language(W)
    edl = dict(source=dict(path=os.path.basename(cfg.src)), profile=cleanup.settings(PROFILE, OVERRIDES)["profile"],
               language=lang, ranges=[list(r) for r in ranges], edits=edits, episode=g,
               reply=replies.get(str(g), ""))
    _lfc.dump_json(edl, f"cleanup.ep{g}.json")
    cleanup.review_sheet(edl, f"cleanup_review.ep{g}.md")
    ids = cleanup.applied_ids(edits, dec["approve"], dec["keep"], dec["all_confirm"])
    n_conf = sum(e["action"] == "confirm" for e in edits)
    total_auto += len(ids)
    total_conf += n_conf
    print(f"ep{g}: {len(ids)} cleanup edits applied, {n_conf} to confirm -> cleanup_review.ep{g}.md"
          + (f"  (reply: {replies[str(g)]})" if replies.get(str(g)) else ""))

# ------------------------------------------------------------------ hook clips (hand-written ranges)
hooks = {}
for key, h in [("hook", cfg.get("hook.src"))] + [(f"ep{i + 1}", (it.get("hook") or {}).get("src"))
                                                   for i, it in enumerate(items)]:
    if not h or not W:
        continue
    en = energy([(h[0], h[1])])
    a, b = cleanup.snap_range(W, float(h[0]), float(h[1]), en)
    b, _, info = cleanup.extend_end(W, en, a, b, FADE_OUT, HOOK)
    hooks[key] = {"src": [float(h[0]), float(h[1])], "edge": [round(a, 3), round(b, 3)]}
    if info:
        print(f"  {key}: {info}")
if hooks:
    _lfc.dump_json(hooks, "hook_edges.json")
elif os.path.exists("hook_edges.json"):
    os.remove("hook_edges.json")

_lfc.dump_json(segments, "keep_list.json")

total = sum(sum(b - a for a, b in s["keep"]) for s in segments)
span = sum(s["t1"] - s["t0"] for s in segments)
cur = 0.0
print(f"segments={len(segments)} total={total/60:.1f}min (cleanup -{span - total:.1f}s, before speed-up)"
      + (f"; {total_conf} edits wait for the creator's reply" if total_conf else ""))
for i, s in enumerate(segments):
    if s["chapter"]:
        print(f"  seg {i:>3}  {_lfc.mmss(cur)}  {s['chapter']}")
    cur += sum(b - a for a, b in s["keep"])
