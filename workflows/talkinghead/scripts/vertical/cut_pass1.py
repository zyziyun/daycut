#!/usr/bin/env python3
"""Pass 1: hand-written keep list -> one body. Snaps each range to voiced audio, squeezes
pauses/breaths, cuts frame-exact video segments, splices audio sample-exact.
usage (in WORK): python cut_pass1.py edit_list.py   -> body_v.mp4 body_a.wav segs.json
edit_list.py defines  E = [(clip_no, [(t0, t1), ...], "subtitle|with|manual breaks"), ...]
one entry per sentence; its index becomes the sentence id (sid) used everywhere later."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import sys, os, json, subprocess, importlib.util, numpy as np, soundfile as sf
from concurrent.futures import ThreadPoolExecutor
spec = importlib.util.spec_from_file_location('el', sys.argv[1]); el = importlib.util.module_from_spec(spec); spec.loader.exec_module(el)
E = el.E; F = 30; SR = 48000
TH = getattr(el, 'TH', -45.0); MAXGAP = getattr(el, 'MAXGAP', 0.20); KEEPGAP = getattr(el, 'KEEPGAP', 0.10)
env = {}
for c in sorted({e[0] for e in E}):
    x, sr = sf.read(f'a{c}.wav'); n = sr // 100
    r = 20 * np.log10(np.sqrt((x[:len(x)//n*n].reshape(-1, n)**2).mean(1)) + 1e-9); env[c] = np.convolve(r, np.ones(3)/3, 'same')
segs = []
for sid, (c, ranges, text) in enumerate(E):
    for t0, t1 in ranges:
        r = env[c]; a = max(0, int((t0 - .08) * 100)); b = min(len(r), int((t1 + .10) * 100)); v = r[a:b] > TH; runs = []; k = 0
        while k < len(v):
            if v[k]:
                j = k
                while j < len(v) and v[j]: j += 1
                if j - k >= 3: runs.append([(a + k) / 100, (a + j) / 100])
                k = j
            else: k += 1
        if not runs: print('NO VOICE', sid, text); continue
        m = [runs[0]]
        for s, e in runs[1:]:
            if s - m[-1][1] <= MAXGAP: m[-1][1] = e
            else: m.append([s, e])
        for q, (s, e) in enumerate(m):
            s -= .05 if q == 0 else KEEPGAP / 2; e += .07 if q == len(m) - 1 else KEEPGAP / 2
            s = max(0.0, s)   # a range at t~0 must not go negative (bad trim + wrapped numpy slice)
            if e - s >= .08: segs.append(dict(clip=c, t0=s, t1=e, sid=sid))
os.makedirs('seg1', exist_ok=True)
def job(ks):
    k, s = ks; a = round(s['t0'] * F); n = round(s['t1'] * F) - a; out = f'seg1/{k:04d}.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f"sdr{s['clip']}.mp4", '-an', '-vf',
                    f"fps=30,trim=start_frame={a}:end_frame={a+n},setpts=PTS-STARTPTS,setsar=1", '-c:v', 'libx264', '-crf', '12',
                    '-preset', 'fast', '-pix_fmt', 'yuv420p', '-video_track_timescale', '30000', out], check=True); return out
with ThreadPoolExecutor(6) as ex: outs = list(ex.map(job, enumerate(segs)))
open('seg1/list.txt', 'w').write(''.join(f"file '{os.path.basename(o)}'\n" for o in outs))
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', 'seg1/list.txt', '-c', 'copy', 'body_v.mp4'], check=True)
aud = {c: sf.read(f'a48_{c}.wav')[0] for c in env}; parts = []; fd = int(.012 * SR); T = 0; st = {}
for s in segs:
    a = round(s['t0'] * F); n = round(s['t1'] * F) - a; x = aud[s['clip']][a*SR//F:(a+n)*SR//F].copy()
    x = np.pad(x, ((0, n*SR//F - len(x)), (0, 0))); r = np.linspace(0, 1, fd)[:, None]; x[:fd] *= r; x[-fd:] *= r[::-1]; parts.append(x)
    st.setdefault(s['sid'], [T, T]); T += n / F; st[s['sid']][1] = T
sf.write('body_a.wav', np.concatenate(parts), SR, subtype='PCM_16')
subs = [dict(sid=i, text=E[i][2], start=round(st[i][0], 3), end=round(st[i][1], 3)) for i in sorted(st)]
json.dump(dict(subs=subs, total=T), open('segs.json', 'w'), ensure_ascii=False, indent=1)
print(f'{len(segs)} segments -> body {T:.1f}s')
