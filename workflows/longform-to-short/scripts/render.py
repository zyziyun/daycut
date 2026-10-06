#!/usr/bin/env python3
"""Step 6d: render timeline.json -> <out>/final.mp4 (no subtitles / panels yet).

Per item:
  card   -> still + card_sting.wav (silence-padded)
  clip   -> source (or re-recorded demo) video, per-item crop -> fit -> pad, setpts speed;
            audio atempo; hook clip gets hook_overlay.png
  freeze -> accurate still of the frame before the flash + the live source audio
  pitch  -> asetrate down by pitches.semitones, atempo compensates (duration preserved)
afade only at NON-continuous joins, so zoom / pitch splits stay seamless.
Sample-exact A/V: every item gets exactly the frames / samples of its slot on the timeline's frame grid
(_lfc.segment_grid: frame boundaries round(final_t0 * fps), audio 48 kHz samples tied to those frames).
Video segments (seg/s_NNN.mp4, video only, tpad-cloned / -frames:v capped) are concatenated by stream copy;
audio is rendered as PCM (seg/s_NNN.wav, apad + atrim=end_sample) and joined sample-exactly, then encoded ONCE
by vstudio.audio.loudnorm_2pass to persona audio.loudness_lufs. (Stream-copy concat of per-segment AAC adds
encoder priming at every join: ~25 ms per segment, so audio drifted behind the picture on long cuts.)
With explicit platform targets (config targets / platform) the first horizontal target's profile sets the
canvas (when render.size is not given) and the loudness / true-peak target (vstudio.platform).

render.audio_only (default false; set by the batch `longform-split` recipe): only the audio track is rendered
(same per-item PCM grid, fades, pitch and loudness) -> <out>/final.mp4 without a video stream; make_vertical.py
re-composes every picture from the source anyway, so the 16:9 picture is not needed for vertical-only jobs.

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
PROF = _lfc.primary_horizontal(cfg)       # None unless targets were set explicitly
W, H = cfg.get("render.size", list(PROF.size) if PROF else [1920, 1080])
FIT_W, FIT_H = cfg.get("render.fit", [W - 64, H - 64])
BG = cfg.get("render.pad_color", "0x141414")
FPS = cfg.get("render.fps", 24)
VID = ["-c:v", "libx264", "-preset", "medium", "-crf", str(cfg.get("render.crf", 19)), "-pix_fmt", "yuv420p"]
SR = 48000
AUDIO_ONLY = bool(cfg.get("render.audio_only"))
os.makedirs("seg", exist_ok=True)

timeline = _lfc.load_json("timeline.json")
GRID = _lfc.segment_grid(timeline, FPS, SR)       # [(frames, samples)] per item, sums == the timeline length


def outputs(n, vmap=None, amap=None):
    """Two outputs per item: video-only mp4 capped at the item's frame count, PCM wav of exactly its samples."""
    nf = GRID[n][0]
    v = (["-map", vmap] if vmap else []) + ["-an", "-frames:v", str(nf), *VID, "-movflags", "+faststart",
                                            f"seg/s_{n:03d}.mp4"]
    a = (["-map", amap] if amap else []) + ["-vn", "-c:a", "pcm_s16le", "-ar", str(SR), "-ac", "2", f"seg/s_{n:03d}.wav"]
    return v, a


def exact_af(n):
    """Tail of every audio chain: 48 kHz stereo s16, padded / trimmed to the item's exact sample count."""
    return (f"aresample={SR},aformat=sample_fmts=s16:channel_layouts=stereo,apad,"
            f"atrim=end_sample={GRID[n][1]},asetpts=PTS-STARTPTS")


HOLD = "tpad=stop_mode=clone:stop=-1"            # clone the last frame if a segment decodes short
FIT = (f"scale={FIT_W}:{FIT_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
       f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1")
files = []
for n, it in enumerate(timeline):
    out = f"seg/s_{n:03d}.mp4"
    files.append(out)
    if n < args.start and os.path.exists(out) and os.path.exists(out[:-4] + ".wav"):
        continue
    if GRID[n][0] <= 0:
        sys.exit(f"timeline item {n} is shorter than one frame at {FPS} fps")
    if it["kind"] == "card":
        sting = ["-i", "card_sting.wav"] if os.path.exists("card_sting.wav") else \
            ["-f", "lavfi", "-t", str(it["dur"]), "-i", f"anullsrc=r={SR}:cl=stereo"]
        v, a = outputs(n, "0:v:0", "1:a:0")
        if AUDIO_ONLY:
            media.run(["ffmpeg", "-y", *sting, "-af", exact_af(n), *outputs(n, None, "0:a:0")[1]])
            continue
        media.run(["ffmpeg", "-y", "-loop", "1", "-t", str(it["dur"]), "-i", it["png"], *sting,
                  "-vf", f"scale={W}:{H},setsar=1,fps={FPS},{HOLD}", *v, "-af", exact_af(n), *a])
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
    af += "," + exact_af(n)

    if AUDIO_ONLY:                               # the item's audio exactly as below, no picture
        media.run(["ffmpeg", "-y", "-ss", str(t0), "-to", str(t1), "-i", SRC, "-af", af,
                   *outputs(n, None, "0:a:0")[1]])
        continue

    if it["kind"] == "freeze":
        still = f"seg/still_{n:03d}.png"
        media.grab_frame(SRC, it["still_at"], still)
        cw, ch, cx, cy = it["crop"]
        v, a = outputs(n, "0:v:0", "1:a:0")
        media.run(["ffmpeg", "-y", "-loop", "1", "-t", f"{fdur:.3f}", "-i", still,
                  "-ss", str(t0), "-to", str(t1), "-i", SRC,
                  "-vf", f"crop={cw}:{ch}:{cx}:{cy},{FIT},fps={FPS},{HOLD}", *v, "-af", af, *a])
        continue

    if it["demo_slice"] is not None:
        if not REC:
            sys.exit("timeline has demo slices but demo.enabled/demo.rec is not set")
        vf = (f"scale={FIT_W}:{FIT_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1,setpts=PTS/{sp},fps={FPS},{HOLD}")
        v, a = outputs(n, "0:v:0", "1:a:0")
        media.run(["ffmpeg", "-y", "-ss", f"{it['demo_slice'][0]:.3f}", "-t", f"{dur:.3f}", "-i", REC,
                  "-ss", str(t0), "-to", str(t1), "-i", SRC, "-vf", vf, *v, "-af", af, *a])
        continue

    cw, ch, cx, cy = it["crop"]
    chain = f"crop={cw}:{ch}:{cx}:{cy},{FIT}"
    if it.get("overlay") and os.path.exists(it["overlay"]):
        fc = (f"[0:v]{chain}[v0];[v0][1:v]overlay=0:0[v1];[v1]setpts=PTS/{sp},fps={FPS},{HOLD}[vout];"
              f"[0:a]{af}[aout]")
        v, a = outputs(n, "[vout]", "[aout]")
        media.run(["ffmpeg", "-y", "-ss", str(t0), "-to", str(t1), "-i", SRC, "-i", it["overlay"],
                  "-filter_complex", fc, *v, *a])
    else:
        v, a = outputs(n, "0:v:0", "0:a:0")
        media.run(["ffmpeg", "-y", "-ss", str(t0), "-to", str(t1), "-i", SRC,
                  "-vf", f"{chain},setpts=PTS/{sp},fps={FPS},{HOLD}", *v, "-af", af, *a])
    if n % 8 == 0:
        print(f"[{n + 1}/{len(timeline)}]", flush=True)

_lfc.concat_wavs([p[:-4] + ".wav" for p in files], "joined.wav")      # PCM: sample-exact joins
if AUDIO_ONLY:
    joined = "joined.wav"
else:
    with open("concat.txt", "w") as f:
        f.writelines(f"file '{p}'\n" for p in files)
    media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-an", "-c", "copy", "joined_v.mp4"])
    media.run(["ffmpeg", "-y", "-i", "joined_v.mp4", "-i", "joined.wav", "-map", "0:v:0", "-map", "1:a:0",
               "-c", "copy", "joined.mkv"])
    joined = "joined.mkv"
final = os.path.join(cfg.out, "final.mp4")
# two-pass linear loudnorm to persona audio.loudness_lufs (-14) or the target profile, 48 kHz stereo, video copied;
# the only AAC encode of the cut
loud = dict(lufs=PROF.loudness["lufs"], tp=PROF.loudness["tp"]) if PROF else {}
m = audio.loudnorm_2pass(joined, final, **loud)
print(f"loudnorm: measured {m['input_i']:.1f} LUFS -> target")
print("done:", final)
