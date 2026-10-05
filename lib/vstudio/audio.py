"""Audio: loudness, stems, envelopes, silence, music beds, pitch, synthesized SFX.

    from vstudio import audio
    audio.loudnorm_2pass("joined.mp4", "final.mp4")          # persona audio.loudness_lufs (-14), linear
    audio.normalize_stem("vo.wav", "vo_n.wav")               # persona audio.voice_lufs (-16)
    audio.mix_bed("vo_n.wav", "music.mp3", "mix.wav", duck_db=-10)
    env, hop = audio.rms_envelope(x, sr)                     # 10 ms hop, dB or linear

Every stem this module writes is 48 kHz STEREO: mono is up-mixed BEFORE loudness is measured,
so a mono narration and a stereo hook land at the same perceived level and concat never
re-initialises the audio stream. Unified from polish ``polish.measure/step_loudness``, call-clips
``build_clips`` loudnorm block, longform ``render.py`` (two-pass, linear) + ``qa.py``, preproduction
``make_drill`` loudnorm, vlog ``add_music``, photo-story ``render.mix_audio``, promo ``tight_cut.rms_envelope``,
talkinghead ``cut_pass1``/``strict_pass`` RMS and ``compose.sfx_bank``.
"""
import json
import os
import re
import shutil
import tempfile
import wave

import numpy as np

from . import media

SR = 48000


def _persona_audio():
    try:
        from .config import persona
        return persona().get("audio", {}) or {}
    except Exception:
        return {}


# ------------------------------------------------------------------ wav io
def read_wav(path, mono=False):
    """Read a wav as float32 in [-1, 1]. Returns (x, sr); x is (n,) if mono/1-channel else (n, ch).
    soundfile when installed (any subtype), else the stdlib ``wave`` module (16-bit PCM)."""
    try:
        import soundfile as sf
        x, sr = sf.read(path, dtype="float32", always_2d=False)
    except ImportError:
        with wave.open(path, "rb") as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw != 2:
            raise ValueError(f"{path}: install soundfile to read {8 * sw}-bit wav")
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        if ch > 1:
            x = x.reshape(-1, ch)
    if mono and x.ndim > 1:
        x = x.mean(1)
    return x, sr


def write_wav(path, x, sr=SR):
    """Write float audio (n,) or (n, ch) as 16-bit PCM wav (clipped). Returns path."""
    x = np.clip(np.asarray(x, np.float32), -1, 1)
    try:
        import soundfile as sf
        sf.write(path, x, sr, subtype="PCM_16")
    except ImportError:
        ch = 1 if x.ndim == 1 else x.shape[1]
        with wave.open(path, "wb") as w:
            w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


def decode_audio(path, sr=SR, channels=2, start=None, dur=None, af=None):
    """Decode any media's first audio stream with ffmpeg -> float32 array (n, channels).
    start/dur in seconds (accurate seek); af: optional filter chain applied before resampling."""
    cmd = ["ffmpeg"]
    if start:
        cmd += ["-ss", f"{start:.4f}"]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    chain = [c for c in (af, f"aresample={sr}") if c]
    cmd += ["-map", "0:a:0", "-vn", "-af", ",".join(chain), "-ac", str(channels), "-f", "f32le", "-"]
    r = media.run(cmd, capture=True)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, channels).copy()


# ------------------------------------------------------------------ loudness
_LN_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)
_STEREO48 = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"


def measure_loudness(path, lufs=-14.0, tp=-1.5, lra=11.0, pre=_STEREO48):
    """EBU R128 first pass (ffmpeg loudnorm print_format=json) of ``path``'s audio.

    Measured after ``pre`` (default: 48 kHz stereo up-mix, the way it will be delivered).
    Returns dict of floats: input_i, input_tp, input_lra, input_thresh, target_offset
    (input_i = -inf for digital silence). From polish ``measure`` / call-clips / longform render.py.
    """
    af = (pre + "," if pre else "") + f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:print_format=json"
    r = media.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", path, "-vn", "-af", af,
                   "-f", "null", "-"], capture=True)
    ms = _LN_JSON.findall(r.stderr_text)
    if not ms:
        raise media.FFmpegError("loudnorm measurement failed:\n" + r.stderr_text[-1500:])
    d = json.loads(ms[-1])
    out = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            out[k] = float(d[k])
        except (KeyError, ValueError):
            out[k] = float("-inf")
    return out


def loudnorm_filter(m, lufs, tp=-1.5, lra=11.0):
    """Second-pass ``loudnorm`` string (linear=true) from a ``measure_loudness`` dict.

    The LRA target is raised to the measured LRA so loudnorm stays in linear (pure-gain) mode
    instead of silently falling back to dynamic compression. Linear mode still falls back if the
    gain would push true peak over ``tp``; that is loudnorm's own limiter doing its job.
    """
    lra_t = min(50.0, max(lra, m["input_lra"] + 0.1)) if np.isfinite(m["input_lra"]) else lra
    return (f"loudnorm=I={lufs}:TP={tp}:LRA={lra_t:.1f}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
            f"linear=true:print_format=summary")


def loudnorm_2pass(src, dst, lufs=None, tp=-1.5, lra=11.0, audio_bitrate=None, video="copy"):
    """Two-pass loudness normalisation of ``src`` -> ``dst`` (48 kHz stereo).

    Args: lufs target (default persona audio.loudness_lufs, -14); tp true-peak ceiling; lra;
    video "copy" (stream copy, default) or "drop". Output codec from the extension: .wav -> PCM s16,
    .m4a/.mp4/.mov/.mkv -> AAC (persona export.audio_bitrate) + video copy + faststart.
    Single-pass loudnorm undershoots on short or quiet cuts, hence measure-then-apply in linear mode
    and resample back to 48 kHz (loudnorm works at 192 kHz internally).
    Returns the first-pass measurement dict. From polish ``step_loudness``, call-clips, longform render.py.
    """
    lufs = float(_persona_audio().get("loudness_lufs", -14) if lufs is None else lufs)
    m = measure_loudness(src, lufs, tp, lra)
    if not np.isfinite(m["input_i"]):
        af = _STEREO48                       # silence: nothing to normalise
    else:
        af = f"{_STEREO48},{loudnorm_filter(m, lufs, tp, lra)},aresample={SR}"
    ext = os.path.splitext(dst)[1].lower()
    info = media.probe(src)
    cmd = ["ffmpeg", "-y", "-i", src]
    if ext == ".wav":
        cmd += ["-map", "0:a:0", "-vn", "-af", af, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", dst]
    else:
        if info["has_video"] and video == "copy" and ext not in (".m4a", ".aac"):
            cmd += ["-map", "0:v:0", "-c:v", "copy"]
        else:
            cmd += ["-vn"]
        br = audio_bitrate or _persona_export_bitrate()
        cmd += ["-map", "0:a:0", "-af", af, "-ar", str(SR), "-ac", "2", "-c:a", "aac", "-b:a", br]
        if ext in (".mp4", ".m4a", ".mov"):
            cmd += ["-movflags", "+faststart"]
        cmd += [dst]
    media.run(cmd)
    return m


def _persona_export_bitrate():
    try:
        from .config import persona
        return str((persona().get("export") or {}).get("audio_bitrate", "192k"))
    except Exception:
        return "192k"


def normalize_stem(src, dst, lufs=None, tp=-1.5):
    """Normalise a narration / music stem to ``lufs`` (default persona audio.voice_lufs, -16) as a
    48 kHz stereo PCM wav, ready to mix. Returns the measurement dict.
    From promo ``tight_cut.cut_file`` (stems at voice_lufs) and explainer narration prep."""
    lufs = float(_persona_audio().get("voice_lufs", -16) if lufs is None else lufs)
    if not dst.lower().endswith(".wav"):
        raise ValueError("normalize_stem writes .wav stems")
    return loudnorm_2pass(src, dst, lufs=lufs, tp=tp)


# ------------------------------------------------------------------ envelopes / silence
def rms_envelope(x, sr, hop=0.01, win=0.03, db=True, smooth=3, smooth_db=False):
    """Short-time RMS envelope of mono float audio (stereo is averaged).

    Args: hop/win in seconds; db -> 20*log10(rms) (floor -120); smooth = moving-average frames,
    applied to the linear RMS (default) or, with smooth_db=True, to the dB values (talkinghead
    cut_pass1/strict_pass rules were tuned on dB smoothing; linear smoothing widens voiced runs ~10 ms).
    Returns (env, hop). Frame i covers samples [i*hop, i*hop + win).
    Vectorised merge of promo ``tight_cut.rms_envelope`` (linear, 10/30 ms) and talkinghead
    ``cut_pass1``/``strict_pass`` (dB, 10 ms, 3-frame smoothing).
    """
    x = np.asarray(x, np.float32)
    if x.ndim > 1:
        x = x.mean(1)
    h, n = max(1, int(round(sr * hop))), max(1, int(round(sr * win)))
    frames = max(1, (len(x) - n) // h + 1) if len(x) >= n else 1
    c = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    idx = np.arange(frames) * h
    end = np.minimum(idx + n, len(x))
    env = np.sqrt((c[end] - c[idx]) / np.maximum(1, end - idx) + 1e-12)
    if smooth_db and db:
        env = 20 * np.log10(np.maximum(env, 1e-6))
        if smooth and smooth > 1 and len(env) >= smooth:
            env = np.convolve(env, np.ones(smooth) / smooth, mode="same")
        return env.astype(np.float32), hop
    if smooth and smooth > 1 and len(env) >= smooth:
        env = np.convolve(env, np.ones(smooth) / smooth, mode="same")
    if db:
        env = 20 * np.log10(np.maximum(env, 1e-6))
    return env.astype(np.float32), hop


def voiced_runs(env_db, hop, threshold_db=-45.0, min_run=0.03, max_gap=0.20, t0=0.0):
    """Runs of frames above ``threshold_db``, merged across gaps <= max_gap s, each >= min_run s.
    Returns [[start, end], ...] in seconds (offset by t0). From talkinghead ``cut_pass1`` (inline)."""
    v = np.asarray(env_db) > threshold_db
    runs, k = [], 0
    while k < len(v):
        if v[k]:
            j = k
            while j < len(v) and v[j]:
                j += 1
            if (j - k) * hop >= min_run:
                runs.append([t0 + k * hop, t0 + j * hop])
            k = j
        else:
            k += 1
    merged = []
    for s, e in runs:
        if merged and s - merged[-1][1] <= max_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return merged


def silence_spans(path, noise_db=-35.0, min_dur=0.5):
    """ffmpeg ``silencedetect`` -> [(start, end), ...] silences in seconds (an open trailing
    silence ends at the file duration). From longform-to-short ``analyze.py``."""
    r = media.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", path, "-vn", "-af",
                   f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"], capture=True)
    txt = r.stderr_text
    starts = [float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", txt)]
    ends = [float(m) for m in re.findall(r"silence_end: (-?[\d.]+)", txt)]
    if len(ends) < len(starts):
        ends.append(media.duration(path))
    return [(max(0.0, s), e) for s, e in zip(starts, ends)]


def sounded_spans(silences, total, pad=0.30, min_sound=0.40, join=0.2):
    """Complement of ``silences`` within [0, total]: sounded spans >= min_sound, padded by ``pad``
    and merged when closer than ``join``. From longform-to-short ``analyze.py`` (sounded.json)."""
    sounded, cur = [], 0.0
    for s, e in silences:
        if s > cur:
            sounded.append([cur, s])
        cur = max(cur, e)
    if cur < total:
        sounded.append([cur, total])
    out = []
    for a, b in sounded:
        if b - a < min_sound:
            continue
        a, b = max(0.0, a - pad), min(total, b + pad)
        if out and a <= out[-1][1] + join:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out


# ------------------------------------------------------------------ music bed
def _db(g):
    return 10 ** (g / 20)


def mix_bed(voice, music, out, duck_db=-10.0, music_lufs=None, voice_lufs=None, lufs=None, carve=False,
            fade_in=2.0, fade_out=3.0, attack=0.08, release=0.40, threshold_db=None, music_start=0.0,
            ambient_db=None):
    """Mix a looping music bed under a voice track with volume-automation ducking -> 48 kHz stereo.

    Args:
      voice, music: any media paths (voice may be a video; its first audio stream is used).
      duck_db: extra music gain while the voice is active (negative). attack/release seconds.
      music_lufs / voice_lufs: stem levels before mixing (persona audio.music_lufs -30 /
        audio.voice_lufs -16); pure gain from a loudness measurement, no compression.
      lufs: if set (e.g. persona loudness_lufs), the mix gets a final two-pass loudnorm.
      carve: also cut the 1-4 kHz presence band of the music by ~5 dB (static EQ) so consonants
        stay clear. In HyperFrames projects use hyperframes-audio ``carve.mjs`` instead (it carves
        per-word on the timeline); a duck alone is not enough for busy tracks.
      threshold_db: voice-activity threshold on the 10 ms RMS (default: recording floor +
        30% of the floor->speech range, the find_disfluencies rule).
      music_start: skip into the track; ambient_db: keep the voice file's audio as "ambience" at this
        gain instead of treating it as speech (vlog ``add_music --ambient-db``): no ducking.
    Writes ``out`` (.wav PCM, or AAC if another extension). Returns out.
    From vlog ``add_music`` (loop+fade+loudnorm), photo-story ``render.mix_audio`` (bed volume),
    explainer ``make_bgm_bed`` (-30 LUFS bed).
    """
    pa = _persona_audio()
    music_lufs = float(pa.get("music_lufs", -30) if music_lufs is None else music_lufs)
    voice_lufs = float(pa.get("voice_lufs", -16) if voice_lufs is None else voice_lufs)
    v = decode_audio(voice)
    mv = measure_loudness(voice)
    if np.isfinite(mv["input_i"]):
        v *= _db(voice_lufs - mv["input_i"]) if ambient_db is None else _db(ambient_db)
    eq = "equalizer=f=2200:t=q:w=1.1:g=-5" if carve else None
    m = decode_audio(music, af=eq, start=music_start or None)
    mm = measure_loudness(music)
    if np.isfinite(mm["input_i"]):
        m *= _db(music_lufs - mm["input_i"])
    n = len(v)
    if len(m) == 0:
        m = np.zeros((n, 2), np.float32)
    reps = int(np.ceil(n / len(m)))
    m = np.tile(m, (reps, 1))[:n]
    # fades
    t = np.arange(n) / SR
    g = np.ones(n, np.float32)
    if fade_in > 0:
        g *= np.clip(t / fade_in, 0, 1)
    if fade_out > 0 and n:
        g *= np.clip((t[-1] - t) / fade_out, 0, 1)
    # ducking curve from the voice envelope (one-pole attack/release in dB)
    if duck_db and ambient_db is None:
        env, hop = rms_envelope(v, SR, hop=0.01, win=0.03)
        if threshold_db is None:
            floor, speech = np.percentile(env, 8), np.percentile(env, 70)
            threshold_db = floor + 0.30 * (speech - floor)
        tgt = np.where(env > threshold_db, duck_db, 0.0)
        a_k, r_k = 1 - np.exp(-hop / max(attack, 1e-3)), 1 - np.exp(-hop / max(release, 1e-3))
        cur, curve = 0.0, np.empty(len(tgt), np.float32)
        for i, x in enumerate(tgt):
            cur += (x - cur) * (a_k if x < cur else r_k)
            curve[i] = cur
        # look-ahead by the attack time so the dip lands with the first syllable, not after it
        shift = int(round(attack / hop))
        curve = np.concatenate([curve[shift:], np.full(shift, curve[-1] if len(curve) else 0.0)])
        g *= _db(np.interp(t, np.arange(len(curve)) * hop + 0.015, curve)).astype(np.float32)
    mix = v + m * g[:, None]
    tmp = out if out.lower().endswith(".wav") and lufs is None else tempfile.mktemp(suffix=".wav")
    write_wav(tmp, mix, SR)
    if lufs is not None:
        loudnorm_2pass(tmp, out, lufs=lufs)
        os.remove(tmp)
    elif tmp != out:
        media.run(["ffmpeg", "-y", "-i", tmp, "-c:a", "aac", "-b:a", _persona_export_bitrate(), "-ar", str(SR), out])
        os.remove(tmp)
    return out


def _write_out(x, out, lufs=None, tp=-1.5, lra=11.0):
    """float (n, 2) -> ``out`` (.wav PCM, else AAC); optional two-pass loudnorm."""
    if lufs is None and out.lower().endswith(".wav"):
        return write_wav(out, x, SR)
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        write_wav(tmp, x, SR)
        if lufs is not None:
            loudnorm_2pass(tmp, out, lufs=lufs, tp=tp, lra=lra)
        else:
            media.run(["ffmpeg", "-y", "-i", tmp, "-c:a", "aac", "-b:a", _persona_export_bitrate(), "-ar", str(SR), out])
    finally:
        os.remove(tmp)
    return out


def loop_bed(src, dst, total, xfade=6.0, lufs=-30.0, fade_in=3.0, fade_out=5.0, start=0.0, tp=-6.0, lra=7.0):
    """Loop a music track to ``total`` seconds with ``xfade`` s linear crossfades between the loops
    (no hard seam, unlike ``mix_bed``'s tiling), fade in/out, then two-pass loudnorm to ``lufs``
    (None = leave the level) -> 48 kHz stereo ``dst`` (.wav PCM, else AAC). start: skip into the
    track first. Raises ValueError if the track is not longer than xfade. Returns dst.
    From explainer ``make_bgm_bed.py`` (acrossfade c1=tri:c2=tri chain, -30 LUFS, tp -6, LRA 7)."""
    x = decode_audio(src, start=start or None)
    L, X, N = len(x), int(round(xfade * SR)), int(round(total * SR))
    if L <= X or L == 0:
        raise ValueError(f"source ({L / SR:.1f}s) must be longer than xfade ({xfade}s)")
    out = np.zeros((max(N, L), 2), np.float32)
    out[:L] = x
    end = L
    if X:
        up = np.linspace(0, 1, X, dtype=np.float32)[:, None]
    while end < N:
        pos = end - X
        if X:
            out[pos:end] = out[pos:end] * (1 - up) + x[:X] * up
        rest = x[X:]
        need = min(len(rest), len(out) - end)
        if end + len(rest) > len(out):
            out = np.concatenate([out, np.zeros((end + len(rest) - len(out), 2), np.float32)])
            need = len(rest)
        out[end:end + need] = rest[:need]
        end += len(rest)
    y = out[:N].copy()
    t = np.arange(N) / SR
    g = np.ones(N, np.float32)
    if fade_in > 0:
        g *= np.clip(t / fade_in, 0, 1)
    if fade_out > 0 and N:
        g *= np.clip((total - t) / fade_out, 0, 1)
    return _write_out(y * g[:, None], dst, lufs, tp, lra)


def place_clips(clips, total, dst, lufs=None, tp=-1.5):
    """Place audio files on a timeline -> one 48 kHz stereo stem ``dst`` of ``total`` seconds.

    clips: [(path, start)] or [(path, start, gain_db)] or dicts {path, start, gain_db, trim}
    (start in timeline seconds; a negative start drops the clip's head; trim = max seconds used).
    Overlapping clips are summed (no normalisation); lufs: optional final two-pass loudnorm.
    Returns dst. From photo-story ``timeline.place_voice`` (adelay + amix normalize=0)."""
    N = int(round(total * SR))
    mix = np.zeros((N, 2), np.float32)
    for c in clips:
        if isinstance(c, dict):
            path, st, gdb, trim = c["path"], float(c["start"]), float(c.get("gain_db", 0) or 0), c.get("trim")
        else:
            path, st = c[0], float(c[1])
            gdb, trim = (float(c[2]) if len(c) > 2 else 0.0), None
        if st >= total:
            continue
        x = decode_audio(str(path))
        if trim is not None:
            x = x[:int(round(float(trim) * SR))]
        i = int(round(st * SR))
        if i < 0:
            x, i = x[-i:], 0
        j = min(N, i + len(x))
        if j > i:
            mix[i:j] += x[:j - i] * (_db(gdb) if gdb else 1.0)
    return _write_out(mix, dst, lufs, tp)


# ------------------------------------------------------------------ pitch
def pitch_shift_filter(semitones, tempo=1.0, sr=SR):
    """ffmpeg audio chain that shifts pitch by ``semitones`` and plays at ``tempo`` (duration / tempo).

    asetrate re-labels the rate (pitch AND speed change by r = 2^(st/12)), aresample returns to
    ``sr``, then atempo(tempo / r) restores the wanted duration. Used for voice anonymisation.
    From longform-to-short ``render.py`` (pitch windows).
    """
    r = 2 ** (semitones / 12.0)
    return f"aresample={sr},asetrate={int(round(sr * r))},aresample={sr},{media.atempo_chain(tempo / r)}"


# ------------------------------------------------------------------ SFX
# Everything here is synthesised from sine/noise maths (no samples, no licences). The vocabulary,
# grammar and levels are documented in references/SOUND.md.
def _sfx_t(d, sr):
    return np.arange(int(round(d * sr))) / sr


def _sfx_band(x, sr, lo, hi):
    """Static band-pass by FFT masking with ~1/3-octave cosine skirts."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    m = np.ones_like(f)
    with np.errstate(divide="ignore"):
        lf = np.log2(np.maximum(f, 1e-3))
    if lo:
        m *= np.clip((lf - np.log2(lo) + 1 / 3) * 3, 0, 1)
    if hi:
        m *= np.clip((np.log2(hi) - lf + 1 / 3) * 3, 0, 1)
    return np.fft.irfft(X * m, len(x))


def _sfx_sweep(x, sr, fc, bw=0.6, n_fft=1024):
    """Time-varying band-pass (overlap-add STFT, Gaussian band in log-frequency).
    fc: callable u -> centre Hz, with u in [0, 1] across the sound."""
    hop = n_fft // 4
    win = np.hanning(n_fft)
    xp = np.pad(x, (n_fft, n_fft))
    out = np.zeros_like(xp)
    norm = np.zeros_like(xp)
    f = np.maximum(np.fft.rfftfreq(n_fft, 1 / sr), 1.0)
    n = max(1, (len(xp) - n_fft) // hop + 1)
    for i in range(n):
        a = i * hop
        u = np.clip((a + n_fft / 2 - n_fft) / max(1, len(x)), 0, 1)
        g = np.exp(-0.5 * (np.log2(f / fc(u)) / bw) ** 2)
        out[a:a + n_fft] += np.fft.irfft(np.fft.rfft(xp[a:a + n_fft] * win) * g, n_fft) * win
        norm[a:a + n_fft] += win ** 2
    return (out / np.maximum(norm, 1e-3))[n_fft:n_fft + len(x)]


def _sfx_tone(freq, sr):
    """Phase-continuous oscillator from an instantaneous-frequency array."""
    return np.sin(2 * np.pi * np.cumsum(freq) / sr)


def _sfx_norm(x, peak, sr, fade=0.004):
    x = np.asarray(x, np.float64)
    n = min(len(x), max(1, int(fade * sr)))
    x[-n:] *= np.linspace(1, 0, n)
    m = np.abs(x).max()
    return x * (peak / m) if m > 0 else x


def _sfx_new(sr):
    """The extended vocabulary (all mono, normalised to a 0.8 peak unless noted)."""
    rng = lambda s: np.random.default_rng(s)  # noqa: E731
    b = {}
    # riser: swept noise + rising detuned tones, crescendo whose peak sits ~30 ms before the end
    tt = _sfx_t(2.4, sr)
    u = tt / tt[-1]
    nz = _sfx_sweep(rng(11).standard_normal(len(tt)), sr, lambda v: 300 * (6000 / 300) ** v, bw=0.5)
    fr = 150 * (900 / 150) ** u
    tone = sum(_sfx_tone(fr * d, sr) for d in (1.0, 1.006, 0.994)) / 3
    env = u ** 2.2 * np.clip((tt[-1] - tt) / 0.03, 0, 1)
    b["riser"] = _sfx_norm((nz / (np.abs(nz).max() + 1e-9) * 0.6 + tone * 0.4) * env, 0.8, sr)

    # impact / boom: pitch-dropping sub + low noise transient, soft-saturated; two variants
    def impact(base, decay, seed):
        tt = _sfx_t(1.4, sr)
        body = _sfx_tone(base + 90 * np.exp(-tt * 18), sr) * np.exp(-tt * decay) * np.clip(tt / 0.002, 0, 1)
        hit = _sfx_band(rng(seed).standard_normal(len(tt)), sr, 60, 2500) * np.exp(-tt * 60)
        hit /= np.abs(hit).max() + 1e-9
        return _sfx_norm(np.tanh(1.6 * (body + 0.5 * hit)), 0.9, sr)
    b["impact"], b["impact_b"] = impact(45, 3.2, 21), impact(52, 3.8, 22)

    # sparkle: staggered high bell pings + a thin shimmer
    tt = _sfx_t(0.9, sr)
    r = rng(31)
    sp = np.zeros(len(tt))
    for k, (t0, f0) in enumerate(sorted(zip(r.uniform(0, 0.45, 14), r.uniform(3000, 8000, 14)))):
        d = np.clip(tt - t0, 0, None)
        sp += (tt >= t0) * np.sin(2 * np.pi * f0 * d) * np.exp(-d * 25) * (1 - 0.04 * k)
    sh = _sfx_band(r.standard_normal(len(tt)), sr, 6000, 11000) * np.exp(-tt * 6) * 0.15
    b["sparkle"] = _sfx_norm(sp + sh / (np.abs(sh).max() + 1e-9) * 0.3, 0.7, sr)

    # shutter (camera): two mechanical clicks (mirror up / down) with a small body resonance
    def shutter(gap, seed):
        tt = _sfx_t(0.18, sr)
        out = np.zeros(len(tt))
        for t0, g in ((0.0, 1.0), (gap, 0.7)):
            d = np.clip(tt - t0, 0, None)
            on = tt >= t0
            n = _sfx_band(rng(seed).standard_normal(len(tt)), sr, 2000, 12000)
            out += on * g * (n / (np.abs(n).max() + 1e-9) * np.exp(-d * 400)
                             + 0.3 * np.sin(2 * np.pi * 1200 * d) * np.exp(-d * 120)
                             + 0.25 * np.sin(2 * np.pi * 180 * d) * np.exp(-d * 90))
            seed += 1
        return _sfx_norm(out, 0.8, sr)
    b["shutter"], b["shutter_b"] = shutter(0.075, 41), shutter(0.06, 43)

    # swoosh: short swept-noise swell (titles, small pushes); two variants
    def swoosh(f0, f1, c, seed):
        tt = _sfx_t(0.22, sr)
        n = _sfx_sweep(rng(seed).standard_normal(len(tt)), sr, lambda v: f0 * (f1 / f0) ** v, bw=0.7, n_fft=512)
        return _sfx_norm(n * np.exp(-0.5 * ((tt - c) / 0.045) ** 2), 0.8, sr)
    b["swoosh"], b["swoosh_b"] = swoosh(800, 4000, 0.13, 51), swoosh(1000, 5000, 0.12, 52)

    # whip: fast rising swell that peaks right at the cut and stops dead (whip pans)
    tt = _sfx_t(0.28, sr)
    n = _sfx_sweep(rng(61).standard_normal(len(tt)), sr, lambda v: 400 * (7000 / 400) ** v, bw=0.8, n_fft=512)
    env = np.where(tt < 0.24, (tt / 0.24) ** 3, np.exp(-(tt - 0.24) * 120))
    b["whip"] = _sfx_norm(n * env, 0.8, sr)

    # soft transition: slow airy swell for scene changes
    tt = _sfx_t(0.9, sr)
    n = _sfx_sweep(rng(71).standard_normal(len(tt)), sr, lambda v: 300 * (1800 / 300) ** v, bw=1.0)
    b["soft"] = _sfx_norm(n * np.exp(-0.5 * ((tt - 0.45) / 0.18) ** 2), 0.7, sr)

    # tick: tiny pitched click (counters, list steps); two variants
    def tick(f0, seed):
        tt = _sfx_t(0.03, sr)
        c = rng(seed).standard_normal(len(tt)) * np.exp(-tt * 900) * 0.3
        return _sfx_norm(np.sin(2 * np.pi * f0 * tt) * np.exp(-tt * 250) + c, 0.7, sr)
    b["tick"], b["tick_b"] = tick(3200, 81), tick(2700, 82)

    # typewriter key: bright clack + low thock; two variants; ``typing`` = 3 s of irregular keys
    def key(lo, f_thock, seed):
        tt = _sfx_t(0.07, sr)
        n = _sfx_band(rng(seed).standard_normal(len(tt)), sr, lo, 6000)
        return _sfx_norm(n / (np.abs(n).max() + 1e-9) * np.exp(-tt * 180)
                         + 0.5 * np.sin(2 * np.pi * f_thock * tt) * np.exp(-tt * 60), 0.8, sr)
    b["typewriter"], b["typewriter_b"] = key(1500, 220, 91), key(1800, 190, 92)
    r = rng(93)
    typing = np.zeros(int(3.0 * sr))
    t0, k = 0.0, 0
    while t0 < 2.93:
        s = (b["typewriter"], b["typewriter_b"])[k % 2] * r.uniform(0.55, 1.0)
        i = int(t0 * sr)
        j = min(len(typing), i + len(s))
        typing[i:j] += s[:j - i]
        t0 += r.gamma(4.0, 0.085 / 4.0) + 0.02
        k += 1
    b["typing"] = _sfx_norm(typing, 0.8, sr)

    # record scratch: band-limited noise whose centre swings back and forth (two strokes)
    tt = _sfx_t(0.45, sr)
    n = _sfx_sweep(rng(101).standard_normal(len(tt)), sr,
                   lambda v: 700 * 2 ** (1.4 * np.sin(2 * np.pi * 2 * v)), bw=0.5, n_fft=512)
    env = np.abs(np.sin(np.pi * tt / 0.225)) ** 0.5 * np.clip(tt / 0.005, 0, 1)
    b["scratch"] = _sfx_norm(n * env, 0.8, sr)

    # tape stop: a low chord whose pitch and level fall to nothing (the "everything stops" gag)
    tt = _sfx_t(0.7, sr)
    fr = 220 * (1 - tt / 0.7) ** 2 + 8
    saw = sum(_sfx_tone(fr * h * m, sr) / h for h in range(1, 7) for m in (1.0, 1.5)) * 0.5
    b["stop"] = _sfx_norm(saw * (1 - tt / 0.7) ** 2 * np.clip(tt / 0.004, 0, 1), 0.8, sr)

    # pop variant (alternation partner for list pops)
    tt = _sfx_t(0.08, sr)
    b["pop_b"] = _sfx_norm(np.sin(2 * np.pi * (600 + 2200 * tt) * tt) * np.exp(-tt * 50), 0.5, sr)
    # whoosh variant
    tt = _sfx_t(0.32, sr)
    n = rng(3).standard_normal(len(tt))
    b["whoosh_b"] = np.convolve(n, np.ones(14) / 14, "same") * np.exp(-((tt - 0.15) / 0.065) ** 2) * 0.35
    return b


# alias -> canonical name (aliases are in the bank too, but write_sfx skips them)
SFX_ALIASES = dict(thud="stamp", boom="impact", transition="soft", camera="shutter", keyclick="typewriter",
                   record_scratch="scratch", tapestop="stop", whip_pan="whip")


_SFX_CACHE = {}


def sfx_bank(sr=SR):
    """Synthesised, licence-free sounds as mono float32 arrays (fresh copies each call).

    Original four (unchanged): pop (rising chirp), whoosh (band-limited noise swell), ding
    (two-partial bell), stamp (low thud + click; alias ``thud``).
    Extended vocabulary: riser (2.4 s build, peak at the end), impact / impact_b (boom), sparkle,
    shutter / shutter_b (camera), swoosh / swoosh_b (short), whip (whip pan, peak at 0.24 s),
    soft (scene-change transition), tick / tick_b, typewriter / typewriter_b (one key), typing
    (3 s of keys; trim with ``dur``), scratch (record scratch), stop (tape stop), pop_b, whoosh_b.
    ``*_b`` = alternation partner for repeated hits. Aliases: see ``SFX_ALIASES``.
    From talkinghead ``compose.sfx_bank`` (pop/whoosh/thud), ``ding`` added, the rest new.
    """
    if sr not in _SFX_CACHE:
        t = lambda d: np.arange(int(d * sr)) / sr  # noqa: E731
        tt = t(0.09)
        pop = np.sin(2 * np.pi * (500 + 2500 * tt) * tt) * np.exp(-tt * 45) * 0.5
        tt = t(0.32)
        n = np.random.default_rng(1).standard_normal(len(tt))
        whoosh = np.convolve(n, np.ones(18) / 18, "same") * np.exp(-((tt - 0.16) / 0.07) ** 2) * 0.35
        tt = t(0.22)
        stamp = (np.sin(2 * np.pi * 95 * tt) * np.exp(-tt * 22) * 0.8
                 + np.random.default_rng(2).standard_normal(len(tt)) * np.exp(-tt * 90) * 0.25)
        tt = t(0.9)
        ding = (np.sin(2 * np.pi * 1318.5 * tt) * 0.6 + np.sin(2 * np.pi * 2637 * tt) * 0.2) * np.exp(-tt * 5.5) \
            * np.clip(tt / 0.004, 0, 1) * 0.5
        bank = dict(pop=pop, whoosh=whoosh, stamp=stamp, ding=ding, **_sfx_new(sr))
        for a, k in SFX_ALIASES.items():
            bank[a] = bank[k]
        _SFX_CACHE[sr] = {k: v.astype(np.float32) for k, v in bank.items()}
    return {k: v.copy() for k, v in _SFX_CACHE[sr].items()}


# Base linear gains applied by place_sfx (multiplied by the event's gain_db). Peaks after gain land
# around -21 dBFS (tick) to -7 dBFS (impact); see references/SOUND.md for levels vs voice and music.
SFX_GAINS = dict(pop=0.32, whoosh=0.4, stamp=0.45, thud=0.45, ding=0.35,
                 riser=0.3, impact=0.5, sparkle=0.35, shutter=0.45, swoosh=0.35, whip=0.4, soft=0.3,
                 tick=0.25, typewriter=0.3, typing=0.28, scratch=0.35, stop=0.4)


def _sfx_gain(name, gains):
    for k in (name, SFX_ALIASES.get(name), name[:-2] if name.endswith("_b") else None):
        if k and k in gains:
            return gains[k]
    return 0.4


def sfx_peak(s, sr=SR, win=0.005):
    """Seconds from the start of sample ``s`` to its energy peak (5 ms moving RMS)."""
    s = np.asarray(s, np.float64)
    if s.ndim > 1:
        s = s.mean(1)
    w = max(1, int(win * sr))
    if len(s) <= w:
        return 0.0
    c = np.concatenate([[0.0], np.cumsum(s ** 2)])
    e = c[w:] - c[:-w]
    return (int(np.argmax(e)) + w / 2) / sr


def place_sfx(x, events, sr=SR, gains=None, bank=None, peak_align=None):
    """Add SFX into audio ``x`` (n,) or (n, ch) in place. Returns x.

    events: tuples ``(t, name)`` / ``(t, name, gain_db)`` or dicts
      ``{t, sfx (or name), gain_db=0, dur=None, peak_align=True, fade=0.02}``.
      gain_db  - on top of the base level (``SFX_GAINS`` / ``gains``),
      dur      - trim the sound to ``dur`` s with a short fade-out (long samples such as ``typing``),
      peak_align - put the sound's energy PEAK (not its first sample) on ``t``; risers and whips
                 peak late, so start-aligning them makes every hit sound late.
    peak_align default: dict events True, tuple events False (backward compatible); a value passed
    here overrides that default, a per-event key overrides both.
    From talkinghead ``compose.mix_audio``.
    """
    bank = bank or sfx_bank(sr)
    gains = {**SFX_GAINS, **(gains or {})}
    for ev in events:
        if isinstance(ev, dict):
            t, k = float(ev["t"]), ev.get("sfx", ev.get("name"))
            gdb, dur, fade = float(ev.get("gain_db") or 0), ev.get("dur"), float(ev.get("fade", 0.02))
            pa = ev.get("peak_align", True if peak_align is None else peak_align)
        else:
            t, k = float(ev[0]), ev[1]
            gdb, dur, fade = (float(ev[2]) if len(ev) > 2 else 0.0), None, 0.02
            pa = bool(peak_align)
        s = bank[k]
        if dur is not None:
            s = s[:max(1, int(round(float(dur) * sr)))].copy()
            nf = min(len(s), max(1, int(min(fade, float(dur) / 4) * sr)))
            s[-nf:] *= np.linspace(1, 0, nf, dtype=np.float32)
        s = s * (_sfx_gain(k, gains) * (_db(gdb) if gdb else 1.0))
        if pa:
            t -= sfx_peak(s, sr)
        i = int(round(t * sr)) if (pa or isinstance(ev, dict)) else int(t * sr)
        if i < 0:
            s, i = s[-i:], 0
        j = min(len(x), i + len(s))
        if i < len(x) and j > i:
            x[i:j] += s[:j - i, None] if x.ndim > 1 else s[:j - i]
    return x


def write_sfx(directory, sr=SR):
    """Write every bank sound (aliases skipped) as <directory>/<name>.wav (48 kHz stereo).
    Returns {name: path}."""
    os.makedirs(directory, exist_ok=True)
    out = {}
    for k, v in sfx_bank(sr).items():
        if k in SFX_ALIASES:
            continue
        out[k] = write_wav(os.path.join(directory, f"{k}.wav"), np.stack([v, v], 1), sr)
    return out


# ---- cue sheets: a declarative SFX table + grammar rules
# A cue is {t, sfx, gain_db, dur, note}: t = where the sound's PEAK lands (render_cue_sheet peak-aligns).
_TRANSITIONS = {"soft", "swoosh", "swoosh_b", "whoosh", "whoosh_b", "whip"}
_CUT_SFX = {"scene": "soft", "move": "whoosh", "push": "whoosh", "zoom": "swoosh", "whip": "whip",
            "landing": "impact", "impact": "impact", "stop": "stop", "freeze": "scratch", "beat": None,
            "montage": None, "hard": None, "jump": None}
_REVEAL_SFX = {"text": "swoosh", "title": "swoosh", "photo": "shutter", "snap": "shutter", "landing": "impact",
               "stamp": "stamp", "small": "stamp", "item": "pop", "list": "pop", "type": "typing",
               "sparkle": "sparkle", "glow": "sparkle", "check": "ding", "ding": "ding", "tick": "tick",
               "count": "tick", "freeze": "scratch", "stop": "stop", "move": "whoosh", "whip": "whip",
               "finale": "finale"}
_PRIO = {"impact": 4, "riser": 4, "sparkle": 3, "stop": 3, "scratch": 3, "whip": 3, "soft": 2, "whoosh": 2,
         "swoosh": 2, "stamp": 2, "shutter": 2, "ding": 1, "typing": 1, "pop": 0, "tick": 0, "typewriter": 0}
# per video kind: density cap (SFX per 2 s), overall gain offset, vocabulary swaps
CUE_PROFILES = {
    "travel-fun": dict(max_per_2s=3, gain_db=0.0, swap={}),
    "promo": dict(max_per_2s=3, gain_db=0.0, swap={"pop": "tick", "ding": "sparkle", "scratch": "stop"}),
    "talking-head": dict(max_per_2s=2, gain_db=-3.0, swap={"scratch": "stop", "whip": "swoosh"}),
    "story": dict(max_per_2s=2, gain_db=-2.0, swap={"pop": "tick", "scratch": "soft", "whip": "soft",
                                                    "stop": "soft"}),
}


def _as_event(e, default):
    if isinstance(e, dict):
        return dict(e, kind=e.get("kind", default))
    return dict(t=float(e), kind=default)


def cue_sheet_for(cuts=(), reveals=(), kind="travel-fun", max_per_2s=None, beats=None, snap_tol=0.12,
                  repeat_window=1.5, step_db=1.5, max_step_db=9.0):
    """Turn edit events into a cue sheet [{t, sfx, gain_db, dur, note}] by grammar rules.

    cuts:    times or {t, kind, note}; kind 'scene' (default: one ``soft`` transition), 'move'/'push'
             (whoosh), 'zoom' (swoosh), 'whip' (whip), 'landing' (impact), 'stop' (tape stop),
             'freeze' (scratch), 'beat'/'montage'/'jump' (no SFX: the music's drums carry beat cuts).
    reveals: times or {t, kind, dur, note}; kind 'text' (default, swoosh), 'photo' (shutter),
             'landing' (impact), 'stamp', 'item'/'list' (pop), 'type' (typing trimmed to dur),
             'sparkle', 'check' (ding), 'tick'/'count', 'freeze', 'finale' (riser peaking at t ->
             impact at t -> sparkle 0.6 s later).
    kind:    video kind (``CUE_PROFILES``): density cap, gain offset, vocabulary swaps (promo and
             story drop the cartoon sounds).
    Rules applied: one transition per scene change (transitions within 0.3 s collapse to the most
    important); repeated sounds within ``repeat_window`` s alternate with their ``_b`` variant and
    step down ``step_db`` per repeat (max ``max_step_db``); impacts / finales snap to the nearest
    beat within ``snap_tol`` when ``beats`` (a ``vstudio.beats.Beats``) is given; at most
    ``max_per_2s`` cues in any 2 s window (a finale triple counts once), keeping the important ones.
    """
    prof = CUE_PROFILES.get(kind, CUE_PROFILES["travel-fun"])
    cap = int(max_per_2s if max_per_2s is not None else prof["max_per_2s"])
    swap = prof["swap"]
    raw = []

    def snap(t):
        if beats is None:
            return t
        s = float(beats.snap(t, "beat"))
        return s if abs(s - t) <= snap_tol else t

    def add(t, sfx, note, dur=None, group=None, src="reveal", gain=0.0):
        sfx = swap.get(sfx, sfx)
        raw.append(dict(t=float(t), sfx=sfx, gain_db=gain, dur=dur, note=note, group=group, src=src))

    for e in (_as_event(c, "scene") for c in cuts):
        sfx = _CUT_SFX.get(e["kind"], "soft")
        if sfx:
            t = snap(e["t"]) if sfx == "impact" else e["t"]
            add(t, sfx, e.get("note") or f"{e['kind']} cut", src="cut")
    for gi, e in enumerate(_as_event(r, "text") for r in reveals):
        sfx = _REVEAL_SFX.get(e["kind"], "swoosh")
        note = e.get("note") or f"{e['kind']} reveal"
        if sfx == "finale":
            t = snap(e["t"])
            g = f"finale{gi}"
            add(t, "riser", note + ": riser builds into the hit", group=g, gain=-2.0)
            add(t, "impact", note + ": impact (loudest moment)", group=g)
            add(t + 0.6, "sparkle", note + ": sparkle tail", group=g, gain=-3.0)
        elif sfx == "typing":
            add(e["t"], "typing", note, dur=float(e.get("dur", 1.0)))
        else:
            add(snap(e["t"]) if sfx == "impact" else e["t"], sfx, note, dur=e.get("dur"))
    raw.sort(key=lambda c: c["t"])

    # one transition per scene change: collapse transition-class cues closer than 0.3 s
    kept = []
    for c in raw:
        if c["sfx"] in _TRANSITIONS and kept:
            near = [k for k in kept if k["sfx"] in _TRANSITIONS and abs(k["t"] - c["t"]) < 0.3]
            if near:
                k = near[0]
                better = (c["src"] == "cut", _PRIO.get(c["sfx"], 1)) > (k["src"] == "cut", _PRIO.get(k["sfx"], 1))
                if better:
                    kept[kept.index(k)] = c
                continue
        kept.append(c)

    # repeats: alternate variants + step the level down
    bank_names = set(sfx_bank(SR)) if kept else set()
    last = {}
    for c in kept:
        base = c["sfx"]
        prev = last.get(base)
        j = prev[1] + 1 if prev is not None and c["t"] - prev[0] <= repeat_window else 0
        last[base] = (c["t"], j)
        if j:
            if j % 2 and base + "_b" in bank_names:
                c["sfx"] = base + "_b"
            c["gain_db"] -= min(step_db * j, max_step_db)

    # density cap (priority first, then time); a group counts once
    def units(lst):
        return sorted({(c["group"] or id(c)): c["t"] for c in lst}.values())

    order = sorted(kept, key=lambda c: (-_PRIO.get(c["sfx"].removesuffix("_b"), 1) - (2 if c["group"] else 0),
                                        c["t"]))
    final = []
    for c in order:
        trial = units(final + [c])
        ok = True
        for a in trial:
            if sum(1 for u in trial if a <= u < a + 2.0) > cap:
                ok = False
                break
        if ok or (c["group"] and any(f["group"] == c["group"] for f in final)):
            final.append(c)
    out = []
    for c in sorted(final, key=lambda c: c["t"]):
        out.append(dict(t=round(c["t"], 4), sfx=c["sfx"], gain_db=round(c["gain_db"] + prof["gain_db"], 2),
                        dur=c["dur"], note=c["note"]))
    return out


def render_cue_sheet(cues, total, sr=SR, bank=None, channels=2, gains=None):
    """Render a cue sheet to a float32 array (n, channels) of ``total`` seconds. Each cue's sound is
    peak-aligned to its ``t`` unless the cue says ``peak_align: False``. Write it with ``write_wav``
    or place it under the mix with ``place_clips``."""
    x = np.zeros((int(round(total * sr)), channels), np.float32)
    return place_sfx(x, [dict(c) for c in cues], sr=sr, gains=gains, bank=bank or sfx_bank(sr), peak_align=True)


def silence(seconds, path, sr=SR, channels=2):
    """Write a digital-silence wav. From preproduction ``make_drill.silence``."""
    return write_wav(path, np.zeros((int(round(seconds * sr)), channels), np.float32), sr)


def which_tools():
    """Diagnostic: which optional audio tools exist (soundfile, rubberband filter)."""
    try:
        import soundfile  # noqa: F401
        sf = True
    except ImportError:
        sf = False
    return dict(soundfile=sf, rubberband=media.has_filter("rubberband"), ffmpeg=shutil.which("ffmpeg") is not None)
