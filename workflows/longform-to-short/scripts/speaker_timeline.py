#!/usr/bin/env python3
"""Speaker timeline from the meeting's embedded caption track.

Platform auto-captions mis-hear non-English speech as random English words, so the
TEXT is thrown away; only speaker labels + timestamps are kept. Labels are then
renamed through config.speakers.aliases so no real names reach any work file
(e.g. {"<name as shown in the meeting>": "Host"}). Labels are often misattributed:
decide who said what by content before cutting or pitch-shifting anyone.

Output speakers.json: [[t0, t1, "Host"], ...]
Usage: python3 speaker_timeline.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os
import re
from collections import Counter

import _lfc

cfg, _ = _lfc.load(description=__doc__)
srt = cfg.get("speakers.srt", "rec_subs.srt")
label_re = re.compile(cfg.get("speakers.label_regex", r"\(([^)]+)\)"))
aliases = cfg.get("speakers.aliases", {})
merge_gap = cfg.get("speakers.merge_gap", 8)

events = []
if os.path.exists(srt):
    ts = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)")
    unknown = {}
    for b in open(srt, encoding="utf-8", errors="replace").read().split("\n\n"):
        m = ts.search(b)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        for raw in label_re.findall(b):
            if raw not in aliases:
                unknown.setdefault(raw, f"Speaker {chr(65 + len(unknown))}")
            events.append([t0, t1, aliases.get(raw) or unknown[raw]])
    if unknown:
        # print only the anonymous placeholders; map real labels in config.speakers.aliases
        print(f"{len(unknown)} label(s) without an alias were anonymised as "
              f"{sorted(set(unknown.values()))}; add them to speakers.aliases to name roles")
else:
    print(f"no {srt}; speakers.json will be empty and blocks show '?'")

events.sort()
merged = []
for t0, t1, spk in events:
    if merged and merged[-1][2] == spk and t0 - merged[-1][1] <= merge_gap:
        merged[-1][1] = t1
    else:
        merged.append([t0, t1, spk])
_lfc.dump_json(merged, "speakers.json", indent=0)

tot = Counter()
for t0, t1, s in merged:
    tot[s] += t1 - t0
print("turns:", dict(Counter(s for *_, s in merged)))
print("airtime_min:", {k: round(v / 60, 1) for k, v in tot.items()})
