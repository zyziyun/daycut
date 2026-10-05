#!/usr/bin/env python3
"""Align hand-paired bilingual cues to word timestamps; export cues.json + SRTs.

Usage:  python3 align_cues.py [--project .]
Reads   <project>/SCRIPT.md, subtitles/cues.txt, audio/transcript.json (from transcribe.py or
        `npx hyperframes transcribe`), audio/vo/offsets.json (from concat_vo.py),
        optional subtitles/display_rules.json
Writes  <project>/subtitles/cues.json, subtitles/en.srt, subtitles/zh.srt

cues.txt format (EN chunks of a line, concatenated, must equal that line's spoken text):
    ## 1
    Here's a strange fact. || 一个奇怪的事实：
    A language model with seventy billion parameters || 一个有 700 亿参数的语言模型，
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, bisect, difflib, json, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from display_en import display, load_rules
from vstudio import subs

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
root = pathlib.Path(ap.parse_args().project)
RULES = load_rules(str(root))

T = json.load(open(root / "audio/transcript.json"))
OFF = json.load(open(root / "audio/vo/offsets.json"))
spoken = {int(b.split()[0]): " ".join(l.strip() for l in b.split("\n") if l.startswith("    "))
          for b in re.split(r"\n## Line ", (root / "SCRIPT.md").read_text())[1:]}
norm = lambda s: [w for w in re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("'", "")).split() if w]

groups, cur = {}, None
for ln in open(root / "subtitles/cues.txt"):
    ln = ln.rstrip("\n")
    if ln.startswith("## "):
        cur = int(ln[3:]); groups[cur] = []
    elif "||" in ln and cur:
        ln = re.sub(r"\s+# check:.*$", "", ln)          # review flags left by pair_cues.py
        en, zh = [x.strip() for x in ln.split("||")]; groups[cur].append((en, zh))

cues = []
for n, st, dur in OFF:
    pairs = groups[n]
    if norm(" ".join(e for e, _ in pairs)) != norm(spoken[n]):
        raise SystemExit(f"line {n}: cues.txt EN chunks do not equal the spoken text in SCRIPT.md")
    tw = [w for w in T if st - 0.25 <= w["start"] < st + dur + 0.25]
    S = norm(spoken[n]); Tt = [" ".join(norm(w["text"])) for w in tw]
    sm = difflib.SequenceMatcher(None, S, Tt, autojunk=False)
    anc = {(0, 0), (len(S), len(tw))}
    for a, b, k in sm.get_matching_blocks():
        anc.update((a + j, b + j) for j in range(k))
    anc = sorted(anc); xs = [p for p, _ in anc]; ys = [q for _, q in anc]

    def t_at(i, end=False):
        k = max(0, min(bisect.bisect_right(xs, i) - 1, len(xs) - 2))
        x0, x1, y0, y1 = xs[k], xs[k + 1], ys[k], ys[k + 1]
        y = int(round(y0 + (y1 - y0) * ((i - x0) / (x1 - x0) if x1 > x0 else 0))) - (1 if end else 0)
        y = max(0, min(y, len(tw) - 1))
        return tw[y]["end"] if end else tw[y]["start"]

    i = 0
    for j, (en, zh) in enumerate(pairs):
        k = len(norm(en))
        s_ = st if j == 0 else t_at(i)
        e_ = t_at(i + k, end=True)
        cues.append({"line": n, "start": round(s_, 2), "end": round(max(e_, s_ + 0.8), 2),
                     "en": display(en, n, RULES), "spoken": en, "zh": zh})
        i += k

for a, b in zip(cues, cues[1:]):
    if b["start"] - a["end"] < 0.7:
        a["end"] = round(max(a["start"] + 0.5, b["start"] - 0.04), 2)
cues[-1]["end"] = round(cues[-1]["end"] + 1.5, 2)
json.dump(cues, open(root / "subtitles/cues.json", "w"), ensure_ascii=False, indent=1)
for lang in ("en", "zh"):
    p = root / f"subtitles/{lang}.srt"
    subs.srt_write([subs.Cue(c["start"], c["end"], c[lang]) for c in cues], str(p))
    with open(p, "a") as f:        # keep the trailing blank line the shipped example .srt files have
        f.write("\n")
print(f"{len(cues)} cues · max EN {max(len(c['en']) for c in cues)} chars · max ZH {max(len(c['zh']) for c in cues)} chars")
