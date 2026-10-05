"""Shared helper for the V-track cut passes: keep ranges of a body (video-only mp4 + 48 kHz wav, the files
every step passes on), frame-exact. The cutting itself is ``vstudio.cut.cut_segments`` (accurate pre-seek,
frame-grid snap, sample-exact audio with 12 ms edge fades, so A/V cannot drift); the time map is
``vstudio.cut.TimeMap``. This file only adapts the separate video/audio files of this pipeline."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
import os
import numpy as np
from vstudio import audio, cut, media

F = 30


# Snap every video timestamp to the 1/30 s grid while stream-copying. Bodies made by joining parts with the
# concat demuxer carry ~1 ms timestamp jitter; cut.cut_segments seeks with an accurate -ss, so a frame that sits
# 1 ms before its nominal time is dropped and the whole range shifts by one frame (and loses its last frame).
SNAP_BSF = f"setts=pts=round(PTS*TB*{F})/(TB*{F}):dts=round(DTS*TB*{F})/(TB*{F})"


def mux(in_v, in_a, out):
    """Stream-copy video (timestamps snapped to the frame grid) + wav into one file (.mov keeps the video
    timescale; mkv rounds pts to whole ms). Returns out."""
    media.run(["ffmpeg", "-y", "-i", in_v, "-i", in_a, "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-bsf:v", SNAP_BSF, out])
    return out


def q(t):
    """Snap to the 30 fps frame grid."""
    return round(t * F) / F


def dbenv(x, sr):
    """10 ms RMS envelope in dB, 3-frame moving average IN dB (the threshold/run rules were tuned on this;
    audio.rms_envelope smooths before the log, which widens every voiced run by ~10 ms)."""
    env = audio.rms_envelope(x, sr, hop=0.01, win=0.01, smooth=0)[0]
    return np.convolve(env, np.ones(3) / 3, "same")


def remap(keep):
    """f(old_t) -> new_t for a sorted list of kept (s, e) ranges; a cut-out time maps to where the next
    kept range starts (vstudio TimeMap, snap="fwd")."""
    tm = cut.TimeMap.from_segments(keep)

    def m(t):
        v = tm.to_final(t, snap="fwd")
        return round(tm.duration if v is None else v, 3)
    return m


def cut_sources(segs, out_v, out_a, tmp="segtmp", crf=12, fade=0.012):
    """segs: [(src, t0, t1), ...] in output order; each src carries video AND audio. Consecutive ranges of
    one source go through one cut.cut_segments call. Writes out_v (video only) + out_a (48 kHz stereo
    PCM wav). Returns the total length in seconds (frame-quantised)."""
    groups = []
    for src, a, b in segs:
        if groups and groups[-1][0] == src:
            groups[-1][1].append((a, b))
        else:
            groups.append((src, [(a, b)]))
    os.makedirs(tmp, exist_ok=True)
    parts, pcm, total = [], [], 0.0
    for k, (src, rng) in enumerate(groups):
        p = os.path.join(tmp, f"g{k:03d}.mov")
        tm = cut.cut_segments(src, rng, p, fps=F, crf=crf, fade=fade, workers=6, tmpdir=os.path.join(tmp, f"g{k:03d}"))
        parts.append(p); pcm.append(audio.decode_audio(p)); total += tm.duration
    lst = os.path.join(tmp, "groups.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
    media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v:0", "-c", "copy", out_v])
    audio.write_wav(out_a, np.concatenate(pcm), audio.SR)
    return total


def cut_body(in_v, in_a, keep, out_v, out_a, tmp="segtmp"):
    """Keep `keep` [(s, e)] of the body (in_v video-only + in_a wav) -> out_v + out_a. Returns seconds."""
    os.makedirs(tmp, exist_ok=True)
    av = mux(in_v, in_a, os.path.join(tmp, "body_av.mov"))     # cut_segments wants a/v in one file
    return cut_sources([(av, s, e) for s, e in keep], out_v, out_a, tmp)
