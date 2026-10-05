#!/usr/bin/env python3
"""Cut whole padding sentences (废话) out of the current body by sid.
usage: python drop_pass.py "1,7,11,17" IN_V IN_A OUT_V OUT_A   -> segs.json remapped (sids preserved)."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import sys, json, shutil
from bodycut import cut_body, remap, q
DROP = {int(x) for x in sys.argv[1].split(',') if x.strip()}; IN_V, IN_A, OUT_V, OUT_A = sys.argv[2:6]
d = json.load(open('segs.json')); shutil.copy('segs.json', 'segs_prev.json'); keep = []
for s in d['subs']:
    if s['sid'] in DROP: continue
    a, b = q(s['start']), q(s['end'])
    if keep and abs(keep[-1][1] - a) < 1e-6: keep[-1][1] = b
    else: keep.append([a, b])
T = cut_body(IN_V, IN_A, keep, OUT_V, OUT_A, 'seg_drop'); m = remap(keep)
subs = [dict(sid=s['sid'], text=s['text'], start=m(s['start']), end=m(s['end'] - 1e-4)) for s in d['subs'] if s['sid'] not in DROP]
words = [dict(w, b0=m(w['b0']), b1=m(w['b1'])) for w in d.get('words', []) if w.get('sid') not in DROP]
json.dump(dict(subs=subs, words=words, total=T, keep=keep), open('segs.json', 'w'), ensure_ascii=False, indent=1)
print(f'dropped {sorted(DROP)}: body {d["total"]:.1f}s -> {T:.1f}s')
