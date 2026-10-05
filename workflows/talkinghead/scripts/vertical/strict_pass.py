#!/usr/bin/env python3
"""Strict disfluency pass on an existing body (keeps the retouch, no re-render of it).
1) python strict_pass.py transcribe body_a.wav "术语 prompt"   -> bw.json + indexed word list printed
   Also writes strict_suggest.json + strict_draft.py: DEL pre-filled ONLY with high-confidence
   candidates (standalone 嗯/呃/um/uh, stutter repeats); semantic fillers (就是 那个 然后), merged-filler /
   "hidden onset" PATCHes and 2-word repeats are listed under CONFIRM and need the creator's yes.
2) the creator confirms the DEL list; copy strict_draft.py to strict.py and edit:
       DEL = {13, 18, 25, ...}            # word indices from step 1 (confirmed)
       TEXT = {3: "职业发展的初期|对于大家的习惯", ...}   # optional subtitle rewrites per sid
3) python strict_pass.py apply strict.py IN_V IN_A OUT_V OUT_A
   -> pauses squeezed to KEEPGAP, segs.json rewritten (subs keep their sid, words carry new times).
4) python strict_pass.py verify strict.py OUT_A ["术语 prompt"]
   -> re-ASR the cut and compare with the original words minus DEL; flags missing content words
      (exit 1 when something is missing: listen, then remove that index from DEL and re-apply)."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import json, shutil, importlib.util
from bodycut import cut_body, dbenv, remap, q
from vstudio import asr, audio, cut
import filler_policy as fp
if sys.argv[1] == 'verify':
    import os, importlib.util as ilu
    sp = ilu.spec_from_file_location('st', sys.argv[2]); st = ilu.module_from_spec(sp); sp.loader.exec_module(st)
    ws = json.load(open('bw.json'))
    if os.path.exists('segs_prev.json'):
        t0 = json.load(open('segs_prev.json'))['total']; ws = [w for w in ws if w['b0'] < t0 - 0.05]
    expected = [w for i, w in enumerate(ws) if i not in st.DEL]
    got = asr.transcribe(sys.argv[3], prompt=sys.argv[4] if len(sys.argv) > 4 else None)['words']
    flags = fp.content_check(expected, got, fillers=cut.FILLERS_ZH + cut.FILLERS_EN)
    fp.print_flags(flags, f' ({sys.argv[3]})')
    for f in flags:   # map back to bw.json indices near the flag so the DEL entry is easy to find
        near = [i for i, w in enumerate(ws) if abs(w['b0'] - f['t']) < 1.0]
        print(f"     bw idx near: {near}  DEL there: {sorted(set(near) & set(st.DEL))}")
    sys.exit(1 if flags else 0)
if sys.argv[1] == 'transcribe':
    # vstudio.asr: mlx_whisper -> faster_whisper -> OpenAI, cached in body_a.wav.asr.json, term-fixed, with
    # whisper's zero-length repeated tail words dropped BEFORE indexing so DEL indices stay valid
    tr = asr.transcribe(sys.argv[2], prompt=sys.argv[3] if len(sys.argv) > 3 else None)
    ws = [dict(w=w['w'], b0=round(w['t'], 2), b1=round(w['te'], 2)) for w in tr['words']]
    json.dump(ws, open('bw.json', 'w'), ensure_ascii=False); line = ''
    for i, w in enumerate(ws):
        line += f"{i}:{w['w']}[{w['b0']:.1f}] "
        if len(line) > 150: print(line); line = ''
    print(line)
    # review aid (vstudio.cut.suggest_fillers), scored by filler_policy: only "auto" rows are pre-filled
    sug = fp.score(cut.suggest_fillers(tr['words'], audio=sys.argv[2]))
    for r in sug:
        r['idx'] = [i for i, w in enumerate(tr['words']) if r['start'] - 0.005 <= w['t'] < max(r['end'], r['start'] + 0.01) - 0.005]
    auto, confirm, info = fp.split_tiers(sug)
    json.dump(sug, open('strict_suggest.json', 'w'), ensure_ascii=False, indent=1)
    for title, rows in (('AUTO (high confidence, pre-filled - still listen)', auto),
                        ('CONFIRM (creator must say yes; often real words)', confirm), ('INFO (listen, no cut)', info)):
        if rows: print(f'\n{title}:')
        for r in rows:
            print(f"  {r['conf']:.2f} {r['kind']:<12} {r['text']:<8} idx {r['idx']}  {r['why']}. {r['note']}")
    auto_idx = sorted({i for r in auto for i in r['idx']})
    with open('strict_draft.py', 'w') as f:
        f.write('"""strict_pass DEL draft. The creator confirms this list before apply. AUTO = high-confidence only;\n'
                'move CONFIRM indices into DEL only after listening (they are often real words)."""\n')
        f.write(f'DEL = {set(auto_idx) or "set()"}\n')
        f.write('# CONFIRM (not applied):\n')
        for r in confirm: f.write(f"#   {r['idx']}  {r['kind']} '{r['text']}'  {r['why']}\n")
        f.write('TEXT = {}\n')
    print(f"\nstrict_draft.py: DEL = {auto_idx} ({len(auto)} auto, {len(confirm)} to confirm). "
          'Show the creator AUTO + CONFIRM, then copy to strict.py; after apply run `verify`.')
    sys.exit()
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[2]))); sys.path.insert(0, os.getcwd())
spec = importlib.util.spec_from_file_location('st', sys.argv[2]); st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
IN_V, IN_A, OUT_V, OUT_A = sys.argv[3:7]
DEL = st.DEL; TEXT = getattr(st, 'TEXT', {}); TH = getattr(st, 'TH', -45); MAXGAP = getattr(st, 'MAXGAP', 0.12)
from vstudio.config import persona
KEEPGAP = getattr(st, 'KEEPGAP', (persona().get('audio') or {}).get('pause_squeeze', 0.06))   # 气口 target
prev = json.load(open('segs.json')); shutil.copy('segs.json', 'segs_prev.json'); total0 = prev['total']
ws = json.load(open('bw.json'))
ws = [w for w in ws if w['b0'] < total0 - 0.05]          # whisper hallucinates over the tail

x, sr = audio.read_wav(IN_A, mono=True); r = dbenv(x, sr)   # 10 ms dB
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
    lo, hi = int(a * 100), int(b * 100)
    mg = audio.voiced_runs(r[lo:hi], 0.01, TH, min_run=0.03, max_gap=MAXGAP, t0=lo / 100)
    if not mg: continue
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
