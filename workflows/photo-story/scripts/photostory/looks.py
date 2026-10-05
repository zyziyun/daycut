"""Looks: film grain, vignette, memory-film grade (scratches, dust, flicker), light leak, ink noise,
torn-edge profile, canvas background, paper texture."""
import random

import cv2
import numpy as np


def make_grain(C, n=6):
    r = np.random.default_rng(7)
    out = []
    for _ in range(n):
        g = r.normal(0, 1, (C.BOX_H // 2, C.BOX_W // 2)).astype(np.float32)
        out.append(cv2.resize(g, (C.BOX_W, C.BOX_H), interpolation=cv2.INTER_LINEAR)[..., None])
    return out


def make_leak(C):
    im = np.zeros((C.BOX_H, C.BOX_W, 3), np.float32)
    for (cx, cy, r, col) in [(0.15, 0.25, 0.7, (255, 140, 40)), (0.85, 0.65, 0.6, (255, 70, 30)),
                             (0.55, 0.1, 0.45, (255, 210, 120))]:
        d = np.sqrt((C.XX - cx * C.BOX_W) ** 2 + (C.YY - cy * C.BOX_H) ** 2) / (r * C.BOX_W)
        im += np.clip(1 - d, 0, 1)[..., None] ** 2 * np.array(col, np.float32)
    return im


def _noise(C, seed, sig):
    r = np.random.default_rng(seed)
    n = r.normal(0, 1, (C.BOX_H // 8 + 1, C.BOX_W // 8 + 1)).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), max(sig * C.bs / 8, 0.6))
    n = cv2.resize(n, (C.BOX_W, C.BOX_H), interpolation=cv2.INTER_CUBIC)
    return (n - n.min()) / (n.max() - n.min())


def make_ink(C):
    """Low-frequency noise field driving the ink-bleed transition and sketch->colour reveal."""
    ink = _noise(C, 3, 60) * 0.7 + _noise(C, 5, 10) * 0.3
    return (ink - ink.min()) / (ink.max() - ink.min())


def make_jag(C):
    """Per-row x-offset of a torn paper edge."""
    r = np.random.default_rng(11)
    j = np.cumsum(r.normal(0, 6, C.BOX_H))
    j = cv2.GaussianBlur(j.reshape(-1, 1).astype(np.float32), (0, 0), 3).ravel()
    return ((j - j.mean()) / (np.abs(j).max() + 1e-6) * 45 + r.normal(0, 3, C.BOX_H)) * C.bs


def make_bg(C):
    """Dark radial canvas behind header / picture box / subtitle band."""
    yy, xx = np.mgrid[0:C.H, 0:C.W]
    fall = 1 - 0.7 * (((xx - C.W / 2) / C.W) ** 2 + ((yy - C.H / 2) / C.H) ** 2)
    return (np.array(C.pal["ground"], np.float32) * fall[..., None] * 1.15).astype(np.float32)


def paper_bg(C, seed):
    r = np.random.default_rng(seed)
    base = np.array(C.pal["paper"], np.float32)
    n = cv2.GaussianBlur(r.normal(0, 1, (C.BOX_H, C.BOX_W)).astype(np.float32), (0, 0), 1.2)[..., None]
    fib = cv2.GaussianBlur(r.normal(0, 1, (C.BOX_H, C.BOX_W)).astype(np.float32), (0, 0), 9)[..., None]
    return np.clip(base + n * 6 + fib * 10, 0, 255) * C.VIG_BOX * 1.04


def film_look(C, box, gt, strong):
    """Always: light grain. strong=True (FILM_SECTIONS or film-strip shots): memory film —
    desaturated warm grade, flicker, vignette, random scratches and dust."""
    fi = int(gt * C.FPS)
    amt = 9.0 if strong else 3.2
    box += C.GRAIN[fi % len(C.GRAIN)] * amt
    if strong:
        r = random.Random(fi)
        gray = box.mean(2, keepdims=True)
        box[:] = box * 0.62 + gray * np.array([1.08, 0.98, 0.82], np.float32) * 0.38
        box *= (1 + r.uniform(-0.035, 0.035)) * (0.82 + 0.18 * C.VIG_BOX)
        m = C.b(40)
        if r.random() < 0.18:   # scratch
            x = r.randrange(m, C.BOX_W - m)
            w = max(1, C.b(2))
            box[:, x:x + w] = box[:, x:x + w] * 0.6 + 230 * 0.4
        if r.random() < 0.3:    # dust specks
            for _ in range(r.randint(1, 4)):
                cv2.circle(box, (r.randrange(C.BOX_W), r.randrange(C.BOX_H)), C.b(r.randint(2, 5)), (30, 26, 22), -1)
    return box
