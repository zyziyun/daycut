"""Background music library: built-in beds generated from code (no third-party rights at all) + your own folders.

    from vstudio import music
    music.moods()                                   # ['calm', 'warm', 'bright', 'tech', 'story']
    music.mood_of("加一个轻的背景音乐，温暖一点")       # -> 'warm'
    path = music.resolve("calm", duration=95)       # a generated, cached 95 s bed (48 kHz wav, fades in / out)
    path = music.resolve("~/Music/Reelfold/x.mp3")  # a file passes through
    music.tracks()                                  # built-ins + files in your music folders (with mood / license)

    python -m vstudio.music list [--mood calm]
    python -m vstudio.music make --mood warm --duration 60 -o bed.wav [--seed 2]
    python -m vstudio.music pick "轻松一点的背景音乐" --duration 60 [-o bed.wav]

Built-in moods are synthesised here (FM e-piano, pads, Karplus-Strong plucks, sine bass, soft drums, a small
reverb), so they are free to use anywhere, commercially too. They are calm, simple beds meant to sit at -30 LUFS
under a voice, not foreground music. For real songs put files you have the rights to in a music folder:
``~/Music/Reelfold`` or persona ``music.dirs`` / env ``VSTUDIO_MUSIC_DIRS`` (os.pathsep-separated). A sidecar
``<file>.json`` {mood, license, source, title} labels a track; otherwise the mood is guessed from the file name.
Mixing and ducking under the voice: ``audio.mix_bed`` (output edit effect ``music-bed``, polish ``--music``).
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

SR = 48000
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aiff", ".aif")

# A minor = 57 (MIDI). Chords as scale-degree triads (+7th) in a key; progressions per mood.
_MAJ = [0, 2, 4, 5, 7, 9, 11]
_MIN = [0, 2, 3, 5, 7, 8, 10]
STYLES = {
    "calm": dict(bpm=72, key=60, scale=_MAJ, prog=[0, 5, 3, 4], lead="epiano", pattern="arp8", pad=0.5,
                 drums=None, bass=0.35, zh="平静 / 治愈", en="Calm, soft piano and pad"),
    "warm": dict(bpm=82, key=62, scale=_MAJ, prog=[3, 4, 2, 5], lead="epiano", pattern="chords", pad=0.35,
                 drums="lofi", bass=0.5, swing=0.12, zh="温暖 / lo-fi", en="Warm lo-fi chords, soft beat"),
    "bright": dict(bpm=108, key=65, scale=_MAJ, prog=[0, 4, 5, 3], lead="pluck", pattern="arp16", pad=0.3,
                   drums="pop", bass=0.5, zh="轻快 / 明亮", en="Bright plucks, light four-on-the-floor"),
    "tech": dict(bpm=100, key=57, scale=_MIN, prog=[0, 5, 2, 6], lead="pluck", pattern="pulse", pad=0.35,
                 drums="tech", bass=0.6, zh="科技 / 理性", en="Minor pulse arpeggio, tight hats"),
    "story": dict(bpm=64, key=57, scale=_MIN, prog=[5, 3, 0, 4], lead="epiano", pattern="sparse", pad=0.6,
                  drums=None, bass=0.3, zh="叙事 / 安静", en="Slow pad with sparse piano"),
}
KEYWORDS = {
    "calm": ["calm", "chill", "soft", "relax", "gentle", "light", "平静", "治愈", "轻", "柔", "安静的", "舒缓", "放松", "淡"],
    "warm": ["warm", "lofi", "lo-fi", "cozy", "vlog", "温暖", "温馨", "日常", "生活", "复盘", "暖"],
    "bright": ["bright", "upbeat", "happy", "fun", "energetic", "pop", "轻快", "欢快", "明亮", "活泼", "励志", "积极",
               "开心", "快节奏", "卡点"],
    "tech": ["tech", "ai", "code", "product", "explainer", "electronic", "科技", "理性", "技术", "产品", "讲解", "编程",
             "干货", "知识"],
    "story": ["story", "cinematic", "emotional", "sad", "piano", "叙事", "故事", "情绪", "文艺", "感性", "回忆", "电影感"],
}


def moods():
    return list(STYLES)


def mood_of(text, default="calm"):
    """A request / title / file name -> the best-matching mood (keyword hits; ``default`` when nothing matches)."""
    t = str(text or "").lower()
    best, score = default, 0
    for m, kws in KEYWORDS.items():
        s = sum(len(k) for k in kws if k in t)
        if m in t:
            s += 10
        if s > score:
            best, score = m, s
    return best


# ------------------------------------------------------------------ instruments
def _env(n, a, d, s, r, sr=SR):
    """ADSR (seconds; s = sustain level) over n samples, release inside n."""
    e = np.full(n, s, np.float32)
    na, nd, nr = int(a * sr), int(d * sr), int(r * sr)
    na = min(na, n)
    e[:na] = np.linspace(0, 1, na, endpoint=False) if na else e[:na]
    nd = min(nd, n - na)
    if nd > 0:
        e[na:na + nd] = np.linspace(1, s, nd, endpoint=False)
    nr = min(nr, n)
    if nr > 0:
        e[n - nr:] *= np.linspace(1, 0, nr)
    return e


def _hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def epiano(midi, dur, vel=0.6, sr=SR):
    """2-operator FM electric piano: bell-ish attack that mellows, ~1.2 s natural decay."""
    n = int((dur + 1.2) * sr)
    t = np.arange(n) / sr
    f = _hz(midi)
    idx = 1.6 * np.exp(-t * 3.0) + 0.25
    y = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))
    y += 0.25 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 2.0)
    e = np.exp(-t * (1.1 + midi / 120)) * _env(n, 0.004, 0.05, 1.0, 0.25)
    return (vel * 0.35 * y * e).astype(np.float32)


def pluck(midi, dur, vel=0.6, sr=SR, seed=0):
    """Karplus-Strong plucked string (decay ~0.8 s), soft lowpass."""
    f = _hz(midi)
    p = max(2, int(round(sr / f)))
    n = int((dur + 0.8) * sr)
    rng = np.random.default_rng(seed + midi)
    buf = rng.uniform(-1, 1, p).astype(np.float32)
    out = np.empty(n, np.float32)
    damp = 0.996 - (midi - 48) * 0.0004
    for i in range(0, n, p):                      # one period per step (vectorised inside the period)
        seg = buf.copy()
        out[i:i + p] = seg[:min(p, n - i)]
        buf = damp * 0.5 * (seg + np.roll(seg, -1))
    return (vel * 0.4 * out * _env(n, 0.002, 0.0, 1.0, 0.1)).astype(np.float32)


def pad(midis, dur, vel=0.5, sr=SR):
    """Slow detuned additive pad (a few odd/even partials per voice), soft attack / release."""
    n = int((dur + 0.6) * sr)
    t = np.arange(n) / sr
    y = np.zeros(n, np.float32)
    for m in midis:
        f = _hz(m)
        for det in (-0.12, 0.0, 0.11):
            ff = f * 2 ** (det / 12)
            for h, a in ((1, 1.0), (2, 0.35), (3, 0.18), (4, 0.08)):
                y += (a * np.sin(2 * np.pi * ff * h * t + det * 7)).astype(np.float32)
    y /= max(1, len(midis) * 3 * 1.6)
    return (vel * 0.3 * y * _env(n, min(0.9, dur / 3), 0.2, 0.85, 0.6)).astype(np.float32)


def bass(midi, dur, vel=0.6, sr=SR):
    n = int((dur + 0.15) * sr)
    t = np.arange(n) / sr
    f = _hz(midi)
    y = np.sin(2 * np.pi * f * t) + 0.15 * np.sin(2 * np.pi * 2 * f * t)
    return (vel * 0.5 * y * _env(n, 0.01, 0.1, 0.8, 0.12)).astype(np.float32)


def kick(vel=0.8, sr=SR):
    n = int(0.35 * sr)
    t = np.arange(n) / sr
    f = 45 + 90 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / sr
    return (vel * np.sin(ph) * np.exp(-t * 9)).astype(np.float32)


def noise_hit(dur, lo, hi, decay, vel, sr=SR, seed=0):
    n = int(dur * sr)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n).astype(np.float32)
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(n, 1 / sr)
    X[(fr < lo) | (fr > hi)] = 0
    x = np.fft.irfft(X, n).astype(np.float32)
    x /= max(1e-6, np.max(np.abs(x)))
    t = np.arange(n) / sr
    return (vel * x * np.exp(-t * decay)).astype(np.float32)


def reverb(x, sr=SR, t60=1.6, mix=0.22, seed=0):
    """Convolution with a decaying stereo noise tail (pre-delay 20 ms): a small hall."""
    n = int(t60 * sr)
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    out = []
    for c in range(2):
        ir = rng.standard_normal(n) * np.exp(-6.9 * t / t60)
        ir[: int(0.02 * sr)] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        L = len(x) + n
        nfft = 1 << (L - 1).bit_length()
        y = np.fft.irfft(np.fft.rfft(x[:, c], nfft) * np.fft.rfft(ir, nfft), nfft)[:len(x)]
        out.append(y)
    wet = np.stack(out, 1).astype(np.float32)
    return ((1 - mix) * x + mix * wet).astype(np.float32)


# ------------------------------------------------------------------ composition
def _chord(style, degree, octave=0):
    sc, key = style["scale"], style["key"]
    notes = [key + 12 * octave + sc[(degree + k) % 7] + 12 * ((degree + k) // 7) for k in (0, 2, 4, 6)]
    return notes


def _add(buf, x, at, pan=0.0):
    i = int(at * SR)
    if i >= len(buf):
        return
    x = x[:len(buf) - i]
    lg, rg = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(x), 0] += x * lg * 1.414
    buf[i:i + len(x), 1] += x * rg * 1.414


def generate(mood="calm", duration=60.0, seed=0):
    """Synthesise a bed of ``duration`` s -> float32 (n, 2) at 48 kHz, peak ~-6 dBFS, fade in 2 s / out 4 s,
    ending on the home chord."""
    if mood not in STYLES:
        raise ValueError(f"mood must be one of {moods()}, got {mood!r}")
    st = STYLES[mood]
    rng = np.random.default_rng(seed)
    beat = 60.0 / st["bpm"]
    bar = 4 * beat
    nbars = max(2, int(np.ceil(duration / bar)))
    total = duration
    buf = np.zeros((int((total + 3.0) * SR), 2), np.float32)
    prog = list(st["prog"])
    if seed:
        k = int(rng.integers(0, len(prog)))
        prog = prog[k:] + prog[:k]
    sw = st.get("swing", 0.0)
    for b in range(nbars):
        t0 = b * bar
        last = b == nbars - 1
        deg = 0 if last else prog[b % len(prog)]
        ch = _chord(st, deg)
        intro = b < 1
        if st["pad"]:
            _add(buf, pad([n - 12 for n in ch[:3]] + [ch[3]], bar, st["pad"]), t0)
        if st["bass"] and not intro:
            for k in range(2 if st["bpm"] < 90 else 4):
                step = bar / (2 if st["bpm"] < 90 else 4)
                _add(buf, bass(ch[0] - 24, step * 0.9, st["bass"]), t0 + k * step)
        lead = epiano if st["lead"] == "epiano" else (lambda m, d, v: pluck(m, d, v, seed=seed))
        pat = st["pattern"]
        if last:
            for i, nt in enumerate(ch[:3]):
                _add(buf, lead(nt, bar, 0.5), t0 + i * 0.03, pan=(i - 1) * 0.3)
            continue
        if pat == "chords":
            for k in (0, 2.5) if not intro else (0,):
                at = t0 + k * beat + (sw * beat if k % 1 else 0)
                for i, nt in enumerate(ch):
                    _add(buf, lead(nt, beat * 1.5, 0.42 + 0.08 * rng.random()), at + i * 0.012, pan=(i - 1.5) * 0.2)
        elif pat in ("arp8", "arp16", "pulse"):
            div = 8 if pat == "arp8" else 16
            order = [0, 1, 2, 3, 2, 1] if pat == "arp8" else [0, 2, 1, 3]
            step = bar / div
            for k in range(div):
                if intro and k >= div // 2:
                    break
                nt = ch[order[k % len(order)]] + (12 if pat == "arp16" and k % 4 == 3 else 0)
                if pat == "pulse":
                    nt = ch[0] + (12 if k % 2 else 0) + (st["scale"][4] - st["scale"][0] if k % 8 >= 6 else 0)
                v = (0.5 if k % 4 == 0 else 0.33) * (0.9 + 0.2 * rng.random())
                at = t0 + k * step + (sw * step if k % 2 else 0)
                _add(buf, lead(nt, step * 1.6, v), at, pan=0.35 * np.sin(k))
        elif pat == "sparse":
            for k in sorted(rng.choice(8, size=3, replace=False)):
                nt = ch[int(rng.integers(0, 4))] + 12
                _add(buf, lead(nt, beat * 2, 0.35), t0 + k * bar / 8, pan=float(rng.uniform(-0.4, 0.4)))
        dr = st["drums"]
        if dr and not intro:
            for k in range(4):
                at = t0 + k * beat
                if dr in ("pop",) or (dr in ("lofi", "tech") and k in (0, 2)):
                    _add(buf, kick(0.55 if dr == "lofi" else 0.65), at)
                if dr == "pop" and k in (1, 3):
                    _add(buf, noise_hit(0.18, 900, 6000, 22, 0.22, seed=b * 4 + k), at)
                if dr == "lofi" and k in (1, 3):
                    _add(buf, noise_hit(0.12, 1500, 5000, 30, 0.12, seed=b * 4 + k), at + sw * beat * 0.3)
                for h in (0, 1) if dr != "tech" else (0, 1, 2, 3):
                    sub = beat / (2 if dr != "tech" else 4)
                    _add(buf, noise_hit(0.05, 7000, 16000, 70, 0.06 if h else 0.09, seed=b * 16 + k * 4 + h),
                         at + h * sub + (sw * sub if h % 2 else 0), pan=0.3)
    y = reverb(buf, t60=1.8 if mood in ("calm", "story") else 1.2, mix=0.28 if mood in ("calm", "story") else 0.18,
               seed=seed)
    n = int(total * SR)
    y = y[:n]
    t = np.arange(n) / SR
    g = np.clip(t / 2.0, 0, 1) * np.clip((total - t) / min(4.0, total / 3), 0, 1)
    y *= g[:, None]
    pk = float(np.max(np.abs(y))) or 1.0
    return (y * (0.5 / pk)).astype(np.float32)


# ------------------------------------------------------------------ library
def _cache():
    from .config import cache_dir
    return cache_dir("music")


def dirs():
    """Your music folders: env VSTUDIO_MUSIC_DIRS, persona music.dirs, ~/Music/Reelfold (existing ones only)."""
    out = [p for p in (os.environ.get("VSTUDIO_MUSIC_DIRS") or "").split(os.pathsep) if p]
    try:
        from .config import persona
        out += list(((persona().get("music") or {}).get("dirs")) or [])
    except Exception:  # noqa: BLE001
        pass
    out.append("~/Music/Reelfold")
    seen, res = set(), []
    for p in out:
        q = os.path.abspath(os.path.expanduser(str(p)))
        if q not in seen and os.path.isdir(q):
            seen.add(q)
            res.append(q)
    return res


def _sidecar(path):
    for p in (path + ".json", os.path.splitext(path)[0] + ".json"):
        if os.path.exists(p):
            try:
                with open(p) as f:
                    d = json.load(f)
                return d if isinstance(d, dict) else {}
            except (OSError, ValueError):
                return {}
    return {}


def tracks(mood=None):
    """Built-in moods + files in your music folders: [{id, title, mood, source builtin|file, path?, license}]."""
    out = [dict(id=f"builtin:{m}", title=s["en"], title_zh=s["zh"], mood=m, source="builtin", bpm=s["bpm"],
                license="generated by Reelfold (MIT), free for any use") for m, s in STYLES.items()]
    for d in dirs():
        for root, _, files in os.walk(d):
            for fn in sorted(files):
                if not fn.lower().endswith(AUDIO_EXT):
                    continue
                p = os.path.join(root, fn)
                sc = _sidecar(p)
                m = sc.get("mood") if sc.get("mood") in STYLES else mood_of(sc.get("title") or fn, default="calm")
                out.append(dict(id=p, title=sc.get("title") or os.path.splitext(fn)[0], mood=m, source="file", path=p,
                                license=sc.get("license") or "yours (check you may use it)", origin=sc.get("source")))
    return [t for t in out if mood is None or t["mood"] == mood]


def _key(mood, duration, seed):
    return hashlib.sha1(json.dumps([mood, round(float(duration), 2), int(seed), 1]).encode()).hexdigest()[:12]


def make(mood="calm", duration=60.0, out=None, seed=0):
    """Generate (or reuse the cached) built-in bed -> wav path."""
    from . import audio as A
    if out is None:
        out = os.path.join(_cache(), f"{mood}-{_key(mood, duration, seed)}.wav")
        if os.path.exists(out):
            return out
    tmp = out + ".part.wav"
    A.write_wav(tmp, generate(mood, duration, seed), SR)
    os.replace(tmp, out)
    return out


def resolve(spec, duration=60.0, seed=0, text=None):
    """``spec`` = an existing file | 'builtin:<mood>' | a mood | a library track title | None (mood from ``text``:
    your own track of that mood, else the built-in) -> a playable file path. Built-ins are generated to
    ``duration`` (cached). Anything else raises ValueError."""
    if spec and os.path.exists(os.path.expanduser(str(spec))):
        return os.path.abspath(os.path.expanduser(str(spec)))
    s = str(spec or "").strip()
    if s.startswith("builtin:"):
        s = s.split(":", 1)[1]
    if s in STYLES:
        return make(s, duration, seed=seed)
    if s:
        for t in tracks():
            if t["source"] == "file" and (t["title"] == s or os.path.basename(t["path"]) == s):
                return t["path"]
        raise ValueError(f"no music file, mood or library track called {spec!r} (moods: {', '.join(moods())})")
    m = mood_of(text or "")
    own = tracks(m)
    files = [t for t in own if t["source"] == "file"]
    if files:                                          # your own track of that mood first
        return files[int(seed) % len(files)]["path"]
    return make(m, duration, seed=seed)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.music", description="Background music library.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list")
    a.add_argument("--mood", choices=moods())
    a.add_argument("--json", action="store_true")
    b = sub.add_parser("make")
    b.add_argument("--mood", default="calm", choices=moods())
    b.add_argument("--duration", type=float, default=60.0)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("-o", "--out", required=True)
    c = sub.add_parser("pick")
    c.add_argument("text")
    c.add_argument("--duration", type=float, default=60.0)
    c.add_argument("-o", "--out")
    x = ap.parse_args(argv)
    if x.cmd == "list":
        rows = tracks(x.mood)
        if x.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for t in rows:
                print(f"{t['mood']:>7}  {t['source']:<7}  {t['title']}  ({t['license']})")
            if not dirs():
                print("  (no music folders yet: put licensed tracks in ~/Music/Reelfold or set persona music.dirs)")
    elif x.cmd == "make":
        print(make(x.mood, x.duration, x.out, x.seed))
    else:
        p = resolve(None, x.duration, text=x.text)
        if x.out:
            import shutil
            shutil.copy(p, x.out)
            p = x.out
        print(f"{mood_of(x.text)}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

