"""Per-second clip scores and best-window picking (auto windows when the edit list gives none).

score = 0.35 sharpness + 0.30 motion (moderate motion preferred, a frozen or whipping frame scores low)
      + 0.20 brightness (mid-grey best, crushed or blown frames low) + 0.15 face (a face in frame).
Samples are grey 160-px thumbnails at 4 fps (faces: 1 fps, 480 px, vstudio.face when MediaPipe works).
Results are cached in <cache>/scores_<hash>.json keyed by path, size and mtime.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
import hashlib
import json
import os
import subprocess

import numpy as np

from vstudio import media

W_SHARP, W_MOTION, W_BRIGHT, W_FACE = 0.35, 0.30, 0.20, 0.15
MOTION_BEST = 8.0          # mean abs grey diff (0-255) between samples 0.25 s apart that reads as "lively"


def _decode_grey(src, fps=4.0, width=160):
    info = media.probe(src)
    w, h = info["display_w"] or 16, info["display_h"] or 9
    tw = width
    th = max(2, int(round(h * tw / w / 2)) * 2)
    cmd = [media.ffmpeg_bin(), "-v", "error", "-i", os.fspath(src), "-vf", f"fps={fps},scale={tw}:{th},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (tw * th)
    return np.frombuffer(raw[:n * tw * th], np.uint8).reshape(n, th, tw), info


def _faces_per_sec(src, dur):
    """{second: 1/0} via vstudio.face (MediaPipe); {} when unavailable."""
    try:
        from vstudio import face as F
        lm = F.landmarker(num_faces=1)
    except Exception:
        return {}
    out = {}
    try:
        info = media.probe(src)
        w, h = info["display_w"], info["display_h"]
        tw = 480
        th = max(2, int(round(h * tw / w / 2)) * 2)
        cmd = [media.ffmpeg_bin(), "-v", "error", "-i", os.fspath(src), "-vf", f"fps=1,scale={tw}:{th}",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        raw = subprocess.run(cmd, capture_output=True, check=True).stdout
        n = len(raw) // (tw * th * 3)
        for i in range(n):
            fr = np.frombuffer(raw[i * tw * th * 3:(i + 1) * tw * th * 3], np.uint8).reshape(th, tw, 3)
            try:
                out[i] = 1.0 if F.detect(lm, np.ascontiguousarray(fr)) else 0.0
            except Exception:
                out[i] = 0.0
    finally:
        try:
            lm.close()
        except Exception:
            pass
    return out


def clip_scores(src, cache_dir=None, faces=True):
    """Per-second scores for ``src``: dict(duration, fps, secs=[{t, score, sharp, motion, bright, face}])."""
    st = os.stat(src)
    key = hashlib.sha1(f"{os.path.abspath(src)}|{st.st_size}|{st.st_mtime}|{faces}|v1".encode()).hexdigest()[:16]
    cp = os.path.join(cache_dir, f"scores_{key}.json") if cache_dir else None
    if cp and os.path.exists(cp):
        with open(cp) as f:
            return json.load(f)
    import cv2
    fr, info = _decode_grey(src)
    dur = info["duration"] or len(fr) / 4.0
    n_sec = max(1, int(np.ceil(dur - 1e-6)))
    per = [[] for _ in range(n_sec)]
    prev = None
    for i, g in enumerate(fr):
        t = i / 4.0
        sharp = float(cv2.Laplacian(g, cv2.CV_32F).var())
        bright = float(g.mean())
        motion = float(np.abs(g.astype(np.int16) - prev).mean()) if prev is not None else None
        prev = g.astype(np.int16)
        k = min(n_sec - 1, int(t))
        per[k].append((sharp, bright, motion))
    fc = _faces_per_sec(src, dur) if faces else {}
    secs = []
    for k, rows in enumerate(per):
        if not rows:
            secs.append(dict(t=k, score=0.0, sharp=0.0, motion=0.0, bright=0.0, face=0.0))
            continue
        sharp = float(np.mean([r[0] for r in rows]))
        bright = float(np.mean([r[1] for r in rows]))
        ms = [r[2] for r in rows if r[2] is not None]
        motion = float(np.mean(ms)) if ms else 0.0
        s_sharp = float(np.clip(np.log10(sharp + 1.0) / 3.0, 0, 1))
        s_motion = float(np.exp(-((motion - MOTION_BEST) / MOTION_BEST) ** 2))
        s_bright = float(1 - np.clip(abs(bright - 125.0) / 125.0, 0, 1) ** 1.5)
        s_face = float(fc.get(k, 0.0))
        score = W_SHARP * s_sharp + W_MOTION * s_motion + W_BRIGHT * s_bright + W_FACE * s_face
        secs.append(dict(t=k, score=round(score, 4), sharp=round(sharp, 1), motion=round(motion, 2),
                         bright=round(bright, 1), face=s_face))
    res = dict(src=os.fspath(src), duration=dur, fps=info["fps"], secs=secs)
    if cp:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cp, "w") as f:
            json.dump(res, f)
    return res


def _curve(scores, step=0.25):
    secs = scores["secs"]
    dur = scores["duration"]
    ts = np.arange(0.0, max(step, dur), step)
    vals = np.array([secs[min(len(secs) - 1, int(t))]["score"] for t in ts]) if secs else np.zeros(len(ts))
    return ts, vals


def window_score(scores, start, length):
    ts, vals = _curve(scores)
    m = (ts >= start - 1e-6) & (ts < start + length - 1e-6)
    return float(vals[m].mean()) if m.any() else 0.0


def pick_window(scores, length, avoid=(), edge=0.3, step=0.25):
    """Start time of the best ``length``-second window (sliding mean of the per-second score), keeping
    ``edge`` s clear of the clip ends (dead heads/tails) when possible and penalising overlap with
    ``avoid`` [(a, b)] spans already used. Returns (start, mean score)."""
    dur = float(scores["duration"])
    if length >= dur - 1e-3:
        return 0.0, window_score(scores, 0.0, dur)
    lo = min(edge, max(0.0, dur - length) / 2)
    hi = max(lo, dur - length - lo)
    best = (lo, -1e9)
    ts, vals = _curve(scores, step)
    for s in np.arange(lo, hi + 1e-6, step):
        m = (ts >= s - 1e-6) & (ts < s + length - 1e-6)
        v = float(vals[m].mean()) if m.any() else 0.0
        ov = sum(max(0.0, min(s + length, b) - max(s, a)) for a, b in avoid) / max(length, 1e-6)
        v_eff = v - 0.6 * ov
        if v_eff > best[1] + 1e-9:
            best = (float(s), v_eff)
    return round(best[0], 3), round(window_score(scores, best[0], length), 4)


def best_second(scores):
    secs = scores["secs"] or [dict(t=0, score=0.0)]
    s = max(secs, key=lambda r: r["score"])
    return s["t"], s["score"]
