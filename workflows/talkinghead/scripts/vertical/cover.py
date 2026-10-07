#!/usr/bin/env python3
"""Cover from the retouched body, styled like the video (same fonts, grade, keyword colours).
Size per platform (vstudio.platform.cover_size): 小红书 3:4 1080x1440 (default), 抖音 / TikTok / Shorts 9:16
1080x1920 (title kept inside the centre 3:4 the profile grid shows), YouTube 1280x720, B站 1146x717.
Reads the COVER dict from the compose config:

    COVER = dict(SRC="body3_rt.mp4",            # the FINAL body (frame times are in its timeline)
                 T=12.3,                         # chosen with pick_cover_frame.py
                 OUT="cover.jpg",
                 TITLE=["line 1 white", "line 2 with KEYWORDS in yellow"],
                 STICKY=("记笔记", [("point one", "ink"), ("point two", "accent")]),   # or None
                 TAG="short tag")                # rotated pill top-right, or None
usage: python3 cover.py work/config.py [--platform douyin --platform youtube]   (then always LOOK at the result)
OUT belongs to the config's own platform (COVER PLATFORM, else config PLATFORM, else persona platforms.default);
every other platform writes <OUT stem>.<platform>-<orientation>.jpg (+ .feed.jpg where the feed shows a centre
crop), so `cover.py config.py --platform douyin` never overwrites the 小红书 cover.
A 9:16 body on the 3:4 小红书 cover keeps the measured layout (band y 200..1640, title at y 1010).
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parent)]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, importlib.util
import numpy as np, cv2
from PIL import Image, ImageDraw
from vstudio import media
from vstudio import draw as D, overlays as O
from vstudio import platform as P
from layout import resolve_profile

plats = []
while "--platform" in sys.argv:
    i = sys.argv.index("--platform"); plats.append(sys.argv[i + 1]); del sys.argv[i:i + 2]
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
COL = {'ink': INK, 'red': B['accent'], 'accent': B['accent']}   # 'red' = the theme accent (no hard-coded red)
F = lambda sz: D.load_font('cjk-bold', int(sz))
def colorize(s): return [(t, B['highlight'] + (255,) if h else WHITE) for t, h in D.runs(s, KW)]

# exact frame by index: ffmpeg -ss near a cut can land on a different frame
cap = cv2.VideoCapture(SRC); cap.set(cv2.CAP_PROP_POS_FRAMES, round(T * 30)); ok, bgr = cap.read()
if not ok:
    sys.exit(f'cannot read frame at {T}s of {SRC}')
FH, FW = bgr.shape[:2]
g0 = media.run(['ffmpeg', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{FW}x{FH}', '-i', '-', '-vf', GRADE,
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], input=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes(), capture=True).stdout
fr = Image.fromarray(np.frombuffer(g0, np.uint8).reshape(FH, FW, 3))


def face_center(im):
    try:
        from vstudio import face as VF
        lm = VF.landmarker(1)
        f = VF.main_face(VF.detect(lm, cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR))); lm.close()
        if f is not None:
            p = f['pts']; return float(p[:, 0].mean()), float(p[:, 1].mean())
    except Exception:
        pass
    return None
FC = None


def base_image(CW, CH):
    """Frame cropped to the cover aspect: face centre at ~42 % of the height (the measured 3:4 band does that)."""
    global FC
    if (FW, FH, CW, CH) == (1080, 1920, 1080, 1440):
        return fr.crop((0, 200, 1080, 1640))
    if FC is None:
        FC = face_center(fr) or (FW / 2, FH * 0.42)
    s = max(CW / FW, CH / FH); cw, ch = CW / s, CH / s
    x0 = min(max(FC[0] - cw / 2, 0), FW - cw); y0 = min(max(FC[1] - 0.42 * ch, 0), FH - ch)
    return fr.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((CW, CH), Image.LANCZOS)


def render(prof):
    CW, CH = P.cover_size(prof)
    legacy = (CW, CH) == (1080, 1440)
    tx0, ty0, tx1, ty1 = P.cover_title_safe(prof)
    k = CW / 1080 if CH >= CW else CH / 900            # landscape thumbnails: big text
    cv = base_image(CW, CH).convert('RGBA')
    t1 = D.text_layer([(TITLE[0], WHITE)], F(80 * k), stroke=max(3, int(7 * k))) if TITLE else None
    t2 = D.text_layer(colorize(TITLE[1]), F(86 * k), stroke=max(3, int(8 * k))) if len(TITLE) > 1 else None
    for _ in range(0 if legacy else 12):                 # shrink until both lines fit the title-safe width
        if max([t.width for t in (t1, t2) if t is not None] or [0]) <= (tx1 - tx0) + 20 * k: break
        k *= 0.94
        t1 = D.text_layer([(TITLE[0], WHITE)], F(80 * k), stroke=max(3, int(7 * k))) if TITLE else None
        t2 = D.text_layer(colorize(TITLE[1]), F(86 * k), stroke=max(3, int(8 * k))) if len(TITLE) > 1 else None
    th = (t1.height if t1 else 0) + (t2.height - int(24 * k) if t2 else 0)
    ty = 1010 if legacy else int(ty1 - th)
    g0_, g1_ = (700, 1440) if legacy else (max(0, ty - 310 * k), CH)
    g = Image.new('L', (1, CH)); g.putdata([int(max(0, (y - g0_) / max(1, g1_ - g0_)) ** 1.4 * 190) for y in range(CH)])
    cv.alpha_composite(Image.merge('RGBA', [Image.new('L', (CW, CH), 0)] * 3 + [g.resize((CW, CH))]))
    xc = (tx0 + tx1) / 2 if not legacy else CW / 2
    if t1 is not None:
        cv.alpha_composite(t1, (int(xc - t1.width / 2), ty))
        if t2 is not None:
            cv.alpha_composite(t2, (int(xc - t2.width / 2), ty + t1.height - int(24 * k)))
    if STICKY:   # small 记笔记 sticky top-left
        head, lines = STICKY; ks = k if not legacy else 1
        st = D.rounded_rect((int(380 * ks), int((112 + 52 * len(lines)) * ks)), int(18 * ks), B['highlight']); d = ImageDraw.Draw(st)
        d.text((26 * ks, 22 * ks), head, font=F(34 * ks), fill=INK)
        for i, (line, col) in enumerate(lines): d.text((26 * ks, (78 + 52 * i) * ks), line, font=F(38 * ks), fill=COL.get(col, col))
        st, p = D.shadow(st.rotate(-4, expand=True, resample=Image.BICUBIC), 14, 8, 100)
        sx, sy = (30, 40) if legacy else (tx0 - 10, ty0 + 10)
        cv.alpha_composite(st, (int(sx - p), int(sy - p)))
    if TAG:      # rotated accent tag top-right
        bd = O.tag(TAG, angle=5, size=int(36 * (k if not legacy else 1)))
        cv.alpha_composite(bd, ((1040 - bd.width, 60) if legacy else (int(tx1 + 20 * k - bd.width), int(ty0 + 20))))
    return cv.convert('RGB')


HOME = resolve_profile(CV.get('PLATFORM') or getattr(C, 'PLATFORM', None))
def out_name(prof):
    """OUT for the config's own platform; <stem>.<platform>-<orientation>.jpg for every other one."""
    same = prof.key == HOME.key or (prof.name == HOME.name and P.cover_size(prof) == P.cover_size(HOME))
    return OUT if same else f"{os.path.splitext(OUT)[0]}.{prof.name}-{prof.orientation}.jpg"


specs = plats or [None]
for sp in specs:
    prof = resolve_profile(sp) if sp else HOME
    img = render(prof)
    out = out_name(prof)
    q = 93; img.save(out, quality=q)
    while prof.cover.get('max_bytes') and os.path.getsize(out) > prof.cover['max_bytes'] and q > 60:
        q -= 8; img.save(out, quality=q)
    fc = prof.cover.get('feed_crop'); extra = ''
    if fc:
        aw, ah = (float(v) for v in fc.split(':')); W_, H_ = img.size
        cw, ch = (H_ * aw / ah, H_) if W_ / H_ > aw / ah else (W_, W_ * ah / aw)
        x0, y0 = (W_ - cw) / 2, (H_ - ch) / 2
        img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).save(out[:-4] + '.feed.jpg', quality=90); extra = f' + {fc} feed preview'
    print(f"{prof.key}: {img.width}x{img.height} -> {os.path.abspath(out)}{extra}")
