#!/usr/bin/env python3
"""Cut whole padding sentences (废话) out of the current body by sid.
usage: python drop_pass.py "1,7,11,17" IN_V IN_A OUT_V OUT_A   -> segs.drop.json + segs.json (sids preserved).
IN must be the strict body (or the pass-1 body when no strict pass was run); the cut is derived from that
stage's immutable segs.<stage>.json, so re-running with another list REPLACES the previous drop (give the
full list every time). An already-dropped body is refused instead of being cut twice.
Also writes <OUT_A stem>.cleanup.json (vstudio.cleanup sidecar), so `python -m vstudio.cleanup verify OUT_A`
checks that only the dropped sentences went missing."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, json
from bodycut import F, cut_body, on_body, remap, q, pick_parent, save_stage
from vstudio import cleanup
DROP = {int(x) for x in sys.argv[1].split(',') if x.strip()}; IN_V, IN_A, OUT_V, OUT_A = sys.argv[2:6]
parent, d = pick_parent(IN_A, ['strict', 'pass1']); keep = []
if os.path.exists('segs.drop.json'):
    old = json.load(open('segs.drop.json')).get('dropped')
    if old is not None and set(old) != DROP: print(f'replacing the previous drop list {old}')
for s in d['subs']:
    if s['sid'] in DROP: continue
    a, b = q(s['start']), q(s['end'])
    if keep and abs(keep[-1][1] - a) < 1e-6: keep[-1][1] = b
    else: keep.append([a, b])
T = cut_body(IN_V, IN_A, keep, OUT_V, OUT_A, 'seg_drop'); m = remap(keep)
subs = [dict(sid=s['sid'], text=s['text'], start=m(s['start']), end=m(s['end'] - 1e-4)) for s in d['subs'] if s['sid'] not in DROP]
words = [dict(w, b0=m(w['b0']), b1=m(w['b1'])) for w in d.get('words', []) if w.get('sid') not in DROP]
src_words = d.get('words') or d.get('body_words') or []
side = cleanup.write_sidecar(OUT_A, IN_A, keep, on_body([w for w in src_words if w.get('sid') not in DROP]),
                             d.get('language'), fps=F, dropped=sorted(DROP))
save_stage('drop', dict(subs=subs, words=words, total=T, keep=keep, dropped=sorted(DROP), sidecar=side), parent=parent)
print(f'dropped {sorted(DROP)} from the {parent} body: body {d["total"]:.1f}s -> {T:.1f}s')
