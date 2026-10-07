#!/usr/bin/env python3
"""Build the built-in sample recording (packaging/sample/): a ~2-minute narrated screen lesson, made entirely by us.

    python3 apps/desk/scripts/sample/make_sample.py            # needs ffmpeg, Pillow and mlx-audio (Kokoro, Apple Silicon)

No camera, no people, no third-party media: the voice is Kokoro-82M (Apache-2.0 weights, voice af_heart), the visuals
are slides drawn here with SIL OFL fonts (the engine's font cache, else Pillow's default). The narration has a few
real pauses, filler words and one restarted sentence on purpose, so the first batch has something visible to clean
up. The output is released under CC0 (packaging/sample/LICENSE.txt).

Deterministic enough to rebuild: same script + same Kokoro weights -> the same words and timing.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
DESK = HERE.parents[1]
OUT = DESK / "packaging" / "sample"

W, H = 1080, 1920          # vertical: TikTok / Shorts / Reels fit it as is (no reframe), captions go below the slide
BG, FG, MUTED, ACCENT = (17, 20, 27), (236, 238, 242), (140, 148, 163), (255, 140, 66)

# (slide, line, pause after in seconds). Fillers / a restart are part of the script so cleanup has work to do.
SLIDES = [
    ("One recording, a week of posts", ["Record once", "Cut many", "Post everywhere"]),
    ("1 · Plan the beats", ["Three to five points", "One sentence each", "A clear ending"]),
    ("2 · Record in one take", ["Pause between points", "Restart a line, don't stop", "Keep the camera rolling"]),
    ("3 · Let the batch do the rest", ["Cut pauses and fillers", "Captions for every clip", "One export per platform"]),
    ("Try it", ["Review the flagged clips", "Fix by chatting", "Publish when it feels right"]),
]
SCRIPT = [
    (0, "Hi! This is a sample recording that ships with Reelfold, so you can try a whole batch without your own footage.", 0.6),
    (0, "Um, the idea is simple.", 1.4),
    (0, "You record once. You cut it into many short clips. Then you post them on every platform.", 0.7),
    (0, "In the next two minutes I'll walk through three habits that make this, uh, really easy.", 2.0),
    (1, "The first habit is", 0.5),
    (1, "The first habit is to plan the beats before you press record.", 0.6),
    (1, "Write down three to five points, one sentence each.", 0.5),
    (1, "And, um, know how you want to end, so every clip has a clear landing.", 1.8),
    (1, "If a point needs a long explanation, it's probably two points.", 0.9),
    (2, "The second habit: record it in one take.", 0.6),
    (2, "Leave a short pause between points. Those pauses become the natural cut lines for your clips.", 0.8),
    (2, "If you stumble, just, uh, restart the sentence. Don't stop the recording.", 1.6),
    (2, "The editor keeps the last good take and drops the rest, so a restart costs you nothing.", 2.2),
    (3, "The third habit is to let the batch do the boring part.", 0.6),
    (3, "Pauses and filler words get cut, like the ones in this very sample.", 0.6),
    (3, "Every clip gets captions, a cover and its own copy.", 0.5),
    (3, "And you export one file per platform, in the right shape, with the right loudness.", 1.9),
    (4, "So, um, here is what to do now.", 0.8),
    (4, "Open the review, look only at the clips that were flagged, and fix them by chatting.", 0.7),
    (4, "When a clip feels right, publish it. That's it. Thanks for trying the sample!", 1.2),
]


def font(size, bold=False):
    from PIL import ImageFont
    cache = pathlib.Path(os.environ.get("VSTUDIO_CACHE") or pathlib.Path.home() / ".cache" / "video-studio") / "fonts"
    for name in (["NotoSansSC-Bold.otf"] if bold else ["NotoSansSC-Regular.otf"]):
        p = cache / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def slide_png(path, idx, shown):
    """Slide ``idx`` with its first ``shown`` bullets revealed (a talking-head-free 'screen' lesson). The lower part of
    the frame stays empty: that is where captions and the platforms' own buttons go."""
    from PIL import Image, ImageDraw
    title, bullets = SLIDES[idx]
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 10], fill=ACCENT)
    d.text((96, 200), "Reelfold sample · CC0", font=font(30), fill=MUTED)
    y = 300
    words, line = title.split(" "), ""
    for w in words:                                            # wrap the title at ~18 characters
        if len(line + " " + w) > 18 and line:
            d.text((96, y), line, font=font(76, True), fill=FG)
            y, line = y + 100, w
        else:
            line = (line + " " + w).strip()
    d.text((96, y), line, font=font(76, True), fill=FG)
    y += 170
    for k, b in enumerate(bullets):
        on = k < shown
        d.ellipse([100, y + 22, 124, y + 46], fill=ACCENT if on else (52, 58, 70))
        d.text((156, y), b, font=font(50), fill=FG if on else (70, 76, 90))
        y += 110
    for k in range(len(SLIDES)):                                  # progress dots
        d.ellipse([96 + k * 34, y + 40, 116 + k * 34, y + 60], fill=ACCENT if k <= idx else (52, 58, 70))
    im.save(path)


def _kokoro(text, dst):
    """One sentence -> wav, or None when Kokoro's vocoder trips over its length (a known shape bug in mlx-audio)."""
    for speed in ("1.0", "0.95", "1.05", "0.9"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "-m", "mlx_audio.tts.generate", "--model", "mlx-community/Kokoro-82M-bf16",
                            "--text", text, "--voice", "af_heart", "--speed", speed, "--lang_code", "a", "--join_audio",
                            "--audio_format", "wav", "--output_path", tmp, "--file_prefix", "k"], capture_output=True, text=True)
            wavs = sorted(pathlib.Path(tmp).glob("k*.wav"))
            if wavs:
                run(["ffmpeg", "-y", "-v", "error", "-i", str(wavs[0]), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
                return dst
    return None


def synth(text, dst):
    """Kokoro-82M (mlx-audio), American English voice af_heart -> 48 kHz mono wav. Called directly (not vstudio.tts)
    to pin the language code; sentence by sentence (then clause by clause) so one unlucky length can't fail a line."""
    import re
    work = pathlib.Path(tempfile.mkdtemp())
    pieces = []
    for k, sent in enumerate(x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()):
        w = _kokoro(sent, work / f"s{k}.wav")
        if w is None:
            for j, part in enumerate(x for x in re.split(r"(?<=,)\s+", sent) if x.strip()):
                w2 = _kokoro(part, work / f"s{k}_{j}.wav")
                if w2 is None:
                    raise SystemExit(f"kokoro failed for {part!r}")
                pieces.append(w2)
        else:
            pieces.append(w)
    if len(pieces) == 1:
        shutil.move(pieces[0], dst)
    else:
        gap = work / "gap.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.12", "-c:a", "pcm_s16le", str(gap)])
        lst = work / "l.txt"
        lst.write_text("".join(f"file '{p}'\nfile '{gap}'\n" for p in pieces[:-1]) + f"file '{pieces[-1]}'\n")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(dst)])
    shutil.rmtree(work, ignore_errors=True)
    return dst


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"{cmd[0]} failed:\n{r.stderr[-2000:]}")
    return r.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).strip())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        # 1) voice, line by line, with silence after each line
        parts, timeline, t = [], [], 0.6
        silence = lambda s, name: run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                                       "-t", f"{s:.3f}", "-c:a", "pcm_s16le", str(tmp / name)]) or tmp / name
        parts.append(silence(0.6, "lead.wav"))
        for k, (slide, text, pause) in enumerate(SCRIPT):
            wav = synth(text, tmp / f"l{k:02d}.wav")
            dur = duration(wav)
            timeline.append(dict(slide=slide, start=round(t, 2), end=round(t + dur, 2), text=text))
            parts.append(pathlib.Path(wav))
            parts.append(silence(pause, f"p{k:02d}.wav"))
            t += dur + pause
        lst = tmp / "parts.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        voice = tmp / "voice.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(voice)])
        total = duration(voice)

        # 2) slides: a bullet appears with the first line that talks about it (evenly spread over the slide's lines)
        frames, cur = [], None
        for k, ln in enumerate(timeline):
            lines = [x for x in timeline if x["slide"] == ln["slide"]]
            pos = lines.index(ln)
            shown = 0 if ln["slide"] == 0 and pos == 0 else min(len(SLIDES[ln["slide"]][1]),
                                                                  1 + pos * len(SLIDES[ln["slide"]][1]) // len(lines))
            key = (ln["slide"], shown)
            if key != cur:
                frames.append((ln["start"] if frames else 0.0, key))
                cur = key
        concat = []
        for k, (start, (s, shown)) in enumerate(frames):
            png = tmp / f"s{k:02d}.png"
            slide_png(png, s, shown)
            end = frames[k + 1][0] if k + 1 < len(frames) else total
            concat.append(f"file '{png}'\nduration {end - start:.3f}\n")
        concat.append(f"file '{tmp / f's{len(frames) - 1:02d}.png'}'\n")
        (tmp / "slides.txt").write_text("".join(concat))

        # 3) mux: small H.264 (static slides compress to almost nothing) + AAC mono
        dst = OUT / "reelfold-sample.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "slides.txt"), "-i", str(voice),
             "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-tune", "stillimage",
             "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-ar", "48000", "-shortest", "-movflags", "+faststart",
             "-metadata", "title=Reelfold sample: one recording, a week of posts", "-metadata", "copyright=CC0 1.0",
             str(dst)])
        (OUT / "script.json").write_text(json.dumps(dict(duration=round(duration(dst), 2), voice="Kokoro-82M af_heart",
                                                          lines=timeline), indent=1, ensure_ascii=False) + "\n")
        print(f"{dst} {dst.stat().st_size / 1e6:.1f} MB {duration(dst):.1f} s")


if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found")
    main()
