#!/usr/bin/env python3
"""Step 7a: subtitles for the cut, mapped through timeline.json.

Each whisper segment overlapping a timeline item is retimed by that item's speed and
final offset (cards skipped; the hook clip gets its own subs naturally). Segments clipped by
a cut keep only the words inside the item. Term fixes (see subs_lib) + filler-only lines dropped.

Writes subs.srt (soft subs for platform CC upload, also copied to <out>/subs.srt) and subs.ass
(burn-in) including 勘误 notes: config.subtitles.errata [{"src": [t0,t1], "text": "勘误：..."}]
shown as a top-of-frame note while that source window plays.

Usage: python3 build_subs.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os
import shutil

import _lfc
import subs_lib as S

cfg, _ = _lfc.load(description=__doc__)
MAX_LINE = cfg.get("subtitles.max_line", 22)  # CJK chars per line on a 16:9 frame
W, H = cfg.get("render.size", [1920, 1080])
clean = S.make_clean(cfg)
w = _lfc.load_json("audio16k.json")
timeline = _lfc.load_json("timeline.json")

events = []
for it in timeline:
    if it["kind"] == "card":
        continue
    t0, t1, sp, f0 = it["t0"], it["t1"], it["speed"], it["final_t0"]
    for seg in w["segments"]:
        if seg["end"] <= t0 or seg["start"] >= t1:
            continue
        raw = seg["text"]
        if (seg["start"] < t0 - 0.05 or seg["end"] > t1 + 0.05) and seg.get("words"):
            raw = "".join(wd["word"] for wd in seg["words"]
                          if wd["start"] >= t0 - 0.05 and wd["end"] <= t1 + 0.05)
        txt = clean(raw)
        if not txt or S.FILLER_ONLY.fullmatch(txt):
            continue
        a = f0 + (max(seg["start"], t0) - t0) / sp
        b = f0 + (min(seg["end"], t1) - t0) / sp
        if b - a < 0.25:
            continue
        n = MAX_LINE * 2
        chunks = [txt] if len(txt) <= n else [txt[i:i + n] for i in range(0, len(txt), n)]
        step = (b - a) / len(chunks)
        events += [(a + i * step, a + (i + 1) * step, c) for i, c in enumerate(chunks)]

events.sort()
for i in range(1, len(events)):
    pa, pb, pt = events[i - 1]
    if events[i][0] < pb:
        events[i - 1] = (pa, max(pa + 0.2, events[i][0] - 0.05), pt)

with open("subs.srt", "w", encoding="utf-8") as f:
    for i, (a, b, t) in enumerate(events, 1):
        f.write(f"{i}\n{S.srt_ts(a)} --> {S.srt_ts(b)}\n{t}\n\n")
shutil.copy("subs.srt", os.path.join(cfg.out, "subs.srt"))

notes = []
for e in cfg.get("subtitles.errata", []):
    a, b = _lfc.map_src(timeline, e["src"][0], "fwd"), _lfc.map_src(timeline, e["src"][1], "back")
    if a is None or b is None or b <= a:
        print(f"WARN errata at src {e['src']} falls outside the cut; skipped")
        continue
    notes.append((a, b, e["text"]))

with open("subs.ass", "w", encoding="utf-8") as f:
    f.write(S.ass_header(cfg.get("subtitles.font_name") or _lfc.font_family_name("cjk-bold"), W, H))
    for a, b, t in events:
        f.write(f"Dialogue: 0,{S.ass_ts(a)},{S.ass_ts(b)},Sub,,0,0,0,,{S.wrap(t, MAX_LINE)}\n")
    for a, b, t in notes:
        f.write(f"Dialogue: 1,{S.ass_ts(a)},{S.ass_ts(b)},Note,,0,0,0,,{t}\n")
print(f"events={len(events)} notes={len(notes)} -> subs.srt subs.ass "
      + " ".join(f"note@{_lfc.mmss(a)}" for a, _, _ in notes))
