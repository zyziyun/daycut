#!/usr/bin/env python3
"""Track the main face on the CURRENT body video (every 3rd frame) -> face_track.npy
rows = (body_time, cx, cy, face_width, x0, y0, x1, y1) in body pixels (box = landmark extent, forehead..chin).
compose.py uses it to centre zooms and circle insets, cap the punch-in by face size, and keep the hook
title, callouts, PiP cards and pop words off the face. Older 4-column files still work (box estimated).
usage: python3 face_track.py body.mp4 [out.npy]"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import cv2, numpy as np
from vstudio import face as VF
src = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else 'face_track.npy'
lm = VF.landmarker(1); cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; rows = []; i = 0
while True:
    ok, img = cap.read()
    if not ok: break
    if i % 3 == 0:
        f = VF.main_face(VF.detect(lm, cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))))
        if f is not None:
            p = f['pts'] * 2
            rows.append((i / fps, p[:, 0].mean(), p[:, 1].mean(), np.ptp(p[:, 0]),
                         p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()))
        else: rows.append((i / fps,) + (np.nan,) * 7)
    i += 1
a = np.array(rows); hit = np.isfinite(a[:, 1]).mean() if len(a) else 0
np.save(out, a); print(out, len(rows), f'samples, face found in {hit:.0%}')
