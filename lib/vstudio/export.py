"""Multi-platform export: one clean master -> a file + cover + post stub per platform, plus a manifest.

    python -m vstudio.export master.mp4 --platforms xiaohongshu:vertical,douyin,youtube --out exports/ \\
        [--cues cues.json | --cues subs.srt] [--cover cover.png ...] [--title "..."] [--post post.json]

Per target (vstudio.platform profile):
  1. reframe the master to the profile canvas (vstudio.reframe): same aspect -> plain scale; otherwise
     ``--mode`` (default face, keeping the face in the profile's safe box; no face -> pad-blur);
  2. burn captions (if cues are given) in the profile's caption box at a fitted size (PIL, no libass);
  3. two-pass loudnorm to the profile's LUFS / true-peak target (audio.loudnorm_2pass);
  4. H.264 delivery encode (media.delivery_args with the profile's encode guidance);
  5. cover: the --cover whose aspect is closest, cover-cropped to platform.cover_size (else a frame of
     the export); covers shown as a centre crop in the feed also get a ``.feed.jpg`` preview;
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
def load_cues(path):
    from .subs import Cue, srt_read
    if path is None:
        return []
    if isinstance(path, (list, tuple)):
        return [c if isinstance(c, Cue) else Cue.from_dict(c) for c in path]
    if str(path).lower().endswith(".srt"):
        return srt_read(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("cues") or data.get("segments") or []
    return [Cue.from_dict(d) for d in data]


def caption_overlay(prof, cues, fps, role="cjk-bold", fill=(255, 255, 255, 255)):
    """overlay(i, t, img_bgr) for reframe.render: draws the active cue centred in caption_box."""
    from . import draw
    x0, y0, x1, y1 = P.caption_box(prof)
    cache = {}

    def layer(k, c):
        if k not in cache:
            fit = P.fit_text_size(prof, c.text.replace("\n", " "), role)
            f = draw.load_font(role, fit["size"])
            stroke = max(2, int(fit["size"] * float(prof.caption.get("stroke", 0.08))))
            prim = _lines_layer(fit["lines"], f, fill, stroke)
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

    def overlay(i, t, img):
        for a, b, k, c in spans:
            if a <= t < b:
                L = layer(k, c)
                h, w = L.shape[:2]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                y = min(cy - h / 2, y1 - h) if h <= y1 - y0 else cy - h / 2   # over-tall: centred on the band
                draw.alpha_paste(img, L, (cx - w / 2, y), bgr=True)
                break
        return img
    return overlay


def _lines_layer(lines, f, fill, stroke):
    """Centred stroked lines (markup 【】 highlighted in brand.highlight) as one RGBA strip."""
    from PIL import Image
    from . import draw
    rows = [draw.text_layer(ln, f, fill=fill, stroke=stroke, stroke_fill=(0, 0, 0, 235), shadow_alpha=110, pad=6)
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


def make_cover(prof, covers, video, out_path, at=None):
    """Write the profile's cover to out_path from the closest-aspect image in ``covers`` (paths), else from
    a frame of ``video`` (at ``at`` s, default 1/3 in). Returns (path, notes)."""
    from PIL import Image
    size = P.cover_size(prof)
    notes = []
    if covers:
        imgs = [(c, Image.open(c)) for c in covers]
        c, im = min(imgs, key=lambda ci: abs(np.log(_aspect(ci[1].size) / _aspect(size))))
        if abs(np.log(_aspect(im.size) / _aspect(size))) > 0.05:
            notes.append(f"cover {os.path.basename(c)} {im.width}x{im.height} re-fitted to {size[0]}x{size[1]} "
                         f"({prof.cover.get('aspect')}); check the title is still inside the crop")
    else:
        tmp = out_path + ".frame.png"
        media.grab_frame(video, at if at is not None else media.duration(video) / 3, tmp)
        im = Image.open(tmp); im.load(); os.remove(tmp)
        notes.append("no --cover given: used a frame of the export")
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
    return out_path, notes


# ----------------------------------------------------------------------------------- export
def _publish_platform(prof):
    return "youtube" if prof.name == "youtube-shorts" else prof.name


def export_one(master, prof, out_dir, cues=None, covers=None, post=None, mode="face", fallback="pad-blur",
               start=0.0, dur=None, workdir=None, encoder="libx264", preset="medium", **reframe_opts):
    """Export ``master`` for one Profile. Returns the manifest entry (dict)."""
    from . import audio
    info = media.probe(master)
    stem = f"{prof.name}-{prof.orientation}"
    out_mp4 = os.path.join(out_dir, stem + ".mp4")
    warnings = []
    same_aspect = abs(np.log(_aspect((info["display_w"], info["display_h"])) / _aspect(prof.size))) < 0.01
    m = "letterbox" if same_aspect else mode
    pl = R.plan(master, prof.w, prof.h, mode=m, safe=P.safe_box(prof), start=start, dur=dur,
                fallback=fallback, **reframe_opts)
    if pl["mode_used"] != m:
        warnings.append(f"reframe fell back to {pl['mode_used']}: {pl.get('fallback_reason')}")
    cue_list = load_cues(cues) if cues is not None else []
    if start:
        from .subs import Cue
        cue_list = [Cue(c.start - start, c.end - start, c.text, c.alt, c.meta) for c in cue_list if c.end > start]
    overlay = caption_overlay(prof, cue_list, pl["fps"]) if cue_list else None
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
        if has_a:
            mid = os.path.join(tmpd, stem + ".mov")
            R.render(master, mid, pl, overlay=overlay, encode_args=vargs + ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"],
                     fps=fps_out)
            audio.loudnorm_2pass(mid, out_mp4, lufs=prof.loudness["lufs"], tp=prof.loudness["tp"])
        else:
            R.render(master, out_mp4, pl, overlay=overlay, encode_args=vargs + ["-an", "-movflags", "+faststart"],
                     fps=fps_out)
            warnings.append("master has no audio")
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
    cover_path, notes = make_cover(prof, covers, out_mp4, os.path.join(out_dir, stem + ".cover.jpg"))
    entry = dict(platform=prof.name, orientation=prof.orientation, label=prof.label, file=os.path.basename(out_mp4),
                 w=oinfo["w"], h=oinfo["h"], fps=round(oinfo["fps"], 3), duration=round(oinfo["duration"], 3),
                 loudness=loud, target_loudness=prof.loudness, reframe=dict(
                     mode=pl["mode"], mode_used=pl["mode_used"], hit_rate=pl.get("hit_rate"), cuts=len(pl.get("cuts") or []),
                     switches=pl.get("switches"), stats=pl.get("stats"), plan=os.path.basename(crop_json)),
                 captions=len(cue_list), cover=os.path.basename(cover_path), cover_size=list(P.cover_size(prof)),
                 notes=notes, safe_box=list(P.safe_box(prof)), caption_box=list(P.caption_box(prof)))
    if post:
        from . import publish
        msgs = []
        tags = post.get("tags")
        body = publish.post_body(post.get("hook", ""), post.get("body", ""), chapters=post.get("chapters"),
                                 links=post.get("links"), tags=tags, platform=_publish_platform(prof),
                                 title=post.get("title"), warn=msgs.append)
        warnings += msgs
        warnings += P.check_text(prof, body=body, tags=tags)   # title already checked by post_body
        if post.get("chapters") and not prof.chapters.get("supported"):
            entry["notes"].append(f"{prof.label} has no native chapters; timeline kept as plain text")
        pp = os.path.join(out_dir, stem + ".post.md")
        with open(pp, "w", encoding="utf-8") as f:
            f.write(body)
        entry["post"] = os.path.basename(pp)
    entry["warnings"] = list(dict.fromkeys(warnings))
    return entry


def export(master, targets, out_dir="exports", cues=None, covers=None, post=None, **kw):
    """Export to every target ("name[:orientation]" strings or Profiles). Writes out_dir/manifest.json and
    returns the manifest dict."""
    os.makedirs(out_dir, exist_ok=True)
    profs = [t if isinstance(t, P.Profile) else P.profile(t) for t in
             (P.parse_targets(targets) if isinstance(targets, str) else targets)]
    covers = [covers] if isinstance(covers, str) else list(covers or [])
    entries = []
    for prof in profs:
        print(f"[export] {prof.key} {prof.w}x{prof.h}", file=sys.stderr)
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
    ap.add_argument("--cover", action="append", default=[], help="cover image(s); closest aspect is re-fitted")
    ap.add_argument("--title", help="post title (checked against each platform's limit)")
    ap.add_argument("--post", help="post.json {title, hook, body, chapters, links, tags} -> <target>.post.md")
    ap.add_argument("--mode", default="face", choices=R.MODES, help="reframe mode when the aspect changes")
    ap.add_argument("--fallback", default="pad-blur", choices=R.MODES[1:])
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--encoder", default="libx264", choices=["libx264", "videotoolbox"])
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
    man = export(a.master, targets, a.out, cues=a.cues, covers=a.cover, post=post, mode=a.mode, fallback=a.fallback,
                 start=a.start, dur=a.dur, encoder=a.encoder, preset=a.preset)
    for e in man["exports"]:
        print(f"{e['file']:32s} {e['w']}x{e['h']} {e['duration']:.1f}s "
              f"{(e['loudness'] or {}).get('i', '-')} LUFS  reframe={e['reframe']['mode_used']}")
    for w in man["warnings"]:
        print("WARN", w)
    print(os.path.join(a.out, "manifest.json"))


if __name__ == "__main__":
    sys.exit(main())
