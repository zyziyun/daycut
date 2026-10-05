#!/usr/bin/env python3
"""Rank cover-frame candidates: big smile, eyes open, face centered
(score = mouthSmile - 1.5*eyeBlink - |cx-0.5|, candidates at least 2 s apart).
usage: python3 pick_cover_frame.py body3_rt.mp4 [top_n]  -> prints times + writes cover_candidates.jpg"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import cv2, numpy as np
from vstudio import face as VF
src = sys.argv[1]; top = int(sys.argv[2]) if len(sys.argv) > 2 else 6
lm = VF.landmarker(1); cap = cv2.VideoCapture(src); res = []; i = 0
while True:
    ok, img = cap.read()
    if not ok: break
    if i % 5 == 0:
        f = VF.main_face(VF.detect(lm, cv2.resize(img, (540, 960))))
        if f is not None and f['blend']:
            b = f['blend']; cx = f['pts'][:, 0].mean() / 540
            sm = (b['mouthSmileLeft'] + b['mouthSmileRight']) / 2; bl = (b['eyeBlinkLeft'] + b['eyeBlinkRight']) / 2
            res.append((sm - 1.5 * bl - abs(cx - 0.5), i, i / 30))
    i += 1
res.sort(reverse=True); picks = []
for sc, fi, t in res:
    if all(abs(t - p[2]) > 2 for p in picks): picks.append((sc, fi, t))
    if len(picks) == top: break
tiles = []
for sc, fi, t in picks:
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi); ok, img = cap.read()
    img = cv2.resize(img[200:1640], (270, 360)); cv2.putText(img, f'{t:.2f}', (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    tiles.append(img); print(f't={t:.3f}  frame={fi}  score={sc:.3f}')
if tiles:
    cv2.imwrite('cover_candidates.jpg', np.hstack(tiles)); print('wrote cover_candidates.jpg (use frame-index seek, not -ss, for the exact frame)')
else:
    print('no face found')
