#!/usr/bin/env python3
"""Notes-board 小红书 cover: face visible, mini 记笔记 panels mirroring video panels + fun sticky,
rotated with shadow, kept inside 4:3 center-crop safe area x[240,1680]. Also writes cover43.png preview.
Usage: python3 make_cover.py work/config.py"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, importlib.util
from vstudio.config import font, persona
_PS = persona(); _BR = _PS.get("brand") or {}; _SP = _PS.get("speed") or {}
def _rgb(h, d): h = (h or d).lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
LUFS = (_PS.get("audio") or {}).get("loudness_lufs", -14)
from PIL import Image, ImageDraw, ImageFont, ImageFilter

cfg = sys.argv[1] if len(sys.argv) > 1 else "config.py"
spec = importlib.util.spec_from_file_location("config", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
WORK, SRC = C.WORK, C.SRC
OUT = C.COVER_OUT
RED, INK, YEL, DARK = _rgb(_BR.get("accent"), "FF2442"), (32,33,38), _rgb(_BR.get("highlight"), "FFD640"), (16,18,24)
def F(s): return ImageFont.truetype(font("cjk-bold"), s)

frame = f"{WORK}/cover_frame.jpg"
import subprocess  # extract the cover frame
# COVER_EQ: optional ffmpeg eq on the grabbed frame. The cards are near-black, so a frame that
# looked fine in the video often reads as a dark cover once they are pasted on. Lift it here.
EQ = getattr(C, "COVER_EQ", None)
cmd = ["ffmpeg","-y","-ss",str(C.COVER_FRAME_T),"-i",SRC,"-frames:v","1","-q:v","2","-update","1"]
if EQ: cmd += ["-vf", EQ]
subprocess.run(cmd + [frame], capture_output=True)

img = Image.open(frame).convert("RGBA"); W, H = img.size
# mute bottom subtitle band. COVER_MUTE_BOTTOM=0 skips it when the frame carries no burned-in sub.
MUTE = getattr(C, "COVER_MUTE_BOTTOM", 150)
if MUTE:
    # Must be a SOLID cover over the subtitle band. A gradient that peaks at alpha 150 lets white
    # burned-in subtitles show through (happened on two covers). Feather the top 24px, rest opaque.
    FEATH = 24
    g = Image.new("L",(W,H),0); gd = ImageDraw.Draw(g)
    gd.rectangle([0, H-MUTE+FEATH, W, H], fill=255)
    for i in range(FEATH): gd.line([(0,H-MUTE+i),(W,H-MUTE+i)], fill=int(255*i/FEATH))
    img = Image.composite(Image.new("RGBA",(W,H),(12,13,16,255)), img, g)

MT = getattr(C, "COVER_MUTE_TOP", 0)
if MT:
    # Some 剪映 exports burn subtitles at the top; cover those solidly too.
    FEATH = 20
    g = Image.new("L",(W,H),0); gd = ImageDraw.Draw(g)
    gd.rectangle([0, 0, W, MT-FEATH], fill=255)
    for i in range(FEATH): gd.line([(0,MT-FEATH+i),(W,MT-FEATH+i)], fill=int(255*(1-i/FEATH)))
    img = Image.composite(Image.new("RGBA",(W,H),(12,13,16,255)), img, g)

def paste(note, cx, cy, ang):
    a = note.split()[3]
    blk = Image.new("RGBA", note.size,(0,0,0,255)); blk.putalpha(a.point(lambda p:int(p*0.42)))
    blk = blk.rotate(ang, expand=True, resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(8))
    rot = note.rotate(ang, expand=True, resample=Image.BICUBIC)
    img.alpha_composite(blk,(cx-blk.width//2+10, cy-blk.height//2+12))
    img.alpha_composite(rot,(cx-rot.width//2, cy-rot.height//2))

def mini_panel(title, bullet):
    ft, fbu, ftag = F(28), F(29), F(20); tmp = ImageDraw.Draw(Image.new("RGBA",(4,4)))
    tw = tmp.textbbox((0,0),title,font=ft)[2]; bw = tmp.textbbox((0,0),bullet,font=fbu)[2]
    tg = tmp.textbbox((0,0),"记笔记↓",font=ftag)[2]; PADX=20; HEAD=52; body=58
    Wc = max(tw+24+tg+26, PADX+18+bw+PADX)+PADX; Hc = HEAD+body
    c = Image.new("RGBA",(Wc,Hc),(0,0,0,0)); d=ImageDraw.Draw(c)
    d.rounded_rectangle([0,0,Wc-1,Hc-1],radius=14,fill=DARK+(245,))
    d.rounded_rectangle([0,0,Wc-1,HEAD+14],radius=14,fill=RED+(255,)); d.rectangle([0,HEAD-2,Wc-1,HEAD+14],fill=DARK+(245,))
    d.text((PADX,(HEAD-32)//2+2),title,font=ft,fill=(255,255,255))
    px=Wc-tg-22-18; d.rounded_rectangle([px,11,px+tg+20,11+30],radius=9,fill=YEL+(255,)); d.text((px+10,15),"记笔记↓",font=ftag,fill=(20,20,20))
    cy=HEAD+body//2; d.ellipse([PADX,cy-4,PADX+8,cy+4],fill=RED+(255,)); d.text((PADX+18,HEAD+(body-34)//2),bullet,font=fbu,fill=(245,246,250))
    return c

# place: head x-range avoids face. 2 left + 1 right; fun sticky right-lower.
hx0, hx1 = C.COVER_HEAD_X
left_cx = max(470, hx0//2)         # left column center
mp = [mini_panel(t, b) for (t, b) in C.COVER_PANELS]
spots = [(490, 300, -4), (470, 560, 3), (1466, 250, 3), (470, 800, -3)]  # add more if >3 panels
for i, card in enumerate(mp):
    cx, cy, ang = spots[i % len(spots)]; paste(card, cx, cy, ang)

# fun yellow sticky
ftitle, lines, hl = C.COVER_FUN
FW = 412; FH = 70 + len(lines)*58 + 18
fn = Image.new("RGBA",(FW,FH),(0,0,0,0)); fd=ImageDraw.Draw(fn)
fd.rounded_rectangle([0,0,FW-1,FH-1],radius=22,fill=YEL+(255,))
fd.rounded_rectangle([0,0,FW-1,70],radius=22,fill=(20,20,22,255)); fd.rectangle([0,50,FW-1,70],fill=(20,20,22,255))
hb=fd.textbbox((0,0),ftitle,font=F(33)); fd.text(((FW-(hb[2]-hb[0]))//2,14),ftitle,font=F(33),fill=YEL)
for i, lnt in enumerate(lines):
    col = RED if lnt==hl else (28,28,30); fnt = F(40) if lnt==hl else F(34)
    fd.text((30, 92+i*58), lnt, font=fnt, fill=col)
paste(fn, 1466, 600, -3)

# top kicker
d = ImageDraw.Draw(img); k = C.COVER_KICKER; kb = d.textbbox((0,0),k,font=F(44)); kx=(W-(kb[2]-kb[0]))//2
d.rounded_rectangle([kx-26,34,kx+(kb[2]-kb[0])+26,34+70],radius=16,fill=RED+(255,))
d.text((kx,48),k,font=F(44),fill=(255,255,255))

img.convert("RGB").save(OUT, quality=93)
# 4:3 center-crop preview (what 小红书 shows)
im = img.convert("RGB"); cw = int(H*4/3); x0 = (W-cw)//2
im.crop((x0,0,x0+cw,H)).save(f"{WORK}/cover43.png")
print(f"cover -> {OUT}  | 4:3 preview -> {WORK}/cover43.png (check the crop, not the full frame)")
