"""Multi-platform export: one clean master -> a file + cover + post stub per platform, plus a manifest.

    python -m vstudio.export master.mp4 --platforms xiaohongshu:vertical,douyin,youtube --out exports/ \\
        [--cues cues.json | --cues subs.srt] [--no-captions] [--cover cover.png | --cover douyin=c916.png ...]
        [--title "..."] [--post post.json]

Per target (vstudio.platform profile):
  1. reframe the master to the profile canvas (vstudio.reframe): same aspect -> plain scale (no face
     tracking; reported as ``scale``); otherwise ``--mode`` (default face, keeping the face in the
     profile's safe box; no face -> pad-blur);
  2. burn captions (if cues are given and not --no-captions) in the profile's caption box at a fitted
     size (PIL, no libass), keyword markup 【】 / ``hl`` spans in brand.highlight. ``keepouts`` in
     cues.json ([{t0, t1, box: [x, y, w, h]}] in master px - or 0..1 fractions - and final seconds:
     panels, stamps, titles already burned into the master) are mapped through the reframe and the
     caption moves above/below them while they are on screen;
  3. two-pass loudnorm to the profile's LUFS / true-peak target (audio.loudnorm_2pass);
  4. H.264 delivery encode (media.delivery_args with the profile's encode guidance);
  5. cover: a per-target ``--cover platform[:orientation]=path`` wins; else the --cover whose aspect is
     closest - cover-cropped when the aspect matches, otherwise FITTED on a blurred pad of itself (a
     centre crop would cut the headline off) with a warning to supply a per-target cover; else a frame
     of the export. Covers shown as a centre crop in the feed also get a ``.feed.jpg`` preview;
  6. post stub via publish.post_body when --title / --post is given;
and ``manifest.json`` with files, durations, measured loudness, reframe stats and warnings.

Masters should be caption-free: keep a clean master + cues (JSON from subs.Cue.to_dict, or SRT) so each
platform gets captions sized and placed for its own UI. A master with burned-in captions will have them
cropped or covered on other canvases.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

import numpy as np

from . import media
from . import platform as P
from . import reframe as R


# ----------------------------------------------------------------------------------- cues
def _hl_markup(text, hl):
    """Apply ``hl`` (keywords ["AWS", ...] or [[i, j], ...] char spans of the plain text) as highlight
    markup, unless the text already carries markup."""
    from . import draw
    a, z = draw.markup()
    if not hl or a in text:
        return text
    mark = [False] * len(text)
    for h in hl:
        if isinstance(h, str):
            k = text.find(h)
            while h and k >= 0:
                for j in range(k, k + len(h)):
                    mark[j] = True
                k = text.find(h, k + len(h))
        elif isinstance(h, (list, tuple)) and len(h) == 2:
            for j in range(max(0, int(h[0])), min(len(text), int(h[1]))):
                mark[j] = True
    out, on = [], False
    for ch, m in zip(text, mark):
        if m != on:
            out.append(a if m else z)
            on = m
        out.append(ch)
    if on:
        out.append(z)
    return "".join(out)


def _cue_from_dict(d):
    from .subs import Cue
    c = Cue.from_dict(d)
    hl = d.get("hl") or (d.get("style") or {}).get("hl") or (d.get("meta") or {}).get("hl")
    if hl:
        c.text = _hl_markup(c.text, hl)
    st = d.get("style")
    if isinstance(st, dict):
        c.meta = dict(c.meta or {}, style={k: v for k, v in st.items() if k != "hl"})
    return c


def load_cues(path):
    """Cues from a list, .srt, or cues.json (a list of Cue dicts, or {cues: [...], keepouts: [...]}).
    Per-cue ``hl`` (keywords or [i, j] spans) becomes 【】 markup; ``style`` ({fill, highlight}
    colours) is kept in ``meta["style"]``."""
    from .subs import Cue, srt_read
    if path is None:
        return []
    if isinstance(path, (list, tuple)):
        return [c if isinstance(c, Cue) else _cue_from_dict(c) for c in path]
    if str(path).lower().endswith(".srt"):
        return srt_read(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("cues") or data.get("segments") or []
    return [_cue_from_dict(d) for d in data]


def load_keepouts(path, master_size=None):
    """``keepouts`` of a cues.json -> [{t0, t1, box: (x, y, w, h) in master px}]. A box whose values are
    all <= 1 is a fraction of the frame; a top-level ``size`` [W, H] different from ``master_size``
    rescales. Missing / SRT / list cues -> []."""
    if path is None or isinstance(path, (list, tuple)) or str(path).lower().endswith(".srt"):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return []
    W, H = master_size or data.get("size") or (1, 1)
    sx = sy = 1.0
    if data.get("size") and master_size:
        sx, sy = master_size[0] / float(data["size"][0]), master_size[1] / float(data["size"][1])
    out = []
    for k in data.get("keepouts") or []:
        x, y, w, h = (float(v) for v in k["box"])
        if max(x, y, w, h) <= 1.0:
            x, y, w, h = x * W, y * H, w * W, h * H
        else:
            x, y, w, h = x * sx, y * sy, w * sx, h * sy
        out.append(dict(t0=float(k.get("t0", 0.0)), t1=float(k.get("t1", 1e9)), box=(x, y, w, h),
                        kind=k.get("kind", "")))
    return out


def map_box(pl, box, i=0):
    """Master-px box (x, y, w, h) -> target-px (x0, y0, x1, y1) through a reframe plan at frame ``i``."""
    x, y, w, h = box
    tw, th = pl["target"]
    sw, sh = pl["src_w"], pl["src_h"]
    if pl["mode_used"] in ("pad-blur", "letterbox"):
        s = min(tw / sw, th / sh)
        ox, oy = (tw - sw * s) / 2, (th - sh * s) / 2
        return (ox + x * s, oy + y * s, ox + (x + w) * s, oy + (y + h) * s)
    rects = pl.get("rects")
    cx, cy, cw, ch = pl.get("fixed") if rects is None else rects[min(i, len(rects) - 1)]
    s = tw / cw
    return ((x - cx) * s, (y - cy) * s, (x + w - cx) * s, (y + h - cy) * s)


def _rebalance(lines, mk):
    """Close/reopen highlight markup across wrapped lines so each line renders its own spans."""
    a, z = mk[0], mk[-1]
    out, open_ = [], False
    for ln in lines:
        s = (a if open_ else "") + ln
        depth = 0
        for ch in s:
            if ch == a:
                depth = 1
            elif ch == z:
                depth = 0
        open_ = depth == 1
        out.append(s + (z if open_ else ""))
    return out


def caption_overlay(prof, cues, fps, role="cjk-bold", fill=(255, 255, 255, 255), keepouts=None, plan=None,
                    report=None):
    """overlay(i, t, img_bgr) for reframe.render: draws the active cue centred in caption_box.
    keepouts ([{t0, t1, box}] master px, see load_keepouts) + plan: while a keep-out is on screen and
    overlaps the caption, the caption moves to the nearest free spot above/below it inside the
    profile's safe box. ``report`` (dict) collects {"moved": n, "blocked": n} frame counts."""
    from . import draw
    x0, y0, x1, y1 = P.caption_box(prof)
    sx0, sy0, sx1, sy1 = P.safe_box(prof)
    cache = {}
    kos = list(keepouts or []) if plan is not None else []
    rep_ = report if report is not None else {}
    rep_.setdefault("moved", 0); rep_.setdefault("blocked", 0)
    mk = draw.markup()

    def layer(k, c):
        if k not in cache:
            fit = P.fit_text_size(prof, c.text.replace("\n", " "), role)
            f = draw.load_font(role, fit["size"])
            stroke = max(2, int(fit["size"] * float(prof.caption.get("stroke", 0.08))))
            st = (c.meta or {}).get("style") or {}
            fl = draw.rgba(st["fill"]) if st.get("fill") else fill
            hl = draw.rgba(st["highlight"]) if st.get("highlight") else None
            prim = _lines_layer(_rebalance(fit["lines"], mk), f, fl, stroke, hl)
            if c.alt and c.alt.strip():
                fa = draw.load_font("cjk", max(16, int(fit["size"] * 0.66)))
                alt_lines = draw.wrap(c.alt.strip(), fa, x1 - x0, balance=True, max_lines=2)
                sec = _lines_layer(alt_lines, fa, (226, 232, 240, 255), max(2, stroke * 2 // 3))
                w = max(prim.width, sec.width)
                from PIL import Image
                im = Image.new("RGBA", (w, prim.height + sec.height - 8), (0, 0, 0, 0))
                im.alpha_composite(prim, ((w - prim.width) // 2, 0))
                im.alpha_composite(sec, ((w - sec.width) // 2, prim.height - 8))
                prim = im
            cache[k] = np.asarray(prim)
        return cache[k]

    spans = sorted(((c.start, c.end, k, c) for k, c in enumerate(cues) if c.text.strip()), key=lambda s: s[0])

    def _place(i, t, w, h, cx, y):
        boxes = [map_box(plan, k["box"], i) for k in kos if k["t0"] <= t < k["t1"]]
        if not boxes:
            return y
        def hits(yy):
            return any(not (cx + w / 2 <= b[0] or cx - w / 2 >= b[2] or yy + h <= b[1] or yy >= b[3]) for b in boxes)
        if not hits(y):
            return y
        m = 12
        cands = [b[1] - h - m for b in boxes] + [b[3] + m for b in boxes]
        cands = [c for c in cands if sy0 <= c <= sy1 - h and not hits(c)]
        if not cands:
            rep_["blocked"] += 1
            return y
        rep_["moved"] += 1
        return min(cands, key=lambda c: abs(c - y))

    def overlay(i, t, img):
        for a, b, k, c in spans:
            if a <= t < b:
                L = layer(k, c)
                h, w = L.shape[:2]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                y = min(cy - h / 2, y1 - h) if h <= y1 - y0 else cy - h / 2   # over-tall: centred on the band
                if kos:
                    y = _place(i, t, w, h, cx, y)
                draw.alpha_paste(img, L, (cx - w / 2, y), bgr=True)
                break
        return img
    return overlay


def _lines_layer(lines, f, fill, stroke, hl_fill=None):
    """Centred stroked lines (markup 【】 highlighted in brand.highlight / ``hl_fill``) as one RGBA strip."""
    from PIL import Image
    from . import draw
    rows = [draw.text_layer(ln, f, fill=fill, hl_fill=hl_fill, stroke=stroke, stroke_fill=(0, 0, 0, 235),
                            shadow_alpha=110, pad=6)
            for ln in lines]
    if not rows:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    gap = -int(f.size * 0.12)
    w = max(r.width for r in rows)
    h = sum(r.height for r in rows) + gap * (len(rows) - 1)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for r in rows:
        im.alpha_composite(r, ((w - r.width) // 2, y))
        y += r.height + gap
    return im


# ----------------------------------------------------------------------------------- covers
def _aspect(wh):
    return wh[0] / wh[1]


def fit_cover(src_img, size, focus=None):
    """Cover-crop a PIL image to ``size`` (w, h) around ``focus`` (fx, fy in 0..1, default centre)."""
    from PIL import Image
    W, H = size
    im = src_img.convert("RGB")
    s = max(W / im.width, H / im.height)
    rw, rh = max(W, int(round(im.width * s))), max(H, int(round(im.height * s)))
    im = im.resize((rw, rh), Image.LANCZOS)
    fx, fy = focus or (0.5, 0.5)
    x = int(min(max(fx * rw - W / 2, 0), rw - W))
    y = int(min(max(fy * rh - H / 2, 0), rh - H))
    return im.crop((x, y, x + W, y + H))


def fit_cover_pad(src_img, size, dim=0.55):
    """Fit a PIL image INSIDE ``size`` (nothing cropped) over a blurred, dimmed cover-crop of itself -
    for a cover whose aspect differs from the target (keeps a headline that a crop would cut)."""
    from PIL import Image, ImageEnhance, ImageFilter
    W, H = size
    im = src_img.convert("RGB")
    bg = fit_cover(im, size).filter(ImageFilter.GaussianBlur(max(8, W // 30)))
    bg = ImageEnhance.Brightness(bg).enhance(dim)
    s = min(W / im.width, H / im.height)
    fg = im.resize((max(1, int(round(im.width * s))), max(1, int(round(im.height * s)))), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def parse_covers(covers):
    """--cover values -> (generic [paths], {target: path}); "douyin=c.png" / "xiaohongshu:full=c.png"
    are per-target, anything else (an existing path) is generic."""
    generic, per = [], {}
    for c in covers or []:
        c = os.fspath(c)
        if "=" in c and not os.path.exists(c):
            k, _, v = c.partition("=")
            per[k.strip()] = v.strip()
        else:
            generic.append(c)
    return generic, per


def _cover_for(prof, per):
    for k, v in (per or {}).items():
        n, _, o = k.partition(":")
        try:
            if P.canonical(n) != prof.name:
                continue
            if o and P.profile(n, o).key != prof.key:
                continue
        except (KeyError, ValueError):
            continue
        return v
    return None


def _face_focus(im):
    try:
        import cv2
        from . import face
        lm = face.landmarker(1)
        try:
            bgr = cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)
            f = face.main_face(face.detect(lm, bgr))
        finally:
            lm.close()
        if f is None:
            return None
        p = f["pts"]
        return float(p[:, 0].mean() / im.width), float(p[:, 1].mean() / im.height)
    except Exception:
        return None


def make_cover(prof, covers, video, out_path, at=None, per_target=None, warnings=None):
    """Write the profile's cover to out_path: the per-target cover (``per_target`` {"douyin": path,
    "xiaohongshu:full": path}) if one matches, else the closest-aspect image in ``covers`` (paths), else a
    frame of ``video`` (at ``at`` s, default 1/3 in). A cover of the right aspect (<= 5 % off) is
    cover-cropped (face-aware); a different aspect is FITTED over a blurred pad (never centre-cropped:
    that cuts the headline) and a warning asks for a per-target cover. Returns (path, notes)."""
    from PIL import Image
    size = P.cover_size(prof)
    notes = []
    pad = False
    own = _cover_for(prof, per_target)
    if own or covers:
        imgs = [(own, Image.open(own))] if own else [(c, Image.open(c)) for c in covers]
        c, im = min(imgs, key=lambda ci: abs(np.log(_aspect(ci[1].size) / _aspect(size))))
        if abs(np.log(_aspect(im.size) / _aspect(size))) > 0.05:
            pad = True
            msg = (f"cover {os.path.basename(c)} {im.width}x{im.height} is not {prof.cover.get('aspect')}: fitted on a "
                   f"blurred pad to {size[0]}x{size[1]}; pass --cover {prof.name}=<{size[0]}x{size[1]} cover> for a real one")
            notes.append(msg)
            if warnings is not None:
                warnings.append(msg)
    else:
        tmp = out_path + ".frame.png"
        media.grab_frame(video, at if at is not None else media.duration(video) / 3, tmp)
        im = Image.open(tmp); im.load(); os.remove(tmp)
        notes.append("no --cover given: used a frame of the export")
    if pad:
        fit_cover_pad(im, size).save(out_path, quality=92)
    elif abs(np.log(_aspect(im.size) / _aspect(size))) < 0.01:
        fit_cover(im, size).save(out_path, quality=92)          # same aspect: a plain resize, no face pass
    else:
        fit_cover(im, size, _face_focus(im)).save(out_path, quality=92)
    mb = prof.cover.get("max_bytes")
    if mb and os.path.getsize(out_path) > mb:
        Image.open(out_path).save(out_path, quality=80)
    fc = prof.cover.get("feed_crop")
    if fc:
        aw, ah = (float(v) for v in fc.split(":"))
        W, H = size
        cw, ch = (H * aw / ah, H) if W / H > aw / ah else (W, W * ah / aw)
        x0, y0 = (W - cw) / 2, (H - ch) / 2
        prev = os.path.splitext(out_path)[0] + ".feed.jpg"
        Image.open(out_path).crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).save(prev, quality=90)
        notes.append(f"feed shows a centre {fc} crop: preview {os.path.basename(prev)}")
    extra = [a for a in P.cover_crops(prof) if a != fc]
    if extra:
        chk = cover_crop_check(out_path, prof, write_previews=True)
        notes.append("cover is also shown as centre " + ", ".join(extra) + " crops: previews "
                     + ", ".join(os.path.basename(c["preview"]) for c in chk["crops"] if c.get("preview"))
                     + f" and {os.path.basename(chk['sheet'])}")
        for c in chk["crops"]:
            if c["cut_detail"]:
                msg = (f"cover: detail (text/edges) in the strips the {c['aspect']} crop cuts off "
                       f"({c['cut_density']:.0%} busy tiles) - keep the headline inside {list(P.cover_title_safe(prof))}")
                notes.append(msg)
                if warnings is not None:
                    warnings.append(msg)
    return out_path, notes


def _busy_tiles(edges, tile=48, busy=0.04):
    """Share of tile x tile blocks with > ``busy`` edge pixels (text / faces / detail, not flat or gradient fill)."""
    h, w = edges.shape
    if h < 8 or w < 8:
        return 0.0
    n = hit = 0
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            b = edges[y:y + tile, x:x + tile]
            if b.size < tile * tile // 4:
                continue
            n += 1
            hit += b.mean() > busy
    return hit / n if n else 0.0


def cover_crop_check(path, prof, write_previews=False, threshold=0.15):
    """Check a cover against every centre crop a surface shows (``platform.cover_crops``: Instagram 4:5 feed /
    3:4 grid / 1:1, 视频号 6:7 share card, B站 4:3 / 16:9, ...). For each crop: the box, and (cut_density) the
    share of busy 48 px tiles (text, faces, detail - not flat fill) in the busiest strip the crop removes; over
    ``threshold`` = ``cut_detail`` (something worth seeing is cut). write_previews: ``<stem>.crop-4x5.jpg`` per crop + ``<stem>.crops.jpg``,
    the cover with every crop outlined. Returns {crops: [{aspect, box, cut_density, cut_detail, preview}], sheet}."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(path).convert("RGB")
    W, H = im.size
    edges = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES)) > 48
    stem = os.path.splitext(path)[0]
    out = []
    sheet = im.copy()
    dr = ImageDraw.Draw(sheet)
    colours = [(255, 214, 10), (45, 212, 191), (244, 114, 182), (96, 165, 250)]
    for k, a in enumerate(P.cover_crops(prof)):
        box = P.crop_box(W, H, a)
        x0, y0, x1, y1 = box
        strips = [edges[:y0], edges[y1:], edges[:, :x0], edges[:, x1:]]       # what the crop removes, per side
        dens = max([_busy_tiles(st) for st in strips if st.size] or [0.0])
        cut = any(st.size for st in strips)
        e = dict(aspect=a, box=list(box), cut_density=round(dens, 4), cut_detail=bool(cut and dens > threshold))
        if write_previews:
            pv = f"{stem}.crop-{a.replace(':', 'x')}.jpg"
            im.crop(box).save(pv, quality=90)
            e["preview"] = pv
        c = colours[k % len(colours)]
        dr.rectangle(box, outline=c, width=max(3, W // 200))
        dr.text((x0 + 12, y0 + 12 + 28 * k), a, fill=c)
        out.append(e)
    res = dict(crops=out, sheet=None)
    if write_previews and out:
        ts = P.cover_title_safe(prof)
        dr.rectangle(ts, outline=(255, 255, 255), width=2)
        res["sheet"] = f"{stem}.crops.jpg"
        sheet.save(res["sheet"], quality=88)
    return res


# ----------------------------------------------------------------------------------- export
def _publish_platform(prof):
    return "youtube" if prof.name == "youtube-shorts" else prof.name


def _scale_only(master, dst, prof, info, start, dur, vargs, fps_out):
    """Same-aspect fast path: one ffmpeg scale + encode (no Python frame pipe, no face tracking)."""
    win = (["-ss", f"{start:.3f}"] if start else []) + (["-t", f"{dur:.3f}"] if dur else [])
    vf = f"scale={prof.w}:{prof.h}:flags=lanczos,setsar=1"
    cmd = [media.ffmpeg_bin(), "-y", "-v", "error", *win, "-i", master, "-map", "0:v:0", "-vf", vf]
    if info["has_audio"]:
        cmd += ["-map", "0:a:0"]
    cmd += list(vargs) + (["-r", str(fps_out)] if fps_out else [])
    cmd += (["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"] if info["has_audio"] else ["-an", "-movflags", "+faststart"])
    media.run(cmd + [dst])
    return dst


def export_one(master, prof, out_dir, cues=None, covers=None, post=None, mode="face", fallback="pad-blur",
               start=0.0, dur=None, workdir=None, encoder=None, preset="medium", captions=True,
               cover_targets=None, post_lang=None, **reframe_opts):
    """Export ``master`` for one Profile. Returns the manifest entry (dict).
    captions=False: never burn ``cues`` (the master already has them). cover_targets: {target: path}
    per-target covers (see make_cover)."""
    from . import audio
    info = media.probe(master)
    stem = f"{prof.name}-{prof.orientation}"
    out_mp4 = os.path.join(out_dir, stem + ".mp4")
    warnings = []
    same_aspect = abs(np.log(_aspect((info["display_w"], info["display_h"])) / _aspect(prof.size))) < 0.01
    crop_b = float(reframe_opts.pop("crop_bottom", 0) or 0)
    crop_t = float(reframe_opts.pop("crop_top", 0) or 0)
    band = None
    if mode == "band":                              # old burned captions cropped off, the rest fitted in a band
        sw, sh = int(info["display_w"]), int(info["display_h"])
        y0 = int(round(sh * max(0.0, crop_t)))
        hh = max(2, int(round(sh * max(0.1, 1 - crop_t - crop_b))) // 2 * 2)
        band = dict(crop_top=crop_t, crop_bottom=crop_b, region=[0, y0, sw, min(hh, sh - y0)])
        m = "pad-blur"
        reframe_opts["region"] = band["region"]
    else:
        m = "letterbox" if same_aspect else mode   # same aspect: a fit == a plain scale, no face tracking
    pl = R.plan(master, prof.w, prof.h, mode=m, safe=P.safe_box(prof), start=start, dur=dur,
                fallback=fallback, **reframe_opts)
    if band:
        same_aspect = False
    if pl["mode_used"] != m:
        warnings.append(f"reframe fell back to {pl['mode_used']}: {pl.get('fallback_reason')}")
    cue_list = load_cues(cues) if (cues is not None and captions) else []
    kos = load_keepouts(cues, (info["display_w"], info["display_h"])) if cue_list else []
    if start:
        from .subs import Cue
        cue_list = [Cue(c.start - start, c.end - start, c.text, c.alt, c.meta) for c in cue_list if c.end > start]
        kos = [dict(k, t0=k["t0"] - start, t1=k["t1"] - start) for k in kos if k["t1"] > start]
    cap_report = {}
    pl_geo = pl
    overlay = caption_overlay(prof, cue_list, pl["fps"], keepouts=kos, plan=pl_geo, report=cap_report) if cue_list else None
    for c in cue_list:
        fit = P.fit_text_size(prof, c.text.replace("\n", " "))
        if not fit["fits"]:
            warnings.append(f"caption too long for {prof.caption['max_lines']} lines at min size: {c.text[:24]}…")
    fps_out = None
    if info["fps"] and info["fps"] > prof.fps.get("max", 60) + 0.5:
        fps_out = prof.fps.get("default", 30)
    enc = dict(prof.encode)
    vargs = media.delivery_args(crf=enc.get("crf"), preset=preset, audio=None, faststart=False, encoder=encoder,
                                maxrate=enc.get("maxrate"), bufsize=enc.get("bufsize"), vbitrate=enc.get("vbitrate"))
    has_a = info["has_audio"]
    tmpd = workdir or tempfile.mkdtemp(prefix="vexport-")
    try:
        fast = same_aspect and overlay is None and not info.get("hdr")
        if has_a:
            mid = os.path.join(tmpd, stem + ".mov")
            if fast:
                _scale_only(master, mid, prof, info, start, dur, vargs, fps_out)
            else:
                R.render(master, mid, pl_geo, overlay=overlay,
                         encode_args=vargs + ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"], fps=fps_out)
            audio.loudnorm_2pass(mid, out_mp4, lufs=prof.loudness["lufs"], tp=prof.loudness["tp"])
        else:
            if fast:
                _scale_only(master, out_mp4, prof, info, start, dur, vargs, fps_out)
            else:
                R.render(master, out_mp4, pl_geo, overlay=overlay, encode_args=vargs + ["-an", "-movflags", "+faststart"],
                         fps=fps_out)
            warnings.append("master has no audio")
        if cap_report.get("blocked"):
            warnings.append(f"captions overlap a burned overlay (keepout) on {cap_report['blocked']} frames: "
                            f"no free spot in the safe box")
    finally:
        if workdir is None:
            shutil.rmtree(tmpd, ignore_errors=True)
    crop_json = os.path.join(out_dir, stem + ".crop.json")
    with open(crop_json, "w") as f:
        json.dump(pl, f)
    oinfo = media.probe(out_mp4)
    loud = None
    if has_a:
        mm = audio.measure_loudness(out_mp4, prof.loudness["lufs"], prof.loudness["tp"])
        loud = dict(i=round(mm["input_i"], 2), tp=round(mm["input_tp"], 2), lra=round(mm["input_lra"], 2))
        if abs(mm["input_i"] - prof.loudness["lufs"]) > 1.0:
            warnings.append(f"loudness {mm['input_i']:.1f} LUFS vs target {prof.loudness['lufs']}")
        if mm["input_tp"] > prof.loudness["tp"] + 0.5:
            warnings.append(f"true peak {mm['input_tp']:.1f} dBTP over {prof.loudness['tp']}")
    warnings += P.check_length(prof, oinfo["duration"])
    warnings += P.check_format(prof, info["display_w"] / info["display_h"], oinfo["duration"])
    lim = prof.extra.get("limits") or {}
    if lim.get("max_bytes") and os.path.getsize(out_mp4) > lim["max_bytes"]:
        warnings.append(f"file {os.path.getsize(out_mp4) / 1e6:.0f} MB over the {prof.name} upload cap "
                        f"{lim['max_bytes'] / 1e6:.0f} MB ({prof.extra.get('account') or 'standard'} account)")
    capr = prof.extra.get("captions") or {}
    if capr.get("burn") == "recommended" and not cue_list and captions:
        warnings.append(f"{prof.name}: {capr.get('reason', 'burned captions recommended')} (pass --cues)")
    cover_path, notes = make_cover(prof, covers, out_mp4, os.path.join(out_dir, stem + ".cover.jpg"),
                                   per_target=cover_targets, warnings=warnings)
    entry = dict(platform=prof.name, orientation=prof.orientation, label=prof.label, file=os.path.basename(out_mp4),
                 w=oinfo["w"], h=oinfo["h"], fps=round(oinfo["fps"], 3), duration=round(oinfo["duration"], 3),
                 loudness=loud, target_loudness=prof.loudness, reframe=dict(
                     mode="scale" if same_aspect else pl["mode"], mode_used="scale" if same_aspect else pl["mode_used"],
                     hit_rate=pl.get("hit_rate"), cuts=len(pl.get("cuts") or []),
                     switches=pl.get("switches"), stats=pl.get("stats"), plan=os.path.basename(crop_json),
                     **({"band": band} if band else {})),
                 captions=len(cue_list), keepouts=len(kos), captions_moved_frames=cap_report.get("moved", 0),
                 cover=os.path.basename(cover_path), cover_size=list(P.cover_size(prof)),
                 notes=notes, safe_box=list(P.safe_box(prof)), caption_box=list(P.caption_box(prof)))
    if prof.feed_crop:
        entry["notes"].append(f"{prof.label} feed shows a centre {prof.feed_crop} crop of the video "
                              f"{list(P.feed_crop_box(prof))}: keep faces and captions inside it")
    if post:
        from . import publish
        msgs = []
        src_cues = cue_list or (load_cues(cues) if cues is not None else [])
        content_lang = post_lang or publish.detect_lang(src_cues)
        body, copy = publish.platform_post(post, _publish_platform(prof), content_lang=content_lang,
                                           lang=post.get("_lang"), bilingual=post.get("_bilingual"), warn=msgs.append)
        warnings += msgs
        warnings += P.check_text(prof, body=body, tags=copy.get("tags"))   # title already checked by post_body
        if copy.get("chapters") and not prof.chapters.get("supported") and prof.name not in publish.NO_TITLE:
            entry["notes"].append(f"{prof.label} has no native chapters; timeline kept as plain text")
        pp = os.path.join(out_dir, stem + ".post.md")
        with open(pp, "w", encoding="utf-8") as f:
            f.write(body)
        entry["post"] = os.path.basename(pp)
        entry["post_lang"] = copy.get("lang")
        entry["post_len"] = P.text_len(prof, body)
    entry["warnings"] = list(dict.fromkeys(warnings))
    return entry


def export(master, targets, out_dir="exports", cues=None, covers=None, post=None, account=None, **kw):
    """Export to every target ("name[:orientation]" strings or Profiles). Writes out_dir/manifest.json and
    returns the manifest dict. A bare platform name that takes several shapes (X) gets the orientation closest
    to the master's aspect (no letterbox); ``account`` ("premium") applies that account tier's limits."""
    os.makedirs(out_dir, exist_ok=True)
    mi = media.probe(master)
    aspect = mi["display_w"] / mi["display_h"]
    ov = {"account": account} if account else None
    profs = P.parse_targets(targets if isinstance(targets, (str, list, tuple)) else [targets], master_aspect=aspect,
                            overrides=ov)
    covers = [covers] if isinstance(covers, str) else list(covers or [])
    covers, per = parse_covers(covers)
    if per:
        kw = dict(kw, cover_targets=dict(per, **(kw.get("cover_targets") or {})))
    entries = []
    from .batch.livestatus import heartbeat
    for i, prof in enumerate(profs):
        print(f"[export] {prof.key} {prof.w}x{prof.h}", file=sys.stderr)
        heartbeat("export", progress=i / max(1, len(profs)), message=prof.key, force=True)
        entries.append(export_one(master, prof, out_dir, cues=cues, covers=covers, post=post, **kw))
    man = dict(master=os.path.abspath(master), master_info={k: media.probe(master)[k] for k in
                                                            ("w", "h", "fps", "duration", "has_audio")},
               exports=entries, warnings=[f"{e['platform']}:{e['orientation']}: {w}" for e in entries for w in e["warnings"]])
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.export", description=__doc__.split("\n\n")[0])
    ap.add_argument("master", help="clean (caption-free) master video")
    ap.add_argument("--platforms", default=None,
                    help="comma list of name[:orientation], e.g. xiaohongshu:vertical,douyin,youtube "
                         "(default persona platforms.default). Known: " + ", ".join(P.list_profiles()))
    ap.add_argument("--out", default="exports")
    ap.add_argument("--cues", help="cues.json (subs.Cue dicts) or .srt to burn per platform")
    ap.add_argument("--cover", action="append", default=[],
                    help="cover image(s): a path (closest aspect wins; another aspect is fitted on a blurred pad) "
                         "or platform[:orientation]=path for one target, e.g. --cover xiaohongshu=c34.png")
    ap.add_argument("--no-captions", action="store_true",
                    help="do not burn --cues (the master already carries its captions)")
    ap.add_argument("--title", help="post title (checked against each platform's limit)")
    ap.add_argument("--post", help="post.json {title, hook, body, chapters, links, tags} -> <target>.post.md")
    ap.add_argument("--lang", default=None, help="post copy language (en | zh); default: the content language "
                    "detected from the cues (English content -> English copy on X / Instagram / TikTok / YouTube)")
    ap.add_argument("--bilingual", action="store_true", help="post copy in English + Chinese (post.json en + zh blocks)")
    ap.add_argument("--account", default=None, help="account tier for limits, e.g. premium (X: longer videos/posts)")
    ap.add_argument("--mode", default="face", choices=R.MODES, help="reframe mode when the aspect changes")
    ap.add_argument("--fallback", default="pad-blur", choices=R.MODES[1:])
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--encoder", default=None, help="H.264 encoder (default $VSTUDIO_H264_ENCODER / persona "
                    "export.h264_encoder / libx264): libx264 | videotoolbox | h264_videotoolbox | h264_mf")
    ap.add_argument("--preset", default="medium")
    a = ap.parse_args(argv)
    targets = a.platforms
    if not targets:
        try:
            from .config import persona
            targets = (persona().get("platforms") or {}).get("default") or "xiaohongshu"
        except Exception:
            targets = "xiaohongshu"
    post = None
    if a.post:
        with open(a.post, encoding="utf-8") as f:
            post = json.load(f)
    if a.title:
        post = dict(post or {}, title=a.title)
    if post is not None and (a.lang or a.bilingual):
        post = dict(post, _lang=a.lang, _bilingual=a.bilingual or None)
    man = export(a.master, targets, a.out, cues=a.cues, covers=a.cover, post=post, account=a.account,
                 mode=a.mode, fallback=a.fallback,
                 start=a.start, dur=a.dur, encoder=a.encoder, preset=a.preset, captions=not a.no_captions)
    for e in man["exports"]:
        print(f"{e['file']:32s} {e['w']}x{e['h']} {e['duration']:.1f}s "
              f"{(e['loudness'] or {}).get('i', '-')} LUFS  reframe={e['reframe']['mode_used']}")
    for w in man["warnings"]:
        print("WARN", w)
    print(os.path.join(a.out, "manifest.json"))


if __name__ == "__main__":
    sys.exit(main())
