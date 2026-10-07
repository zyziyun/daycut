#!/usr/bin/env python3
"""Slice whisper segments into clip-relative, term-fixed subtitle lines.

Also the home of fix(), the term-fix pass build_clips.py applies to every line
(a thin wrapper over ``vstudio.asr.apply_term_fixes``).

Usage (standalone, one plain range):
  build_subs.py work/audio16k.json --start 120 --end 180 --out work/test.subs.json [--config clips.json]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

from vstudio.asr import apply_term_fixes
from vstudio.subs import join_caption, text_width

# Call-site REGEX fixes for code-switched zh/en call audio, on top of vstudio.asr's generic list
# (reasoning, 思维导图, figure out, GitHub, ... live there). Where fixes come from, in order:
#   1. per recording: clips.json -> "term_fix": [[regex, replacement], ...]
#   2. this list (regex)
#   3. persona.local.yaml -> subtitles.term_fixes: {"heard": "meant"}  (LITERAL, case-insensitive;
#      a regex there no longer works -- move it to clips.json term_fix)
#   4. vstudio.asr.GENERIC_TERM_FIXES
# NB: \b does not work next to CJK (CJK counts as \w), so these are unanchored.
CALL_TERM_FIXES = [
    (r"engagent", "engaging"),
    (r"fake out", "figure out"),
    (r"Pendix", "Appendix"),
    (r"迭代迭到", "迭代得"),
    (r"文档reveal", "文档review"),
    (r"塞\s*off", "sign off"),
    (r"scate", "skip"),
    (r"体效", "提效"),
]


def fix(s, extra=None):
    """Term-fix one subtitle line. extra: per-recording [[regex, replacement], ...] (clips.json
    term_fix), applied first. Also collapses whitespace and drops 嗯嗯 / 5+ repeated-char runs."""
    return apply_term_fixes(s, extra=[tuple(x) for x in (extra or [])] + CALL_TERM_FIXES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("whisper_json")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=20, help="merge limit, CJK chars (latin counts 1/2)")
    ap.add_argument("--max-gap", type=float, default=0.45)
    ap.add_argument("--config", default=None, help="clips.json whose term_fix list to apply first")
    args = ap.parse_args()
    extra = json.load(open(args.config, encoding="utf-8")).get("term_fix") if args.config else None

    segs = [s for s in json.load(open(args.whisper_json, encoding="utf-8"))["segments"]
            if s["end"] > args.start and s["start"] < args.end]

    lines = []
    for s in segs:
        txt = fix(s["text"], extra)
        if not txt:
            continue
        a = max(s["start"], args.start) - args.start
        b = min(s["end"], args.end) - args.start
        if lines:
            prev = lines[-1]
            merged = join_caption([prev["text"], txt])        # "any" + "way" keeps its space; CJK glues
            if text_width(merged) <= args.max_chars and a - prev["end"] <= args.max_gap:
                prev["text"] = merged
                prev["end"] = b
                continue
        lines.append({"start": a, "end": b, "text": txt})

    # let a line linger into the pause that follows it, so subs do not flicker
    for i, ln in enumerate(lines[:-1]):
        ln["end"] = min(lines[i + 1]["start"], ln["end"] + 0.35)
    if lines:
        lines[-1]["end"] = min(args.end - args.start, lines[-1]["end"] + 0.5)

    json.dump(lines, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"{len(lines)} subtitle lines -> {args.out}")
    for ln in lines:
        print(f"  {ln['start']:6.2f} {ln['text']}")


if __name__ == "__main__":
    main()
