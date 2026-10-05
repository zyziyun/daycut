"""MODE = "music": the timeline is driven by the music bed instead of narration timing.

    MUSIC = dict(grid="bar",        # cut grid: "bar" (calm, 文艺片) | "beat" | "2" (every 2 beats) | number of beats
                 per=1.0,           # grid units per unit of shot weight (weight 2 = 2 bars at per=1)
                 length=None,       # target seconds (overrides per; units are spread by weight)
                 start=0.0,         # seconds to skip into the track (video t=0 = this music time)
                 tr="fade", trd=None,   # default transition + duration (None = half a grid unit, 0.25-1.4 s)
                 sections=True,     # move spec section boundaries onto the music's section changes when close
                 captions="title",  # "title" (quiet serif text) | "subs" (speech-style) | False
                 lufs=-16,          # music stem level before the final loudnorm
                 backend="auto")    # beats.analyze backend: auto | numpy | librosa

Each shot gets a whole number of grid units by weight (min 1), so every cut lands on a beat / downbeat.
Spec sections (chapter cards, header progress) start on the music's own section changes
(``beats.analyze`` novelty sections) when one is within a quarter section; else on the nearest grid point.
"""
import hashlib
import json
import math
import os
import pickle

from vstudio import beats as vbeats

from .transitions import TRD

DEFAULTS = dict(grid="bar", per=1.0, length=None, start=0.0, tr="fade", trd=None, sections=True,
                captions="title", lufs=-16.0, tail=0.0, backend="auto")


def config(C):
    cfg = dict(DEFAULTS)
    cfg.update(getattr(C.spec, "MUSIC", {}) or {})
    return cfg


def bgm_path(C):
    p = C.path(getattr(C.spec, "BGM", None))
    if not p or not os.path.exists(p):
        raise SystemExit(f'MODE "music" needs BGM (a music file); got {p!r}')
    return p


def analyze(C):
    """beats.analyze(BGM), cached in <cache>/beats_<hash>.pkl (+ a JSON audit copy)."""
    p = bgm_path(C)
    st = os.stat(p)
    key = hashlib.sha1(f"{os.path.abspath(p)}|{st.st_size}|{st.st_mtime}|{config(C).get('backend', 'auto')}"
                       .encode()).hexdigest()[:12]
    pk = os.path.join(C.cache_dir, f"beats_{key}.pkl")
    if os.path.exists(pk):
        with open(pk, "rb") as f:
            return pickle.load(f)
    b = _analyze(p, config(C).get("backend", "auto"))
    with open(pk, "wb") as f:
        pickle.dump(b, f)
    b.save(os.path.join(C.cache_dir, "beats.json"))
    return b


def _kick_share(b):
    tc = b.tempo_check or {}
    ch = tc.get(str(tc.get("chosen", 1.0))) or {}
    return float(ch.get("kick_on_grid", 1.0))


def _analyze(p, backend="auto"):
    """beats.analyze; with backend "auto", when the chosen grid catches few kicks (librosa can lock onto
    off-beat hats in sparse tracks) the numpy tracker is tried too and the grid with more kicks wins."""
    b = vbeats.analyze(p, backend=backend)
    if backend == "auto" and b.backend != "numpy" and _kick_share(b) < 0.35:
        n = vbeats.analyze(p, backend="numpy")
        if _kick_share(n) > _kick_share(b) + 0.15:
            print(f"note: beat grid from the numpy tracker (kicks on grid {_kick_share(n):.2f} vs "
                  f"{b.backend} {_kick_share(b):.2f})")
            b = n
    return b


def grid_step(cfg):
    g = cfg["grid"]
    return {"bar": float(vbeats.BAR), "beat": 1.0, "half": 0.5}.get(str(g), None) or float(g)


def verify_grid(cfg):
    """grid argument for beats.verify / Beats.snap."""
    st = grid_step(cfg)
    return "bar" if st == vbeats.BAR else "beat" if st == 1 else st


def allot(weights, total):
    """Integer units per weight, each >= 1, summing to ``total`` (largest remainder)."""
    n = len(weights)
    total = max(total, n)
    ws = sum(weights) or 1.0
    extra = total - n
    raw = [extra * w / ws for w in weights]
    out = [1 + int(math.floor(r)) for r in raw]
    rest = total - sum(out)
    for i in sorted(range(n), key=lambda i: raw[i] - math.floor(raw[i]), reverse=True)[:rest]:
        out[i] += 1
    return out


class MusicTimeline:
    """Same surface as timeline.Timeline (units, shots, subs, total, sec_bounds, pace) plus beats/cuts."""

    def __init__(self, C):
        from .timeline import PACING
        cfg = self.cfg = config(C)
        b = self.beats = analyze(C)
        pace = dict(PACING)
        pace.update(getattr(C.spec, "PACING", {}) or {})
        step = grid_step(cfg)
        phase = b.downbeat_phase if step % vbeats.BAR == 0 else 0
        self.m0 = m0 = float(cfg["start"] or 0)
        k0 = math.ceil((b.beat_n(m0) - phase) / step - 1e-6)
        G = lambda k: float(b.beat_t(phase + (k0 + k) * step))
        unit = step * b.period
        avail = int((b.duration - 0.25 - G(0)) // unit)       # grid points inside the track after G(0)
        script = C.spec.SCRIPT
        flat = [(i, sec, sh) for i, (sec, _, shots) in enumerate(script) for sh in shots]
        if not flat:
            raise SystemExit("SCRIPT has no shots")
        if cfg["length"]:
            U = int((float(cfg["length"]) + m0 - G(0)) // unit)
        else:
            U = int(round(sum(sh[1] for _, _, sh in flat) * float(cfg["per"])))
        U = max(U, len(flat))
        if U > avail:
            print(f"! music has {avail} {cfg['grid']} units after {m0:.1f}s; wanted {U} - "
                  f"{'shots get fewer units' if avail >= len(flat) else 'the bed will loop'}")
            U = max(avail, len(flat))
        # ---- per section: target unit counts by weight, boundaries moved onto music sections
        secs = sorted({sec for _, sec, _ in flat})
        sw = {s: sum(sh[1] for _, sec, sh in flat if sec == s) for s in secs}
        nshots = {s: sum(1 for _, sec, _ in flat if sec == s) for s in secs}
        counts = allot([sw[s] for s in secs], U)
        bounds = [0]
        for c in counts:
            bounds.append(bounds[-1] + c)
        self.snapped = []
        if cfg["sections"] and len(secs) > 1 and b.sections:
            mb = sorted({int(round((b.beat_n(s["start"]) - phase) / step)) - k0 for s in b.sections[1:]})
            for j in range(1, len(bounds) - 1):
                tol = max(1, int(round(0.25 * min(counts[j - 1], counts[j]))))
                near = [m for m in mb if abs(m - bounds[j]) <= tol
                        and m - bounds[j - 1] >= nshots[secs[j - 1]] and bounds[j + 1] - m >= nshots[secs[j]]]
                if near:
                    m = min(near, key=lambda m: abs(m - bounds[j]))
                    if m != bounds[j]:
                        self.snapped.append((secs[j], bounds[j], m))
                    bounds[j] = m
        units_per_shot = []
        for j, s in enumerate(secs):
            ws = [sh[1] for _, sec, sh in flat if sec == s]
            units_per_shot += allot(ws, bounds[j + 1] - bounds[j])
        # ---- shots on the grid
        trd0 = cfg["trd"] if cfg["trd"] is not None else min(1.4, max(0.25, 0.5 * unit))
        self.units, self.shots, self.subs = [], [], []
        c = 0
        for (i, sec, (src, w, mo, opt)), n in zip(flat, units_per_shot):
            a, e = G(c) - m0, G(c + n) - m0
            sh = dict(src=src, start=max(0.0, a), end=e, motion=mo, sec=sec, item=i, units=n, **(opt or {}))
            sh.setdefault("tr", cfg["tr"])
            if "trd" not in sh:     # the bed's own slow default for the default transition, the type's own otherwise
                sh["trd"] = trd0 if sh["tr"] == cfg["tr"] else TRD.get(sh["tr"], 0.4)
            self.shots.append(sh)
            c += n
        self.shots[0]["start"] = 0.0
        self.total = G(c) - m0 + float(cfg["tail"] or 0)
        pace["end_fade"] = min(max(pace["end_fade"], 2 * b.period), 0.5 * (self.shots[-1]["end"] - self.shots[-1]["start"]))
        self.pace = pace
        self.cuts = [G(sum(units_per_shot[:k])) for k in range(1, len(self.shots))]   # music time of every cut
        # ---- section bounds (chapter cards + header progress)
        n = len(C.SECTIONS)
        bnd = []
        for s in range(n):
            st = [sh["start"] for sh in self.shots if sh["sec"] == s]
            bnd.append(min(st) if st else (bnd[-1] if bnd else 0.0))
        bnd[0] = 0.0
        bnd.append(self.total)
        self.sec_bounds = bnd
        for k, sh in enumerate(self.shots):
            if k == 0:
                sh["tr"], sh["trd"] = None, 0
        for k, sh in enumerate(self.shots):
            sh["tail"] = self.shots[k + 1]["trd"] if k + 1 < len(self.shots) else 99
        # ---- on-screen text: each item's lines share the item's span
        style = cfg["captions"]
        if style:
            for i, (sec, chunks, _) in enumerate(script):
                mine = [sh for sh in self.shots if sh["item"] == i]
                if not mine or not chunks:
                    continue
                a, e = mine[0]["start"], mine[-1]["end"]
                part = (e - a) / len(chunks)
                for k, (en, zh) in enumerate(chunks):
                    st = a + k * part + min(0.6, 0.15 * part) + (mine[0]["trd"] if k == 0 else 0) * 0.5
                    self.subs.append(dict(en=en, zh=zh, start=st, end=a + (k + 1) * part - min(0.5, 0.12 * part),
                                          sec=sec, style="title" if style == "title" else "subs"))

    def section_at(self, gt):
        return max(i for i in range(len(self.sec_bounds) - 1) if self.sec_bounds[i] <= gt)

    def summary(self):
        b = self.beats
        return (f"music {b.bpm:.1f} BPM (grid {'ok' if b.grid_ok else 'raw'}, p90 {b.residual_p90_ms:.1f} ms), "
                f"cuts on {self.cfg['grid']}s from {self.m0:.1f}s | total {self.total:.1f}s, {len(self.shots)} shots, "
                f"{len(self.subs)} text cues" + (f", sections moved onto music: {self.snapped}" if self.snapped else ""))

    def verify(self, fps):
        return vbeats.verify(self.cuts, self.beats, tol_frames=3, fps=fps, grid=verify_grid(self.cfg))

    def save(self, path, fps):
        v = self.verify(fps)
        with open(path, "w") as f:
            json.dump(dict(bpm=self.beats.bpm, grid=self.cfg["grid"], music_start=self.m0, total=self.total,
                           cuts_music_time=[round(t, 4) for t in self.cuts],
                           shots=[dict(src=s["src"], start=round(s["start"], 3), end=round(s["end"], 3), units=s["units"],
                                       sec=s["sec"]) for s in self.shots],
                           verify={k: v[k] for k in ("ok", "n_bad", "max_abs_frames", "mean_abs_ms")}), f, indent=1)
        return v
