#!/usr/bin/env python3
"""Vertical 3:4 cover (1080x1440) from the retouched body, styled like the video (same fonts, grade,
keyword colours). Reads the COVER dict from the compose config:

    COVER = dict(SRC="body3_rt.mp4",            # the FINAL body (frame times are in its timeline)
                 T=12.3,                         # chosen with pick_cover_frame.py
                 OUT="cover.jpg",
                 TITLE=["line 1 white", "line 2 with KEYWORDS in yellow"],
                 STICKY=("记笔记", [("point one", "ink"), ("point two", "red")]),   # or None
                 TAG="short tag")                # rotated pill top-right, or None
usage: python3 cover.py work/config.py      (then always LOOK at the result)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, subprocess
import numpy as np, cv2
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_cfg = sys.argv[1]
sys.argv = ['compose.py', _cfg, 'none']       # reuse compose's helpers without rendering (it chdirs to the config dir)
import compose as K

CV = getattr(K.C, 'COVER', None)
if not CV:
    sys.exit("config has no COVER dict - see this script's docstring")
SRC, T, OUT = CV['SRC'], float(CV['T']), CV.get('OUT', 'cover.jpg')
TITLE = CV.get('TITLE', []); STICKY = CV.get('STICKY'); TAG = CV.get('TAG')
COL = {'ink': K.INK, 'red': (214, 40, 70)}

# exact frame by index: ffmpeg -ss near a cut can land on a different frame
cap = cv2.VideoCapture(SRC); cap.set(cv2.CAP_PROP_POS_FRAMES, round(T * 30)); ok, bgr = cap.read()
if not ok:
    sys.exit(f'cannot read frame at {T}s of {SRC}')
g0 = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-i', '-', '-vf', K.GRADE,
                     '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], input=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes(), capture_output=True).stdout
fr = Image.fromarray(np.frombuffer(g0, np.uint8).reshape(1920, 1080, 3))
cv = fr.crop((0, 200, 1080, 1640)).convert('RGBA')
# bottom gradient for the title
g = Image.new('L', (1, 1440)); g.putdata([int(max(0, (y - 700) / 740) ** 1.4 * 190) for y in range(1440)])
cv.alpha_composite(Image.merge('RGBA', [Image.new('L', (1080, 1440), 0)] * 3 + [g.resize((1080, 1440))]))
if TITLE:
    t1 = K.text_layer([(TITLE[0], K.WHITE)], K.F(80), stroke=7)
    cv.alpha_composite(Image.fromarray(t1), ((1080 - t1.shape[1]) // 2, 1010))
    if len(TITLE) > 1:
        t2 = K.text_layer(K.colorize(TITLE[1], K.WHITE), K.F(86), stroke=8)
        cv.alpha_composite(Image.fromarray(t2), ((1080 - t2.shape[1]) // 2, 1010 + t1.shape[0] - 24))
if STICKY:   # small 记笔记 sticky top-left
    head, lines = STICKY
    st = K.rounded((380, 112 + 52 * len(lines)), 18, K.YEL + (255,)); d = ImageDraw.Draw(st); d.text((26, 22), head, font=K.F(34), fill=K.INK)
    for i, (line, col) in enumerate(lines): d.text((26, 78 + 52 * i), line, font=K.F(38), fill=COL.get(col, col))
    st, p = K.shadowed(st.rotate(-4, expand=True, resample=Image.BICUBIC), 14, 8, 100); cv.alpha_composite(st, (30 - p, 40 - p))
if TAG:      # rotated red tag top-right
    tw = int(K.tl(TAG, K.F(36))) + 60
    bd = K.rounded((tw, 70), 35, K.RED + (255,)); ImageDraw.Draw(bd).text((tw / 2, 35), TAG, font=K.F(36), fill='white', anchor='mm')
    bd = bd.rotate(5, expand=True, resample=Image.BICUBIC); cv.alpha_composite(bd, (1040 - bd.width, 60))
cv.convert('RGB').save(OUT, quality=93); print(os.path.abspath(OUT))
