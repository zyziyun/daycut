#!/usr/bin/env python3
"""French typography in the French strings: narrow no-break space (U+202F) before : ; ? ! » and after «.
Idempotent. Run after editing French copy:  python3 scripts/fr-typo.py"""
import re, pathlib
SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
NB = " "
LIT = re.compile(r"'(?:[^'\\\n]|\\.)*'")

def fix_lit(m):
    s = m.group(0)
    s = re.sub(r"[  ]([:;?!»])", NB + r"\1", s)
    s = re.sub(r"«[  ]", "«" + NB, s)
    return s

def fix(text):
    return LIT.sub(fix_lit, text)

def blocks(text, start, end):
    out, on = [], False
    for line in text.splitlines(keepends=True):
        if re.match(start, line): on = True
        elif on and re.match(end, line): on = False
        out.append(fix(line) if on else line)
    return "".join(out)

p = SRC / "i18n/fr.ts"; p.write_text(fix(p.read_text()))
for name in ["content/usecases.ts", "content/compare.ts", "content/platforms.ts"]:
    p = SRC / name; t = p.read_text()
    t = blocks(t, r"^\s+fr: \{", r"^\s+(es|en|zh): \{|^\s*\},?\s*$(?!.)")
    # single-line fr entries (LABELS / REELFOLD_NOTES / batch titles)
    t = re.sub(r"(^\s+fr: \{.*\},?$)", lambda m: fix(m.group(1)), t, flags=re.M)
    p.write_text(t)
p = SRC / "data/batch.ts"; t = p.read_text()
t = re.sub(r"fr: '(?:[^'\\]|\\.)*'", lambda m: fix(m.group(0)), t); p.write_text(t)
print("ok")
