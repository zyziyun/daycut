#!/usr/bin/env python3
"""Narration QA: does each TTS take say every sentence of its SCRIPT.md line?

A whole-line difflib ratio can't tell a dropped sentence from number formatting ("sixteen thousand" vs
"16,000" scored 0.68-0.74 on clean takes, about the same as a take that silently dropped its last sentence).
Here both sides are normalised first (spoken numbers -> digits with display_en, digit grouping, punctuation,
case, hyphens), the take's transcript is aligned to the script word by word, and every SCRIPT sentence gets a
coverage score (share of its words found in order). A sentence under --min-cover (0.5) is reported MISSING.

Usage:  python3 vo_check.py [--project .] [LINE ...] [--min-cover 0.5] [--backend auto] [--model ...]
Reads   <project>/SCRIPT.md, <project>/audio/vo/lineNN.wav (ASR via vstudio.asr, cached next to each wav)
Exit 1  when any sentence is missing (tts.py runs the same check per take and re-generates the line).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, difflib, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from display_en import _convert  # noqa: E402

MIN_COVER = 0.5


def _scaled(num, word):
    v = float(num) * {"thousand": 10**3, "million": 10**6, "billion": 10**9}[word]
    return str(int(v)) if v == int(v) else str(v)


def norm_tokens(text):
    """Comparable tokens: spoken numbers -> digits, "16,896" -> "16896", "0.51" kept, punctuation / case dropped."""
    s = re.sub(r"\b[Aa] (hundred|thousand|million|billion)\b", r"one \1", text.replace("−", "-"))
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    # "1 million" / "1.5 million" (as ASR writes them) -> digits before the word-number pass sees the scale word
    s = re.sub(r"\b(\d+(?:\.\d+)?) (thousand|million|billion)\b",
               lambda m: _scaled(m.group(1), m.group(2)), s)
    s = _convert(s, aggressive=True)
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = re.sub(r"\b(\d+(?:\.\d+)?) (thousand|million|billion)\b", lambda m: _scaled(m.group(1), m.group(2)), s)
    s = s.lower().replace("-", " ").replace("%", " percent")
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?", s)


def sentences(text):
    """Script sentences (split after . ! ? followed by a space / end)."""
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]


def check(script, heard, min_cover=MIN_COVER):
    """Align ``heard`` (ASR text of the take) to ``script`` (the line's spoken text).
    Returns dict(ratio, sentences=[{text, cover, missing}], missing=[text, ...])."""
    sents = sentences(script)
    toks, owner = [], []
    for i, s in enumerate(sents):
        t = norm_tokens(s)
        toks += t
        owner += [i] * len(t)
    heard_t = norm_tokens(heard)
    sm = difflib.SequenceMatcher(None, toks, heard_t, autojunk=False)
    hit = [False] * len(toks)
    for a, _, n in sm.get_matching_blocks():
        for j in range(a, a + n):
            hit[j] = True
    out = []
    for i, s in enumerate(sents):
        idx = [j for j, o in enumerate(owner) if o == i]
        cover = (sum(hit[j] for j in idx) / len(idx)) if idx else 1.0
        out.append(dict(text=s, cover=round(cover, 3), missing=bool(idx) and cover < min_cover))
    return dict(ratio=round(sm.ratio(), 3), sentences=out, missing=[d["text"] for d in out if d["missing"]])


def script_lines(root):
    """{line number: spoken text} from SCRIPT.md (4-space indented blocks under '## Line N')."""
    blocks = re.split(r"\n## Line ", (pathlib.Path(root) / "SCRIPT.md").read_text())[1:]
    out = {}
    for b in blocks:
        n = int(b.split(" ", 1)[0])
        out[n] = " ".join(l.strip() for l in b.split("\n") if l.startswith("    "))
    return out


def check_take(wav, script, min_cover=MIN_COVER, backend="auto", model=None):
    """ASR one take (vstudio.asr, cached by content) and check it against its script line."""
    from vstudio import asr
    tr = asr.transcribe(str(wav), language="en", backend=backend, model=model, fix_terms=False)
    r = check(script, tr.get("text") or " ".join(w["w"] for w in tr["words"]), min_cover)
    r["heard"] = tr.get("text", "")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lines", nargs="*", help="only these line numbers")
    ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
    ap.add_argument("--min-cover", type=float, default=MIN_COVER)
    ap.add_argument("--backend", default="auto", choices=["auto", "mlx", "faster", "openai", "openai-compatible"])
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    root = pathlib.Path(a.project)
    bad = 0
    for n, text in sorted(script_lines(root).items()):
        if a.lines and str(n) not in a.lines:
            continue
        wav = root / f"audio/vo/line{n:02d}.wav"
        if not wav.exists():
            print(f"line {n:02d}: no take ({wav})")
            continue
        r = check_take(wav, text, a.min_cover, a.backend, a.model)
        worst = min((s["cover"] for s in r["sentences"]), default=1.0)
        print(f"line {n:02d}: ratio {r['ratio']:.2f}  min sentence cover {worst:.2f}"
              + ("" if not r["missing"] else "  MISSING:"))
        for s in r["missing"]:
            print(f"    - {s}")
        bad += bool(r["missing"])
    if bad:
        sys.exit(f"{bad} line(s) dropped a sentence: re-generate them (python3 tts.py --fresh N)")


if __name__ == "__main__":
    main()
