"""Studio sound: make a phone / laptop / room recording sound like a close mic (降噪, 人声增强, 去回声).

    from vstudio import studiosound as SS
    rep = SS.enhance("take.mp4", "take.studio.mp4")                 # video copied, audio cleaned, -14 LUFS
    rep = SS.enhance("vo.wav", "vo.clean.wav", strength="strong")    # light | standard | strong
    y, info = SS.enhance_array(x, 48000, strength="standard")        # in memory (output edit audio stage)
    SS.ab("take.mp4", "work/ab", start=30, dur=20)                   # before / after clips + report.json

    python -m vstudio.studiosound take.mp4 -o take.studio.mp4 [--strength standard]
    python -m vstudio.studiosound take.mp4 --ab work/ab --at 30 --dur 20 [--json]

Chain (numpy + plain ffmpeg filters, all local; no model download):
  1. analyse      noise floor (quietest frames), speech level, SNR, mains hum (50 / 60 Hz), reverb time
  2. denoise      decision-directed Wiener gain over a block-wise noise profile (quietest frames per 10 s),
                  smoothed in time and frequency so it does not "bubble"
  3. dereverb     late-reverb spectral subtraction (exponential decay model, T60 from the recording)
  4. tone         high-pass, hum notches, mud cut, presence lift, air shelf, de-esser, gentle compressor
  5. level        two-pass loudness to persona ``audio.loudness_lufs`` (-14) when writing a file
``strength`` scales 2-4 (how deep the noise goes down, how much reverb is taken, how much EQ); light keeps
some room so a clean phone recording is not over-processed.
"""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile

import numpy as np

from . import audio as A
from . import media

SR = A.SR
STRENGTHS = {
    # reduce_db: maximum noise attenuation; over: noise over-estimate; dereverb: 0..1; eq: 0..1 of the tone
    # curve; wet: processed share before the tone stage (the rest is the original, time-aligned)
    "light": dict(reduce_db=10.0, over=1.0, dereverb=0.25, eq=0.5, wet=0.85),
    "standard": dict(reduce_db=18.0, over=1.2, dereverb=0.5, eq=1.0, wet=1.0),
    "strong": dict(reduce_db=28.0, over=1.6, dereverb=0.8, eq=1.0, wet=1.0),
}
ALIASES = {"轻": "light", "轻度": "light", "低": "light", "中": "standard", "标准": "standard", "默认": "standard",
           "强": "strong", "强力": "strong", "高": "strong", "medium": "standard", "normal": "standard",
           "high": "strong", "low": "light"}

N_FFT = 1024
HOP = 256


def strength_of(s):
    """'standard' / '强' / 0..1 number -> a STRENGTHS key."""
    if s is None:
        return "standard"
    if isinstance(s, (int, float)):
        return "light" if s < 0.4 else ("standard" if s < 0.75 else "strong")
    k = str(s).strip().lower()
    k = ALIASES.get(k, k)
    if k not in STRENGTHS:
        raise ValueError(f"strength must be one of {sorted(STRENGTHS)}, got {s!r}")
    return k


# ------------------------------------------------------------------ STFT
def _win():
    return np.sqrt(np.hanning(N_FFT + 1)[:-1]).astype(np.float32)


def stft(x):
    """(n,) float -> complex64 (frames, N_FFT//2+1). Padded so every sample is covered by 4 frames."""
    w = _win()
    pad = N_FFT
    xp = np.concatenate([np.zeros(pad, np.float32), x.astype(np.float32), np.zeros(pad + HOP, np.float32)])
    n = 1 + (len(xp) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    return np.fft.rfft(xp[idx] * w, axis=1).astype(np.complex64)


def istft(S, n):
    w = _win()
    frames = np.fft.irfft(S, n=N_FFT, axis=1).astype(np.float32) * w
    out = np.zeros(HOP * (len(S) - 1) + N_FFT, np.float32)
    norm = np.zeros_like(out)
    for j in range(len(S)):                # plain overlap-add: ~0.1 s per minute of audio
        out[j * HOP:j * HOP + N_FFT] += frames[j]
        norm[j * HOP:j * HOP + N_FFT] += w * w
    out = out / np.maximum(norm, 1e-6)
    return out[N_FFT:N_FFT + n]


# ------------------------------------------------------------------ analysis
def _frame_db(P):
    return 10 * np.log10(np.maximum(P.mean(1), 1e-12))


def noise_profile(P, block_s=10.0, quiet=0.15):
    """Noise power per (frame, bin): mean of the quietest ``quiet`` share of frames in blocks of ``block_s``,
    linearly interpolated between block centres (slowly changing room noise follows, speech never counts)."""
    nf = len(P)
    per = max(40, int(block_s * SR / HOP))
    e = _frame_db(P)
    cents, profs = [], []
    for a in range(0, nf, per):
        b = min(nf, a + per)
        if b - a < 20 and profs:
            break
        sel = np.argsort(e[a:b])[:max(8, int((b - a) * quiet))] + a
        profs.append(P[sel].mean(0))
        cents.append((a + b) / 2)
    profs = np.array(profs)
    if len(profs) == 1:
        return np.broadcast_to(profs[0], P.shape)
    t = np.arange(nf)
    out = np.empty_like(P)
    for k in range(P.shape[1]):
        out[:, k] = np.interp(t, cents, profs[:, k])
    return out


def _hum(N0):
    """Mains hum: 50 or 60 Hz (+ harmonics) standing >= 10 dB above the neighbouring noise bins."""
    best = None
    for base in (50.0, 60.0):
        score = []
        for h in (1, 2, 3):
            k = int(round(base * h / (SR / N_FFT)))
            nb = np.r_[N0[max(0, k - 6):max(0, k - 2)], N0[k + 3:k + 7]]
            score.append(10 * np.log10(max(N0[k], 1e-20) / max(np.median(nb), 1e-15)))
        s = float(np.mean(score))
        if s >= 10 and (best is None or s > best[1]):
            best = (base, s)
    return best[0] if best else None


def _t60(x):
    """Reverb time from the steepest level falls (10 ms RMS envelope): every run of >= 60 ms where the level keeps
    falling, above the noise floor, gets a fitted fall rate (dB/s). A room cannot let the level fall faster than
    its own decay, so the fastest falls (90th percentile) are the room: T60 = 60 dB / that rate. Clamped to
    0.1-1.2 s; None when there are fewer than 5 usable falls."""
    env, hop = A.rms_envelope(x, SR, hop=0.01, win=0.02, db=True, smooth=1)
    env = np.asarray(env, np.float64)
    if len(env) < 50:
        return None
    floor = float(np.percentile(env, 3))
    ok = env > floor + 8
    falling = np.r_[False, np.diff(env) < 0] & ok
    rates = []
    i, n = 0, len(env)
    while i < n:
        if not falling[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and falling[j + 1]:
            j += 1
        a0 = i - 1                                        # the frame the fall starts from
        if j - a0 + 1 >= 6 and env[a0] - env[j] >= 6:
            k = np.arange(a0, j + 1)
            slope = -np.polyfit(k * hop, env[a0:j + 1], 1)[0]
            if slope > 0:
                rates.append(slope)
        i = j + 1
    if len(rates) < 5:
        return None
    return float(min(1.2, max(0.1, 60.0 / float(np.percentile(rates, 90)))))


def _round(v, n=2):
    return None if v is None else round(v, n)


def analyze(x, sr=SR):
    """x (n,) or (n, ch) -> {noise_db, speech_db, snr_db, hum_hz, t60, clip_pct, seconds}."""
    if sr != SR:
        raise ValueError("analyze expects 48 kHz audio (decode with audio.decode_audio)")
    m = x.mean(1) if x.ndim > 1 else x
    P = np.abs(stft(m)) ** 2
    e = _frame_db(P)
    loud = e[e > np.percentile(e, 60)] if len(e) > 10 else e
    noise_db = float(np.percentile(e, 10)) if len(e) else -120.0
    speech_db = float(np.mean(loud)) if len(loud) else noise_db
    N0 = np.sort(P, axis=0)[:max(4, len(P) // 7)].mean(0)
    return dict(noise_db=round(noise_db, 1), speech_db=round(speech_db, 1), snr_db=round(speech_db - noise_db, 1),
                hum_hz=_hum(N0), t60=_round(_t60(m)), clip_pct=round(float(np.mean(np.abs(x) > 0.99) * 100), 3),
                seconds=round(len(m) / SR, 2))


# ------------------------------------------------------------------ spectral denoise + dereverb
def _gains(P, N, reduce_db, over, dereverb, t60):
    """Decision-directed Wiener gain with a floor, times a late-reverb suppression gain; smoothed."""
    floor = 10 ** (-reduce_db / 20)
    nf, nb = P.shape
    Nn = np.maximum(N * over, 1e-12)
    gamma = P / Nn
    G = np.empty_like(P)
    a = 0.96
    prev = np.ones(nb, np.float32)
    prev_g = np.ones(nb, np.float32)
    for t in range(nf):
        xi = a * prev_g ** 2 * prev + (1 - a) * np.maximum(gamma[t] - 1, 0)
        g = xi / (1 + xi)
        G[t] = g
        prev, prev_g = gamma[t], g
    if dereverb > 0 and t60 and t60 >= 0.3:                # a dry close-mic take is left alone
        td = 0.05
        d = max(1, int(round(td * SR / HOP)))
        delta = 3 * math.log(10) / t60
        late = np.zeros_like(P)
        late[d:] = math.exp(-2 * delta * td) * P[:-d]
        # smooth the reverb estimate over a few frames (the tail of many earlier frames, not one)
        k = np.ones(5, np.float32) / 5
        late = np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, late)
        Gr = np.clip(1 - dereverb * 2.0 * late / np.maximum(P, 1e-12), 1 - 0.85 * dereverb, 1.0)
        G = G * Gr
    # frequency smoothing (3 bins) + fast attack / slower release over time: no musical noise
    G = (np.roll(G, 1, 1) + 2 * G + np.roll(G, -1, 1)) / 4
    out = np.empty_like(G)
    g = G[0]
    for t in range(nf):
        up = G[t] > g
        g = np.where(up, 0.6 * G[t] + 0.4 * g, 0.25 * G[t] + 0.75 * g)
        out[t] = g
    return np.clip(out, floor, 1.0)


def _spectral(x, cfg, t60):
    ch = [x] if x.ndim == 1 else [x[:, c] for c in range(x.shape[1])]
    mid = x if x.ndim == 1 else x.mean(1)
    Sm = stft(mid)
    P = (np.abs(Sm) ** 2).astype(np.float32)
    N = noise_profile(P)
    G = _gains(P, N, cfg["reduce_db"], cfg["over"], cfg["dereverb"], t60)
    outs = []
    for c in ch:
        S = Sm if x.ndim == 1 else stft(c)
        outs.append(istft(S * G, len(c)))
    return outs[0] if x.ndim == 1 else np.stack(outs, 1)


def _ff_filter(x, chain):
    """Run an ffmpeg audio filter chain on an in-memory 48 kHz array (same shape back)."""
    chn = 1 if x.ndim == 1 else x.shape[1]
    r = media.run(["ffmpeg", "-f", "f32le", "-ar", str(SR), "-ac", str(chn), "-i", "-", "-af", chain,
                   "-ar", str(SR), "-ac", str(chn), "-f", "f32le", "-"],
                  capture=True, input=np.ascontiguousarray(x, np.float32).tobytes())
    y = np.frombuffer(r.stdout, np.float32).copy()
    y = y.reshape(-1, chn) if x.ndim > 1 else y
    n = len(x)
    if len(y) >= n:
        return y[:n]
    pad = np.zeros((n - len(y),) + y.shape[1:], np.float32)
    return np.concatenate([y, pad])


# ------------------------------------------------------------------ tone
def tone_chain(eq=1.0, hum_hz=None):
    """ffmpeg filter chain: high-pass, hum notches, mud cut, presence, air, de-ess, compressor."""
    f = ["highpass=f=75:poles=2"]
    if hum_hz:
        f += [f"bandreject=f={hum_hz * h:g}:width_type=q:w=25" for h in (1, 2, 3, 4)]
    if eq > 0:
        f += [f"equalizer=f=250:t=q:w=1.1:g={-2.5 * eq:.2f}",
              f"equalizer=f=3200:t=q:w=0.9:g={2.5 * eq:.2f}",
              f"highshelf=f=9000:g={1.5 * eq:.2f}",
              "deesser=i=0.35:m=0.5:f=0.5",
              f"acompressor=threshold=-18dB:ratio={1.3 + 0.9 * eq:.2f}:attack=10:release=200:makeup=1.5:knee=6"]
    return ",".join(f)


# ------------------------------------------------------------------ public
def enhance_array(x, sr=SR, strength="standard"):
    """Clean a 48 kHz array (n,) / (n, ch). Returns (y, info). Level is NOT normalised here (callers do loudness)."""
    if sr != SR:
        raise ValueError("enhance_array expects 48 kHz audio")
    x = np.asarray(x, np.float32)
    key = strength_of(strength)
    cfg = STRENGTHS[key]
    before = analyze(x)
    if len(x) < N_FFT * 2 or not np.any(np.abs(x) > 1e-6):
        return x.copy(), dict(strength=key, skipped="silent or under 50 ms", before=before, after=before)
    y = _spectral(x, cfg, before["t60"])
    if cfg["wet"] < 1.0:
        y = cfg["wet"] * y + (1 - cfg["wet"]) * x
    y = _ff_filter(y, tone_chain(cfg["eq"], before["hum_hz"]))
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0.98:
        y = y * (0.98 / peak)
    after = analyze(y)
    return y.astype(np.float32), dict(strength=key, before=before, after=after,
                                      noise_drop_db=round(before["noise_db"] - after["noise_db"], 1))


def enhance(src, dst, strength="standard", lufs=None, tp=-1.5, video="copy", report=None):
    """``src`` (audio or video) -> ``dst`` with cleaned audio; video stream-copied; loudness to ``lufs``
    (persona audio.loudness_lufs, -14) unless ``lufs is False``. Returns the info dict (+ ``loudness``);
    ``report`` = a json path to write it to."""
    info = media.probe(src)
    if not info.get("has_audio"):
        raise ValueError(f"{src}: no audio stream")
    x = A.decode_audio(src, sr=SR, channels=2)
    y, rep = enhance_array(x, SR, strength)
    d = tempfile.mkdtemp(prefix="vss-")
    try:
        wav = os.path.join(d, "clean.wav")
        A.write_wav(wav, y, SR)
        ext = os.path.splitext(dst)[1].lower()
        if lufs is False:
            if ext == ".wav":
                shutil.copy(wav, dst)
            else:
                A._encode_audio(src, wav, dst, video=video)
        elif ext == ".wav":
            rep["loudness"] = A.loudnorm_2pass(wav, dst, lufs=lufs, tp=tp, headroom=0)
        else:
            mid = os.path.join(d, "mux" + (ext if ext in (".mp4", ".mov", ".m4a", ".mkv") else ".mp4"))
            A._encode_audio(src, wav, mid, video=video)
            rep["loudness"] = A.loudnorm_2pass(mid, dst, lufs=lufs, tp=tp, video="copy")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    rep.update(src=os.path.abspath(src), dst=os.path.abspath(dst))
    if report:
        with open(report, "w") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, default=float)
    return rep


def ab(src, out_dir, start=0.0, dur=20.0, strengths=("light", "standard", "strong")):
    """Before / after snippets for listening: ``out_dir/0_original.wav`` + ``<n>_<strength>.wav`` (all at the
    same loudness, so louder never sounds 'better') + report.json."""
    os.makedirs(out_dir, exist_ok=True)
    x = A.decode_audio(src, sr=SR, channels=2, start=start or None, dur=dur)
    rows = []
    orig = os.path.join(out_dir, "0_original.wav")
    A.write_wav(orig, x, SR)
    A.loudnorm_2pass(orig, orig + ".tmp.wav", lufs=-16, headroom=0)
    os.replace(orig + ".tmp.wav", orig)
    rows.append(dict(file=orig, strength="original", **analyze(A.read_wav(orig)[0])))
    for i, s in enumerate(strengths, 1):
        y, info = enhance_array(x, SR, s)
        p = os.path.join(out_dir, f"{i}_{strength_of(s)}.wav")
        A.write_wav(p, y, SR)
        A.loudnorm_2pass(p, p + ".tmp.wav", lufs=-16, headroom=0)
        os.replace(p + ".tmp.wav", p)
        rows.append(dict(file=p, strength=info["strength"],
                         **analyze(A.read_wav(p)[0])))
    rep = dict(src=os.path.abspath(src), start=start, dur=dur, rows=rows)
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=float)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.studiosound",
                                 description="Studio sound: denoise, dereverb, voice EQ and loudness (local).")
    ap.add_argument("src")
    ap.add_argument("-o", "--out", help="output file (video: picture copied); default <src>.studio<ext>")
    ap.add_argument("--strength", default="standard", help="light | standard | strong (轻 / 标准 / 强)")
    ap.add_argument("--lufs", type=float, default=None, help="loudness target (default persona, -14)")
    ap.add_argument("--no-loudness", action="store_true", help="keep the cleaned level (no loudness pass)")
    ap.add_argument("--ab", metavar="DIR", help="write before / after listening clips instead of a full file")
    ap.add_argument("--at", type=float, default=0.0, help="--ab: start second")
    ap.add_argument("--dur", type=float, default=20.0, help="--ab: clip length")
    ap.add_argument("--analyze", action="store_true", help="only print the analysis")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.analyze:
        rep = analyze(A.decode_audio(a.src, sr=SR, channels=2))
    elif a.ab:
        rep = ab(a.src, a.ab, a.at, a.dur)
    else:
        stem, ext = os.path.splitext(a.out or a.src)
        out = a.out or f"{stem}.studio{ext}"
        rep = enhance(a.src, out, a.strength, lufs=False if a.no_loudness else a.lufs)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=float))
    elif a.analyze:
        print(f"noise {rep['noise_db']} dB, speech {rep['speech_db']} dB, SNR {rep['snr_db']} dB, "
              f"hum {rep['hum_hz'] or '-'}, T60 {rep['t60'] or 'dry'} s")
    elif a.ab:
        for r in rep["rows"]:
            print(f"{r['strength']:>9}  noise {r['noise_db']:6.1f} dB  SNR {r['snr_db']:5.1f} dB  {r['file']}")
    else:
        b, f = rep["before"], rep["after"]
        print(f"studio sound ({rep['strength']}): noise {b['noise_db']} -> {f['noise_db']} dB, "
              f"SNR {b['snr_db']} -> {f['snr_db']} dB -> {rep['dst']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
