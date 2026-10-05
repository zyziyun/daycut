"""Beat-grid planning for the fun travel vlog: which source plays where, every cut ON a beat.

Video time 0 = a downbeat of the music (``music_start: "auto"`` = first downbeat; a number is snapped to the
nearest bar). All shot boundaries are whole beats of that grid (``Beats.beat_t``), so ``beats.verify``
can prove them after frame rounding.

Timeline (beats.energy_arc "travel-fun" sets the body's cut pattern):
  hook      best 3-5 windows of the whole trip, ``cut_plan(..., "accelerate")`` into the first bar line
            after 8 beats; hard cuts (the drums carry them)
  intro     the edit list's shots start; title pops on the bar line (flash = full-frame hit #1)
  body      shots in edit-list order. Shot length by section pattern: every-beat 1 unit, every-2 2 units,
            every-bar 4 beats (breather); 1 unit = 1 beat, 2 beats when the beat is shorter than 0.42 s.
            Speech shots keep whole sentences (length = speech rounded UP to the next beat); photos 2 units;
            ramped / slow-mo shots >= 1 bar; a ``dur`` (source s) or ``beats`` in the edit list wins.
            A new place / day starts on a bar line (previous shot extended <= 3 beats) and gets a styled
            transition (whip, once glitch); a music drop gets a cut exactly on it (zoom punch + impact).
  finale    best windows again, one per clip, accelerating into the outro bar (riser -> impact -> sparkle)
  outro     one slow wide shot (speed 0.8) for 2 bars, end card on the last bar(s)
Budgets: <= 3 full-frame hits (flash / zoom punch), >= 16 beats apart (A4); one transition per cut, frames
borrowed from both neighbours (A5); a transition is dropped to a hard cut when a neighbour is too short.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
import copy
import json
import math
import os

import numpy as np

from vstudio import beats as BT
from vstudio import media

from . import score as SC
from .frames import ramp_keys, src_span_of, trans_frames

HIT_KINDS = ("flash", "zoom")
TRANSITIONS = ("cut", "whip", "zoom", "flash", "leak", "glitch")


def shift_beats(b, m0):
    """Copy of a Beats analysis with every time shifted by -m0 (music time -> video time)."""
    c = copy.deepcopy(b)
    c.beats = np.asarray(b.beats) - m0
    c.raw_beats = np.asarray(b.raw_beats) - m0
    c.offset = b.offset - m0
    c.sections = [dict(s, start=s["start"] - m0, end=s["end"] - m0) for s in b.sections]
    c.hits = [dict(h, t=h["t"] - m0) for h in b.hits]
    c.onsets = {k: [(t - m0, s) for t, s in v] for k, v in (b.onsets or {}).items()}
    c.duration = b.duration - m0
    if b.rms is not None:
        c.rms = b.rms[max(0, int(round(m0 / b.rms_hop))):]
    return c


def music_origin(b, music_start="auto"):
    """Music time of video t=0: the first downbeat >= 0 ("auto") or the bar nearest ``music_start``."""
    bar = BT.BAR * b.period
    if music_start in (None, "auto"):
        n = math.ceil((0.0 - float(b.bar_t(0))) / bar - 1e-6)
        return float(b.bar_t(n))
    return float(b.snap(float(music_start), "bar"))


# ----------------------------------------------------------------------------- speech
def _norm_words(ws):
    out = []
    for w in ws:
        if "t" in w:
            out.append(dict(w=str(w["w"]).strip(), t=float(w["t"]), te=float(w["te"])))
        else:
            out.append(dict(w=str(w["word"]).strip(), t=float(w["start"]), te=float(w["end"])))
    return [w for w in out if w["w"]]


def sentences(words, gap=0.6):
    """Group words into sentences: a gap > ``gap`` s, or sentence-final punctuation then >= 0.25 s."""
    out, cur = [], []
    for w in words:
        if cur and (w["t"] - cur[-1]["te"] > gap or
                    (cur[-1]["w"][-1:] in ".?!。？！" and w["t"] - cur[-1]["te"] >= 0.25)):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [dict(a=s[0]["t"], b=s[-1]["te"], words=s) for s in out]


def voiced_sentences(src, start=0.0, dur=None):
    """Speech-like runs from the RMS envelope when no transcript exists. Returns (runs, contrast_db)."""
    from vstudio import audio as A
    x = A.decode_audio(src, start=start or None, dur=dur)
    if len(x) == 0:
        return [], 0.0
    env, hop = A.rms_envelope(x, A.SR, hop=0.01, win=0.03)
    lo, hi = float(np.percentile(env, 10)), float(np.percentile(env, 95))
    thr = lo + max(12.0, 0.4 * (hi - lo))
    runs = A.voiced_runs(env, hop, threshold_db=thr, min_run=0.15, max_gap=0.6, t0=start or 0.0)
    return [dict(a=a, b=b, words=[]) for a, b in runs if b - a >= 0.3], hi - lo


def load_speech(src, shot, cfg, warnings):
    """(words or None, sentences, source of truth) for a clip that may carry speech."""
    words = None
    wf = shot.get("words")
    if not wf:
        side = os.path.splitext(src)[0] + ".words.json"
        wf = side if os.path.exists(side) else None
    elif not os.path.isabs(wf):
        wf = os.path.join(os.path.dirname(src), wf) if not os.path.exists(wf) else wf
    how = None
    if wf and os.path.exists(wf):
        with open(wf) as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("words") or [w for s in data.get("segments", []) for w in s.get("words", [])]
        words, how = _norm_words(data), "transcript file"
    elif cfg.get("asr", True):
        try:
            from vstudio import asr
            tr = asr.transcribe(src, language=cfg.get("language"))
            words, how = asr.words_of(tr), "asr"
        except Exception as e:                                   # no whisper backend: fall back to RMS
            warnings.append(f"{os.path.basename(src)}: ASR unavailable ({type(e).__name__}); speech found from "
                            "loudness only, no captions")
    if words:
        return words, sentences(words), how
    runs, contrast = voiced_sentences(src)
    return None, (runs if contrast >= 15.0 else []), "rms"


def speech_window(sents, clip_dur, start=None, dur=None, max_speech=12.0, pre=0.15, post=0.25):
    """Source window that never cuts a sentence: a given window grows to whole sentences; without one the
    first sentences up to ``max_speech`` s (always at least one)."""
    if start is not None:
        a, b = float(start), float(start) + float(dur if dur is not None else max_speech)
        for s in sents:
            if s["a"] < b and s["b"] > a:
                a, b = min(a, s["a"] - pre), max(b, s["b"] + post)
    elif sents:
        a, b = sents[0]["a"] - pre, sents[0]["b"] + post
        for s in sents[1:]:
            if s["b"] + post - a > max_speech:
                break
            b = s["b"] + post
    else:
        a, b = 0.0, min(clip_dur, max_speech)
    return max(0.0, a), min(clip_dur, b)


# ----------------------------------------------------------------------------- planner
class Planner:
    def __init__(self, cfg, base, prof, bv, fps, cache_dir, warnings):
        self.cfg, self.base, self.prof, self.bv, self.fps = cfg, base, prof, bv, fps
        self.cache, self.warn = cache_dir, warnings
        self.period = float(bv.period)
        self.n0 = int(round(float(bv.beat_n(0.0))))
        self.phase = (int(bv.downbeat_phase) - self.n0) % BT.BAR
        self.u = 1 if self.period >= 0.42 else 2
        pace = cfg.get("pace", "fast")
        self.pace = {"fast": 1, "relaxed": 2}.get(pace, 1)
        self.scores = {}
        self.src_dir = os.path.join(base, os.path.expanduser(cfg.get("src_dir", ".")))
        self.photo_dir = os.path.join(base, os.path.expanduser(cfg.get("photo_dir", cfg.get("src_dir", "."))))

    # grid helpers (relative beat numbers: 0 = video t=0)
    def bt(self, n):
        return float(self.bv.beat_t(self.n0 + n))

    def next_bar(self, n):
        return n + (self.phase - n) % BT.BAR

    def is_bar(self, n):
        return (n - self.phase) % BT.BAR == 0

    def score_of(self, src):
        if src not in self.scores:
            self.scores[src] = SC.clip_scores(src, self.cache, faces=self.cfg.get("face_score", True))
        return self.scores[src]

    # ---- edit list -> prepared shots
    def resolve(self, name, photo=False):
        clips = self.cfg.get("clips") or {}
        name = clips.get(name, name)
        p = os.path.expanduser(name)
        if not os.path.isabs(p):
            p = os.path.join(self.photo_dir if photo else self.src_dir, p)
        if not os.path.exists(p):
            raise SystemExit(f"missing source: {p}")
        return p

    def prepare(self):
        shots = []
        for i, s in enumerate(self.cfg.get("shots") or self.cfg.get("segments") or []):
            s = dict(s)
            if s.get("photo"):
                s.update(kind="photo", src=self.resolve(s["photo"], photo=True))
                shots.append(s)
                continue
            src = self.resolve(s["clip"])
            info = media.probe(src)
            s.update(kind="video", src=src, info=dict(fps=info["fps"], duration=info["duration"],
                                                     has_audio=info["has_audio"], w=info["display_w"],
                                                     h=info["display_h"], transfer=info["transfer"]))
            sp = s.get("speech", False)
            if sp and info["has_audio"]:
                words, sents, how = load_speech(src, s, self.cfg, self.warn)
                if sp == "auto" and not (words and len(words) >= 2) and not sents:
                    sp = False
                elif sp == "auto" and how == "rms" and sum(x["b"] - x["a"] for x in sents) < 1.0:
                    sp = False
                if sp:
                    a, b = speech_window(sents, info["duration"], s.get("start"), s.get("dur"),
                                         float(self.cfg.get("max_speech", 12.0)))
                    pieces = [(a, b)]
                    wl = [w for w in (words or []) if a <= (w["t"] + w["te"]) / 2 <= b]
                    if self.cfg.get("tighten") or s.get("tighten"):
                        if wl:
                            from vstudio import cut as C
                            pieces = [tuple(p) for p in C.tighten(wl, keep=[(a, b)])] or pieces
                        else:
                            self.warn.append(f"{os.path.basename(src)}: tighten needs words; skipped")
                    s.update(speech=True, pieces=pieces, words=wl, speech_from=how,
                             sentences=[(round(x["a"], 3), round(x["b"], 3)) for x in sents if a <= x["a"] < b])
            elif sp and not info["has_audio"]:
                self.warn.append(f"{os.path.basename(src)}: speech requested but the clip has no audio")
            s["speech"] = bool(sp)
            shots.append(s)
        if not shots:
            raise SystemExit("edit list has no shots")
        mp = self.cfg.get("map")
        self.map_slot = None
        if mp and mp.get("places"):
            # the route card gets its own breather slot: a blurred, dimmed best window under the card
            bg = next((x for x in shots if x["kind"] == "video" and not x.get("speech")), None)
            if bg is not None:
                self.map_slot = dict(kind="video", src=bg["src"], info=bg["info"], speech=False, map_slot=True,
                                     bg_blur=True, beats=int(mp.get("beats", 8)),
                                     transition=mp.get("transition"), after=mp.get("after"))
            else:
                self.warn.append("map: no silent video clip for the card background; map skipped")
        return shots

    # ---- lengths
    def pattern_beats(self, pattern):
        return {"every-beat": self.u * self.pace, "every-2": 2 * self.u * self.pace, "every-bar": 4,
                "accelerate": self.u * self.pace, "drop": self.u * self.pace}.get(pattern, 2 * self.u)

    def shot_beats(self, s, pattern):
        P = self.period
        if s.get("beats"):
            return max(1, int(s["beats"]))
        if s["kind"] == "photo":
            return max(2 * self.u, 4 if pattern == "every-bar" else 0)
        if s.get("speech"):
            L = sum(b - a for a, b in s["pieces"])
            return max(1, math.ceil((L + 0.05) / P - 1e-6))
        nb = None
        if s.get("dur") and not s.get("ramp"):
            nb = max(1, int(round(float(s["dur"]) / float(s.get("speed", self.cfg.get("speed", 1.0))) / P)))
        elif s.get("ramp"):
            nb = 4
        if nb is None:
            nb = self.pattern_beats(pattern)
        if s.get("freeze"):
            nb += self.freeze_beats(s)
        return nb

    def title_beats(self):
        """Beats the title pop occupies (pop 0.35 s + hold + 0.2 s out); 0 without a title."""
        t = self.cfg.get("title")
        if not t:
            return 0
        hold = max(1.2, float((t if isinstance(t, dict) else {}).get("hold", 3 * self.period)))
        return math.ceil((hold + 0.55) / self.period - 1e-6)

    def freeze_beats(self, s):
        f = s.get("freeze")
        if f is True:
            return 2 * self.u
        return max(1, int(round(float(f) / self.period)))

    # ---- auto windows
    def broll_pool(self, shots):
        pool = []
        seen = set()
        for s in shots:
            if s["kind"] == "video" and not s.get("speech") and s["src"] not in seen:
                seen.add(s["src"])
                sc = self.score_of(s["src"])
                pool.append((SC.best_second(sc)[1], s["src"], s))
        pool.sort(key=lambda r: -r[0])
        return pool

    def highlight(self, src, nb, avoid, speed=1.0):
        L = nb * self.period * speed
        st, sc = SC.pick_window(self.score_of(src), L, avoid=avoid.get(src, []))
        avoid.setdefault(src, []).append((st, st + L))
        return dict(kind="video", src=src, start=st, speed=speed, auto=True, score=sc,
                    info=dict(fps=media.probe(src)["fps"]))

    # ---- full plan
    def plan(self):
        shots = self.prepare()
        pool = self.broll_pool(shots)
        drops = self.drop_beats()
        T_est = None
        for _ in range(2):                                 # arc from an estimate, then from the result
            tl, meta = self._place(shots, pool, drops, T_est)
            T_est = self.bt(meta["n_end"])
        meta["arc"] = BT.energy_arc(T_est, "travel-fun", beats=self.bv)
        self._windows(tl)
        cuts = self._transitions(tl, meta)
        return tl, cuts, meta

    def drop_beats(self):
        out = []
        m0 = float(self.cfg.get("_m0", 0.0))
        for t in self.cfg.get("drops") or []:
            out.append(float(t) - m0)
        if not self.cfg.get("drops"):
            secs = self.bv.sections
            for a, b in zip(secs, secs[1:]):
                if b["energy"] >= a["energy"] + 0.15:
                    out.append(b["start"])
        return sorted({int(round(float(self.bv.beat_n(t)) - self.n0)) for t in out if t > 0})

    def _arc_pattern(self, arc, n):
        t = self.bt(n)
        for s in arc or []:
            if s["start"] - 1e-6 <= t < s["end"]:
                return s["pattern"], s["name"]
        return "every-2", "body"

    def _place(self, shots, pool, drops, T_est):
        u = self.u
        arc = BT.energy_arc(T_est, "travel-fun", beats=self.bv) if T_est else None
        tl, n = [], 0
        avoid = {}
        meta = dict(drops_used=[])
        # hook: best windows, accelerate into the bar line 8 units in
        hook_n = min(5, len(pool)) if self.cfg.get("hook", True) else 0
        if hook_n >= 3:
            end_n = 8 * u
            lad = tuple(x * u for x in (2, 2, 1, 1))[:hook_n - 1]
            cuts = self.bv.cut_plan(hook_n, self.bt(0) + 1e-3, self.bt(end_n) + 1e-6, "accelerate", ladder=lad)
            ns = [0] + [int(round(float(self.bv.beat_n(c)) - self.n0)) for c in cuts]
            picks = [pool[k % len(pool)][1] for k in range(hook_n)]
            for k in range(hook_n):
                nb = ns[k + 1] - ns[k]
                h = self.highlight(picks[k], nb, avoid)
                h.update(role="hook", n0=ns[k], nb=nb, section="hook")
                tl.append(h)
            n = ns[-1]
        meta["hook_end"] = n
        meta["intro_n"] = n
        prev = None
        pending = dict(self.map_slot) if self.map_slot else None
        after = pending.get("after") if pending else None
        need = meta["intro_n"] + self.title_beats()
        for k, s in enumerate(shots):
            if pending and after is None and prev is not None and n >= need:
                n, prev = self._place_one(pending, tl, n, prev, arc, drops, meta, need)
                pending = None
            n, prev = self._place_one(s, tl, n, prev, arc, drops, meta, need)
            if pending and after is not None and k + 1 >= int(after):
                n, prev = self._place_one(pending, tl, n, prev, arc, drops, meta, need)
                pending = None
        if pending:
            n, prev = self._place_one(pending, tl, n, prev, arc, drops, meta, need)
        for d in drops:
            if d not in meta["drops_used"] and any(t["n0"] == d for t in tl):
                meta["drops_used"].append(d)
        # finale on a bar line
        fin_n = min(5, len(pool)) if self.cfg.get("finale", True) else 0
        if fin_n >= 3:
            if not self.is_bar(n):
                ext = self.next_bar(n) - n
                tl[-1]["nb"] += ext
                n += ext
            meta["finale_n"] = n
            end_n = n + 8 * u
            lad = tuple(x * u for x in (2, 2, 1, 1))[:fin_n - 1]
            cuts = self.bv.cut_plan(fin_n, self.bt(n) + 1e-3, self.bt(end_n) + 1e-6, "accelerate", ladder=lad)
            ns = [n] + [int(round(float(self.bv.beat_n(c)) - self.n0)) for c in cuts]
            for k in range(fin_n):
                nb = ns[k + 1] - ns[k]
                src = pool[k % len(pool)][1]
                h = self.highlight(src, nb, avoid)
                h.update(role="finale", n0=ns[k], nb=nb, section="finale")
                tl.append(h)
            n = ns[-1]
        # outro: a slow wide shot for 2 bars
        if self.cfg.get("outro", True) is not False:
            if not self.is_bar(n):
                ext = self.next_bar(n) - n
                tl[-1]["nb"] += ext
                n += ext
            nb = int(self.cfg.get("outro_beats", 8))
            o = self.cfg.get("outro") if isinstance(self.cfg.get("outro"), dict) else None
            if o:
                src = self.resolve(o["clip"])
                h = dict(kind="video", src=src, start=o.get("start"), speed=o.get("speed", 0.8),
                         info=dict(fps=media.probe(src)["fps"]))
            elif pool:
                # calmest good window: lowest motion among the top half by score
                src = pool[0][1]
                h = self.highlight(src, nb, avoid, speed=0.8)
            else:
                h = None
            if h:
                h.update(role="outro", n0=n, nb=nb, section="outro", speed=h.get("speed", 0.8))
                tl.append(h)
                meta["outro_n"] = n
                n += nb
        meta["n_end"] = n
        return tl, meta

    def _place_one(self, s, tl, n, prev, arc, drops, meta, need):
        if s.get("map_slot"):
            s = dict(s, place=(prev or {}).get("place"), day=(prev or {}).get("day"))
        pattern, sec = self._arc_pattern(arc, n) if arc else ("every-2", "body")
        if sec.startswith(("hook", "finale", "outro")):
            pattern = "every-2"
        nb = self.shot_beats(s, pattern)
        change = None
        if prev is not None:
            if s.get("day") is not None and s.get("day") != prev.get("day"):
                change = "day"
            elif s.get("place") and s.get("place") != prev.get("place"):
                change = "place"
        if s.get("map_slot"):
            # the route card starts after the title has had its hold (A1), on a bar line
            if tl and n < need:
                tl[-1]["nb"] += need - n
                n = need
            if tl and not self.is_bar(n):
                ext = self.next_bar(n) - n
                tl[-1]["nb"] += ext
                n += ext
        if change and tl and not self.is_bar(n):
            ext = self.next_bar(n) - n
            if ext <= 3:
                tl[-1]["nb"] += ext
                n += ext
        # a drop inside this shot -> cut exactly on it (not through speech)
        for d in drops:
            if d not in meta["drops_used"] and n < d < n + nb and not s.get("speech") and d - n >= 1:
                nb = d - n
                meta["drops_used"].append(d)
                break
        item = dict(s, role="body", n0=n, nb=nb, section=sec, pattern=pattern, change=change)
        tl.append(item)
        n += nb
        return n, s

    def _windows(self, tl):
        """Frame ranges + source windows (auto-picked when missing) for every placed shot."""
        fps = self.fps
        avoid = {}
        for s in tl:
            s["t0"], s["t1"] = self.bt(s["n0"]), self.bt(s["n0"] + s["nb"])
            s["f0"], s["f1"] = int(round(s["t0"] * fps)), int(round(s["t1"] * fps))
            if s["kind"] != "video":
                continue
            D = s["t1"] - s["t0"]
            fz = self.freeze_beats(s) * self.period if s.get("freeze") else 0.0
            live = max(1.0 / fps, D - fz)
            s["freeze_s"] = fz
            if s.get("speech"):
                L = sum(b - a for a, b in s["pieces"])
                extra = live - L
                a, b = s["pieces"][-1]
                s["pieces"][-1] = (a, b + max(0.0, extra))          # room tone + picture to the beat
                s["src_span"] = (s["pieces"][0][0], s["pieces"][-1][1])
                continue
            keys = ramp_keys(s.get("ramp"), (s.get("info") or {}).get("fps") or 30.0,
                             float(s.get("speed", self.cfg.get("speed", 1.0))))
            s["ramp_keys"] = keys
            need = src_span_of(keys, live)
            if s.get("start") is None:
                st, sc = SC.pick_window(self.score_of(s["src"]), need, avoid=avoid.get(s["src"], []))
                s["start"], s["auto"], s["score"] = st, True, sc
            dur = (s.get("info") or {}).get("duration") or media.probe(s["src"])["duration"]
            if s["start"] + need > dur + 1e-3:
                self.warn.append(f"{os.path.basename(s['src'])}: window {s['start']:.2f}+{need:.2f}s runs past the "
                                 f"clip end ({dur:.2f}s); last frame held")
            avoid.setdefault(s["src"], []).append((s["start"], s["start"] + need))
            s["src_span"] = (s["start"], s["start"] + need)
            minr = min(r for _, r in keys)
            if minr < 0.5 and ((s.get("info") or {}).get("fps") or 30) < 50:
                self.warn.append(f"{os.path.basename(s['src'])}: rate {minr:g} on a "
                                 f"{(s.get('info') or {}).get('fps') or 30:g} fps source is not true slow-mo "
                                 "(frames blended); shoot 60/120 fps for clean slow motion")

    # ---- transitions + budgets
    def _transitions(self, tl, meta):
        cuts = []
        whip_dir = 1
        changes = 0
        glitch_used = False
        photo_seen = 0
        for i in range(1, len(tl)):
            a, b = tl[i - 1], tl[i]
            kind, reason = "cut", "beat"
            if b["role"] == "body" and a["role"] == "hook":
                kind, reason = "flash", "title"
            elif b["role"] == "finale" and a["role"] != "finale":
                kind, reason = "zoom", "finale"
            elif b["role"] == "outro":
                kind, reason = "leak", "outro"
            elif b["role"] == "body":
                if b["n0"] in meta.get("drops_used", []):
                    kind, reason = "zoom", "drop"
                elif b.get("change"):
                    changes += 1
                    reason = b["change"]
                    if changes == 3 and not glitch_used:
                        kind, glitch_used = "glitch", True
                    else:
                        kind = "whip"
                elif b["kind"] == "photo":
                    photo_seen += 1
                    kind, reason = ("flash" if photo_seen == 1 else "leak"), "photo"
                elif b.get("speech"):
                    kind, reason = "cut", "speech"
            if b.get("transition"):
                kind, reason = b["transition"], "requested"
                if kind not in TRANSITIONS:
                    raise SystemExit(f"transition {kind!r}: one of {TRANSITIONS}")
            c = dict(i=i, n=b["n0"], t=round(b["t0"], 5), frame=b["f0"], kind=kind, reason=reason)
            if kind == "whip":
                c["dir"] = whip_dir
                whip_dir = -whip_dir
            cuts.append(c)
        # A5: frames borrowed from both neighbours - drop to a hard cut if a neighbour is too short
        for c in cuts:
            pre, post = trans_frames(c["kind"], self.fps)
            a, b = tl[c["i"] - 1], tl[c["i"]]
            if (a["f1"] - a["f0"]) < pre + 2 or (b["f1"] - b["f0"]) < post + 2:
                if c["kind"] != "cut":
                    c["note"] = f"{c['kind']} dropped: neighbour shorter than its {pre}+{post} frames"
                    c["kind"] = "cut"
        # A4: <= 3 full-frame hits, >= 16 beats apart; priority finale > title > drop > photo > requested
        prio = {"finale": 0, "title": 1, "drop": 2, "photo": 3, "requested": 4}
        hits = []
        for c in sorted([c for c in cuts if c["kind"] in HIT_KINDS], key=lambda c: (prio.get(c["reason"], 5), c["n"])):
            ok = len(hits) < int(self.cfg.get("max_hits", 3)) and all(abs(c["n"] - h["n"]) >= 16 for h in hits)
            if ok:
                hits.append(c)
            else:
                c["note"] = f"{c['kind']} -> leak (full-frame hit budget, A4)"
                c["kind"] = "leak"
        meta["hits"] = [dict(n=h["n"], t=h["t"], kind=h["kind"], reason=h["reason"]) for h in sorted(hits, key=lambda h: h["n"])]
        return cuts
