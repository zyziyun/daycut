#!/usr/bin/env python3
"""Matte a single still (speaker photo / video frame) to a transparent RGBA PNG.

Engines
  mediapipe (default)  MediaPipe selfie segmenter (Apache-2.0, vstudio.config.model("selfie_segmenter")),
                       refined with an edge-aware guided filter so hair edges follow the photo.
  rvm (optional)       Robust Video Matting via torch.hub. RVM is **GPL-3.0**: it is NOT vendored here;
                       torch.hub downloads it at runtime into your torch cache, on your machine, under its
                       own licence. Cleaner hair than the default; needs `pip install torch torchvision`.

Usage:
  python3 matte.py face_src.png face_alpha.png [--engine mediapipe|rvm] [--crop-bottom 0.1] [--trim]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse

import cv2
import numpy as np


def _box(x, r):
    return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), normalize=True, borderType=cv2.BORDER_REFLECT)


def guided(guide_gray, src, r=8, eps=1e-3):
    """He et al. guided filter (grey guide). Snaps a coarse mask to image edges."""
    I, p = guide_gray.astype(np.float32), src.astype(np.float32)
    mI, mp_ = _box(I, r), _box(p, r)
    a = (_box(I * p, r) - mI * mp_) / (_box(I * I, r) - mI * mI + eps)
    b = mp_ - a * mI
    return _box(a, r) * I + _box(b, r)


def matte_mediapipe(bgr, lo=0.25, hi=0.75, radius=None):
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    from vstudio.config import model

    opts = vision.ImageSegmenterOptions(base_options=mpt.BaseOptions(model_asset_path=model("selfie_segmenter")),
                                        output_confidence_masks=True, output_category_mask=False)
    with vision.ImageSegmenter.create_from_options(opts) as seg:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    conf = res.confidence_masks[-1].numpy_view().astype(np.float32)   # last mask = person
    conf = cv2.resize(conf, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    a = np.clip((conf - lo) / (hi - lo), 0, 1)
    a = a * a * (3 - 2 * a)                                            # smoothstep
    r = radius or max(4, int(min(bgr.shape[:2]) / 120))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    a = np.clip(guided(gray, a, r=r, eps=2e-3), 0, 1)
    # keep the solid interior solid, kill faint speckle far from the body
    core = cv2.erode((conf > 0.9).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    a[core] = 1.0
    a[a < 0.04] = 0.0
    return bgr, a


def matte_rvm(bgr, warmup=2):
    try:
        import torch
    except ImportError:
        raise SystemExit("--engine rvm needs torch (pip install torch torchvision). RVM itself is GPL-3.0 and is "
                         "downloaded at runtime by torch.hub; it is not part of this repo.")
    print("note: Robust Video Matting (PeterL1n/RobustVideoMatting) is GPL-3.0, fetched by torch.hub at runtime.")
    dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    net = torch.hub.load("PeterL1n/RobustVideoMatting", "mobilenetv3").to(dev).eval()
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    ten = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(dev)
    rec = [None] * 4
    with torch.no_grad():
        for _ in range(max(1, warmup)):           # RVM is recurrent: warm the state on the same frame
            fgr, pha, *rec = net(ten, *rec, 0.4)
    fg = (fgr.clamp(0, 1)[0].permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)
    return cv2.cvtColor(fg, cv2.COLOR_RGB2BGR), pha.clamp(0, 1)[0, 0].cpu().numpy()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("out", help="RGBA png")
    ap.add_argument("--engine", choices=["mediapipe", "rvm"], default="mediapipe")
    ap.add_argument("--lo", type=float, default=0.25, help="mediapipe: confidence mapped to alpha 0")
    ap.add_argument("--hi", type=float, default=0.75, help="mediapipe: confidence mapped to alpha 1")
    ap.add_argument("--crop-bottom", type=float, default=0.0,
                    help="drop this fraction of the height from the bottom (burned-in caption band)")
    ap.add_argument("--trim", action="store_true", help="crop to the alpha bounding box (+2%% margin)")
    ap.add_argument("--preview", action="store_true", help="also write <out>.check.png over a grey checker")
    a = ap.parse_args()

    bgr = cv2.imread(a.src)
    if bgr is None:
        raise SystemExit(f"cannot read {a.src}")
    fg, alpha = matte_rvm(bgr) if a.engine == "rvm" else matte_mediapipe(bgr, a.lo, a.hi)
    rgba = np.dstack([fg, (alpha * 255).astype(np.uint8)])
    if a.crop_bottom > 0:
        rgba = rgba[: int(rgba.shape[0] * (1 - a.crop_bottom))]
    if a.trim:
        ys, xs = np.nonzero(rgba[..., 3] > 8)
        if len(xs):
            m = int(0.02 * max(rgba.shape[:2]))
            rgba = rgba[max(0, ys.min() - m): ys.max() + m, max(0, xs.min() - m): xs.max() + m]
    cv2.imwrite(a.out, rgba)
    h, w = rgba.shape[:2]
    print(f"{a.out}  {w}x{h}  aspect {w / h:.3f}  (size the template's .face-wrap to this aspect)")
    if a.preview:
        chk = (((np.indices((h, w)) // 24).sum(0) % 2) * 60 + 120).astype(np.float32)[..., None].repeat(3, 2)
        al = rgba[..., 3:4].astype(np.float32) / 255
        cv2.imwrite(str(pathlib.Path(a.out).with_suffix(".check.png")),
                    (rgba[..., :3] * al + chk * (1 - al)).astype(np.uint8))


if __name__ == "__main__":
    main()
