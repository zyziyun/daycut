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
import json
import math
import os
import re

import numpy as np

from vstudio import beats as BT
from vstudio import media

from . import score as SC
from . import speechclean as SPC
from .frames import ramp_keys, src_span_of, trans_frames

HIT_KINDS = ("flash", "zoom")
TRANSITIONS = ("cut", "whip", "zoom", "flash", "leak", "glitch")


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


# Whisper's stock hallucinations on music / ambience (subtitle credits, "like and subscribe", outros).
# Used only when vstudio.asr has no drop_hallucinations of its own.
HALLUCINATION_RE = re.compile(
    r"字幕(志愿者|由|提供|制作|製作|组)|不吝点赞|点赞.{0,4}订阅|订阅.{0,6}(频道|栏目|转发)|打赏支持|明镜与点点|"
    r"优优独播|thank(s| you) for watching|please (like|subscribe)|subtitles? by|amara\.org", re.I)


def drop_hallucinations(tr):
    """Transcript without whisper's stock hallucinations (``vstudio.asr.drop_hallucinations`` when the
    library has it; else a phrase filter + zero-length words dropped). Returns a transcript dict."""
    from vstudio import asr
    fn = getattr(asr, "drop_hallucinations", None)
    if fn is not None:
        try:
            out = fn(tr)
            if isinstance(out, dict):
                out.setdefault("words", asr.words_of(out))
                return out
            if isinstance(out, list):                        # a flat word list
                return dict(tr, words=_norm_words(out))
        except Exception:                                     # noqa: BLE001 - fall back to the local filter
            pass
    segs = [s for s in (tr.get("segments") or []) if not HALLUCINATION_RE.search(str(s.get("text", "")))]
    out = dict(tr, segments=segs)
    out["words"] = [w for w in asr.words_of(out) if w["te"] - w["t"] >= 0.02]
    return out


def has_speech_text(tr, min_words=4):
    """Enough real words in a (hallucination-filtered) transcript: ``vstudio.asr.has_speech`` when present."""
    from vstudio import asr
    fn = getattr(asr, "has_speech", None)
    if fn is not None:
        try:
            return bool(fn(tr, min_words=min_words))
        except Exception:                                     # noqa: BLE001
            pass
    return len([w for w in (tr.get("words") or []) if w["te"] - w["t"] >= 0.02]) >= min_words


def speech_evidence(src, words, min_contrast=10.0, min_overlap=0.5):
    """Does the clip's own loudness back up the transcript? Speech has pauses (envelope contrast, 10th vs
    95th percentile) and the words sit inside its voiced runs. Music / ride ambience under a hallucinated
    transcript fails one of the two. Returns (ok, details)."""
    runs, contrast = voiced_sentences(src)
    real = [w for w in words or [] if w["te"] - w["t"] >= 0.02]
    if not real:
        return False, dict(contrast_db=round(contrast, 1), overlap=0.0)
    inside = sum(1 for w in real if any(r["a"] - 0.25 <= (w["t"] + w["te"]) / 2 <= r["b"] + 0.25 for r in runs))
    ov = inside / len(real)
    return (contrast >= min_contrast and ov >= min_overlap), dict(contrast_db=round(contrast, 1), overlap=round(ov, 2))


def load_speech(src, shot, cfg, warnings, log=None):
    """(words or None, sentences, source of truth) for a clip that may carry speech.

    ASR words are only trusted when the transcript survives the hallucination filter, has >= ``min_words``
    (``speech_min_words``, 4) real words AND the clip's loudness shows speech where the words are
    (``speech_evidence``). Otherwise words = None (no captions) and, for ``speech: "auto"``, no speech.
    ``log`` (dict) receives the decision and why."""
    log = log if log is not None else {}
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
        log.update(source=how, words=len(words), reason="words from the transcript file")
    elif cfg.get("asr", True):
        try:
            from vstudio import asr
            tr = asr.transcribe(src, language=cfg.get("language"))
        except Exception as e:                                   # no whisper backend: fall back to RMS
            tr = None
            warnings.append(f"{os.path.basename(src)}: ASR unavailable ({type(e).__name__}); speech found from "
                            "loudness only, no captions")
        if tr is not None:
            n_raw = len(tr.get("words") or asr.words_of(tr))
            tr = drop_hallucinations(tr)
            cand = tr.get("words") or []
            text_ok = has_speech_text(tr, int(cfg.get("speech_min_words", 4)))
            ev_ok, ev = speech_evidence(src, cand)
            log.update(source="asr", words_raw=n_raw, words=len(cand), **ev)
            if text_ok and ev_ok:
                words, how = cand, "asr"
                log["reason"] = "transcript and loudness agree"
            else:
                why = []
                if not text_ok:
                    why.append(f"{len(cand)} real words after the hallucination filter (of {n_raw})")
                if not ev_ok:
                    why.append(f"loudness does not back the words (contrast {ev['contrast_db']} dB, "
                               f"{int(ev['overlap'] * 100)}% of words in voiced runs)")
                log.update(reason="ASR rejected: " + "; ".join(why), rejected_asr=True)
                warnings.append(f"{os.path.basename(src)}: ASR transcript rejected as non-speech / hallucination "
                                f"({'; '.join(why)}); no captions from it")
                return None, [], "asr-rejected"
    if words:
        return words, sentences(words), how
    runs, contrast = voiced_sentences(src)
    log.setdefault("source", "rms")
    log.update(contrast_db=round(contrast, 1))
    log.setdefault("reason", f"loudness only (contrast {contrast:.1f} dB, speech needs >= 15)")
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
        self.speech_log = []                                 # per-clip speech decision + why (report)
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
                log = dict(clip=os.path.basename(src), requested=sp)
                words, sents, how = load_speech(src, s, self.cfg, self.warn, log)
                if sp == "auto" and how == "asr-rejected":
                    sp = False
                elif sp == "auto" and not (words and len(words) >= 2) and not sents:
                    sp = False
                elif sp == "auto" and how == "rms" and sum(x["b"] - x["a"] for x in sents) < 1.0:
                    sp = False
                elif sp is True and how == "asr-rejected":
                    # forced speech keeps the clip's audio over its first seconds, captions off
                    sents = voiced_sentences(src)[0]
                log.update(speech=bool(sp), captions=bool(sp and words))
                self.speech_log.append(log)
                print(f"[fun] speech {log['clip']}: {'SPEECH' if sp else 'no speech'} "
                      f"({log.get('reason', how)})", flush=True)
                if sp:
                    a, b = speech_window(sents, info["duration"], s.get("start"), s.get("dur"),
                                         float(self.cfg.get("max_speech", 12.0)))
                    pieces = [(a, b)]
                    wl = [w for w in (words or []) if a <= (w["t"] + w["te"]) / 2 <= b]
                    # 气口 / filler / repeat cleanup: the shared vstudio.cleanup (gentle by default, auto
                    # edits only unless the creator approves more; legacy "tighten" = standard)
                    co = SPC.options(self.cfg, s, default=True)
                    if co["enabled"] and wl:
                        pieces, clog = SPC.clean_window(src, words, a, b, co, os.path.join(self.cache, "cleanup"),
                                                        self.warn)
                        log["cleanup"] = clog
                        print(f"[fun] cleanup {log['clip']} ({co['profile']}): {clog['source_s']:.2f}s -> "
                              f"{clog['kept_s']:.2f}s, {len(clog['applied'])} edits cut, "
                              f"{len(clog['confirm_pending'])} to confirm -> {clog['review']}", flush=True)
                    elif co["enabled"] and (s.get("tighten") or s.get("cleanup") or self.cfg.get("tighten")):
                        self.warn.append(f"{os.path.basename(src)}: cleanup needs words (transcript); skipped")
                    # room the shot may grow into when it is stretched to the beat grid: up to the next /
                    # from the previous sentence (never into other speech; a cleanup makes shots shorter)
                    nxt = [x["a"] for x in sents if x["a"] >= b - 1e-6]
                    prv = [x["b"] for x in sents if x["b"] <= a + 1e-6]
                    room = (max(prv) + 0.12 if prv else 0.0,
                            min(min(nxt) - 0.12, info["duration"]) if nxt else info["duration"])
                    s.update(speech=True, pieces=pieces, words=wl, speech_from=how, room=room,
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
        if len(pool) < 3 and self.cfg.get("pool_photos", True):
            # too few silent clips for an auto hook / finale: photos (Ken Burns, full frame) fill in
            for s in shots:
                if len(pool) >= 5:
                    break
                if s["kind"] == "photo" and s["src"] not in seen:
                    seen.add(s["src"])
                    pool.append((0.0, s["src"], s))
        return pool

    PHOTO_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff")

    def explicit(self, key):
        """``hook`` / ``finale`` as an explicit list in edit.json -> [shot dict]; None when not a list.
        Items: a clip id / file name, a photo file name (by extension), ``{clip, start, dur, speed}`` or
        ``{photo, style}``."""
        v = self.cfg.get(key)
        if not isinstance(v, list):
            return None
        out = []
        for it in v:
            it = dict(photo=it) if isinstance(it, str) and it.lower().endswith(self.PHOTO_EXT) else \
                (dict(clip=it) if isinstance(it, str) else dict(it))
            out.append(self._source_item(it))
        return out

    def _source_item(self, it):
        if it.get("photo"):
            return dict(it, kind="photo", src=self.resolve(it["photo"], photo=True), style=it.get("style", "full"))
        src = self.resolve(it["clip"])
        return dict(it, kind="video", src=src, info=dict(fps=media.probe(src)["fps"]))

    def pool_item(self, src, nb, avoid, speed=1.0):
        """An auto-picked window of ``src`` (video highlight, or a full-frame Ken Burns photo)."""
        if os.path.splitext(src)[1].lower() in self.PHOTO_EXT:
            return dict(kind="photo", src=src, style="full", auto=True)
        return self.highlight(src, nb, avoid, speed=speed)

    def given_item(self, it, nb, avoid, speed=None):
        """An explicit hook / finale / outro item placed for ``nb`` beats (window auto-picked if no start)."""
        if it["kind"] == "photo":
            return dict(it)
        sp = float(it.get("speed", speed if speed is not None else 1.0))
        if it.get("start") is None:
            h = self.highlight(it["src"], nb, avoid, speed=sp)
            return dict(it, **{k: h[k] for k in ("start", "auto", "score")}, speed=sp)
        return dict(it, speed=sp)

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
        # hook: best windows (or the explicit ``hook`` list), accelerate into the bar line 8 units in
        given = self.explicit("hook")
        if given is not None:
            hook_n = min(len(given), 6)
        else:
            hook_n = min(5, len(pool)) if self.cfg.get("hook", True) else 0
        if hook_n >= (1 if given else 3):
            end_n = 8 * u
            lad = tuple(x * u for x in (2, 2, 1, 1, 1))[:hook_n - 1]
            cuts = self.bv.cut_plan(hook_n, self.bt(0) + 1e-3, self.bt(end_n) + 1e-6, "accelerate", ladder=lad)
            ns = [0] + [int(round(float(self.bv.beat_n(c)) - self.n0)) for c in cuts]
            ns = [x for k, x in enumerate(ns) if k == 0 or x > ns[k - 1]]
            for k in range(len(ns) - 1):
                nb = ns[k + 1] - ns[k]
                h = self.given_item(given[k], nb, avoid) if given else self.pool_item(pool[k % len(pool)][1], nb, avoid)
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
        # finale on a bar line (best windows again, or the explicit ``finale`` list)
        given = self.explicit("finale")
        if given is not None:
            fin_n = min(len(given), 6)
        else:
            fin_n = min(5, len(pool)) if self.cfg.get("finale", True) else 0
        if fin_n >= (1 if given else 3):
            if not self.is_bar(n):
                ext = self.next_bar(n) - n
                tl[-1]["nb"] += ext
                n += ext
            meta["finale_n"] = n
            end_n = n + 8 * u
            lad = tuple(x * u for x in (2, 2, 1, 1, 1))[:fin_n - 1]
            cuts = self.bv.cut_plan(fin_n, self.bt(n) + 1e-3, self.bt(end_n) + 1e-6, "accelerate", ladder=lad)
            ns = [n] + [int(round(float(self.bv.beat_n(c)) - self.n0)) for c in cuts]
            ns = [x for k, x in enumerate(ns) if k == 0 or x > ns[k - 1]]
            for k in range(len(ns) - 1):
                nb = ns[k + 1] - ns[k]
                h = self.given_item(given[k], nb, avoid) if given else self.pool_item(pool[k % len(pool)][1], nb, avoid)
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
            if o:                                          # {clip, start, speed} or {photo, style}
                nb = int(o.get("beats", nb))
                h = self.given_item(self._source_item(o), nb, avoid, speed=0.8)
            elif pool:
                # calmest good window: lowest motion among the top half by score
                src = pool[0][1]
                h = self.pool_item(src, nb, avoid, speed=0.8)
            else:
                h = None
            if h:
                h.update(role="outro", n0=n, nb=nb, section="outro")
                if h["kind"] == "video":
                    h["speed"] = h.get("speed", 0.8)
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
                extra = max(0.0, live - L)
                lo, hi = s.get("room", (0.0, None))
                a, b = s["pieces"][-1]
                tail = extra if hi is None else min(extra, max(0.0, hi - b))
                s["pieces"][-1] = (a, b + tail)                     # room tone + picture to the beat
                a, b = s["pieces"][0]
                head = min(extra - tail, max(0.0, a - lo))          # then a lead-in, never into other speech
                s["pieces"][0] = (a - head, b)
                # anything left: the picture runs on past the last piece (frames.piece_times), voice silent
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
                    # A5: hard cut by default - the photo's shutter SFX carries it. Only the first photo
                    # gets a flash (subject to the A4 hit budget); later video -> photo entries may get a
                    # light leak, capped below (``max_leaks``, spacing) so a photo run is not a leak run.
                    photo_seen += 1
                    if photo_seen == 1:
                        kind, reason = "flash", "photo"
                    elif a["kind"] != "photo":
                        kind, reason = "leak", "photo"
                    else:
                        kind, reason = "cut", "photo"
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
        self._cap_leaks(cuts)
        return cuts

    def _cap_leaks(self, cuts):
        """A5 variety: light leaks (auto ones - photos, demoted hits) at most ``max_leaks`` (4) per video and
        >= ``leak_gap`` (16) beats apart; the outro leak and requested transitions always stay. Extra
        leaks become hard cuts."""
        cap, gap = int(self.cfg.get("max_leaks", 4)), int(self.cfg.get("leak_gap", 16))
        keep = [c for c in cuts if c["kind"] == "leak" and c["reason"] in ("outro", "requested")]
        for c in cuts:
            if c["kind"] != "leak" or c in keep:
                continue
            if len(keep) < cap and all(abs(c["n"] - k["n"]) >= gap for k in keep):
                keep.append(c)
            else:
                c["note"] = (c.get("note", "") + "; " if c.get("note") else "") + "leak -> cut (A5 leak cap/spacing)"
                c["kind"] = "cut"
