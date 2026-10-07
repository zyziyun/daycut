#!/usr/bin/env python3
"""Step 7a: subtitles for the cut, mapped through timeline.json.

Each whisper segment overlapping a timeline item is retimed by that item's speed and
final offset (cards skipped; the hook clip gets its own subs naturally). A piece shorter than 0.25 s (a word
kept between two cuts) joins the neighbouring caption instead of being dropped: it is still said. Segments clipped by
a split or cut keep the words whose midpoint is inside the item (a word straddling a zoom / pitch split is
assigned to one piece, never dropped). Filler-only lines are dropped.

Term fixes (vstudio.asr.apply_term_fixes), in order:
  1. config subtitles.term_fixes   [[regex, replacement], ...]   per-video mis-hearings (regex)
  2. persona subtitles.term_fixes  {"heard": "meant"}            creator-wide (LITERAL, case-insensitive)
  3. vstudio.asr.GENERIC_TERM_FIXES                              common tech-talk ASR misses

Writes subs.srt (soft subs for platform CC upload, also copied to <out>/subs.srt) and subs.ass
(burn-in, vstudio.subs.ass_write, CJK-aware wrap at subtitles.max_line) including 勘误 notes:
config.subtitles.errata [{"src": [t0,t1], "text": "勘误：..."}] shown as a top-of-frame note while
that source window plays. Also writes cues.json (vstudio.subs.Cue dicts, final seconds) next to subs.srt:
the caption track for re-burning per platform (`python -m vstudio.export ... --cues work/cues.json`) and for
the vertical slices (make_vertical.py re-lays it into each profile's caption box). Per horizontal target also
cues.<platform>-<orientation>.json, already split to fit that profile's caption box (use these with export).

With explicit platform targets the first horizontal target's caption profile sets the burn-in: bottom margin
from vstudio.platform.caption_box, chars per line from its max_chars_zh (unless subtitles.max_line is set).

Usage: python3 build_subs.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os
import re
import shutil

import _lfc
from vstudio import asr, subs

FILLER_ONLY = re.compile(r"[嗯啊哦呃哈OK好的。，\s]*")
# a latin word (with the punctuation glued to it) or one other character, plus the spaces after it
WORD_TOK = re.compile(r"[A-Za-z0-9'’.\-]+[^\sA-Za-z0-9\u2e80-\U0010ffff]*\s*|\S\s*|\s+")

cfg, _ = _lfc.load(description=__doc__)
PROF = _lfc.primary_horizontal(cfg)       # None unless targets were set explicitly
MAX_LINE = cfg.get("subtitles.max_line", PROF.caption["max_chars_zh"] if PROF else 22)  # CJK chars per line
W, H = cfg.get("render.size", list(PROF.size) if PROF else [1920, 1080])
MARGIN_V = None
if PROF:
    from vstudio import platform as PF
    MARGIN_V = int(round((PROF.h - PF.caption_box(PROF)[3]) * H / PROF.h))
FIXES = [list(f) for f in (cfg.get("subtitles.term_fixes") or [])]
w = _lfc.load_json("audio16k.json")
timeline = _lfc.load_json("timeline.json")
tm = _lfc.timemap(timeline)

def words_in(words, t0, t1):
    """Words of a segment that belong to the item [t0, t1): each word goes to the piece holding its MIDPOINT,
    so a word straddling a zoom / pitch / freeze split lands in exactly one of the two pieces (never dropped,
    never doubled); words whose midpoint is inside a real cut are gone with the cut."""
    return [wd for wd in words if t0 <= (wd["start"] + wd["end"]) / 2 < t1]


events, short = [], []
for it in timeline:
    if it["kind"] == "card":
        continue
    t0, t1, sp, f0 = it["t0"], it["t1"], it["speed"], it["final_t0"]
    for seg in w["segments"]:
        if seg["end"] <= t0 or seg["start"] >= t1:
            continue
        raw, s0, s1 = seg["text"], seg["start"], seg["end"]
        if (seg["start"] < t0 or seg["end"] > t1) and seg.get("words"):
            mine = words_in(seg["words"], t0, t1)
            if not mine:
                continue
            raw = "".join(wd["word"] for wd in mine)
            s0, s1 = max(mine[0]["start"], t0), min(mine[-1]["end"], t1)
        txt = asr.apply_term_fixes(raw, FIXES)
        if not txt or FILLER_ONLY.fullmatch(txt):
            continue
        a = f0 + (max(s0, t0) - t0) / sp
        b = f0 + (min(s1, t1) - t0) / sp
        if b - a < 0.25:                 # too short to read alone (a word left between two cuts): it is still
            short.append((a, b, txt))    # SAID, so it joins the caption next to it below
            continue
        n = MAX_LINE * 2
        if re.search(r"[A-Za-z]{2}", txt):   # latin / mixed: measure by width, never cut inside a word
            chunks, cur = [], ""
            for tok in WORD_TOK.findall(txt):
                if cur.strip() and subs.text_width(cur + tok) > n and tok[0] not in "，。、！？；：,.!?;:)）】」』》…":
                    chunks.append(cur.strip()); cur = ""
                cur += tok
            if cur.strip():
                chunks.append(cur.strip())
        else:
            chunks = [txt] if len(txt) <= n else [txt[i:i + n] for i in range(0, len(txt), n)]
        step = (b - a) / len(chunks)
        events += [(a + i * step, a + (i + 1) * step, c) for i, c in enumerate(chunks)]

events.sort()


def _join(x, y):
    """``x`` then ``y``; latin words on both sides keep a space between them (the database, not thedatabase)."""
    x, y = x.rstrip(), y.lstrip()
    return x + (" " if re.search(r"[A-Za-z0-9,.!?;:]$", x) and re.match(r"[A-Za-z0-9]", y) else "") + y


OPENERS = ("另外", "然后", "所以", "但是", "而且", "因为", "就是", "那么", "还有", "或者", "如果")
for a, b, txt in sorted(short):           # captions match the audio: a short piece joins its neighbour (an
    prev = max((k for k, e in enumerate(events) if e[1] <= a + 0.05), key=lambda k: events[k][1], default=None)
    nxt = min((k for k, e in enumerate(events) if e[0] >= b - 0.05), key=lambda k: events[k][0], default=None)
    gp = a - events[prev][1] if prev is not None else 1e9       # opener like 另外 joins the words after it)
    gn = events[nxt][0] - b if nxt is not None else 1e9
    if min(gp, gn) > 1.0:
        events.append((a, max(b, a + 0.25), txt))
    elif nxt is not None and (gn < gp or txt.strip().startswith(OPENERS) and gn <= 0.5):
        e = events[nxt]
        events[nxt] = (a, e[1], _join(txt, e[2]))
    else:
        e = events[prev]
        events[prev] = (e[0], b, _join(e[2], txt))
    events.sort()
for i in range(1, len(events)):
    pa, pb, pt = events[i - 1]
    if events[i][0] < pb:
        events[i - 1] = (pa, max(pa + 0.2, events[i][0] - 0.05), pt)
cues = [subs.Cue(a, b, t) for a, b, t in events]

subs.srt_write(cues, "subs.srt")
_lfc.dump_json([c.to_dict() for c in cues], "cues.json")
for prof in _lfc.horizontal(_lfc.targets(cfg)[0]):
    # per-target caption track for `python -m vstudio.export --cues`: long cues split so each fits the profile
    import _vertical
    rc = _vertical.relayout_cues(cues, prof)
    _lfc.dump_json([c.to_dict() for c in rc], f"cues.{prof.name}-{prof.orientation}.json")
shutil.copy("subs.srt", os.path.join(cfg.out, "subs.srt"))

notes = []
for e in cfg.get("subtitles.errata", []):
    span = tm.map_span(e["src"][0], e["src"][1], tag="body")
    if not span:
        print(f"WARN errata at src {e['src']} falls outside the cut; skipped")
        continue
    notes.append((span[0], span[1], e["text"]))

font_name = cfg.get("subtitles.font_name") or subs.font_family("cjk-bold")
subs.ass_write(cues, "subs.ass", w=W, h=H, font_name=font_name, wrap=MAX_LINE, margin_v=MARGIN_V)
if notes:
    # 勘误 notes: a boxed top-centre "Note" style (vstudio.subs.ass_write only defines "Sub")
    k = H / 1080.0
    style = (f"Style: Note,{font_name},{int(38 * k)},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB0000000,"
             f"0,0,0,0,100,100,0,0,3,2,0,8,60,60,{int(36 * k)},1\n")
    ass = open("subs.ass", encoding="utf-8").read().replace("\n[Events]", style + "\n[Events]", 1)
    ass += "".join(f"Dialogue: 1,{subs.ass_ts(a)},{subs.ass_ts(b)},Note,,0,0,0,,{t}\n" for a, b, t in notes)
    open("subs.ass", "w", encoding="utf-8").write(ass)
print(f"events={len(events)} notes={len(notes)} -> subs.srt subs.ass "
      + " ".join(f"note@{_lfc.mmss(a)}" for a, _, _ in notes))
