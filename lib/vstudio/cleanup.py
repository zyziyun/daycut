"""Speech cleanup, one shared tool: 气口 (pauses / breaths), 口头禅 fillers, repeats, stammers,
false starts and re-takes -> a reviewable EDL, a word-safe frame-exact cut, and an ASR verify.

    from vstudio import cleanup
    edl = cleanup.analyze("talk.mp4", transcript="talk.asr.json", profile="standard")  # cleanup.json + cleanup_review.md
    res = cleanup.apply("cleanup.json", approve=[3, 5, 9], keep=[7])                  # talk.clean.<tag>.mp4
    rep = cleanup.verify(res["out"])                                                  # re-ASR, lost content words

    # in memory (a selected range of a long call, no render): workflows keep their own assembly
    words = cleanup.load_words(tr)                                  # any transcript shape -> word dicts
    edits = cleanup.detect(words, audio="call.mp4", ranges=[(812.4, 905.0)], profile="standard")
    keep  = cleanup.keep_segments(edits, [(812.4, 905.0)])          # auto edits only (+ approve=/keep=)
    tm    = cleanup.timemap(keep)                                   # vstudio.cut.TimeMap: captions/overlays/cues
    en    = cleanup.energy_of("call.mp4", words, [(812.4, 905.0)])  # decode + calibrate once, pass energy=en
    a, b  = cleanup.snap_range(words, 812.4, 905.0, en)             # hand-written range -> word-safe edges
    h1, fade, why = cleanup.extend_end(words, en, 812.4, 830.0, fade=0.4)   # hook end over the word tail
    ab    = cleanup.snap_cut(words, en, 850.2, 851.0)                # editor cut -> word-safe (or clean(extra=))
    res   = cleanup.clean(words, None, ranges=[(812.4, 905.0), (990, 1020)], energy=en, id_offset=12)
    cleanup.write_sidecar("body.cut.wav", "body.wav", keep, words)  # verify a cut rendered elsewhere

CLI (``python -m vstudio.cleanup``):
    analyze MEDIA [--transcript T.json] [--ranges 12.5-80,1:40-2:10] [--profile gentle|standard|tight]
            [--lang zh] [--prompt "terms"] [--out cleanup.json] [--review cleanup_review.md] [--force]
    review  cleanup.json                       re-print the review sheet
    apply   cleanup.json [--approve 3,5,9] [--keep 7] [--all-confirm] [--reply "确认 3,5,9 / 保留 7"]
            [--cut 12.3-12.9] [--out clean.mp4] [--force]
    verify  OUTPUT [--transcript got.json] [--lang zh]     exit 1 when content words were lost

What is detected (each edit: t0, t1, kind, text, confidence, action auto|confirm|keep, reason):
  pause / breath   silence (20 ms RMS frames vs the recording's own floor/speech level; soft noise-like
                   runs = breaths) longer than ``pause_min`` is SQUEEZED, not deleted: kept gap =
                   clamp(gap * pause_ratio, gap_min, gap_max), >= gap_sentence at a sentence end.
                   Range head/tail silence -> ``lead`` / ``tail``.
  filler           hesitations (嗯 呃 um uh) -> high confidence; interjections (啊 哦) and semantic
                   fillers (那个 这个 就是 然后 / like, you know, i mean) only when the audio isolates
                   them (pause before/after, drawn out); 「那个问题」 / "I like it" stay (action keep).
  filler-merged    whisper glued a filler onto the next word: RMS valley then a rise inside an over-long
                   word (``cut.hidden_onset``, the promo-recut PATCH) -> cut up to the rise. Confirm only.
  stammer / repeat immediate repeats (我我们, 像这个像这个, the the): the last copy is kept.
  restart          a phrase abandoned and restarted (我们明天去 我们明天要讲) -> the abandoned part.
  retake           a whole sentence said again within ``retake_window`` s -> the earlier take.
  asr-noise        segments ``asr.drop_hallucinations`` removed (text whisper invented over silence/music).
Only edits with confidence >= ``auto_min`` (profile) are ``auto``; the creator approves the rest.

Word-safe cutting: every word edit is cut from the silence after the previous kept word to the silence
before the next kept word (edges = quiet-run edges +- ``pad``, else the quietest frame between the two
words), so a cut never lands inside a kept word. ``apply`` snaps kept spans OUTWARD to the frame grid,
cuts video with ``cut.cut_segments`` (frame-exact) and builds the audio itself: sample-exact PCM, an
equal-power micro crossfade (``crossfade`` s, length-neutral) at every join, encoded ONCE -> A/V can't drift.

Unifies talkinghead ``strict_pass`` / ``filler_policy`` (confidence tiers, CONFIRM list, verify),
promo-recut ``tight_cut`` (RMS hidden-onset patch), call-clips ``find_cuts`` (energy pauses, restart /
repeat, edges at energy minima) and ``cut.tighten`` (pause squeeze). See references/CLEANUP.md.
"""
import argparse
import bisect
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from fractions import Fraction

import numpy as np

from . import asr, cut, media
from .audio import SR, decode_audio, rms_envelope, write_wav

VERSION = 1

# ------------------------------------------------------------------ profiles / persona
PROFILES = {
    # pause_min: shortest silence that is squeezed; kept gap = clamp(gap*pause_ratio, gap_min, gap_max),
    # at a sentence end at least gap_sentence. auto_min / confirm_min: confidence tiers.
    "gentle": dict(pause_min=0.80, pause_ratio=0.50, gap_min=0.35, gap_max=0.70, gap_sentence=0.50,
                   keep_breath=True, lead=0.25, tail=0.35, auto_min=0.92, confirm_min=0.45),
    "standard": dict(pause_min=0.45, pause_ratio=0.30, gap_min=0.18, gap_max=0.40, gap_sentence=0.30,
                     keep_breath=False, lead=0.15, tail=0.25, auto_min=0.85, confirm_min=0.30),
    "tight": dict(pause_min=0.25, pause_ratio=0.15, gap_min=0.08, gap_max=0.20, gap_sentence=0.14,
                  keep_breath=False, lead=0.08, tail=0.15, auto_min=0.75, confirm_min=0.25),
}
COMMON = dict(
    pad=0.035,              # silence left next to a kept word at a word-edit edge (s)
    crossfade=0.02,         # equal-power audio crossfade at every join (s, 0.01-0.03)
    min_piece=0.06,         # kept slivers shorter than this (no word inside) are dropped
    repeat_max_gap=1.2,     # copies further apart are not an immediate repeat
    restart_window=4.0,     # a restart must begin again within this many seconds
    retake_window=20.0,     # a re-take must follow the first take within this many seconds
    retake_ratio=0.6,       # text similarity (difflib) that counts as a re-take
    never_auto=["retake", "filler-merged", "asr-noise"],   # kinds that always need the creator's yes
    fillers_extra=[],       # the creator's own 口头禅 (treated like semantic fillers)
    never_cut=[],           # tokens never flagged as filler / repeat
    hallucinations=True,    # use asr.drop_hallucinations (when present) for asr-noise edits
    breath_flatness=0.2,    # spectral flatness above which a soft voiced run is a breath
    breath_below_db=10.0,   # a breath peaks at least this far below the speech level
)


def _persona_cleanup():
    try:
        from .config import persona
        return persona().get("cleanup") or {}
    except Exception:  # noqa: BLE001
        return {}


def settings(profile=None, overrides=None):
    """Resolved settings: COMMON + PROFILES[profile] <- persona ``cleanup.<common key>`` <-
    persona ``cleanup.profiles.<profile>.<key>`` <- ``overrides``. profile None = persona
    ``cleanup.profile`` or "standard". Unknown override keys raise KeyError."""
    pc = _persona_cleanup()
    name = profile or pc.get("profile") or "standard"
    if name not in PROFILES:
        raise ValueError(f"profile {name!r}: one of {', '.join(PROFILES)}")
    s = dict(COMMON)
    s.update(PROFILES[name])
    for k, v in pc.items():
        if k in COMMON:
            s[k] = v
    for k, v in ((pc.get("profiles") or {}).get(name) or {}).items():
        if k in s:
            s[k] = v
    for k, v in (overrides or {}).items():
        if k not in s:
            raise KeyError(f"unknown cleanup setting {k!r}")
        s[k] = v
    s["profile"] = name
    return s


# ------------------------------------------------------------------ lexicon
HESITATION = {"嗯", "呃", "额", "唔", "嗯嗯", "呃呃", "um", "uh", "erm", "uhm", "umm", "uhh", "hmm", "hm", "mm",
              "er", "ah", "eh"}
SOFT = {"啊", "哦", "哎", "诶", "欸", "噢", "呀", "喔", "oh"}
SEMANTIC_ZH = {"那个", "这个", "就是", "就是说", "然后", "然后呢", "怎么说", "怎么说呢", "对吧", "反正", "所以说", "那么"}
SEMANTIC_EN = {"like", "youknow", "imean", "sortof", "kindof", "basically", "actually", "literally", "so", "well",
               "okay", "ok", "right", "yousee"}
EN_SENTENCE_ONLY = {"so", "well", "okay", "ok", "right", "actually", "basically", "literally"}
LIKE_CONTENT_PREV = {"i", "you", "we", "they", "he", "she", "would", "do", "dont", "didnt", "does", "doesnt", "look",
                     "looks", "looked", "feel", "feels", "felt", "sound", "sounds", "seem", "seems", "is", "was", "be",
                     "more", "less", "things", "stuff", "something", "anything", "nothing", "id", "youd", "wed"}
YOUKNOW_CONTENT_NEXT = {"what", "how", "why", "that", "where", "who", "when", "the", "it", "him", "her", "them", "me",
                        "this", "if", "whether"}
REPEAT_OK = {"对", "好", "是", "行", "嗯", "哈", "yeah", "yes", "no", "bye", "ok", "okay", "very", "really", "so", "that",
             "had", "well", "hey", "ha"}
IMEAN_CONTENT_PREV = {"what", "that", "if", "dont", "didnt", "whatever", "thats"}
EN_FUNCTION = {"the", "and", "but", "this", "that", "what", "just", "they", "there", "then", "when", "with", "have"}
KIND_ZH = {"pause": "气口", "breath": "气口+换气", "lead": "开头静音", "tail": "结尾静音", "filler": "口头禅",
           "filler-merged": "粘连口头禅", "stammer": "结巴", "repeat": "重复", "restart": "说一半重来",
           "retake": "重录句", "asr-noise": "识别噪声", "edit": "手动剪"}
ACTION_ZH = {"auto": "自动删", "confirm": "待确认", "keep": "保留"}

_NORM = re.compile(r"[\W_]+")
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_WIDE = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]")    # CJK + full-width punctuation
_SENT_END = re.compile(r"[。！？!?.…]\s*$")


def norm(s):
    """Lowercase, punctuation/space-free text used for every comparison."""
    return _NORM.sub("", str(s or "").lower())


def _all_fillers(st=None):
    extra = {norm(f) for f in ((st or {}).get("fillers_extra") or [])}
    return HESITATION | SOFT | SEMANTIC_ZH | SEMANTIC_EN | extra


# ------------------------------------------------------------------ words
def load_words(transcript, sentence_gap=0.7):
    """Any transcript -> [{"i", "w", "n", "t", "te", "seg", "end"}] sorted by time.

    Accepts a ``vstudio.asr.transcribe`` dict (segments preferred, else words), whisper segments
    [{start, end, text, words:[{word, start, end}]}], flat [{"w","t","te"}] / [{"word","start","end"}]
    / [(text, start, end)], or a path to a JSON file of any of these. ``n`` = normalised text, ``seg`` =
    segment index, ``end`` = the word ends a sentence (punctuation, segment end, or a gap >= sentence_gap)."""
    if isinstance(transcript, (str, os.PathLike)):
        with open(transcript, encoding="utf-8") as f:
            transcript = json.load(f)
    raw = []
    segs = None
    if isinstance(transcript, dict):
        segs = transcript.get("segments")
        if not segs:
            raw = [(w, None) for w in transcript.get("words") or []]
    elif transcript and isinstance(transcript[0], dict) and "words" in transcript[0] and "start" in transcript[0]:
        segs = transcript
    else:
        raw = [(w, None) for w in transcript or []]
    if segs:
        for si, s in enumerate(segs):
            for w in s.get("words") or []:
                raw.append((w, si))
    out = []
    for w, si in raw:
        if isinstance(w, dict):
            txt = w.get("w", w.get("word", w.get("text", "")))
            a = w.get("t", w.get("start", w.get("b0")))
            b = w.get("te", w.get("end", w.get("b1")))
            si = w.get("seg", si)
        else:
            txt, a, b = w[0], w[1], w[2]
        txt = str(txt).strip()
        if not norm(txt) or a is None or b is None:
            continue
        out.append(dict(w=txt, n=norm(txt), t=round(float(a), 3), te=round(max(float(a), float(b)), 3), seg=si))
    out.sort(key=lambda w: (w["t"], w["te"]))
    for k, w in enumerate(out):
        nxt = out[k + 1] if k + 1 < len(out) else None
        w["i"] = k
        w["end"] = bool(_SENT_END.search(w["w"])) or nxt is None or \
            (w["seg"] is not None and nxt["seg"] != w["seg"]) or (nxt["t"] - w["te"] >= sentence_gap)
    return out


def _mid(w):
    return (w["t"] + w["te"]) / 2


def join_words(words):
    """Word texts joined like a transcript: no space next to CJK (or full-width punctuation), none before
    punctuation, one space between latin words. ``words``: dicts with ``w`` (or ``word`` / ``text``)."""
    s = ""
    for w in words:
        txt = str(w.get("w", w.get("word", w.get("text", ""))) if isinstance(w, dict) else w).strip()
        if not txt:
            continue
        if s and not (_WIDE.search(s[-1:]) or _WIDE.search(txt[:1])) and not re.match(r"[，。,.!?！？、;:；：)）]", txt):
            s += " "
        s += txt
    return s


_join = join_words


def detect_language(words):
    txt = "".join(w["n"] for w in words)
    if not txt:
        return "zh"
    return "zh" if len(_CJK.findall(txt)) >= 0.3 * len(txt) else "en"


# ------------------------------------------------------------------ energy
class Energy:
    """20 ms / 10 ms-hop RMS view of the speech audio, calibrated on the transcript.

    Energy.from_any(path | (x, sr) | Energy, start=None, end=None). ``thr`` = floor + 0.3*(speech -
    floor) (floor = 5th percentile, speech = median level inside words), capped 15 dB below speech.
    Breaths = soft (``breath_below_db`` under speech), noise-like (spectral flatness >=
    ``breath_flatness``) runs of 0.08-0.9 s with no word inside; they count as quiet."""

    hop = 0.01
    win = 0.02

    def __init__(self, x, sr, t0=0.0):
        x = np.asarray(x, np.float32)
        if x.ndim > 1:
            x = x.mean(1)
        self.x, self.sr, self.t0 = x, int(sr), float(t0)
        self.db = rms_envelope(x, sr, self.hop, self.win, db=True, smooth=1)[0]
        self.sm = np.convolve(self.db, np.ones(3) / 3, mode="same") if len(self.db) >= 3 else self.db
        self.lin = rms_envelope(x, sr, self.hop, 0.03, db=False)[0]
        self.thr = self.speech = None
        self.quiet = []
        self.breaths = []

    @classmethod
    def from_any(cls, audio, start=None, end=None):
        if audio is None or isinstance(audio, Energy):
            return audio
        if isinstance(audio, (str, os.PathLike)):
            st = max(0.0, float(start)) if start else 0.0
            dur = (float(end) - st) if end is not None else None
            x = decode_audio(str(audio), sr=16000, channels=1, start=st or None, dur=dur)[:, 0]
            return cls(x, 16000, t0=st)
        x, sr = audio[0], audio[1]
        return cls(x, sr, t0=float(audio[2]) if len(audio) > 2 else 0.0)

    @property
    def end(self):
        return self.t0 + len(self.x) / self.sr

    def idx(self, t):
        return int(round((t - self.t0) / self.hop))

    def t(self, i):
        return self.t0 + i * self.hop

    def calibrate(self, words, st):
        db = self.db
        fr = [db[max(0, self.idx(w["t"])):max(self.idx(w["t"]) + 1, self.idx(w["te"]))] for w in words]
        fr = [f for f in fr if len(f)]
        speech = float(np.median(np.concatenate(fr))) if fr else float(np.percentile(db, 70))
        floor = float(np.percentile(db, 5))
        self.speech = speech
        self.thr = min(floor + 0.3 * (speech - floor), speech - 15.0)
        voiced = db >= self.thr
        mids = sorted(_mid(w) for w in words)
        breath = np.zeros(len(db), bool)
        self.breaths = []
        for a, b in _runs(voiced):
            dur = (b - a) * self.hop
            if not (0.08 <= dur <= 0.9) or db[a:b].max() >= speech - st["breath_below_db"]:
                continue
            ta, tb = self.t(a), self.t(b) + self.win
            k = bisect.bisect_left(mids, ta)
            if k < len(mids) and mids[k] <= tb:
                continue
            if self.flatness(ta, tb) >= st["breath_flatness"]:
                breath[a:b] = True
                self.breaths.append((round(ta, 3), round(tb, 3)))
        quiet = ~voiced | breath
        # frame i covers [t(i), t(i)+win): sound may reach t(a+1) before a quiet run [a, b) and start at t(b)
        self.quiet = [(self.t(a + 1), self.t(b)) for a, b in _runs(quiet) if b - a >= 2]
        self._q0 = [q[0] for q in self.quiet]
        return self

    def flatness(self, a, b):
        x = self.x[max(0, int((a - self.t0) * self.sr)):int((b - self.t0) * self.sr)]
        n = 512 if self.sr >= 16000 else 256
        if len(x) < n:
            return 0.0
        fr = np.lib.stride_tricks.sliding_window_view(x, n)[::n // 2] * np.hanning(n)
        p = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-12
        f = np.fft.rfftfreq(n, 1 / self.sr)
        p = p[:, (f >= 300) & (f <= min(6000, self.sr / 2 - 1))]
        return float(np.mean(np.exp(np.mean(np.log(p), axis=1)) / np.mean(p, axis=1)))

    def quiet_in(self, a, b, min_len=0.02):
        """Quiet runs clipped to [a, b] (seconds), each >= min_len."""
        out = []
        k = max(0, bisect.bisect_right(self._q0, a) - 1)
        while k < len(self.quiet) and self.quiet[k][0] < b:
            q0, q1 = max(a, self.quiet[k][0]), min(b, self.quiet[k][1])
            if q1 - q0 >= min_len:
                out.append((q0, q1))
            k += 1
        return out

    def quiet_len(self, a, b):
        return sum(q1 - q0 for q0, q1 in self.quiet_in(a, b))

    def quietest(self, a, b):
        i0, i1 = max(0, self.idx(a)), min(len(self.sm) - 1, self.idx(b))
        if i1 <= i0:
            return (a + b) / 2
        return self.t(i0 + int(np.argmin(self.sm[i0:i1 + 1]))) + self.win / 2


def _runs(mask):
    """[(a, b)] index runs where mask is True."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(np.int8))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


# ------------------------------------------------------------------ detection
class _Ctx:
    def __init__(self, words, en, st, lo, hi):
        self.W, self.en, self.st, self.lo, self.hi = words, en, st, lo, hi
        self.fill = _all_fillers(st)
        self.never = {norm(x) for x in st.get("never_cut") or []}

    def gap(self, a, b):
        """Silence between two words (energy when available, else whisper's gap)."""
        if self.en is not None:
            return self.en.quiet_len(_mid(a), _mid(b))
        return max(0.0, b["t"] - a["te"])

    def kept_gap(self, g, sentence):
        st = self.st
        k = min(max(g * st["pause_ratio"], st["gap_min"]), st["gap_max"])
        if sentence:
            k = max(k, st["gap_sentence"])
        return min(g, k)


def _filler_rows(R, cx):
    out = []
    k = 0
    while k < len(R):
        hit = None
        for n in (3, 2, 1):
            if k + n > len(R):
                continue
            grp = R[k:k + n]
            txt = "".join(w["n"] for w in grp)
            if n > 1 and any(b["t"] - a["te"] > 0.3 for a, b in zip(grp, grp[1:])):
                continue
            if txt in cx.fill and txt not in cx.never:
                hit = (n, txt)
                break
        if not hit:
            k += 1
            continue
        n, txt = hit
        a, b = R[k], R[k + n - 1]
        prev = R[k - 1] if k else None
        nxt = R[k + n] if k + n < len(R) else None
        g0 = cx.gap(prev, a) if prev else 9.0
        g1 = cx.gap(b, nxt) if nxt else 9.0
        sent_start = prev is None or prev["end"]
        iso_b = g0 >= 0.15 or sent_start or (prev is not None and prev["n"] in cx.fill)
        iso_a = g1 >= 0.15 or b["end"] or (nxt is not None and nxt["n"] in cx.fill)
        dur = b["te"] - a["t"]
        chars = max(1, len(txt) if _CJK.search(txt) else len(txt) // 4)
        drawn = dur > 0.18 * chars + 0.25
        conf, why, kind = None, "", "filler"
        if txt in HESITATION:
            if dur > 0.8:
                conf, why = 0.55, f"hesitation but {dur:.2f}s long: whisper may have merged a real word"
            elif nxt is not None and nxt["n"] in ("对", "好", "是", "行", "yeah", "yes", "right") and g1 < 0.2:
                conf, why = 0.6, "嗯 before an answer word: may be agreement"
            else:
                conf, why = 0.95, "hesitation sound"
        elif txt in SOFT:
            if prev is not None and g0 < 0.06 and prev["n"] not in cx.fill and not sent_start and not iso_a:
                conf, why = None, ""                       # sentence-final particle (好啊, 是哦): not a filler
            elif prev is not None and g0 < 0.06 and prev["n"] not in cx.fill and not sent_start:
                conf, why = 0.3, "particle attached to the previous word (好啊): usually part of the sentence"
            elif iso_b and iso_a:
                conf, why = 0.8, "isolated interjection between pauses"
            else:
                conf, why = 0.45, "interjection, often part of the sentence"
        elif txt in SEMANTIC_EN or (not _CJK.search(txt) and txt in cx.fill and txt not in SEMANTIC_ZH):
            pn = prev["n"] if prev else ""
            nn = nxt["n"] if nxt else ""
            if txt in EN_SENTENCE_ONLY and not (sent_start and iso_a):
                conf = None
            elif txt in EN_SENTENCE_ONLY:
                conf, why = 0.45, "sentence-initial discourse marker before a pause: taste call"
            elif txt == "like" and pn in LIKE_CONTENT_PREV and g0 < 0.15:
                conf, why = 0.15, f"'{pn} like': verb / comparison, a real word"
            elif txt == "youknow" and nn in YOUKNOW_CONTENT_NEXT and g1 < 0.15:
                conf, why = 0.15, f"'you know {nn}': a real phrase"
            elif txt == "imean" and pn in IMEAN_CONTENT_PREV and g0 < 0.15:
                conf, why = 0.15, f"'{pn} I mean': a real phrase"
            else:
                conf = 0.3 + 0.25 * iso_b + 0.25 * iso_a + 0.1 * drawn
                why = "discourse filler" + (" between pauses" if iso_b and iso_a else
                                            ", one side runs into speech: confirm by ear")
                if not iso_b and not iso_a:
                    conf, why = 0.2, "inside a phrase: probably a real word"
                conf = min(conf, 0.8)
        else:                                              # zh semantic / creator's own 口头禅
            nn_glued = nxt is not None and g1 < 0.1 and nxt["n"] not in cx.fill
            if not iso_b and not iso_a and not drawn:
                conf, why = 0.15, "inside a phrase (那个问题 / 我就是喜欢): a real word"
            elif txt in ("那个", "这个") and nn_glued and not drawn:
                conf, why = (0.25, f"sentence-initial determiner before '{nxt['w']}' (这个模型): usually a real word") \
                    if iso_b else (0.15, f"determiner before '{nxt['w']}': a real word")
            else:
                conf = 0.3 + 0.25 * iso_b + 0.25 * iso_a + 0.15 * drawn
                bits = [x for x, on in (("pause before", iso_b), ("pause after", iso_a), ("drawn out", drawn)) if on]
                why = "semantic filler (" + ", ".join(bits) + ")"
                if txt in ("然后", "所以说", "那么") and not iso_a:
                    conf, why = min(conf, 0.4), "connector at a sentence start: often fine, confirm by ear"
                if txt == "对吧" and b["end"]:
                    conf, why = min(conf, 0.35), "tag question at a sentence end"
                conf = min(conf, 0.8)
        if conf is not None:
            out.append(dict(kind=kind, i=a["i"], j=b["i"], conf=conf, reason=why, text=_join(R[k:k + n])))
        k += n
    return out


def _repeat_rows(R, cx):
    out, k = [], 0
    st = cx.st
    while k < len(R) - 1:
        best = None
        for n in range(1, 7):
            if k + 2 * n > len(R):
                break
            u1 = "".join(w["n"] for w in R[k:k + n])
            u2 = "".join(w["n"] for w in R[k + n:k + 2 * n])
            if u1 == u2 and 1 <= len(u1) <= 16 and R[k + n]["t"] - R[k + n - 1]["te"] <= st["repeat_max_gap"] \
                    and not any(w["end"] and w["n"] not in cx.fill for w in R[k:k + n - 1]):
                best = n
        if best:
            n = best
            u = "".join(w["n"] for w in R[k:k + n])
            last = k + n
            while last + n <= len(R) and "".join(w["n"] for w in R[last:last + n]) == u:
                last += n
            last -= n                                      # start index of the kept (last) copy
            gap = cx.gap(R[last - 1], R[last])
            if u in HESITATION or u in cx.never:
                k = last + n
                continue
            if n == 1 and (u in REPEAT_OK or u in cut.EMPHASIS or (len(u) == 1 and u in cut.REDUP_ZH)):
                conf, kind, why = 0.35, "repeat", "doubling that can be deliberate (对对 / very very / 慢慢)"
            elif n == 1 and (len(u) == 1 or (not _CJK.search(u) and len(u) <= 6)):
                conf, kind, why = (0.9 if gap < 0.5 else 0.7), "stammer", "stammer: same word twice, keep the last"
            else:
                conf, kind = (0.88 if gap < 0.6 else 0.7), "repeat"
                why = f"'{u}' said {(last - k) // n + 1}x back to back, keep the last"
            if u in cx.fill:
                why += " (filler repeated)"
            out.append(dict(kind=kind, i=R[k]["i"], j=R[last - 1]["i"], conf=conf, reason=why,
                            text=_join(R[k:last])))
            k = last + n
            continue
        a, b = R[k], R[k + 1]
        cjk = bool(_CJK.search(a["n"]))
        if a["n"] and b["n"].startswith(a["n"]) and a["n"] != b["n"] and a["n"] not in cx.never \
                and b["t"] - a["te"] <= 0.6 and not a["end"]:
            if cjk and len(a["n"]) == 1:
                out.append(dict(kind="stammer", i=a["i"], j=a["i"], conf=0.75, text=a["w"],
                                reason=f"'{a['w']}' then '{b['w']}': clipped start, keep the full word"))
            elif not cjk and (a["w"].rstrip().endswith("-") or (2 <= len(a["n"]) <= 4 and a["te"] - a["t"] < 0.15)):
                cutoff = a["w"].rstrip().endswith("-")
                out.append(dict(kind="stammer", i=a["i"], j=a["i"], conf=0.9 if cutoff else 0.8, text=a["w"],
                                reason=f"'{a['w']}' cut off before '{b['w']}'"))
            elif not cjk and 2 <= len(a["n"]) <= 4:
                out.append(dict(kind="stammer", i=a["i"], j=a["i"], conf=0.5, text=a["w"],
                                reason=f"'{a['w']}' is a prefix of '{b['w']}': stammer or two real words"))
        k += 1
    return out


def _restart_rows(R, cx, taken):
    out = []
    st = cx.st
    i = 0
    while i < len(R) - 2:
        if R[i]["i"] in taken or R[i]["end"]:
            i += 1
            continue
        found = None
        for j in range(i + 2, min(len(R), i + 14)):
            if R[j]["t"] - R[i]["t"] > st["restart_window"]:
                break
            if R[j - 1]["end"] and R[j - 1]["n"] not in cx.fill:
                break                                      # a finished sentence: parallel structure, not a restart
            m = 0
            while j + m < len(R) and i + m < j and R[i + m]["n"] == R[j + m]["n"]:
                m += 1
            if m == 0 or j - i == m or j + m >= len(R):
                continue
            pref = "".join(w["n"] for w in R[i:i + m])
            cjk = bool(_CJK.search(pref))
            if pref in cx.fill or j - i - m > 6:
                continue
            marker = cx.gap(R[j - 1], R[j]) >= 0.15 or R[j - 1]["n"] in cx.fill or R[j - 1]["te"] - R[j - 1]["t"] < 0.1
            if cjk and not (len(pref) >= 2 and (m >= 2 or marker)):
                continue
            if not cjk and not (m >= 2 or (len(pref) >= 4 and pref not in EN_FUNCTION and marker)):
                continue
            found = (j, m, marker)
            break
        if not found:
            i += 1
            continue
        j, m, marker = found
        conf = 0.62 + (0.15 if marker else 0.0)
        out.append(dict(kind="restart", i=R[i]["i"], j=R[j - 1]["i"], conf=conf, text=_join(R[i:j]),
                        reason=f"starts '{_join(R[i:i + m])}', breaks off"
                               + (" (pause / filler)" if marker else "") + f", restarts as '{_join(R[j:j + m + 2])}'"))
        i = j
    return out


def _sentences(R, cx):
    S, cur = [], []
    for k, w in enumerate(R):
        cur.append(w)
        nxt = R[k + 1] if k + 1 < len(R) else None
        if w["end"] or nxt is None or cx.gap(w, nxt) >= 0.7:
            S.append(cur)
            cur = []
    return S


def _retake_rows(R, cx):
    st = cx.st
    S = _sentences(R, cx)
    txt = ["".join(w["n"] for w in s if w["n"] not in HESITATION) for s in S]
    out, a = [], 0
    while a < len(S) - 1:
        hit = None
        for b in range(a + 1, min(len(S), a + 4)):
            if S[b][0]["t"] - S[a][-1]["te"] > st["retake_window"]:
                break
            if len(txt[a]) < 6 or len(txt[b]) < 6:
                continue
            r = difflib.SequenceMatcher(None, txt[a], txt[b], autojunk=False).ratio()
            mid_ok = all(len(txt[m]) <= 6 or difflib.SequenceMatcher(None, txt[m], txt[b]).ratio() >= 0.5
                         for m in range(a + 1, b))
            if r >= st["retake_ratio"] and mid_ok:
                hit = (b, r)
                break
        if not hit:
            a += 1
            continue
        b, r = hit
        conf = min(0.8, 0.55 + 0.6 * (r - st["retake_ratio"]))
        why = f"sentence said again {S[b][0]['t'] - S[a][0]['t']:.1f}s later (similarity {r:.2f}): keep the last take"
        if len(txt[b]) < 0.6 * len(txt[a]):
            conf -= 0.15
            why += "; the later take is much shorter - maybe keep the first instead"
        drop = [w for s in S[a:b] for w in s]
        out.append(dict(kind="retake", i=drop[0]["i"], j=drop[-1]["i"], conf=round(conf, 2), text=_join(drop),
                        reason=why))
        a = b
    return out


def _merged_rows(R, cx):
    en = cx.en
    if en is None:
        return []
    out = []
    for k, w in enumerate(R):
        d, syl = w["te"] - w["t"], cut.syllables(w["w"])
        if d <= max(0.45, 0.22 * syl + 0.15) or w["t"] < en.t0 or w["te"] > en.end:
            continue
        latin = not _CJK.search(w["n"])
        h = cut.hidden_onset(en.lin, en.hop, w["t"] - en.t0, w["te"] - en.t0, min_gap=0.2 if latin else 0.05,
                             min_tail=max(0.06, 0.1 * syl - 0.03))
        if not h:
            continue
        d0, d1, new = (v + en.t0 for v in h)
        back = w["te"] - new
        vs = [q for q in en.quiet_in(w["t"], d0)]
        front_start = vs[-1][1] if vs and vs[-1][1] < d0 - 0.05 else w["t"]
        front = d0 - front_start
        if back < max(0.15, 0.12 * syl) or not (0.06 <= front <= 0.8):
            continue
        first = w["n"][:1]
        conf = 0.6 if first in HESITATION or w["n"][:2] in HESITATION else 0.45
        out.append(dict(kind="filler-merged", i=w["i"], j=w["i"], conf=conf, text=w["w"], cut_to=round(new, 3),
                        patch=[w["t"], round(new, 3)],
                        reason=f"'{w['w']}' is {d:.2f}s: {front:.2f}s of sound, a dip at {d0:.2f}-{d1:.2f}s, then the "
                               f"word - a filler/restart merged into it; cut up to {new:.2f}s (listen)"))
    return out


def _block_edges(cx, i, j, cut_to=None):
    """Word-safe (t0, t1) removing words i..j (global indices) inside the current range."""
    W, en, st = cx.W, cx.en, cx.st
    wi, wj = W[i], W[j]
    P = W[i - 1] if i > 0 and _mid(W[i - 1]) >= cx.lo else None
    N = W[j + 1] if j + 1 < len(W) and _mid(W[j + 1]) <= cx.hi else None
    pad = st["pad"]
    gl = gr = 0.0
    if P is None:
        A0 = A = cx.lo
    elif en is not None:
        runs = en.quiet_in(_mid(P), _mid(wi))
        if runs:
            A0, gl = runs[0][0], runs[0][1] - runs[0][0]
        else:
            A0 = en.quietest(P["t"] + 0.6 * (P["te"] - P["t"]), wi["t"] + 0.35 * (wi["te"] - wi["t"]))
    else:
        A0 = min(P["te"] + 0.06, (P["te"] + wi["t"]) / 2)
    if cut_to is not None:
        B1 = cut_to
    elif N is None:
        B1 = cx.hi
    elif en is not None:
        runs = en.quiet_in(_mid(wj), _mid(N))
        if runs:
            B1, gr = runs[-1][1], runs[-1][1] - runs[-1][0]
        else:
            B1 = en.quietest(wj["t"] + 0.6 * (wj["te"] - wj["t"]), N["t"] + 0.35 * (N["te"] - N["t"]))
    else:
        B1 = max(N["t"] - 0.04, (wj["te"] + N["t"]) / 2)
    if P is not None and en is not None:
        kept = cx.kept_gap(gl + gr, P["end"])
        lk = min(gl, kept / 2 if gr > 0 else kept)
        rk = min(gr, kept - lk)
        if gl > 0:
            lk = max(lk, min(pad, gl / 2))
        if gr > 0 and N is not None:
            rk = max(rk, min(pad, gr / 2))
        A, B1 = A0 + lk, B1 - rk
    elif P is not None:
        A = A0
    else:
        A = A0
        if N is not None and gr > 0:
            B1 -= min(st["lead"], gr)
    return round(max(cx.lo, A), 3), round(min(cx.hi, B1), 3)


def _pause_rows(cx, R):
    en, st = cx.en, cx.st
    out = []
    if en is not None:
        runs = en.quiet_in(cx.lo, cx.hi)
    else:
        runs = [(a["te"] + 0.12, b["t"]) for a, b in zip(R, R[1:])]
        if R:
            runs = [(cx.lo, R[0]["t"])] + runs + [(R[-1]["te"] + 0.12, cx.hi)]
    mids = [_mid(w) for w in R]
    for q0, q1 in runs:
        g = q1 - q0
        k = bisect.bisect_left(mids, (q0 + q1) / 2)
        prev = R[k - 1] if k > 0 else None
        nxt = R[k] if k < len(R) else None
        br = [b for b in (en.breaths if en is not None else []) if b[0] < q1 and b[1] > q0]
        conf = 0.97 if en is not None else 0.7
        if prev is None:                                   # range head
            if g < st["lead"] + 0.05:
                continue
            t0, t1 = cx.lo, q1 - st["lead"]
            kind, why = "lead", f"{g:.2f}s silence before the first word -> {st['lead']:.2f}s"
        elif nxt is None:                                  # range tail
            if g < st["tail"] + 0.05:
                continue
            t0, t1 = q0 + st["tail"], cx.hi
            kind, why = "tail", f"{g:.2f}s silence after the last word -> {st['tail']:.2f}s"
        else:
            if g < st["pause_min"]:
                continue
            kept = cx.kept_gap(g, prev["end"])
            if br and st["keep_breath"]:
                b0 = min(b[0] for b in br)
                t0, t1 = q0 + kept / 2, b0 - 0.04
                why = f"{g:.2f}s pause -> breath kept"
            else:
                rk = kept / 2
                if br:
                    be = max(b[1] for b in br)
                    rk = min(rk, max(0.03, q1 - be - 0.02))
                t0, t1 = q0 + (kept - rk), q1 - rk
                why = f"{g:.2f}s {'sentence ' if prev['end'] else ''}pause -> {kept:.2f}s" + \
                    (f" (breath {sum(b[1] - b[0] for b in br):.2f}s removed)" if br else "")
            kind = "breath" if br else "pause"
            if en is None:
                why += " (no audio: from whisper gaps, listen)"
        if t1 - t0 < 0.05:
            continue
        out.append(dict(kind=kind, i=None, j=None, conf=conf, reason=why, text="", t0=round(t0, 3), t1=round(t1, 3),
                        gap=round(g, 3), prev=prev["i"] if prev else None, next=nxt["i"] if nxt else None))
    return out


def _context(W, t0, t1, n=10):
    before = [w for w in W if _mid(w) < t0][-n:]
    after = [w for w in W if _mid(w) > t1][:n]
    return _join(before), _join(after)


def detect(words, audio=None, ranges=None, profile=None, overrides=None, dropped=None, language=None, energy=None,
           id_offset=0):
    """Find every cleanup edit in ``words`` (``load_words`` output or any transcript) inside ``ranges``.

    audio: media path / (x, sr[, t0]) / ``Energy`` (strongly recommended: pauses, breaths, isolation of
    fillers, merged fillers and word-safe edges all come from the audio; without it pauses come from
    whisper gaps at lower confidence). ranges: [(a, b)] source seconds (default: all words).
    dropped: [{start, end, text, reason}] hallucinated segments (``asr-noise`` edits).
    Several ranges (windows) share ONE numbering, in time order. id_offset: ids start at id_offset + 1
    (several clips / windows reviewed on one sheet). Returns edits sorted by t0: {id, t0, t1, kind, text,
    confidence, action, reason, words: [i..], before, after}. Pure: no files written."""
    st = settings(profile, overrides)
    W = words if (isinstance(words, list) and words and isinstance(words[0], dict) and "n" in words[0]
                  and "i" in words[0]) else load_words(words)
    if not W and not ranges:
        return []
    ranges = _norm_ranges(ranges) or [(max(0.0, W[0]["t"] - 0.5), W[-1]["te"] + 0.5)]
    en = energy
    if en is None and audio is not None:
        en = Energy.from_any(audio, start=max(0.0, ranges[0][0] - 1.0), end=ranges[-1][1] + 1.0)
    if en is not None and en.thr is None:
        en.calibrate([w for w in W if any(a <= _mid(w) <= b for a, b in ranges)] or W, st)
    rows = []
    for lo, hi in ranges:
        R = [w for w in W if lo <= _mid(w) <= hi]
        cx = _Ctx(W, en, st, lo, hi)
        found = _filler_rows(R, cx) + _repeat_rows(R, cx)
        taken = {x for r in found if r["kind"] in ("repeat", "stammer") for x in range(r["i"], r["j"] + 1)}
        found += _restart_rows(R, cx, taken) + _retake_rows(R, cx) + _merged_rows(R, cx)
        for r in found:
            r["t0"], r["t1"] = _block_edges(cx, r["i"], r["j"], r.get("cut_to"))
            if en is None:
                r["conf"] = max(0.0, r["conf"] - 0.1)
                r["reason"] += " (no audio: edges from whisper times)"
        found += _pause_rows(cx, R)
        for d in dropped or []:
            a, b = max(lo, float(d["start"])), min(hi, float(d["end"]))
            if b - a >= 0.1:
                found.append(dict(kind="asr-noise", i=None, j=None, conf=0.6, t0=round(a, 3), t1=round(b, 3),
                                  text=str(d.get("text", ""))[:40],
                                  reason=f"whisper text over non-speech ({d.get('reason', 'hallucination')})"))
        for r in found:
            if r["t1"] - r["t0"] >= 0.03:
                rows.append(r)
    edits = []
    for r in sorted(rows, key=lambda r: (r["t0"], r["t1"])):
        c = round(float(r["conf"]), 2)
        if c >= st["auto_min"] and r["kind"] not in st["never_auto"]:
            act = "auto"
        elif c >= st["confirm_min"]:
            act = "confirm"
        else:
            act = "keep"
        bf, af = _context(W, r["t0"], r["t1"])
        e = dict(id=int(id_offset) + len(edits) + 1, t0=r["t0"], t1=r["t1"], kind=r["kind"], text=r["text"], confidence=c,
                 action=act, reason=r["reason"], before=bf, after=af,
                 words=list(range(r["i"], r["j"] + 1)) if r.get("i") is not None and not r.get("patch") else [])
        if "gap" in r:
            e["gap"] = r["gap"]
        if r.get("patch"):
            e["patch"] = r["patch"]           # [old word start, new start]: the word stays, its start moves
        edits.append(e)
    return edits


# ------------------------------------------------------------------ decisions -> keep segments
def norm_ranges(ranges):
    """[(a, b), ...] (any order, overlapping or touching, empty ones) -> sorted, merged [(a, b)] floats.
    Empty / None -> []."""
    out = sorted((float(r[0]), float(r[1])) for r in ranges or () if float(r[1]) > float(r[0]))
    merged = []
    for a, b in out:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _norm_ranges(ranges):
    return norm_ranges(ranges) or None


def applied_ids(edits, approve=(), keep=(), all_confirm=False):
    """Ids that will be cut: every ``auto`` edit, plus ``approve`` (any action), plus every ``confirm``
    edit when all_confirm, minus ``keep``."""
    ap, kp = {int(x) for x in approve or ()}, {int(x) for x in keep or ()}
    return sorted({e["id"] for e in edits if e["action"] == "auto" or e["id"] in ap
                   or (all_confirm and e["action"] == "confirm")} - kp)


def keep_segments(edits, ranges, approve=(), keep=(), all_confirm=False, extra=(), min_piece=None, words=None):
    """Kept source spans [(a, b)]: ``ranges`` minus the applied edits (``applied_ids``) and ``extra``
    editor cuts [(a, b[, why])]. Slivers < min_piece s (COMMON 0.06) are dropped unless a word's
    midpoint is inside (``words`` given)."""
    mp = COMMON["min_piece"] if min_piece is None else min_piece
    ids = set(applied_ids(edits, approve, keep, all_confirm))
    cuts = sorted([(e["t0"], e["t1"]) for e in edits if e["id"] in ids] + [(float(c[0]), float(c[1])) for c in extra or ()])
    out = []
    for lo, hi in _norm_ranges(ranges) or []:
        cur = lo
        for a, b in cuts:
            if b <= cur or a >= hi:
                continue
            if a > cur:
                out.append((cur, min(a, hi)))
            cur = max(cur, b)
        if cur < hi:
            out.append((cur, hi))
    mids = sorted(_mid(w) for w in words or [])
    res = []
    for a, b in out:
        if b - a < mp and not any(a <= m <= b for m in mids):
            continue
        res.append((round(a, 3), round(b, 3)))
    return res


def timemap(keep):
    """``vstudio.cut.TimeMap`` of kept spans played back to back (source -> cleaned seconds)."""
    return cut.TimeMap.from_segments(list(keep))


def remap_words(words, tm):
    """Words whose midpoint survives the cut, in cleaned seconds: [{"w","t","te","src"}]."""
    if not isinstance(tm, cut.TimeMap):
        tm = cut.TimeMap(tm)
    out = []
    for w in load_words(words) if words and "n" not in words[0] else words:
        if tm.to_final(_mid(w)) is None:
            continue
        a, b = tm.to_final(w["t"], "fwd"), tm.to_final(w["te"], "back")
        if a is None or b is None:
            continue
        out.append(dict(w=w["w"], t=round(a, 3), te=round(max(a, b), 3), src=w["t"]))
    return out


def as_cuts(edits, approve=(), keep=(), all_confirm=False):
    """Applied edits as call-clips style cut list [[a, b, why], ...] (``cut.split_window`` input)."""
    ids = set(applied_ids(edits, approve, keep, all_confirm))
    return [[e["t0"], e["t1"], f"{e['kind']}:{e['text']}" if e["text"] else e["kind"]] for e in edits if e["id"] in ids]


def clean(words, audio, lo=None, hi=None, profile=None, overrides=None, approve=(), keep=(), all_confirm=False,
          energy=None, ranges=None, extra=(), id_offset=0):
    """Windows in memory (call-clips / longform selections): dict(edits, keep, cuts, extra, timemap).

    One window ``lo, hi`` or several ``ranges=[(a, b), ...]`` (one edit numbering across all of them,
    starting at ``id_offset + 1``). ``extra``: editor cuts [(a, b[, why])], made word-safe by ``snap_cut``
    (only those touching a window) and cut too. ``cuts`` replaces ``cut.find_cuts`` output (applied edits +
    snapped editor cuts, ``[a, b, why]``); ``keep`` replaces ``cut.split_window`` output; ``extra`` = the
    snapped editor cuts. audio: path / (x, sr[, t0]) / None; ``energy`` = an ``energy_of`` result."""
    W = _words(words)
    rg = norm_ranges(ranges) if ranges is not None else \
        norm_ranges([(lo, hi)]) if lo is not None and hi is not None else []
    if not rg:
        raise ValueError("clean: give lo, hi or ranges=[(a, b), ...]")
    en = energy
    if en is None and audio is not None:
        en = energy_of(audio, W, rg, profile, overrides)
    eds = detect(W, ranges=rg, profile=profile, overrides=overrides, energy=en, id_offset=id_offset)
    ed = snap_cuts(W, en, extra, rg)
    win = [w for w in W if any(a <= _mid(w) <= b for a, b in rg)]
    kp = keep_segments(eds, rg, approve, keep, all_confirm, extra=ed, words=win)
    cuts = as_cuts(eds, approve, keep, all_confirm)
    if ed:
        cuts = sorted(cuts + ed)
    return dict(edits=eds, keep=kp, cuts=cuts, extra=ed, timemap=timemap(kp))


# ------------------------------------------------------------------ word-safe edges (in memory)
# For workflows that place their own edges (hook windows, hand-written keep ranges, editor cuts):
# talkinghead ``bodycut.word_limits / snap_range``, call-clips ``WordClampedAudio`` / ``hook_edges``.
def energy_of(audio, words, ranges=None, profile=None, overrides=None):
    """Calibrated ``Energy`` for ``audio`` (path / (x, sr[, t0])) around ``ranges`` - pass it as
    ``energy=`` to detect / clean / the edge helpers below to decode the audio once."""
    W = _words(words)
    rg = _norm_ranges(ranges)
    en = Energy.from_any(audio, start=max(0.0, rg[0][0] - 1.0) if rg else None, end=rg[-1][1] + 1.0 if rg else None)
    if en is not None and en.thr is None:
        en.calibrate([w for w in W if not rg or any(a <= _mid(w) <= b for a, b in rg)] or W,
                     settings(profile, overrides))
    return en


def _words(words):
    if not words:
        return []
    return words if isinstance(words[0], dict) and "n" in words[0] and "i" in words[0] else load_words(words)


def word_limits(words, t0, t1, margin=0.03):
    """(lo, hi): how far a kept range [t0, t1] may grow before it reaches a NEIGHBOUR word (a word whose
    midpoint is outside the range). Word ends are reliable, word starts swallow the pause before them,
    so the previous word's end (+margin) bounds the start and the next word's start bounds the end.
    Port of talkinghead ``bodycut.word_limits``."""
    W = _words(words)
    prev = [w["te"] for w in W if w["te"] <= t0 + 0.05 and _mid(w) < t0]
    nxt = [w["t"] for w in W if w["t"] >= t1 - 0.05 and _mid(w) > t1]
    lo = min(max(prev) + margin, t0) if prev else float("-inf")
    hi = max(min(nxt), t1) if nxt else float("inf")
    return lo, hi


def word_tail(en, t, limit, quiet_run=0.06):
    """First second >= t where ``en`` (calibrated ``Energy``) stays quiet for ``quiet_run`` s - the real
    end of a word whose whisper ``te`` is ``t`` (whisper ends run early) - or ``limit`` if none."""
    need = max(1, int(round(quiet_run / en.hop)))
    a, b = max(0, en.idx(t)), min(en.idx(limit), len(en.db))
    run = 0
    for k in range(a, b):
        if en.db[k] < en.thr:
            run += 1
            if run >= need:
                return max(t, en.t(k - need + 1) + en.win / 2)
        else:
            run = 0
    return limit


def safe_edge(words, t, en=None, side="end", pad=None):
    """Move one cut / keep edge ``t`` so it is never inside a word.

    side="end": ``t`` ends kept material (keep up to t) -> if t is inside a word, or before that word's
    real tail, it moves LATER to the word's sounding end (+pad), never into the next word.
    side="start": ``t`` starts kept material -> moves EARLIER to before the word's onset (-pad), never
    into the previous word. Inside a pause the edge stays put, or with ``en`` moves to the quiet run.
    Call-clips ``WordClampedAudio`` semantics: an edge never lands inside the word it borders."""
    W = _words(words)
    pad = COMMON["pad"] if pad is None else pad
    if not W:
        return t
    starts = [w["t"] for w in W]
    if side == "end":
        # keep up to t: the word that may be cut short is the last one starting BEFORE t (a word starting
        # exactly at t is not kept at all, so the edge must not grow over it)
        k = bisect.bisect_left(starts, t) - 1
    else:
        k = bisect.bisect_right(starts, t) - 1                   # last word starting at or before t
    cur = W[k] if k >= 0 else None
    nxt = W[k + 1] if k + 1 < len(W) else None
    if side == "end":
        if cur is None:
            return t
        hard = nxt["t"] - 0.02 if nxt is not None else float("inf")
        end = cur["te"]
        if en is not None and en.thr is not None:
            end = word_tail(en, cur["te"], min(cur["te"] + 0.6, hard))
        if t >= end + pad:
            return t
        return round(min(max(t, end + pad), max(t, hard)), 3)
    prev = W[k - 1] if k >= 1 else None
    if cur is not None and t < cur["te"]:                       # inside cur: start before it
        floor = prev["te"] + 0.02 if prev is not None else float("-inf")
        on = cur["t"]
        if en is not None and en.thr is not None:
            runs = en.quiet_in(max(floor, on - 0.6), _mid(cur))
            if runs:
                on = runs[-1][1]
        return round(max(min(t, on - pad), min(t, floor)), 3)
    if nxt is not None and en is not None and en.thr is not None and t > nxt["t"] - 0.3:
        runs = en.quiet_in(cur["te"] if cur else t - 0.6, _mid(nxt))
        if runs and runs[-1][1] < t:
            return round(max(runs[-1][1] - pad, runs[-1][0]), 3)  # the onset hides before whisper's start
    return t


def snap_cut(words, energy, a, b, pad=None):
    """A manual (editor) cut [a, b] -> word-safe (a', b'), or None when nothing is left (< 30 ms).

    The words whose midpoint is inside [a, b] go (the cut grows to cover their onset and whisper end); the
    cut starts no earlier than the previous kept word's sounding end (+pad, ``word_tail``) and ends no
    later than the next kept word's onset (-pad, ``safe_edge`` side="start"). ``energy``: calibrated
    ``Energy`` or None (whisper times only). Port of call-clips ``editor_cut``."""
    W = _words(words)
    en = energy
    pad = COMMON["pad"] if pad is None else pad
    inside = [w for w in W if a <= _mid(w) <= b]
    prev = [w for w in W if _mid(w) < a]
    nxt = [w for w in W if _mid(w) > b]
    first = inside[0]["t"] if inside else b
    lo = float("-inf")
    if prev:
        p = prev[-1]
        tail = word_tail(en, p["te"], max(p["te"], first)) if en is not None else p["te"]
        lo = min(max(tail, p["te"]) + pad, max(first, p["te"]))
    hi = safe_edge(W, nxt[0]["t"], en, "start", pad) if nxt else float("inf")
    a2 = max(min(a, first), lo)
    b2 = min(max(b, inside[-1]["te"]) if inside else b, hi)
    return (round(a2, 3), round(b2, 3)) if b2 - a2 >= 0.03 else None


def snap_cuts(words, energy, cuts, ranges=None, pad=None):
    """Editor cuts [(a, b[, why]), ...] -> word-safe ``[[a, b, "edit: why"], ...]`` (``snap_cut``), only
    those touching one of ``ranges`` (default: all). Ready for ``keep_segments(extra=)`` / a cut list."""
    rg = norm_ranges(ranges) if ranges is not None else None
    W = _words(words)
    out = []
    for c in cuts or ():
        a, b = float(c[0]), float(c[1])
        if rg is not None and not any(b > lo and a < hi for lo, hi in rg):
            continue
        r = snap_cut(W, energy, a, b, pad)
        if r:
            out.append([r[0], r[1], f"edit: {c[2]}" if len(c) > 2 and c[2] else "edit"])
    return out


def snap_range(words, t0, t1, en=None, pad=None):
    """A hand-written keep range -> word-safe (a, b): the start backs off to before its first word's
    onset, the end extends over its last word's real tail, neither reaches a neighbour word
    (``word_limits``). Port of talkinghead ``bodycut.snap_range`` (without the inner pause squeeze -
    run ``detect`` / ``clean`` on the result for that)."""
    lo, hi = word_limits(words, t0, t1)
    a = max(lo, safe_edge(words, t0, en, "start", pad))
    b = min(hi, safe_edge(words, t1, en, "end", pad))
    return round(a, 3), round(max(a, b), 3)


def extend_end(words, en, h0, h1, fade=0.0, speed=1.0, min_fade=0.12, guard=0.05, max_tail=0.6):
    """(new_h1, new_fade, info) for a window [h0, h1] whose last ``fade`` final seconds are faded out
    (a hook dissolving into the body, a clip end): h1 moves to the last word's real tail + fade*speed,
    never into the next word (``guard`` s before it); when the gap is too tight the fade shrinks
    (down to ``min_fade``) instead. new_h1 >= h1, new_fade <= fade. Port of call-clips
    ``hook_edges.extend_hook`` on the shared ``Energy``."""
    W = _words(words)
    inside = [w for w in W if h0 <= _mid(w) <= h1]
    if not inside:
        return h1, fade, ""
    last = inside[-1]
    nxt = next((w["t"] for w in W if w["t"] > last["t"] and _mid(w) > h1), None)
    hard = (nxt - guard) if nxt is not None else float("inf")
    tail = word_tail(en, last["te"], min(last["te"] + max_tail, hard)) if en is not None else last["te"]
    tail = max(tail, last["te"])
    want = tail + max(fade, 0.0) * speed
    limit = min(hard, tail + max_tail + max(fade, 0.0) * speed)
    new_h1 = max(h1, min(want, limit))
    room = (new_h1 - tail) / speed
    new_fade = fade if room >= fade else max(min(min_fade, fade), room)
    info = ""
    if new_h1 > h1 + 1e-6 or new_fade < fade - 1e-6:
        info = (f"end {h1:.2f} -> {new_h1:.2f}s (last word sounds until {tail:.2f}s)"
                + (f", fade {fade:.2f} -> {new_fade:.2f}s" if new_fade < fade - 1e-6 else ""))
    return round(new_h1, 3), round(new_fade, 3), info


# ------------------------------------------------------------------ review sheet / replies
def _mmss(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:04.1f}"


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def saved_seconds(edits, ranges=None):
    """Seconds actually removed by ``edits`` (dicts with t0 / t1, or (a, b) pairs): the length of the
    merged UNION of their spans (overlapping edits, e.g. a pause inside a filler's cut, count once),
    clipped to ``ranges`` when given."""
    spans = norm_ranges([(e["t0"], e["t1"]) if isinstance(e, dict) else (e[0], e[1]) for e in edits or ()])
    if ranges is None:
        return sum(b - a for a, b in spans)
    return sum(max(0.0, min(b, hi) - max(a, lo)) for a, b in spans for lo, hi in norm_ranges(ranges))


def review_sheet(edl, path=None):
    """Markdown review sheet for the creator: numbered edits with context, AUTO / 待确认 / 保留 sections,
    and how to reply ("确认 3,5,9 / 保留 7"). Written to ``path`` if given. Returns the text."""
    edl = _load_edl(edl)[0]
    E = edl["edits"]
    total = sum(b - a for a, b in edl["ranges"])
    saved = saved_seconds([e for e in E if e["action"] == "auto"], edl["ranges"])
    L = [f"# 剪辑清理确认单 / cleanup review", "",
         f"- 素材 source: `{os.path.basename(edl['source']['path'])}`  ·  档位 profile: **{edl['profile']}**"
         f"  ·  语言 {edl.get('language', '')}",
         f"- 范围 ranges: {', '.join(f'{_mmss(a)}-{_mmss(b)}' for a, b in edl['ranges'])}  ({total:.1f}s)",
         f"- 自动删 auto: {sum(e['action'] == 'auto' for e in E)} 处, 省 {saved:.1f}s  ·  待确认 confirm: "
         f"{sum(e['action'] == 'confirm' for e in E)} 处  ·  保留 keep: {sum(e['action'] == 'keep' for e in E)} 处", "",
         "回复方式 reply: `确认 3,5,9 / 保留 7` (确认 = 也删掉这些待确认项; 保留 = 不删这些自动项), "
         "`全部确认`, or `approve 3,5 keep 7`. 数字可写范围 `3-6`.", ""]

    def table(rows, title):
        if not rows:
            return
        L.append(f"## {title}")
        L.append("")
        L.append("| # | 时间 | 类型 | 置信 | 上下文 (【】= 删掉的部分) | 原因 |")
        L.append("|---|---|---|---|---|---|")
        for e in rows:
            if e.get("patch"):                             # the word stays; only the sound glued before it goes
                ctx = f"…{e['before'][-14:]}【{e['text']}前的粘连音】{e['after'][:14]}…"
            elif e["kind"] in ("pause", "breath", "lead", "tail"):
                ctx = f"…{e['before'][-12:]} ⏸ {e['t1'] - e['t0']:.2f}s {e['after'][:12]}…"
            else:
                ctx = f"…{e['before'][-14:]}【{e['text']}】{e['after'][:14]}…"
            L.append(f"| {e['id']} | {_mmss(e['t0'])} | {KIND_ZH.get(e['kind'], e['kind'])} | {e['confidence']:.2f} | "
                     f"{_cell(ctx)} | {_cell(e['reason'])} |")
        L.append("")

    words_auto = [e for e in E if e["action"] == "auto" and e["kind"] not in ("pause", "breath", "lead", "tail")]
    pauses = [e for e in E if e["action"] == "auto" and e["kind"] in ("pause", "breath", "lead", "tail")]
    table([e for e in E if e["action"] == "confirm"], "待确认 CONFIRM (听一下再决定, 默认不删)")
    table(words_auto, "自动删 AUTO (高置信, 默认删; 不想删就回复 保留 N)")
    table(pauses, "气口 AUTO (压缩停顿, 不是整段删除)")
    table([e for e in E if e["action"] == "keep"], "保留 KEEP (像真词, 默认不删; 想删就回复 确认 N)")
    txt = "\n".join(L)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
    return txt


_REPLY = re.compile(r"(全部确认|全确认|全删|all[- ]?confirm|approve[- ]?all|不删|保留|keep|不要删|确认|同意|删除|删|approve|cut|yes)"
                    r"\s*[:：]?\s*([\d\s,，、\-–~]*)", re.I)


def parse_reply(text):
    """Creator reply -> dict(approve={ids}, keep={ids}, all_confirm=bool).
    "确认 3,5,9 / 保留 7", "删 2-4 不删 6", "approve 3,5 keep 7", "全部确认"."""
    res = dict(approve=set(), keep=set(), all_confirm=False)
    for kw, nums in _REPLY.findall(text or ""):
        k = kw.lower().replace(" ", "-")
        if k in ("全部确认", "全确认", "全删", "all-confirm", "allconfirm", "approve-all", "approveall"):
            res["all_confirm"] = True
            continue
        ids = set()
        for a, b in re.findall(r"(\d+)\s*(?:[\-–~]\s*(\d+))?", nums):
            ids |= set(range(int(a), int(b or a) + 1))
        (res["keep"] if k in ("不删", "保留", "keep", "不要删") else res["approve"]).update(ids)
    return res


# ------------------------------------------------------------------ EDL io
def _load_edl(edl):
    if isinstance(edl, dict):
        return edl, None
    with open(edl, encoding="utf-8") as f:
        return json.load(f), os.path.abspath(edl)


def _source_path(edl, edl_path, media_path=None):
    p = media_path or edl["source"]["path"]
    if not os.path.isabs(p) and edl_path:
        cand = os.path.join(os.path.dirname(edl_path), p)
        if os.path.exists(cand):
            return cand
    return p


def _sha(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_edl(words, media_path=None, energy=None, ranges=None, profile=None, overrides=None, dropped=None,
              language=None, duration=None, info=None, id_offset=0):
    """EDL dict (no I/O): source, profile, settings, ranges, words, edits, default keep + timemap.
    id_offset: edit ids start at id_offset + 1 (recorded as ``id_offset`` when non-zero)."""
    st = settings(profile, overrides)
    W = load_words(words) if words and "n" not in words[0] else (words or [])
    dur = duration or (W[-1]["te"] + 0.5 if W else 0.0)
    rg = _norm_ranges(ranges) or [(0.0, round(dur, 3))]
    rg = [(max(0.0, a), min(dur, b)) for a, b in rg]
    edits = detect(W, ranges=rg, profile=st["profile"], overrides=overrides, dropped=dropped, energy=energy,
                   id_offset=id_offset)
    keep = keep_segments(edits, rg, words=W)
    info = info or {}
    edl = dict(version=VERSION, tool="vstudio.cleanup", source=dict(
        path=media_path or "", duration=round(dur, 3), has_video=bool(info.get("has_video")),
        fps=float(info.get("fps") or 0), size=info.get("size")),
        language=language or detect_language(W), profile=st["profile"],
        settings={k: v for k, v in st.items() if k != "profile"}, ranges=[list(r) for r in rg],
        words=[dict(w=w["w"], t=w["t"], te=w["te"], seg=w["seg"], end=w["end"]) for w in W],
        edits=edits, keep=[list(k) for k in keep], timemap=timemap(keep).to_list(),
        stats=dict(auto=sum(e["action"] == "auto" for e in edits), confirm=sum(e["action"] == "confirm" for e in edits),
                   keep=sum(e["action"] == "keep" for e in edits), source_s=round(sum(b - a for a, b in rg), 3),
                   auto_s=round(sum(b - a for a, b in keep), 3),
                   breaths=len(energy.breaths) if energy is not None else 0))
    if id_offset:
        edl["id_offset"] = int(id_offset)
    return edl


def _transcript_of(transcript, media_path, language, prompt, st):
    """(words, dropped, language) from a transcript (path/dict/list) or a fresh asr.transcribe."""
    tr = transcript
    if isinstance(tr, (str, os.PathLike)):
        with open(tr, encoding="utf-8") as f:
            tr = json.load(f)
    if tr is None:
        tr = asr.transcribe(media_path, language=language, prompt=prompt)
    dropped = []
    if isinstance(tr, dict):
        if st["hallucinations"] and tr.get("segments") and hasattr(asr, "drop_hallucinations"):
            tr = asr.drop_hallucinations(tr)            # appends to any "dropped" list transcribe() made
        dropped = list(tr.get("dropped") or [])
        language = language or tr.get("language")
    return load_words(tr), dropped, language


def analyze(media_path, transcript=None, ranges=None, language=None, profile=None, overrides=None, prompt=None,
            out="cleanup.json", review="cleanup_review.md", force=False, write=True, id_offset=0):
    """Analyse ``media_path`` -> EDL dict, written to ``out`` (+ review sheet ``review``).

    transcript: path / dict / list in any ``load_words`` shape; None = ``asr.transcribe`` (cached).
    ranges: [(a, b)] source seconds to clean (and keep); default the whole file. Several windows share one
    edit numbering. id_offset: ids start at id_offset + 1, so several clips' EDLs can be answered with ONE
    reply (clip 2 gets ``id_offset = len(edl1["edits"])``, ...).
    An existing different ``out`` is not overwritten unless force: the next free ``cleanup.N.json``
    is used (the creator may have edited the old one). Returns the EDL (``edl["_path"]`` = file)."""
    st = settings(profile, overrides)
    info = media.probe(media_path)
    if not info["has_audio"]:
        raise ValueError(f"{media_path}: no audio stream - nothing to clean")
    W, dropped, language = _transcript_of(transcript, media_path, language, prompt, st)
    rg = _norm_ranges(ranges)
    a0 = max(0.0, rg[0][0] - 1.0) if rg else 0.0
    a1 = rg[-1][1] + 1.0 if rg else None
    en = Energy.from_any(media_path, start=a0, end=a1)
    en.calibrate([w for w in W if not rg or any(a <= _mid(w) <= b for a, b in rg)] or W, st)
    info = dict(info, size=os.path.getsize(media_path))
    rel = os.path.relpath(os.path.abspath(media_path), os.path.dirname(os.path.abspath(out))) if write else media_path
    edl = build_edl(W, rel, en, rg, st["profile"], overrides, dropped, language, info["duration"], info, id_offset)
    if write:
        path = out
        if os.path.exists(out) and not force:
            old = _load_edl(out)[0]
            if _sha({k: v for k, v in old.items() if k != "_path"}) != _sha(edl):
                stem, ext = os.path.splitext(out)
                n = 2
                while os.path.exists(f"{stem}.{n}{ext}"):
                    n += 1
                path = f"{stem}.{n}{ext}"
                print(f"cleanup: {out} exists and differs -> writing {path} (use --force to overwrite)")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(edl, f, ensure_ascii=False, indent=1)
        if review:
            rv = review if path == out else os.path.splitext(path)[0] + "_review.md"
            review_sheet(edl, rv)
        edl["_path"] = os.path.abspath(path)
    return edl


# ------------------------------------------------------------------ sidecar
def write_sidecar(out, source, keep, words, language=None, fps=None, tag=None, path=None, **extra):
    """Write ``<out stem>.cleanup.json``, the sidecar ``verify`` reads, for ANY cut made outside ``apply``
    (a retouched / derived body cut by a workflow's own renderer, a sentence drop, ...).

    out: the cut file; source: the file it was cut from; keep: kept spans [(a, b)] in ``source`` seconds
    (played back to back = ``out``); words: the source-timeline words (any ``load_words`` shape) - those
    whose midpoint survives ``keep`` become ``expected`` (what verify must hear) and ``words`` (remapped to
    ``out`` seconds, for captions). tag: default = a hash of (source, keep, extra). extra: any JSON fields
    (decisions, ids, ...). path: default ``<out stem>.cleanup.json``. Returns the sidecar path."""
    keep = [(float(a), float(b)) for a, b in keep]
    tm = cut.TimeMap.from_segments(keep)
    W = _words(list(words or []))
    expected = [dict(w=w["w"], t=w["t"], te=w["te"]) for w in W if tm.to_final(_mid(w)) is not None]
    if tag is None:
        sig = json.dumps(dict(source=source, keep=[list(k) for k in keep], extra=extra), sort_keys=True, default=str)
        tag = hashlib.sha1(sig.encode()).hexdigest()[:8]
    d = dict(tool="vstudio.cleanup", version=VERSION, tag=tag, source=source, out=out,
             fps=float(fps) if fps else None, keep=[list(k) for k in keep], timemap=tm.to_list(),
             duration=round(tm.duration, 4), expected=expected, words=remap_words(expected, tm) if expected else [],
             language=language)
    for k, v in extra.items():
        d[k] = v
    side = path or os.path.splitext(out)[0] + ".cleanup.json"
    with open(side, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return side


# ------------------------------------------------------------------ apply
def _frame_grid(keep, F):
    """Kept spans snapped OUTWARD to whole frames (never into kept speech), merged. -> [(fa, fb)]."""
    out = []
    for a, b in keep:
        fa = int(np.floor(a * F + 1e-6))
        fb = int(np.ceil(b * F - 1e-6))
        if fb <= fa:
            continue
        if out and fa <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], fb))
        else:
            out.append((fa, fb))
    return out


def _render_audio(src, spans, xfade, path=None):
    """spans: [(s0, s1)] in SAMPLES (48 kHz) -> stereo float array of exactly sum(s1-s0) samples, with an
    equal-power ``xfade`` s crossfade centred on every join (length-neutral: each side borrows source
    audio from beyond its edge) and 5 ms fades at both ends."""
    h = max(1, int(round(xfade * SR / 2))) if xfade else 0
    clusters, cur = [], []
    for s in spans:
        if cur and (s[1] - cur[0][0] > 120 * SR or s[0] - cur[-1][1] > 30 * SR):
            clusters.append(cur)
            cur = []
        cur.append(s)
    if cur:
        clusters.append(cur)
    pieces = []
    for cl in clusters:
        a = max(0, cl[0][0] - h - SR // 10)
        start = float(f"{a / SR:.4f}")
        a = int(round(start * SR))
        need = cl[-1][1] + h + SR // 10 - a
        buf = decode_audio(src, sr=SR, channels=2, start=start or None, dur=need / SR + 0.05)
        if len(buf) < need:
            buf = np.concatenate([buf, np.zeros((need - len(buf), 2), np.float32)])

        def grab(s0, s1):
            i0, i1 = s0 - a, s1 - a
            x = buf[max(0, i0):max(0, i1)]
            if i0 < 0:
                x = np.concatenate([np.zeros((min(-i0, i1 - i0), 2), np.float32), x])
            return x
        for s0, s1 in cl:
            pieces.append((grab(s0, s1), grab(s0 - h, s0) if h else None, grab(s1, s1 + h) if h else None))
    out = np.concatenate([p[0] for p in pieces]) if pieces else np.zeros((0, 2), np.float32)
    if h:
        ang = np.linspace(0, np.pi / 2, 2 * h, dtype=np.float32)[:, None]
        fo, fi = np.cos(ang), np.sin(ang)
        J = 0
        for k in range(len(pieces) - 1):
            J += len(pieces[k][0])
            core_a, _, post_a = pieces[k]
            core_b, pre_b, _ = pieces[k + 1]
            if len(core_a) < h or len(core_b) < h:
                continue
            A = np.concatenate([core_a[-h:], post_a])
            B = np.concatenate([pre_b, core_b[:h]])
            out[J - h:J + h] = A * fo + B * fi
    f = min(len(out) // 2, int(0.005 * SR))
    if f:
        r = np.linspace(0, 1, f, dtype=np.float32)[:, None]
        out[:f] *= r
        out[-f:] *= r[::-1]
    if path:
        write_wav(path, out, SR)
    return out


def apply(edl, approve=(), keep=(), all_confirm=False, reply=None, extra_cuts=(), out=None, media_path=None,
          fps=None, crossfade=None, crf=14, force=False):
    """Cut the source of ``edl`` (path or dict) with the chosen decisions -> versioned output.

    Decisions: every ``auto`` edit + ``approve`` ids + (all_confirm: every ``confirm``) - ``keep`` ids;
    ``reply`` = the creator's text ("确认 3,5,9 / 保留 7", ``parse_reply``); extra_cuts = editor cuts
    [(a, b[, why])] in source seconds. Never modifies the EDL. out default:
    ``<edl dir>/<stem>.clean.<tag>.mp4`` (.wav for audio-only sources) where tag hashes the decisions,
    so re-applying the same decisions is a no-op and different ones never overwrite each other.
    Writes ``<out>.cleanup.json`` (decisions, keep, TimeMap, kept words for captions / verify).
    Returns dict(out, sidecar, keep, timemap (TimeMap), applied, tag, duration, reused)."""
    E, edl_path = _load_edl(edl)
    src = _source_path(E, edl_path, media_path)
    if not os.path.exists(src):
        raise FileNotFoundError(f"cleanup source not found: {src}")
    info = media.probe(src)
    if abs(info["duration"] - E["source"]["duration"]) > 0.1:
        raise SystemExit(f"cleanup: {src} is {info['duration']:.2f}s but the EDL was made from a "
                         f"{E['source']['duration']:.2f}s file - apply always cuts the ORIGINAL source, not a cut file")
    approve, keep = set(approve or ()), set(keep or ())
    if reply:
        r = parse_reply(reply)
        approve |= r["approve"]
        keep |= r["keep"]
        all_confirm = all_confirm or r["all_confirm"]
    known = {e["id"] for e in E["edits"]}
    bad = (approve | keep) - known
    if bad:
        raise ValueError(f"unknown edit ids {sorted(bad)} (1..{len(known)})")
    ids = applied_ids(E["edits"], approve, keep, all_confirm)
    xf = E["settings"].get("crossfade", COMMON["crossfade"]) if crossfade is None else crossfade
    segs = keep_segments(E["edits"], E["ranges"], approve, keep, all_confirm, extra_cuts,
                         E["settings"].get("min_piece"), words=E["words"])
    if not segs:
        raise ValueError("nothing left to keep")
    video = info["has_video"]
    F = Fraction(fps).limit_denominator(1001) if fps else (info["fps_q"] or Fraction(30)) if video else None
    if video:
        grid = _frame_grid(segs, F)
        secs = [(float(Fraction(a) / F), float(Fraction(b) / F)) for a, b in grid]
        spans = [(int(round(a * SR / F)), int(round(b * SR / F))) for a, b in grid]
    else:
        spans = [(int(round(a * SR)), int(round(b * SR))) for a, b in segs]
        merged = []
        for s in spans:
            if merged and s[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], s[1]))
            else:
                merged.append(s)
        spans = merged
        secs = [(a / SR, b / SR) for a, b in spans]
    sig = dict(src=E["source"], spans=spans, xf=xf, crf=crf, v=VERSION)
    tag = _sha(sig)[:8]
    base_dir = os.path.dirname(edl_path) if edl_path else os.getcwd()
    stem = os.path.splitext(os.path.basename(src))[0]
    if out is None:
        out = os.path.join(base_dir, f"{stem}.clean.{tag}{'.mp4' if video else '.wav'}")
    if edl_path and os.path.abspath(out) == edl_path:
        raise ValueError("refusing to overwrite the EDL")
    side = os.path.splitext(out)[0] + ".cleanup.json"
    tm = cut.TimeMap.from_segments(secs)
    res = dict(out=out, sidecar=side, keep=secs, timemap=tm, applied=ids, tag=tag, duration=tm.duration, reused=False)
    if not force and os.path.exists(out) and os.path.exists(side):
        try:
            with open(side, encoding="utf-8") as f:
                if json.load(f).get("tag") == tag:
                    res["reused"] = True
                    print(f"cleanup: {out} already has these decisions (tag {tag}) - reused")
                    return res
        except (OSError, ValueError):
            pass
    tmp = tempfile.mkdtemp(prefix="vstudio_cleanup_")
    try:
        wav = os.path.join(tmp, "a.wav")
        _render_audio(src, spans, xf, wav)
        part = out + ".part" + os.path.splitext(out)[1]
        if video:
            vtmp = os.path.join(tmp, "v.mov")
            cut.cut_segments(src, secs, vtmp, fps=F, crf=crf, tmpdir=os.path.join(tmp, "seg"))
            ac = ["-c:a", "pcm_s16le"] if out.lower().endswith((".mov", ".mkv")) else \
                ["-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2"]
            media.run(["ffmpeg", "-y", "-i", vtmp, "-i", wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", *ac,
                       "-movflags", "+faststart", part])
        elif out.lower().endswith(".wav"):
            shutil.copyfile(wav, part)
        else:
            media.run(["ffmpeg", "-y", "-i", wav, "-c:a", "aac", "-b:a", "192k", part])
        os.replace(part, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    kept_ids = set(ids)
    cut_spans = [(e["t0"], e["t1"]) for e in E["edits"] if e["id"] in kept_ids] + \
        [(float(c[0]), float(c[1])) for c in extra_cuts or ()]
    W = [w for w in load_words(E["words"]) if any(a <= _mid(w) <= b for a, b in E["ranges"])]
    for e in E["edits"]:
        if e["id"] in kept_ids and e.get("patch"):
            for w in W:
                if abs(w["t"] - e["patch"][0]) < 0.002:
                    w["t"] = e["patch"][1]
    expected = [w for w in W if not any(a <= _mid(w) <= b for a, b in cut_spans)]
    write_sidecar(out, src, secs, expected, E.get("language"), fps=F, tag=tag, path=side, edl=edl_path,
                  applied=ids, approve=sorted(approve), keep_ids=sorted(keep), all_confirm=bool(all_confirm),
                  extra_cuts=[list(c) for c in extra_cuts or ()], crossfade=xf)
    print(f"cleanup: {len(ids)} edits applied, {sum(b - a for a, b in E['ranges']):.1f}s -> {tm.duration:.1f}s -> {out}")
    return res


# ------------------------------------------------------------------ verify
def _units(words):
    out = []
    for w in words:
        for m in re.finditer(r"[a-z0-9]+|[^a-z0-9]", norm(w["w"])):
            out.append((m.group(0), w["t"]))
    return out


def content_check(expected, got, fillers=None, min_chars=2):
    """Missing / changed content between the words that SHOULD remain and a fresh ASR of the cut.
    Fillers are ignored on both sides; a lone CJK character (usually ASR noise) is not flagged; a
    1-2 unit same-length swap counts as a homophone. Returns [{"kind", "text", "got", "t"}] (t = the
    expected word's time). Port of talkinghead ``filler_policy.content_check``."""
    fl = {norm(f) for f in (fillers if fillers is not None else _all_fillers())}
    E = [(u, t) for u, t in _units(load_words(expected)) if u not in fl]
    G = [u for u, _ in _units(load_words(got)) if u not in fl]
    sm = difflib.SequenceMatcher(None, [u for u, _ in E], G, autojunk=False)
    flags = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op not in ("delete", "replace"):
            continue
        miss = [u for u, _ in E[i1:i2]]
        heavy = sum(2 if re.match(r"[a-z0-9]", u) else len(u) for u in miss)
        if heavy < min_chars:
            continue
        if op == "replace" and abs((i2 - i1) - (j2 - j1)) <= 1 and (i2 - i1) <= 2:
            continue
        flags.append(dict(kind="missing" if op == "delete" else "changed",
                          text=" ".join(miss) if any(re.match(r"[a-z0-9]", u) for u in miss) else "".join(miss),
                          got="".join(G[j1:j2]), t=round(E[i1][1], 2)))
    return flags


def verify(target, got=None, transcriber=None, language=None, prompt=None, raise_on_fail=False, write=True):
    """Re-ASR a cleaned output and check nothing but the cut edits went missing.

    target: the output path (its ``<out>.cleanup.json`` sidecar is read) or an ``apply`` result.
    got: transcript of the output (any shape) - else ``transcriber(path)`` - else ``asr.transcribe``.
    Returns dict(ok, missing=[{kind, text, got, t_src, t_out}], leftovers=[{text, t_out, why}]) and writes
    ``<out>.verify.json``. raise_on_fail -> RuntimeError listing the lost words."""
    out = target["out"] if isinstance(target, dict) else target
    side = os.path.splitext(out)[0] + ".cleanup.json"
    with open(side, encoding="utf-8") as f:
        S = json.load(f)
    if got is None:
        got = transcriber(out) if transcriber else asr.transcribe(out, language=language or S.get("language"),
                                                                  prompt=prompt)
    G = load_words(got)
    tm = cut.TimeMap(S["timemap"])
    flags = content_check(S["expected"], G)
    for fl in flags:
        fl["t_src"] = fl.pop("t")
        t = tm.to_final(fl["t_src"], "nearest")
        fl["t_out"] = None if t is None else round(t, 2)
    left = []
    for k, w in enumerate(G):
        if w["n"] in HESITATION:
            left.append(dict(text=w["w"], t_out=w["t"], why="hesitation still in the cut"))
        if k + 1 < len(G) and w["n"] == G[k + 1]["n"] and w["n"] not in REPEAT_OK and \
                not (len(w["n"]) == 1 and w["n"] in cut.REDUP_ZH):
            left.append(dict(text=w["w"] * 2, t_out=w["t"], why="immediate repeat still in the cut"))
    rep = dict(ok=not flags, out=out, missing=flags, leftovers=left, expected_words=len(S["expected"]),
               got_words=len(G))
    if write:
        with open(os.path.splitext(out)[0] + ".verify.json", "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    if flags:
        msg = "; ".join(f"'{x['text']}' @src {x['t_src']:.2f}s / out {x['t_out']}s" for x in flags)
        print(f"cleanup verify: {len(flags)} span(s) LOST - {msg}. Keep the edit that covers it "
              "(apply --keep N) and re-apply.")
        if raise_on_fail:
            raise RuntimeError(f"cleanup verify failed: {msg}")
    else:
        print(f"cleanup verify: OK - all {len(S['expected'])} kept words are in {os.path.basename(out)}")
    return rep


# ------------------------------------------------------------------ CLI
def _parse_time(s):
    s = s.strip()
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        v = 0.0
        for p in parts:
            v = v * 60 + p
        return v
    return float(s)


def parse_ranges(text):
    """"12.5-80,1:40-2:10" -> [(12.5, 80.0), (100.0, 130.0)]."""
    out = []
    for part in (text or "").split(","):
        if part.strip():
            a, b = re.split(r"(?<=\d)\s*-\s*(?=\d)", part.strip(), maxsplit=1)
            out.append((_parse_time(a), _parse_time(b)))
    return out


def _ids(text):
    return parse_reply("approve " + (text or ""))["approve"] if text else set()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.cleanup", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="detect edits -> cleanup.json + cleanup_review.md")
    a.add_argument("media")
    a.add_argument("--transcript", help="vstudio.asr JSON / whisper JSON / word list (default: transcribe)")
    a.add_argument("--ranges", help="only these source spans, e.g. 12.5-80,1:40-2:10")
    a.add_argument("--profile", choices=list(PROFILES), help="default persona cleanup.profile or standard")
    a.add_argument("--lang", help="language for ASR (zh / en)")
    a.add_argument("--prompt", help="ASR prompt with domain terms")
    a.add_argument("--out", default="cleanup.json")
    a.add_argument("--review", default="cleanup_review.md")
    a.add_argument("--force", action="store_true", help="overwrite an existing different EDL")
    r = sub.add_parser("review", help="print the review sheet of an EDL")
    r.add_argument("edl")
    r.add_argument("--out", help="also write it here")
    p = sub.add_parser("apply", help="cut the source with the decisions -> versioned output")
    p.add_argument("edl")
    p.add_argument("--approve", help="confirm ids to cut too: 3,5,9 or 3-6")
    p.add_argument("--keep", help="auto ids NOT to cut: 7")
    p.add_argument("--all-confirm", action="store_true", help="cut every confirm edit as well")
    p.add_argument("--reply", help='creator reply text, e.g. "确认 3,5,9 / 保留 7"')
    p.add_argument("--cut", help="extra editor cuts in source seconds: 12.3-12.9,40-41.2")
    p.add_argument("--out")
    p.add_argument("--media", help="source media path (default: the EDL's)")
    p.add_argument("--fps", type=float)
    p.add_argument("--force", action="store_true", help="re-render even if the output exists")
    v = sub.add_parser("verify", help="re-ASR the output and flag lost content words (exit 1)")
    v.add_argument("output")
    v.add_argument("--transcript", help="transcript of the output (default: transcribe it)")
    v.add_argument("--lang")
    v.add_argument("--prompt")
    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        edl = analyze(args.media, transcript=args.transcript, ranges=parse_ranges(args.ranges) or None,
                      language=args.lang, profile=args.profile, prompt=args.prompt, out=args.out,
                      review=args.review, force=args.force)
        s = edl["stats"]
        print(f"cleanup: {s['auto']} auto, {s['confirm']} to confirm, {s['keep']} kept as real words; "
              f"{s['source_s']:.1f}s -> {s['auto_s']:.1f}s with auto edits -> {edl['_path']}")
        print(review_sheet(edl))
        return 0
    if args.cmd == "review":
        print(review_sheet(args.edl, args.out))
        return 0
    if args.cmd == "apply":
        extra = parse_ranges(args.cut) if args.cut else ()
        res = apply(args.edl, approve=_ids(args.approve), keep=_ids(args.keep), all_confirm=args.all_confirm,
                    reply=args.reply, extra_cuts=extra, out=args.out, media_path=args.media, fps=args.fps,
                    force=args.force)
        print(res["out"])
        return 0
    if args.cmd == "verify":
        rep = verify(args.output, got=args.transcript, language=args.lang, prompt=args.prompt)
        for x in rep["leftovers"]:
            print(f"  leftover @{x['t_out']:.2f}s '{x['text']}': {x['why']}")
        return 0 if rep["ok"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
