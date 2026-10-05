#!/usr/bin/env python3
"""Read the transcript the way the editing decisions need it.

  outline   45s-chunked outline of the whole recording, to pick segments
  runs      whisper segments collapsed into speaker runs (needs speakers.json),
            to check who actually said what before writing a single caption
  coverage  for a tiling cut: covered source seconds / total, and every gap
  editor    dump each keep-window as `speaker: [t]word [t]word ...` in ~7 min
            chunks, the input for the dialogue-editor pass (editor_cuts.json)
  grep      find phrases in the transcript (names, 剪掉 / 公司 ...) with times

Usage:
  transcript_tools.py outline  work/audio16k.json [--chunk 45]
  transcript_tools.py runs     work/audio16k.json --speakers work/speakers.json
  transcript_tools.py coverage clips.json [--only <id>]
  transcript_tools.py editor   clips.json --speakers work/speakers.json --out work/editor/ [--only <id>]
  transcript_tools.py grep     work/audio16k.json 剪掉 剪走 公司
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, bisect, json, os


def load(p):
    return json.load(open(p, encoding="utf-8"))


def fmt(t):
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def speaker_at(sp, t):
    if not sp:
        return "?"
    k = min(max(bisect.bisect_left(sp["times"], t), 0), len(sp["labels"]) - 1)
    return sp["labels"][k]


def cmd_outline(a):
    segs = load(a.whisper)["segments"]
    chunk, cur, buf = a.chunk, 0.0, []
    for s in segs:
        while s["start"] >= cur + chunk:
            if buf:
                print(f"[{fmt(cur)}] " + "".join(buf))
            cur += chunk
            buf = []
        buf.append(f"({s['start']:.1f}){s['text'].strip()} ")
    if buf:
        print(f"[{fmt(cur)}] " + "".join(buf))


def cmd_runs(a):
    segs = load(a.whisper)["segments"]
    sp = load(a.speakers)
    runs = []
    for s in segs:
        who = speaker_at(sp, (s["start"] + s["end"]) / 2)
        if runs and runs[-1][0] == who:
            runs[-1][2] = s["end"]
            runs[-1][3].append(s["text"].strip())
        else:
            runs.append([who, s["start"], s["end"], [s["text"].strip()]])
    for who, s0, s1, txt in runs:
        print(f"{fmt(s0)}-{fmt(s1)} {who:>6}: {''.join(txt)}")


def clip_windows(c):
    return c.get("windows") or [[c["start"], c["end"]]]


def cmd_coverage(a):
    C = load(a.config)
    segs = load(C["whisper"])["segments"]
    total = segs[-1]["end"] - segs[0]["start"] if segs else 0
    ws = sorted(w for c in C["clips"] if not a.only or c["id"] == a.only for w in clip_windows(c))
    covered, gaps, end = 0.0, [], segs[0]["start"] if segs else 0
    for lo, hi in ws:
        if lo > end + 0.05:
            gaps.append((end, lo))
        covered += max(0.0, hi - max(lo, end))
        end = max(end, hi)
    print(f"covered {covered:.1f}s of {total:.1f}s ({covered / max(total, 1e-9):.1%})")
    for g0, g1 in gaps:
        print(f"  gap {g0:8.2f}-{g1:8.2f} ({g1 - g0:.1f}s)")


def cmd_editor(a):
    C = load(a.config)
    segs = load(C["whisper"])["segments"]
    sp = load(a.speakers) if a.speakers else None
    words = sorted(((w["start"], w["word"].strip()) for s in segs for w in s.get("words", [])
                    if w["word"].strip()), key=lambda x: x[0])
    os.makedirs(a.out, exist_ok=True)
    n = 0
    for c in C["clips"]:
        if a.only and c["id"] != a.only:
            continue
        lines, t_chunk = [], None
        for lo, hi in clip_windows(c):
            cur_who, buf = None, []
            for t, w in words:
                if not lo <= t <= hi:
                    continue
                who = speaker_at(sp, t)
                if who != cur_who:
                    if buf:
                        lines.append(f"{cur_who}: " + " ".join(buf))
                    cur_who, buf = who, []
                buf.append(f"[{t:.2f}]{w}")
                t_chunk = t if t_chunk is None else t_chunk
                if t - t_chunk > a.chunk_min * 60:
                    lines.append(f"{cur_who}: " + " ".join(buf))
                    buf = []
                    p = os.path.join(a.out, f"{c['id']}.{n:02d}.txt")
                    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
                    n, lines, t_chunk = n + 1, [], None
            if buf:
                lines.append(f"{cur_who}: " + " ".join(buf))
            lines.append(f"--- window end {hi:.2f} ---")
        if lines:
            p = os.path.join(a.out, f"{c['id']}.{n:02d}.txt")
            open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            n += 1
    print(f"{n} chunk files -> {a.out}")


def cmd_grep(a):
    segs = load(a.whisper)["segments"]
    for s in segs:
        if any(p in s["text"] for p in a.patterns):
            print(f"{s['start']:8.2f}-{s['end']:8.2f}  {s['text'].strip()}")


def main():
    ap = argparse.ArgumentParser(description="Transcript views for picking, attributing and editing clips.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("outline"); p.add_argument("whisper"); p.add_argument("--chunk", type=float, default=45)
    p = sub.add_parser("runs"); p.add_argument("whisper"); p.add_argument("--speakers", required=True)
    p = sub.add_parser("coverage"); p.add_argument("config"); p.add_argument("--only")
    p = sub.add_parser("editor"); p.add_argument("config"); p.add_argument("--speakers")
    p.add_argument("--out", default="work/editor"); p.add_argument("--only")
    p.add_argument("--chunk-min", type=float, default=7.0)
    p = sub.add_parser("grep"); p.add_argument("whisper"); p.add_argument("patterns", nargs="+")
    a = ap.parse_args()
    {"outline": cmd_outline, "runs": cmd_runs, "coverage": cmd_coverage,
     "editor": cmd_editor, "grep": cmd_grep}[a.cmd](a)


if __name__ == "__main__":
    main()
