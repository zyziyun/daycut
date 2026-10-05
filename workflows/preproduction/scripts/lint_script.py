#!/usr/bin/env python3
"""Lint a spoken script against the craft rules (references/script_craft.md) + persona voice.*.

Checks: em-dashes, parentheses, creator-trope openers, generic CTAs, authority framing, AI-tell
vocabulary, meta/forward references, sentences > 25 words, possible fragments, digits under 10,
presence of an insight signpost, and word count vs. the format's target at persona voice.wpm.

  python3 lint_script.py SCRIPT.md [--format short|long-short|mid] [--strict]

Markdown headings, [bracket notes], ZH:/Delivery lines and code fences are ignored. Exit code 1 with
--strict if any error is found.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import re

from vstudio.config import persona

OPENERS = ["ok so", "okay so", "quick thing", "you won't believe", "today we're", "today we are", "today i want to",
           "let me tell you", "buckle up", "here's something wild", "welcome back", "hey everyone", "hey guys"]
CTAS = ["follow for more", "subscribe", "hope that helps", "wild, right", "wild right", "smash", "like button",
        "comment your thoughts", "drop your thoughts", "let me know in the comments", "don't forget to"]
AUTHORITY = ["every time someone asks me", "as an expert", "the thing nobody is talking about",
             "nobody is talking about", "most people don't realize", "most people don't know"]
AI_TELL = ["delve", "dive into", "deep dive", "navigate", "leverage", "tapestry", "journey", "comprehensive", "robust",
           "seamless", "in today's fast-paced world", "it's important to note", "it is important to note", "realm",
           "unlock the power", "game-changer", "game changer"]
META = ["this slide", "this video", "if you remember one thing", "this is the most important", "we've got a lot to cover",
        "more on that later", "we'll come back to", "to recap", "as i mentioned", "in a few minutes"]
SIGNPOSTS = ["explained enough", "most explanations skip", "doesn't get talked about", "what's actually happening",
             "here's the detail", "the part that", "underneath"]
TARGETS = {"short": (165, 250), "long-short": (250, 510), "mid": (500, 1650)}
SMALL = {"1", "2", "3", "4", "5", "6", "7", "8", "9"}


def spoken_text(raw):
    out, fence = [], False
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith("```"):
            fence = not fence; continue
        if fence or not s or s.startswith(("#", "[", "ZH:", "zh:", "**Delivery", "Delivery:", ">", "<!--", "|", "---")):
            continue
        out.append(re.sub(r"\[[^\]]*\]", "", s))
    return " ".join(out)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", text) if s.strip()]


def find_any(text_l, phrases):
    return [p for p in phrases if re.search(r"(?<![a-z])" + re.escape(p.lower()) + r"(?![a-z])", text_l)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--format", choices=list(TARGETS), default="short")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    v = persona().get("voice", {}) or {}
    wpm = float(v.get("wpm", 165))
    avoid = [p.lower() for p in v.get("phrases_avoid", [])]
    rules = " ".join(v.get("rules", [])).lower()

    text = spoken_text(pathlib.Path(a.script).read_text(encoding="utf-8"))
    tl = text.lower()
    sents = sentences(text)
    errs, warns = [], []

    if "—" in text or "–" in text or " -- " in text:
        errs.append(f"em/en-dash x{text.count('—') + text.count('–') + text.count(' -- ')}: use a period or comma")
    if "parenthes" in rules and re.search(r"[()（）]", text):
        errs.append("parentheses in spoken lines (persona voice.rules)")
    first = " ".join(sents[:1]).lower()
    for p in find_any(first, OPENERS):
        errs.append(f"creator-trope opener: '{p}'")
    if re.match(r"^(so|alright|ok|okay|well)\b", first):
        errs.append("throat-clearing word before the first sentence")
    tail = " ".join(sents[-3:]).lower()
    for p in find_any(tail, CTAS):
        errs.append(f"generic CTA in closing: '{p}'")
    for label, lst in (("authority framing", AUTHORITY), ("AI-tell word", AI_TELL), ("meta/navigation", META),
                       ("persona voice.phrases_avoid", avoid)):
        for p in find_any(tl, lst):
            errs.append(f"{label}: '{p}'")
    if any(0x1F300 <= ord(c) <= 0x1FAFF for c in text):
        errs.append("emoji in spoken script")

    lens = []
    for s in sents:
        n = len(s.split()); lens.append(n)
        if n > 25:
            warns.append(f"{n}-word sentence (split it): {s[:70]}…")
        elif n <= 3 and not s.endswith("?"):
            warns.append(f"possible fragment: '{s}'")
    for m in re.finditer(r"(?<![\d.,])\b([1-9])\b(?![\d.,%])", text):
        warns.append(f"digit '{m.group(1)}' under 10: spell it out for speech"); break
    if not find_any(tl, SIGNPOSTS + [p.lower() for p in v.get("signposts", [])]):
        warns.append("no insight signpost found (every script needs one signposted reframe paragraph)")

    words = len(re.findall(r"[A-Za-z0-9']+", text)) + len(re.findall(r"[一-鿿]", text)) // 2
    lo, hi = TARGETS[a.format]
    secs = words / wpm * 60
    avg = sum(lens) / len(lens) if lens else 0
    print(f"{words} words ≈ {secs:.0f}s at {wpm:.0f} wpm (target {lo}-{hi} words for {a.format}); "
          f"{len(sents)} sentences, avg {avg:.1f} words")
    if not lo <= words <= hi:
        warns.append(f"word count {words} outside {a.format} target {lo}-{hi}")
    if avg and not 8 <= avg <= 20:
        warns.append(f"average sentence length {avg:.1f} (aim 12-18)")

    for e in errs:
        print("ERROR ", e)
    for w in warns:
        print("warn  ", w)
    if not errs and not warns:
        print("clean")
    sys.exit(1 if (a.strict and errs) else 0)


if __name__ == "__main__":
    main()
