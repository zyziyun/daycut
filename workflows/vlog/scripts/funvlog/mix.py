"""Audio for the fun travel vlog: speech stem, looped music bed ducked under speech, SFX cue sheet, loudness.

    voice stem  speech shots' own audio placed at their timeline positions (10 ms fades at every edit)
    music bed   audio.loop_bed (crossfaded loops, starts at the analysed downbeat, fades out at the end)
    mix         audio.mix_bed(voice, bed): music at ``music_lufs`` (-19, music-led montage), voice at
                persona audio.voice_lufs (-16), music ducked ``duck_db`` (-12) while anyone speaks
    SFX         audio.cue_sheet_for(...) -> render_cue_sheet, summed on top
    final       two-pass loudnorm to the platform profile (LUFS / true peak)
    accent      ``keep_audio`` shots' native sound, each piece at voice_lufs + gain_db (-8), under the bed
    no-music    voice + accents + SFX with the SAME gain as the final mix (A13: a re-scorable version). With
                no speech and no accents it is SFX only, so it measures well below the target (e.g. -17
                LUFS against -14): it is a stem for re-scoring, not a finished upload.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
import os

import numpy as np

from vstudio import audio as A

SR = A.SR


def voice_stem(pieces, total, fade=0.01, level=None):
    """pieces: [{src, a, b, t, rate?, gain_db?}] (source span a..b placed at timeline t, played at ``rate``)
    -> (n, 2) float32. ``level`` (LUFS): each piece normalised to level + its gain_db (accent stems)."""
    N = int(round(total * SR))
    x = np.zeros((N, 2), np.float32)
    nf = max(1, int(fade * SR))
    ramp = np.linspace(0, 1, nf, dtype=np.float32)[:, None]
    for p in pieces:
        rate = float(p.get("rate", 1.0))
        n = int(round((p["b"] - p["a"]) / rate * SR))
        if n <= 0:
            continue
        af = f"atempo={rate:.5f}" if abs(rate - 1.0) > 1e-3 else None
        y = A.decode_audio(p["src"], start=p["a"], dur=p["b"] - p["a"], af=af)[:n]
        if level is not None and len(y):
            li = A.integrated_lufs(y)
            if np.isfinite(li):
                y = y * np.float32(10 ** ((level + float(p.get("gain_db", 0.0)) - li) / 20))
        if len(y) < n:
            y = np.concatenate([y, np.zeros((n - len(y), 2), np.float32)])
        if n > 2 * nf:
            y[:nf] *= ramp
            y[-nf:] *= ramp[::-1]
        i = int(round(p["t"] * SR))
        j = min(N, i + n)
        if j > i:
            x[i:j] += y[:j - i]
    return x


def build_mix(work, total, music, music_start, speech_pieces, cues, prof, music_lufs=-19.0, duck_db=-12.0,
              fade_out=1.5, music_xfade=4.0, accent_pieces=None):
    """Write work/{voice,bed,vm,accent,sfx,mix,nomusic}.wav; returns dict(paths, measured loudness, gain).

    accent_pieces: native audio of non-speech shots kept with ``keep_audio`` ([{src, a, b, t, rate,
    gain_db}]): each piece at persona voice_lufs + gain_db (default -8 dB, i.e. ducked under the voice
    level), 30 ms fades, laid UNDER the music bed (the bed does not duck for it), also in the no-music mix."""
    os.makedirs(work, exist_ok=True)
    pa = A._persona_audio()
    n_all = int(round(total * SR))
    accent = None
    if accent_pieces:
        accent = _fit_len(voice_stem(accent_pieces, total, fade=0.03,
                                     level=float(pa.get("voice_lufs", -16))), n_all)
        out_acc = A.write_wav(os.path.join(work, "accent.wav"), accent)
    voice = voice_stem(speech_pieces, total)
    vp = A.write_wav(os.path.join(work, "voice.wav"), voice)
    out = dict(voice=vp)
    if music:
        bed = A.loop_bed(music, os.path.join(work, "bed.wav"), total, xfade=music_xfade, lufs=None,
                         fade_in=0.02, fade_out=fade_out, start=music_start)
        vm = A.mix_bed(vp, bed, os.path.join(work, "vm.wav"), duck_db=duck_db, music_lufs=music_lufs,
                       voice_lufs=float(pa.get("voice_lufs", -16)), fade_in=0.0, fade_out=0.0)
        mixed, _ = A.read_wav(vm)
        out["bed"], out["vm"] = bed, vm
        out["duck_measured_db"] = measured_duck(voice, vp, bed, mixed, speech_pieces, pa)
    else:
        mixed = voice.copy()
        mv = A.measure_loudness(vp)
        if np.isfinite(mv["input_i"]):
            mixed *= 10 ** ((float(pa.get("voice_lufs", -16)) - mv["input_i"]) / 20)
    n = n_all
    mixed = _fit_len(mixed, n)
    if accent is not None:
        mixed = mixed + accent
        out["accent"] = out_acc
    sfx = A.render_cue_sheet(cues, total) if cues else np.zeros((n, 2), np.float32)
    sfx = _fit_len(sfx, n)
    out["sfx"] = A.write_wav(os.path.join(work, "sfx.wav"), sfx)
    lufs, tp = float(prof.loudness["lufs"]), float(prof.loudness["tp"])
    x = mixed + sfx
    pk = float(np.max(np.abs(x))) if len(x) else 0.0
    s0 = min(1.0, 0.98 / pk) if pk > 0 else 1.0               # measure without 16-bit clipping
    pre = A.write_wav(os.path.join(work, "premix.wav"), x * s0)
    m0 = A.measure_loudness(pre)
    gain_db = (lufs - m0["input_i"]) if np.isfinite(m0["input_i"]) else 0.0
    g = s0 * 10 ** (gain_db / 20)
    ceil = tp - 2.0                                            # headroom for AAC / inter-sample overshoot
    lim = os.path.join(work, "limited.wav")
    for _ in range(3):                                         # limit, re-measure, re-gain: loudnorm stays linear
        A.write_wav(lim, A.limit(x * g, ceil))                # true-peak limiter: impacts never force dynamic loudnorm
        ml = A.measure_loudness(lim)
        if not np.isfinite(ml["input_i"]) or abs(lufs - ml["input_i"]) < 0.2:
            break
        g *= 10 ** ((lufs - ml["input_i"]) / 20)
    final = os.path.join(work, "mix.wav")
    m = A.loudnorm_2pass(lim, final, lufs=lufs, tp=tp)
    # no-music version: voice (at its stem level) + SFX, same gain as the music mix, same limiter
    vlev = voice.copy()
    mv = A.measure_loudness(vp)
    if np.isfinite(mv["input_i"]):
        vlev *= 10 ** ((float(pa.get("voice_lufs", -16)) - mv["input_i"]) / 20)
    nm = A.limit((_fit_len(vlev, n) + sfx + (accent if accent is not None else 0)) * g, ceil)
    out["nomusic"] = A.write_wav(os.path.join(work, "nomusic.wav"), nm)
    out["mix"] = final
    out["premix_lufs"] = round(float(m0["input_i"]), 2)
    out["gain_db"] = round(float(20 * np.log10(g)), 2)
    out["limited_lufs"] = round(float(m["input_i"]), 2)
    return out


def measured_duck(voice, vp, bed, vm, pieces, pa):
    """How far the music actually dips under speech (dB): music-in-mix / bed during speech vs elsewhere.
    The music in the mix = vm - voice * (mix_bed's voice gain). None without speech."""
    if not pieces:
        return None
    mv = A.measure_loudness(vp)
    if not np.isfinite(mv["input_i"]):
        return None
    gv = 10 ** ((float(pa.get("voice_lufs", -16)) - mv["input_i"]) / 20)
    b, _ = A.read_wav(bed)
    n = min(len(vm), len(b), len(voice))
    mus = (vm[:n] - voice[:n] * gv).mean(1)
    bb = b[:n].mean(1)
    sp = np.zeros(n, bool)
    for p in pieces:
        i, j = int((p["t"] + 0.3) * SR), int((p["t"] + p["b"] - p["a"] - 0.1) * SR)
        sp[max(0, i):max(0, min(n, j))] = True
    # only where the voice actually sounds: a speech piece also carries room tone (lead-in, the stretch to
    # the beat, squeezed pauses) where the ducker has released
    hop = SR // 20
    vm1 = voice[:n].mean(1).astype(np.float64)
    m = len(vm1) // hop
    if m:
        env = 10 * np.log10(np.mean(vm1[:m * hop].reshape(m, hop) ** 2, axis=1) + 1e-12)
        on = np.repeat(env > env.max() - 30.0, hop)
        sp[:len(on)] &= on
        sp[len(on):] = False
    away = np.ones(n, bool)
    for p in pieces:
        i, j = int((p["t"] - 1.0) * SR), int((p["t"] + p["b"] - p["a"] + 1.0) * SR)
        away[max(0, i):max(0, min(n, j))] = False
    away &= np.abs(bb) > 0
    if sp.sum() < SR // 4 or away.sum() < SR // 4:
        return None
    r = lambda y: 10 * np.log10(np.mean(y.astype(np.float64) ** 2) + 1e-12)
    return round(float((r(mus[sp]) - r(bb[sp])) - (r(mus[away]) - r(bb[away]))), 2)


def _fit_len(x, n):
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x), x.shape[1]), np.float32)])
