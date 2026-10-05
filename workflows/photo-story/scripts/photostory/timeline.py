"""Narration timing -> units (one TTS clip each), shots, bilingual subtitle cues, section bounds.

SCRIPT item = (section_index, [(en, zh), ...], [(src, weight, motion, opts), ...])
  one item = one TTS clip; each (en, zh) = one subtitle cue; shots split the item's slot by weight.
timing.json (written by tts.py) = [{i, path, dur, chunks: [{start, end}, ...]}, ...]
Without timing.json, durations are ESTIMATED (silent) so you can preview layout before paying for TTS.
"""
import json
import os
import re

from vstudio import audio, media

from .transitions import TRD

PACING = dict(gap=0.32, sec_gap=0.75, tail=2.8, lead=0.3, end_fade=1.8)


def tts_dir(C):
    return C.path((getattr(C.spec, "TTS", {}) or {}).get("dir", "tts"))


def estimate(text_en, text_zh):
    words = len(re.findall(r"[\w’']+", (text_en or "").replace("**", "")))
    if words:
        return 0.35 + words / 2.6
    return 0.35 + len(re.sub(r"\W", "", text_zh or "")) / 4.2


def load_timing(C):
    path = os.path.join(tts_dir(C), "timing.json")
    if os.path.exists(path):
        data = {d["i"]: d for d in json.load(open(path))}
        for i, (_, chunks, _) in enumerate(C.spec.SCRIPT):     # script edited since TTS -> stale unit
            if i in data and len(data[i]["chunks"]) != len(chunks):
                del data[i]
        missing = [i for i in range(len(C.spec.SCRIPT)) if i not in data]
        if not missing:
            return data, True
        print(f"! timing.json lacks units {missing} - estimating those (silent)")
    else:
        data = {}
        print("! no timing.json - estimating durations, video will be silent (run tts.py first)")
    for i, (sec, chunks, _) in enumerate(C.spec.SCRIPT):
        if i in data:
            continue
        t, ch = 0.0, []
        for en, zh in chunks:
            d = estimate(en, zh)
            ch.append(dict(start=round(t, 3), end=round(t + d, 3)))
            t += d + 0.22
        data[i] = dict(i=i, path=None, dur=max(0.8, t - 0.22), chunks=ch)
    return data, False


class Timeline:
    def __init__(self, C, timing):
        pace = dict(PACING)
        pace.update(getattr(C.spec, "PACING", {}) or {})
        self.pace = pace
        script = C.spec.SCRIPT
        t = pace["lead"]
        self.units, self.shots, self.subs = [], [], []
        for i, (sec, chunks, shotlist) in enumerate(script):
            tm = timing[i]
            nxt = script[i + 1][0] if i + 1 < len(script) else None
            slot = tm["dur"] + (pace["tail"] if nxt is None else pace["sec_gap"] if nxt != sec else pace["gap"])
            self.units.append(dict(start=t, path=tm["path"], sec=sec, dur=tm["dur"], i=i))
            ch = tm["chunks"]
            for k, (en, zh) in enumerate(chunks):
                st = t + ch[k]["start"]
                en_t = t + (ch[k + 1]["start"] if k + 1 < len(ch) else min(ch[k]["end"] + 0.45, slot - 0.05))
                self.subs.append(dict(en=en, zh=zh, start=st, end=en_t, sec=sec))
            wsum = sum(s[1] for s in shotlist)
            a = t
            for src, w, mo, opt in shotlist:
                d = slot * w / wsum
                self.shots.append(dict(src=src, start=a, end=a + d, motion=mo, sec=sec, **(opt or {})))
                a += d
            t += slot
        self.total = t
        self.shots[0]["start"] = 0.0
        n = len(C.SECTIONS)
        b = []
        for s in range(n):
            st = [u["start"] for u in self.units if u["sec"] == s]
            b.append(min(st) if st else (b[-1] if b else 0.0))
        b[0] = 0.0
        b.append(self.total)
        self.sec_bounds = b
        for k, sh in enumerate(self.shots):
            sh["tr"] = sh.get("tr", "fade") if k else None
            sh["trd"] = sh.get("trd", TRD.get(sh["tr"], 0.4)) if k else 0
        for k, sh in enumerate(self.shots):    # each shot keeps rendering until the next transition ends
            sh["tail"] = self.shots[k + 1]["trd"] if k + 1 < len(self.shots) else 99

    def section_at(self, gt):
        return max(i for i in range(len(self.sec_bounds) - 1) if self.sec_bounds[i] <= gt)

    def summary(self):
        return f"total {self.total:.1f}s ({self.total / 60:.1f} min), {len(self.shots)} shots, {len(self.subs)} subtitle cues"


def place_voice(C, T, t0, t1, out):
    """Narration track for [t0, t1): every voice unit at its timeline start -> 48 kHz stereo wav
    (digital silence when there is no timing.json). Returns out."""
    dur = t1 - t0
    ins, flt = [], []
    for u in T.units:
        if not u["path"] or u["start"] >= t1 or u["start"] + u["dur"] <= t0:
            continue
        ms = int(round((u["start"] - t0) * 1000))
        trim = f"atrim=start={-ms / 1000:.3f}," if ms < 0 else ""
        flt.append(f"[{len(ins) // 2}:a]aresample={audio.SR},{trim}asetpts=PTS-STARTPTS,"
                   f"adelay={max(ms, 0)}:all=1,apad[a{len(flt)}]")
        ins += ["-i", C.path(u["path"])]
    if not flt:
        return audio.silence(dur, out)
    n = len(flt)
    flt.append("".join(f"[a{k}]" for k in range(n)) +
               f"amix=inputs={n}:normalize=0,atrim=0:{dur:.3f},aformat=channel_layouts=stereo[vo]")
    media.run(["ffmpeg", "-y", *ins, "-filter_complex", ";".join(flt), "-map", "[vo]",
               "-ar", str(audio.SR), "-ac", "2", "-c:a", "pcm_s16le", out])
    return out
