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
def sfx_bank(sr=SR):
    """Synthesised, licence-free UI sounds as mono float arrays: pop (rising chirp), whoosh
    (band-limited noise swell), ding (two-partial bell), stamp (low thud + click; alias ``thud``).
    From talkinghead ``compose.sfx_bank`` (pop/whoosh/thud), ``ding`` added."""
    t = lambda d: np.arange(int(d * sr)) / sr
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
    bank = dict(pop=pop, whoosh=whoosh, stamp=stamp, thud=stamp, ding=ding)
    return {k: v.astype(np.float32) for k, v in bank.items()}


SFX_GAINS = dict(pop=0.32, whoosh=0.4, stamp=0.45, thud=0.45, ding=0.35)


def place_sfx(x, events, sr=SR, gains=None, bank=None):
    """Add SFX into audio ``x`` (n,) or (n, ch) in place. events: [(t_seconds, name), ...].
    Returns x. From talkinghead ``compose.mix_audio``."""
    bank = bank or sfx_bank(sr)
    gains = {**SFX_GAINS, **(gains or {})}
    for t, k in events:
        i = int(t * sr)
        s = bank[k] * gains.get(k, 0.4)
        if i < 0:
            s, i = s[-i:], 0
        j = min(len(x), i + len(s))
        if i < len(x):
            x[i:j] += s[:j - i, None] if x.ndim > 1 else s[:j - i]
    return x


def write_sfx(directory, sr=SR):
    """Write every bank sound as <directory>/<name>.wav (48 kHz stereo). Returns {name: path}."""
    os.makedirs(directory, exist_ok=True)
    out = {}
    for k, v in sfx_bank(sr).items():
        if k == "thud":
            continue
        out[k] = write_wav(os.path.join(directory, f"{k}.wav"), np.stack([v, v], 1), sr)
    return out


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
