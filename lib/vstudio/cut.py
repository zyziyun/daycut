"""Cutting: time maps, word-level tightening, automatic disfluency removal, frame-exact cuts and
crossfaded assembly.

    from vstudio import cut, asr
    tr   = asr.transcribe("talk.mp4")
    segs = cut.tighten(tr["words"], keep=[(3.2, 95.0)], drop=[(10.1, 10.6)])   # pause squeeze
    tm   = cut.cut_segments("talk.mp4", segs, "body.mp4")                       # frame-exact, 48k stereo
    tm.to_final(42.0)                                                           # source s -> body s

    # stumbles / 气口 on conversational speech (call-clips algorithm, intact)
    a    = cut.Audio.from_media("talk.mp4")
    cuts = cut.find_cuts(a, tr["segments"], lo, hi)
    keep = cut.split_window(lo, hi, cuts)

    # hook montage + body with dissolves, muted pads so xfades never swallow a syllable
    asm = cut.xfade_assemble([(12.0, 15.5), (40.2, 44.0), (0.0, 90.0)], xfade=0.3, speeds=[1.3, 1.3, 1.1])
    cut.render_assembly(asm, ["talk.mp4"], "base.mp4")

Everything is authored in SOURCE seconds; ``TimeMap`` is the one place that converts to final time.
Unified from promo-recut ``tight_cut.tighten/suggest/hidden_onset/rawmap/remap`` + ``common.raw2cut``,
talkinghead ``cut_pass1`` (RMS snap) + ``bodycut.cut_body/remap`` + ``compose`` (muted-pad xfade math, MAP/b2f/f2b),
call-clips ``find_disfluencies`` (promoted intact) + ``build_clips.offsets_of/dissolve/src_to_final``,
longform ``_lfc.map_src`` (cards = holds), vlog ``build_vlog`` (xfade chain).
"""
import bisect
import json
import os
import re
import shutil
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from . import media
from .audio import SR, decode_audio, rms_envelope, write_wav


# =================================================================== TimeMap
class TimeMap:
    """Source -> final time through an ordered list of timeline items.

    Items (dicts): kind "clip" (src0..src1 of input ``source`` played at ``speed``) or "hold"
    (a card, freeze, still or inserted footage with no mapping back to the source), each starting
    ``xfade`` s before the previous item ends (a dissolve overlaps them). Optional ``tag`` (e.g.
    "hook" / "body") lets callers map only through the body when hooks repeat source material.

    Methods: add_segment, add_hold, to_final(t, snap=None, tag=None, source=0),
    to_source(t) -> source seconds (or None inside a hold), map_span(a, b), segments, duration,
    to_list()/from_list() for JSON.
    From talkinghead ``compose`` MAP/b2f/f2b + ``bodycut.remap``, call-clips ``src_to_final``,
    longform ``_lfc.map_src``, promo ``common.raw2cut``/``tight_cut.rawmap``.
    """

    def __init__(self, items=None):
        self.items = []
        for it in items or []:
            it = dict(it)
            self.items.append(it)

    # -------- building
    def _end(self):
        if not self.items:
            return 0.0
        it = self.items[-1]
        return it["dst0"] + it["dur"]

    def add_segment(self, src0, src1, speed=1.0, source=0, xfade=0.0, tag=None, dur=None,
                    mute_head=0.0, mute_tail=0.0):
        """Append source span [src0, src1] at ``speed``; it starts ``xfade`` before the current end.
        dur overrides (src1-src0)/speed (e.g. frame-quantised). mute_*: muted pad lengths (source s).
        Returns the item dict."""
        if src1 < src0:
            raise ValueError("src1 < src0")
        d = (src1 - src0) / speed if dur is None else dur
        it = dict(kind="clip", src0=float(src0), src1=float(src1), speed=float(speed), source=source,
                  dst0=max(0.0, self._end() - xfade) if self.items else 0.0, dur=float(d), xfade=float(xfade if self.items else 0.0),
                  tag=tag, mute_head=float(mute_head), mute_tail=float(mute_tail))
        self.items.append(it)
        return it

    def add_hold(self, dur, label=None, xfade=0.0, tag=None):
        """Append ``dur`` s with no source mapping (chapter card, freeze frame, inserted reel)."""
        it = dict(kind="hold", dur=float(dur), label=label, dst0=max(0.0, self._end() - xfade) if self.items else 0.0,
                  xfade=float(xfade if self.items else 0.0), tag=tag)
        self.items.append(it)
        return it

    add_insert = add_hold

    @classmethod
    def from_segments(cls, segments, speeds=1.0, source=0, xfade=0.0, tag=None):
        """TimeMap of kept [(start, end), ...] played back to back (speeds: float or list)."""
        tm = cls()
        for i, (a, b) in enumerate(segments):
            sp = speeds[i] if isinstance(speeds, (list, tuple)) else speeds
            tm.add_segment(a, b, sp, source=source, xfade=xfade if i else 0.0, tag=tag)
        return tm

    # -------- queries
    @property
    def duration(self):
        return max((it["dst0"] + it["dur"] for it in self.items), default=0.0)

    @property
    def segments(self):
        """The clip items (dicts with src0, src1, speed, dst0, dur, ...)."""
        return [it for it in self.items if it["kind"] == "clip"]

    def _clips(self, tag=None, source=0):
        return [it for it in self.items if it["kind"] == "clip" and (tag is None or it.get("tag") == tag)
                and (source is None or it.get("source", 0) == source)]

    def to_final(self, t, snap=None, tag=None, source=0):
        """Source second -> final second. snap for times that were cut out: None -> None,
        "fwd" -> start of the next kept span, "back" -> end of the previous one, "nearest".
        If several items contain t (a hook re-using body footage), the LAST one wins unless ``tag``
        filters (pass tag="body")."""
        clips = self._clips(tag, source)
        hit = None
        for it in clips:
            if it["src0"] - 1e-6 <= t <= it["src1"] + 1e-6:
                hit = it["dst0"] + (min(max(t, it["src0"]), it["src1"]) - it["src0"]) / it["speed"]
        if hit is not None or snap is None:
            return hit
        nxt = [it for it in clips if it["src0"] > t]
        prv = [it for it in clips if it["src1"] < t]
        f = min(nxt, key=lambda it: it["src0"])["dst0"] if nxt else None
        b = None
        if prv:
            it = max(prv, key=lambda it: it["src1"])
            b = it["dst0"] + (it["src1"] - it["src0"]) / it["speed"]
        if snap == "fwd":
            return f
        if snap == "back":
            return b
        if snap == "nearest":
            cands = [(abs(min(nxt, key=lambda it: it["src0"])["src0"] - t), f)] if nxt else []
            if prv:
                cands.append((abs(t - max(prv, key=lambda it: it["src1"])["src1"]), b))
            return min(cands)[1] if cands else None
        raise ValueError(f"snap={snap!r}")

    def owner(self, t):
        """Item shown at final second t (inside a dissolve, the later item from its midpoint on)."""
        cur = None
        for it in self.items:
            if it["dst0"] + it.get("xfade", 0.0) / 2 <= t + 1e-9:
                cur = it
        return cur

    def to_source(self, t, with_item=False):
        """Final second -> source second (None inside a hold). with_item -> (src_t, item)."""
        it = self.owner(t)
        if it is None or it["kind"] != "clip":
            return (None, it) if with_item else None
        s = it["src0"] + (t - it["dst0"]) * it["speed"]
        s = min(max(s, it["src0"]), it["src1"])
        return (s, it) if with_item else s

    def map_span(self, a, b, tag=None, min_dur=0.0):
        """Source span -> (final_a, final_b), snapping its ends inward past cuts; None if nothing
        of it survives (or it is shorter than min_dur)."""
        fa, fb = self.to_final(a, "fwd", tag), self.to_final(b, "back", tag)
        if fa is None or fb is None or fb - fa < max(min_dur, 1e-6):
            return None
        return fa, fb

    def to_list(self):
        return [dict(it) for it in self.items]

    @classmethod
    def from_list(cls, items):
        return cls(items)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_list(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def __repr__(self):
        return f"TimeMap({len(self.items)} items, {self.duration:.2f}s)"


# =================================================================== word helpers
_PUNCT = re.compile(r"[\s，。,.!?！？、：:；;“”\"'…\-]+")


def _norm(s):
    return _PUNCT.sub("", s).lower()


def _w(w):
    """(text, start, end) from {"w","t","te"} or {"word","start","end"} or a tuple."""
    if isinstance(w, dict):
        if "t" in w:
            return w["w"], float(w["t"]), float(w["te"])
        return w["word"], float(w["start"]), float(w["end"])
    return w[0], float(w[1]), float(w[2])


def _load_env(audio, hop=0.01, win=0.03, db=True):
    """Envelope from a path (any media), (x, sr) tuple or a precomputed (env, hop) dict."""
    if audio is None:
        return None, hop
    if isinstance(audio, dict):
        return audio["env"], audio["hop"]
    if isinstance(audio, (str, os.PathLike)):
        x = decode_audio(str(audio), sr=16000, channels=1)[:, 0]
        return rms_envelope(x, 16000, hop, win, db=db)
    x, sr = audio
    return rms_envelope(x, sr, hop, win, db=db)


# =================================================================== tighten
def tighten(words, keep, drop=(), patch=(), pause_threshold=None, squeeze=None, pad_in=0.06, pad_out=0.08,
            audio=None, threshold_db=-45.0):
    """Turn kept spans + word timestamps into tight cut segments (pause squeeze).

    Args:
      words: [{"w","t","te"}] or whisper words [{"word","start","end"}] (source seconds).
      keep: [(a, b)] source spans to keep (sentences / sections chosen by the creator).
      drop: [(a, b)] spans to remove (fillers, repeats); a word is dropped if it STARTS inside.
        Each drop also forces a join (no pad) at that point.
      patch: [(old_start, new_start)] hand-measured word-start fixes (whisper merged a filler into
        the next word; the RMS valley from ``suggest_fillers`` tells you the new start).
      pause_threshold: gaps longer than this get squeezed (persona audio.pause_threshold, 0.35).
      squeeze: silence kept at a squeezed pause, half on each side (persona audio.pause_squeeze,
        0.06). With ``audio`` it is measured from the voiced-energy edges (talkinghead cut_pass1:
        RMS > threshold_db, 10 ms frames) so soft onsets survive; without audio it is measured from
        whisper's word edges but never less than pad_in (before a word) / pad_out (after one).
      audio: media path or (x, sr) for RMS snapping (optional).
    Returns sorted, merged [(start, end)] with starts clamped >= 0.
    From promo-recut ``tight_cut.tighten`` + talkinghead ``cut_pass1`` RMS snap.
    """
    try:
        from .config import persona
        pa = persona().get("audio", {}) or {}
    except Exception:
        pa = {}
    thr = float(pa.get("pause_threshold", 0.35) if pause_threshold is None else pause_threshold)
    sq = float(pa.get("pause_squeeze", 0.06) if squeeze is None else squeeze)
    env, hop = _load_env(audio)

    ws = []
    for w in words:
        txt, s, e = _w(w)
        for a, b in patch or ():
            if abs(s - a) < 0.015:
                s = b
        ws.append(dict(w=txt, s=s, e=max(e, s)))
    ws.sort(key=lambda w: w["s"])
    drops = list(drop or ())
    dropped = lambda w: any(a - 0.01 <= w["s"] < b - 0.01 for a, b in drops)

    def voiced_end(t, lo, hi):
        if env is None:
            return None
        i0, i1 = max(0, int(lo / hop)), min(len(env), int(hi / hop) + 1)
        idx = np.nonzero(env[i0:i1] > threshold_db)[0]
        return None if not len(idx) else (i0 + idx[-1] + 1) * hop

    def voiced_start(t, lo, hi):
        if env is None:
            return None
        i0, i1 = max(0, int(lo / hop)), min(len(env), int(hi / hop) + 1)
        idx = np.nonzero(env[i0:i1] > threshold_db)[0]
        return None if not len(idx) else (i0 + idx[0]) * hop

    def end_edge(last_w, nxt_s):
        e = last_w["e"]
        ve = voiced_end(e, e - 0.15, min(e + 0.30, nxt_s - 0.02) if nxt_s else e + 0.30)
        if ve is not None:
            return max(e - 0.05, ve) + sq / 2
        return e + max(pad_out, sq / 2)

    def start_edge(w, prev_e):
        s = w["s"]
        vs = voiced_start(s, max(s - 0.30, (prev_e or 0) + 0.02), s + 0.10)
        if vs is not None:
            return min(s + 0.05, vs) - sq / 2
        return s - max(pad_in, sq / 2)

    out = []
    for a, b in keep:
        span = [w for w in ws if a - 0.05 <= w["s"] < b and not dropped(w)]
        if not span:
            continue
        brk = lambda p, w: (w["s"] - p["e"] > thr
                            or any(p["e"] - 0.02 <= x[0] < w["s"] + 0.02 for x in drops))
        cur = [max(a, start_edge(span[0], None)), None]
        pw = span[0]
        for w in span[1:]:
            if brk(pw, w):
                long_gap = w["s"] - pw["e"] > thr
                if long_gap:
                    cur[1] = end_edge(pw, w["s"])
                    out.append(cur)
                    cur = [start_edge(w, pw["e"]), None]
                else:                                   # a drop: hard join right at the words
                    cur[1] = pw["e"] + 0.01
                    out.append(cur)
                    cur = [w["s"], None]
            pw = w
        cur[1] = min(b + 0.05, max(pw["e"] + 0.1, end_edge(pw, None) if env is not None else 0))
        out.append(cur)
    out = sorted([max(0.0, s), e] for s, e in out if e > max(0.0, s))   # clamp negative starts
    merged = []
    for s, e in out:
        if merged and s <= merged[-1][1] + 1e-3:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in merged]


# =================================================================== filler suggestions
FILLERS_ZH = ["嗯", "啊", "呃", "额", "哎", "诶", "哦", "然后呢", "然后", "就是", "就是说", "那个", "怎么说呢",
              "怎么说", "对吧"]
FILLERS_EN = ["um", "uh", "erm", "uhm", "hmm", "like", "you know", "i mean", "sort of", "kind of"]


def hidden_onset(env, hop, t0, t1, valley=0.35, min_gap=0.05):
    """Energy valley inside a word (< valley*peak for >= min_gap s) followed by a rise: usually a
    filler or restart merged into the word. env must be LINEAR rms. Returns (dip_start, dip_end,
    new_start) or None. From promo-recut ``tight_cut.hidden_onset``."""
    i0, i1 = int(t0 / hop), int(t1 / hop)
    seg = env[i0:i1]
    if len(seg) < 8:
        return None
    peak = seg.max()
    low = seg < valley * peak
    best, i = None, 0
    while i < len(seg):
        if low[i]:
            j = i
            while j < len(seg) and low[j]:
                j += 1
            if (j - i) * hop >= min_gap and i > 2 and j < len(seg) - 3:
                after = seg[j:] > 0.5 * peak
                rise = j + int(np.argmax(after)) if after.any() else j
                best = (i0 + i) * hop, (i0 + j) * hop, (i0 + rise) * hop - 0.03
            i = j
        else:
            i += 1
    return best


def suggest_fillers(words, audio=None, fillers=None, drops=(), per_char=0.22):
    """Candidate DROP / PATCH edits for the creator to review (never applied automatically).

    Finds: fillers (also split over 2-3 tokens, or glued to the next word), immediate repeats
    (A A, A B A B: drop the first copy), and over-long words whose RMS envelope has a valley then a
    rise (a merged filler/restart; needs ``audio``) -> suggested PATCH start.
    Args: words (any word shape), audio (path or (x, sr)), fillers (default FILLERS_ZH + FILLERS_EN),
    drops already chosen (flagged), per_char seconds/char for "long word".
    Returns [{"kind", "start", "end", "text", "note", "patch": (old, new) | None, "dropped": bool}].
    From promo-recut ``tight_cut.suggest/hidden_onset``.
    """
    fl = [_norm(f) for f in (fillers or FILLERS_ZH + FILLERS_EN)]
    ws = [_w(w) for w in words]
    toks = [_norm(t) for t, _, _ in ws]
    in_drop = lambda t: any(a - 0.01 <= t < b - 0.01 for a, b in drops or ())
    out = []

    def add(kind, a, b, text, note="", patch=None):
        out.append(dict(kind=kind, start=round(a, 3), end=round(b, 3), text=text, note=note, patch=patch,
                        dropped=in_drop(a)))

    for i in range(len(ws)):
        hit = False
        for k in (1, 2, 3):
            if i + k > len(ws):
                break
            joined = "".join(toks[i:i + k])
            if joined and joined in fl and (k == 1 or all(toks[i:i + k])):
                add("filler", ws[i][1], ws[i + k - 1][2], joined)
                hit = True
                break
        if not hit:
            for f in fl:
                if len(f) >= 2 and toks[i].startswith(f) and toks[i] != f and not re.match(r"[a-z]", f):
                    add("filler-glued", ws[i][1], ws[i][2], toks[i],
                        f"starts with '{f}': drop it + PATCH the word start")
                    break
    for i in range(len(ws) - 1):
        if toks[i] and toks[i] == toks[i + 1] and toks[i] not in fl:
            add("repeat", ws[i][1], ws[i + 1][1], toks[i] * 2)
        if i + 3 < len(ws) and toks[i] and toks[i + 1] and toks[i] + toks[i + 1] == toks[i + 2] + toks[i + 3]:
            add("repeat2", ws[i][1], ws[i + 2][1], toks[i] + toks[i + 1])
    if audio is not None:
        env, hop = _load_env(audio, db=False)
        for txt, s, e in ws:
            d, n = e - s, max(1, len(_norm(txt)))
            if d > max(0.45, per_char * n + 0.15):
                h = hidden_onset(env, hop, s, e)
                if h:
                    add("long-word", s, e, txt.strip(), f"{d:.2f}s, dip {h[0]:.2f}-{h[1]:.2f}: PATCH start -> "
                        f"{h[2]:.2f}, maybe DROP [{s:.2f}, {h[2]:.2f}]", patch=(round(s, 3), round(h[2], 3)))
                else:
                    add("long-word", s, e, txt.strip(), f"{d:.2f}s, no clear dip - listen")
    out.sort(key=lambda r: r["start"])
    return out


# =================================================================== find_disfluencies (call-clips, intact)
# Automatic 气口 / stumble remover for conversational speech (Chinese-first, works on code-switched
# zh/en). Whisper's word timestamps abut each other, so they cannot show pauses: silence comes
# from 20 ms RMS frames (threshold = floor + 0.30 * (speech - floor), floor = 8th percentile dB,
# speech = 70th); the transcript only says WHAT to cut (restart, repeated phrase, lone 嗯). Every
# cut edge moves to the quietest frame between the neighbouring words' midpoints, so a join never
# lands mid-syllable and never eats a kept word (subtitles keep a word by its midpoint).
#   pause    silence > PAUSE_MIN with no word midpoint inside -> cut, keep PAUSE_EDGE each side
#   restart  segment A then B starting with A's text within 1.5 s -> drop A
#   repeat   the same 1..6-word unit (2..10 chars) said twice back to back -> keep the last copy;
#            one-word repeats across a segment break are kept; EMPHASIS doublings whitelisted
#   filler   a whole segment that is only a FILLERS word
#   edit     optional editor cuts ``extra``: [[from_onset, next_kept_onset, why], ...]
# Cuts < MIN_CUT are ignored; overlapping cuts merge. Expect ~3% of body time from the auto
# rules, ~10% with an editor pass. FILLERS/EMPHASIS are Mandarin lists: replace them for another
# language (the energy/pause and restart/repeat logic is language-agnostic). Constants were tuned
# on multi-person call audio; persona pause_* keys are NOT read here.
PAUSE_MIN = 0.60
PAUSE_EDGE = 0.18
MIN_CUT = 0.25
SNAP = 0.12
FRAME = 0.02

FILLERS = {"嗯", "啊", "呃", "额", "哎", "诶", "哦", "然后呢", "然后", "就是", "就是说", "那个",
           "怎么说呢", "怎么说", "对吧"}
EMPHASIS = {"一半", "合作", "非常", "特别", "真的", "一点", "好好", "越来", "谢谢", "慢慢", "常常", "天天", "最最"}

_DPUNCT = re.compile(r"[\s,，。.!?！？、…]+")


def norm(s):
    return _DPUNCT.sub("", s)


def load_energy(wav_path):
    """20 ms RMS in dB of a 16-bit PCM wav (mono expected; stereo is interleaved-averaged)."""
    w = wave.open(wav_path)
    sr, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    hop = int(sr * FRAME)
    n = len(x) // hop
    fr = x[:n * hop].reshape(n, hop)
    return 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-6)


class Audio:
    """Energy view of a recording for ``find_cuts``. Audio("audio16k.wav") (16-bit PCM wav) or
    Audio.from_media("talk.mp4"). From call-clips ``find_disfluencies.Audio`` (unchanged)."""

    def __init__(self, wav_path):
        self.db = load_energy(wav_path)
        floor, speech = np.percentile(self.db, 8), np.percentile(self.db, 70)
        self.thr = floor + 0.30 * (speech - floor)

    @classmethod
    def from_media(cls, path):
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "a16.wav")
            media.extract_wav(path, wav, sr=16000, channels=1)
            return cls(wav)

    def idx(self, t):
        return int(round(t / FRAME))

    def boundary(self, t, words, reach=0.30):
        """Cut point near a word boundary: between the two words around t, only between their
        midpoints (late in the word before, early in the word after), on 60 ms smoothed energy."""
        if not words:
            return self.snap(t)
        starts = [w["s"] for w in words]
        k = bisect.bisect_left(starts, t)
        cands = [j for j in (k - 1, k, k + 1) if 0 < j < len(words)]
        if not cands:
            return self.snap(t)
        j = min(cands, key=lambda j: abs(words[j]["s"] - t))
        if abs(words[j]["s"] - t) > reach:
            return self.snap(t)
        prev, nxt = words[j - 1], words[j]
        lo = prev["s"] + 0.60 * (prev["e"] - prev["s"])
        hi = nxt["s"] + 0.35 * (nxt["e"] - nxt["s"])
        a, b = self.idx(lo), self.idx(hi)
        if b <= a:
            return words[j]["s"]
        sm = np.convolve(self.db, np.ones(3) / 3, mode="same")
        return (a + int(np.argmin(sm[a:b + 1]))) * FRAME

    def snap_back(self, t, reach=0.15):
        """Quietest frame at or just BEFORE t (for editor cuts, where t is a word onset)."""
        a, b = max(0, self.idx(t - reach)), self.idx(t)
        if b <= a:
            return t
        return (a + int(np.argmin(self.db[a:b + 1]))) * FRAME

    def snap(self, t):
        """Move t to the quietest frame within +-SNAP."""
        a, b = max(0, self.idx(t - SNAP)), min(len(self.db) - 1, self.idx(t + SNAP))
        if b <= a:
            return t
        return (a + int(np.argmin(self.db[a:b + 1]))) * FRAME

    def silences(self, lo, hi):
        a, b = self.idx(lo), self.idx(hi)
        quiet = self.db[a:b] < self.thr
        out, k = [], 0
        while k < len(quiet):
            if quiet[k]:
                j = k
                while j < len(quiet) and quiet[j]:
                    j += 1
                out.append(((a + k) * FRAME, (a + j) * FRAME))
                k = j
            else:
                k += 1
        return out


_AW = {}


def all_words(segs):
    """Every word in the recording, sorted, cached per transcript object."""
    key = id(segs)
    hit = _AW.get(key)
    if hit is None or hit[0] is not segs:
        ws = [{"t": norm(w["word"]), "s": w["start"], "e": w["end"]}
              for s in segs for w in s.get("words", []) if norm(w["word"])]
        ws.sort(key=lambda w: w["s"])
        hit = _AW[key] = (segs, ws)
    return hit[1]


def words_in(segs, lo, hi):
    out = []
    for si, s in enumerate(segs):
        if s["end"] <= lo or s["start"] >= hi:
            continue
        for w in s.get("words", []):
            m = (w["start"] + w["end"]) / 2
            if lo <= m <= hi and norm(w["word"]):
                out.append({"t": norm(w["word"]), "s": w["start"], "e": w["end"], "seg": si})
    return out


def find_cuts(audio, segs, lo, hi, extra=None):
    """Cut intervals [[a, b, why], ...] (source s) inside window [lo, hi].

    audio: ``Audio``; segs: whisper segments with words (word_timestamps=True); extra: editor cuts.
    From call-clips ``find_disfluencies.find_cuts`` (algorithm unchanged).
    """
    cuts = []
    AWp = all_words(segs)
    for a, b in audio.silences(lo, hi):
        if b - a < PAUSE_MIN:
            continue
        if any(a < (w["s"] + w["e"]) / 2 < b for w in AWp if w["e"] > a - 1 and w["s"] < b + 1):
            continue
        ca, cb = a + PAUSE_EDGE, b - PAUSE_EDGE
        if cb - ca >= 0.2:
            cuts.append((ca, cb, "pause"))

    inside = [s for s in segs if s["start"] >= lo - 0.05 and s["end"] <= hi + 0.05]
    for s in inside:
        if norm(s["text"]) in FILLERS:
            cuts.append((s["start"], s["end"], f"filler:{norm(s['text'])}"))
    for A, B in zip(inside, inside[1:]):
        ta, tb = norm(A["text"]), norm(B["text"])
        if len(ta) >= 2 and tb.startswith(ta) and B["start"] - A["end"] < 1.5:
            cuts.append((A["start"], B["start"], f"restart:{ta}"))

    W = words_in(segs, lo, hi)
    i = 0
    while i < len(W):
        hit = None
        for n in range(1, 7):
            if i + 2 * n > len(W):
                break
            u1 = "".join(w["t"] for w in W[i:i + n])
            u2 = "".join(w["t"] for w in W[i + n:i + 2 * n])
            if u1 == u2 and 2 <= len(u1) <= 10 and u1 not in EMPHASIS \
                    and W[i + n]["s"] - W[i + n - 1]["e"] < 1.2:
                cross = W[i]["seg"] != W[i + n]["seg"]
                if n == 1 and cross:
                    continue
                hit = n
        if hit:
            n = hit
            k = i + n
            while k + n <= len(W) and "".join(w["t"] for w in W[k:k + n]) == \
                    "".join(w["t"] for w in W[i:i + n]):
                k += n
            last = k - n
            cuts.append((W[i]["s"], W[last]["s"], "repeat:" + "".join(w["t"] for w in W[i:i + n])))
            i = k
        else:
            i += 1

    snapped = []
    AW = all_words(segs)
    kept_onsets = [b for a, b, why in cuts if why.startswith(("repeat", "restart"))]
    for a, b, why in (extra or []):
        if any(abs(a - k) < 0.05 for k in kept_onsets):
            continue
        if lo <= a < b <= hi:
            a, b = audio.boundary(a, AW), audio.boundary(b, AW)
            a, b = max(a, lo + 0.05), min(b, hi - 0.05)
            if b - a >= 0.12:
                snapped.append([a, b, "edit:" + why[:40]])
    for a, b, why in cuts:
        if why != "pause":
            a, b = audio.boundary(a, AW), audio.boundary(b, AW)
        a, b = max(a, lo + 0.05), min(b, hi - 0.05)
        if b - a >= MIN_CUT:
            snapped.append([a, b, why])
    snapped.sort()
    merged = []
    for c in snapped:
        if merged and c[0] <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], c[1])
            merged[-1][2] += "+" + c[2]
        else:
            merged.append(c)
    return merged


def split_window(lo, hi, cuts, min_piece=0.4):
    """Keep-intervals [[a, b], ...] of [lo, hi] after removing ``cuts``; slivers < min_piece between
    two cuts fall into the cut. From call-clips ``find_disfluencies.split_window``."""
    out, cur = [], lo
    for a, b, _ in cuts:
        if a - cur >= min_piece:
            out.append([round(cur, 3), round(a, 3)])
        cur = b
    if hi - cur >= min_piece:
        out.append([round(cur, 3), round(hi, 3)])
    return out


# =================================================================== frame-exact cut
def _fps_q(fps, src):
    if fps:
        return Fraction(fps).limit_denominator(1001)
    q = media.probe(src)["fps_q"]
    return q if q else Fraction(30)


def cut_segments(src, segments, out, fps=None, crf=14, preset="fast", fade=0.012, vf=None, workers=4,
                 tmpdir=None):
    """Keep ``segments`` [(start, end)] of ``src`` -> ``out``, frame-exact, audio 48 kHz stereo.

    Video: each segment snapped to the frame grid (round(t*fps)), encoded separately (accurate
    pre-seek + fps + trim by frame), then joined by stream copy. Audio: decoded per segment at
    48 kHz stereo (silence if the source has none), sliced sample-exact to the same frame grid,
    ``fade`` s fades at every edge (no clicks), spliced in numpy - so A/V can never drift.
    vf: optional filter chain (grade, scale) applied to every segment. Output audio is AAC 192k for
    .mp4/.m4v, PCM for .mov/.mkv. Returns the TimeMap (source -> out).
    From talkinghead ``bodycut.cut_body`` / ``cut_pass1`` (frame trim + numpy splice), promo ``cut_file``.
    """
    F = _fps_q(fps, src)
    info = media.probe(src)
    total = info["duration"] or 1e9
    snapped = []
    for s, e in segments:
        s, e = max(0.0, float(s)), min(float(e), total)
        a, b = int(round(s * F)), int(round(e * F))
        if b > a:
            snapped.append((a, b))
    if not snapped:
        raise ValueError("no non-empty segments")
    own = tmpdir is None
    tmp = tmpdir or tempfile.mkdtemp(prefix="vstudio_cut_")
    os.makedirs(tmp, exist_ok=True)
    ts = int(F.numerator * 1000 // F.denominator) if F.denominator == 1 else F.numerator

    def job(k_ab):
        k, (a, b) = k_ab
        pre_f = max(0, a - int(2 * F))
        pre = float(Fraction(pre_f) / F)
        chain = f"fps={F.numerator}/{F.denominator},trim=start_frame={a - pre_f}:end_frame={b - pre_f}," \
                f"setpts=PTS-STARTPTS" + (f",{vf}" if vf else "") + ",setsar=1,format=yuv420p"
        p = os.path.join(tmp, f"{k:04d}.mp4")
        media.run(["ffmpeg", "-y", "-ss", f"{pre:.6f}", "-i", src, "-an", "-vf", chain, "-c:v", "libx264",
                   "-crf", str(crf), "-preset", preset, "-video_track_timescale", str(ts), p])
        return p

    try:
        with ThreadPoolExecutor(max(1, workers)) as ex:
            parts = list(ex.map(job, enumerate(snapped)))
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
        vtmp = os.path.join(tmp, "v.mp4")
        media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", vtmp])
        chunks, fd = [], max(1, int(fade * SR))
        ramp = np.linspace(0, 1, fd, dtype=np.float32)[:, None]
        for a, b in snapped:
            n = int(round(b * SR / F)) - int(round(a * SR / F))
            if info["has_audio"]:
                x = decode_audio(src, start=float(Fraction(a) / F), dur=float(Fraction(b - a) / F))
            else:
                x = np.zeros((0, 2), np.float32)
            x = x[:n]
            if len(x) < n:
                x = np.concatenate([x, np.zeros((n - len(x), 2), np.float32)])
            if fade and n > 2 * fd:
                x[:fd] *= ramp
                x[-fd:] *= ramp[::-1]
            chunks.append(x)
        atmp = os.path.join(tmp, "a.wav")
        write_wav(atmp, np.concatenate(chunks), SR)
        acodec = ["-c:a", "pcm_s16le"] if out.lower().endswith((".mov", ".mkv")) else \
            ["-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2"]
        media.run(["ffmpeg", "-y", "-i", vtmp, "-i", atmp, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                   *acodec, "-movflags", "+faststart", out])
    finally:
        if own:
            shutil.rmtree(tmp, ignore_errors=True)
    return TimeMap.from_segments([(float(Fraction(a) / F), float(Fraction(b) / F)) for a, b in snapped])


# =================================================================== crossfaded assembly
@dataclass
class Assembly:
    """Result of ``xfade_assemble``: ffmpeg filter graph + the timing it implies."""
    graph: str
    vout: str
    aout: str
    offsets: list
    durations: list
    xfades: list
    total: float
    timemap: TimeMap
    pieces: list = field(default_factory=list)
    inputs: list = field(default_factory=list)


def _piece(p):
    if isinstance(p, dict):
        return dict(input=p.get("input", 0), start=float(p["start"]), end=float(p["end"]), speed=p.get("speed"),
                    gain_db=p.get("gain_db", 0.0), tag=p.get("tag"))
    if len(p) == 2:
        return dict(input=0, start=float(p[0]), end=float(p[1]), speed=None, gain_db=0.0, tag=None)
    return dict(input=int(p[0]), start=float(p[1]), end=float(p[2]), speed=None, gain_db=0.0, tag=None)


def xfade_assemble(pieces, xfade=0.3, speeds=1.0, mute_pad=True, fps=30, size=None, vf=None,
                   src_durations=None, fade_edge=0.015):
    """Filter graph that plays ``pieces`` back to back, each at its own speed, dissolving between them.

    Args:
      pieces: [(start, end)] on input 0, [(input, start, end)], or dicts {input, start, end, speed,
        gain_db, tag} - source seconds.
      xfade: dissolve seconds (float, or one per join: len n-1; 0 = hard cut).
      speeds: float or one per piece (dict ``speed`` wins).
      mute_pad: True/"both" -> every join gets muted pads: the next piece starts xfade*speed source
        seconds EARLIER and the previous one ends that much LATER, both muted, so the dissolve runs
        over silence and never swallows a first or last syllable (talkinghead compose's pads, done on
        both sides). "head" -> only the incoming side (talkinghead's original). False -> plain
        acrossfade. Pads are clamped at 0 (negative starts) and at src_durations[input] if given.
      fps / size ("1080:1920") / vf: every piece is normalised to the same rate, size and yuv420p so
        xfade accepts it; vf is an extra chain (grade) per piece.
    Durations are quantised to whole frames and audio is padded/trimmed to the same sample count, so
    offset maths stays exact over hundreds of joins: offset[k] = offset[k-1] + dur[k-1] - xfade[k].
    Returns an ``Assembly`` (graph, "[vout]", "[aout]", offsets, durations, xfades, total, timemap).
    From call-clips ``build_clips.offsets_of/_dissolve``, talkinghead ``compose.build_base`` (muted pads),
    vlog ``build_vlog`` xfade chain. For 30+ pieces from separate files, render in chunks (call-clips
    ``dissolve``) - the offset maths is linear so chunked output is identical.
    """
    P = [_piece(p) for p in pieces]
    n = len(P)
    if not n:
        raise ValueError("no pieces")
    for i, p in enumerate(P):
        if p["speed"] is None:
            p["speed"] = float(speeds[i] if isinstance(speeds, (list, tuple)) else speeds)
    if isinstance(xfade, (list, tuple)):
        xf = [0.0] + [float(x) for x in (xfade[1:] if len(xfade) == n else xfade)]
    else:
        xf = [0.0] + [float(xfade)] * (n - 1)
    xf = [round(x * fps) / fps for x in xf]
    mode = "both" if mute_pad is True else (mute_pad or None)
    for k, p in enumerate(P):
        p["head"] = p["tail"] = 0.0
    for k in range(1, n):
        if not xf[k] or not mode:
            continue
        cur, prev = P[k], P[k - 1]
        want = xf[k] * cur["speed"]
        cur["head"] = min(want, cur["start"])                    # clamp: never before 0
        if mode == "both":
            lim = None
            if src_durations is not None:
                try:
                    lim = src_durations[prev["input"]]
                except (KeyError, IndexError):
                    lim = None
            want_t = xf[k] * prev["speed"]
            prev["tail"] = want_t if lim is None else max(0.0, min(want_t, lim - prev["end"]))
    graph, durs = [], []
    for i, p in enumerate(P):
        s0, s1 = p["start"] - p["head"], p["end"] + p["tail"]
        sp = p["speed"]
        N = max(1, int(round((s1 - s0) / sp * fps)))
        D = N / fps
        durs.append(D)
        p.update(s0=s0, s1=s1, frames=N, dur=D)
        vchain = [f"trim=start={s0:.4f}:end={s1 + 2.0 / fps:.4f}", f"setpts=(PTS-STARTPTS)/{sp:.6g}", f"fps={fps}"]
        if size:
            w, h = str(size).replace("x", ":").split(":")
            vchain.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
        if vf:
            vchain.append(vf)
        vchain += ["setsar=1", "format=yuv420p", "tpad=stop_mode=clone:stop_duration=1",
                   f"trim=end_frame={N}", "setpts=PTS-STARTPTS", "settb=AVTB"]
        graph.append(f"[{p['input']}:v]" + ",".join(vchain) + f"[v{i}]")
        achain = [f"atrim=start={s0:.4f}:end={s1:.4f}", "asetpts=PTS-STARTPTS", f"aresample={SR}",
                  "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if abs(sp - 1) > 1e-6:
            achain.append(media.atempo_chain(sp))
        if p["gain_db"]:
            achain.append(f"volume={p['gain_db']}dB")
        if p["head"] > 0 or (i > 0 and xf[i]):
            achain.append(f"afade=t=in:st={p['head'] / sp:.4f}:d={fade_edge}")
        if p["tail"] > 0 or (i < n - 1 and xf[i + 1]):
            achain.append(f"afade=t=out:st={max(0.0, D - p['tail'] / sp - fade_edge):.4f}:d={fade_edge}")
        achain += ["apad", f"atrim=end_sample={int(round(D * SR))}", "asetpts=PTS-STARTPTS"]
        graph.append(f"[{p['input']}:a]" + ",".join(achain) + f"[a{i}]")
    offs = [0.0]
    for k in range(1, n):
        offs.append(offs[-1] + durs[k - 1] - xf[k])
    vc, ac = "[v0]", "[a0]"
    for k in range(1, n):
        if xf[k] > 0:
            graph.append(f"{vc}[v{k}]xfade=transition=fade:duration={xf[k]:.4f}:offset={offs[k]:.4f}[vx{k}]")
            graph.append(f"{ac}[a{k}]acrossfade=d={xf[k]:.4f}:c1=tri:c2=tri[ax{k}]")
        else:
            graph.append(f"{vc}[v{k}]concat=n=2:v=1:a=0[vx{k}]")
            graph.append(f"{ac}[a{k}]concat=n=2:v=0:a=1[ax{k}]")
        vc, ac = f"[vx{k}]", f"[ax{k}]"
    graph.append(f"{vc}null[vout]")
    graph.append(f"{ac}anull[aout]")
    tm = TimeMap()
    for k, p in enumerate(P):
        tm.add_segment(p["s0"], p["s1"], p["speed"], source=p["input"], xfade=xf[k], tag=p["tag"], dur=p["dur"],
                       mute_head=p["head"], mute_tail=p["tail"])
    total = offs[-1] + durs[-1]
    return Assembly(graph=";".join(graph), vout="[vout]", aout="[aout]", offsets=offs, durations=durs, xfades=xf,
                    total=total, timemap=tm, pieces=P, inputs=sorted({p["input"] for p in P}))


def render_assembly(asm, inputs, out, args=None, post_audio=None):
    """Run ffmpeg for an ``Assembly``. inputs: paths indexed like the pieces' ``input``.
    args: encoder args (default ``media.delivery_args()``); post_audio: extra chain on [aout]
    (e.g. a loudnorm string). Returns out."""
    cmd = ["ffmpeg", "-y"]
    for p in inputs:
        cmd += ["-i", p]
    graph, aout = asm.graph, asm.aout
    if post_audio:
        graph += f";{aout}{post_audio}[apost]"
        aout = "[apost]"
    cmd += media.filter_complex_args(graph) + ["-map", asm.vout, "-map", aout]
    cmd += list(args) if args is not None else media.delivery_args()
    media.run(cmd + [out])
    return out
