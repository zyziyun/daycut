#!/usr/bin/env python3
"""Slice whisper segments into clip-relative, term-fixed subtitle lines.

Also the home of fix(), the term-fix pass build_clips.py applies to every line.

Usage (standalone, one plain range):
  build_subs.py work/audio16k.json --start 120 --end 180 --out work/test.subs.json
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, re

from vstudio.config import persona

# Generic whisper mishearings of English terms code-switched into Chinese speech.
# Creator- or recording-specific fixes do NOT go here:
#   - per creator (product names, employers, recurring jargon):
#       persona.local.yaml -> subtitles.term_fixes: {"regex": "replacement"}
#   - per recording: clips.json -> "term_fix": [[regex, replacement], ...]
# Order applied: clips.json term_fix, then persona term_fixes, then this list.
TERM_FIX = [
    (r"readnning|readning", "reasoning"),
    (r"engagent", "engaging"),
    (r"思维导徒", "思维导图"),
    # NB: \b does not work next to CJK (CJK counts as \w), so these are unanchored
    (r"favor out|fake out|figur out", "figure out"),
    (r"Pendix", "Appendix"),
    (r"迭代迭到", "迭代得"),
    (r"文档reveal", "文档review"),
    (r"塞\s*off", "sign off"),
    (r"scate", "skip"),
    (r"体效", "提效"),
]
_persona_loaded = False


def _load_persona_fixes():
    """Prepend persona.subtitles.term_fixes once (keys are regexes)."""
    global _persona_loaded
    if _persona_loaded:
        return
    _persona_loaded = True
    fixes = ((persona().get("subtitles") or {}).get("term_fixes")) or {}
    TERM_FIX[:0] = [(k, v) for k, v in fixes.items()]


def fix(s):
    _load_persona_fixes()
    for pat, rep in TERM_FIX:
        s = re.sub(pat, rep, s)
    # tighten spacing around latin runs inside CJK
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("whisper_json")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=20)
    ap.add_argument("--max-gap", type=float, default=0.45)
    args = ap.parse_args()

    segs = [s for s in json.load(open(args.whisper_json, encoding="utf-8"))["segments"]
            if s["end"] > args.start and s["start"] < args.end]

    lines = []
    for s in segs:
        txt = fix(s["text"])
        if not txt:
            continue
        a = max(s["start"], args.start) - args.start
        b = min(s["end"], args.end) - args.start
        if lines:
            prev = lines[-1]
            merged = prev["text"] + txt
            if len(merged) <= args.max_chars and a - prev["end"] <= args.max_gap:
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
