"""Synthetic media for the vlog tests (lavfi + numpy only; no network, no personal media).

    python3 synth.py OUT_DIR          # writes footage/*, music/song.wav, photos/*, transcripts

Clips (all short):
  scenery.mp4   1920x1080 30 fps 12 s, testsrc2 (moving), no audio       -> landscape scenery, no face
  portrait.mp4  1080x1920 30 fps 10 s, mandelbrot zoom, ambient noise     -> portrait phone clip
  slowmo.mp4    1920x1080 120 fps 4 s, moving testsrc                     -> true slow-mo source
  talk.mp4      1920x1080 30 fps 12 s, smptehdbars + moving box, a sine "speech" track with
                two sentences (1.0-4.2 s and 6.0-9.4 s) and silence between -> speech clip
  talk.words.json  hand transcript (word timestamps) matching the sine bursts
  song.wav      120 BPM drum track, 40 s: hats-only intro until 8 s, full kit after (a "drop")
  photo1.jpg / photo2.heic (HEIC only when macOS ``sips`` exists)
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np

SR = 48000


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True)


def drum_track(bpm=120.0, dur=40.0, t0=0.5, quiet_until=8.0, seed=0, sr=SR):
    rng = np.random.default_rng(seed)
    x = np.zeros(int(dur * sr) + sr)
    T, times = 60.0 / bpm, []
    t = t0
    while t < dur:
        times.append(t)
        t += T

    def add(s, at, g):
        i = int(round(at * sr))
        j = min(len(x), i + len(s))
        x[i:j] += g * s[:j - i]

    tk = np.arange(int(0.25 * sr)) / sr
    kick = np.sin(2 * np.pi * np.cumsum(50 + 120 * np.exp(-tk * 30)) / sr) * np.exp(-tk * 12)
    ts = np.arange(int(0.15 * sr)) / sr
    snare = np.convolve(rng.standard_normal(len(ts)), np.ones(4) / 4, "same") * np.exp(-ts * 30)
    th = np.arange(int(0.04 * sr)) / sr
    hat = np.diff(np.concatenate([[0], rng.standard_normal(len(th))])) * np.exp(-th * 120)
    for k, bt in enumerate(times):
        if bt >= quiet_until:
            add(kick, bt, 1.0 if k % 4 == 0 else 0.55)
            if k % 4 in (1, 3):
                add(snare, bt, 0.35)
        else:
            add(kick, bt, 0.12)
        if k + 1 < len(times):
            add(hat, (bt + times[k + 1]) / 2, 0.25)
    # a pad so the bed has some body between hits
    tt = np.arange(len(x)) / sr
    x += 0.04 * np.sin(2 * np.pi * 110 * tt) * (tt > quiet_until)
    x = x[:int(dur * sr)]
    return (x / np.max(np.abs(x)) * 0.8).astype(np.float32), np.array(times)


def write_wav(path, x, sr=SR):
    import wave
    x = np.clip(x, -1, 1)
    st = np.stack([x, x], 1) if x.ndim == 1 else x
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((st * 32767).astype("<i2").tobytes())


SPEECH = [(1.0, 4.2), (6.0, 9.4)]
WORDS = [("Hello", 1.0, 1.5), ("everyone,", 1.55, 2.2), ("welcome", 2.3, 2.9), ("to", 2.95, 3.1),
         ("the", 3.15, 3.35), ("old", 3.4, 3.7), ("harbour.", 3.75, 4.2),
         ("This", 6.0, 6.3), ("market", 6.35, 6.9), ("opens", 6.95, 7.4), ("at", 7.45, 7.6),
         ("five", 7.65, 8.0), ("every", 8.05, 8.5), ("morning.", 8.55, 9.4)]


def speech_track(dur=12.0, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    x = np.zeros_like(t)
    for a, b in SPEECH:
        m = (t >= a) & (t < b)
        # syllable-like amplitude modulation on a 200 Hz voice-ish tone + harmonics
        env = 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * (t - a)) ** 2
        x += m * env * (0.35 * np.sin(2 * np.pi * 200 * t) + 0.15 * np.sin(2 * np.pi * 400 * t)
                        + 0.08 * np.sin(2 * np.pi * 600 * t))
    return x.astype(np.float32)


def main(out):
    fd = os.path.join(out, "footage")
    os.makedirs(fd, exist_ok=True)
    os.makedirs(os.path.join(out, "music"), exist_ok=True)
    os.makedirs(os.path.join(out, "photos"), exist_ok=True)
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p"]
    ff("-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=12", *enc, os.path.join(fd, "scenery.mp4"))
    ff("-f", "lavfi", "-i", "mandelbrot=s=1080x1920:r=30", "-f", "lavfi", "-i", "anoisesrc=a=0.02:c=pink:r=48000",
       "-t", "10", *enc, "-c:a", "aac", "-shortest", os.path.join(fd, "portrait.mp4"))
    ff("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=120:d=4", *enc, os.path.join(fd, "slowmo.mp4"))
    wav = os.path.join(out, "music", "_speech.wav")
    write_wav(wav, speech_track())
    ff("-f", "lavfi", "-i", "smptehdbars=s=1920x1080:r=30:d=12", "-i", wav,
       "-vf", "drawbox=x='200+100*t':y=400:w=300:h=300:color=white@0.9:t=fill",
       *enc, "-c:a", "aac", "-b:a", "192k", "-shortest", os.path.join(fd, "talk.mp4"))
    os.remove(wav)
    with open(os.path.join(fd, "talk.words.json"), "w") as f:
        json.dump([dict(w=w, t=a, te=b) for w, a, b in WORDS], f)
    song, times = drum_track()
    write_wav(os.path.join(out, "music", "song.wav"), song)
    with open(os.path.join(out, "music", "song.truth.json"), "w") as f:
        json.dump(dict(bpm=120.0, beats=[round(float(t), 4) for t in times], drop=8.0), f)
    from PIL import Image, ImageDraw
    for k, (name, col) in enumerate((("photo1.jpg", (40, 120, 200)), ("photo2.jpg", (200, 110, 40)))):
        im = Image.new("RGB", (3000, 2000), col)
        d = ImageDraw.Draw(im)
        for i in range(0, 3000, 150):
            d.line([(i, 0), (i + 600, 2000)], fill=(255, 255, 255), width=12)
        d.ellipse([1200, 700, 1800, 1300], fill=(250, 220, 60))
        im.save(os.path.join(out, "photos", name), quality=92)
    if shutil.which("sips"):
        src = os.path.join(out, "photos", "photo2.jpg")
        subprocess.run(["sips", "-s", "format", "heic", src, "--out", os.path.join(out, "photos", "photo2.heic")],
                       check=True, capture_output=True)
    return out


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vlog_synth"))
