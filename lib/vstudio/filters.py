"""Signal smoothing for tracked points (landmarks, face boxes, crop paths).

One Euro filter (Casiez, Roussel, Vogel, CHI 2012): an adaptive low-pass whose cutoff rises with speed,
so a still subject gets no jitter and fast motion gets little lag. Independent implementation.

    f = OneEuro(min_cutoff=1.0, beta=0.02)
    y = f(x, t)              # scalar or numpy array (e.g. a (478, 2) landmark array), t in seconds
    smooth_series(xs, fps)   # offline: forward pass over a whole sequence
"""
import math

import numpy as np


def _alpha(cutoff, dt):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    """min_cutoff: jitter reduction when still (lower = smoother); beta: speed responsiveness (higher = less lag);
    d_cutoff: cutoff for the derivative estimate. Works on scalars or numpy arrays (element-wise)."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.x = self.dx = self.t = None

    def __call__(self, x, t: float):
        x = np.asarray(x, dtype=np.float64)
        if self.x is None:
            self.x, self.dx, self.t = x.copy(), np.zeros_like(x), t
            return x.copy()
        dt = max(t - self.t, 1e-6)
        dx = (x - self.x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * np.abs(self.dx)
        a = 1.0 / (1.0 + (1.0 / (2 * np.pi * cutoff)) / dt)
        self.x = a * x + (1 - a) * self.x
        self.t = t
        return self.x.copy()


def smooth_series(xs, fps: float, min_cutoff: float = 1.0, beta: float = 0.02, d_cutoff: float = 1.0,
                  warmup=None):
    """Filter a whole sequence offline. `xs`: list/array of values (None = missing, held from the last value).
    `warmup`: optional list of preceding samples fed first (keeps state continuous across chunk boundaries)."""
    f = OneEuro(min_cutoff, beta, d_cutoff)
    t0 = 0.0
    if warmup:
        n = len(warmup)
        for i, w in enumerate(warmup):
            if w is not None:
                f(w, (i - n) / fps)
    out, last = [], None
    for i, x in enumerate(xs):
        if x is None:
            x = last
        if x is None:
            out.append(None)
            continue
        last = x
        out.append(f(x, t0 + i / fps))
    return out
