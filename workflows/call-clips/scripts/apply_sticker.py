#!/usr/bin/env python3
"""Paste an RGBA sticker over a tracked face, frame by frame.

Pass 2 of the mask pipeline. Reads the track from track_face.py and pipes
composited frames into ffmpeg, keeping the source audio.

Usage:
  apply_sticker.py VIDEO --track track.json --sticker cat.png --out masked.mp4
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import alpha_paste     # vstudio.draw.alpha_paste, centred, BGR frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--track", required=True)
    ap.add_argument("--sticker", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=2.40,
                    help="sticker width as a multiple of the tracked face width")
    ap.add_argument("--y-offset", type=float, default=-0.031,
                    help="vertical nudge as a fraction of sticker height; negative = up")
    ap.add_argument("--bob", type=float, default=0.0,
                    help="idle bob amplitude in px (0 = off)")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--frames-dir", default=None,
                    help="also dump every Nth composited frame here for review")
    ap.add_argument("--frames-every", type=int, default=100)
    args = ap.parse_args()

    tr = json.load(open(args.track))
    cxs, cys, ws = tr["cx"], tr["cy"], tr["w"]
    fps = tr["fps"]

    sticker = np.array(Image.open(args.sticker).convert("RGBA"))
    s_h0, s_w0 = sticker.shape[:2]

    cap = cv2.VideoCapture(args.video)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
        "-i", args.video, "-map", "0:v", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", args.out,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    cache = {}
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        j = min(i, len(cxs) - 1)
        target_w = max(24, int(round(ws[j] * args.scale)))
        if target_w not in cache:
            th = int(round(target_w * s_h0 / s_w0))
            cache[target_w] = np.array(
                Image.fromarray(sticker).resize((target_w, th), Image.LANCZOS))
        st = cache[target_w]
        y = cys[j] + args.y_offset * st.shape[0]
        if args.bob:
            y += args.bob * np.sin(2 * np.pi * i / (fps * 2.4))
        alpha_paste(frame, st, cxs[j], y)
        if args.frames_dir and i % args.frames_every == 0:
            cv2.imwrite(f"{args.frames_dir}/m_{i:05d}.jpg", frame)
        proc.stdin.write(frame.tobytes())
        i += 1

    cap.release()
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        sys.exit(f"ffmpeg failed ({rc})")
    print(f"composited {i} frames -> {args.out}")


if __name__ == "__main__":
    main()
