"""Moving Least Squares rigid image deformation (Schaefer, McPhail, Warren, SIGGRAPH 2006).

Independent implementation using complex arithmetic: in 2D the rigid MLS transform at a point v is
    f(v) = (v - p*) * m / |m| + q*,   m = sum_i w_i * conj(p_i - p*) * (q_i - q*)
with w_i = 1 / |p_i - v|^(2 alpha). For image warping we need, for every OUTPUT pixel, the SOURCE
pixel to sample, so `inverse_map` evaluates the deformation that sends dst controls back to src.
"""
import numpy as np


def rigid(points: np.ndarray, src: np.ndarray, dst: np.ndarray, alpha: float = 1.0,
          eps: float = 1e-6, chunk: int = 60000) -> np.ndarray:
    """Deform `points` (M,2 as x,y) by the rigid MLS transform that maps src -> dst controls (N,2)."""
    P = src[:, 0] + 1j * src[:, 1]
    Q = dst[:, 0] + 1j * dst[:, 1]
    V = points[:, 0] + 1j * points[:, 1]
    out = np.empty(V.shape, np.complex128)
    for s in range(0, len(V), chunk):
        v = V[s:s + chunk, None]
        w = 1.0 / (np.abs(P[None] - v) ** (2 * alpha) + eps)
        ws = w.sum(1, keepdims=True)
        ps = (w * P[None]).sum(1, keepdims=True) / ws
        qs = (w * Q[None]).sum(1, keepdims=True) / ws
        m = (w * np.conj(P[None] - ps) * (Q[None] - qs)).sum(1, keepdims=True)
        mag = np.abs(m)
        rot = np.where(mag > 0, m / np.where(mag > 0, mag, 1), 1)
        out[s:s + chunk] = ((v - ps) * rot + qs)[:, 0]
    return np.stack([out.real, out.imag], 1)


def inverse_map(h: int, w: int, src: np.ndarray, dst: np.ndarray, grid: int = 640, alpha: float = 1.0):
    """Return (map_x, map_y) float32 for cv2.remap so that pixels at `src` controls move to `dst`.
    Computed on a coarse grid (longest side `grid`) and upsampled for speed."""
    import cv2
    g = min(1.0, grid / max(h, w))
    gh, gw = max(2, int(h * g)), max(2, int(w * g))
    ys, xs = np.mgrid[0:gh, 0:gw].astype(np.float64)
    pts = np.stack([xs.ravel(), ys.ravel()], 1)
    srcpts = rigid(pts, dst * g, src * g, alpha)          # output pixel -> where it came from
    mx = (srcpts[:, 0].reshape(gh, gw) / g).astype(np.float32)
    my = (srcpts[:, 1].reshape(gh, gw) / g).astype(np.float32)
    return (cv2.resize(mx, (w, h), interpolation=cv2.INTER_LINEAR),
            cv2.resize(my, (w, h), interpolation=cv2.INTER_LINEAR))
