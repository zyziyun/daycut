#!/usr/bin/env python3
"""Strict disfluency pass on an existing body (keeps the retouch, no re-render of it).
1) python strict_pass.py transcribe body_a.wav "术语 prompt"   -> bw.json + indexed word list printed
2) mark leftover fillers / repeats / stray syllables in strict.py:
       DEL = {13, 18, 25, ...}            # word indices from step 1
       TEXT = {3: "职业发展的初期|对于大家的习惯", ...}   # optional subtitle rewrites per sid
3) python strict_pass.py apply strict.py IN_V IN_A OUT_V OUT_A
   -> pauses squeezed to KEEPGAP, segs.json rewritten (subs keep their sid, words carry new times)."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import sys, json, shutil, importlib.util, numpy as np, soundfile as sf
from bodycut import cut_body, remap, q
if sys.argv[1] == 'transcribe':
    import subprocess
    from asr import transcribe          # mlx_whisper if available, else faster_whisper
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', sys.argv[2], '-ac', '1', '-ar', '16000', '_b16.wav'], check=True)
    r = transcribe('_b16.wav', prompt=sys.argv[3] if len(sys.argv) > 3 else None)
    ws = [dict(w=w['word'].strip(), b0=round(w['start'], 2), b1=round(w['end'], 2)) for s in r['segments'] for w in s['words']]
    # tail hallucination = burst of zero-length / repeated words ("feed feed feed"); drop BEFORE indexing so DEL indices stay valid
    ws = [w for k, w in enumerate(ws) if not (k and w['b1'] - w['b0'] < 0.02 and w['w'] == ws[k - 1]['w'])]
    json.dump(ws, open('bw.json', 'w'), ensure_ascii=False); line = ''
    for i, w in enumerate(ws):
        line += f"{i}:{w['w']}[{w['b0']:.1f}] "
        if len(line) > 150: print(line); line = ''
    print(line); sys.exit()
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[2]))); sys.path.insert(0, os.getcwd())
spec = importlib.util.spec_from_file_location('st', sys.argv[2]); st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
IN_V, IN_A, OUT_V, OUT_A = sys.argv[3:7]
DEL = st.DEL; TEXT = getattr(st, 'TEXT', {}); TH = getattr(st, 'TH', -45); MAXGAP = getattr(st, 'MAXGAP', 0.12)
from vstudio.config import persona
KEEPGAP = getattr(st, 'KEEPGAP', (persona().get('audio') or {}).get('pause_squeeze', 0.06))   # 气口 target
prev = json.load(open('segs.json')); shutil.copy('segs.json', 'segs_prev.json'); total0 = prev['total']
ws = json.load(open('bw.json'))
ws = [w for w in ws if w['b0'] < total0 - 0.05]          # whisper hallucinates over the tail

x, sr = sf.read(IN_A); mono = x.mean(1) if x.ndim > 1 else x; n = sr // 100
r = 20 * np.log10(np.sqrt((mono[:len(mono)//n*n].reshape(-1, n)**2).mean(1)) + 1e-9); r = np.convolve(r, np.ones(3)/3, 'same')
runs = []; i = 0; pend = 0.0
while i < len(ws):
    if i in DEL: pend = ws[i]['b1']; i += 1; continue
    j = i
    while j + 1 < len(ws) and j + 1 not in DEL: j += 1
    b = ws[j]['b1'] + 0.04
    if j + 1 < len(ws): b = min(b, ws[j + 1]['b1'] - 0.12)
    runs.append((pend, b, list(range(i, j + 1)))); pend = ws[j]['b1']; i = j + 1
runs[-1] = (runs[-1][0], total0, runs[-1][2])
segs = []
for a, b, _ in runs:
    lo, hi = int(a * 100), int(b * 100); v = r[lo:hi] > TH; vr = []; k = 0
    while k < len(v):
        if v[k]:
            m = k
            while m < len(v) and v[m]: m += 1
            if m - k >= 3: vr.append([(lo + k) / 100, (lo + m) / 100])
            k = m
        else: k += 1
    if not vr: continue
    mg = [vr[0]]
    for s, e in vr[1:]:
        if s - mg[-1][1] <= MAXGAP: mg[-1][1] = e
        else: mg.append([s, e])
    for qq, (s, e) in enumerate(mg):
        segs.append((max(0, s - (0.04 if qq == 0 else KEEPGAP / 2)), min(total0, e + (0.06 if qq == len(mg) - 1 else KEEPGAP / 2))))
segs.sort(); keep = []
for s, e in segs:
    if keep and s <= keep[-1][1]: keep[-1][1] = max(keep[-1][1], e)
    else: keep.append([s, e])
keep = [(q(s), q(e)) for s, e in keep if e - s > 0.05]
T = cut_body(IN_V, IN_A, keep, OUT_V, OUT_A, 'seg_strict'); m = remap(keep)
def old_sid(t):
    for s in prev['subs']:
        if s['start'] - 0.15 <= t < s['end'] - 0.15: return s['sid']
    return prev['subs'][-1]['sid']
words = [dict(w=ws[i]['w'], b0=m(ws[i]['b0']), b1=m(ws[i]['b1']), sid=old_sid(ws[i]['b0'])) for _, _, idx in runs for i in idx]
first = {}
for w in words: first.setdefault(w['sid'], w['b0'])
sids = [s['sid'] for s in prev['subs'] if s['sid'] in first]; subs = []
for k, sid in enumerate(sids):
    st0 = 0.0 if k == 0 else subs[-1]['end']; en = first[sids[k + 1]] if k + 1 < len(sids) else T
    old = next(s['text'] for s in prev['subs'] if s['sid'] == sid)
    subs.append(dict(sid=sid, text=TEXT.get(sid, old), start=round(st0, 3), end=round(en, 3)))
json.dump(dict(subs=subs, words=words, total=T, keep=keep), open('segs.json', 'w'), ensure_ascii=False, indent=1)
print(f'{len(keep)} ranges, body {total0:.1f}s -> {T:.1f}s. Re-read every subtitle against the audio:')
for s in subs:
    print(s['sid'], ''.join(w['w'] for w in words if w['sid'] == s['sid']), ' || ', s['text'])
