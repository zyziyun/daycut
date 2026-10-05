#!/usr/bin/env python3
"""Step 6d: render timeline.json -> <out>/final.mp4 (no subtitles / panels yet).

Per item:
  card   -> still + card_sting.wav (silence-padded)
  clip   -> source (or re-recorded demo) video, per-item crop -> fit -> pad, setpts speed;
            audio atempo; hook clip gets hook_overlay.png
  freeze -> accurate still of the frame before the flash + the live source audio
  pitch  -> asetrate down by pitches.semitones, atempo compensates (duration preserved)
afade only at NON-continuous joins, so zoom / pitch splits stay seamless.
Segments are concatenated by stream copy, then vstudio.audio.loudnorm_2pass to persona audio.loudness_lufs.

Usage: python3 render.py work/config.py [--from N]   (--from: reuse already-rendered segments < N)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import math
import os

import _lfc
from vstudio import audio, media


def extra(ap):
    ap.add_argument("--from", dest="start", type=int, default=0, help="re-render segments from this index")


cfg, args = _lfc.load(description=__doc__, extra=extra)
SRC = cfg.src
REC = cfg.path_of(cfg.get("demo.rec")) if cfg.get("demo.enabled") else None
W, H = cfg.get("render.size", [1920, 1080])
FIT_W, FIT_H = cfg.get("render.fit", [W - 64, H - 64])
BG = cfg.get("render.pad_color", "0x141414")
FPS = cfg.get("render.fps", 24)
VID = ["-c:v", "libx264", "-preset", "medium", "-crf", str(cfg.get("render.crf", 19)), "-pix_fmt", "yuv420p"]
AUD = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]  # uniform, so concat never reinits
os.makedirs("seg", exist_ok=True)

timeline = _lfc.load_json("timeline.json")
FIT = (f"scale={FIT_W}:{FIT_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
       f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1")
files = []
for n, it in enumerate(timeline):
    out = f"seg/s_{n:03d}.mp4"
    files.append(out)
    if n < args.start and os.path.exists(out):
        continue
    if it["kind"] == "card":
        sting = ["-i", "card_sting.wav"] if os.path.exists("card_sting.wav") else \
            ["-f", "lavfi", "-t", str(it["dur"]), "-i", "anullsrc=r=48000:cl=stereo"]
        media.run(["ffmpeg", "-y", "-loop", "1", "-t", str(it["dur"]), "-i", it["png"], *sting,
                  "-vf", f"scale={W}:{H},setsar=1,fps={FPS}", "-af", "aresample=48000,apad",
                  "-shortest", *VID, *AUD, "-movflags", "+faststart", out])
        continue

    t0, t1, sp = it["t0"], it["t1"], it["speed"]
    dur = t1 - t0
    fdur = dur / sp
    fades = []
    if not it["cont_in"]:
        fades.append("afade=t=in:st=0:d=0.03")
    if not it["cont_out"]:
        fades.append(f"afade=t=out:st={max(0.0, fdur - 0.04):.3f}:d=0.04")
    if it.get("pitch"):
        semitones = 12 * math.log2(float(it["pitch"]))  # timeline stores the rate ratio
        af = f"{audio.pitch_shift_filter(semitones, tempo=sp)},asetpts=PTS-STARTPTS"
    else:
        af = f"aresample=48000,{media.atempo_chain(sp)},asetpts=PTS-STARTPTS"
    af += ("," + ",".join(fades)) if fades else ""

    if it["kind"] == "freeze":
        still = f"seg/still_{n:03d}.png"
        media.grab_frame(SRC, it["still_at"], still)
        cw, ch, cx, cy = it["crop"]
        media.run(["ffmpeg", "-y", "-loop", "1", "-t", f"{fdur:.3f}", "-i", still,
                  "-ss", str(t0), "-to", str(t1), "-i", SRC, "-map", "0:v:0", "-map", "1:a:0",
                  "-vf", f"crop={cw}:{ch}:{cx}:{cy},{FIT},fps={FPS}", "-af", af,
                  *VID, *AUD, "-shortest", "-movflags", "+faststart", out])
        continue

    if it["demo_slice"] is not None:
        if not REC:
            sys.exit("timeline has demo slices but demo.enabled/demo.rec is not set")
        vf = (f"scale={FIT_W}:{FIT_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1,setpts=PTS/{sp},fps={FPS}")
        media.run(["ffmpeg", "-y", "-ss", f"{it['demo_slice'][0]:.3f}", "-t", f"{dur:.3f}", "-i", REC,
                  "-ss", str(t0), "-to", str(t1), "-i", SRC, "-map", "0:v:0", "-map", "1:a:0",
                  "-vf", vf, "-af", af, *VID, *AUD, "-shortest", "-movflags", "+faststart", out])
        continue

    cw, ch, cx, cy = it["crop"]
    chain = f"crop={cw}:{ch}:{cx}:{cy},{FIT}"
    if it.get("overlay") and os.path.exists(it["overlay"]):
        fc = (f"[0:v]{chain}[v0];[v0][1:v]overlay=0:0[v1];[v1]setpts=PTS/{sp},fps={FPS}[vout];"
              f"[0:a]{af}[aout]")
        media.run(["ffmpeg", "-y", "-ss", str(t0), "-to", str(t1), "-i", SRC, "-i", it["overlay"],
                  "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
                  *VID, *AUD, "-movflags", "+faststart", out])
    else:
        media.run(["ffmpeg", "-y", "-ss", str(t0), "-to", str(t1), "-i", SRC,
                  "-vf", f"{chain},setpts=PTS/{sp},fps={FPS}", "-af", af,
                  *VID, *AUD, "-movflags", "+faststart", out])
    if n % 8 == 0:
        print(f"[{n + 1}/{len(timeline)}]", flush=True)

with open("concat.txt", "w") as f:
    f.writelines(f"file '{p}'\n" for p in files)
media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "joined.mp4"])
final = os.path.join(cfg.out, "final.mp4")
# two-pass linear loudnorm to persona audio.loudness_lufs (-14), 48 kHz stereo, video stream-copied
m = audio.loudnorm_2pass("joined.mp4", final)
print(f"loudnorm: measured {m['input_i']:.1f} LUFS -> target")
print("done:", final)
