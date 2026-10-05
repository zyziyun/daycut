#!/usr/bin/env python3
"""Spoken English -> on-screen English: digits, math symbols, acronyms.

The narration script spells numbers out for TTS ("zero point five one"); subtitles read
far better as digits ("0.51"). Generic number conversion lives here; project-specific
replacements (acronyms, formulas) come from subtitles/display_rules.json:

{
  "replace": [["F P thirty-two", "FP32"], ["q equals round of x over s", "q = round(x / s)"]],
  "digit_lines": [7, 8, 9],          # lines where even small numbers become digits
  "post": [["total is one", "total is 1"]]
}

Library-free on purpose (nothing in vstudio converts spoken numbers to digits).
Usage:  python3 display_en.py [--project .]     # preview every cue's display form from subtitles/cues.json
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re

U = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALE = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}
NUMW = set(U) | set(TENS) | set(SCALE)


def load_rules(project="."):
    """<project>/subtitles/display_rules.json, or {} when absent."""
    p = os.path.join(project, "subtitles", "display_rules.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def _cardinal(ws):
    total, cur = 0, 0
    for w in ws:
        if w in U: cur += U[w]
        elif w in TENS: cur += TENS[w]
        elif w == "hundred": cur = max(cur, 1) * 100
        elif w in SCALE: total += max(cur, 1) * SCALE[w]; cur = 0
    return total + cur


def _valid(ws):
    """True when ``ws`` reads as ONE cardinal. "three ninety-nine" (a price), "nineteen eighty-four" (a year)
    or "two three" are several numbers said back to back; summing them gave "102" on a real script."""
    rank = {"unit": 1, "teen": 1, "tens": 2}
    prev = None
    for w in ws:
        kind = "scale" if w in SCALE and w != "hundred" else "hundred" if w == "hundred" else \
            "tens" if w in TENS else "teen" if U.get(w, 0) >= 10 else "unit"
        if prev in ("unit", "teen") and kind in ("unit", "teen", "tens"):
            return False
        if prev == "tens" and kind in ("teen", "tens"):
            return False
        if prev == "hundred" and kind == "hundred":
            return False
        prev = kind
    return True


def _convert(text, aggressive):
    toks = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*|[^A-Za-z]+", text)
    is_num = lambda t: all(p.lower() in NUMW for p in t.split("-"))
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        j, neg = i, False
        prev_num = bool(out) and re.search(r"\d\s*$", "".join(out))
        if t.lower() == "minus" and not prev_num and i + 2 < len(toks) and is_num(toks[i + 2]):
            neg, j = True, i + 2
        if j < len(toks) and is_num(toks[j]):
            words, k = [], j
            while k < len(toks):
                if is_num(toks[k]):
                    words += [p.lower() for p in toks[k].split("-")]; k += 1
                elif toks[k] == " " and k + 1 < len(toks) and (is_num(toks[k + 1]) or (
                        toks[k + 1].lower() == "and" and words and words[-1] in SCALE and k + 3 < len(toks) and is_num(toks[k + 3]))):
                    k += 1
                    if toks[k].lower() == "and": k += 2
                else:
                    break
            dec = []
            if k + 2 < len(toks) and toks[k] == " " and toks[k + 1].lower() == "point":
                m = k + 2
                while m < len(toks) and (toks[m] == " " or (toks[m].lower() in U and U[toks[m].lower()] < 10)):
                    if toks[m] != " ": dec.append(str(U[toks[m].lower()]))
                    m += 1
                if dec:
                    while toks[m - 1] == " ": m -= 1
                    k = m
            if not _valid(words):                      # several numbers in a row: leave them spoken
                out.append("".join(toks[i:k])); i = k; continue
            val = _cardinal(words)
            special = neg or dec or any(w in SCALE for w in words) or val >= 10
            nxt = "".join(toks[k:k + 2]).lower().strip()
            ok = aggressive and not (words == ["one"] or nxt in ("more", "of"))
            if special or ok:
                s = ("−" if neg else "") + f"{val:,}" + ("." + "".join(dec) if dec else "")
                for name, unit in (("billion", 10**9), ("million", 10**6)):
                    if name in words and val % unit == 0: s = f"{val // unit} {name}"
                out.append(s); i = k; continue
        out.append(t); i += 1
    return "".join(out)


def display(en, line, rules=None):
    """Display form of spoken chunk ``en`` from SCRIPT.md line ``line`` (rules: see load_rules)."""
    RULES = load_rules() if rules is None else rules
    s = re.sub(r"\ba hundred\b", "one hundred", en).replace("a few hundred", "a few QQQ")
    for a, b in RULES.get("replace", []):
        s = re.sub(a, b, s)
    s = _convert(s, aggressive=line in RULES.get("digit_lines", []))
    s = re.sub(r"\b1 (question|switch|for the|of just)", r"one \1", s).replace("QQQ", "hundred")
    for a, b in RULES.get("post", []):
        s = s.replace(a, b)
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Preview spoken -> on-screen English for every cue.")
    ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
    a = ap.parse_args()
    rules = load_rules(a.project)
    for c in json.load(open(os.path.join(a.project, "subtitles", "cues.json"))):
        print(c["line"], "|", display(c["spoken"], c["line"], rules))
