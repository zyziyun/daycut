#!/usr/bin/env python3
"""Pass 1: hand-written keep list -> one body. Snaps each range to voiced audio, squeezes
pauses/breaths, cuts frame-exact video segments, splices audio sample-exact.
usage (in WORK): python cut_pass1.py edit_list.py   -> body_v.mp4 body_a.wav segs.json
(reads a<N>.wav for snapping and sdr<N>.mp4 for picture + sound, from prep_sources.sh)
edit_list.py defines  E = [(clip_no, [(t0, t1), ...], "subtitle|with|manual breaks"), ...]
one entry per sentence; its index becomes the sentence id (sid) used everywhere later."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import json, importlib.util
from vstudio import audio
from bodycut import F, cut_sources, dbenv
spec = importlib.util.spec_from_file_location('el', sys.argv[1]); el = importlib.util.module_from_spec(spec); spec.loader.exec_module(el)
E = el.E
TH = getattr(el, 'TH', -45.0); MAXGAP = getattr(el, 'MAXGAP', 0.20); KEEPGAP = getattr(el, 'KEEPGAP', 0.10)
env = {}
for c in sorted({e[0] for e in E}):           # 10 ms dB envelope of the 16 kHz mono ASR wav
    x, sr = audio.read_wav(f'a{c}.wav', mono=True); env[c] = dbenv(x, sr)
segs = []
for sid, (c, ranges, text) in enumerate(E):
    for t0, t1 in ranges:
        r = env[c]; a = max(0, int((t0 - .08) * 100)); b = min(len(r), int((t1 + .10) * 100))
        m = audio.voiced_runs(r[a:b], 0.01, TH, min_run=0.03, max_gap=MAXGAP, t0=a / 100)
        if not m: print('NO VOICE', sid, text); continue
        for k, (s, e) in enumerate(m):
            s -= .05 if k == 0 else KEEPGAP / 2; e += .07 if k == len(m) - 1 else KEEPGAP / 2
            s = max(0.0, s)   # a range at t~0 must not go negative
            if e - s >= .08: segs.append(dict(clip=c, t0=s, t1=e, sid=sid))
# frame-exact cut + sample-exact audio from each clip's own a/v (vstudio.cut.cut_segments via bodycut)
T = cut_sources([(f"sdr{s['clip']}.mp4", s['t0'], s['t1']) for s in segs], 'body_v.mp4', 'body_a.wav', 'seg1')
t = 0.0; st = {}
for s in segs:
    n = round(s['t1'] * F) - round(s['t0'] * F)
    st.setdefault(s['sid'], [t, t]); t += n / F; st[s['sid']][1] = t
subs = [dict(sid=i, text=E[i][2], start=round(st[i][0], 3), end=round(st[i][1], 3)) for i in sorted(st)]
json.dump(dict(subs=subs, total=T), open('segs.json', 'w'), ensure_ascii=False, indent=1)
print(f'{len(segs)} segments -> body {T:.1f}s')
