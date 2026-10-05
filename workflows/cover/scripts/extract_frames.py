#!/usr/bin/env python3
"""Pull stills out of a video for covers.

  sheet    sample every N seconds into a labelled contact sheet, to pick a talking (mid-word,
           eyes-on-camera) face frame or the 4 collage moments
  collage  4 pre-cropped cells for the collage pattern; per-time crop given as fractions of the
           real decoded frame (ffprobe sometimes reports the wrong size, so we decode first)
  face     one frame cropped to the face region, stopping above any burned-in caption band

Examples:
  python3 extract_frames.py sheet  my-talk.mp4 work/cover_src --every 5
  python3 extract_frames.py collage my-talk.mp4 work/cover_src 2.5 37 76 80:face
  python3 extract_frames.py face   my-talk.mp4 work/cover_src/face_src.png --t 70 --box 0,0.5,1,0.95
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import subprocess
import tempfile

import cv2
import numpy as np

from vstudio.config import font


def grab(video, t):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        p = f.name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", p], check=True)
    img = cv2.imread(p)
    pathlib.Path(p).unlink(missing_ok=True)
    if img is None:
        raise SystemExit(f"could not decode a frame at t={t}")
    return img


def crop_frac(img, box):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def fit_pad(img, W, H):
    h, w = img.shape[:2]
    s = min(W / w, H / h)
    r = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    out = np.zeros((H, W, 3), np.uint8)
    y, x = (H - r.shape[0]) // 2, (W - r.shape[1]) // 2
    out[y:y + r.shape[0], x:x + r.shape[1]] = r
    return out


def duration(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def cmd_sheet(a):
    from PIL import Image, ImageDraw, ImageFont
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    ts = list(np.arange(a.every / 2, duration(a.video), a.every))[: a.max]
    thumbs = []
    for t in ts:
        img = grab(a.video, t)
        cv2.imwrite(str(out / f"cand_{t:07.1f}.png"), img)
        th = cv2.cvtColor(cv2.resize(img, (240, int(240 * img.shape[0] / img.shape[1]))), cv2.COLOR_BGR2RGB)
        thumbs.append((t, Image.fromarray(th)))
    cols = 6; tw, thh = 240, thumbs[0][1].height
    sheet = Image.new("RGB", (cols * tw, ((len(thumbs) + cols - 1) // cols) * (thh + 30)), "black")
    d = ImageDraw.Draw(sheet); f = ImageFont.truetype(font("mono-bold"), 20)
    for i, (t, im) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (thh + 30)
        sheet.paste(im, (x, y)); d.text((x + 6, y + thh + 4), f"{t:.1f}s", font=f, fill="white")
    sheet.save(out / "contact_sheet.jpg", quality=88)
    print(out / "contact_sheet.jpg")


def cmd_collage(a):
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    slide = [float(v) for v in a.slide_box.split(",")]
    face = [float(v) for v in a.face_box.split(",")]
    for i, spec in enumerate(a.times[:4], 1):
        t, _, kind = spec.partition(":")
        cell = fit_pad(crop_frac(grab(a.video, float(t)), face if kind == "face" else slide), a.cell_w, a.cell_h)
        cv2.imwrite(str(out / f"q{i}.png"), cell)
    print(f"wrote q1..q{min(4, len(a.times))}.png to {out}")


def cmd_face(a):
    img = crop_frac(grab(a.video, a.t), [float(v) for v in a.box.split(",")])
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(a.out, img)
    print(a.out, img.shape[1], "x", img.shape[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("sheet"); s.add_argument("video"); s.add_argument("out")
    s.add_argument("--every", type=float, default=5.0); s.add_argument("--max", type=int, default=48)
    c = sp.add_parser("collage"); c.add_argument("video"); c.add_argument("out")
    c.add_argument("times", nargs="+", help="4 times; suffix ':face' to use --face-box for that cell")
    c.add_argument("--slide-box", default="0,0,1,0.3125", help="x0,y0,x1,y1 fractions (default top 600/1920)")
    c.add_argument("--face-box", default="0,0.5,1,0.9167", help="x0,y0,x1,y1 fractions (default y 960-1760)")
    c.add_argument("--cell-w", type=int, default=1080); c.add_argument("--cell-h", type=int, default=960)
    f = sp.add_parser("face"); f.add_argument("video"); f.add_argument("out")
    f.add_argument("--t", type=float, required=True)
    f.add_argument("--box", default="0,0.5,1,0.948", help="x0,y0,x1,y1 fractions; stop above the caption band")
    a = ap.parse_args()
    {"sheet": cmd_sheet, "collage": cmd_collage, "face": cmd_face}[a.cmd](a)


if __name__ == "__main__":
    main()
