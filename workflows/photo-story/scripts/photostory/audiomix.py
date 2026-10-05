"""Audio for a render window [t0, t1): narration + video-clip sound + music bed, with ducking.

Video shots (``v<clip>``) can keep their own sound:
    ("vIMG_1234", 1, "still", dict(audio="keep", gain=0))    # foreground: the music ducks under it
    ("vIMG_1234", 1, "still", dict(audio="duck", gain=-3))   # ambience: ducks under the narration
    audio="mute" (default) = silent clip, as before.
Levels: a kept clip is set to CLIP_LUFS (default persona audio.voice_lufs -16 + 0), an ambient clip to
AMBIENT_LUFS (-26), then ``gain`` dB. Ducking (one-pole attack/release on the stem's 10 ms RMS):
music under narration = BGM_DUCK (narration mode, as before), music under kept clips = CLIP_DUCK (-10),
ambient clips under narration = AMBIENT_DUCK (-12). Clip sound fades with the picture transitions.
The final mix gets a two-pass loudnorm to the platform / persona LUFS and true peak.
"""
import os

import numpy as np

from vstudio import audio, media
from vstudio.config import persona

from .shots import parse_src

SR = audio.SR


def _db(g):
    return 10 ** (np.asarray(g, np.float32) / 20)


def duck_curve(stem, duck_db, n, attack=0.08, release=0.40, threshold_db=-42.0):
    """Per-sample gain (n,) that dips by ``duck_db`` while ``stem`` is active (absolute RMS threshold,
    so stems that are digital silence between clips work)."""
    if not duck_db or stem is None or not np.any(stem):
        return np.ones(n, np.float32)
    env, hop = audio.rms_envelope(stem, SR, hop=0.01, win=0.03)
    tgt = np.where(env > threshold_db, float(duck_db), 0.0)
    a_k, r_k = 1 - np.exp(-hop / attack), 1 - np.exp(-hop / release)
    cur, curve = 0.0, np.empty(len(tgt), np.float32)
    for i, x in enumerate(tgt):
        cur += (x - cur) * (a_k if x < cur else r_k)
        curve[i] = cur
    shift = int(round(attack / hop))          # look-ahead: the dip starts with the sound, not after it
    curve = np.concatenate([curve[shift:], np.full(shift, curve[-1] if len(curve) else 0.0)])
    t = np.arange(n) / SR
    return _db(np.interp(t, np.arange(len(curve)) * hop + 0.015, curve))


def clip_sounds(C, T):
    """[{path, start, dur, mode, gain, fade_in, fade_out, src}] for video shots with audio keep/duck."""
    out = []
    for k, sh in enumerate(T.shots):
        mode = str(sh.get("audio", "mute")).lower()
        if mode in ("mute", "none", "off", "false") or parse_src(C, sh["src"])[0] != "video":
            continue
        if mode not in ("keep", "duck"):
            raise ValueError(f"shot {sh['src']}: audio= must be keep | duck | mute, got {mode!r}")
        src = C.find_video(parse_src(C, sh["src"])[1])
        if not media.probe(src)["has_audio"]:
            print(f"! {sh['src']}: audio={mode} but the clip has no sound")
            continue
        nxt = T.shots[k + 1]["trd"] if k + 1 < len(T.shots) else 0.0
        fi = max(0.08, sh.get("trd") or 0.0)
        out.append(dict(src=src, shot=sh["src"], start=sh["start"], dur=sh["end"] - sh["start"] + nxt, mode=mode,
                        gain=float(sh.get("gain", 0) or 0), off=float(sh.get("off", 0.0)),
                        speed=float(sh.get("speed", 1.0)), fade_in=fi if k else 0.02, fade_out=max(0.12, nxt)))
    return out


def _clip_wav(C, c, cache):
    tag = f"{os.path.basename(c['src'])}_{c['off']}_{c['speed']}_{c['dur']:.3f}_{c['fade_in']:.2f}_{c['fade_out']:.2f}"
    out = os.path.join(cache, "clipaudio_" + "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in tag) + ".wav")
    if not os.path.exists(out):
        af = [media.atempo_chain(c["speed"])] if abs(c["speed"] - 1) > 1e-3 else []
        af += [f"aresample={SR}", f"apad=whole_dur={c['dur']:.3f}", f"atrim=0:{c['dur']:.3f}",
               f"afade=t=in:d={c['fade_in']:.3f}", f"afade=t=out:st={max(0, c['dur'] - c['fade_out']):.3f}:d={c['fade_out']:.3f}"]
        media.run(["ffmpeg", "-y", "-ss", f"{c['off']:.3f}", "-t", f"{c['dur'] * c['speed'] + 0.2:.3f}", "-i", c["src"],
                   "-vn", "-af", ",".join(a for a in af if a), "-ac", "2", "-c:a", "pcm_s16le", out])
    return out


def _level(x, path, target):
    m = audio.measure_loudness(path)
    if np.isfinite(m["input_i"]) and m["input_i"] > -70:
        return x * _db(target - m["input_i"])
    return x


def _place(dst, x, i0):
    i, j = max(0, i0), min(len(dst), i0 + len(x))
    if j > i:
        dst[i:j] += x[i - i0:j - i0]


def mix(C, T, t0, t1, out, voice_wav=None, music=None, music_mode=False):
    """Write the final mix for [t0, t1) to ``out`` (48 kHz stereo wav, loudnorm'd to C.LUFS / C.TP).
    voice_wav: narration stem for the window (place_voice) or None; music: BGM path or None."""
    pa = persona().get("audio") or {}
    sp = lambda k, d: getattr(C.spec, k, d)
    N = int(round((t1 - t0) * SR))
    mixbuf = np.zeros((N, 2), np.float32)
    voice = None
    if voice_wav:
        v = audio.decode_audio(voice_wav)[:N]
        if np.any(v):
            voice = np.zeros((N, 2), np.float32)
            voice[:len(v)] = _level(v, voice_wav, float(pa.get("voice_lufs", -16)))
            mixbuf += voice
    keep = np.zeros((N, 2), np.float32)
    amb = np.zeros((N, 2), np.float32)
    clips = clip_sounds(C, T)
    for c in clips:
        if c["start"] >= t1 or c["start"] + c["dur"] <= t0:
            continue
        p = _clip_wav(C, c, C.cache_dir)
        x = audio.decode_audio(p)
        tgt = float(sp("CLIP_LUFS", pa.get("voice_lufs", -16))) if c["mode"] == "keep" else float(sp("AMBIENT_LUFS", -26))
        x = _level(x, p, tgt) * _db(c["gain"])
        _place(keep if c["mode"] == "keep" else amb, x, int(round((c["start"] - t0) * SR)))
    if np.any(amb):
        mixbuf += amb * duck_curve(voice, float(sp("AMBIENT_DUCK", -12)), N)[:, None]
    mixbuf += keep
    if music:
        mstart = (T.m0 if music_mode else 0.0) + t0
        m = audio.decode_audio(music, start=mstart or None)
        if len(m) == 0:
            m = np.zeros((N, 2), np.float32)
        m = np.tile(m, (int(np.ceil(N / len(m))), 1))[:N]
        mm = audio.measure_loudness(music)
        lev = float(T.cfg["lufs"]) if music_mode else float(sp("BGM_LUFS", None) or pa.get("music_lufs", -30))
        if np.isfinite(mm["input_i"]):
            m *= _db(lev - mm["input_i"])
        t = t0 + np.arange(N) / SR
        g = np.ones(N, np.float32)
        fin = (0.8 if mstart > 0 else 0.0) if music_mode else 2.0
        fout = T.pace["end_fade"] if music_mode else 3.5
        if fin and t0 < fin:
            g *= np.clip(t / fin, 0, 1)
        g *= np.clip((T.total - t) / max(fout, 1e-3), 0, 1) if music_mode else np.clip((t1 - t) / fout, 0, 1)
        if not music_mode:
            g *= duck_curve(voice, float(sp("BGM_DUCK", 0) or 0), N)
        g *= duck_curve(keep, float(sp("CLIP_DUCK", -10)), N)
        mixbuf += m * g[:, None]
    tmp = out + ".pre.wav"
    audio.write_wav(tmp, mixbuf, SR)
    if np.any(mixbuf):
        audio.loudnorm_2pass(tmp, out, lufs=C.LUFS, tp=C.TP)
        os.remove(tmp)
    else:
        os.replace(tmp, out)
    return out, clips
