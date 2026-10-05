#!/usr/bin/env python3
"""Pull stills out of a video for covers.

  sheet    sample every N seconds into a labelled contact sheet, to pick a talking (mid-word,
           eyes-on-camera) face frame or the 4 collage moments (--save-frames keeps full-size stills)
  pick     rank frames by face expression (smile, eyes open, centred face; needs the face model)
  collage  4 pre-cropped cells for the collage pattern; per-time crop given as fractions of the
           real decoded frame (ffprobe sometimes reports the wrong size, so we decode first)
  face     one frame cropped to the face region, stopping above any burned-in caption band

Examples:
  python3 extract_frames.py sheet  my-talk.mp4 work/cover_src --every 5
  python3 extract_frames.py pick   my-talk.mp4 work/cover_src --top 6
  python3 extract_frames.py collage my-talk.mp4 work/cover_src 2.5 37 76 80:face
  python3 extract_frames.py face   my-talk.mp4 work/cover_src/face_src.png --t 70 --box 0,0.5,1,0.95
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import os
import tempfile

import cv2
import numpy as np

from vstudio import media


def grab(video, t):
    """Frame-accurate BGR still at t seconds (vstudio.media.grab_frame)."""
    fd, p = tempfile.mkstemp(suffix=".png"); os.close(fd)
    try:
        media.grab_frame(str(video), float(t), p)
        img = cv2.imread(p)
    except media.FFmpegError as e:
        raise SystemExit(f"could not decode a frame at t={t}: {e}")
    finally:
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


def cmd_sheet(a):
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sheet, ts = media.contact_sheet(str(a.video), str(out / "contact_sheet.jpg"), every=a.every, cols=6,
                                    thumb_w=240, max_frames=a.max)
    if a.save_frames:
        for t in ts:
            cv2.imwrite(str(out / f"cand_{t:07.1f}.png"), grab(a.video, t))
    print(sheet)


def cmd_pick(a):
    """Rank frames by face expression (smile, eyes open, centred) with vstudio.cover.score_frames."""
    from vstudio.cover import contact_sheet, score_frames
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    picks = [p for p in score_frames(str(a.video), top_n=a.top, step=a.step, min_gap=a.min_gap) if p["image"] is not None]
    if not picks:
        raise SystemExit("no face frames found (face model missing or no face); use `sheet` instead")
    for i, p in enumerate(picks, 1):
        cv2.imwrite(str(out / f"pick{i}_{p['t']:07.1f}.png"), p["image"])
    contact_sheet([p["image"] for p in picks], labels=[f"#{i} {p['t']:.1f}s {p['score']:+.2f}" for i, p in
                  enumerate(picks, 1)], cols=min(6, len(picks)), bgr=True).save(out / "picks_sheet.jpg", quality=88)
    print(out / "picks_sheet.jpg")


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
    s.add_argument("--save-frames", action="store_true", help="also write full-size cand_<t>.png per sample")
    k = sp.add_parser("pick"); k.add_argument("video"); k.add_argument("out")
    k.add_argument("--top", type=int, default=6); k.add_argument("--step", type=int, default=5, help="analyse every Nth frame")
    k.add_argument("--min-gap", type=float, default=2.0, help="seconds between picks")
    c = sp.add_parser("collage"); c.add_argument("video"); c.add_argument("out")
    c.add_argument("times", nargs="+", help="4 times; suffix ':face' to use --face-box for that cell")
    c.add_argument("--slide-box", default="0,0,1,0.3125", help="x0,y0,x1,y1 fractions (default top 600/1920)")
    c.add_argument("--face-box", default="0,0.5,1,0.9167", help="x0,y0,x1,y1 fractions (default y 960-1760)")
    c.add_argument("--cell-w", type=int, default=1080); c.add_argument("--cell-h", type=int, default=960)
    f = sp.add_parser("face"); f.add_argument("video"); f.add_argument("out")
    f.add_argument("--t", type=float, required=True)
    f.add_argument("--box", default="0,0.5,1,0.948", help="x0,y0,x1,y1 fractions; stop above the caption band")
    a = ap.parse_args()
    {"sheet": cmd_sheet, "pick": cmd_pick, "collage": cmd_collage, "face": cmd_face}[a.cmd](a)


if __name__ == "__main__":
    main()
