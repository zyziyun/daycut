#!/usr/bin/env python3
"""口播 compositor (V track): hook montage + body (ffmpeg base), then a per-frame PIL/numpy overlay pass.
Every editing strategy is a switch in the config's STYLE dict, so one video can be notes-board style,
精剪 style, or any mix. Vertical (9:16, 3:4) and horizontal (16:9) canvases come from platform profiles.

usage (run from anywhere; it chdirs to the config's folder, which must hold segs.json):
  python3 compose.py work/config.py all          # base + overlays
  python3 compose.py work/config.py base         # only the hook montage + body base.mov
  python3 compose.py work/config.py comp         # only overlays (reuses base.mov)
  python3 compose.py work/config.py preview 3,40,95   # stills at final seconds -> preview.jpg
options (anywhere after the config):
  --platform xiaohongshu:vertical   canvas / safe zones / caption band / loudness from vstudio.platform
                                    (default: config PLATFORM, else persona platforms.default in 9:16;
                                    e.g. xiaohongshu:vertical = 3:4 1080x1440, douyin = 9:16, youtube = 16:9)
  --clean-master                    comp/all: also write <OUT stem>.clean.mp4 without burned captions
                                    + <OUT stem>.cues.json, for `python -m vstudio.export`
A body whose aspect differs from the canvas (9:16 body -> 3:4 or 16:9 canvas) is reframed once with
vstudio.reframe (face mode, pad-blur fallback) into body_<W>x<H>.mp4; the face track follows it.
Template config: $VSTUDIO/workflows/talkinghead/examples/v_config_example.py
Built on vstudio: hook/body dissolves = cut.xfade_assemble (muted pads both sides, see ../montage.py),
loudness = audio.loudnorm_2pass, SFX = audio.place_sfx, text/badges/stamps/progress bars = draw/overlays,
subtitle chunk timing = asr.align_script on the strict_pass words. The per-frame animation engine and the
layout (layout.py) and B-roll (broll.py) are local.
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1]),
                                     str(pathlib.Path(__file__).resolve().parent)]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, json, re, subprocess, importlib.util
import numpy as np, cv2
from PIL import Image, ImageDraw
from vstudio import asr, audio, media, subs as vsubs
from vstudio import draw as D, overlays as O
from montage import Montage
from bodycut import mux
from layout import Layout, resolve_profile, pop_platform_arg, pick, face_core, overlap
import broll as BR

HERE = os.path.dirname(os.path.abspath(__file__))
_PLAT_ARG, CLEAN = pop_platform_arg(sys.argv)
FPS = 30
CFG = os.path.abspath(sys.argv[1]); STAGE = sys.argv[2] if len(sys.argv) > 2 else 'all'
os.chdir(os.path.dirname(CFG)); sys.path[:0] = [HERE, os.path.dirname(CFG)]
spec = importlib.util.spec_from_file_location('cfg', CFG); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
G = lambda name, default: getattr(C, name, default)

PROF = resolve_profile(_PLAT_ARG or G('PLATFORM', None))
L = Layout(PROF); W, H = L.W, L.H; CXM = W / 2

DEFAULT_STYLE = dict(
    zoom=False, emph_zoom=1.32, alt_zoom=1.16,      # per-sentence punch-in rhythm (精剪)
    max_upscale=2.0,                                 # cap: source upscale (prep.json / SRC_UPSCALE) x punch-in
    max_face_frac=0.62,                              # cap: zoomed face width / canvas width
    pops=False, stamps=False, circles=False, cards=False, sfx=False,
    progress='refined',                              # 'refined' | 'classic' | None
    callouts=False, panels=False,                    # notes-board strategies
    callout_theme='notes-yellow',                    # overlays theme of the callout bubble (white bubble, accent rail)
    hook_badge=False, fx_in_hooks=True,
    sub_size=54, sub_y=None, sub_stroke=5,           # sub_y None -> centre of the platform caption band
)
ST = {**DEFAULT_STYLE, **G('STYLE', {})}
if ST['sub_y'] is None or not (L.cap[1] - 40 <= ST['sub_y'] <= L.cap[3] + 40):
    if ST['sub_y'] is not None:
        print(f"STYLE sub_y={ST['sub_y']} is outside the {PROF.key} caption band {L.cap[1]}..{L.cap[3]}; using {L.sub_y}")
    ST['sub_y'] = L.sub_y
from vstudio.config import persona
_PS = persona(); _SPEED = _PS.get('speed') or {}
LUFS, TP = PROF.loudness.get('lufs', (_PS.get('audio') or {}).get('loudness_lufs', -14)), PROF.loudness.get('tp', -1.5)
SEGJ = json.load(open(G('SEGS', 'segs.json')))
SUBS = SEGJ['subs']; BODY_T = SEGJ['total']
HOOKS = C.HOOKS; HS = G('HOOK_SPEED', _SPEED.get('hook', 1.3)); BS = G('BODY_SPEED', _SPEED.get('body', 1.1)); XF = G('XF', 0.3)
GRADE = G('GRADE', "hqdn3d=1.2:1.2:3:3,eq=contrast=1.06:brightness=0.015:saturation=1.07:gamma=1.02,colorbalance=rs=-0.02:bs=0.015:rm=-0.01,cas=0.45")

# ---------------- source upscale (prep_sources.sh writes prep.json: how much the picture was enlarged) ----------------
def _src_upscale():
    if G('SRC_UPSCALE', None):
        return float(C.SRC_UPSCALE)
    try:
        return max(float(v.get('upscale', 1.0)) for v in json.load(open('prep.json')).values()) or 1.0
    except Exception:
        return 1.0
UPSCALE = _src_upscale()

# ---------------- canvas: reframe the body when its aspect differs (vstudio.reframe, face mode) ----------------
_bi = media.probe(C.BODY)
BW, BH = _bi['w'], _bi['h']
CANVAS_PLAN = None
BODY_SRC = C.BODY
if (BW, BH) != (W, H):
    from vstudio import reframe as R
    from vstudio import platform as P
    BODY_SRC = f"body_{W}x{H}.mp4"; pj = f"body_{W}x{H}.crop.json"
    fresh = os.path.exists(BODY_SRC) and os.path.exists(pj) and os.path.getmtime(BODY_SRC) >= os.path.getmtime(C.BODY)
    if fresh:
        CANVAS_PLAN = json.load(open(pj))
    else:
        same = abs(np.log((BW / BH) / (W / H))) < 0.01
        # 9:16 body -> 16:9 canvas: a face crop would be a 1.8x-upscaled strip, so the speaker goes on a blurred fill
        mode = 'center' if same else ('pad-blur' if BH > BW and W > H else G('REFRAME_MODE', 'face'))
        CANVAS_PLAN = R.plan(C.BODY, W, H, mode=mode, safe=P.safe_box(PROF),
                             fallback='center' if (BH > BW) == (H > W) else 'pad-blur')   # no face: 9:16 -> 3:4 centre crop
        print(f"reframe body {BW}x{BH} -> {W}x{H}: {CANVAS_PLAN['mode_used']} (hit rate {CANVAS_PLAN.get('hit_rate')})")
        R.render(C.BODY, BODY_SRC, CANVAS_PLAN, audio=False,
                 encode_args=['-c:v', 'libx264', '-crf', '13', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-an'])
        json.dump(CANVAS_PLAN, open(pj, 'w'))
    if CANVAS_PLAN.get('rects') or CANVAS_PLAN.get('fixed'):
        UPSCALE *= W / (CANVAS_PLAN['rects'][0][2] if CANVAS_PLAN.get('rects') else CANVAS_PLAN['fixed'][2])

def canvas_xy(t, x, y, w=None):
    """Body-pixel point (and width) at body time t -> canvas pixels (follows the reframe plan)."""
    if CANVAS_PLAN is None:
        return x, y, w
    p = CANVAS_PLAN
    if p.get('rects') or p.get('fixed'):
        r = p['fixed'] if not p.get('rects') else p['rects'][min(len(p['rects']) - 1, max(0, int(round(t * p['fps']))))]
        s = W / r[2]; return (x - r[0]) * s, (y - r[1]) * s, (None if w is None else w * s)
    s = min(W / p['src_w'], H / p['src_h']); ox, oy = (W - p['src_w'] * s) / 2, (H - p['src_h'] * s) / 2
    return x * s + ox, y * s + oy, (None if w is None else w * s)

# ---------------- timeline: hooks + body on one muted-pad dissolve chain (../montage.py) ----------------
BASE_SRC = 'base_src.mov' if BODY_SRC == C.BODY else f'base_src_{W}x{H}.mov'
def _mux():
    if not (os.path.exists(BASE_SRC) and all(os.path.getmtime(BASE_SRC) >= os.path.getmtime(p) for p in (BODY_SRC, C.AUDIO))):
        mux(BODY_SRC, C.AUDIO, BASE_SRC)
    return BASE_SRC
_mux()
BASE = 'base.mov' if BODY_SRC == C.BODY else f'base_{W}x{H}.mov'
M = Montage(BASE_SRC, HOOKS, (0.0, BODY_T), HS, BS, XF, hook_gain_db=G('HOOK_VOL_DB', 2), fps=FPS)
TOTAL = M.total; MAIN0 = M.body_dst0
b2f = M.b2f
def f2b(t): return M.f2b(t, BODY_T)
def sid_at(b):
    for s in SUBS:
        if s['start'] <= b < s['end']: return s['sid']
    return -1

def build_base():
    graph = M.graph + f";{M.vout}{GRADE},format=yuv420p[vg]"
    open('base_filter.txt', 'w').write(graph.replace(';', ';\n'))   # kept on disk for debugging
    media.run(['ffmpeg', '-y', *M.input_args, *media.filter_complex_args(graph), '-map', '[vg]', '-map', M.aout,
               '-c:v', 'libx264', '-crf', '13', '-preset', 'medium', '-c:a', 'pcm_s16le', BASE])

# ---------------- text helpers (vstudio.draw) ----------------
def F(sz, bold=True): return D.load_font('cjk-bold' if bold else 'cjk', sz)
_B = D.brand(); RED = _B['accent']; YEL = _B['highlight']; INK = (34, 34, 40); WHITE = (255, 255, 255, 255)
_KW = [k for k in G('KEYWORDS', []) if k]
def tl(s, f): return D.text_width(s, f)
def text_layer(runs, font, stroke=6, pad=16):
    return np.asarray(D.text_layer(runs, font, stroke=stroke, pad=pad))
def colorize(s, base=WHITE, hi=YEL + (255,)):
    """KEYWORDS (and 【】 markup) in `hi`, the rest in `base` -> [(text, colour)] runs."""
    return [(t, hi if h else base) for t, h in D.runs(s, _KW)] or [(s, base)]
def split_sub(text):
    out = []
    for part in text.split('|'): out += re.split(r'(?<=[一-鿿]) (?=[一-鿿])', part)
    return [c.strip() for c in out if c.strip()]
def fit_layer(make, size, max_w, floor=0.6):
    """Render with make(size); shrink the font until the layer fits max_w (captions on narrow boxes)."""
    im = make(size); s = size
    while im.shape[1] > max_w and s > size * floor:
        s -= 2; im = make(s)
    return im

# ---------------- draw helpers ----------------
def blit(fr, a, x, y, alpha=1.0, scale=1.0): D.alpha_paste(fr, a, (x, y), alpha, scale=scale)
def blitc(fr, a, cx, cy, alpha=1.0, scale=1.0): D.alpha_paste(fr, a, (cx, cy), alpha, center=True, scale=scale)
def ease_pop(dt, d=0.18, s0=1.5):
    if dt >= d: return 1.0
    u = max(0, dt) / d; return s0 + (1 - s0) * (1 - (1 - u) ** 3)
def fade(b, b0, b1, d=0.25):  # alpha for a body-time window, fades in final-time seconds
    return max(0, min(1, (b - b0) / BS / d, (b1 - b) / BS / d))
def blurbg(fr):
    s = cv2.GaussianBlur(cv2.resize(fr, (max(8, W // 20), max(8, H // 20)), interpolation=cv2.INTER_AREA), (0, 0), 2)
    return cv2.resize(s, (W, H), interpolation=cv2.INTER_CUBIC) * 0.42

# ---------------- face track (for zoom / circle inset / keeping text off the face) ----------------
# face_track.npy rows: (t, cx, cy, w[, x0, y0, x1, y1]) in BODY pixels; old 4-column files get a box estimate.
FACE, FBOX = {}, {}
def _box_est(cx, cy, w): return np.array([cx - w / 2, cy - 0.55 * w, cx + w / 2, cy + 0.68 * w])
if os.path.exists(G('FACE', 'face_track.npy')):
    FT = np.load(G('FACE', 'face_track.npy'))
    if FT.shape[1] < 8:
        FT = np.hstack([FT[:, :4], np.array([_box_est(*r[1:4]) for r in FT])])
    if CANVAS_PLAN is not None:
        FT = FT.copy()
        for r in FT:
            if np.isnan(r[1]): continue
            r[1], r[2], r[3] = canvas_xy(r[0], r[1], r[2], r[3])
            r[4], r[5], _ = canvas_xy(r[0], r[4], r[5]); r[6], r[7], _ = canvas_xy(r[0], r[6], r[7])
    for s in SUBS:
        m = (FT[:, 0] >= s['start']) & (FT[:, 0] < s['end'])
        v = np.nanmedian(FT[m, 1:], 0) if m.any() else np.nanmedian(FT[:, 1:], 0)
        if np.isnan(v).any(): v = np.nanmedian(FT[:, 1:], 0)
        FACE[s['sid']] = v[:3]; FBOX[s['sid']] = v[3:7]
    FACE[-1] = np.nanmedian(FT[:, 1:4], 0); FBOX[-1] = np.nanmedian(FT[:, 4:8], 0)
    HAVE_FACE = True
else:
    FACE[-1] = np.array([540.0, 860.0, 480.0]) if L.legacy else np.array([W / 2, H * (0.42 if L.portrait else 0.45), min(W, H) * 0.32])
    FBOX[-1] = _box_est(*FACE[-1])
    HAVE_FACE = False
def face(sid): return FACE.get(sid, FACE[-1])
def fbox(sid): return FBOX.get(sid, FBOX[-1])

def zoom_affine(z, sid):
    fx, fy, fw = face(sid); w, h = W / z, H / z
    cx = np.clip(fx, w / 2, W - w / 2); cy = np.clip(fy + 0.12 * h, h / 2, H - h / 2)
    return np.float32([[z, 0, -(cx - w / 2) * z], [0, z, -(cy - h / 2) * z]])
def zoom_level(z, sid):
    """Punch-in capped by source resolution (an upscaled webcam crop goes soft), by face size (a big face
    must not fill the frame), and so the zoomed face stays below the progress bar / inside the canvas."""
    if z <= 1.001: return 1.0
    fw = face(sid)[2]
    z = min(z, ST['max_upscale'] / max(UPSCALE, 1e-6), ST['max_face_frac'] * W / max(fw, 1))
    while z > 1.001:
        x0, y0, x1, y1 = _xf_box(fbox(sid), zoom_affine(z, sid))
        if y0 >= L.safe[1] + 40 and x0 >= 0 and x1 <= W: break
        z -= 0.02
    return max(1.0, z)
def _xf_box(b, A):
    return (b[0] * A[0, 0] + A[0, 2], b[1] * A[1, 1] + A[1, 2], b[2] * A[0, 0] + A[0, 2], b[3] * A[1, 1] + A[1, 2])
ZCACHE = {}
def sid_zoom(sid):
    if sid not in ZCACHE:
        z0 = ST['emph_zoom'] if sid in G('EMPH', set()) else (1.0 if sid % 2 == 0 else ST['alt_zoom'])
        ZCACHE[sid] = zoom_level(z0, sid)
    return ZCACHE[sid]
def face_on_canvas(sid):
    """Face box as shown (after the punch-in of that sentence, if zoom is on)."""
    if ST['zoom'] and sid_zoom(sid) > 1.001: return _xf_box(fbox(sid), zoom_affine(sid_zoom(sid), sid))
    return tuple(fbox(sid))
def zoom(fr, z, sid):
    if z <= 1.001: return fr
    return cv2.warpAffine(fr, zoom_affine(z, sid), (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
_CM = {}
def circle_inset(fr, sid, R=290):
    fx, fy, fw = face(sid); side = int(min(fw * 1.85, W, H))
    x0 = int(np.clip(fx - side / 2, 0, W - side)); y0 = int(np.clip(fy - side / 2 + fw * 0.12, 0, H - side))
    crop = cv2.resize(fr[y0:y0 + side, x0:x0 + side], (2 * R, 2 * R), interpolation=cv2.INTER_AREA)
    if R not in _CM:
        yy, xx = np.mgrid[:2 * R + 20, :2 * R + 20] - (R + 10); d = np.sqrt(xx ** 2 + yy ** 2)
        inner = np.clip(R - d + 0.5, 0, 1); _CM[R] = (inner, np.clip(R + 9 - d + 0.5, 0, 1) - inner)
    tile = np.zeros((2 * R + 20, 2 * R + 20, 3), np.float32); tile[10:10 + 2 * R, 10:10 + 2 * R] = crop
    return tile, _CM[R][0][..., None], _CM[R][1][..., None]
def card(fr, bg, s=0.55, r=36, xy=None):
    w, h = int(W * s), int(H * s); small = cv2.resize(fr, (w, h), interpolation=cv2.INTER_AREA)
    m = np.zeros((h, w), np.uint8); cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)): cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    m = (cv2.GaussianBlur(m, (3, 3), 0) / 255.0)[..., None]; x0, y0 = xy
    sh = np.zeros((H, W), np.float32); sh[y0 + 14:y0 + h + 14, x0:x0 + w] = m[..., 0][:max(0, min(h, H - y0 - 14))]
    out = bg * (1 - cv2.GaussianBlur(sh, (0, 0), 18)[..., None] * 0.6)
    out[y0:y0 + h, x0:x0 + w] = out[y0:y0 + h, x0:x0 + w] * (1 - m) + small * m; return out

# ---------------- assets ----------------
WORDS = SEGJ.get('words', [])
def chunk_times(s, ch):
    """Display windows for the chunks of one sentence: each chunk ends where its last word ends
    (asr.align_script on the strict_pass words, whose END times are the reliable ones); without words,
    proportional to subtitle width."""
    ws = [(w['w'], w['b0'], w['b1']) for w in WORDS if w.get('sid') == s['sid']]
    if ws and len(ch) > 1:
        al = asr.align_script(ch, ws, s['end'])
        cuts = [min(max(x['end'], s['start']), s['end']) for x in al[:-1]]
        for i in range(1, len(cuts)): cuts[i] = max(cuts[i], cuts[i - 1])
    else:
        tot = sum(vsubs.text_width(c) for c in ch) or 1; cuts = []; a = s['start']
        for c in ch[:-1]: a += (s['end'] - s['start']) * vsubs.text_width(c) / tot; cuts.append(a)
    edges = [s['start']] + cuts + [s['end']]
    return list(zip(edges[:-1], edges[1:]))
SUBIMG = []; CHUNKS = []
for s in SUBS:
    ch = split_sub(s['text'])
    for (a, b), c in zip(chunk_times(s, ch), ch):
        if b > a:
            CHUNKS.append((a, b, c))
            SUBIMG.append((a, b, fit_layer(lambda sz: text_layer(colorize(c), F(sz), stroke=ST['sub_stroke'], pad=10), ST['sub_size'], L.sub_max_w)))
HT = G('HOOK_TITLE', [])
_TW = W if L.legacy else (L.safe[2] - L.safe[0]) - 20   # legacy: the measured layout never shrank titles
HTI = [fit_layer(lambda sz: text_layer([(HT[0], WHITE)], F(sz), stroke=7), 76, _TW)] if HT else []
if len(HT) > 1: HTI.append(fit_layer(lambda sz: text_layer(colorize(HT[1], WHITE), F(sz), stroke=8), 88, _TW))
BADGE = np.asarray(O.badge(G('HOOK_BADGE_TEXT', "精彩预告"), size=36)) if ST['hook_badge'] else None

def _hook_block():
    """(badge_cy, [line centre y], scale) of the hook title block. Default spot: top of the safe box. If that
    covers the face core (brows..chin) of any hook frame (face boxes from face_track, after the punch-in), try
    the block pushed up to the safe top, then shrunk there (down to 0.7x), then in the band between the chin
    and the captions (down to 0.62x); else the spot covering least."""
    ys = [L.title_y + (60 if BADGE is not None else 0) + (HTI[0].shape[0] - 18) * i for i in range(len(HTI))] if HTI else []
    by = L.badge_y if BADGE is not None else None
    items = [(y, im) for y, im in zip(ys, HTI)] + ([(by, BADGE)] if BADGE is not None else [])
    if not items: return by, ys, 1.0
    top = min(y - im.shape[0] / 2 for y, im in items); bot = max(y + im.shape[0] / 2 for y, im in items)
    wmax = max(im.shape[1] for _, im in items); h = bot - top
    if L.legacy and not HAVE_FACE: return by, ys, 1.0
    hook_sids = {sid_at(a + (b - a) * f) for hk in HOOKS for a, b in ([hk] if not isinstance(hk[0], (list, tuple)) else hk)
                 for f in (0.1, 0.5, 0.9)}
    cores = [face_core(face_on_canvas(s_)) for s_ in hook_sids]
    hit = lambda y, k: sum(overlap((CXM - wmax * k / 2, y, CXM + wmax * k / 2, y + h * k), c) for c in cores)
    cands = [(top, 1.0)] + [(L.safe[1] + 8, k) for k in (1.0, 0.9, 0.8, 0.7)] + \
            [(L.cap[1] - 16 - h * k, k) for k in (1.0, 0.9, 0.8, 0.7, 0.62)]
    best = next(((y, k) for y, k in cands if hit(y, k) <= 0), None) or min(cands, key=lambda c: hit(*c))
    y0, k = best
    if (y0, k) != (top, 1.0):
        print(f"hook title moved {y0 - top:+.0f}px, scale {k:.2f}, to keep it off the face")
    m = lambda y: y0 + (y - top) * k
    return (None if by is None else m(by)), [m(y) for y in ys], k
HOOK_BADGE_Y, HOOK_TITLE_Y, HOOK_K = _hook_block()

def stamp_img(text, ang): return np.asarray(O.stamp(text, ang, size=56))
def pop_img(text, col, size):
    c = YEL + (255,) if col == 'Y' else (255, 128, 20, 255)
    return np.asarray(D.text_layer([(text, c)], F(size), stroke=max(8, size // 14)).rotate(-4, expand=True, resample=Image.BICUBIC))
def token_img(text):
    f = F(56); im = D.rounded_rect((int(tl(text, f)) + 56, 92), 18, (15, 15, 18, 235), outline=YEL, width=3)
    ImageDraw.Draw(im).text((im.width / 2, 46), text, font=f, fill=YEL + (255,), anchor='mm'); return np.asarray(im)

def _pop_xy(b, im, x, y):
    """Authoring-frame centre -> canvas, clamped above the captions and off the face core / button column."""
    if L.legacy: return x, y
    x, y = L.map_point(x, y, face(sid_at(b)))
    w, h = im.shape[1], im.shape[0]
    x0, y0 = L.clamp_rect(x - w / 2, y - h / 2, w, h)
    fb = face_core(face_on_canvas(sid_at(b)))
    if overlap((x0, y0, x0 + w, y0 + h), fb) > 0:            # never over the mouth: drop below the chin
        x0, y0 = L.clamp_rect(x0, fb[3] + 20, w, h)
    return x0 + w / 2, y0 + h / 2
def _stamp_xy(b, im, x, y):
    if L.legacy: return x, y
    x, y = L.map_point(x, y, face(sid_at(b)))
    return L.clamp_rect(x, y, im.shape[1], im.shape[0])
POPI = []
if ST['pops']:
    for b, t, col, x, y, sz, hold in G('POPS', []):
        im = pop_img(t, col, sz); POPI.append((b, im, *_pop_xy(b, im, x, y), hold))
STI = []
if ST['stamps']:
    for b0, b1, t, x, y, ang in G('STAMPS', []):
        im = stamp_img(t, ang); STI.append((b0, b1, im, *_stamp_xy(b0, im, x, y)))
CIRI = [(t0, t1, text_layer([(ti, WHITE)], F(66), stroke=6), [(t, token_img(k)) for t, k in toks], grid)
        for t0, t1, ti, toks, grid in G('CIRCLES', [])] if ST['circles'] else []
CARI = [(t0, t1, fit_layer(lambda sz: text_layer([(ti, YEL + (255,))], F(sz), stroke=6), 70, L.card_col_w),
         [(t, fit_layer(lambda sz: text_layer(colorize(l), F(sz), stroke=5), 50, L.card_col_w)) for t, l in ls])
        for t0, t1, ti, ls in G('CARDS', [])] if ST['cards'] else []

def _boxes_during(b0, b1):
    return [face_on_canvas(s['sid']) for s in SUBS if s['start'] < b1 and s['end'] > b0] or [face_on_canvas(-1)]

# callouts (notes style): top-left bubble with an accent rail (overlays.callout; white on 'notes-yellow')
CALI = []
if ST['callouts']:
    for t, dur, txt in G('CALLOUTS', []):
        im, pad = D.shadow(O.callout(txt, ST['callout_theme'], max_w=L.callout_max_w, scale=40 / 34, keywords=_KW))
        x, y = L.callout_xy
        if not (L.legacy and not HAVE_FACE):
            w, h = im.width - 2 * pad, im.height - 2 * pad
            r = pick([(x, y, x + w, y + h)] + L.side_cands(w, h), _boxes_during(t, t + dur * BS), L.keep)
            x, y = r[0], r[1]
        CALI.append((t, t + dur * BS, np.asarray(im), x - pad, y - pad))
# 记笔记 panels (notes style): bottom card (vertical) / side card (horizontal), red header, yellow tag, bullets
# revealed one by one as she says them. Kept local (overlays.notes_panel renders all bullets at once).
PANI = []
def _panel(title, bullets, k=1.0):
    """记笔记 card at metric scale k: (shadowed bg, pad, [(t, row layer, dx, dy)], width, height)."""
    n = len(bullets); RW = L.panel_w; HH = int(96 * k); ROW = int(66 * k); ph = HH + int(26 * k) + n * ROW + int(22 * k)
    bg = D.rounded_rect((RW, ph), 28, (255, 255, 255, 242)); d = ImageDraw.Draw(bg)
    d.rounded_rectangle([0, 0, RW - 1, HH], 28, fill=RED + (255,)); d.rectangle([0, HH - 30, RW - 1, HH], fill=RED + (255,))
    d.text((40, HH / 2), title, font=D.fit_font(title, 'cjk-bold', int(48 * k), RW - 260), fill='white', anchor='lm')
    tag = O.tag(G('NOTES_TAG', O.notes_tag_default()), angle=4, size=int(32 * k), fill=YEL, text_fill=INK)
    bg.alpha_composite(tag, (RW - tag.width - 24, (HH - tag.height) // 2))
    bgs, pad = D.shadow(bg, 18, 10, 110); rows = []
    for i, (rt, txt) in enumerate(bullets):
        row = Image.new('RGBA', (RW - 60, ROW), (0, 0, 0, 0)); dr = ImageDraw.Draw(row)
        dr.ellipse([6, ROW / 2 - 9 * k, 24 * k, ROW / 2 + 9 * k], fill=RED + (255,))
        D.draw_runs(dr, (48 * k, ROW / 2), txt, D.fit_font(txt, 'cjk-bold', int(44 * k), RW - 120), INK + (255,), (214, 40, 70, 255), _KW, anchor='lm')
        rows.append((rt, np.asarray(row), 30, HH + int(26 * k) + i * ROW))
    return bgs, pad, rows, RW, ph
if ST['panels']:
    for p0, p1, title, bullets in G('PANELS', []):
        for k in ((1.0,) if L.legacy else (1.0, 0.88, 0.78)):   # vertical: shrink until it clears the chin
            bgs, pad, rows, RW, ph = _panel(title, bullets, k)
            if L.portrait:
                x = (W - RW) / 2; top = ST['sub_y'] - 60 * k - ph
            else:   # landscape: on the side away from the face, ending above the captions
                fb = np.mean(_boxes_during(p0, p1), 0); side_l = (fb[0] + fb[2]) / 2 > W / 2
                x = L.safe[0] + 10 if side_l else L.safe[2] - 10 - RW
                for kx0, ky0, kx1, ky1 in L.keep: x = min(x, kx0 - RW - 10)
                top = max(L.safe[1] + 70, L.cap[1] - 30 - ph)
            if L.legacy or not L.portrait or not any(overlap((x, top, x + RW, top + ph), face_core(b_)) > 0 for b_ in _boxes_during(p0, p1)):
                break
        PANI.append((p0, p1, np.asarray(bgs), x - pad, top - pad, [(max(rt, p0), im, x + dx, top + dy) for rt, im, dx, dy in rows]))

# ---------------- B-roll (broll.py): cut-away / picture-in-picture / split screen at sentence anchors ----------------
BRI = BR.load(G('BROLL', []), L, YEL)
_LBLF = F(30)
for it in BRI:
    it.label = BR.badge_layer(it.d['label'], _LBLF) if it.d.get('label') else None
    if it.mode == 'pip':
        fw = it.d.get('w', 0.5 if L.portrait else 0.36); w = int(W * fw)
        ar = it.src.h / it.src.w
        h = int(min(w * ar, (L.content_box()[3] - L.content_box()[1]) * (0.5 if L.portrait else 0.7)))
        if it.screen: h = int(min(w * min(ar, 1.25), h))
        pos = it.d.get('pos', 'auto')
        if pos != 'auto':
            bx0, by0, bx1, by1 = L.content_box(); top = by0 + 40
            xy = dict(tl=(bx0, top), tr=(bx1 - w, top), bl=(bx0, by1 - h), br=(bx1 - w, by1 - h))[pos]
            it.rect = (*xy, xy[0] + w, xy[1] + h)
        else:   # corner/side clear of the face core; on a frame-filling face shrink the card before overlapping
            boxes = _boxes_during(it.t0, it.t1); best = None
            for k in (1.0, 0.85, 0.7, 0.58):
                r = pick(L.side_cands(int(w * k), int(h * k)), boxes, L.keep)
                sc = sum(overlap(r, face_core(c)) for c in boxes)
                if best is None or sc < best[0]: best = (sc, r)
                if sc <= 0: break
            it.rect = best[1]
missing = BR.exists(G('BROLL', []))
if missing: sys.exit(f"BROLL sources not found: {missing}")

def broll_frame(fr, it, b, t):
    """Apply one B-roll item to the frame (float RGB, canvas size). Returns the new frame."""
    dt = (b - it.t0) / BS; a_in = min(1.0, dt / 0.2); a_out = min(1.0, (it.t1 - b) / BS / 0.2); a = max(0.0, min(a_in, a_out))
    if it.mode == 'cut':
        if it.screen:
            out = BR.blur_fill(it.src.frame(dt), W, H, 0.5) + 18
            cb = L.content_box(); cw = int(min(W * (0.86 if L.portrait else 0.6), cb[2] - cb[0]))
            ch = int(cb[3] - cb[1] - 40)
            v = it.view(dt, cw, ch, b)
            if v.shape[0] > v.shape[1] * it.src.h / it.src.w + 2: v = v[:int(v.shape[1] * it.src.h / it.src.w) + 1]
            x0 = (W - cw) // 2; y0 = int(cb[1] + 20 + (ch - v.shape[0]) / 2)
            BR.paste_card(out, v, x0, y0, r=24, shadow=0.6)
            if it.label is not None: blit(out, it.label, x0 + 16, y0 + 16)
        else:
            out = it.view(dt, W, H, b)
        return fr * (1 - a) + out * a
    if it.mode == 'split':
        side = it.d.get('side', 'top' if L.portrait else 'left')
        fx, fy, fw = face(sid_at(b))
        if L.portrait:
            hh = H // 2; v = it.view(dt, W, hh, b) if not it.screen else _screen_box(it, dt, b, W, hh)
            y = int(np.clip(fy + 0.15 * hh - hh / 2, 0, H - hh)); me = fr[y:y + hh]
            out = np.empty_like(fr)
            if side == 'top': out[:hh] = v; out[hh:hh + me.shape[0]] = me
            else: out[:hh] = me; out[hh:] = v[:H - hh]
            out[hh - 3:hh + 3] = 255
        else:
            hw = W // 2; v = it.view(dt, hw, H, b) if not it.screen else _screen_box(it, dt, b, hw, H)
            x = int(np.clip(fx - hw / 2, 0, W - hw)); me = fr[:, x:x + hw]
            out = np.empty_like(fr)
            if side == 'left': out[:, :hw] = v; out[:, hw:] = me
            else: out[:, :hw] = me; out[:, hw:] = v
            out[:, hw - 3:hw + 3] = 255
        if it.label is not None:
            blit(out, it.label, L.safe[0] + 10 if L.portrait or side == 'left' else W // 2 + 20,
                 (L.safe[1] + 70) if (not L.portrait or side == 'top') else H // 2 + 20)
        return fr * (1 - a) + out * a
    # pip
    x0, y0, x1, y1 = (int(v) for v in it.rect); w, h = x1 - x0, y1 - y0
    sc = ease_pop(dt, 0.22, 0.85)
    v = it.view(dt, w, h, b)
    if sc != 1.0:
        v = cv2.resize(v, (max(8, int(w * sc)), max(8, int(h * sc)))); x0 += (w - v.shape[1]) // 2; y0 += (h - v.shape[0]) // 2
    BR.paste_card(fr, v, x0, y0, r=22, shadow=0.55, border=(255, 255, 255), alpha=a)
    if it.label is not None: blit(fr, it.label, x0 + 14, y0 + 14, a)
    return fr
def split_geom(it, b):
    """(side, face box on the split output) for a split item at body time b (zoom is off under a split)."""
    side = it.d.get('side', 'top' if L.portrait else 'left')
    fx, fy, fw = face(sid_at(b)); x0, y0, x1, y1 = fbox(sid_at(b))
    if L.portrait:
        hh = H // 2; y = int(np.clip(fy + 0.15 * hh - hh / 2, 0, H - hh)); off = hh if side == 'top' else 0
        return side, (x0, y0 - y + off, x1, y1 - y + off)
    hw = W // 2; x = int(np.clip(fx - hw / 2, 0, W - hw)); off = hw if side == 'left' else 0
    return side, (x0 - x + off, y0, x1 - x + off, y1)
def split_caption_xy(it, b, im):
    """Captions under a split screen go where the face is not: the platform caption spot if it is clear of the
    speaker's face core, else inside the B-roll pane right next to the seam, else centred on the seam
    (vertical); on 16:9 the caption moves under the B-roll half. Falls back to the spot covering least."""
    side, fb = split_geom(it, b); core = face_core(fb); ch, cw = im.shape[0], im.shape[1]
    rect = lambda cx, cy: (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    if L.portrait:
        hh = H // 2; pane = (hh - 24 - ch / 2) if side == 'top' else (hh + 24 + ch / 2)
        cands = [(CXM, ST['sub_y']), (CXM, pane), (CXM, hh)]
        cands = [(x, y) for x, y in cands if L.safe[1] + ch / 2 <= y <= L.safe[3] - ch / 2] or cands
    else:
        hw = W // 2; bx = hw / 2 if side == 'left' else hw + hw / 2
        cands = [(CXM, ST['sub_y']), (bx, ST['sub_y'])]
    return next((c for c in cands if overlap(rect(*c), core) <= 0), None) or min(cands, key=lambda c: overlap(rect(*c), core))
def _screen_box(it, dt, b, w, h):
    out = BR.blur_fill(it.src.frame(dt), w, h, 0.5) + 18
    cw, ch = int(w * 0.88), int(h * 0.86); v = it.view(dt, cw, ch, b)
    BR.paste_card(out, v, (w - cw) // 2, (h - v.shape[0]) // 2, r=20, shadow=0.5); return out

# ---------------- progress bars (overlays.progress_bar, body-time clock) ----------------
CH = G('CHAPTERS', [])
def progress_refined(fr, b, alpha):
    strip = np.asarray(O.progress_bar(CH, b, BODY_T, style='refined', width=W, scale=L.bar_s))
    y0 = O._s(12, L.bar_s); cut_y = y0 + O._s(22, L.bar_s)
    blit(fr, strip[:cut_y], 0, L.pb_y - y0, alpha)
    # the '01 / 03 label' pill fades + slides in at every chapter change (the bar itself does not move)
    a = next((c0 for c0, c1, _ in CH if c0 <= b < c1), CH[-1][0] if b >= CH[-1][1] else CH[0][0])
    ca = min(1, (b - a) / BS / 0.35) if (a > CH[0][0] or b > 0.35) else 1
    blit(fr, strip[cut_y:], 0, L.pb_y - y0 + cut_y + int(8 * (1 - ca)), alpha * ca)
def progress_classic(fr, b, alpha):
    blit(fr, np.asarray(O.progress_bar(CH, b, BODY_T, style='classic', width=W, x0=L.classic_x[0], x1=L.classic_x[1], scale=L.bar_s)), 0, L.classic_y + 14 - O._s(14, L.bar_s), alpha)

# ---------------- SFX + loudness ----------------
def mix_audio():
    """base audio -> two-pass loudnorm (so SFX gains sit against a voice at the target) -> + SFX -> two-pass again."""
    audio.loudnorm_2pass(BASE, 'voice.wav', lufs=LUFS, tp=TP)
    if not ST['sfx']:
        os.replace('voice.wav', 'mix.wav'); return
    a, _ = audio.read_wav('voice.wav')
    ev = [(b2f(b), 'pop') for b, *_ in POPI] + [(b2f(b0), 'thud') for b0, *_ in STI]
    for t0, t1, _, toks, _ in CIRI: ev += [(b2f(t0) - 0.12, 'whoosh'), (b2f(t1) - 0.12, 'whoosh')] + [(b2f(t), 'pop') for t, _ in toks]
    for t0, t1, *_ in CARI: ev += [(b2f(t0) - 0.12, 'whoosh'), (b2f(t1) - 0.12, 'whoosh')]
    for it in BRI: ev += [(b2f(it.t0) - 0.12, 'whoosh')] + ([(b2f(it.t1) - 0.12, 'whoosh')] if it.mode != 'pip' else [])
    ev += [(t, 'whoosh') for t in M.join_starts[:-1]] + ([(MAIN0 - 0.1, 'whoosh')] if HOOKS else [])
    audio.write_wav('mix_raw.wav', audio.place_sfx(a, ev), audio.SR)
    audio.loudnorm_2pass('mix_raw.wav', 'mix.wav', lufs=LUFS, tp=TP)

def in_scene(b, scenes):
    for sc in scenes:
        if sc[0] <= b < sc[1]: return sc
    return None

# ---------------- per-frame composite ----------------
def compose(fr, t, captions=True):
    b = f2b(t); sid = sid_at(b); hook = M.is_hook(t)
    cir = None if hook else in_scene(b, CIRI); crd = None if hook else in_scene(b, CARI)
    br = None if (hook or cir or crd) else BR.active(BRI, b)
    if cir:
        t0, t1, title, toks, grid = cir; bg = blurbg(fr); rows = (len(toks) + 1) // 2 if grid else len(toks)
        R = L.circle_R(rows); tile, inner, ring = circle_inset(fr, sid, R); ccx, ccy = L.circle_center(R)
        sc = ease_pop((b - t0) / BS, 0.22, 0.6)
        if sc != 1.0:
            tile = cv2.resize(tile, None, fx=sc, fy=sc); inner = cv2.resize(inner, None, fx=sc, fy=sc)[..., None]; ring = cv2.resize(ring, None, fx=sc, fy=sc)[..., None]
        h = tile.shape[0]; x0, y0 = int(ccx - h / 2), int(ccy - h / 2)
        bg[y0:y0 + h, x0:x0 + h] = bg[y0:y0 + h, x0:x0 + h] * (1 - inner - ring) + tile * inner + 255 * ring; fr = bg
        blitc(fr, title, L.circ_title[0], L.circ_title[1], min(1, (b - t0) / BS / 0.2))
        for i, (tt, im) in enumerate(toks):
            if b < tt: continue
            if grid: row, col = divmod(i, 2); x, y = L.tok_x + (-L.tok_dx if col == 0 else L.tok_dx), L.tok_y0 + row * 108
            else: x, y = L.tok_x, L.tok_y0 + i * 108
            blitc(fr, im, x, y, 1, ease_pop((b - tt) / BS, 0.15, 1.4))
    elif crd:
        t0, t1, title, ls = crd; fr = card(fr, blurbg(fr), L.card_s, xy=L.card_xy)
        blitc(fr, title, L.card_title[0], L.card_title[1], min(1, (b - t0) / BS / 0.2))
        for i, (tt, im) in enumerate(ls):
            if b >= tt: blitc(fr, im, L.card_lines[0], L.card_lines[1] + i * 58, min(1, (b - tt) / BS / 0.2))
    elif ST['zoom'] and not (br and br.mode != 'pip'):
        fr = zoom(fr, sid_zoom(sid), sid)
    if br:
        fr = broll_frame(fr, br, b, t)
    if hook:
        if BADGE is not None: blitc(fr, BADGE, CXM, HOOK_BADGE_Y, min(1, t / 0.2), HOOK_K)
        for i, im in enumerate(HTI):
            st = 0.2 * i; blitc(fr, im, CXM, HOOK_TITLE_Y[i], min(1, max(0, t - st) / 0.2), HOOK_K * ease_pop(max(0, t - st), 0.2, 1.3))
    panel_on = (not hook) and any(p0 <= b < p1 for p0, p1, *_ in PANI)
    covered = br is not None and br.mode != 'pip'
    if not cir and not crd and not panel_on and not covered and (ST['fx_in_hooks'] or not hook):
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
        elif CH and ST['progress'] == 'classic': progress_classic(fr, b, pa)
    if captions:
        for a0, a1, im in SUBIMG:
            if a0 <= b < a1:
                cx, cy = split_caption_xy(br, b, im) if br is not None and br.mode == 'split' else (CXM, ST['sub_y'])
                blitc(fr, im, cx, cy); break
    return fr

def render(out, captions=True, audio_path='mix.wav'):
    ff = media.ffmpeg_bin()
    src = subprocess.Popen([ff, '-v', 'error', '-i', BASE, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', audio_path, '-map', '0:v', '-map', '1:a', *media.delivery_args(crf=17, preset='slow'), out], stdin=subprocess.PIPE)
    fi = 0; N = W * H * 3
    while True:
        buf = src.stdout.read(N)
        if len(buf) < N: break
        fr = compose(np.frombuffer(buf, np.uint8).reshape(H, W, 3).astype(np.float32), fi / FPS, captions)
        enc.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes()); fi += 1
        if fi % 900 == 0: print('frame', fi, f'{fi/FPS:.1f}/{TOTAL:.1f}', flush=True)
    enc.stdin.close(); enc.wait()

def final_cues():
    """Caption chunks in FINAL-video seconds (hooks included), as subs.Cue dicts for vstudio.export."""
    out = []
    for i, it in enumerate(M.tm.items):
        if it['kind'] != 'clip': continue
        lo = it['src0'] + it.get('mute_head', 0.0) + M.off[i]; hi = it['src1'] - it.get('mute_tail', 0.0) + M.off[i]
        for a, b, text in CHUNKS:
            a2, b2 = max(a, lo), min(b, hi)
            if b2 - a2 > 0.05:
                tf = lambda s: it['dst0'] + (s - M.off[i] - it['src0']) / it['speed']
                out.append(vsubs.Cue(round(tf(a2), 3), round(tf(b2), 3), text).to_dict())
    return sorted(out, key=lambda c: c['start'])

def preview(ts):
    outs = []; tw = 360 if L.portrait else 640; th = int(round(tw * H / W))
    for t in ts:
        raw = subprocess.run([media.ffmpeg_bin(), '-v', 'error', '-ss', f'{t:.3f}', '-i', BASE, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
        fr = compose(np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.float32), t)
        outs.append(Image.fromarray(np.clip(fr, 0, 255).astype(np.uint8)).resize((tw, th)))
    im = Image.new('RGB', (tw * len(outs), th))
    for i, o in enumerate(outs): im.paste(o, (tw * i, 0))
    name = f'preview_{PROF.name}-{PROF.orientation}.jpg' if (_PLAT_ARG or G('PLATFORM', None)) else 'preview.jpg'
    im.save(name, quality=85); print('wrote', os.path.abspath(name))

if __name__ == '__main__':
    print(f"HOOK_DUR={M.body_start:.2f} BODY_START={M.body_start:.2f} TOTAL={TOTAL:.2f}  canvas {W}x{H} ({PROF.key})"
          + (f"  source upscale x{UPSCALE:.2f}" if UPSCALE > 1.01 else ""))
    if STAGE in ('all', 'base'): build_base()
    if STAGE in ('all', 'comp'):
        mix_audio(); render(C.OUT)
        if CLEAN:
            stem = os.path.splitext(C.OUT)[0]
            render(stem + '.clean.mp4', captions=False)
            json.dump(final_cues(), open(stem + '.cues.json', 'w'), ensure_ascii=False, indent=1)
            print('clean master', stem + '.clean.mp4', '+', stem + '.cues.json')
        from vstudio import platform as P
        for w_ in P.check_length(PROF, TOTAL): print('WARN', w_)
    if STAGE == 'preview': preview([float(x) for x in sys.argv[3].split(',')])
    tl_ = M.timeline(); tl_.update(PLATFORM=PROF.key, W=W, H=H)
    json.dump(tl_, open('timeline.json', 'w'))
