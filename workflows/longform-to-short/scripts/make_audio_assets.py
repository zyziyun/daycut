#!/usr/bin/env python3
"""Step 6c: synthesize the chapter-card stinger (license-free, no samples).

card_sting.wav  ~1.6 s soft band-limited whoosh + low thump, peak -19 dBFS.
--hook-bed also writes hook_bgm.wav (12 s ambient A-minor pad). Kept for completeness but
NOT recommended: a synthesized bed under a lecture cold-open tested as odd. Default is no BGM.

Usage: python3 make_audio_assets.py work/config.py [--hook-bed]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import numpy as np
import soundfile as sf
from numpy.fft import irfft, rfft

import _lfc


def extra(ap):
    ap.add_argument("--hook-bed", action="store_true", help="also write hook_bgm.wav (not recommended)")


cfg, args = _lfc.load(description=__doc__, extra=extra)
SR = 48000
rng = np.random.default_rng(7)


def norm_to(x, peak_db):
    return x / (np.max(np.abs(x)) + 1e-9) * (10 ** (peak_db / 20))


def write(name, mono, haas):
    st = np.stack([mono, np.roll(mono, haas)], axis=1)
    sf.write(name, (st * 32767).astype(np.int16), SR, subtype="PCM_16")   # 16-bit PCM stereo WAV


D2 = float(cfg.get("cards.dur", 1.6))
t2 = np.arange(int(SR * D2)) / SR
spec = rfft(rng.standard_normal(len(t2)))
spec *= np.exp(-((np.fft.rfftfreq(len(t2), 1 / SR) - 1200) ** 2) / (2 * 900 ** 2))
whoosh = irfft(spec, len(t2))
whoosh = whoosh / (np.max(np.abs(whoosh)) + 1e-9)
whoosh *= np.clip(t2 / 0.35, 0, 1) * np.exp(-np.clip(t2 - 0.45, 0, None) * 4.5)
thump = np.sin(2 * np.pi * 110 * t2) * np.exp(-t2 * 9) * 0.8
write("card_sting.wav", norm_to(whoosh * 0.8 + thump, -19.0), 180)
print("card_sting.wav")

if args.hook_bed:
    DUR = 12.0
    t = np.arange(int(SR * DUR)) / SR
    pad = np.zeros_like(t)
    for f in [110.0, 164.81, 220.0, 261.63, 329.63]:
        for det in (-0.15, 0.12):
            ph = rng.uniform(0, 2 * np.pi)
            lfo = 1 + 0.08 * np.sin(2 * np.pi * rng.uniform(0.07, 0.16) * t + ph)
            pad += np.sin(2 * np.pi * (f + det) * t + ph) * lfo
    pad /= 10
    sp = rfft(rng.standard_normal(len(t)))
    sp *= np.exp(-((np.fft.rfftfreq(len(t), 1 / SR) - 1200) ** 2) / (2 * 600 ** 2)) * 0.5
    sh = irfft(sp, len(t))
    mix = pad + 0.10 * sh / (np.max(np.abs(sh)) + 1e-9)
    mix *= np.minimum(t / 2.2, 1.0) * np.clip((DUR - t) / 2.5, 0, 1.0)
    write("hook_bgm.wav", norm_to(mix, -21.0), 240)
    print("hook_bgm.wav (not mixed by render.py; add it yourself if you really want it)")
