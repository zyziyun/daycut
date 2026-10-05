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
import os, importlib.util
import numpy as np, cv2
from PIL import Image, ImageDraw
from vstudio import media
from vstudio import draw as D, overlays as O

CFG = os.path.abspath(sys.argv[1]); os.chdir(os.path.dirname(CFG))
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.dirname(CFG)]   # anchors.py reads ./segs.json
spec = importlib.util.spec_from_file_location('cfg', CFG); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
CV = getattr(C, 'COVER', None)
if not CV:
    sys.exit("config has no COVER dict - see this script's docstring")
SRC, T, OUT = CV['SRC'], float(CV['T']), CV.get('OUT', 'cover.jpg')
TITLE = CV.get('TITLE', []); STICKY = CV.get('STICKY'); TAG = CV.get('TAG')
GRADE = getattr(C, 'GRADE', "hqdn3d=1.2:1.2:3:3,eq=contrast=1.06:brightness=0.015:saturation=1.07:gamma=1.02,colorbalance=rs=-0.02:bs=0.015:rm=-0.01,cas=0.45")
KW = [k for k in getattr(C, 'KEYWORDS', []) if k]
B = D.brand(); INK = (34, 34, 40); WHITE = (255, 255, 255, 255)
COL = {'ink': INK, 'red': (214, 40, 70)}
F = lambda sz: D.load_font('cjk-bold', sz)
def colorize(s): return [(t, B['highlight'] + (255,) if h else WHITE) for t, h in D.runs(s, KW)]

# exact frame by index: ffmpeg -ss near a cut can land on a different frame
cap = cv2.VideoCapture(SRC); cap.set(cv2.CAP_PROP_POS_FRAMES, round(T * 30)); ok, bgr = cap.read()
if not ok:
    sys.exit(f'cannot read frame at {T}s of {SRC}')
g0 = media.run(['ffmpeg', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-i', '-', '-vf', GRADE,
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], input=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes(), capture=True).stdout
fr = Image.fromarray(np.frombuffer(g0, np.uint8).reshape(1920, 1080, 3))
cv = fr.crop((0, 200, 1080, 1640)).convert('RGBA')
# bottom gradient for the title
g = Image.new('L', (1, 1440)); g.putdata([int(max(0, (y - 700) / 740) ** 1.4 * 190) for y in range(1440)])
cv.alpha_composite(Image.merge('RGBA', [Image.new('L', (1080, 1440), 0)] * 3 + [g.resize((1080, 1440))]))
if TITLE:
    t1 = D.text_layer([(TITLE[0], WHITE)], F(80), stroke=7)
    cv.alpha_composite(t1, ((1080 - t1.width) // 2, 1010))
    if len(TITLE) > 1:
        t2 = D.text_layer(colorize(TITLE[1]), F(86), stroke=8)
        cv.alpha_composite(t2, ((1080 - t2.width) // 2, 1010 + t1.height - 24))
if STICKY:   # small 记笔记 sticky top-left
    head, lines = STICKY
    st = D.rounded_rect((380, 112 + 52 * len(lines)), 18, B['highlight']); d = ImageDraw.Draw(st); d.text((26, 22), head, font=F(34), fill=INK)
    for i, (line, col) in enumerate(lines): d.text((26, 78 + 52 * i), line, font=F(38), fill=COL.get(col, col))
    st, p = D.shadow(st.rotate(-4, expand=True, resample=Image.BICUBIC), 14, 8, 100); cv.alpha_composite(st, (30 - p, 40 - p))
if TAG:      # rotated accent tag top-right
    bd = O.tag(TAG, angle=5, size=36)
    cv.alpha_composite(bd, (1040 - bd.width, 60))
cv.convert('RGB').save(OUT, quality=93); print(os.path.abspath(OUT))
