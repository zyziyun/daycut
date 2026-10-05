#!/usr/bin/env python3
"""Per-frame talking-head video retouch: MLS face slim + light eye open, de-shine, three-band skin smoothing
with texture kept, subtle makeup (lips / blush / brows; preset "natural"), temporally stable.

Temporal stability (all from vstudio.face / vstudio.retouch; this file adds chunking + re-encode):
  - landmarks: VIDEO-mode landmarker on a face crop at adequate resolution (VideoFaceTracker), One Euro
    filtered per landmark (eyes / lips / brows more responsive, outline steadier), reset on cuts;
  - masks: segmentation EMA'd in a landmark-anchored canonical face frame, everything else built from the
    smoothed landmarks, so neither the skin mask nor the makeup flickers;
  - warp: coarse MLS grid (160 px) and the field is reused while the controls move < 0.35 px;
  - chunks: every worker starts WARMUP frames before its first written frame, so filter / tracker / mask
    state is continuous across chunk seams (no jumps).

usage:
  python3 retouch_video.py body_v.mp4 x --test 300,2500,4800     # side-by-side stills test_<f>.jpg, check first
  python3 retouch_video.py body_v.mp4 body_rt.mp4 --workers 5
  python3 retouch_video.py body_v.mp4 body_rt.mp4 --makeup 0      # skin + reshape only
Defaults: persona retouch.video.<knob> overrides the built-ins (e.g. retouch.video.makeup), CLI flags override both.
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
from vstudio.retouch import PRESETS, RetouchState, retouch

# Video defaults (measured on 1080x1920 iPhone footage, glasses-wearing speaker): eye enlarge stays tiny
# because lenses warp; makeup subtle (0.3 x the "natural" preset); blemish removal off (per-frame
# component detection is the one step that is not temporally anchored).
VIDEO_DEFAULTS = dict(slim=0.042, eye=0.04, eye_extra=0.0, shine=0.7, shine_feather=2.5,
                      smooth=0.55, light=0.04, makeup=0.3, body=0.0, pores=0.8, tone=0.3, blemish=0.0,
                      undereye=0.3, neck=0.5, grid=160)
STR_KNOBS = dict(preset="natural", glasses="auto")
WARMUP = 15                 # frames each chunk processes (and discards) before its first written frame
MIN_FACE_PX = 150           # face narrower than this: left untouched
P = dict(VIDEO_DEFAULTS, **STR_KNOBS)


class Retoucher:
    """Tracker + temporal retouch state for one continuous run of frames."""

    def __init__(self, fps, opts):
        self.opts = dict(opts)
        self.tr = VF.VideoFaceTracker(fps)
        self.st = RetouchState(video=True)
        self.resets = 0

    def __call__(self, img, idx):
        f = self.tr(img, idx)
        if f is None:
            self.st.reset(); return img
        if np.ptp(f["pts"][:, 0]) < MIN_FACE_PX:            # face too small to retouch safely
            return img
        if self.tr.sm.resets != self.resets:                 # cut / re-acquired face: drop mask + warp state
            self.resets = self.tr.sm.resets; self.st.reset()
        return retouch(img, f={"pts": f["pts"], "blend": f["blend"]}, lm=None, state=self.st, **self.opts)

    def close(self):
        self.tr.close()


def _rate(src):
    """Exact source frame rate (e.g. 30000/1001) so the re-encode never drifts against the audio."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate',
                        '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.strip()
    return r or '30'


def _fps(rate):
    a, _, b = rate.partition('/')
    return float(a) / float(b or 1)


def run_chunk(args):
    src, a, b, out, opts = args
    rate = _rate(src)
    rt = Retoucher(_fps(rate), opts)
    s = max(0, a - WARMUP)
    cap = cv2.VideoCapture(src); cap.set(cv2.CAP_PROP_POS_FRAMES, s)
    W, H = int(cap.get(3)), int(cap.get(4))
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', rate,
                           '-i', '-', '-c:v', 'libx264', '-crf', '12', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                           '-video_track_timescale', '30000', out], stdin=subprocess.PIPE)
    try:
        for i in range(s, b):
            ok, img = cap.read()
            if not ok:
                break
            r = rt(img, i)
            if i >= a:
                ff.stdin.write(r.tobytes())
    finally:
        rt.close()
        ff.stdin.close(); ff.wait()
    return out


def main():
    ap = argparse.ArgumentParser(description="Per-frame portrait retouch of a talking-head body video.")
    ap.add_argument('src'); ap.add_argument('out', help="output mp4 (ignored with --test)")
    ap.add_argument('--test', default='', help="comma-separated frame indices -> test_<f>.jpg before/after")
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--start', type=int, default=0, help="first frame (default 0)")
    ap.add_argument('--frames', type=int, default=0, help="number of frames (default: to the end)")
    for k in VIDEO_DEFAULTS:
        ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float, default=None)
    ap.add_argument('--preset', choices=sorted(PRESETS), default=None, help="makeup preset (default natural)")
    ap.add_argument('--glasses', choices=('auto', 'none', 'thin', 'thick'), default=None)
    o = ap.parse_args()
    P.update((persona().get("retouch") or {}).get("video") or {})
    P.update({k: getattr(o, k) for k in list(VIDEO_DEFAULTS) + list(STR_KNOBS) if getattr(o, k) is not None})
    rate = _rate(o.src); fps = _fps(rate)
    if o.test:
        cap = cv2.VideoCapture(o.src)
        for fi in map(int, o.test.split(',')):
            rt = Retoucher(fps, P)                       # warm up like a chunk would
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, fi - WARMUP))
            img = r = None
            for i in range(max(0, fi - WARMUP), fi + 1):
                ok, img = cap.read()
                if not ok:
                    break
                r = rt(img, i)
            rt.close()
            if r is None:
                print('cannot read frame', fi); continue
            pair = np.hstack([img, r])
            if img.shape[0] > img.shape[1]:          # vertical: drop top/bottom margins; landscape: keep whole
                pair = pair[int(img.shape[0] * .1):int(img.shape[0] * .78)]
            cv2.imwrite(f'test_{fi}.jpg', pair, [cv2.IMWRITE_JPEG_QUALITY, 88])
            print('wrote', f'test_{fi}.jpg')
        return
    n = int(cv2.VideoCapture(o.src).get(cv2.CAP_PROP_FRAME_COUNT))
    a0 = max(0, o.start); n = min(n, a0 + o.frames) if o.frames else n
    k = max(1, o.workers); step = (n - a0 + k - 1) // k
    tmp = os.path.join(os.path.dirname(os.path.abspath(o.out)), 'rt'); os.makedirs(tmp, exist_ok=True)
    jobs = [(o.src, a0 + i * step, min(n, a0 + (i + 1) * step), os.path.join(tmp, f'c{i}.mp4'), dict(P))
            for i in range(k) if a0 + i * step < n]
    with Pool(len(jobs)) as pool:
        outs = pool.map(run_chunk, jobs)
    lst = os.path.join(tmp, 'list.txt')
    open(lst, 'w').write(''.join(f"file '{os.path.basename(x)}'\n" for x in outs))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', o.out], check=True)
    print('wrote', o.out)


if __name__ == '__main__':
    main()
