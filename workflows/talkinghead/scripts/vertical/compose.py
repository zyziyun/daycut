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
Built on vstudio: hook/body dissolves = cut.xfade_assemble (muted pads both sides, see ../montage.py),
loudness = audio.loudnorm_2pass, SFX = audio.place_sfx, text/badges/stamps/progress bars = draw/overlays,
subtitle chunk timing = asr.align_script on the strict_pass words. The per-frame animation engine is local.
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, json, re, subprocess, importlib.util
import numpy as np, cv2
from PIL import Image, ImageDraw
from vstudio import asr, audio, media, subs as vsubs
from vstudio import draw as D, overlays as O
from montage import Montage
from bodycut import mux

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
CFG = os.path.abspath(sys.argv[1]); STAGE = sys.argv[2] if len(sys.argv) > 2 else 'all'
os.chdir(os.path.dirname(CFG)); sys.path[:0] = [HERE, os.path.dirname(CFG)]
spec = importlib.util.spec_from_file_location('cfg', CFG); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)

DEFAULT_STYLE = dict(
    zoom=False, emph_zoom=1.32, alt_zoom=1.16,      # per-sentence punch-in rhythm (精剪)
    pops=False, stamps=False, circles=False, cards=False, sfx=False,
    progress='refined',                              # 'refined' | 'classic' | None
    callouts=False, panels=False,                    # notes-board strategies
    callout_theme='notes-yellow',                    # overlays theme of the callout bubble (white bubble, accent rail)
    hook_badge=False, fx_in_hooks=True,
    sub_size=54, sub_y=1525, sub_stroke=5,
)
ST = {**DEFAULT_STYLE, **getattr(C, 'STYLE', {})}
G = lambda name, default: getattr(C, name, default)
from vstudio.config import persona
_PS = persona(); _SPEED = _PS.get('speed') or {}
LUFS = (_PS.get('audio') or {}).get('loudness_lufs', -14)
SUBS = json.load(open(G('SEGS', 'segs.json')))['subs']
BODY_T = json.load(open(G('SEGS', 'segs.json')))['total']
HOOKS = C.HOOKS; HS = G('HOOK_SPEED', _SPEED.get('hook', 1.3)); BS = G('BODY_SPEED', _SPEED.get('body', 1.1)); XF = G('XF', 0.3)
GRADE = G('GRADE', "hqdn3d=1.2:1.2:3:3,eq=contrast=1.06:brightness=0.015:saturation=1.07:gamma=1.02,colorbalance=rs=-0.02:bs=0.015:rm=-0.01,cas=0.45")

# ---------------- timeline: hooks + body on one muted-pad dissolve chain (../montage.py) ----------------
BASE_SRC = 'base_src.mov'           # BODY video + AUDIO muxed by stream copy (xfade_assemble wants a/v per input)
def _mux():
    if not (os.path.exists(BASE_SRC) and all(os.path.getmtime(BASE_SRC) >= os.path.getmtime(p) for p in (C.BODY, C.AUDIO))):
        mux(C.BODY, C.AUDIO, BASE_SRC)
    return BASE_SRC
_mux()
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
               '-c:v', 'libx264', '-crf', '13', '-preset', 'medium', '-c:a', 'pcm_s16le', 'base.mov'])

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

# ---------------- draw helpers ----------------
def blit(fr, a, x, y, alpha=1.0, scale=1.0): D.alpha_paste(fr, a, (x, y), alpha, scale=scale)
def blitc(fr, a, cx, cy, alpha=1.0, scale=1.0): D.alpha_paste(fr, a, (cx, cy), alpha, center=True, scale=scale)
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
WORDS = json.load(open(G('SEGS', 'segs.json'))).get('words', [])
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
SUBIMG = []
for s in SUBS:
    ch = split_sub(s['text'])
    for (a, b), c in zip(chunk_times(s, ch), ch):
        if b > a: SUBIMG.append((a, b, text_layer(colorize(c), F(ST['sub_size']), stroke=ST['sub_stroke'], pad=10)))
HT = G('HOOK_TITLE', [])
HTI = [text_layer([(HT[0], WHITE)], F(76), stroke=7)] if HT else []
if len(HT) > 1: HTI.append(text_layer(colorize(HT[1], WHITE), F(88), stroke=8))
BADGE = np.asarray(O.badge(G('HOOK_BADGE_TEXT', "精彩预告"), size=36)) if ST['hook_badge'] else None

def stamp_img(text, ang): return np.asarray(O.stamp(text, ang, size=56))
def pop_img(text, col, size):
    c = YEL + (255,) if col == 'Y' else (255, 128, 20, 255)
    return np.asarray(D.text_layer([(text, c)], F(size), stroke=max(8, size // 14)).rotate(-4, expand=True, resample=Image.BICUBIC))
def token_img(text):
    f = F(56); im = D.rounded_rect((int(tl(text, f)) + 56, 92), 18, (15, 15, 18, 235), outline=YEL, width=3)
    ImageDraw.Draw(im).text((im.width / 2, 46), text, font=f, fill=YEL + (255,), anchor='mm'); return np.asarray(im)
POPI = [(b, pop_img(t, col, sz), x, y, hold) for b, t, col, x, y, sz, hold in G('POPS', [])] if ST['pops'] else []
STI = [(b0, b1, stamp_img(t, ang), x, y) for b0, b1, t, x, y, ang in G('STAMPS', [])] if ST['stamps'] else []
CIRI = [(t0, t1, text_layer([(ti, WHITE)], F(66), stroke=6), [(t, token_img(k)) for t, k in toks], grid)
        for t0, t1, ti, toks, grid in G('CIRCLES', [])] if ST['circles'] else []
CARI = [(t0, t1, text_layer([(ti, YEL + (255,))], F(70), stroke=6), [(t, text_layer(colorize(l), F(50), stroke=5)) for t, l in ls])
        for t0, t1, ti, ls in G('CARDS', [])] if ST['cards'] else []

# callouts (notes style): top-left bubble with an accent rail (overlays.callout; white on 'notes-yellow')
CALI = []
if ST['callouts']:
    for t, dur, txt in G('CALLOUTS', []):
        im, pad = D.shadow(O.callout(txt, ST['callout_theme'], max_w=880, scale=40 / 34, keywords=_KW))
        CALI.append((t, t + dur * BS, np.asarray(im), 60 - pad, 350 - pad))
# 记笔记 panels (notes style): bottom card, red header, yellow tag, bullets revealed one by one as she says them.
# Kept local (overlays.notes_panel renders all bullets at once; the per-row reveal needs separate row layers).
PANI = []
if ST['panels']:
    for p0, p1, title, bullets in G('PANELS', []):
        n = len(bullets); RW = 940; HH = 96; ROW = 66; ph = HH + 26 + n * ROW + 22; top = ST['sub_y'] - 60 - ph
        bg = D.rounded_rect((RW, ph), 28, (255, 255, 255, 242)); d = ImageDraw.Draw(bg)
        d.rounded_rectangle([0, 0, RW - 1, HH], 28, fill=RED + (255,)); d.rectangle([0, HH - 30, RW - 1, HH], fill=RED + (255,))
        d.text((40, HH / 2), title, font=F(48), fill='white', anchor='lm')
        tag = O.tag(G('NOTES_TAG', O.notes_tag_default()), angle=4, size=32, fill=YEL, text_fill=INK)
        bg.alpha_composite(tag, (RW - tag.width - 24, (HH - tag.height) // 2))
        bgs, pad = D.shadow(bg, 18, 10, 110); x = (W - RW) / 2; rows = []
        for i, (rt, txt) in enumerate(bullets):
            row = Image.new('RGBA', (RW - 60, ROW), (0, 0, 0, 0)); dr = ImageDraw.Draw(row)
            dr.ellipse([6, ROW / 2 - 9, 24, ROW / 2 + 9], fill=RED + (255,))
            D.draw_runs(dr, (48, ROW / 2), txt, F(44), INK + (255,), (214, 40, 70, 255), _KW, anchor='lm')
            rows.append((max(rt, p0), np.asarray(row), x + 30, top + HH + 26 + i * ROW))
        PANI.append((p0, p1, np.asarray(bgs), x - pad, top - pad, rows))

# ---------------- progress bars (overlays.progress_bar, body-time clock) ----------------
CH = G('CHAPTERS', [])
PB_Y = 250                       # refined: bar centre line ~ y 253; classic: track top at y 262
def progress_refined(fr, b, alpha):
    strip = np.asarray(O.progress_bar(CH, b, BODY_T, style='refined', width=W)); y0 = 12; cut_y = y0 + 22
    blit(fr, strip[:cut_y], 0, PB_Y - y0, alpha)
    # the '01 / 03 label' pill fades + slides in at every chapter change (the bar itself does not move)
    a = next((c0 for c0, c1, _ in CH if c0 <= b < c1), CH[-1][0] if b >= CH[-1][1] else CH[0][0])
    ca = min(1, (b - a) / BS / 0.35) if (a > CH[0][0] or b > 0.35) else 1
    blit(fr, strip[cut_y:], 0, PB_Y - y0 + cut_y + int(8 * (1 - ca)), alpha * ca)
def progress_classic(fr, b, alpha):
    blit(fr, np.asarray(O.progress_bar(CH, b, BODY_T, style='classic', width=W, x0=70, x1=1010)), 0, 262 - 14, alpha)

# ---------------- SFX + loudness ----------------
def mix_audio():
    """base audio -> two-pass loudnorm (so SFX gains sit against a voice at the target) -> + SFX -> two-pass again."""
    audio.loudnorm_2pass('base.mov', 'voice.wav', lufs=LUFS)
    if not ST['sfx']:
        os.replace('voice.wav', 'mix.wav'); return
    a, _ = audio.read_wav('voice.wav')
    ev = [(b2f(b), 'pop') for b, *_ in POPI] + [(b2f(b0), 'thud') for b0, *_ in STI]
    for t0, t1, _, toks, _ in CIRI: ev += [(b2f(t0) - 0.12, 'whoosh'), (b2f(t1) - 0.12, 'whoosh')] + [(b2f(t), 'pop') for t, _ in toks]
    for t0, t1, *_ in CARI: ev += [(b2f(t0) - 0.12, 'whoosh'), (b2f(t1) - 0.12, 'whoosh')]
    ev += [(t, 'whoosh') for t in M.join_starts[:-1]] + ([(MAIN0 - 0.1, 'whoosh')] if HOOKS else [])
    audio.write_wav('mix_raw.wav', audio.place_sfx(a, ev), audio.SR)
    audio.loudnorm_2pass('mix_raw.wav', 'mix.wav', lufs=LUFS)

def in_scene(b, scenes):
    for sc in scenes:
        if sc[0] <= b < sc[1]: return sc
    return None

# ---------------- per-frame composite ----------------
def compose(fr, t):
    b = f2b(t); sid = sid_at(b); hook = M.is_hook(t)
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
        elif CH and ST['progress'] == 'classic': progress_classic(fr, b, pa)
    for a0, a1, im in SUBIMG:
        if a0 <= b < a1: blitc(fr, im, 540, ST['sub_y']); break
    return fr

def render():
    ff = media.ffmpeg_bin()
    src = subprocess.Popen([ff, '-v', 'error', '-i', 'base.mov', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', 'mix.wav', '-map', '0:v', '-map', '1:a', *media.delivery_args(crf=17, preset='slow'), C.OUT], stdin=subprocess.PIPE)
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
        raw = subprocess.run([media.ffmpeg_bin(), '-v', 'error', '-ss', f'{t:.3f}', '-i', 'base.mov', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
        fr = compose(np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.float32), t)
        outs.append(Image.fromarray(np.clip(fr, 0, 255).astype(np.uint8)).resize((360, 640)))
    im = Image.new('RGB', (360 * len(outs), 640))
    for i, o in enumerate(outs): im.paste(o, (360 * i, 0))
    im.save('preview.jpg', quality=85); print('wrote', os.path.abspath('preview.jpg'))

if __name__ == '__main__':
    print(f"HOOK_DUR={M.body_start:.2f} BODY_START={M.body_start:.2f} TOTAL={TOTAL:.2f}")
    if STAGE in ('all', 'base'): build_base()
    if STAGE in ('all', 'comp'): mix_audio(); render()
    if STAGE == 'preview': preview([float(x) for x in sys.argv[3].split(',')])
    json.dump(M.timeline(), open('timeline.json', 'w'))
