#!/usr/bin/env python3
"""Automatic 气口 / stumble remover for conversational speech (Chinese-first, works on
code-switched zh/en). Finds dead air, false starts, stutters and filler-only breaths
inside keep-windows and returns cut intervals in SOURCE seconds.

This is the most reliable automatic disfluency pass in video-studio; phase 2 will
promote it to lib/vstudio. Keep the algorithm intact when editing; tune constants.

Why it works
------------
Whisper's word timestamps abut each other, so they cannot show pauses. Silence
comes from the audio energy (20ms RMS frames, threshold set per recording at
floor + 0.30 * (speech - floor), floor = 8th percentile dB, speech = 70th); the
transcript is only used to spot *what* to cut (a restart, a repeated phrase, a
lone 嗯). Every cut edge is then moved to the quietest frame between the two
neighbouring words' midpoints (Audio.boundary), so a join never lands mid-syllable
and never eats a kept word (subtitles keep a word by its midpoint).

Rules, most conservative first
------------------------------
  pause    silence > PAUSE_MIN (0.60s) with no word midpoint inside it -> cut it
           but keep PAUSE_EDGE (0.18s) of silence on each side (~0.36s breath).
           Soft onsets (f, s, sh, q, z, t) sit under the threshold, hence the
           word-midpoint guard.
  restart  segment A, then B starting with A's text within 1.5s
           ("我觉得这是" / "我觉得这是个trade off") -> drop A
  repeat   the same 1..6-word unit (2..10 chars) said twice back to back
           ("以后 以后 以后") -> keep only the last copy. A one-word repeat across
           a segment break is NOT cut (Chinese repeats across a sentence break on
           purpose: 「没有很重要｜重要的是…」); EMPHASIS doublings (非常非常, 一半一半)
           are whitelisted.
  filler   a whole segment that is only a FILLERS word (嗯 / 啊 / 然后呢 / 怎么说呢 ...)
  edit     optional editor cuts passed as `extra`: [[from_onset, next_kept_onset, why], ...]
           (e.g. from a human or LLM dialogue-editor pass). Both edges snap to word
           boundaries; an editor cut that would start on the onset an auto
           repeat/restart cut keeps is dropped (the auto cut wins).
Cuts shorter than MIN_CUT (0.25s) are ignored; overlapping cuts merge. Expect ~3%
of body time from the auto rules, ~10% with an editor pass.

API (used by build_clips.py when clips.json has "auto_trim": true)
--------------------------------------------------------------------
  audio = Audio("audio16k.wav")                 # 16 kHz mono 16-bit wav
  segs  = json.load(open("audio16k.json"))["segments"]   # whisper, word_timestamps=True
  cuts  = find_cuts(audio, segs, lo, hi, extra=None)     # [[a, b, why], ...] source s
  keep  = split_window(lo, hi, cuts)            # [[a, b], ...] keep-intervals (>=0.4s)

Language notes: FILLERS and EMPHASIS are Mandarin lists; for another language
replace them (the energy/pause and restart/repeat logic is language-agnostic).
The persona keys audio.pause_threshold / pause_squeeze are NOT read here (they
belong to the talking-head pause squeezer); these constants were tuned on
multi-person call audio.

Usage (standalone report, read before building):
  find_disfluencies.py work/audio16k.wav work/audio16k.json --windows 124.58-410.3,527-560.9
  find_disfluencies.py ... --extra editor_cuts.json --json work/cuts.json
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, re, wave
import numpy as np

PAUSE_MIN = 0.60     # silence longer than this inside a window is a pause
PAUSE_KEEP = 0.25    # (legacy, unused: the kept breath is 2 * PAUSE_EDGE)
PAUSE_EDGE = 0.18    # silence kept on each side of a cut pause
MIN_CUT = 0.25
SNAP = 0.12
FRAME = 0.02

FILLERS = {"嗯", "啊", "呃", "额", "哎", "诶", "哦", "然后呢", "然后", "就是", "就是说", "那个",
           "怎么说呢", "怎么说", "对吧"}
# reduplication that is emphasis, not a stutter
EMPHASIS = {"一半", "合作", "非常", "特别", "真的", "一点", "好好", "越来", "谢谢", "慢慢", "常常", "天天", "最最"}

_PUNCT = re.compile(r"[\s,，。.!?！？、…]+")


def norm(s):
    return _PUNCT.sub("", s)


def load_energy(wav_path):
    w = wave.open(wav_path)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    hop = int(sr * FRAME)
    n = len(x) // hop
    fr = x[:n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-6)
    return db


class Audio:
    def __init__(self, wav_path):
        self.db = load_energy(wav_path)
        # silence threshold relative to this recording's own floor and speech level
        floor, speech = np.percentile(self.db, 8), np.percentile(self.db, 70)
        self.thr = floor + 0.30 * (speech - floor)

    def idx(self, t):
        return int(round(t / FRAME))

    def boundary(self, t, words, reach=0.30):
        """Cut point for an edge near a word boundary. Whisper's word times
        abut and drift, and the quietest frame near t can sit INSIDE a kept
        word (「去迭代」 lost its 代). So find the boundary between the two
        words around t and only search between their midpoints, on a 60ms
        smoothed energy, so a single unvoiced consonant cannot win."""
        if not words:
            return self.snap(t)
        starts = [w["s"] for w in words]
        import bisect
        k = bisect.bisect_left(starts, t)
        cands = [j for j in (k - 1, k, k + 1) if 0 < j < len(words)]
        if not cands:
            return self.snap(t)
        j = min(cands, key=lambda j: abs(words[j]["s"] - t))
        if abs(words[j]["s"] - t) > reach:
            return self.snap(t)
        prev, nxt = words[j - 1], words[j]
        # stay clear of both words' midpoints (subtitles keep a word by its
        # midpoint): late in the word before, early in the word after
        lo = prev["s"] + 0.60 * (prev["e"] - prev["s"])
        hi = nxt["s"] + 0.35 * (nxt["e"] - nxt["s"])
        a, b = self.idx(lo), self.idx(hi)
        if b <= a:
            return words[j]["s"]
        sm = np.convolve(self.db, np.ones(3) / 3, mode="same")
        return (a + int(np.argmin(sm[a:b + 1]))) * FRAME

    def snap_back(self, t, reach=0.15):
        """Quietest frame at or just BEFORE t. For editor cuts, where t is a
        word onset: searching forward could land inside that word."""
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
    """Every word in the recording, sorted, cached per transcript."""
    key = id(segs)
    if key not in _AW:
        ws = [{"t": norm(w["word"]), "s": w["start"], "e": w["end"]}
              for s in segs for w in s.get("words", []) if norm(w["word"])]
        ws.sort(key=lambda w: w["s"])
        _AW[key] = ws
    return _AW[key]


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
    cuts = []

    # pause: long silence, keep a short breath of it. Soft onsets (f, q, s,
    # sh, z, t) sit under the silence threshold, so a pause is only trusted if
    # no word's midpoint falls inside it, and the cut keeps PAUSE_EDGE of
    # silence on each side instead of being snapped toward the edge.
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

    # filler-only segment
    for s in inside:
        if norm(s["text"]) in FILLERS:
            cuts.append((s["start"], s["end"], f"filler:{norm(s['text'])}"))

    # restart: A then B that starts with A (or B == A)
    for A, B in zip(inside, inside[1:]):
        ta, tb = norm(A["text"]), norm(B["text"])
        if len(ta) >= 2 and tb.startswith(ta) and B["start"] - A["end"] < 1.5:
            cuts.append((A["start"], B["start"], f"restart:{ta}"))

    # repeat: the same run of words said twice back to back
    W = words_in(segs, lo, hi)
    i = 0
    while i < len(W):
        hit = None
        for n in range(1, 7):                      # unit of n words
            if i + 2 * n > len(W):
                break
            u1 = "".join(w["t"] for w in W[i:i + n])
            u2 = "".join(w["t"] for w in W[i + n:i + 2 * n])
            if u1 == u2 and 2 <= len(u1) <= 10 and u1 not in EMPHASIS \
                    and W[i + n]["s"] - W[i + n - 1]["e"] < 1.2:
                # a one-word repeat across a sentence break is usually real
                # speech ("没有很重要 | 重要的是..."), so only trust it inside
                # one segment unless the word is long enough to be a restart
                cross = W[i]["seg"] != W[i + n]["seg"]
                if n == 1 and cross:
                    continue
                hit = n
        if hit:
            n = hit
            k = i + n
            # swallow a third, fourth copy too: keep only the last one
            while k + n <= len(W) and "".join(w["t"] for w in W[k:k + n]) == \
                    "".join(w["t"] for w in W[i:i + n]):
                k += n
            last = k - n
            cuts.append((W[i]["s"], W[last]["s"], "repeat:" + "".join(w["t"] for w in W[i:i + n])))
            i = k
        else:
            i += 1

    # snap to quiet frames, clip into the window, merge
    snapped = []
    # word-level editor cuts: [from word onset, next kept word onset)
    AW = all_words(segs)
    # an auto repeat/restart cut ends on the onset of the copy it keeps; an
    # editor cut starting on that same onset removes the kept copy too, and
    # 「自己自己去做」 plays as 「去做」. The auto cut wins.
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
        if why == "pause":
            pass            # already inside verified silence, with margin
        else:
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
    """Keep-intervals of [lo, hi] after removing cuts. Tiny slivers between two
    cuts are dropped into the cut rather than becoming a 0.2s piece."""
    out, cur = [], lo
    for a, b, _ in cuts:
        if a - cur >= min_piece:
            out.append([round(cur, 3), round(a, 3)])
        cur = b
    if hi - cur >= min_piece:
        out.append([round(cur, 3), round(hi, 3)])
    return out


def main():
    ap = argparse.ArgumentParser(description="Report the stumbles/pauses find_cuts() would remove.")
    ap.add_argument("wav", help="16 kHz mono wav of the recording")
    ap.add_argument("whisper", help="whisper JSON with word timestamps")
    ap.add_argument("--windows", required=True, help="a-b,a-b in source seconds")
    ap.add_argument("--extra", default=None, help="editor cuts JSON: [[from, to, why], ...]")
    ap.add_argument("--json", default=None, help="also write {window: cuts} here")
    args = ap.parse_args()
    audio = Audio(args.wav)
    segs = json.load(open(args.whisper, encoding="utf-8"))["segments"]
    extra = json.load(open(args.extra, encoding="utf-8")) if args.extra else None
    total = saved = 0
    report = {}
    for w in args.windows.split(","):
        lo, hi = (float(v) for v in w.split("-"))
        cuts = find_cuts(audio, segs, lo, hi, extra)
        report[w] = cuts
        total += hi - lo
        for a, b, why in cuts:
            saved += b - a
            print(f"{a:8.2f}-{b:8.2f} {b - a:5.2f}s  {why}")
    print(f"window {total:.0f}s, cut {saved:.1f}s ({saved / total:.0%}), thr {audio.thr:.1f}dB")
    if args.json:
        json.dump(report, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
