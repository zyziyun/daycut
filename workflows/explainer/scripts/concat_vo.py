#!/usr/bin/env python3
"""Join audio/vo/lineNN.wav into one narration track with fixed gaps, then loudness-normalize.

Usage:  python3 concat_vo.py [--project .] [--lead 0.4] [--gap 0.7] [--lufs -16]
Writes  <project>/audio/narration.wav (two-pass loudnorm, 48 kHz stereo), audio/narration_raw.wav,
        audio/vo/offsets.json = [[line, start_s, duration_s], ...]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, tempfile

from vstudio import audio, media

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--lead", type=float, default=0.4, help="silence before line 1 (s)")
ap.add_argument("--gap", type=float, default=0.7, help="silence between lines (s)")
ap.add_argument("--lufs", type=float, default=-16, help="narration loudness target")
a = ap.parse_args()

root = pathlib.Path(a.project).resolve()
files = sorted((root / "audio/vo").glob("line*.wav"))
if not files:
    raise SystemExit(f"no audio/vo/line*.wav in {root}")
info = media.probe(str(files[0]))
sr, ch = info["sample_rate"] or 48000, info["channels"] or 1

offsets, t = [], a.lead
with tempfile.TemporaryDirectory() as tmp:
    lead, gap = audio.silence(a.lead, f"{tmp}/lead.wav", sr, ch), audio.silence(a.gap, f"{tmp}/gap.wav", sr, ch)
    lst = [f"file '{lead}'"]
    for i, f in enumerate(files):
        n, d = int(f.name[4:6]), media.duration(str(f))
        offsets.append([n, round(t, 3), round(d, 3)]); t += d + a.gap
        lst.append(f"file '{f}'")
        if i < len(files) - 1:
            lst.append(f"file '{gap}'")
    pathlib.Path(f"{tmp}/list.txt").write_text("\n".join(lst) + "\n")
    json.dump(offsets, open(root / "audio/vo/offsets.json", "w"))
    media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{tmp}/list.txt",
               "-c:a", "pcm_s16le", str(root / "audio/narration_raw.wav")])
m = audio.normalize_stem(str(root / "audio/narration_raw.wav"), str(root / "audio/narration.wav"), lufs=a.lufs)
print(f"{len(files)} lines, narration ≈ {t - a.gap:.1f}s (was {m['input_i']:.1f} LUFS) → audio/narration.wav")
