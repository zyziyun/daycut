#!/usr/bin/env python3
"""Print the head x-range in a frame so cover cards avoid the face (-> COVER_HEAD_X in the H config).
Uses the vstudio face landmarker (face width x1.3 for hair) when available, else a dark-hair scan.
Usage: python3 detect_head.py frame.jpg"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
from PIL import Image

path = sys.argv[1]
try:
    import cv2
    from vstudio import face as VF
    f = VF.main_face(VF.detect(VF.landmarker(1), cv2.imread(path)))
    if f is not None:
        x0, x1 = float(f["pts"][:, 0].min()), float(f["pts"][:, 0].max()); pad = (x1 - x0) * 0.15
        print("head x-range (landmarks):", (int(x0 - pad), int(x1 + pad))); sys.exit(0)
except Exception as e:  # model not installed, mediapipe missing, ...
    print("landmarker unavailable, falling back to dark-hair scan:", e)

im = Image.open(path).convert("RGB"); W, H = im.size; px = im.load()
xs = []
for x in range(0, W, 4):
    for y in range(int(H*0.13), int(H*0.5), 4):
        r, g, b = px[x, y]
        if r < 95 and g < 95 and b < 95:  # dark hair
            xs.append(x); break
print(f"frame {W}x{H}  head/hair x-range:", (min(xs), max(xs)) if xs else "not found")
