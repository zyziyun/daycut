#!/usr/bin/env python3
"""Render overlay PNGs from config: dim chapter bar, active-chapter highlights, hook badge,
callout bubbles, 记笔记 panels. Writes assets.json (manifest read by build_filter.py).
Usage: python3 make_assets.py work/config.py   (template: examples/h_config_example.py)"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, json, re, importlib.util
from vstudio.config import font, persona
_PS = persona(); _BR = _PS.get("brand") or {}; _SP = _PS.get("speed") or {}
def _rgb(h, d): h = (h or d).lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
LUFS = (_PS.get("audio") or {}).get("loudness_lufs", -14)
from PIL import Image, ImageDraw, ImageFont

cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.py"
spec = importlib.util.spec_from_file_location("config", cfg_path)
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
OUT, MAIN_DUR = C.WORK, C.MAIN_DUR
RED, YEL = _rgb(_BR.get("accent"), "FF2442"), _rgb(_BR.get("highlight"), "FFD60A")
os.makedirs(OUT, exist_ok=True)
def F(s, bold=False): return ImageFont.truetype(font("cjk-bold" if bold else "cjk"), s)

BAR_X, BAR_W = 80, 1760
BAR_Y, BAR_H, TICK_TOP, TICK_H, LABEL_Y = 22, 5, 17, 15, 40
def pos(t): return BAR_X + t / MAIN_DUR * BAR_W

# dim chapter bar
bar = Image.new("RGBA", (1920, 80), (0, 0, 0, 0)); d = ImageDraw.Draw(bar)
d.rectangle([BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H], fill=(255, 255, 255, 95))
for s, _, _ in C.CHAPTERS:
    x = int(round(pos(s))); d.rectangle([x-1, TICK_TOP, x+1, TICK_TOP+TICK_H], fill=(255,255,255,235))
d.rectangle([BAR_X+BAR_W-1, TICK_TOP, BAR_X+BAR_W+1, TICK_TOP+TICK_H], fill=(255,255,255,235))
fl = F(22)
for s, e, label in C.CHAPTERS:
    cx = (pos(s)+pos(e))/2; w = d.textbbox((0,0), label, font=fl)[2]
    d.text((int(cx-w/2), LABEL_Y), label, font=fl, fill=(255,255,255,235), stroke_width=3, stroke_fill=(0,0,0,210))
bar.save(f"{OUT}/bar_overlay.png")

# active-chapter highlight labels (bright red, bigger)
fa = F(26); active = []
for k, (s, e, label) in enumerate(C.CHAPTERS):
    bb = fa.getbbox(label); tw, th = bb[2]-bb[0], bb[3]-bb[1]; pad = 8
    W, H = tw+pad*2, th+pad*2
    im = Image.new("RGBA", (W,H), (0,0,0,0)); di = ImageDraw.Draw(im)
    di.text((pad-bb[0], pad-bb[1]), label, font=fa, fill=RED+(255,), stroke_width=4, stroke_fill=(255,255,255,255))
    im.save(f"{OUT}/active_{k}.png")
    cx = (pos(s)+pos(e))/2
    active.append({"k": k, "x": int(round(cx-W/2)), "y": 1000+LABEL_Y+(th//2)-(H//2)-1, "s": s, "e": e})

# hook badge
bw, bh = 560, 76; badge = Image.new("RGBA", (bw,bh), (0,0,0,0)); db = ImageDraw.Draw(badge)
db.rounded_rectangle([0,0,bw-1,bh-1], radius=16, fill=RED+(240,))
fb = F(30, True); txt = getattr(C, "HOOK_BADGE_TEXT", "高光预告 · 完整版在下面"); bb = db.textbbox((0,0), txt, font=fb)
db.text(((bw-(bb[2]-bb[0]))//2, (bh-(bb[3]-bb[1]))//2-6), txt, font=fb, fill=(255,255,255))
badge.save(f"{OUT}/hook_badge.png")

# text wrap (keep latin/number runs intact)
def toks(s):
    out, i = [], 0
    while i < len(s):
        m = re.match(r"[A-Za-z0-9%/+.\-]+", s[i:])
        if m: out.append(m.group()); i += m.end()
        else: out.append(s[i]); i += 1
    return out
def wrap(text, font, maxw, dr):
    lines, cur = [], ""
    for t in toks(text):
        if dr.textbbox((0,0), cur+t, font=font)[2] > maxw and cur:
            lines.append(cur.rstrip()); cur = t if t.strip() else ""
        else: cur += t
    if cur.strip(): lines.append(cur.rstrip())
    return lines
tmp = ImageDraw.Draw(Image.new("RGBA", (10,10)))

# callouts (skip REMOVE)
fc = F(34); MAXW = 560; PADX, PADY, ACC, GAP, LG = 26, 18, 8, 14, 8
asc, desc = fc.getmetrics(); lh = asc+desc
co = []
for i, (anchor, dur, text) in enumerate(C.CALLOUTS):
    if anchor in getattr(C, "REMOVE", set()): continue
    lines = wrap(text, fc, MAXW, tmp)
    tw = max(tmp.textbbox((0,0), ln, font=fc)[2] for ln in lines)
    W = ACC+GAP+tw+PADX*2; H = len(lines)*lh+(len(lines)-1)*LG+PADY*2
    img = Image.new("RGBA", (W,H), (0,0,0,0)); dd = ImageDraw.Draw(img)
    dd.rounded_rectangle([0,0,W-1,H-1], radius=16, fill=(18,20,26,235))
    dd.rounded_rectangle([8,12,8+ACC,H-12], radius=4, fill=RED+(255,))
    tx, ty = 8+ACC+GAP+(PADX-8), PADY
    for ln in lines: dd.text((tx,ty), ln, font=fc, fill=(255,255,255,255)); ty += lh+LG
    img.save(f"{OUT}/callout_{i}.png")
    co.append({"i": i, "anchor": anchor, "dur": dur, "w": W, "h": H})

# 记笔记 panels
ft = F(34, True); fbu = F(30); PW = 620; PX2, PY2, HEAD, BG, DOT = 26, 20, 70, 16, 9
ba, bd2 = fbu.getmetrics(); blh = ba+bd2
pa = []
for p, (anchor, dur, title, bullets) in enumerate(C.PANELS):
    wr = [wrap(b, fbu, PW-PX2*2-22, tmp) for b in bullets]
    n = sum(len(w) for w in wr)
    H = HEAD + (PY2*2 + n*blh + (len(bullets)-1)*BG)
    img = Image.new("RGBA", (PW,H), (0,0,0,0)); dd = ImageDraw.Draw(img)
    dd.rounded_rectangle([0,0,PW-1,H-1], radius=18, fill=(16,18,24,240))
    dd.rounded_rectangle([0,0,PW-1,HEAD+18], radius=18, fill=RED+(255,))
    dd.rectangle([0,HEAD-2,PW-1,HEAD+18], fill=(16,18,24,240))
    tb = dd.textbbox((0,0), title, font=ft)
    dd.text((22, (HEAD-(tb[3]-tb[1]))//2-tb[1]), title, font=ft, fill=(255,255,255,255))
    tag = getattr(C, "NOTES_TAG", "记笔记 ↓"); tt = dd.textbbox((0,0), tag, font=fbu)[2]; px = PW-tt-22-24
    if 22 + dd.textbbox((0,0), title, font=ft)[2] > px - 10:
        print(f"WARN panel {p}: title runs under the 记笔记 tag -> {title}")
    dd.rounded_rectangle([px,16,px+tt+24,16+40], radius=12, fill=YEL+(255,))
    dd.text((px+12,16+6), tag, font=fbu, fill=(20,20,20,255))
    y = HEAD+PY2
    for w in wr:
        cy = y+blh//2; dd.ellipse([22,cy-DOT//2,22+DOT,cy+DOT//2], fill=RED+(255,))
        for ln in w: dd.text((22+DOT+14,y), ln, font=fbu, fill=(245,246,250,255)); y += blh
        y += BG
    img.save(f"{OUT}/panel_{p}.png")
    pa.append({"p": p, "anchor": anchor, "dur": dur, "w": PW, "h": H})

json.dump({"callouts": co, "panels": pa, "active": active}, open(f"{OUT}/assets.json","w"), ensure_ascii=False, indent=1)
print(f"callouts {len(co)} | panels {len(pa)} | active {len(active)} -> {OUT}")
