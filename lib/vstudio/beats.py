"""Beat analysis for cutting to music: beat grid, tempo check, band onsets, energy, sections, downbeats.

    from vstudio import beats
    b = beats.analyze("music.mp3")                 # librosa when importable, else a numpy tracker
    b.bpm, b.grid_ok, b.residual_ms                 # least-squares grid fit (accepted within +-15 ms)
    b.beat_t(16), b.bar_t(4)                        # beat / bar number -> seconds (fractions allowed)
    b.snap(3.1, grid="half", direction="after")     # nearest grid point
    cuts = b.cut_plan(8, 4.0, 12.0, pattern="accelerate")
    beats.verify(cuts, b, tol_frames=3, fps=30)     # per-cut frame error report
    beats.energy_arc(60, "travel-fun", beats=b)     # section plan, boundaries snapped to bars

Method (our own implementation; the workflow - fit a straight line through the tracked beats
instead of trusting the tracker's tempo scalar, settle 1/2x-1x-2x ambiguity with where the kicks
land, keep real transients for sparse accents, verify cut frames after the fact - was inspired by
the music-beat-sync notes of video-shotcraft by Wei Yihao, Apache-2.0, re-expressed here):

1. Onset envelope: log-magnitude spectral flux (hop ~5.8 ms). Band envelopes for kick (<150 Hz),
   snare (150-2500 Hz) and hat (>5 kHz) come from the same STFT.
2. Tempo: autocorrelation of the onset envelope weighted by a log-normal prior around 120 BPM.
3. Beats: dynamic-programming tracker (onset strength minus a log-interval deviation penalty),
   then each beat is nudged onto the sharpest attack within +-40 ms on a 2 ms energy curve.
4. Grid: least squares t_i = offset + i * period. Accepted if the p90 residual <= 15 ms (and the
   max <= 30 ms); otherwise the raw beats are kept (tempo drift, live playing).
5. Tempo check: 1/2x, 1x, 2x candidate grids scored by the share of kick energy that lands on them.
6. Downbeats: bar = 4 beats; phase = the beat position (mod 4) with the strongest kicks.
7. RMS curve (50 ms hop), section boundaries from a checkerboard novelty over per-beat spectra,
   snapped to bars, and the top-N strongest hits (band onsets weighted by loudness).
All times are float seconds; convert to frames only at the very end.
"""
import json
import math
from dataclasses import dataclass, field

import numpy as np

BANDS = {"kick": (20.0, 150.0), "snare": (150.0, 2500.0), "hat": (5000.0, 16000.0)}
GRID_TOL_MS = 15.0
BAR = 4


# ------------------------------------------------------------------ loading
def _load(music, sr):
    """Path -> mono float32 at ``sr`` (default 22050) via ffmpeg; ndarray -> as-is (``sr`` required)."""
    if isinstance(music, np.ndarray):
        if not sr:
            raise ValueError("pass sr= with an ndarray")
        x = music.astype(np.float32)
        return (x.mean(1) if x.ndim > 1 else x), int(sr)
    from .audio import decode_audio
    sr = int(sr or 22050)
    return decode_audio(str(music), sr=sr, channels=1)[:, 0].copy(), sr


# ------------------------------------------------------------------ spectral features
def _spectral(x, sr, hop, n_fft, lag, n_feat=16):
    """One chunked STFT pass -> broadband flux, per-band flux, per-frame log band energies."""
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    win = np.hanning(n_fft).astype(np.float32)
    pad = n_fft // 2
    xp = np.pad(x, (pad, pad))
    n = 1 + (len(xp) - n_fft) // hop
    masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
    edges = np.geomspace(40, min(16000, sr / 2), n_feat + 1)
    feat_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(n_feat)]
    flux = np.zeros(n, np.float32)
    bflux = {k: np.zeros(n, np.float32) for k in BANDS}
    feats = np.zeros((n, n_feat), np.float32)
    prev = None
    chunk = 2048
    for c0 in range(0, n, chunk):
        c1 = min(n, c0 + chunk)
        idx = (np.arange(c0, c1) * hop)[:, None] + np.arange(n_fft)[None, :]
        L = np.log1p(100.0 * np.abs(np.fft.rfft(xp[idx] * win, axis=1))).astype(np.float32)
        full = L if prev is None else np.concatenate([prev, L])
        off = 0 if prev is None else len(prev)
        d = np.zeros_like(L)
        src = np.arange(off, off + len(L)) - lag
        ok = src >= 0
        d[ok] = np.maximum(0.0, L[ok] - full[src[ok]])
        bandf = [d[:, fi].mean(1) for fi in feat_idx if len(fi)]
        flux[c0:c1] = np.mean(bandf, 0) if bandf else d.mean(1)   # log-band average (mel-like weighting)
        for k, m in masks.items():
            if m.any():
                bflux[k][c0:c1] = d[:, m].mean(1)
        for i, fi in enumerate(feat_idx):
            if len(fi):
                feats[c0:c1, i] = L[:, fi].mean(1)
        prev = full[-lag:]
    return flux, bflux, feats


def _attack(x, sr, hop_s=0.002, win_s=0.004):
    """Fine attack curve: positive change of log energy over ~4 ms, 2 ms hop. Returns (curve, hop_s)."""
    h, w = max(1, int(sr * hop_s)), max(2, int(sr * win_s))
    c = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    starts = np.arange(0, max(1, len(x) - w), h)
    e = np.log10((c[starts + w] - c[starts]) / w + 1e-10)
    a = np.zeros_like(e)
    a[2:] = np.maximum(0.0, e[2:] - e[:-2])
    return a, h / sr, w / sr


def _refine(times, att, ahop, awin, radius=0.04, min_rel=3.0):
    """Move each time onto the sharpest attack within +-radius (if that attack is clearly above the
    curve's median). The onset is placed at the start of the attack frame plus half a window."""
    out = np.array(times, float)
    if len(att) == 0:
        return out
    floor = np.median(att) + 1e-6
    r = int(radius / ahop)
    for i, t in enumerate(out):
        c = int(round(t / ahop))
        a, b = max(0, c - r), min(len(att), c + r + 1)
        if b <= a:
            continue
        j = a + int(np.argmax(att[a:b]))
        if att[j] > min_rel * floor:
            out[i] = j * ahop + awin * 0.5
    return out


def _peaks(env, hop, min_gap=0.05, rel=0.12, local=0.5):
    """Peak-pick an onset envelope -> (times, strengths 0..1)."""
    if len(env) < 3 or env.max() <= 0:
        return np.zeros(0), np.zeros(0)
    e = env / (np.percentile(env, 99.5) + 1e-9)
    g = max(1, int(min_gap / hop))
    from numpy.lib.stride_tricks import sliding_window_view as swv
    ep = np.pad(e, (g, g), constant_values=-1)
    mx = swv(ep, 2 * g + 1).max(1)
    L = max(1, int(local / hop))
    cs = np.concatenate([[0.0], np.cumsum(e)])
    lo, hi = np.clip(np.arange(len(e)) - L, 0, len(e)), np.clip(np.arange(len(e)) + L + 1, 0, len(e))
    mean = (cs[hi] - cs[lo]) / np.maximum(1, hi - lo)
    pk = np.where((e >= mx) & (e > rel) & (e > mean + 0.05))[0]
    return pk * hop, np.clip(e[pk], 0, 1)


# ------------------------------------------------------------------ tempo + DP tracker
def _tempo(onset, hop, lo_bpm=40, hi_bpm=240, prior_bpm=120.0, prior_oct=1.0):
    o = onset - onset.mean()
    n = len(o)
    f = np.fft.rfft(o, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    lags = np.arange(n)
    lmin, lmax = max(2, int(60 / (hi_bpm * hop))), min(n - 2, int(60 / (lo_bpm * hop)) + 1)
    if lmax <= lmin:
        return 60 / (prior_bpm * hop)
    L = lags[lmin:lmax]
    bpm = 60 / (L * hop)
    w = np.exp(-0.5 * (np.log2(bpm / prior_bpm) / prior_oct) ** 2)
    s = ac[lmin:lmax] * w
    k = int(np.argmax(s))
    p = float(L[k])
    if 0 < k < len(s) - 1:                         # parabolic refinement of the lag
        a, b, c = s[k - 1], s[k], s[k + 1]
        den = a - 2 * b + c
        if den < 0:
            p += 0.5 * (a - c) / den
    return p                                       # period in frames


def _track(onset, period, tightness=100.0):
    """Dynamic-programming beat tracker on the onset envelope; returns beat frame indices."""
    o = onset / (onset.std() + 1e-9)
    sd = max(1.0, period / 32)
    k = np.arange(-int(4 * sd), int(4 * sd) + 1)
    local = np.convolve(o, np.exp(-0.5 * (k / sd) ** 2), "same")
    n = len(local)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offs = np.arange(lo, hi + 1)
    pen = -tightness * np.log(offs / period) ** 2
    cum = local.copy()
    back = np.full(n, -1)
    for t in range(lo, n):
        cand = t - offs
        ok = cand >= 0
        sc = cum[cand[ok]] + pen[ok]
        j = int(np.argmax(sc))
        if sc[j] > 0:
            cum[t] = local[t] + sc[j]
            back[t] = cand[ok][j]
    # last beat: the latest local max of cum that is at least half the median local-max score
    mx = np.where((cum[1:-1] >= cum[:-2]) & (cum[1:-1] >= cum[2:]))[0] + 1
    if len(mx) == 0:
        return np.zeros(0, int)
    med = np.median(cum[mx])
    t = int(mx[cum[mx] >= 0.5 * med][-1])
    out = [t]
    while back[out[-1]] >= 0:
        out.append(int(back[out[-1]]))
    b = np.array(out[::-1])
    # trim weak beats at the edges (silence / fade)
    thr = 0.5 * np.sqrt(np.mean(local ** 2))
    strong = np.where(local[b] > thr)[0]
    return b[strong[0]:strong[-1] + 1] if len(strong) else b


def _fit(times):
    """Least-squares straight line through beat times. Index from the median interval so a skipped
    beat does not break the fit. Returns (period, offset, residual seconds array, idx)."""
    t = np.asarray(times, float)
    if len(t) < 3:
        p = float(np.median(np.diff(t))) if len(t) > 1 else 0.5
        return p, (t[0] if len(t) else 0.0), np.zeros(len(t)), np.arange(len(t))
    ibi = float(np.median(np.diff(t)))
    idx = np.round((t - t[0]) / ibi).astype(int)
    A = np.vstack([idx, np.ones_like(idx)]).T.astype(float)
    (p, t0), *_ = np.linalg.lstsq(A, t, rcond=None)
    return float(p), float(t0), t - (t0 + idx * p), idx


def _strength_at(times, env, hop, radius=0.035):
    r = max(1, int(radius / hop))
    out = np.zeros(len(times))
    for i, t in enumerate(times):
        c = int(round(t / hop))
        a, b = max(0, c - r), min(len(env), c + r + 1)
        out[i] = env[a:b].max() if b > a else 0.0
    return out


def _on_grid(kt, ks, grid, tol):
    """Share of kick strength within ``tol`` of a grid point, and share of grid points with a kick."""
    if len(kt) == 0 or len(grid) == 0:
        return 0.0, 0.0
    g = np.sort(grid)
    j = np.clip(np.searchsorted(g, kt), 1, len(g) - 1)
    d = np.minimum(np.abs(kt - g[j - 1]), np.abs(kt - g[j]))
    on = float(ks[d <= tol].sum() / (ks.sum() + 1e-9))
    jj = np.clip(np.searchsorted(kt, g), 1, max(1, len(kt) - 1))
    if len(kt) == 1:
        dg = np.abs(g - kt[0])
    else:
        dg = np.minimum(np.abs(g - kt[jj - 1]), np.abs(g - kt[np.minimum(jj, len(kt) - 1)]))
    return on, float((dg <= tol).mean())


def _novelty(F, kernel=8):
    """Foote checkerboard novelty on a per-beat feature matrix (rows = beats)."""
    n = len(F)
    if n < 2 * kernel + 2:
        return np.zeros(n)
    Z = (F - F.mean(0)) / (F.std(0) + 1e-6)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
    S = Z @ Z.T
    k = kernel
    u = np.arange(-k, k) + 0.5
    g = np.exp(-0.5 * (u / (0.5 * k)) ** 2)
    K = np.outer(g, g) * np.sign(u)[:, None] * np.sign(u)[None, :]
    Sp = np.pad(S, k, mode="edge")
    nov = np.array([(Sp[i:i + 2 * k, i:i + 2 * k] * K).sum() for i in range(n)])
    return np.maximum(0, -nov) if nov.mean() < 0 else np.maximum(0, nov)


# ------------------------------------------------------------------ result
@dataclass
class Beats:
    """Analysis result. ``beats`` = grid times when ``grid_ok`` else the raw tracked beats."""
    beats: np.ndarray
    raw_beats: np.ndarray
    bpm: float
    period: float
    offset: float
    residual_ms: float
    residual_p90_ms: float
    grid_ok: bool
    tempo_factor: float = 1.0
    tempo_check: dict = field(default_factory=dict)
    onsets: dict = field(default_factory=dict)       # band -> [(t, strength 0..1)]
    rms: np.ndarray = None                           # dB, one value per rms_hop
    rms_hop: float = 0.05
    sections: list = field(default_factory=list)     # [{start, end, energy 0..1, level}]
    hits: list = field(default_factory=list)         # [{t, s, k, beat}]
    downbeat_phase: int = 0
    duration: float = 0.0
    backend: str = "numpy"

    # ---- grid maths (fractional beat numbers allowed; beat 0 = first tracked beat)
    def beat_t(self, n):
        """Beat number -> seconds. Linear grid if accepted, else interpolated raw beats
        (extrapolated with the mean period outside the tracked range)."""
        n = np.asarray(n, float)
        if self.grid_ok or len(self.beats) < 2:
            r = self.offset + n * self.period
        else:
            b, i = self.beats, np.arange(len(self.beats))
            r = np.interp(n, i, b)
            r = np.where(n < 0, b[0] + n * self.period, r)
            r = np.where(n > i[-1], b[-1] + (n - i[-1]) * self.period, r)
        return float(r) if r.ndim == 0 else r

    def beat_n(self, t):
        """Seconds -> fractional beat number (inverse of ``beat_t``)."""
        t = np.asarray(t, float)
        if self.grid_ok or len(self.beats) < 2:
            r = (t - self.offset) / self.period
        else:
            b, i = self.beats, np.arange(len(self.beats))
            r = np.interp(t, b, i)
            r = np.where(t < b[0], (t - b[0]) / self.period, r)
            r = np.where(t > b[-1], i[-1] + (t - b[-1]) / self.period, r)
        return float(r) if r.ndim == 0 else r

    def bar_t(self, n):
        """Bar number -> seconds of its downbeat (bar 0 = first downbeat in the track)."""
        return self.beat_t(self.downbeat_phase + BAR * np.asarray(n, float))

    @property
    def downbeats(self):
        n = np.arange(self.downbeat_phase, len(self.beats), BAR)
        return self.beats[n] if len(self.beats) else np.zeros(0)

    def snap(self, t, grid="beat", direction="nearest"):
        """Snap ``t`` to the grid: grid 'beat' | 'half' | 'quarter' | 'bar' (or a step in beats);
        direction 'nearest' | 'before' | 'after' (before/after include t itself when on-grid)."""
        step = {"beat": 1.0, "half": 0.5, "quarter": 0.25, "bar": float(BAR)}.get(grid, grid)
        step = float(step)
        phase = self.downbeat_phase if grid == "bar" else 0.0
        u = (self.beat_n(t) - phase) / step
        eps = 1e-6
        f = {"nearest": np.round, "before": lambda v: np.floor(v + eps),
             "after": lambda v: np.ceil(v - eps)}[direction](u)
        return self.beat_t(phase + f * step)

    def cut_plan(self, n_cuts, start, end, pattern="every-beat", ladder=None):
        """Cut times inside [start, end] aligned to the grid.

        pattern:
          every-beat / every-2 / every-bar  - steady cuts (every-2 and every-bar start on bar phase)
          accelerate - shrinking intervals that resolve on the last bar line before ``end``.
                       Default ladder in beats (1/8-beat aligned): 2, 1.5, 1, 0.75, 0.5, 0.375, 0.25
                       (at 112 BPM / 30 fps that is 32 24 16 12 8 6 4 frames), then 0.25 repeats.
          drop       - up to two sparse bar cuts building in, then a cut on the drop (first
                       section boundary in range, else the strongest hit, snapped to a bar) and
                       every beat after it.
        May return fewer than ``n_cuts`` when the span is too short.
        """
        n_cuts = int(n_cuts)
        if n_cuts <= 0 or end <= start:
            return []
        if pattern in ("every-beat", "every-2", "every-bar"):
            step = {"every-beat": 1, "every-2": 2, "every-bar": BAR}[pattern]
            ph = 0 if step == 1 else self.downbeat_phase
            n0 = math.ceil((self.beat_n(start) - ph) / step - 1e-6) * step + ph
            out = [self.beat_t(n0 + k * step) for k in range(n_cuts)]
            return [t for t in out if t <= end + 1e-6]
        if pattern == "accelerate":
            lad = list(ladder or (2, 1.5, 1, 0.75, 0.5, 0.375, 0.25))
            gaps = (lad + [lad[-1]] * max(0, n_cuts - 1 - len(lad)))[:n_cuts - 1]
            last = self.beat_n(self.snap(end, "bar", "before"))
            if self.beat_t(last) < start:
                last = self.beat_n(self.snap(end, "beat", "before"))
            n_start = self.beat_n(start) - 1e-6
            while gaps and last - sum(gaps) < n_start:
                gaps.pop(0)
            ns = [last - sum(gaps[i:]) for i in range(len(gaps))] + [last]
            return [self.beat_t(round(n * 8) / 8) for n in ns if n >= n_start]
        if pattern == "drop":
            drop = None
            for s in self.sections[1:]:
                if start < s["start"] <= end:
                    drop = s["start"]
                    break
            if drop is None:
                hs = [h for h in self.hits if start < h["t"] <= end]
                drop = max(hs, key=lambda h: h["s"])["t"] if hs else (start + end) / 2
            nd = self.beat_n(self.snap(drop, "bar"))
            before = [self.beat_t(nd - BAR * k) for k in (2, 1)]
            before = [t for t in before if t >= start - 1e-6][:max(0, n_cuts - 1)]
            before = before[-min(2, max(0, n_cuts - 1)):] if before else []
            after, k = [], 0
            while len(before) + len(after) < n_cuts and self.beat_t(nd + k) <= end + 1e-6:
                after.append(self.beat_t(nd + k))
                k += 1
            return before + after
        raise ValueError(f"unknown pattern {pattern!r}")

    def to_dict(self):
        d = {k: getattr(self, k) for k in ("bpm", "period", "offset", "residual_ms", "residual_p90_ms",
                                            "grid_ok", "tempo_factor", "tempo_check", "rms_hop",
                                            "sections", "hits", "downbeat_phase", "duration", "backend")}
        d["beats"] = [round(float(t), 5) for t in self.beats]
        d["raw_beats"] = [round(float(t), 5) for t in self.raw_beats]
        d["downbeats"] = [round(float(t), 5) for t in self.downbeats]
        d["onsets"] = {k: [[round(float(t), 4), round(float(s), 3)] for t, s in v] for k, v in self.onsets.items()}
        d["rms"] = [round(float(v), 2) for v in (self.rms if self.rms is not None else [])]
        return d

    def save(self, path):
        """Write the analysis as JSON (the audit trail every cut can be checked against)."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=1)
        return path


# ------------------------------------------------------------------ analyze
def _librosa_beats(x, sr, hop):
    import librosa  # noqa: WPS433 (optional)
    _, fr = librosa.beat.beat_track(y=x, sr=sr, hop_length=hop, tightness=400)
    return librosa.frames_to_time(fr, sr=sr, hop_length=hop)


def analyze(music, sr=None, backend="auto", n_hits=8, tol_ms=GRID_TOL_MS, prior_bpm=120.0):
    """Analyse a music file (any ffmpeg-readable path) or a mono/stereo ndarray (pass ``sr``).

    backend: 'auto' (librosa's beat tracker if importable, else numpy), 'numpy', 'librosa'.
    Everything after beat tracking (refinement, grid fit, tempo check, bands, sections) is shared.
    Returns a ``Beats``.
    """
    x, sr = _load(music, sr)
    dur = len(x) / sr
    hop = max(32, int(round(sr * 0.0058)))
    n_fft = 1 << int(math.ceil(math.log2(sr * 0.046)))
    lag = max(1, int(round(0.012 / (hop / sr))))
    hs = hop / sr
    flux, bflux, feats = _spectral(x, sr, hop, n_fft, lag)
    att, ahop, awin = _attack(x, sr)
    # band attack curves (FFT masking of the whole signal) for precise band-onset times
    X = np.fft.rfft(x)
    fq = np.fft.rfftfreq(len(x), 1 / sr)
    onsets = {}
    for k, (lo, hi) in BANDS.items():
        t, s = _peaks(bflux[k], hs)
        if len(t):
            xb = np.fft.irfft(X * ((fq >= lo) & (fq < hi)), len(x)).astype(np.float32)
            a, ah, aw = _attack(xb, sr)
            t = _refine(t - 0.01, a, ah, aw, radius=0.03, min_rel=2.0)
        onsets[k] = list(zip(t.tolist(), s.tolist()))

    used = "numpy"
    raw = None
    if backend in ("auto", "librosa"):
        try:
            raw = _librosa_beats(x, sr, hop)
            used = "librosa"
        except ImportError:
            if backend == "librosa":
                raise
    if raw is None:
        P = _tempo(flux, hs, prior_bpm=prior_bpm)
        raw = _track(flux, P) * hs
    raw = _refine(raw, att, ahop, awin)
    raw = np.unique(np.round(raw, 5))

    # tempo ambiguity: 1/2x, 1x, 2x by kick-on-grid share
    kt = np.array([t for t, _ in onsets.get("kick", [])])
    ks = np.array([s for _, s in onsets.get("kick", [])])
    ibi = float(np.median(np.diff(raw))) if len(raw) > 1 else 0.5
    tol = max(0.035, 0.08 * ibi)
    kstr = _strength_at(raw, bflux["kick"], hs)
    half_phase = int(np.argmax([kstr[p::2].sum() for p in range(2)])) if len(raw) > 1 else 0
    # off-beat lock: a tracker can sit on the hats between kicks; shift half a beat if the kicks say so
    if len(raw) > 2 and len(kt) >= 4:
        mid = np.concatenate([[raw[0] - ibi / 2], (raw[:-1] + raw[1:]) / 2, [raw[-1] + ibi / 2]])
        mid = mid[(mid >= 0) & (mid <= dur)]
        on_a, _ = _on_grid(kt, ks, raw, tol)
        on_b, _ = _on_grid(kt, ks, mid, tol)
        if on_b > max(0.6, on_a + 0.3):
            raw = _refine(mid, att, ahop, awin)
            kstr = _strength_at(raw, bflux["kick"], hs)
            half_phase = int(np.argmax([kstr[p::2].sum() for p in range(2)]))
    cands = {1.0: raw,
             2.0: np.sort(np.concatenate([raw, (raw[:-1] + raw[1:]) / 2])) if len(raw) > 1 else raw,
             0.5: raw[half_phase::2]}
    check = {}
    for f, g in cands.items():
        on, cov = _on_grid(kt, ks, g, tol)
        check[str(f)] = dict(bpm=round(60 / ibi * f, 2), kick_on_grid=round(on, 3), grid_with_kick=round(cov, 3))
    factor = 1.0
    bpm1 = 60 / ibi
    in_range = lambda b: 70 <= b <= 180  # noqa: E731
    if len(kt) >= 4:
        if check["1.0"]["kick_on_grid"] < 0.6 and check["2.0"]["kick_on_grid"] >= 0.8 and in_range(2 * bpm1):
            factor = 2.0
        elif bpm1 > 160 and check["0.5"]["kick_on_grid"] >= 0.9 and in_range(bpm1 / 2):
            factor = 0.5
    check["chosen"] = factor
    raw = cands[factor]

    period, offset, res, idx = _fit(raw)
    out = np.abs(res) * 1000 > 2 * tol_ms              # a few stray beats (edges, fills) must not
    if 0 < out.sum() <= max(1, 0.1 * len(raw)):        # veto an otherwise clean grid: drop + refit
        raw = raw[~out]
        period, offset, res, idx = _fit(raw)
    absr = np.abs(res) * 1000
    rmax = float(absr.max()) if len(absr) else 0.0
    p90 = float(np.percentile(absr, 90)) if len(absr) else 0.0
    grid_ok = len(raw) >= 4 and p90 <= tol_ms and rmax <= 2 * tol_ms
    if grid_ok:
        n_last = max(int(idx[-1]) if len(idx) else 0, int(math.floor((dur - offset) / period)))
        grid = offset + np.arange(n_last + 1) * period
    else:
        grid = raw
        offset = float(raw[0]) if len(raw) else 0.0

    # downbeat phase from kick strength
    kb = _strength_at(grid, bflux["kick"], hs)
    phase = int(np.argmax([kb[p::BAR].mean() if len(kb[p::BAR]) else 0 for p in range(BAR)])) if len(grid) >= BAR else 0

    from .audio import rms_envelope
    rms, rhop = rms_envelope(x, sr, hop=0.05, win=0.1, db=True, smooth=1)

    # sections: novelty over per-beat spectra + loudness, snapped to bars
    sections = []
    if len(grid) >= 2:
        edges = np.concatenate([grid, [min(dur, grid[-1] + period)]])
        fi = np.clip((edges / hs).astype(int), 0, len(feats) - 1)
        ri = np.clip((edges / rhop).astype(int), 0, len(rms) - 1)
        F = np.array([np.concatenate([feats[a:max(a + 1, b)].mean(0), [rms[c:max(c + 1, d)].mean() / 10]])
                      for a, b, c, d in zip(fi[:-1], fi[1:], ri[:-1], ri[1:])])
        nov = _novelty(F, kernel=8)
        bounds = [0.0]
        if nov.max() > 0:
            nv = nov / nov.max()
            thr = max(0.3, nv.mean() + nv.std())
            pk = [i for i in range(8, len(nv) - 8) if nv[i] >= nv[i - 1] and nv[i] >= nv[i + 1] and nv[i] > thr]
            last = -10 ** 9
            chosen = []
            for i in sorted(pk, key=lambda i: -nv[i]):
                if all(abs(i - j) >= 2 * BAR for j in chosen):
                    chosen.append(i)
            for i in sorted(chosen):
                n = phase + round((i - phase) / BAR) * BAR
                n = min(max(n, 0), len(grid) - 1)
                t = float(grid[n])
                if t - bounds[-1] >= 2.0 and dur - t >= 2.0 and t > last:
                    bounds.append(t)
                    last = t
        bounds.append(dur)
        lin = 10 ** (rms / 20)
        lo_, hi_ = np.percentile(lin, 5), np.percentile(lin, 95) + 1e-9
        for a, b in zip(bounds[:-1], bounds[1:]):
            seg = lin[int(a / rhop):max(int(a / rhop) + 1, int(b / rhop))]
            e = float(np.clip((seg.mean() - lo_) / (hi_ - lo_), 0, 1)) if len(seg) else 0.0
            sections.append(dict(start=round(a, 4), end=round(b, 4), energy=round(e, 3),
                                 level="high" if e > 0.66 else "mid" if e > 0.33 else "low"))

    # strongest hits: band onsets weighted by loudness, >= 2 beats apart
    lin = 10 ** (rms / 20)
    lmax = lin.max() + 1e-9
    wts = {"kick": 1.0, "snare": 0.8, "hat": 0.4}
    cand = []
    for k, lst in onsets.items():
        for t, s in lst:
            loud = lin[min(len(lin) - 1, int(t / rhop))] / lmax
            cand.append((s * wts[k] * loud, t, k))
    cand.sort(reverse=True)
    hits = []
    for sc, t, k in cand:
        if len(hits) >= n_hits:
            break
        if all(abs(t - h["t"]) >= 2 * period for h in hits):
            hits.append(dict(t=round(t, 4), s=round(float(sc), 3), k=k, beat=None))
    top = max([h["s"] for h in hits], default=1.0) or 1.0
    b = Beats(beats=np.asarray(grid, float), raw_beats=np.asarray(raw, float), bpm=60.0 / period,
              period=period, offset=offset, residual_ms=rmax, residual_p90_ms=p90, grid_ok=bool(grid_ok),
              tempo_factor=factor, tempo_check=check, onsets=onsets, rms=rms, rms_hop=rhop,
              sections=sections, hits=[], downbeat_phase=phase, duration=dur, backend=used)
    for h in hits:
        h["s"] = round(h["s"] / top, 3)
        h["beat"] = round(float(b.beat_n(h["t"])), 2)
    b.hits = sorted(hits, key=lambda h: h["t"])
    return b


# ------------------------------------------------------------------ verification
def verify(cut_times, beats, tol_frames=3, fps=30, grid="beat"):
    """Check designed cut times against the beat grid after frame rounding.

    beats: a ``Beats`` (snapped with ``grid``) or an array of beat times (nearest one).
    Per cut: target beat time, audio error (ms, unrounded seconds vs beat) and frame error
    (round(t*fps)/fps vs beat, in frames). A cut fails when |frame error| > tol_frames.
    Returns {ok, n_bad, bad: [indices], max_abs_frames, mean_abs_ms, rows: [...]}.
    """
    rows, bad = [], []
    arr = None if isinstance(beats, Beats) else np.sort(np.asarray(beats, float))
    for i, t in enumerate(cut_times):
        t = float(t)
        if arr is None:
            tgt = float(beats.snap(t, grid))
        else:
            tgt = float(arr[np.argmin(np.abs(arr - t))]) if len(arr) else t
        fr = round(t * fps)
        ef = (fr / fps - tgt) * fps
        row = dict(i=i, t=round(t, 4), frame=fr, beat_t=round(tgt, 4), audio_err_ms=round((t - tgt) * 1000, 2),
                   frame_err=round(ef, 2), ok=abs(ef) <= tol_frames)
        rows.append(row)
        if not row["ok"]:
            bad.append(i)
    ae = [abs(r["audio_err_ms"]) for r in rows]
    return dict(ok=not bad, n_bad=len(bad), bad=bad, tol_frames=tol_frames, fps=fps,
                max_abs_frames=max([abs(r["frame_err"]) for r in rows], default=0.0),
                mean_abs_ms=float(np.mean(ae)) if ae else 0.0, rows=rows)


# ------------------------------------------------------------------ energy arcs
# Each arc: (name, share of duration, energy 0..1, suggested cut pattern, note). Our own arcs.
_ARCS = {
    "travel-fun": {
        "head": [("hook", 0.08, 1.0, "every-beat", "best 5-8 shots of the whole trip, max energy, ends on a hit"),
                 ("intro", 0.07, 0.55, "every-2", "where/who/why; title card holds >= 1 s")],
        "block": [("montage", 0.62, 0.8, "every-beat", "fast place montage; accelerate into the breather"),
                  ("breather", 0.38, 0.4, "every-bar", "one moment that breathes: a reaction, food, a view, a line")],
        "tail": [("finale", 0.11, 1.0, "accelerate", "peak: best shots again, riser -> impact -> sparkle"),
                 ("outro", 0.06, 0.3, "every-bar", "slow wide shot, sign-off, end card")],
        "body": 0.68,
    },
    "talking-head": {
        "head": [("hook", 0.06, 0.8, "every-2", "cold open: the strongest line or result first"),
                 ("setup", 0.09, 0.5, "every-bar", "who this is for and what they get")],
        "block": [("point", 0.8, 0.55, "every-bar", "one point; punch-in or card on the key line"),
                  ("reset", 0.2, 0.35, "every-bar", "B-roll / pause so the next point lands")],
        "tail": [("recap", 0.08, 0.6, "every-2", "the one-sentence takeaway"),
                 ("cta", 0.05, 0.4, "every-bar", "call to action, hold the end card")],
        "body": 0.72,
    },
    "promo": {
        "head": [("tease", 0.07, 0.6, "every-2", "one hero element, full action arc"),
                 ("problem", 0.1, 0.4, "every-bar", "the pain, quiet, readable")],
        "block": [("feature", 0.7, 0.75, "every-2", "one feature per block, hero on the downbeat"),
                  ("proof", 0.3, 0.5, "every-bar", "number / quote / UI detail held >= 1 s")],
        "tail": [("finale", 0.12, 1.0, "drop", "everything returns; riser -> impact -> sparkle"),
                 ("end card", 0.07, 0.3, "every-bar", "logo + line, hold >= 1 s")],
        "body": 0.64,
    },
    "story": {
        "head": [("setup", 0.15, 0.35, "every-bar", "world and person, slow"),
                 ("inciting", 0.08, 0.6, "every-2", "the thing that changes")],
        "block": [("rising", 0.7, 0.6, "every-2", "attempts, each a little bigger"),
                  ("setback", 0.3, 0.35, "every-bar", "a beat of doubt")],
        "tail": [("climax", 0.1, 1.0, "drop", "the payoff"),
                 ("resolution", 0.1, 0.3, "every-bar", "after; let it ring")],
        "body": 0.57,
    },
}


def energy_arc(duration, kind="travel-fun", n_blocks=None, beats=None):
    """Plan a video's sections: [{name, start, end, frac, energy 0..1, pattern, note}, ...].

    kind: 'travel-fun' (hook 0-8 % at max energy, intro, 3-5 place/day blocks alternating a fast
    montage and a breather with energy rising block to block, peak finale, outro), 'talking-head',
    'promo', 'story'. n_blocks: number of middle blocks (travel-fun default 4 for >= 90 s else 3,
    clipped to 3-5; others 3). beats: a ``Beats`` -> boundaries snapped to the nearest bar.
    """
    if kind not in _ARCS:
        raise ValueError(f"kind must be one of {sorted(_ARCS)}")
    A = _ARCS[kind]
    if n_blocks is None:
        n_blocks = (4 if duration >= 90 else 3) if kind == "travel-fun" else 3
    n_blocks = int(np.clip(n_blocks, 3, 5)) if kind == "travel-fun" else max(1, int(n_blocks))
    parts = [(n, f, e, p, note) for n, f, e, p, note in A["head"]]
    per = A["body"] / n_blocks
    for b in range(n_blocks):
        lift = 0.1 * b / max(1, n_blocks - 1)        # energy creeps up block to block
        for n, f, e, p, note in A["block"]:
            parts.append((f"{n} {b + 1}", per * f, min(1.0, e + lift), p, note))
    parts += [(n, f, e, p, note) for n, f, e, p, note in A["tail"]]
    tot = sum(f for _, f, *_ in parts)
    out, t = [], 0.0
    for n, f, e, p, note in parts:
        out.append(dict(name=n, start=t, end=t + duration * f / tot, frac=round(f / tot, 4), energy=round(e, 2),
                        pattern=p, note=note))
        t = out[-1]["end"]
    out[-1]["end"] = float(duration)
    if beats is not None:
        for a, b in zip(out[:-1], out[1:]):
            s = float(beats.snap(a["end"], "bar"))
            if a["start"] < s < b["end"]:
                a["end"] = b["start"] = s
    for s in out:
        s["start"], s["end"] = round(s["start"], 4), round(s["end"], 4)
    return out
