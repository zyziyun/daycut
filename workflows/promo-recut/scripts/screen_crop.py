#!/usr/bin/env python3
"""Privacy crop for screen recordings / captures: never show the browser chrome (tabs, URL bar, bookmarks bar:
they leak accounts and open tabs) or a native app's black title band.

`crop` on a pip window, a card (image or video) or the montage highlights:
  [x, y, w, h]   source pixels
  auto           detect_top_bar() on a few frames: Chrome / Safari header, or black rows at the top
  false          no crop
Unset = auto for files named like a screen recording (Screen Recording*.mov, 屏幕录制*, 录屏*, rec*.mov / .mp4),
else no crop. The cropped media is cached in work/clean/ (ffmpeg with vstudio.media's encoder selection, so the
bundled LGPL ffmpeg without libx264 works); the frame it lands in shows it cover-fit, so 16:9 framing is kept.

    python3 screen_crop.py "inputs/Screen Recording 2026-01-01.mov"      # print the detected crop
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import hashlib
import os
import re
import shutil

import numpy as np

from vstudio import media  # noqa: E402

VIDEO_EXT = (".mov", ".mp4", ".m4v", ".mkv", ".webm")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
RECORDING_RE = re.compile(r"^(screen ?recording|screen ?capture|屏幕录制|录屏|rec(?=[\d_\-\s.]|$))", re.I)


def looks_like_recording(path):
    """A file named like a screen recording (Screen Recording*.mov, 屏幕录制*, 录屏*, rec1.mov ...)."""
    b = os.path.basename(str(path))
    return b.lower().endswith(VIDEO_EXT) and bool(RECORDING_RE.match(b))


def resolve_spec(spec, path):
    """Config `crop` -> "auto" | [x, y, w, h] | None. Unset (None) = auto for screen recordings."""
    if spec is None:
        return "auto" if looks_like_recording(path) else None
    if spec is False or spec == "none" or spec == "off":
        return None
    if spec is True or spec == "auto":
        return "auto"
    v = [int(round(float(x))) for x in spec]
    if len(v) != 4 or v[2] <= 0 or v[3] <= 0:
        raise ValueError(f"crop {spec!r}: want [x, y, w, h] (source px), auto or false")
    return v


# ---------------------------------------------------------------- detection
def _gray(frame):
    a = np.asarray(frame, dtype=np.float32)
    if a.ndim == 3:
        a = a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    return a


def detect_top_bar(frames, max_frac=0.2):
    """Rows to drop at the top of a screen recording (0 = nothing found). frames: HxW(x3) arrays (a few
    samples of one recording; their per-pixel median is analysed, so moving content averages out).

      1. black band (native-app recording, e.g. 32 rows at the top of a 1920x1112 capture);
      2. browser header over a DARK page: the header rows are light (row mean ~230) and the page starts with
         a jump to dark (~15): the first row of that jump (+2 rows past the border: 124 in a 1920x1080 Chrome capture);
      3. browser header over a LIGHT page: the bookmarks / toolbar bar ends in a thin uniform border line;
         the lowest such line in the top band, with a light header above it -> the row after it.
    Only the top `max_frac` of the frame is searched."""
    g = np.median(np.stack([_gray(f) for f in frames]), axis=0) if len(frames) > 1 else _gray(frames[0])
    H = g.shape[0]
    lim = max(8, int(H * max_frac))
    rm, rs = g.mean(axis=1), g.std(axis=1)
    # 1. black band
    n = 0
    while n < lim and rm[n] < 10 and rs[n] < 6:
        n += 1
    if 4 <= n < lim and rm[n:n + 20].mean() > 14:
        return n
    lo = max(6, int(H * 0.025))
    pad = max(1, round(H * 0.002))                # past the anti-aliased border / shadow under the bar
    # 2. light header -> dark page
    for y in range(lo, lim):
        if rm[y] < 90 and rm[y:y + 10].mean() < 90 and rm[max(0, y - 6):y].mean() > 150 and rm[:y].mean() > 120:
            return y + pad
    # 3. light page: lowest thin uniform border line under a light header
    best = 0
    for y in range(lo, min(lim, H - 3)):
        if rs[y] < 10 and rm[:y].mean() > 150 and abs(rm[y] - rm[y - 2]) > 5 and abs(rm[y] - rm[y + 2]) > 5 \
                and rs[y - 2] < 40:
            best = y + 1
    return best + pad if best else 0


def sample_frames(path, n=5, workdir=None):
    """n evenly spaced frames of a video (or the image itself) as RGB arrays."""
    from PIL import Image
    if str(path).lower().endswith(IMAGE_EXT):
        return [np.asarray(Image.open(path).convert("RGB"))]
    dur = media.duration(path)
    tmp = workdir or os.path.dirname(os.path.abspath(path))
    out = []
    for k in range(n):
        f = os.path.join(tmp, f".crop_probe_{os.getpid()}_{k}.png")
        try:
            media.grab_frame(path, dur * (k + 0.5) / n, f, preroll=2.0)
            out.append(np.asarray(Image.open(f).convert("RGB")))
        except Exception:      # noqa: BLE001 - a frame that does not decode is skipped
            pass
        finally:
            if os.path.exists(f):
                os.remove(f)
    if not out:
        raise RuntimeError(f"crop auto: no frame decoded from {path}")
    return out


def frame_size(path):
    if str(path).lower().endswith(IMAGE_EXT):
        from PIL import Image
        return Image.open(path).size
    p = media.probe(path)
    return p["w"], p["h"]


def auto_crop(path, workdir=None):
    """[x, y, w, h] that drops the detected top bar, or None when none is found."""
    fr = sample_frames(path, workdir=workdir)
    y = detect_top_bar(fr)
    if not y:
        return None
    h, w = fr[0].shape[:2]
    y += y % 2                                    # even sizes for yuv420p
    return [0, y, w - w % 2, (h - y) - (h - y) % 2]


# ---------------------------------------------------------------- apply
def clean(path, spec, workdir, log=print):
    """Media to use for `path` under config crop `spec`: the original, or a cropped copy cached in
    <workdir>/clean/. Returns (path, [x, y, w, h] or None)."""
    c = resolve_spec(spec, path)
    if c is None:
        return path, None
    os.makedirs(os.path.join(workdir, "clean"), exist_ok=True)
    if c == "auto":
        c = auto_crop(path, os.path.join(workdir, "clean"))
        if c is None:
            log(f"crop auto: no browser / title bar found in {os.path.basename(path)} - used as is")
            return path, None
    W, H = frame_size(path)
    x, y, w, h = c
    w, h = min(w, W - x), min(h, H - y)
    if (x, y, w, h) == (0, 0, W, H):
        return path, None
    st = os.stat(path)
    sig = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime}|{x},{y},{w},{h}".encode()).hexdigest()[:10]
    stem, ext = os.path.splitext(os.path.basename(path))
    is_img = ext.lower() in IMAGE_EXT
    out = os.path.join(workdir, "clean", f"{re.sub(r'[^A-Za-z0-9._-]', '_', stem)}-{sig}{ext if is_img else '.mp4'}")
    if not os.path.exists(out):
        tmp = out + ".part" + (ext if is_img else ".mp4")
        if is_img:
            from PIL import Image
            Image.open(path).crop((x, y, x + w, y + h)).save(tmp)
        else:
            has_a = media.probe(path).get("has_audio")
            media.run(["ffmpeg", "-y", "-i", path, "-vf", f"crop={w}:{h}:{x}:{y},format=yuv420p",
                       *media.delivery_args(crf=16, preset="fast", audio=bool(has_a), faststart=True), tmp])
        shutil.move(tmp, out)
    log(f"crop {os.path.basename(path)}: [{x}, {y}, {w}, {h}] -> {os.path.relpath(out, workdir)}")
    return out, [x, y, w, h]


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(a, auto_crop(a))
