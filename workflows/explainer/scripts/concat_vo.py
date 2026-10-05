#!/usr/bin/env python3
"""Join audio/vo/lineNN.wav into one narration track with fixed gaps, then loudness-normalize.

Usage:  python3 concat_vo.py [--lead 0.4] [--gap 0.7] [--lufs -16]
Writes  audio/narration.wav (normalized), audio/narration_raw.wav, audio/vo/offsets.json
        offsets.json = [[line, start_s, duration_s], ...]
"""
import argparse, glob, json, os, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("--lead", type=float, default=0.4)
ap.add_argument("--gap", type=float, default=0.7)
ap.add_argument("--lufs", type=float, default=-16)
a = ap.parse_args()

files = sorted(glob.glob("audio/vo/line*.wav"))
dur = lambda f: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                                     capture_output=True, text=True).stdout)
sr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", files[0]],
                    capture_output=True, text=True).stdout.strip()
def silence(path, t):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=mono", "-t", str(t), path], check=True)
silence("/tmp/_lead.wav", a.lead); silence("/tmp/_gap.wav", a.gap)

offsets, t = [], a.lead
with open("/tmp/_vo_concat.txt", "w") as lst:
    lst.write("file '/tmp/_lead.wav'\n")
    for i, f in enumerate(files):
        n = int(os.path.basename(f)[4:6]); d = dur(f)
        offsets.append([n, round(t, 3), round(d, 3)]); t += d + a.gap
        lst.write(f"file '{os.path.abspath(f)}'\n")
        if i < len(files) - 1:
            lst.write("file '/tmp/_gap.wav'\n")
json.dump(offsets, open("audio/vo/offsets.json", "w"))
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "/tmp/_vo_concat.txt",
                "-c:a", "pcm_s16le", "audio/narration_raw.wav"], check=True)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "audio/narration_raw.wav", "-af",
                f"loudnorm=I={a.lufs}:LRA=11:TP=-1.5", "-ar", "48000", "audio/narration.wav"], check=True)
print(f"{len(files)} lines, narration ≈ {t - a.gap:.1f}s → audio/narration.wav")
