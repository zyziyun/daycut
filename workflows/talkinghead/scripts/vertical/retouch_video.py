#!/usr/bin/env python3
"""Per-frame talking-head video retouch: MLS face slim + light eye open, de-shine, skin smoothing with
texture kept, gentle face light. Landmarks are EMA-smoothed across frames so the warp never jitters.
All image ops come from vstudio.retouch / vstudio.face; this file only adds the temporal smoothing,
chunked multiprocessing and the frame-exact re-encode.

usage:
  python3 retouch_video.py body_v.mp4 x --test 300,2500,4800     # side-by-side stills test_<f>.jpg, check first
  python3 retouch_video.py body_v.mp4 body_rt.mp4 --workers 5     # ~1 s/frame/worker
Defaults: persona retouch.video.<knob> overrides the built-ins, CLI flags override both.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
import argparse
import os
import subprocess
from multiprocessing import Pool

import cv2
import numpy as np

from vstudio import face as VF
from vstudio.config import persona
from vstudio.retouch import retouch

# Video defaults (measured on 1080x1920 iPhone footage, glasses-wearing speaker): eye enlarge stays tiny
# because lenses warp; makeup off because it flickers frame to frame.
VIDEO_DEFAULTS = dict(slim=0.042, eye=0.04, eye_extra=0.0, shine=0.7, shine_feather=2.5,
                      smooth=0.55, light=0.04, makeup=0.0, body=0.0)
P = dict(VIDEO_DEFAULTS)


class Smoother:
    """EMA over the 478 landmarks; resets on a big jump (cut / new face) so it never lags across a cut."""
    def __init__(s, a=0.55, reset_px=25):
        s.a = a; s.reset = reset_px; s.prev = None

    def __call__(s, pts):
        if s.prev is None or np.abs(pts - s.prev).mean() > s.reset:
            s.prev = pts
        else:
            s.prev = s.prev * (1 - s.a) + pts * s.a
        return s.prev


def process_frame(lm, sm, img):
    small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    f = VF.main_face(VF.detect(lm, small))
    if f is None:
        sm.prev = None; return img
    pts = sm(f["pts"] * 2.0)
    if np.ptp(pts[:, 0]) < 150:            # face too small to retouch safely
        return img
    # f given + lm=None: vstudio.retouch skips re-detection, and its feathered face-region mask blends
    # the warp ROI back in (no streaks at the ROI edge).
    return retouch(img, f={"pts": pts, "blend": f["blend"]}, lm=None, **P)


def _rate(src):
    """Exact source frame rate (e.g. 30000/1001) so the re-encode never drifts against the audio."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate',
                        '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.strip()
    return r or '30'


def run_chunk(args):
    src, a, b, out, opts = args
    P.update(opts)
    lm = VF.landmarker(1); sm = Smoother()
    cap = cv2.VideoCapture(src); cap.set(cv2.CAP_PROP_POS_FRAMES, a)
    W, H = int(cap.get(3)), int(cap.get(4))
    fps = _rate(src)
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', fps,
                           '-i', '-', '-c:v', 'libx264', '-crf', '12', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                           '-video_track_timescale', '30000', out], stdin=subprocess.PIPE)
    for _ in range(a, b):
        ok, img = cap.read()
        if not ok:
            break
        ff.stdin.write(process_frame(lm, sm, img).tobytes())
    ff.stdin.close(); ff.wait(); return out


def main():
    ap = argparse.ArgumentParser(description="Per-frame portrait retouch of a talking-head body video.")
    ap.add_argument('src'); ap.add_argument('out', help="output mp4 (ignored with --test)")
    ap.add_argument('--test', default='', help="comma-separated frame indices -> test_<f>.jpg before/after")
    ap.add_argument('--workers', type=int, default=5)
    for k in VIDEO_DEFAULTS:
        ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float, default=None)
    o = ap.parse_args()
    P.update((persona().get("retouch") or {}).get("video") or {})
    P.update({k: getattr(o, k) for k in VIDEO_DEFAULTS if getattr(o, k) is not None})
    if o.test:
        lm = VF.landmarker(1); cap = cv2.VideoCapture(o.src)
        for fi in map(int, o.test.split(',')):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi); ok, img = cap.read()
            if not ok:
                print('cannot read frame', fi); continue
            r = process_frame(lm, Smoother(), img)
            pair = np.hstack([img, r])
            if img.shape[0] > img.shape[1]:          # vertical: drop top/bottom margins; landscape: keep whole
                pair = pair[int(img.shape[0] * .1):int(img.shape[0] * .78)]
            cv2.imwrite(f'test_{fi}.jpg', pair, [cv2.IMWRITE_JPEG_QUALITY, 88])
            print('wrote', f'test_{fi}.jpg')
        return
    n = int(cv2.VideoCapture(o.src).get(cv2.CAP_PROP_FRAME_COUNT))
    k = o.workers; step = (n + k - 1) // k; os.makedirs('rt', exist_ok=True)
    jobs = [(o.src, i * step, min(n, (i + 1) * step), f'rt/c{i}.mp4', dict(P)) for i in range(k)]
    with Pool(k) as pool:
        outs = pool.map(run_chunk, jobs)
    open('rt/list.txt', 'w').write(''.join(f"file '{os.path.basename(x)}'\n" for x in outs))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', 'rt/list.txt', '-c', 'copy', o.out], check=True)
    print('wrote', o.out)


if __name__ == '__main__':
    main()
