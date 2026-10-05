#!/usr/bin/env python3
"""1280x720 YouTube thumbnail, built to the two-person-conversation convention
that the genre actually uses:

  - the headline owns the top ~55% and is set far larger than feels right on a
    full-size canvas, because the thumbnail is read at ~210px wide in a feed
  - one line carries the setup in white, one carries the punch in the accent
    colour, both with a heavy dark stroke so they survive any background
  - both speakers sit along the bottom as large, tightly cropped faces, one per
    side, which is what signals "two people talking" at a glance
  - a vignette and a colour wash keep the faces from competing with the text

Everything is driven by the `thumb` block in the title json, so a variant is a
config edit rather than a code edit.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout
from style import TEAL, YEL, WHITE, DIM, font, alpha_paste, frame_at
from vstudio.draw import fit_font, text_width

W, H = 1280, 720
ACCENTS = {"teal": TEAL, "yellow": YEL, "white": WHITE}


def face_crop(frame, rect, face_cx, face_cy, top_y, out_w, out_h, zoom):
    """Crop around a face, clamped inside the tile and anchored so the top of
    the head (top_y, which for the guest is the sticker's top edge) keeps a
    margin. A thumbnail with a head sliced off reads as a mistake."""
    rx, ry, rw, rh = rect
    cw, ch = int(out_w / zoom), int(out_h / zoom)
    x0 = int(np.clip(face_cx - cw / 2, rx, rx + rw - cw))
    y0 = int(np.clip(top_y - ch * 0.04, ry, ry + rh - ch))
    return cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (out_w, out_h),
                      interpolation=cv2.INTER_CUBIC)


def host_face(frame, rect):
    """The host has no stored track, so read their face from this one frame."""
    from vstudio.face import landmarker, detect
    rx, ry, rw, rh = rect
    det = landmarker(num_faces=1)
    faces = detect(det, np.ascontiguousarray(frame[ry:ry + rh, rx:rx + rw]))
    det.close()
    if not faces:
        return rx + rw * 0.47, ry + rh * 0.45, rh * 0.45
    p = faces[0]["pts"] + np.array([rx, ry], np.float32)
    return p[:, 0].mean(), (p[:, 1].min() + p[:, 1].max()) / 2, np.ptp(p[:, 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="the SOURCE recording, not the rendered cut")
    ap.add_argument("--at", type=float, default=300)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--track", required=True)
    ap.add_argument("--sticker", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--zoom", type=float, default=1.30)
    ap.add_argument("--guest-region", default="0,180,640,360")
    ap.add_argument("--host-region", default="640,180,640,360")
    ap.add_argument("--scale", type=float, default=2.40, help="same sticker geometry as the render")
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--platform", default=None,
                    help="size the thumbnail for this profile's cover (youtube 1280x720, bilibili 1146x717 ...)")
    ap.add_argument("--name-mask", default=None, choices=["blur", "cover", "off"],
                    help="hide the call app's name labels in both tiles (default persona call_clips.name_mask, else blur)")
    ap.add_argument("--name-box", default=None, help="label rect as tile fractions fx,fy,fw,fh")
    args = ap.parse_args()
    prof = layout.cover_profile(args.platform, "horizontal")
    nmask = layout.parse_name_mask({"mode": args.name_mask, "box": args.name_box}
                                   if (args.name_mask or args.name_box) else None)

    meta = json.load(open(args.title_json))
    tb = meta["thumb"]
    accent = ACCENTS[tb.get("accent_color", "yellow")]

    # the guest's face is covered in the thumbnail too: grab exactly the frame
    # the track sample j belongs to
    tr = json.load(open(args.track))
    fps = tr.get("fps") or cv2.VideoCapture(args.video).get(cv2.CAP_PROP_FPS) or 25.0
    j = min(int(args.at * fps), len(tr["cx"]) - 1)
    fr = frame_at(args.video, j / fps)
    layout.mask_names(fr, layout.name_rects(nmask, [[int(v) for v in args.guest_region.split(",")]],
                                            [[int(v) for v in args.host_region.split(",")]]), nmask["mode"])
    gcx, gcy, gw = tr["cx"][j], tr["cy"][j], tr["w"][j]
    st = Image.open(args.sticker).convert("RGBA")
    sw = max(24, int(round(gw * args.scale)))
    sa = np.array(st.resize((sw, int(round(sw * st.height / st.width))), Image.LANCZOS))
    alpha_paste(fr, sa, gcx, gcy + args.y_offset * sa.shape[0])

    grect = [int(v) for v in args.guest_region.split(",")]
    hrect = [int(v) for v in args.host_region.split(",")]
    # host face centre, read once from this frame
    hcx, hcy, hface_h = host_face(fr, hrect)

    band_h = int(H * 0.56)
    zoom = args.zoom
    cat_top = gcy + args.y_offset * sa.shape[0] - sa.shape[0] / 2
    left = face_crop(fr, grect, gcx, gcy, cat_top, W // 2, band_h, zoom)
    right = face_crop(fr, hrect, hcx, hcy, hcy - hface_h * 0.85, W // 2, band_h, zoom)

    img = Image.new("RGB", (W, H), (8, 9, 12))
    strip = Image.fromarray(cv2.cvtColor(np.hstack([left, right]), cv2.COLOR_BGR2RGB))
    img.paste(strip, (0, H - band_h))

    # cool the faces down and fade their top edge into the headline block
    px = np.array(img).astype(np.float32)
    band = px[H - band_h:]
    band[:, :, 0] *= 0.90          # cool the faces slightly
    band[:, :, 1] *= 0.96
    band *= 1.18                   # but keep them bright enough to read
    for k in range(150):
        band[k] *= 0.12 + 0.88 * k / 150
    px[H - band_h:] = band
    # vignette, so the corners do not pull the eye off the text
    yy, xx = np.mgrid[0:H, 0:W]
    v = 1 - 0.38 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    px *= np.clip(v, 0.55, 1)[:, :, None]
    img = Image.fromarray(np.clip(px, 0, 255).astype(np.uint8))

    # a soft accent glow behind the headline
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-200, -260, 900, 420], fill=tuple(int(c * 0.30) for c in accent))
    img = Image.fromarray(np.clip(
        np.array(img).astype(np.int16) +
        np.array(glow.filter(ImageFilter.GaussianBlur(150))).astype(np.int16), 0, 255
    ).astype(np.uint8))

    d = ImageDraw.Draw(img)
    if tb.get("eyebrow"):
        d.rectangle([64, 52, 64 + 72, 58], fill=accent)
        d.text((64, 72), tb["eyebrow"], font=font(30), fill=accent)

    y = tb.get("y", 118)
    for line, is_acc in tb["lines"]:
        f = fit_font(line, "cjk-bold", tb.get("size", 104), W - 128, min_size=40)
        d.text((64, y), line, font=f, fill=accent if is_acc else WHITE,
               stroke_width=9, stroke_fill=(0, 0, 0))
        y += int(f.size * 1.16)

    fl = font(28)
    for label, cx in ((meta.get("guest_label", ""), W * 0.25),
                      (meta.get("host_label", ""), W * 0.75)):
        if not label:
            continue
        wlab = text_width(label, fl) + 36
        d.rounded_rectangle([cx - wlab / 2, H - 58, cx + wlab / 2, H - 14],
                            radius=22, fill=(0, 0, 0, 255), outline=accent, width=2)
        d.text((cx - text_width(label, fl) / 2, H - 50), label, font=fl, fill=WHITE)

    img.save(args.out, quality=95)
    layout.fit_saved_cover(args.out, prof)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
