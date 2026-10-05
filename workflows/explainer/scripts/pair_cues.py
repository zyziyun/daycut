#!/usr/bin/env python3
"""Propose subtitles/cues.txt (EN chunk || 中文 pairs) from SCRIPT.md, for review.

Usage:  python3 pair_cues.py [--project .] [--platform xiaohongshu:full] [--out subtitles/cues.draft.txt]
                             [--compare subtitles/cues.txt] [--max-en N --max-zh N]
Reads   <project>/SCRIPT.md (spoken EN + "ZH:" per line), scenes.config.json "platform" (caption limits)
Writes  <project>/subtitles/cues.draft.txt  (never cues.txt unless you pass --out subtitles/cues.txt)

How: EN is split into clauses (sentence ends, then , ; : — when long), 中文 into clauses (after 。！？；：，—).
A monotone dynamic programme groups 1-4 EN clauses with 1-5 中文 clauses per cue, minimising
  |log(share of ZH chars / share of EN chars)|  (length ratio along the line)
  + a penalty when one side ends a sentence and the other does not (punctuation agreement)
  + penalties for cues over the caption limits (canvas.py: 2 lines each) or very short cues.
EN chunks always concatenate to the spoken text (align_cues.py checks it). Pairs whose ratio is off
or whose punctuation disagrees get a "# check" comment: a human/agent still verifies every pair — the
machine cannot know which clause translates which; it only proposes a sensible split.
--compare reports how many of a hand-made cues.txt's EN boundaries the draft reproduces.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, math, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canvas import add_platform_arg, resolve
from script_md import parse_script

W_CUE, W_MID, W_STRADDLE = 0.1, 0.3, 0.8    # tuned on example/ (78 % of hand cue boundaries)
EN_END = re.compile(r"[.?!][\"'”’)]*$")
ZH_END = re.compile(r"[。！？!?][”」』）)]*$")
ZH_SOFT_END = re.compile(r"[；;：:][”」』）)]*$")


def zh_len(s):
    """Display width: CJK = 1, latin/digits/space = 0.5."""
    return sum(1 if ord(c) > 0x2E80 else 0.5 for c in s.strip())


def en_clauses(text, max_en):
    """Sentence split, then clause split of long sentences at , ; : — (keeps every word, in order)."""
    sents = re.findall(r".+?(?:[.?!][\"'”’)]*(?=\s|$)|$)", text.strip())
    sents = [s.strip() for s in sents if s.strip()]
    out = []
    for s in sents:
        if len(s) <= max(28, max_en // 2):
            out.append(s)
            continue
        parts = re.split(r"(?<=[,;:—])\s+", s)
        out.extend(p for p in parts if p)
    # very long clauses without punctuation: split at " and " / " but " / " so " / " because " / any word
    fin = []
    for c in out:
        while len(c) > max_en:
            cut = None
            for kw in (" because ", " and ", " but ", " so ", " which ", " that ", " with "):
                i = c.find(kw, len(c) // 3, 2 * len(c) // 3 + len(kw))
                if i > 0:
                    cut = i; break
            if cut is None:
                cut = c.rfind(" ", 0, len(c) // 2 + 10)
            if cut <= 0:
                break
            fin.append(c[:cut].strip()); c = c[cut:].strip()
        fin.append(c)
    return fin


def zh_clauses(text):
    parts = re.findall(r".+?(?:——|[。！？!?；;：:，,][”」』）)]*|$)", text.strip())
    return [p.strip() for p in parts if p.strip()]


def pair_line(en, zh, max_en, max_zh, min_en=22):
    E, Z = en_clauses(en, max_en), zh_clauses(zh)
    if not Z:
        return [(e, "", 0.0, ["no ZH"]) for e in E]
    LE = [len(e) + 1 for e in E]; LZ = [zh_len(z) for z in Z]
    TE, TZ = float(sum(LE)), float(sum(LZ))
    n, m = len(E), len(Z)
    INF = float("inf")
    best = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0

    def cost(i, a, j, b):
        e = " ".join(E[i:i + a]); z = "".join(Z[j:j + b])
        le, lz = sum(LE[i:i + a]) / TE, sum(LZ[j:j + b]) / TZ
        c = 2.0 * abs(math.log((lz + 1e-6) / (le + 1e-6)))
        e_end, z_end = bool(EN_END.search(e)), bool(ZH_END.search(z) or ZH_SOFT_END.search(z))
        last = (i + a == n) and (j + b == m)
        if e_end != z_end and not last:
            c += 0.6
        if len(e) > max_en:
            c += 1.5 + (len(e) - max_en) / 20
        if zh_len(z) > max_zh:
            c += 1.5 + (zh_len(z) - max_zh) / 8
        if len(e) < min_en and not last:
            c += 0.5
        inner_end = any(EN_END.search(x) for x in E[i:i + a - 1])
        if not e_end and not last:
            c += W_MID + (W_STRADDLE if inner_end else 0.0)    # cue ends mid-sentence (worse if it began another)
        c += 0.08 * (a - 1) + 0.04 * (b - 1)
        return c

    for i in range(n + 1):
        for j in range(m + 1):
            if best[i][j] == INF:
                continue
            for a in range(1, 5):
                for b in range(1, 6):
                    if i + a > n or j + b > m:
                        continue
                    c = best[i][j] + cost(i, a, j, b) + W_CUE          # per-cue cost: prefer fewer, fuller cues
                    if c < best[i + a][j + b]:
                        best[i + a][j + b] = c; back[i + a][j + b] = (a, b)
    pairs, i, j = [], n, m
    if best[n][m] == INF:          # more cues than clauses on one side: one pair per line
        return [(en, zh, 1.0, ["unpaired"])]
    while i or j:
        a, b = back[i][j]
        pairs.append((i - a, a, j - b, b)); i, j = i - a, j - b
    out = []
    for i, a, j, b in reversed(pairs):
        e = " ".join(E[i:i + a]); z = "".join(Z[j:j + b])
        r = (sum(LZ[j:j + b]) / TZ) / (sum(LE[i:i + a]) / TE)
        flags = []
        if abs(math.log(r)) > math.log(1.6):
            flags.append(f"ratio {r:.2f}")
        if bool(EN_END.search(e)) != bool(ZH_END.search(z) or ZH_SOFT_END.search(z)) and (i + a, j + b) != (n, m):
            flags.append("punct")
        if len(e) > max_en or zh_len(z) > max_zh:
            flags.append("long")
        out.append((e, z, r, flags))
    return out


def read_cues_txt(path):
    groups, cur = {}, None
    for ln in open(path, encoding="utf-8"):
        ln = ln.rstrip("\n")
        if ln.startswith("## "):
            cur = int(ln[3:].split()[0]); groups[cur] = []
        elif "||" in ln and cur is not None:
            en, zh = [x.strip() for x in ln.split("||")][:2]
            groups[cur].append((en, zh))
    return groups


def boundaries(chunks):
    """Word indices where a new cue starts (excluding 0)."""
    out, k = set(), 0
    for c in chunks[:-1]:
        k += len(c.split()); out.add(k)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
    ap.add_argument("--script", default="SCRIPT.md")
    ap.add_argument("--out", default="subtitles/cues.draft.txt")
    ap.add_argument("--max-en", type=int, default=None, help="default 90 (16:9) or the vertical caption box limit")
    ap.add_argument("--max-zh", type=float, default=None, help="default 38 (16:9) or the vertical caption box limit")
    ap.add_argument("--compare", default=None, help="hand-made cues.txt to score the draft against")
    add_platform_arg(ap)
    a = ap.parse_args()
    root = pathlib.Path(a.project)
    cv = resolve(root, a.platform)
    max_en = a.max_en or (90 if cv["legacy"] else min(cv["max_en"], 64))
    max_zh = a.max_zh or (38 if cv["legacy"] else min(cv["max_zh"], 24))
    lines = parse_script(root / a.script)
    out = ["# Bilingual cue pairs (DRAFT from pair_cues.py — verify every pair: meaning, not just length).",
           "# Per narration line: \"EN || ZH\". EN chunks concatenated must equal the spoken text.",
           f"# limits: EN <= {max_en} chars, ZH <= {max_zh:g} (canvas {cv['key']}). '# check: ...' = look twice."]
    nflag = ncue = 0
    for L in lines:
        out.append(f"## {L['n']}")
        for e, z, r, flags in pair_line(L["en"], L["zh"], max_en, max_zh):
            ncue += 1
            out.append(f"{e} || {z}" + (f"    # check: {', '.join(flags)}" if flags else ""))
            nflag += bool(flags)
    p = root / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.name == "cues.txt" and p.exists():
        sys.exit(f"{p} exists: write the draft elsewhere (--out) and merge by hand")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{p}: {len(lines)} lines, {ncue} cues, {nflag} flagged for a second look")
    if a.compare:
        hand = read_cues_txt(root / a.compare)
        draft = read_cues_txt(p)
        hit = tot = exact = cues = 0
        for n, pairs in hand.items():
            hb, db = boundaries([e for e, _ in pairs]), boundaries([e for e, _ in draft.get(n, [])])
            hit += len(hb & db); tot += len(hb)
            hp = {(e, z) for e, z in pairs}; cues += len(pairs)
            exact += sum((e, z) in hp for e, z in draft.get(n, []))
        print(f"vs {a.compare}: {hit}/{tot} hand EN cue boundaries reproduced ({100 * hit / max(tot, 1):.0f} %), "
              f"{exact}/{cues} pairs identical (EN and ZH)")


if __name__ == "__main__":
    main()
