"""MODE = "music": the timeline is driven by the music bed instead of narration timing.

    MUSIC = dict(grid="bar",        # cut grid: "bar" (calm, 文艺片) | "beat" | "2" (every 2 beats) | number of beats
                 per=1.0,           # grid units per unit of shot weight (weight 2 = 2 bars at per=1)
                 length=None,       # target seconds (overrides per; units are spread by weight)
                 start=0.0,         # seconds to skip into the track (video t=0 = this music time)
                 tr="fade", trd=None,   # default transition + duration (None = half a grid unit, 0.25-1.4 s)
                 sections=True,     # move spec section boundaries onto the music's section changes when close
                 captions="title",  # "title" (quiet serif text) | "subs" (speech-style) | False
                 lufs=-16,          # music stem level before the final loudnorm
                 backend="auto",    # beats.analyze backend: auto | numpy | librosa
                 min_seconds=None)  # {kind: s} overrides MIN_SECONDS (shortest time per shot kind)

Each shot gets a whole number of grid units by weight, so every cut lands on a beat / downbeat. With ``length``
(or ``min_seconds``) set, each shot gets at least its kind's minimum (MIN_SECONDS: collage / grid / rows / deck 2.5 s, film / route / quote 3 s,
split 2 s, else 1 unit; MUSIC min_seconds={...} or a shot's ``min_s=`` override): sections are sized by weight
but never below the sum of their shots' minimums, and a ``length`` too short for them is raised (with a
printed suggestion) instead of squeezing a late chapter into 1-bar shots. In plain ``per`` mode (weight 1 =
``per`` units, the old contract) short multi-picture shots are only warned about.
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
                captions="title", lufs=-16.0, tail=0.0, backend="auto", min_seconds=None)

# Shortest readable on-screen time per shot kind (seconds). Multi-picture shots need time to be read; a
# tight ``length`` used to squeeze a late chapter's collage / film strip into a single bar. Override per kind
# with MUSIC min_seconds={"collage": 3.0, ...}; a shot's own ``min_s=`` option wins. Kinds not listed: 1 unit.
MIN_SECONDS = dict(collage=2.5, film=3.0, grid=2.5, rows=2.5, deck=2.5, route=3.0, quote=3.0, split=2.0)


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


def allot_min(weights, total, mins):
    """Integer units per weight summing to ``total`` with out[i] >= mins[i] (>= 1): proportional to weight,
    shots whose share falls under their minimum are pinned there and the rest is re-shared (largest
    remainder). ``total`` below sum(mins) returns the minimums (the caller warns)."""
    n = len(weights)
    mins = [max(1, int(m)) for m in mins]
    total = max(int(total), sum(mins))
    plain = allot(weights, total)
    if all(a >= m for a, m in zip(plain, mins)):          # nothing under its minimum: the historical split
        return plain
    fixed = {}
    while True:
        free = [i for i in range(n) if i not in fixed]
        left = total - sum(fixed.values())
        ws = sum(weights[i] for i in free) or 1.0
        want = {i: left * weights[i] / ws for i in free}
        low = [i for i in free if want[i] < mins[i]]
        if not low:
            break
        for i in low:
            fixed[i] = mins[i]
    out = [fixed.get(i, 0) for i in range(n)]
    for i in free:
        out[i] = max(mins[i], int(math.floor(want[i])))
    rest = total - sum(out)
    order = sorted(free, key=lambda i: want[i] - math.floor(want[i]), reverse=True) or list(range(n))
    k = 0
    while rest > 0:
        out[order[k % len(order)]] += 1
        rest -= 1
        k += 1
    while rest < 0:                                   # rounding up to a minimum overshot: take from the largest
        cand = [i for i in range(n) if out[i] > mins[i]]
        if not cand:
            break
        j = max(cand, key=lambda i: out[i] - mins[i])
        out[j] -= 1
        rest += 1
    return out


def shot_kind(src):
    k = str(src).split(":", 1)[0] if ":" in str(src) else ("video" if str(src).startswith("v") else "img")
    return k if k in MIN_SECONDS or k in ("video", "img") else "img"


def min_units(cfg, flat, unit):
    """Minimum grid units per shot from MIN_SECONDS / MUSIC min_seconds / the shot's ``min_s`` option."""
    table = dict(MIN_SECONDS)
    table.update(cfg.get("min_seconds") or {})
    out = []
    for _, _, (src, _w, _mo, opt) in flat:
        sec = (opt or {}).get("min_s", table.get(shot_kind(src), 0.0))
        out.append(max(1, int(math.ceil(float(sec or 0.0) / unit - 1e-6))))
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
        mins = min_units(cfg, flat, unit)
        if not cfg["length"] and not cfg.get("min_seconds"):
            # per-weight mode: weight 1 = ``per`` units is the contract - only warn about short multi-picture shots
            got = [max(1, int(round(sh[1] * float(cfg["per"])))) for _, _, sh in flat]
            short = [f"{sh[0]} ({g} < {m})" for (_, _, sh), g, m in zip(flat, got, mins) if g < m]
            if short:
                print(f"! {len(short)} multi-picture shot(s) get fewer {cfg['grid']} units than their minimum time: "
                      f"{', '.join(short[:4])}{' ...' if len(short) > 4 else ''} - raise their weight or set "
                      "MUSIC min_seconds / length")
            mins = [1] * len(flat)
        self.min_units = mins
        if cfg["length"]:
            U = int((float(cfg["length"]) + m0 - G(0)) // unit)
        else:
            U = int(round(sum(sh[1] for _, _, sh in flat) * float(cfg["per"])))
        if U < sum(mins):
            need = G(sum(mins)) - G(0)
            short = [f"{sh[0]} ({mn} {cfg['grid']})" for (_, _, sh), mn in zip(flat, mins) if mn > 1]
            print(f"! length: {U} {cfg['grid']} units is too short for the minimum shot times "
                  f"({sum(mins)} units = {need:.1f}s; multi-picture shots: {', '.join(short[:6])}"
                  f"{' ...' if len(short) > 6 else ''}). Using {need:.1f}s instead of squeezing - set "
                  f"MUSIC length={math.ceil(need + float(cfg['tail'] or 0))} (or drop a shot / lower min_seconds).")
        U = max(U, sum(mins))
        if U > avail:
            print(f"! music has {avail} {cfg['grid']} units after {m0:.1f}s; wanted {U} - "
                  f"{'shots get fewer units' if avail >= sum(mins) else 'the bed will loop'}")
            U = max(avail, sum(mins))
        # ---- per section: target unit counts by weight, boundaries moved onto music sections
        secs = sorted({sec for _, sec, _ in flat})
        sw = {s: sum(sh[1] for _, sec, sh in flat if sec == s) for s in secs}
        smin = {s: sum(m for (_, sec, _), m in zip(flat, mins) if sec == s) for s in secs}
        counts = allot_min([sw[s] for s in secs], U, [smin[s] for s in secs])
        bounds = [0]
        for c in counts:
            bounds.append(bounds[-1] + c)
        self.snapped = []
        if cfg["sections"] and len(secs) > 1 and b.sections:
            mb = sorted({int(round((b.beat_n(s["start"]) - phase) / step)) - k0 for s in b.sections[1:]})
            for j in range(1, len(bounds) - 1):
                tol = max(1, int(round(0.25 * min(counts[j - 1], counts[j]))))
                near = [m for m in mb if abs(m - bounds[j]) <= tol
                        and m - bounds[j - 1] >= smin[secs[j - 1]] and bounds[j + 1] - m >= smin[secs[j]]]
                if near:
                    m = min(near, key=lambda m: abs(m - bounds[j]))
                    if m != bounds[j]:
                        self.snapped.append((secs[j], bounds[j], m))
                    bounds[j] = m
        units_per_shot = []
        for j, s in enumerate(secs):
            ws = [sh[1] for _, sec, sh in flat if sec == s]
            ms = [m for (_, sec, _), m in zip(flat, mins) if sec == s]
            units_per_shot += allot_min(ws, bounds[j + 1] - bounds[j], ms)
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
