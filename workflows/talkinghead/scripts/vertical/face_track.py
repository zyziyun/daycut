#!/usr/bin/env python3
"""Track the main face on the CURRENT body video (every 3rd frame) -> face_track.npy
rows = (body_time, cx, cy, face_width). compose.py uses it to center zooms and circle insets.
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
        if f is not None: p = f['pts'] * 2; rows.append((i / fps, p[:, 0].mean(), p[:, 1].mean(), np.ptp(p[:, 0])))
        else: rows.append((i / fps, np.nan, np.nan, np.nan))
    i += 1
np.save(out, np.array(rows)); print(out, len(rows), 'samples')
