"""Clip kit: render planned clips (lesson points, Q&A pairs, recaps) from one recording - or a screen recording
plus a camera - into per-platform files with themed cards, a persistent header, key-term cards, speaker labels,
face masks and (bilingual) captions.

    from vstudio import clipkit as CK
    spec = dict(id="p01", source="lesson.mp4", camera="cam.mov", offset=2.4, layout="pip",
                parts=[dict(kind="card", kicker="Today's phrase", title="break the ice", sub="打破僵局", dur=2.2),
                       dict(kind="src", a=8.2, b=36.5)],
                header=dict(kicker="Today's phrase", title="break the ice", sub="打破僵局"),
                terms=[dict(t=9.0, term="break the ice", gloss="打破僵局")],
                labels=[dict(a=8.2, b=12.0, text="Host")], mask=dict(mode="sticker", target="camera"))
    res = CK.render_clip(spec, words, canvas=(1080, 1920), workdir="work/p01")   # master + cues + keepouts
    out = CK.deliver(spec, words, platforms=["douyin", "youtube"], out_dir="out/p01", captions=dict(
        mode="bilingual", src="en", tgt="zh", highlight=["break the ice"]), fmt="lesson-points")

Canvas = the platform's (``vstudio.platform``): one master per distinct canvas among the targets (9:16 and 16:9),
so nothing is cropped by a later reframe. Layouts (``LAYOUTS``):

  screen   the main source only (a single file: the recording itself)
  camera   the camera file only
  pip      main source + the camera as a picture-in-picture inset (bottom right)
  band     vertical: main source band + camera band under it; horizontal: main source left, camera column right
Vertical masters put the picture in a band under a paper header (kind label + title + translation) that stays
on screen for the whole clip; horizontal masters put the header in a small card top-left.

Parts play in order: ``card`` (a full-canvas title / question card, silent) and ``src`` ([a, b] of the source,
the camera follows at ``offset``: t_cam = t_src + offset). ``speed`` applies to src parts (pitch kept).
Masks (``mask``): mode ``sticker`` (call-clips' cat, scaled to the tracked face) | ``blur`` | ``off``; target
``all`` (the main picture), ``camera`` (the camera tile), ``screen``, or ``regions`` [[x, y, w, h] source px]; one
face tracked per target box (``face.track_faces``), the hit rate reported per part (``mask_report``).
Captions: words of each src part -> final time -> ``subs.cues_from_words`` (term fixes applied); ``deliver``
translates (``vstudio.bilingual``), applies the caption mode, highlights the target phrases, burns them per
platform through ``vstudio.export`` (keep-outs: header, term cards, labels) and writes per-language SRT / VTT.
Every export is checked with ``vstudio.firstpass`` (``firstpass.json``).
"""
import json
import os
import shutil

from . import media

LAYOUTS = ("screen", "camera", "pip", "band")


class TranslationError(RuntimeError):
    """Bilingual / translated captions were asked for and no translation came back (never rendered mono silently)."""
FPS = 30
CARD_S = 2.2
STICKER = os.path.join(os.path.dirname(__file__), "..", "..", "workflows", "call-clips", "assets", "cat.png")


# --------------------------------------------------------------------------- theme / drawing
def _T():
    from . import theme as TH
    return TH.current()


def _hex(c):
    from . import theme as TH
    r, g, b = TH.rgb(_T(), c)
    return f"0x{r:02X}{g:02X}{b:02X}"


def _font(role_key, size):
    from . import draw as D
    T = _T()
    return D.load_font(T.get(role_key, role_key), size)


def _fit_lines(text, role_key, size, max_w, max_lines, min_size=28):
    from . import draw as D
    while True:
        f = _font(role_key, size)
        lines = D.wrap(text, f, max_w, balance=True)
        if len(lines) <= max_lines or size <= min_size:
            return f, lines[:max_lines] if len(lines) > max_lines else lines
        size = int(size * 0.9)


def _draw_block(im, x, y, w, kicker, title, sub, scale=1.0, align="left", title_size=None, max_lines=3):
    """kicker (accent, tracked) / title (theme title font, ink) / sub (ink2) / accent rule. Returns the bottom y."""
    from PIL import ImageDraw
    from . import draw as D
    from . import overlays as O
    from . import theme as TH
    T = _T()
    d = ImageDraw.Draw(im)
    u = scale
    if kicker:
        fk = _font("font_label", int(30 * u))
        kw = O.tracked_width(kicker.upper() if kicker.isascii() else kicker, fk, T.get("label_track", 0.12))
        kx = x if align == "left" else x + (w - kw) / 2
        O.draw_tracked(d, (kx, y), kicker.upper() if kicker.isascii() else kicker, fk, TH.rgba(T, "accent"),
                       T.get("label_track", 0.12))
        y += int(sum(fk.getmetrics()) * 1.6)
    if title:
        ft, lines = _fit_lines(title, "font_title", int((title_size or 84) * u), w, max_lines)
        lh = int(sum(ft.getmetrics()) * 1.12)
        for ln in lines:
            lw = D.text_width(ln, ft)
            lx = x if align == "left" else x + (w - lw) / 2
            D.draw_runs(d, (lx, y), ln, ft, TH.rgba(T, "ink"), TH.rgba(T, "accent"))
            y += lh
    if sub:
        fs, slines = _fit_lines(sub, "font_body", int(40 * u), w, 2, min_size=22)
        y += int(10 * u)
        for ln in slines:
            lw = D.text_width(ln, fs)
            lx = x if align == "left" else x + (w - lw) / 2
            d.text((lx, y), ln, font=fs, fill=TH.rgba(T, "ink2"))
            y += int(sum(fs.getmetrics()) * 1.2)
    y += int(22 * u)
    rw = int(96 * u)
    rx = x if align == "left" else x + (w - rw) / 2
    d.rectangle([rx, y, rx + rw, y + max(3, int(5 * u))], fill=TH.rgba(T, "accent"))
    return y + int(8 * u)


def card_image(kicker, title, sub=None, size=(1080, 1920), footer=None):
    """Full-canvas card on the theme paper: the block centred (vertically and horizontally), optional footer line
    (the asker's role, the lesson title). Opaque RGBA."""
    from PIL import Image, ImageDraw
    from . import theme as TH
    W, H = size
    T = _T()
    im = Image.new("RGBA", (W, H), TH.rgb(T, "paper") + (255,))
    u = min(W, H) / 1080
    margin = int(W * (0.1 if W < H else 0.14))
    probe = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    long_t = len(title or "") > 40
    h = _draw_block(probe, margin, 0, W - 2 * margin, kicker, title, sub, u, "center",
                    title_size=66 if long_t else 96, max_lines=5 if long_t else 3)
    y0 = int((H - h) / 2)
    _draw_block(im, margin, y0, W - 2 * margin, kicker, title, sub, u, "center", title_size=66 if long_t else 96,
                max_lines=5 if long_t else 3)
    if footer:
        f = _font("font_body", int(30 * u))
        ImageDraw.Draw(im).text((W / 2, H - int(H * 0.12)), footer, font=f, fill=TH.rgba(T, "ink2"), anchor="mm")
    return im


def header_image(kicker, title, sub, width, height, vertical=True):
    """The persistent header: vertical = transparent block on the paper above the picture; horizontal = a card
    (theme card colour, rounded) to sit top-left over the picture."""
    from PIL import Image
    from . import draw as D
    from . import theme as TH
    T = _T()
    if vertical:
        im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        u = width / 1080
        m = int(64 * u)
        probe = Image.new("RGBA", (width, height * 2), (0, 0, 0, 0))
        h = _draw_block(probe, m, 0, width - 2 * m, kicker, title, sub, u * 0.85, "left", title_size=80, max_lines=2)
        _draw_block(im, m, max(0, height - h - int(24 * u)), width - 2 * m, kicker, title, sub, u * 0.85, "left",
                    title_size=80, max_lines=2)
        return im
    u = height / 160
    probe = Image.new("RGBA", (width, 600), (0, 0, 0, 0))
    h = _draw_block(probe, int(28 * u), int(22 * u), width - int(56 * u), kicker, title, sub, u * 0.55, "left",
                    title_size=72, max_lines=2)
    card = D.rounded_rect((width, h + int(12 * u)), T.get("radius", 14),
                          TH.rgb(T, "card") + (int(255 * T.get("card_alpha", 0.95)),))
    _draw_block(card, int(28 * u), int(22 * u), width - int(56 * u), kicker, title, sub, u * 0.55, "left",
                title_size=72, max_lines=2)
    return card


def term_card(term, gloss=None, width=520, label=None, scale=1.0):
    """Key-term card: small label, the term (strong), its meaning (ink2) on the theme card."""
    from PIL import ImageDraw
    from . import draw as D
    from . import overlays as O
    from . import theme as TH
    T = _T()
    u = scale
    fl, ft, fg = _font("font_label", int(24 * u)), _font("font_strong", int(46 * u)), _font("font_body", int(32 * u))
    pad = int(28 * u)
    inner = width - 2 * pad
    tl = D.wrap(term, ft, inner, max_lines=2)
    gl = D.wrap(gloss, fg, inner, max_lines=2) if gloss else []
    h = pad + int(sum(fl.getmetrics()) * 1.5) + len(tl) * int(sum(ft.getmetrics()) * 1.1) + \
        (int(8 * u) + len(gl) * int(sum(fg.getmetrics()) * 1.2) if gl else 0) + pad
    im = D.rounded_rect((width, h), T.get("radius", 14), TH.rgb(T, "card") + (int(255 * T.get("card_alpha", 0.95)),))
    d = ImageDraw.Draw(im)
    y = pad
    O.draw_tracked(d, (pad, y), (label or "KEY TERM").upper() if (label or "KEY TERM").isascii() else label, fl,
                   TH.rgba(T, "accent"), T.get("label_track", 0.12))
    y += int(sum(fl.getmetrics()) * 1.5)
    for ln in tl:
        d.text((pad, y), ln, font=ft, fill=TH.rgba(T, "card_ink"))
        y += int(sum(ft.getmetrics()) * 1.1)
    if gl:
        y += int(8 * u)
        for ln in gl:
            d.text((pad, y), ln, font=fg, fill=TH.rgba(T, "ink2"))
            y += int(sum(fg.getmetrics()) * 1.2)
    d.rectangle([0, int(16 * u), max(3, int(5 * u)), h - int(16 * u)], fill=TH.rgba(T, "accent"))
    return im


def label_chip(text, scale=1.0):
    from . import overlays as O
    return O.lower_third(text, None, scale=scale * 0.8)


# --------------------------------------------------------------------------- geometry
def _fit(sw, sh, bw, bh):
    s = min(bw / sw, bh / sh)
    w, h = int(sw * s) // 2 * 2, int(sh * s) // 2 * 2
    return w, h


def geometry(canvas, layout, src_wh, cam_wh=None, header=True):
    """-> {canvas, main: (x, y, w, h), camera: box | None, camera_crop: (w, h) aspect to crop, header: box,
    terms: (x, y, w), labels: (x, y)}. Boxes in canvas px."""
    W, H = canvas
    vertical = H > W
    sw, sh = src_wh
    if layout == "camera" and cam_wh:
        sw, sh = cam_wh
    g = dict(canvas=(W, H), vertical=vertical, camera=None, camera_crop=None, layout=layout)
    if vertical:
        hy0, hy1 = int(H * 0.08), int(H * 0.305)
        g["header"] = (0, hy0, W, hy1 - hy0) if header else None
        top = hy1 + int(H * 0.012) if header else int(H * 0.2)
        if layout == "band" and cam_wh:
            mw, mh = _fit(sw, sh, W, int(H * 0.33))
            g["main"] = ((W - mw) // 2, top, mw, mh)
            cy = top + mh + int(H * 0.008)
            ch = min(int(H * 0.30), H - cy - int(H * 0.04)) // 2 * 2
            g["camera"] = (0, cy, W, ch)
            g["camera_crop"] = (W, ch)
            g["terms"] = (int(W * 0.06), cy + int(ch * 0.08), int(W * 0.56))
        else:
            mw, mh = _fit(sw, sh, W, int(H * 0.52))
            g["main"] = ((W - mw) // 2, top, mw, mh)
            if layout == "pip" and cam_wh:
                cw = int(W * 0.34) // 2 * 2
                chh = int(cw * 1.0) // 2 * 2
                g["camera"] = (W - cw - int(W * 0.04), top + mh - int(chh * 0.55), cw, chh)
                g["camera_crop"] = (cw, chh)
            g["terms"] = (int(W * 0.06), top + mh + int(H * 0.02), int(W * 0.62))
        g["labels"] = (int(W * 0.06), top + int(H * 0.012))
    else:
        g["header"] = (int(W * 0.025), int(H * 0.04), int(W * 0.42), int(H * 0.15)) if header else None
        if layout == "band" and cam_wh:
            cw = int(W * 0.25) // 2 * 2
            mw, mh = _fit(sw, sh, W - cw, H)
            g["main"] = (0, (H - mh) // 2, mw, mh)
            g["camera"] = (W - cw, 0, cw, H)
            g["camera_crop"] = (cw, H)
        else:
            mw, mh = _fit(sw, sh, W, H)
            g["main"] = ((W - mw) // 2, (H - mh) // 2, mw, mh)
            if layout == "pip" and cam_wh:
                cw = int(W * 0.22) // 2 * 2
                chh = int(cw * 9 / 16) // 2 * 2
                g["camera"] = (W - cw - int(W * 0.025), H - chh - int(H * 0.05), cw, chh)
                g["camera_crop"] = (cw, chh)
        g["terms"] = (int(W * 0.66), int(H * 0.06), int(W * 0.3))
        g["labels"] = (int(W * 0.03), int(H * 0.76))
    return g


# --------------------------------------------------------------------------- parts
def _enc(crf=16, preset="fast"):
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def card_part(png, dur, out):
    media.run(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", png, "-f", "lavfi", "-t", f"{dur:.3f}",
               "-i", "anullsrc=r=48000:cl=stereo", "-vf", f"fps={FPS},format=yuv420p", "-shortest", *_enc(), out])
    return out


def _crop_fill(w, h):
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def compose_part(src, a, b, out, geo, camera=None, offset=0.0, speed=1.0, header_png=None, audio="source"):
    """One src part on the canvas: paper ground, the main picture (and camera) placed per ``geo``, the header,
    speed-up with pitch kept. Audio from the main source (or ``audio="camera"``); silence if it has none."""
    W, H = geo["canvas"]
    dur = max(0.05, float(b) - float(a))
    out_dur = dur / speed
    main_is_cam = geo["layout"] == "camera" and camera
    main_src, main_off = (camera, offset) if main_is_cam else (src, 0.0)
    ins = ["-f", "lavfi", "-i", f"color=c={_hex('paper')}:s={W}x{H}:r={FPS}:d={out_dur:.3f}"]
    ins += ["-ss", f"{max(0.0, a + main_off):.3f}", "-t", f"{dur:.3f}", "-i", main_src]
    idx_cam = idx_hdr = None
    n = 2
    if camera and geo.get("camera") and not main_is_cam:
        ins += ["-ss", f"{max(0.0, a + offset):.3f}", "-t", f"{dur:.3f}", "-i", camera]
        idx_cam = n
        n += 1
    if header_png:
        ins += ["-i", header_png]
        idx_hdr = n
        n += 1
    sp = f"setpts=(PTS-STARTPTS)/{speed:.4f}"
    x, y, w, h = geo["main"]
    g = [f"[1:v]{sp},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:"
         f"color={_hex('paper')},setsar=1[m]", f"[0:v][m]overlay={x}:{y}:shortest=1[b0]"]
    last = "b0"
    if idx_cam is not None:
        cx, cy, cw, ch = geo["camera"]
        g.append(f"[{idx_cam}:v]{sp},{_crop_fill(cw, ch)},setsar=1[c]")
        g.append(f"[{last}][c]overlay={cx}:{cy}:shortest=1[b1]")
        last = "b1"
    if idx_hdr is not None:
        hx, hy = geo["header"][0], geo["header"][1]
        g.append(f"[{last}][{idx_hdr}:v]overlay={hx}:{hy}[b2]")
        last = "b2"
    g.append(f"[{last}]format=yuv420p[v]")
    a_idx = idx_cam if (audio == "camera" and idx_cam is not None) else 1
    a_src = camera if (audio == "camera" and idx_cam is not None) else main_src
    has_a = media.probe(a_src)["has_audio"]
    if has_a:
        g.append(f"[{a_idx}:a]asetpts=PTS-STARTPTS,{media.atempo_chain(speed) + ',' if speed != 1 else ''}"
                 f"aresample=48000,aformat=channel_layouts=stereo[a]")
        amap = ["-map", "[a]"]
    else:
        ins += ["-f", "lavfi", "-t", f"{out_dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = ["-map", f"{n}:a"]
    media.run(["ffmpeg", "-y", *ins, *media.filter_complex_args(";".join(g)), "-map", "[v]", *amap,
               "-t", f"{out_dur:.3f}", *_enc(), out])
    return out


# --------------------------------------------------------------------------- masks
def _mask_boxes(spec, geo):
    """-> [(box, required)]: the boxes whose face is hidden. ``required`` = a person is expected there (the camera,
    a single-file picture, a region she named): a face found on under half of the frames is a red item. A screen
    share next to a camera is masked too (faces in a shared video) but may have none."""
    m = spec.get("mask") or {}
    tgt = m.get("target") or "all"
    main_is_person = not spec.get("camera") or geo.get("layout") == "camera"
    if tgt == "camera" and geo.get("camera"):
        return [(geo["camera"], True)]
    if tgt == "regions" and m.get("regions"):
        x0, y0, w, h = geo["main"]
        sw, sh = spec.get("_src_wh") or (w, h)
        sx, sy = w / sw, h / sh
        return [((int(x0 + rx * sx), int(y0 + ry * sy), int(rw * sx), int(rh * sy)), True)
                for rx, ry, rw, rh in m["regions"]]
    boxes = [(geo["main"], main_is_person or tgt in ("screen", "camera"))]
    if tgt == "all" and geo.get("camera"):
        boxes.append((geo["camera"], True))
    return boxes


def mask_part(video, out, boxes, mode="sticker", sticker=None, scale=2.4, blur_grow=1.7):
    """Hide the face tracked inside each box (canvas px) on every frame: a sticker (call-clips' cat) or a strong
    blur. -> {hit_rates: [...], masked: bool}. A box with no face anywhere is left as is (reported 0.0)."""
    import subprocess
    import cv2
    import numpy as np
    from PIL import Image
    from . import draw as D
    from . import face as F
    tracks, rates = [], []
    boxes = [b if isinstance(b[0], (list, tuple)) else (b, True) for b in boxes]
    required = [r for _, r in boxes]
    for bx, _req in boxes:
        try:
            tr = F.track_faces(video, region=list(bx))
            tracks.append(tr)
            rates.append(tr["hit_rate"])
        except RuntimeError:
            rates.append(0.0)
    if not tracks:
        shutil.copy(video, out)
        return dict(hit_rates=rates, required=required, masked=False)
    st = np.array(Image.open(sticker or STICKER).convert("RGBA")) if mode == "sticker" else None
    cap = cv2.VideoCapture(video)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    tmp = out + ".v.mp4"
    cmd = [media._resolve(["ffmpeg"])[0], "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", f"{fps:.6f}", "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", tmp]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache = {}
    i = 0
    try:
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            for tr in tracks:
                j = min(i, len(tr["cx"]) - 1)
                cx, cy, fw, fh = tr["cx"][j], tr["cy"][j], tr["w"][j], tr["h"][j]
                if st is not None:
                    tw = max(24, int(round(fw * scale)))
                    if tw not in cache:
                        cache[tw] = np.array(Image.fromarray(st).resize((tw, int(round(tw * st.shape[0] / st.shape[1]))),
                                                                        Image.LANCZOS))
                    D.alpha_paste(fr, cache[tw], (cx, cy - 0.031 * cache[tw].shape[0]), center=True, bgr=True)
                else:
                    bw, bh = fw * blur_grow, fh * blur_grow * 1.15
                    D._redact_frame(fr, [(cx - bw / 2, cy - bh / 2, bw, bh)], "blur", factor=24)
            proc.stdin.write(fr.tobytes())
            i += 1
    finally:
        cap.release()
        proc.stdin.close()
        proc.wait()
    media.run(["ffmpeg", "-y", "-i", tmp, "-i", video, "-map", "0:v", "-map", "1:a?", "-c", "copy", out])
    os.remove(tmp)
    return dict(hit_rates=rates, required=required, masked=True)


# --------------------------------------------------------------------------- clip
def _words_in(words, a, b):
    return [w for w in words if a <= (w["t"] + w["te"]) / 2 <= b]


def render_clip(spec, words=None, canvas=(1080, 1920), workdir="work", keep=False):
    """One clip master on ``canvas`` -> {master, cues [Cue], keepouts [...], timeline [...], duration, size,
    mask_report, cover}. ``words``: ``cleanup.load_words`` of the source transcript (source seconds)."""
    from PIL import Image
    from . import subs as S
    os.makedirs(workdir, exist_ok=True)
    W, H = canvas
    src = spec["source"]
    info = media.probe(src)
    src_wh = (info["display_w"], info["display_h"])
    cam = spec.get("camera")
    cam_wh = None
    if cam:
        ci = media.probe(cam)
        cam_wh = (ci["display_w"], ci["display_h"])
    layout = spec.get("layout") or ("pip" if cam else "screen")
    if layout not in LAYOUTS:
        raise ValueError(f"layout {layout!r}: {' | '.join(LAYOUTS)}")
    hdr = spec.get("header")
    geo = geometry(canvas, layout, src_wh, cam_wh if cam else None, header=bool(hdr))
    spec = dict(spec, _src_wh=src_wh)
    header_png = None
    if hdr and geo.get("header"):
        hx, hy, hw, hh = geo["header"]
        header_png = os.path.join(workdir, f"header_{W}x{H}.png")
        header_image(hdr.get("kicker"), hdr.get("title"), hdr.get("sub"), hw, hh, geo["vertical"]).save(header_png)
        if not geo["vertical"]:
            hh = Image.open(header_png).size[1]
            geo["header"] = (hx, hy, hw, hh)
    speed = float(spec.get("speed") or 1.0)
    mask = spec.get("mask") or {}
    parts, timeline, t, cover = [], [], 0.0, None
    mrep = []
    for k, p in enumerate(spec["parts"]):
        out = os.path.join(workdir, f"part{k:02d}_{W}x{H}.mp4")
        if p["kind"] == "card":
            png = os.path.join(workdir, f"card{k:02d}_{W}x{H}.png")
            card_image(p.get("kicker"), p.get("title"), p.get("sub"), canvas, p.get("footer")).convert("RGB").save(png)
            cover = cover or png
            d = float(p.get("dur") or CARD_S)
            card_part(png, d, out)
            timeline.append(dict(kind="card", t0=round(t, 3), t1=round(t + d, 3), title=p.get("title")))
            t += d
        else:
            a, b = float(p["a"]), float(p["b"])
            sp = float(p.get("speed") or speed)
            compose_part(src, a, b, out, geo, cam, float(spec.get("offset") or 0.0), sp, header_png,
                         spec.get("audio") or "source")
            if mask.get("mode") in ("sticker", "blur"):
                mo = out.replace(".mp4", ".masked.mp4")
                r = mask_part(out, mo, _mask_boxes(spec, geo), mask["mode"], mask.get("sticker"))
                mrep.append(dict(part=k, **r))
                os.replace(mo, out)
            d = media.probe(out)["duration"]
            timeline.append(dict(kind="src", t0=round(t, 3), t1=round(t + d, 3), a=a, b=b, speed=sp))
            t += d
        parts.append(out)
    # overlays (final time): term cards, speaker labels
    ovs, keepouts = [], []
    if geo.get("header") and hdr:
        for seg in timeline:
            if seg["kind"] == "src":
                keepouts.append(dict(t0=seg["t0"], t1=seg["t1"], box=list(geo["header"]), kind="header"))

    def to_final(ts):
        for seg in timeline:
            if seg["kind"] == "src" and seg["a"] - 0.01 <= ts <= seg["b"] + 0.01:
                return seg["t0"] + (ts - seg["a"]) / seg["speed"]
        return None
    tx, ty, tw = geo["terms"]
    for i, tm in enumerate(spec.get("terms") or []):
        t0 = to_final(float(tm["t"]))
        if t0 is None:
            continue
        t1 = min(t0 + float(tm.get("dur") or 4.5), t)
        png = os.path.join(workdir, f"term{i:02d}_{W}x{H}.png")
        im = term_card(tm["term"], tm.get("gloss"), tw, tm.get("label"), scale=min(W, H) / 1080)
        im.save(png)
        ovs.append((png, tx, ty, t0, t1))
        keepouts.append(dict(t0=round(t0, 3), t1=round(t1, 3), box=[tx, ty, im.size[0], im.size[1]], kind="term"))
    lx, ly = geo["labels"]
    for i, lb in enumerate(spec.get("labels") or []):
        t0, t1 = to_final(float(lb["a"])), to_final(float(lb["b"]))
        if t0 is None:
            continue
        t1 = t1 if t1 is not None else t0 + 3.0
        png = os.path.join(workdir, f"label{i:02d}_{W}x{H}.png")
        im = label_chip(lb["text"], scale=min(W, H) / 1080)
        im.save(png)
        ovs.append((png, lx, ly, t0, min(t1, t0 + 3.5)))
        keepouts.append(dict(t0=round(t0, 3), t1=round(min(t1, t0 + 3.5), 3), box=[lx, ly, im.size[0], im.size[1]],
                             kind="label"))
    master = os.path.join(workdir, f"master_{W}x{H}.mp4")
    ins = []
    for p in parts:
        ins += ["-i", p]
    for png, *_ in ovs:
        ins += ["-i", png]
    n = len(parts)
    g = ["".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v0][a]"]
    last = "v0"
    for j, (png, x, y, t0, t1) in enumerate(ovs):
        g.append(f"[{last}][{n + j}:v]overlay={int(x)}:{int(y)}:enable='between(t,{t0:.3f},{t1:.3f})'[v{j + 1}]")
        last = f"v{j + 1}"
    media.run(["ffmpeg", "-y", *ins, *media.filter_complex_args(";".join(g), workdir), "-map", f"[{last}]",
               "-map", "[a]", *media.delivery_args(crf=14, preset="medium"), master])
    # captions in final time
    cues = []
    if words:
        for seg in timeline:
            if seg["kind"] != "src":
                continue
            ws = [dict(w=w["w"], t=seg["t0"] + max(0.0, w["t"] - seg["a"]) / seg["speed"],
                       te=seg["t0"] + max(0.0, min(w["te"], seg["b"]) - seg["a"]) / seg["speed"])
                  for w in _words_in(words, seg["a"], seg["b"])]
            part = S.cues_from_words(ws) if ws else []
            for c in part:
                c.end = min(c.end, seg["t1"])
            cues += part
    if not keep:
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass
    return dict(master=master, cues=cues, keepouts=keepouts, timeline=timeline, duration=round(t, 3),
                size=[W, H], mask_report=mrep, cover=cover, geometry={k: v for k, v in geo.items()})


# --------------------------------------------------------------------------- delivery
def canvases(platforms):
    """Targets -> {(W, H): [target keys]} (one master per distinct canvas)."""
    from . import platform as P
    out = {}
    for prof in P.parse_targets(list(platforms)):
        out.setdefault((prof.w, prof.h), []).append(prof.key)
    return out


def _cover_block(spec):
    card = next((p for p in spec["parts"] if p["kind"] == "card"), None) or spec.get("header") or \
        dict(title=spec.get("title"))
    return card.get("kicker"), card.get("title"), card.get("sub")


def _covers(spec, keys, canvas, res, workdir):
    """[generic cover at the canvas, "<target>=<cover>" for targets whose cover shape differs (小红书 3:4)]: the
    title card itself, so the cover is designed type on the theme paper, never a random frame."""
    from . import platform as P
    k, t, sub = _cover_block(spec)
    os.makedirs(workdir, exist_ok=True)
    base = res.get("cover")
    if not base:
        base = os.path.join(workdir, "cover.png")
        card_image(k, t, sub, canvas).convert("RGB").save(base)
    out = [base]
    for key in keys:
        n, _, o = key.partition(":")
        cw, ch = P.cover_size(P.profile(n, o or None))
        if abs(cw / ch - canvas[0] / canvas[1]) > 0.02:
            pth = os.path.join(workdir, f"cover_{cw}x{ch}.png")
            if not os.path.exists(pth):
                card_image(k, t, sub, (cw, ch)).convert("RGB").save(pth)
            out.append(f"{key}={pth}")
    return out


def _prefix_exports(man, out_dir, cid):
    """``<platform>-<orientation>.*`` -> ``<id>-<platform>-<orientation>.*`` (several clips of one lesson land in
    one export folder without overwriting each other); manifest.json rewritten to match."""
    for e in man["exports"]:
        stem = os.path.splitext(e["file"])[0]
        for f in sorted(os.listdir(out_dir)):
            if f.startswith(stem + ".") and not f.startswith(cid + "-"):
                os.replace(os.path.join(out_dir, f), os.path.join(out_dir, f"{cid}-{f}"))
        for k in ("file", "cover", "post"):
            if e.get(k) and not e[k].startswith(cid + "-"):
                e[k] = f"{cid}-{e[k]}"
        if (e.get("reframe") or {}).get("plan"):
            e["reframe"]["plan"] = f"{cid}-{e['reframe']['plan']}"
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    return man


def _cue_dicts(cues):
    return [c.to_dict() for c in cues]


def deliver(spec, words, platforms, out_dir, captions=None, fmt=None, post=None, workdir=None, firstpass=True,
            translate=None):
    """Render + export one clip to every platform. captions = {mode mono|bilingual|translated, src, tgt,
    highlight [phrases], glossary {..}, cache path, off: bool}. translate: fn(cues, src, tgt) -> (cues, info)
    (tests; default ``bilingual.translate_cues``). Writes ``out_dir/<platform>-<orientation>.mp4`` (+ cover,
    post), ``<id>.<lang>.srt/.vtt``, ``cues.<W>x<H>.json``, ``report.json``. Returns the report."""
    from . import bilingual as BL
    from . import export as EX
    captions = dict(captions or {})
    os.makedirs(out_dir, exist_ok=True)
    workdir = workdir or os.path.join(out_dir, "work")
    report = dict(id=spec["id"], exports=[], warnings=[], tracks={}, firstpass=[], masters=[],
                  layout=spec.get("layout"), layout_why=spec.get("layout_why"))
    tr_info = None
    for (W, H), keys in canvases(platforms).items():
        res = render_clip(spec, words, (W, H), os.path.join(workdir, f"{W}x{H}"))
        cues = res["cues"]
        if captions.get("mode") in ("bilingual", "translated") and cues:
            fn = translate or (lambda cs, s, t: BL.translate_cues(cs, s, t, captions.get("glossary"),
                                                                 cache=captions.get("cache")))
            cues, tr_info = fn(cues, captions.get("src") or "en", captions.get("tgt") or "zh")
            if tr_info and tr_info.get("error"):
                raise TranslationError(f"{captions.get('mode')} captions need a translation and it failed: "
                                       f"{tr_info['error']} (route llm.tasks.translate, or subtitles: mono)")
            if tr_info and tr_info.get("missing"):
                report["warnings"].append(f"{tr_info['missing']} caption lines came back untranslated")
            for g in (tr_info or {}).get("glossary_misses") or []:
                report["warnings"].append(f"glossary: '{g['term']}' should read '{g['want']}' in: {g['line'][:60]}")
        if not report["tracks"] and cues:
            report["tracks"] = BL.write_tracks(cues, os.path.join(out_dir, spec["id"]), captions.get("src") or "en",
                                               captions.get("tgt") if captions.get("mode") != "mono" else None)
        shown = BL.apply_mode(cues, captions.get("mode") or "mono") if cues else []
        shown = BL.highlight(shown, captions.get("highlight") or spec.get("highlight"))
        cj = os.path.join(out_dir, f"cues.{W}x{H}.json")
        with open(cj, "w", encoding="utf-8") as f:
            json.dump(dict(cues=_cue_dicts(shown), keepouts=res["keepouts"], size=[W, H], timeline=res["timeline"]),
                      f, ensure_ascii=False, indent=1)
        covers = _covers(spec, keys, (W, H), res, os.path.join(workdir, f"{W}x{H}"))
        man = EX.export(res["master"], keys, out_dir, cues=None if captions.get("off") else cj, covers=covers,
                        post=post)
        report["masters"].append(dict(size=[W, H], master=res["master"], duration=res["duration"],
                                      mask_report=res["mask_report"], cues=cj))
        man = _prefix_exports(man, out_dir, spec["id"])
        for e in man["exports"]:
            e = dict(e, file=os.path.join(out_dir, e["file"]),
                     cover=os.path.join(out_dir, e["cover"]) if e.get("cover") else None,
                     post=os.path.join(out_dir, e["post"]) if e.get("post") else None)
            report["exports"].append(e)
            report["warnings"] += [f"{e['platform']}: {w}" for w in e.get("warnings") or []]
            if firstpass:
                from . import firstpass as FP
                fp = FP.run(e["file"], fmt=fmt, platform=f"{e['platform']}:{e['orientation']}", cues=cj,
                            cover=covers[0] if covers else e.get("cover"), post=e.get("post"), speed=1.0)
                report["firstpass"].append(dict(file=e["file"], ok=fp["ok"],
                                                red=[i["id"] for i in fp["items"] if i["ok"] is False and
                                                     i["severity"] == "red"],
                                                warn=[i["id"] for i in fp["items"] if i["ok"] is False and
                                                      i["severity"] == "warn"]))
        for m in res["mask_report"]:
            low = [r for r, req in zip(m["hit_rates"], m.get("required") or [True] * len(m["hit_rates"]))
                   if req and r < 0.5]
            if low:
                report.setdefault("red", []).append(
                    f"face mask: a face was found on only {min(low):.0%} of the frames of part {m['part']}"
                    f" ({W}x{H}) - the mask may miss it; look at every frame or use mask regions")
    if tr_info:
        report["translation"] = {k: v for k, v in tr_info.items() if k != "calls"}
    report["ok"] = (all(f["ok"] for f in report["firstpass"]) if report["firstpass"] else None) and \
        not report.get("red")
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report


# --------------------------------------------------------------------------- layout choice
def blank_share(src, a, b, n=5, luma=0.04, tmpdir=None):
    """True when the main recording shows (almost) nothing in [a, b]: a screen share that was not sharing yet is
    a black frame in meeting exports. Samples ``n`` frames; mean luma under ``luma`` on all of them = blank."""
    import tempfile
    from PIL import Image, ImageStat
    td = tmpdir or tempfile.mkdtemp(prefix="vblank-")
    try:
        for k in range(n):
            t = a + (b - a) * (k + 0.5) / n
            png = os.path.join(td, f"f{k}.png")
            media.grab_frame(src, t, png, vf="scale=320:-2")
            with Image.open(png) as im:
                if ImageStat.Stat(im.convert("L")).mean[0] / 255.0 >= luma:
                    return False
        return True
    finally:
        if tmpdir is None:
            shutil.rmtree(td, ignore_errors=True)


def auto_layouts(specs, default="pip"):
    """layout None + a camera file: ``camera`` for a clip whose screen share is blank, else ``default``; the
    choice is written into the spec (``layout_why``) and so into the report."""
    for sp in specs:
        if sp.get("camera") and not sp.get("layout"):
            srcs = [(p["a"], p["b"]) for p in sp["parts"] if p["kind"] == "src"]
            blank = all(blank_share(sp["source"], a, b) for a, b in srcs) if srcs else False
            sp["layout"] = "camera" if blank else default
            sp["layout_why"] = "the screen share is blank here" if blank else "screen share + camera inset"
    return specs


# --------------------------------------------------------------------------- batch of clips (lesson / Q&A CLIs)
def translate_lines(texts, src, tgt, cache=None, glossary=None, call=None):
    """Card / header texts in the other language (titles, questions) through ``bilingual.translate_texts``;
    missing -> "" (the card then shows no subline)."""
    from . import bilingual as BL
    texts = [t or "" for t in texts]
    if not any(texts):
        return texts
    out, info = BL.translate_texts(texts, src, tgt, glossary, cache=cache, call=call)
    if info.get("error"):
        raise TranslationError(f"card titles could not be translated: {info['error']} "
                               f"(route llm.tasks.translate, or subtitles: mono)")
    return out


def render_all(specs, words, platforms, out_dir, captions=None, fmt=None, only=None, post_of=None, translate=None):
    """deliver() every spec (``only``: a list of ids) into ``out_dir/<id>/``; writes ``out_dir/report.json``
    {clips: [...], ok}. post_of(spec) -> post dict (title, body, tags)."""
    clips = []
    for sp in specs:
        if only and sp["id"] not in only:
            continue
        rep = deliver(sp, words, platforms, os.path.join(out_dir, sp["id"]), captions, fmt,
                      post=post_of(sp) if post_of else None, translate=translate)
        clips.append(rep)
        print(f"[clipkit] {sp['id']}: {len(rep['exports'])} exports, firstpass "
              f"{'ok' if rep.get('ok') else 'see report'}", flush=True)
    res = dict(clips=[dict(id=c["id"], ok=c.get("ok"), exports=[e["file"] for e in c["exports"]],
                           tracks=c.get("tracks"), warnings=c.get("warnings"), red=c.get("red") or []) for c in clips],
               ok=all(c.get("ok") is not False for c in clips))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


def caption_config(mode, src_lang, tgt_lang=None, cache=None, highlight=None, glossary=None):
    from . import bilingual as BL
    mode = mode or "mono"
    if mode not in BL.MODES:
        raise ValueError(f"subtitles {mode!r}: {' | '.join(BL.MODES)}")
    return dict(mode=mode, src=src_lang, tgt=tgt_lang or BL.other_lang(src_lang), cache=cache,
                highlight=list(highlight or []), glossary=glossary)
