#!/usr/bin/env python3
"""Vertical 口播 compositor: hook montage + body (ffmpeg base), then a per-frame PIL/numpy
overlay pass. Every editing strategy is a switch in the config's STYLE dict, so one video
can be notes-board style, 精剪 style, or any mix.

usage (run from anywhere; it chdirs to the config's folder, which must hold segs.json):
  python3 compose.py work/config.py all          # base + overlays
  python3 compose.py work/config.py base         # only the hook montage + body base.mov
  python3 compose.py work/config.py comp         # only overlays (reuses base.mov)
  python3 compose.py work/config.py preview 3,40,95   # stills at final seconds -> preview.jpg
Template config: $VSTUDIO/workflows/talkinghead/examples/v_config_example.py
Fonts come from vstudio.config.font; brand colours, default speeds and loudness from the persona.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, json, re, subprocess, importlib.util
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 30, 48000
CFG = os.path.abspath(sys.argv[1]); STAGE = sys.argv[2] if len(sys.argv) > 2 else 'all'
os.chdir(os.path.dirname(CFG)); sys.path[:0] = [HERE, os.path.dirname(CFG)]
spec = importlib.util.spec_from_file_location('cfg', CFG); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)

DEFAULT_STYLE = dict(
    zoom=False, emph_zoom=1.32, alt_zoom=1.16,      # per-sentence punch-in rhythm (精剪)
    pops=False, stamps=False, circles=False, cards=False, sfx=False,
    progress='refined',                              # 'refined' | 'classic' | None
    callouts=False, panels=False,                    # notes-board strategies
    hook_badge=False, fx_in_hooks=True,
    sub_size=54, sub_y=1525, sub_stroke=5,
)
ST = {**DEFAULT_STYLE, **getattr(C, 'STYLE', {})}
G = lambda name, default: getattr(C, name, default)
from vstudio.config import font, persona
_PS = persona(); _SPEED = _PS.get('speed') or {}; _BRAND = _PS.get('brand') or {}
LUFS = (_PS.get('audio') or {}).get('loudness_lufs', -14)
SUBS = json.load(open(G('SEGS', 'segs.json')))['subs']
BODY_T = json.load(open(G('SEGS', 'segs.json')))['total']
HOOKS = C.HOOKS; HS = G('HOOK_SPEED', _SPEED.get('hook', 1.3)); BS = G('BODY_SPEED', _SPEED.get('body', 1.1)); XF = G('XF', 0.3)
GRADE = G('GRADE', "hqdn3d=1.2:1.2:3:3,eq=contrast=1.06:brightness=0.015:saturation=1.07:gamma=1.02,colorbalance=rs=-0.02:bs=0.015:rm=-0.01,cas=0.45")

# ---------------- timeline (muted pads so xfades never eat a first/last syllable) ----------------
PADS = [0.0] + [XF * HS] * (len(HOOKS) - 1)
CLIPS = [[(a - (PADS[k] if i == 0 else 0), b) for i, (a, b) in enumerate(clip)] for k, clip in enumerate(HOOKS)]
TAIL = XF * HS
CLIPS[-1][-1] = (CLIPS[-1][-1][0], CLIPS[-1][-1][1] + TAIL)
PRE = XF
hook_d = [sum(b - a for a, b in clip) / HS for clip in CLIPS]
L = [hook_d[0]]
for d in hook_d[1:]: L.append(L[-1] + d - XF)
HOOK_DUR = L[-1]; MAIN0 = HOOK_DUR - XF
TOTAL = MAIN0 + PRE + BODY_T / BS
MAP = []
for k, clip in enumerate(CLIPS):
    t = 0 if k == 0 else L[k - 1] - XF
    for i, (a, b) in enumerate(clip):
        skip = PADS[k] if i == 0 else 0
        MAP.append((t + skip / HS, t + (b - a) / HS, a + skip, HS)); t += (b - a) / HS
MAP.append((MAIN0 + PRE, TOTAL, 0.0, BS))
def b2f(b): return MAIN0 + PRE + b / BS
def f2b(t):
    best = None
    for f0, f1, b0, sp in MAP:
        if f0 <= t < f1: best = b0 + (t - f0) * sp
    return best if best is not None else BODY_T
def sid_at(b):
    for s in SUBS:
        if s['start'] <= b < s['end']: return s['sid']
    return -1

def build_base():
    fc = []; n = 0
    for k, clip in enumerate(CLIPS):
        pv = []; pa = []
        for i, (a, b) in enumerate(clip):
            mute = f",volume=0:enable='lt(t,{PADS[k]:.3f})'" if i == 0 and PADS[k] > 0 else ""
            if k == len(CLIPS) - 1 and i == len(clip) - 1: mute += f",volume=0:enable='gt(t,{b - a - TAIL:.3f})'"
            fc.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[hv{n}];[1:a]atrim={a}:{b},asetpts=PTS-STARTPTS{mute}[ha{n}]")
            pv.append(f"[hv{n}]"); pa.append(f"[ha{n}]"); n += 1
        fc.append("".join(v + a for v, a in zip(pv, pa)) + f"concat=n={len(clip)}:v=1:a=1[hc{k}][hca{k}]")
        fc.append(f"[hc{k}]setpts=PTS/{HS},fps=30[k{k}];[hca{k}]atempo={HS},volume={G('HOOK_VOL_DB', 2)}dB[ka{k}]")
    fc.append(f"[0:v]setpts=PTS/{BS},fps=30,tpad=start_duration={PRE}:start_mode=clone[mv];"
              f"[1:a]atempo={BS},adelay={int(PRE*1000)}|{int(PRE*1000)}[ma]")
    cv, ca = "[k0]", "[ka0]"
    for k in range(1, len(CLIPS)):
        fc.append(f"{cv}[k{k}]xfade=transition=fade:duration={XF}:offset={L[k-1]-XF:.4f}[x{k}];{ca}[ka{k}]acrossfade=d={XF}[xa{k}]")
        cv, ca = f"[x{k}]", f"[xa{k}]"
    fc.append(f"{cv}[mv]xfade=transition=fade:duration={XF}:offset={HOOK_DUR-XF:.4f},{GRADE},format=yuv420p[vout];"
              f"{ca}[ma]acrossfade=d={XF},loudnorm=I={LUFS}:TP=-1.5:LRA=11,aresample=48000[aout]")
    open('base_filter.txt', 'w').write(";\n".join(fc))   # kept on disk for debugging; passed inline (-/filter_complex needs ffmpeg >= 7.1)
    subprocess.run(['ffmpeg', '-v', 'error', '-stats', '-y', '-i', C.BODY, '-i', C.AUDIO, '-filter_complex', open('base_filter.txt').read(),
                    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-crf', '13', '-preset', 'medium', '-c:a', 'pcm_s16le', 'base.mov'], check=True)

# ---------------- text helpers ----------------
_FC = {}
def F(sz, bold=True):
    k = (sz, bold)
    if k not in _FC: _FC[k] = ImageFont.truetype(font('cjk-bold' if bold else 'cjk'), sz)
    return _FC[k]
def _rgb(h, d): h = (h or d).lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
RED = _rgb(_BRAND.get('accent'), 'FF3B5C'); YEL = _rgb(_BRAND.get('highlight'), 'FFD84D'); INK = (34, 34, 40); WHITE = (255, 255, 255, 255)
_KW = [k for k in G('KEYWORDS', []) if k]
KEY = re.compile("(" + "|".join(re.escape(k) for k in sorted(_KW, key=len, reverse=True)) + ")") if _KW else None
_D0 = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
def tl(s, f): return _D0.textlength(s, font=f)
def text_layer(runs, font, stroke=6, pad=16):
    wsum = sum(tl(t, font) for t, _ in runs); asc, desc = font.getmetrics(); h = asc + desc
    im = Image.new('RGBA', (int(wsum) + 2 * pad + 2 * stroke, h + 2 * pad + 2 * stroke), (0, 0, 0, 0))
    sh = Image.new('RGBA', im.size, (0, 0, 0, 0)); ds = ImageDraw.Draw(sh); dr = ImageDraw.Draw(im); x = pad + stroke
    for t, col in runs:
        ds.text((x + 3, pad + stroke + 4), t, font=font, fill=(0, 0, 0, 150), stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        dr.text((x, pad + stroke), t, font=font, fill=col, stroke_width=stroke, stroke_fill=(20, 20, 20, 255)); x += tl(t, font)
    return np.array(Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)), im))
def colorize(s, base=WHITE, hi=YEL + (255,)):
    out = []; i = 0
    if KEY is None: return [(s, base)]
    for m in KEY.finditer(s):
        if m.start() > i: out.append((s[i:m.start()], base))
        out.append((m.group(), hi)); i = m.end()
    if i < len(s): out.append((s[i:], base))
    return out
def vis_len(s): return sum(0.55 if ord(c) < 128 else 1 for c in s)
def split_sub(text):
    out = []
    for part in text.split('|'): out += re.split(r'(?<=[一-鿿]) (?=[一-鿿])', part)
    return [c.strip() for c in out if c.strip()]
def rounded(size, r, fill):
    im = Image.new('RGBA', size, (0, 0, 0, 0)); ImageDraw.Draw(im).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=fill); return im
def shadowed(im, blur=14, off=8, a=90):
    pad = blur * 3; big = Image.new('RGBA', (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('RGBA', im.size, (0, 0, 0, a)); sh.putalpha(im.split()[3].point(lambda v: v * a // 255))
    big.paste(sh, (pad, pad + off), sh); big = big.filter(ImageFilter.GaussianBlur(blur)); big.alpha_composite(im, (pad, pad)); return big, pad

# ---------------- draw helpers ----------------
def blit(fr, a, x, y, alpha=1.0, scale=1.0):
    if alpha <= 0: return
    if scale != 1.0: a = cv2.resize(a, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    h, w = a.shape[:2]; x = int(x); y = int(y)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0: return
    src = a[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32); al = src[..., 3:4] / 255 * alpha
    fr[y0:y1, x0:x1] = fr[y0:y1, x0:x1] * (1 - al) + src[..., :3] * al
def blitc(fr, a, cx, cy, alpha=1.0, scale=1.0):
    h, w = a.shape[:2]; blit(fr, a, cx - w * scale / 2, cy - h * scale / 2, alpha, scale)
def ease_pop(dt, d=0.18, s0=1.5):
    if dt >= d: return 1.0
    u = max(0, dt) / d; return s0 + (1 - s0) * (1 - (1 - u) ** 3)
def fade(b, b0, b1, d=0.25):  # alpha for a body-time window, fades in final-time seconds
    return max(0, min(1, (b - b0) / BS / d, (b1 - b) / BS / d))
def blurbg(fr):
    s = cv2.GaussianBlur(cv2.resize(fr, (54, 96), interpolation=cv2.INTER_AREA), (0, 0), 2)
    return cv2.resize(s, (W, H), interpolation=cv2.INTER_CUBIC) * 0.42

# ---------------- face track (for zoom / circle inset) ----------------
FACE = {}
if os.path.exists(G('FACE', 'face_track.npy')):
    FT = np.load(G('FACE', 'face_track.npy'))
    for s in SUBS:
        m = (FT[:, 0] >= s['start']) & (FT[:, 0] < s['end'])
        FACE[s['sid']] = np.nanmedian(FT[m, 1:], 0) if m.any() else np.nanmedian(FT[:, 1:], 0)
    FACE[-1] = np.nanmedian(FT[:, 1:], 0)
else:
    FACE[-1] = np.array([540.0, 860.0, 480.0])
def face(sid): return FACE.get(sid, FACE[-1])

def zoom(fr, z, sid):
    if z <= 1.001: return fr
    fx, fy, fw = face(sid); w, h = W / z, H / z
    cx = np.clip(fx, w / 2, W - w / 2); cy = np.clip(fy + 0.12 * h, h / 2, H - h / 2)
    M = np.float32([[z, 0, -(cx - w / 2) * z], [0, z, -(cy - h / 2) * z]])
    return cv2.warpAffine(fr, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
_CM = {}
def circle_inset(fr, sid, R=290):
    fx, fy, fw = face(sid); side = int(fw * 1.85)
    x0 = int(np.clip(fx - side / 2, 0, W - side)); y0 = int(np.clip(fy - side / 2 + fw * 0.12, 0, H - side))
    crop = cv2.resize(fr[y0:y0 + side, x0:x0 + side], (2 * R, 2 * R), interpolation=cv2.INTER_AREA)
    if R not in _CM:
        yy, xx = np.mgrid[:2 * R + 20, :2 * R + 20] - (R + 10); d = np.sqrt(xx ** 2 + yy ** 2)
        inner = np.clip(R - d + 0.5, 0, 1); _CM[R] = (inner, np.clip(R + 9 - d + 0.5, 0, 1) - inner)
    tile = np.zeros((2 * R + 20, 2 * R + 20, 3), np.float32); tile[10:10 + 2 * R, 10:10 + 2 * R] = crop
    return tile, _CM[R][0][..., None], _CM[R][1][..., None]
def card(fr, bg, s=0.55, r=36, y0=600):
    w, h = int(W * s), int(H * s); small = cv2.resize(fr, (w, h), interpolation=cv2.INTER_AREA)
    m = np.zeros((h, w), np.uint8); cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)): cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    m = (cv2.GaussianBlur(m, (3, 3), 0) / 255.0)[..., None]; x0 = (W - w) // 2
    sh = np.zeros((H, W), np.float32); sh[y0 + 14:y0 + h + 14, x0:x0 + w] = m[..., 0]
    out = bg * (1 - cv2.GaussianBlur(sh, (0, 0), 18)[..., None] * 0.6)
    out[y0:y0 + h, x0:x0 + w] = out[y0:y0 + h, x0:x0 + w] * (1 - m) + small * m; return out

# ---------------- assets ----------------
SUBIMG = []
for s in SUBS:
    ch = split_sub(s['text']); tot = sum(vis_len(c) for c in ch); a = s['start']
    for c in ch:
        b = a + (s['end'] - s['start']) * vis_len(c) / tot
        SUBIMG.append((a, b, text_layer(colorize(c), F(ST['sub_size']), stroke=ST['sub_stroke'], pad=10))); a = b
HT = G('HOOK_TITLE', [])
HTI = [text_layer([(HT[0], WHITE)], F(76), stroke=7)] if HT else []
if len(HT) > 1: HTI.append(text_layer(colorize(HT[1], WHITE), F(88), stroke=8))
BADGE = None
if ST['hook_badge']:
    BADGE = rounded((250, 64), 32, RED + (255,)); ImageDraw.Draw(BADGE).text((125, 32), G('HOOK_BADGE_TEXT', "精彩预告"), font=F(36), fill='white', anchor='mm'); BADGE = np.array(BADGE)

def stamp_img(text, ang):
    f = F(56); im = Image.new('RGBA', (int(tl(text, f)) + 56, 96), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([3, 3, im.width - 4, im.height - 4], 12, fill=(255, 255, 255, 215), outline=(222, 30, 52, 255), width=7)
    d.text((im.width / 2, im.height / 2), text, font=f, fill=(222, 30, 52, 255), anchor='mm')
    return np.array(im.rotate(ang, expand=True, resample=Image.BICUBIC))
def pop_img(text, col, size):
    c = YEL + (255,) if col == 'Y' else (255, 128, 20, 255)
    return np.array(Image.fromarray(text_layer([(text, c)], F(size), stroke=max(8, size // 14))).rotate(-4, expand=True, resample=Image.BICUBIC))
def token_img(text):
    f = F(56); im = rounded((int(tl(text, f)) + 56, 92), 18, (15, 15, 18, 235)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], 18, outline=YEL + (255,), width=3)
    d.text((im.width / 2, 46), text, font=f, fill=YEL + (255,), anchor='mm'); return np.array(im)
POPI = [(b, pop_img(t, col, sz), x, y, hold) for b, t, col, x, y, sz, hold in G('POPS', [])] if ST['pops'] else []
STI = [(b0, b1, stamp_img(t, ang), x, y) for b0, b1, t, x, y, ang in G('STAMPS', [])] if ST['stamps'] else []
CIRI = [(t0, t1, text_layer([(ti, WHITE)], F(66), stroke=6), [(t, token_img(k)) for t, k in toks], grid)
        for t0, t1, ti, toks, grid in G('CIRCLES', [])] if ST['circles'] else []
CARI = [(t0, t1, text_layer([(ti, YEL + (255,))], F(70), stroke=6), [(t, text_layer(colorize(l), F(50), stroke=5)) for t, l in ls])
        for t0, t1, ti, ls in G('CARDS', [])] if ST['cards'] else []

# callouts (notes style): top-left white bubble with red bar
CALI = []
if ST['callouts']:
    for t, dur, txt in G('CALLOUTS', []):
        f = F(40); im = rounded((int(tl(txt, f)) + 70, 84), 22, (255, 255, 255, 240)); dd = ImageDraw.Draw(im)
        dd.rounded_rectangle([0, 0, 12, 83], 6, fill=RED + (255,)); dd.text((40, 42), txt, font=f, fill=INK, anchor='lm')
        im, pad = shadowed(im); CALI.append((t, t + dur * BS, np.array(im), 60 - pad, 350 - pad))
# 记笔记 panels (notes style): bottom card, red header, yellow tag, bullets revealed as she says them
PANI = []
if ST['panels']:
    for p0, p1, title, bullets in G('PANELS', []):
        n = len(bullets); RW = 940; HH = 96; ROW = 66; ph = HH + 26 + n * ROW + 22; top = ST['sub_y'] - 60 - ph
        bg = rounded((RW, ph), 28, (255, 255, 255, 242)); d = ImageDraw.Draw(bg)
        d.rounded_rectangle([0, 0, RW - 1, HH], 28, fill=RED + (255,)); d.rectangle([0, HH - 30, RW - 1, HH], fill=RED + (255,))
        d.text((40, HH / 2), title, font=F(48), fill='white', anchor='lm')
        tag = rounded((190, 56), 12, YEL + (255,)); ImageDraw.Draw(tag).text((95, 28), G('NOTES_TAG', "记笔记 ↓"), font=F(32), fill=INK, anchor='mm')
        tag = tag.rotate(4, expand=True, resample=Image.BICUBIC); bg.alpha_composite(tag, (RW - tag.width - 24, (HH - tag.height) // 2))
        bgs, pad = shadowed(bg, 18, 10, 110); x = (W - RW) / 2; rows = []
        for i, (rt, txt) in enumerate(bullets):
            row = Image.new('RGBA', (RW - 60, ROW), (0, 0, 0, 0)); dr = ImageDraw.Draw(row)
            dr.ellipse([6, ROW / 2 - 9, 24, ROW / 2 + 9], fill=RED + (255,)); xx = 48
            for t, col in colorize(txt, INK + (255,), (214, 40, 70, 255)):
                dr.text((xx, ROW / 2), t, font=F(44), fill=col, anchor='lm'); xx += dr.textlength(t, font=F(44))
            rows.append((max(rt, p0), np.array(row), x + 30, top + HH + 26 + i * ROW))
        PANI.append((p0, p1, np.array(bgs), x - pad, top - pad, rows))

# ---------------- progress bars ----------------
CH = G('CHAPTERS', [])
PB_X0, PB_X1, PB_Y, PB_H, PB_GAP = 64, 1016, 250, 7, 10
if CH and ST['progress'] == 'refined':
    _tot = sum(b - a for a, b, _ in CH); _avail = PB_X1 - PB_X0 - PB_GAP * (len(CH) - 1); SEGX = []; x = PB_X0
    for a, b_, _ in CH:
        w = _avail * (b_ - a) / _tot; SEGX.append((x, x + w)); x += w + PB_GAP
    GRAD = np.linspace(np.array([255, 70, 110]), np.array([255, 184, 77]), PB_X1 - PB_X0)
    LABELS = []
    for i, (a, b_, lab) in enumerate(CH):
        f1, f2 = F(28), F(30); num = f"{i+1:02d}"; tot = f" / {len(CH):02d}"
        w1, w2, w3 = tl(num, f1), tl(lab, f2), tl(tot, f1)
        im = rounded((int(w1 + w2 + w3 + 62), 50), 25, (10, 10, 14, 120)); d = ImageDraw.Draw(im)
        d.text((20, 25), num, font=f1, fill=(255, 196, 90, 255), anchor='lm'); d.text((20 + w1, 25), tot, font=f1, fill=(255, 255, 255, 120), anchor='lm')
        d.text((20 + w1 + w3 + 16, 25), lab, font=f2, fill=(255, 255, 255, 240), anchor='lm'); LABELS.append(np.array(im))
def progress_refined(fr, b, alpha):
    strip = Image.new('RGBA', (W, 40), (0, 0, 0, 0)); d = ImageDraw.Draw(strip); y0 = 12; cur = 0
    for i, ((a, b_, _), (xa, xb)) in enumerate(zip(CH, SEGX)):
        d.rounded_rectangle([xa - 1, y0 - 1, xb + 1, y0 + PB_H + 2], PB_H // 2 + 1, fill=(0, 0, 0, 70))
        d.rounded_rectangle([xa, y0, xb, y0 + PB_H], PB_H // 2, fill=(255, 255, 255, 110))
        if b >= a:
            p = 1.0 if b >= b_ else (b - a) / (b_ - a); xe = xa + (xb - xa) * p
            if b < b_: cur = i
            if xe - xa > 2:
                wd = int(xe - xa) + 1; arr = np.zeros((PB_H + 1, wd, 4), np.uint8)
                arr[..., :3] = GRAD[int(xa - PB_X0):int(xa - PB_X0) + wd][None]; arr[..., 3] = 255
                m = Image.new('L', (wd, PB_H + 1), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, wd - 1, PB_H], PB_H // 2, fill=255)
                fi = Image.fromarray(arr); fi.putalpha(m); strip.alpha_composite(fi, (int(xa), y0))
    if b >= CH[-1][1]: cur = len(CH) - 1
    glow = np.array(strip.filter(ImageFilter.GaussianBlur(6))).astype(np.float32); glow[..., 3] *= 0.8
    out = Image.alpha_composite(Image.fromarray(glow.astype(np.uint8)), strip)
    a, b_, _ = CH[cur]; xa, xb = SEGX[cur]; xe = xa + (xb - xa) * min(1, max(0, (b - a) / (b_ - a)))
    ImageDraw.Draw(out).ellipse([xe - 8, y0 + PB_H / 2 - 8, xe + 8, y0 + PB_H / 2 + 8], fill=(255, 255, 255, 255))
    blit(fr, np.array(out), 0, PB_Y - y0, alpha)
    ca = min(1, (b - a) / BS / 0.35) if (cur > 0 or b > 0.35) else 1
    blit(fr, LABELS[cur], PB_X0 - 4, PB_Y + 22 + int(8 * (1 - ca)), alpha * ca)
CLS = None
if CH and ST['progress'] == 'classic':
    X0, X1, BY = 70, 1010, 262
    track = Image.new('RGBA', (W, 80), (0, 0, 0, 0)); d = ImageDraw.Draw(track)
    d.rounded_rectangle([X0, 0, X1, 9], 5, fill=(255, 255, 255, 110)); pills = []
    for c0, c1, lab in CH:
        xa = X0 + (X1 - X0) * c0 / BODY_T; xb = X0 + (X1 - X0) * c1 / BODY_T
        if c0 > 0: d.rectangle([xa - 1, -1, xa + 1, 10], fill=(30, 30, 30, 200))
        d.text(((xa + xb) / 2, 38), lab, font=F(30), fill=(255, 255, 255, 235), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0, 160))
        tw = tl(lab, F(30)) + 24; pill = rounded((int(tw), 44), 22, RED + (255,))
        ImageDraw.Draw(pill).text((tw / 2, 22), lab, font=F(30), fill='white', anchor='mm'); pills.append((c0, c1, np.array(pill), (xa + xb) / 2 - tw / 2))
    CLS = (np.array(track), pills, X0, X1, BY)
def progress_classic(fr, b, alpha):
    track, pills, X0, X1, BY = CLS; blit(fr, track, 0, BY, alpha)
    for c0, c1, pill, px in pills:
        if c0 <= b < c1: blit(fr, pill, px, BY + 16, alpha * fade(b, c0, c1, 0.15))
    xe = int(X0 + (X1 - X0) * min(1, b / BODY_T)); fr[BY:BY + 9, X0:xe] = fr[BY:BY + 9, X0:xe] * (1 - alpha) + np.array(RED) * alpha
    yy, xx = np.ogrid[-12:13, -12:13]; m = (xx ** 2 + yy ** 2 <= 144); sub = fr[BY - 8:BY + 17, xe - 12:xe + 13]
    if sub.shape[:2] == m.shape: sub[m] = 255

# ---------------- SFX ----------------
def sfx_bank():
    t = lambda d: np.arange(int(d * SR)) / SR
    tt = t(0.09); pop = np.sin(2 * np.pi * (500 + 2500 * tt) * tt) * np.exp(-tt * 45) * 0.5
    tt = t(0.32); n = np.random.default_rng(1).standard_normal(len(tt))
    whoosh = np.convolve(n, np.ones(18) / 18, 'same') * np.exp(-((tt - 0.16) / 0.07) ** 2) * 0.35
    tt = t(0.22); thud = np.sin(2 * np.pi * 95 * tt) * np.exp(-tt * 22) * 0.8 + np.random.default_rng(2).standard_normal(len(tt)) * np.exp(-tt * 90) * 0.25
    return dict(pop=pop, whoosh=whoosh, thud=thud)
def mix_audio():
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'base.mov', '-vn', '-f', 's16le', '-ac', '2', '-ar', str(SR), '-'], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).reshape(-1, 2).astype(np.float32) / 32768
    if ST['sfx']:
        ev = [(b2f(b), 'pop') for b, *_ in POPI] + [(b2f(b0), 'thud') for b0, *_ in STI]
        for t0, t1, _, toks, _ in CIRI: ev += [(b2f(t0) - 0.12, 'whoosh'), (b2f(t1) - 0.12, 'whoosh')] + [(b2f(t), 'pop') for t, _ in toks]
        for t0, t1, *_ in CARI: ev += [(b2f(t0) - 0.12, 'whoosh'), (b2f(t1) - 0.12, 'whoosh')]
        ev += [(L[k - 1] - XF, 'whoosh') for k in range(1, len(CLIPS))] + [(MAIN0 - 0.1, 'whoosh')]
        S = sfx_bank(); g = dict(pop=0.32, whoosh=0.4, thud=0.45)
        for t, k in ev:
            i = int(t * SR); x = S[k] * g[k]; j = min(len(a), i + len(x))
            if 0 <= i < len(a): a[i:j] += x[:j - i, None]
    import soundfile as sf; sf.write('mix.wav', np.clip(a, -1, 1), SR)

def in_scene(b, scenes):
    for sc in scenes:
        if sc[0] <= b < sc[1]: return sc
    return None

# ---------------- per-frame composite ----------------
def compose(fr, t):
    b = f2b(t); sid = sid_at(b); hook = t < MAIN0 + PRE * 0.5
    cir = None if hook else in_scene(b, CIRI); crd = None if hook else in_scene(b, CARI)
    if cir:
        t0, t1, title, toks, grid = cir; bg = blurbg(fr); tile, inner, ring = circle_inset(fr, sid)
        sc = ease_pop((b - t0) / BS, 0.22, 0.6)
        if sc != 1.0:
            tile = cv2.resize(tile, None, fx=sc, fy=sc); inner = cv2.resize(inner, None, fx=sc, fy=sc)[..., None]; ring = cv2.resize(ring, None, fx=sc, fy=sc)[..., None]
        h = tile.shape[0]; x0, y0 = int(540 - h / 2), int(1100 - h / 2)
        bg[y0:y0 + h, x0:x0 + h] = bg[y0:y0 + h, x0:x0 + h] * (1 - inner - ring) + tile * inner + 255 * ring; fr = bg
        blitc(fr, title, 540, 372, min(1, (b - t0) / BS / 0.2))
        for i, (tt, im) in enumerate(toks):
            if b < tt: continue
            if grid: row, col = divmod(i, 2); x, y = 540 + (-210 if col == 0 else 210), 500 + row * 108
            else: x, y = 540, 500 + i * 108
            blitc(fr, im, x, y, 1, ease_pop((b - tt) / BS, 0.15, 1.4))
    elif crd:
        t0, t1, title, ls = crd; fr = card(fr, blurbg(fr))
        blitc(fr, title, 540, 352, min(1, (b - t0) / BS / 0.2))
        for i, (tt, im) in enumerate(ls):
            if b >= tt: blitc(fr, im, 540, 432 + i * 58, min(1, (b - tt) / BS / 0.2))
    elif ST['zoom']:
        z = ST['emph_zoom'] if sid in G('EMPH', set()) else (1.0 if sid % 2 == 0 else ST['alt_zoom'])
        fr = zoom(fr, z, sid)
    if hook:
        if BADGE is not None: blitc(fr, BADGE, 540, 300, min(1, t / 0.2))
        for i, im in enumerate(HTI):
            st = 0.2 * i; blitc(fr, im, 540, (390 if BADGE is not None else 330) + (HTI[0].shape[0] - 18) * i, min(1, max(0, t - st) / 0.2), ease_pop(max(0, t - st), 0.2, 1.3))
    panel_on = (not hook) and any(p0 <= b < p1 for p0, p1, *_ in PANI)
    if not cir and not crd and not panel_on and (ST['fx_in_hooks'] or not hook):
        for b0, b1, im, x, y in STI:
            if b0 <= b < b1:
                s = ease_pop((b - b0) / BS, 0.12, 1.7); blit(fr, im, x - (s - 1) * im.shape[1] / 2, y - (s - 1) * im.shape[0] / 2, 1, s)
        for b0, im, x, y, hold in POPI:
            if b0 <= b < b0 + hold: blitc(fr, im, x, y, min(1, (b0 + hold - b) / BS / 0.15), ease_pop((b - b0) / BS, 0.2, 1.6))
    if not hook:
        for b0, b1, im, x, y in CALI:
            if b0 <= b < b1: blit(fr, im, x, y + int(24 * (1 - min(1, (b - b0) / BS / 0.25)) ** 2), fade(b, b0, b1))
        if not cir and not crd:
            for p0, p1, bg, x, y, rows in PANI:
                if p0 <= b < p1:
                    a = fade(b, p0, p1, 0.3); blit(fr, bg, x, y + int(40 * (1 - min(1, (b - p0) / BS / 0.3)) ** 2), a)
                    for rt, im, rx, ry in rows:
                        if b >= rt: blit(fr, im, rx, ry + int(18 * (1 - min(1, (b - rt) / BS / 0.25)) ** 2), min(a, fade(b, rt, p1)))
        pa = min(1, (t - MAIN0) / 0.4)
        if CH and ST['progress'] == 'refined': progress_refined(fr, b, pa)
        elif CLS is not None: progress_classic(fr, b, pa)
    for a0, a1, im in SUBIMG:
        if a0 <= b < a1: blitc(fr, im, 540, ST['sub_y']); break
    return fr

def render():
    src = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', 'base.mov', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', '30', '-i', '-',
        '-i', 'mix.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-profile:v', 'high',
        '-pix_fmt', 'yuv420p', '-bsf:v', 'h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1',
        '-af', f'loudnorm=I={LUFS}:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', C.OUT], stdin=subprocess.PIPE)
    fi = 0; N = W * H * 3
    while True:
        buf = src.stdout.read(N)
        if len(buf) < N: break
        fr = compose(np.frombuffer(buf, np.uint8).reshape(H, W, 3).astype(np.float32), fi / FPS)
        enc.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes()); fi += 1
        if fi % 900 == 0: print('frame', fi, f'{fi/FPS:.1f}/{TOTAL:.1f}', flush=True)
    enc.stdin.close(); enc.wait()

def preview(ts):
    outs = []
    for t in ts:
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', 'base.mov', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
        fr = compose(np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.float32), t)
        outs.append(Image.fromarray(np.clip(fr, 0, 255).astype(np.uint8)).resize((360, 640)))
    im = Image.new('RGB', (360 * len(outs), 640))
    for i, o in enumerate(outs): im.paste(o, (360 * i, 0))
    im.save('preview.jpg', quality=85); print('wrote', os.path.abspath('preview.jpg'))

if __name__ == '__main__':
    print(f"HOOK_DUR={HOOK_DUR:.2f} BODY_START={MAIN0 + PRE:.2f} TOTAL={TOTAL:.2f}")
    if STAGE in ('all', 'base'): build_base()
    if STAGE in ('all', 'comp'): mix_audio(); render()
    if STAGE == 'preview': preview([float(x) for x in sys.argv[3].split(',')])
    json.dump(dict(HOOK_DUR=HOOK_DUR, BODY_START=MAIN0 + PRE, BODY_SPEED=BS, TOTAL=TOTAL), open('timeline.json', 'w'))
