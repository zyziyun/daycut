#!/usr/bin/env python3
"""Generate the HyperFrames index.html for a promo recut from the project config + work/layout.json.

Packaging: split-screen talking head (clip-path inset + slide) next to 3D screenshot cards that scroll to
the part being talked about, highlighter sweeps and a red box; chips row; subtitles with 【term】 highlight;
punch-ins; freeze-frame hold with a prompt card flying out of a screenshot (body video split in two clips +
data-media-start); zoom-through into a framed "screen" playing the highlights montage at its own rate with
step labels + badge/title; outro punch + stamp; end card; chapter progress bar on a scrim.

  python3 $VSTUDIO/workflows/promo-recut/scripts/build_promo.py promo.config.json [--orientation vertical]
  python3 $VSTUDIO/workflows/promo-recut/scripts/build_promo.py promo.config.json --platform douyin   # -> promo-vertical-douyin-vertical/

Writes <promo_dir>/index.html, copies media + subset fonts into <promo_dir>/assets/, extracts the freeze
frame, and writes <promo_dir>/timeline.json (section + chapter times, used by post_copy.py).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project, P, link_or_copy, body_rate, parse_clip  # noqa: E402
import screen_crop  # noqa: E402
from vstudio import hf, media, overlays, render  # noqa: E402
from vstudio import platform as PF  # noqa: E402
from vstudio.cut import TimeMap  # noqa: E402

# ---------------------------------------------------------------- geometry per orientation
GEO = {
    "horizontal": dict(
        W=1920, H=1080, face_pos="50% 50%",
        split_inset="inset(40px 520px 120px 500px round 28px)", split_x=-440, split_y=0,
        card_l=1100, card_t=60, CW=760, CHH=740, chips_l=1080, chips_t=822, chips_w=800,
        cue_lr=160, cue_t=922, cue_fs=50,
        scrim_t=990, scrim_h=90, bar_l=80, bar_t=1046, bar_w=1760, chap_t=1012,
        pz_l=160, pz_t=250, pz_w=1600,
        scr_l=0, scr_t=0, scr_w=1920, scr_h=1080, scr_in=0.84, scr_y=-44, scr_drift=0.85,
        mbadge_l=160, mbadge_t=954, mlabel_l=262, mlabel_t=958, mtag_css="right:160px; top:956px;",
        mtitle_t=400, mtitle_fs=96, stamp_l=1290, stamp_t=230, end_fs=80,
        # PiP: face clipped to inset(top right bottom left) (unscaled px), scaled, parked bottom-right
        pip_clip=[60, 500, 140, 500], pip_scale=0.30, pip_radius=70, pip_right=70, pip_bottom=150,
        pip_frame=[60, 44, 1800, 1012],
    ),
    "vertical": dict(
        W=1080, H=1920, face_pos="50% 50%",
        split_inset="inset(200px 40px 1000px 40px round 28px)", split_x=0, split_y=0,
        card_l=90, card_t=1000, CW=900, CHH=560, chips_l=60, chips_t=936, chips_w=960,
        cue_lr=60, cue_t=820, cue_fs=54,
        scrim_t=1580, scrim_h=120, bar_l=60, bar_t=1640, bar_w=960, chap_t=1606,
        pz_l=50, pz_t=560, pz_w=980,
        scr_l=0, scr_t=656, scr_w=1080, scr_h=608, scr_in=0.94, scr_y=0, scr_drift=0.95,
        mbadge_l=60, mbadge_t=1296, mlabel_l=170, mlabel_t=1300, mtag_css="left:60px; top:1380px;",
        mtitle_t=360, mtitle_fs=72, stamp_l=560, stamp_t=380, end_fs=60,
        pip_clip=[120, 140, 820, 140], pip_scale=0.40, pip_radius=60, pip_right=60, pip_bottom=420,
        pip_frame=[40, 200, 1000, 562],
    ),
}


def r(x):
    return round(x, 3)


# ---------------------------------------------------------------- picture-in-picture geometry
def pip_layout(g):
    """Face tile + screen frame for PiP windows from GEO keys pip_clip [top, right, bottom, left] (the region
    of the full-frame face kept, unscaled px), pip_scale, pip_radius, pip_right / pip_bottom (tile margins to
    the canvas edges), pip_frame [l, t, w, h] -> {clip, scale, x, y, tile [l, t, w, h], frame, tile_radius}
    (#face has transform-origin 0 0: a point p lands at (x, y) + scale * p)."""
    W, H = g["W"], g["H"]
    ct, cr, cb, cl = g["pip_clip"]
    s = float(g["pip_scale"])
    rw, rh = W - cl - cr, H - ct - cb
    tw, th = rw * s, rh * s
    tl_, tt = W - g["pip_right"] - tw, H - g["pip_bottom"] - th
    rad = g.get("pip_radius", 70)
    return dict(clip=f"inset({ct}px {cr}px {cb}px {cl}px round {rad}px)", scale=s,
                x=round(tl_ - cl * s, 1), y=round(tt - ct * s, 1),
                tile=[round(tl_, 1), round(tt, 1), round(tw, 1), round(th, 1)],
                frame=list(g["pip_frame"]), tile_radius=round(rad * s, 1))


def final_time(tm, raw, rate, offset=0.0, hold_at=None, hold=0.0):
    """Raw body second -> final composition second: offset (hook montage length) + cut-file second / rate
    (+ the freeze hold once raw >= hold_at). Inside a cut -> start of the next kept span."""
    t = tm.to_final(raw, snap="fwd")
    t = tm.to_final(raw, snap="back") if t is None else t
    return offset + t / rate + (hold if hold_at is not None and raw >= hold_at else 0.0)


def clip_cues(cues, gap=0.02, min_dur=0.2, bridge=0.25):
    """Final-timeline cues [{s, e}] (sorted in place by start): every cue ends `gap` s before the next one starts
    (the +0.15 s tail at a fast body rate would otherwise put two captions on screen at once), and a gap shorter
    than `bridge` is closed up to the same point. A cue keeps at least `min_dur` s."""
    cues.sort(key=lambda c: c["s"])
    for x, y in zip(cues, cues[1:]):
        if y["s"] - x["e"] < bridge:
            x["e"] = r(max(x["s"] + min_dur, y["s"] - gap))
    return cues


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def validate_windows(pips, cards=(), splits=(), hold_at=None, body=None, punches=()):
    """PiP windows vs everything else that moves the talking head (all raw seconds). Raises ValueError on
    PiP / PiP or PiP / card-split overlap, a PiP across the freeze hold, outside the body, or shorter than
    1 s; returns warnings (PiP over a punch-in)."""
    errs, warns = [], []
    P = sorted([(float(w["start"]), float(w["end"]), k) for k, w in enumerate(pips)])
    for a, b, k in P:
        if b - a < 1.0:
            errs.append(f"pip[{k}] [{a}, {b}] is shorter than 1 s")
        if body and not any(s0 - 0.05 <= a and b <= s1 + 0.05 for s0, s1 in body):
            if not (body[0][0] - 0.05 <= a and b <= body[-1][1] + 0.05):
                errs.append(f"pip[{k}] [{a}, {b}] is outside the body (cut.body {body[0][0]}-{body[-1][1]})")
        if hold_at is not None and a <= hold_at < b:
            errs.append(f"pip[{k}] [{a}, {b}] covers the freeze hold at {hold_at}")
    for (a0, b0, k0), (a1, b1, k1) in zip(P, P[1:]):
        if a1 < b0:
            errs.append(f"pip[{k0}] [{a0}, {b0}] overlaps pip[{k1}] [{a1}, {b1}]")
    for a, b, k in P:
        for j, c in enumerate(cards):
            if overlaps((a, b), (float(c["start"]), float(c["end"]))):
                errs.append(f"pip[{k}] [{a}, {b}] overlaps card[{j}] [{c['start']}, {c['end']}] (split screen): "
                            "move one of them - the face cannot be a tile and a split at once")
        for sa, sb in splits:
            if overlaps((a, b), (float(sa), float(sb))):
                errs.append(f"pip[{k}] [{a}, {b}] overlaps split [{sa}, {sb}]")
        for pa, pb in punches:
            if overlaps((a, b), (float(pa), float(pb))):
                warns.append(f"pip[{k}] [{a}, {b}] overlaps punch [{pa}, {pb}]: the tile will zoom too")
    if errs:
        raise ValueError("PiP windows:\n  " + "\n  ".join(errs))
    return warns


# ---------------------------------------------------------------- platform profiles (vstudio.platform)
def resolve_platform(spec, ori):
    """-> (Profile or None, orientation). spec "douyin" / "xiaohongshu:full" / None.
    No spec: horizontal -> None (the legacy 1920x1080 GEO, byte-identical output); vertical -> the persona's
    default platform at 9:16 ("full"; 小红书 full-screen by default)."""
    if spec:
        n, _, o = str(spec).partition(":")
        if not o and ori:
            o = {"vertical": "full", "horizontal": "horizontal"}[ori]
        try:
            prof = PF.profile(n, o or None)
        except KeyError:
            prof = PF.profile(n, None if not o else ("vertical" if o == "full" else o))
        return prof, ("vertical" if prof.h > prof.w else "horizontal")
    if ori == "vertical":
        name = P("platforms.default", "xiaohongshu") or "xiaohongshu"
        return PF.profile(name, "full"), "vertical"
    return None, ori or "horizontal"


def estimate_face(video, samples=6):
    """Median main-face centre / height over a few frames, as fractions of the source frame:
    (fx, fy, fh) or None when no face is found (or mediapipe / the model is missing)."""
    try:
        import cv2
        import numpy as np
        from vstudio import face as F
        cap = cv2.VideoCapture(video)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        lm = F.landmarker(1)
        found = []
        for k in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / samples))
            ok, img = cap.read()
            if not ok:
                continue
            f = F.main_face(F.detect(lm, img))
            if f is not None:
                p, (h, w) = f["pts"], img.shape[:2]
                found.append(((p[:, 0].min() + p[:, 0].max()) / 2 / w, (p[:, 1].min() + p[:, 1].max()) / 2 / h,
                              (p[:, 1].max() - p[:, 1].min()) / h))
        cap.release()
        lm.close()
        if not found:
            return None
        return tuple(float(v) for v in np.median(np.array(found), axis=0))
    except Exception as e:  # no mediapipe / model / unreadable video: fall back to a centred speaker
        print(f"face estimate skipped ({type(e).__name__}); using a centred speaker")
        return None


def vertical_geo(prof, src_wh, face=None, montage_aspect=16 / 9):
    """GEO for a vertical canvas derived from a platform profile: chapter bar + labels at the top of the safe
    box, talking-head band below it, chips + screenshot card under the band, captions in the profile's caption
    box (bottom-anchored, sized from its caption style), framed montage screen + labels above the caption band.
    Every box is inside the safe box and clear of the lower-right button column. face = (fx, fy, fh) as
    fractions of the source frame (estimate_face) or None (centred speaker, eyes ~40 % down)."""
    W, H = prof.w, prof.h
    x0, y0, x1, y1 = PF.safe_box(prof)
    cx0, cy0, cx1, cy1 = PF.caption_box(prof)
    kos = PF.keepouts(prof)

    def margin(ya, yb):  # symmetric side margin for content spanning ya..yb
        m = max(x0, W - x1)
        for kx0, ky0, kx1, ky1 in kos:
            if ky0 < yb and ky1 > ya:
                m = max(m, W - kx0)
        return int(m)

    # where the face lands on the canvas when the talk is shown full-frame (object-fit: cover)
    fx, fy, fh = face or (0.5, 0.40, None)
    sw, sh = src_wh
    S = max(W / sw, H / sh)
    dw, dh = sw * S, sh * S
    px = min(1.0, max(0.0, (dw * fx - W / 2) / (dw - W))) if dw > W + 1 else 0.5
    py = min(1.0, max(0.0, (dh * fy - H / 2) / (dh - H))) if dh > H + 1 else 0.5
    fyc = dh * fy - (dh - H) * py

    bar_t = y0 + 14
    lab_b = bar_t + 14 + 34              # bottom of the chapter labels
    top = y0 + 84                        # below the bar + chapter labels
    bottom = cy0 - 24                    # above the caption band
    avail = bottom - top
    gap, chips_h = 18, 44
    face_h = round(avail * 0.42)
    if fh:                               # band ~2.4 face heights tall (face + some shoulder), within limits
        face_h = int(min(avail * 0.5, max(avail * 0.36, fh * dh * 2.4)))
    mf = margin(top, top + face_h)
    ey0 = int(min(max(fyc - face_h * 0.45, 0), H - face_h))   # band in the face element's own coordinates
    split_inset = f"inset({ey0}px {mf}px {H - ey0 - face_h}px {mf}px round 28px)"
    chips_t = top + face_h + gap
    card_t = chips_t + chips_h + 12
    mc = margin(card_t, bottom)
    CW = W - 2 * mc

    cap = prof.caption
    lo, hi = (int(v) for v in cap["size"])
    cue_fs = int(min(hi, max(lo, (cx1 - cx0) // int(cap.get("max_chars_zh", 14)))))

    # montage: a 16:9 screen whose visible (scaled) frame spans the safe width, top of the free area
    s_in, s_drift = 0.94, 0.95
    ms = max(x0, W - x1)
    vis_w = W - 2 * ms
    fw = vis_w / s_in
    fhh = fw / montage_aspect
    Vt = top + 40                        # centre screen + labels in the free area, but stay above the buttons
    want = top + max(40, (cy0 - top - (fhh * s_in + 170)) / 2)
    lim = min([k[1] for k in kos] or [H]) - 20 - fhh * s_in
    Vt = max(Vt, min(want, lim))
    oy = 0.45 * H                        # #screen transform-origin 50% 45%
    scr_y = Vt - (oy + (Vt - oy) * s_in)
    vb = Vt + fhh * s_in                 # visible bottom of the screen
    mb = margin(Vt, vb)
    if mb > ms:                          # screen would reach into the button column: shrink it
        vis_w = W - 2 * mb; fw = vis_w / s_in; fhh = fw / montage_aspect
        scr_y = Vt - (oy + (Vt - oy) * s_in); vb = Vt + fhh * s_in
    ml = margin(vb, vb + 160)

    # PiP: a face region around the speaker (band height, ~0.9 wide) scaled to a tile ~36 % of the width,
    # sitting just above the caption band and clear of the button column; 16:9 screen frame above it
    fxc = dw * fx - (dw - W) * px
    rh = face_h
    rw = min(W, int(rh * 0.9))
    rt = int(min(max(fyc - rh * 0.45, 0), H - rh))
    rl = int(min(max(fxc - rw / 2, 0), W - rw))
    p_s = round(W * 0.36 / rw, 4)
    t_b = cy0 - 24
    t_t = t_b - rh * p_s
    p_r = margin(t_t, t_b)
    f_m = margin(top, t_t - 24)
    f_w = W - 2 * f_m
    f_h = min(f_w * 9 / 16, t_t - 24 - top)
    f_t = top + max(0, (t_t - 24 - top - f_h) / 2)
    end_pad = f"padding: {y0}px {margin(y0, cy0)}px {H - cy0}px {margin(y0, cy0)}px;"
    extra_css = (
        f"#bar-scrim {{ top: 0; height: {lab_b + 30}px; background: linear-gradient(to bottom, rgba(5,8,16,.8) 0px, "
        f"rgba(5,8,16,.74) {lab_b}px, rgba(5,8,16,0) {lab_b + 30}px); }}\n"
        f".cue {{ top: auto; bottom: {H - cy1}px; text-wrap: balance; }}\n"
        f"#endcard {{ {end_pad} }}\n")
    return dict(
        W=W, H=H, face_pos=f"{px * 100:.1f}% {py * 100:.1f}%",
        split_inset=split_inset, split_x=0, split_y=top - ey0,
        card_l=mc, card_t=card_t, CW=CW, CHH=bottom - card_t, chips_l=mc, chips_t=chips_t, chips_w=CW,
        cue_lr=cx0, cue_t=cy0, cue_fs=cue_fs,
        scrim_t=0, scrim_h=lab_b + 30, chap_fs=22, bar_l=margin(0, top), bar_t=bar_t, bar_w=W - 2 * margin(0, top), chap_t=bar_t + 14,
        pz_l=mc, pz_t=max(top + 80, (top + bottom) // 2 - 200), pz_w=CW,
        scr_l=round((W - fw) / 2, 1), scr_t=Vt, scr_w=round(fw, 1), scr_h=round(fhh, 1),
        scr_in=s_in, scr_y=round(scr_y, 1), scr_drift=s_drift,
        mbadge_l=ml, mbadge_t=int(vb + 30), mlabel_l=ml + 110, mlabel_t=int(vb + 34),
        mtag_css=f"left:{ml}px; top:{int(vb + 100)}px;",
        mtitle_t=int(Vt + fhh * s_in / 2 - 80), mtitle_fs=64, stamp_l=ml + 30, stamp_t=top + 60, end_fs=60,
        pip_clip=[rt, W - rl - rw, H - rt - rh, rl], pip_scale=p_s, pip_radius=60, pip_right=p_r, pip_bottom=H - t_b,
        pip_frame=[f_m, round(f_t, 1), f_w, round(f_h, 1)],
        extra_css=extra_css,
        boxes=dict(safe=[x0, y0, x1, y1], caption=[cx0, cy0, cx1, cy1], keepouts=[list(k) for k in kos],
                   face_band=[mf, top, W - mf, top + face_h], card=[mc, card_t, W - mc, bottom],
                   screen=[ms, int(Vt), W - ms, int(vb)]),
    )


FONT_NAMES = ("cjk-400", "cjk-700", "serif", "serif-italic")
FONT_FMT = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype", ".ttf": "truetype"}


def font_faces(fdir, text=None):
    """Subset Noto Sans SC + STIX Two Text to `text` (vstudio.render.subset_project_fonts), or with
    text=None reuse what is already in fdir. -> {name: (url, css format)}."""
    if text is not None:
        paths = render.subset_project_fonts(fdir, text)
    else:
        have = {os.path.splitext(f)[0]: os.path.join(fdir, f) for f in sorted(os.listdir(fdir))}
        paths = {n: have[n] for n in FONT_NAMES if n in have}
    return {n: (f"assets/fonts/{os.path.basename(p)}", FONT_FMT.get(os.path.splitext(p)[1].lower(), "opentype"))
            for n, p in paths.items()}


def all_strings(x):
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return "".join(all_strings(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return "".join(all_strings(v) for v in x)
    return ""


def scaffold(promo, name):
    os.makedirs(promo, exist_ok=True)
    files = {
        "hyperframes.json": {"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                             "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
                             "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
                             "media": {"autoProxy": True}, "authoringSkill": "general-video"},
        "meta.json": {"id": name, "name": name},
    }
    for fn, data in files.items():
        p = os.path.join(promo, fn)
        if not os.path.exists(p):
            json.dump(data, open(p, "w"), indent=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("config")
    ap.add_argument("--orientation", choices=["horizontal", "vertical"], default=None,
                    help="default: config 'orientation' or horizontal")
    ap.add_argument("--platform", default=None,
                    help="platform profile, e.g. xiaohongshu:full, douyin, youtube-shorts, xiaohongshu:vertical (3:4); "
                         "default: config 'platform', else horizontal = legacy 1920x1080 layout, vertical = persona "
                         "platforms.default at 9:16")
    ap.add_argument("--out", default=None, help="HyperFrames project dir (default promo_dir / promo_dir_vertical, "
                                                "+ '-<platform>-<orientation>' when a platform is given)")
    ap.add_argument("--clean-master", action="store_true",
                    help="no burned subtitles (cues.json is still written) - for vstudio.export to re-burn per platform")
    ap.add_argument("--no-fonts", action="store_true", help="skip font subsetting (reuse existing assets/fonts)")
    a = ap.parse_args()

    prj = Project(a.config)
    c = prj.cfg
    L = json.load(open(prj.w("layout.json"), encoding="utf-8"))
    D = L["D"]
    spec = a.platform or c.get("platform")
    ori = a.orientation or (None if spec else c.get("orientation", "horizontal"))
    prof, ori = resolve_platform(spec, ori)
    if ori == "vertical":
        src_wh = media.probe(prj.w("body.mp4"))
        src_wh = (src_wh["w"], src_wh["h"])
        lv = (c.get("layout") or {}).get("vertical", {})
        face = tuple(lv["face"]) if lv.get("face") else estimate_face(prj.w("body.mp4"))
        if face and len(face) == 2:
            face = (face[0], face[1], None)
        mw, mh = (int(v) for v in str(c.get("montage", {}).get("scale", "1920:1080")).split(":"))
        g = vertical_geo(prof, src_wh, face, mw / mh)
        g.update({k: v for k, v in lv.items() if k != "face"})
    else:
        g = dict(GEO[ori]); g.update((c.get("layout") or {}).get(ori, {}))
    W, Hc = g["W"], g["H"]
    base = c.get("promo_dir_vertical" if ori == "vertical" else "promo_dir",
                 "promo-vertical" if ori == "vertical" else "promo")
    if a.out:
        base = a.out
    elif spec:
        base = f"{base}-{prof.name}-{prof.orientation}"
    promo = prj.p(base)
    scaffold(promo, os.path.basename(promo))

    brand = P("brand", {}) or {}
    from vstudio.draw import brand as _brand                      # accent / highlight follow vstudio.theme
    _hx = lambda c: "#%02X%02X%02X" % tuple(c)
    _br = _brand()
    ACC, HL = _hx(_br["accent"]), _hx(_br["highlight"])
    INK, GROUND = brand.get("ink", "#ECEEF2"), brand.get("ground", "#0B1020")
    GOLD = brand.get("highlight_alt", "#F4D35E")

    # ---------------- timeline
    BR = body_rate(prj)
    cjk_max = float(P("speed.cjk_max_intelligible", 1.4) or 1.4)
    if str(c.get("language", "zh")).startswith("zh") and BR > cjk_max:
        print(f"note: body at {BR:g}x is above speed.cjk_max_intelligible ({cjk_max:g}x) for Chinese speech - used as set")
    MR = prj.get("rates.montage", P("speed.b_roll", 1.1))
    mcfg = c.get("montage") or {}
    XF = mcfg.get("crossfade", 0.3)
    hold = c.get("hold") or {}
    HOLD_AT, HOLD = (hold.get("at"), hold.get("duration", 2.6)) if hold else (None, 0.0)
    has_m = "montage" in D
    has_o = "outro" in D
    hcfg = c.get("hooks") or {}
    has_h = bool(hcfg.get("items"))
    if has_h and "hooks" not in D:
        raise SystemExit("hooks.items is set but work/layout.json has no hook montage: run tight_cut.py first")
    H = r(D["hooks"]) if has_h else 0.0         # the hook montage opens the video; everything after shifts by H
    B = D["body"] / BR + HOLD
    TZ = mcfg.get("zoom_through", 0.5) if has_m else 0.0
    M = H + B - TZ
    Mdur = D["montage"] / MR if has_m else 0.0
    O = M + Mdur if has_m else H + B
    Odur = D["outro"] / BR if has_o else 0.0
    E = O + Odur
    endc = c.get("end_card") or {}
    END = endc.get("duration", 3.2) if endc else 0.0
    TOTAL = round(E + END, 3)

    bmap = TimeMap.from_list(L["maps"]["body"])
    omap = TimeMap.from_list(L["maps"]["outro"]) if L["maps"].get("outro") else None

    def cut_t(tm, raw):  # raw second -> cut-file second; inside a cut -> start of the next kept span
        return final_time(tm, raw, 1.0)

    def BT(raw):  # raw recording second (body) -> final second (after the hook montage)
        return final_time(bmap, raw, BR, H, HOLD_AT, HOLD)

    def OT(raw):  # raw recording second (outro) -> final second
        return final_time(omap, raw, BR, O)

    TC = cut_t(bmap, HOLD_AT) if HOLD_AT is not None else D["body"]
    T_HOLD = H + TC / BR

    def when(x):  # chapter / named anchor -> final second
        if isinstance(x, (int, float)):
            return BT(x)
        return {"start": H, "hooks": 0.0, "montage": M + TZ, "outro": O, "end": E}[x]

    # ---------------- PiP windows: validate against the card splits / hold / body (raw seconds)
    pips = c.get("pip") or []
    body_spans = [(float(a), float(b)) for a, b in (prj.get("cut.body") or [])]
    try:
        for wmsg in validate_windows(pips, c.get("cards") or [], c.get("split") or [], HOLD_AT, body_spans,
                                     c.get("punch") or []):
            print("warning:", wmsg)
    except ValueError as e:
        raise SystemExit(str(e))

    # ---------------- subtitles (hook captions first: two lines each, 【】 highlight)
    subs = c.get("subtitles") or {}
    cues = []
    hook_items = (L.get("hooks") or []) if has_h else []
    for k, hi in enumerate(hook_items):
        lines = [ln for ln in hi.get("lines") or [] if ln]
        if lines:
            cues.append({"s": r(hi["s"] + 0.05), "e": r(hi["e"] - 0.08), "t": "<br>".join(overlays.cue_html(ln) for ln in lines),
                         "raw": "\n".join(lines), "c": "hook"})
    cues += [{"s": r(BT(s)), "e": r(BT(e) + 0.15), "t": overlays.cue_html(t), "raw": t} for s, e, t in subs.get("body", [])]
    if has_o:
        cues += [{"s": r(OT(s)), "e": r(OT(e) + 0.15), "t": overlays.cue_html(t), "raw": t} for s, e, t in subs.get("outro", [])]
    clip_cues(cues)
    for cu in cues:  # captions must be gone before the zoom-through
        if has_m and cu["s"] < M + TZ < cu["e"] + 1:
            cu["e"] = r(min(cu["e"], M - 0.08))
    # final-timeline cues (subs.Cue dicts, 【】 markup kept) for vstudio.export --cues
    json.dump([{"start": cu["s"], "end": cu["e"], "text": cu["raw"]} for cu in cues],
              open(os.path.join(promo, "cues.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if prof is not None and ori == "vertical":  # a cue that can't fit 2 lines in the caption box at min size
        for cu in cues:
            if cu.get("c") == "hook":
                continue
            fit = PF.fit_text_size(prof, cu["raw"].replace("【", "").replace("】", ""))
            if not fit["fits"]:
                print(f"warning: cue at {cu['s']:.1f}s too long for the {prof.key} caption box: {cu['raw']}")
    said = [(cu["s"], cu["e"], cu["raw"]) for cu in cues]
    for cu in cues:
        cu.pop("raw")
    if a.clean_master:
        cues = []

    # ---------------- montage step labels (label null = previous label continues)
    mlab, t = [], 0.0
    for k, clip in enumerate((mcfg.get("clips") or []) if has_m else []):
        cp = parse_clip(clip, k)                    # [start, end, label] or [source, start, end, label]
        s, e, lab = cp["start"], cp["end"], cp["label"]
        if lab:
            mlab.append({"s": r(M + TZ + t), "n": len(mlab) + 1, "t": lab})
        t += (e - s - XF) / MR
    for x, y in zip(mlab, mlab[1:]):
        x["e"] = y["s"]
    if mlab:
        mlab[-1]["e"] = r(O - 0.2)

    # ---------------- cards (screenshot | video | animated scene), chips, splits, punches, chapters
    img_dir = os.path.join(promo, "assets", "img")
    xdir = os.path.join(promo, "assets", "extras")
    from PIL import Image
    pal = hf.scene_palette(gold=GOLD, ink=INK, ground=GROUND)

    def asset(src):  # media used by pip windows / card videos -> assets/extras/ (unique, ascii-safe name)
        import hashlib
        import re
        stem, ext = os.path.splitext(os.path.basename(src))
        name = f"{re.sub(r'[^A-Za-z0-9._-]', '_', stem)}-{hashlib.sha1(os.path.abspath(src).encode()).hexdigest()[:6]}{ext}"
        link_or_copy(src, os.path.join(xdir, name))
        return f"assets/extras/{name}"

    CARDS, card_inner, scene_js, has_card_video, footage = [], {}, [], False, []
    for i, cd in enumerate(c.get("cards") or []):
        cid = f"c{i + 1}"
        s, e = BT(cd["start"]), BT(cd["end"])
        if cd.get("scene") or cd.get("video"):
            if cd.get("scene"):
                sc = hf.scene_card(f"{cid}x", cd["scene"], s, e, g["CW"], g["CHH"], pal)
                card_inner[cid] = sc["html"]
                scene_js.append(sc["js"])
                what = f"scene:{cd['scene'].get('kind')} {cd['scene'].get('title', '')}".strip()
            else:
                src, _ = screen_crop.clean(prj.p(cd["video"]), cd.get("crop"), prj.work)
                cv = hf.card_video(f"{cid}v", asset(src), s, e - s, float(cd.get("media_start", 0) or 0), cd.get("label"),
                                   g["CW"], g["CHH"], gold=GOLD)
                card_inner[cid] = cv["html"]
                has_card_video = True
                what = "video:" + os.path.basename(cd["video"])
            CARDS.append({"id": cid, "w": g["CW"], "h": g["CHH"], "s": s, "e": e, "scroll": [[s, 0]], "hl": []})
        else:
            src, crop = screen_crop.clean(prj.p(cd["img"]), cd.get("crop"), prj.work)
            dy = crop[1] if crop else 0                   # config rows stay in the ORIGINAL image's pixels
            base = os.path.basename(src)
            link_or_copy(src, os.path.join(img_dir, base))
            iw, ih = Image.open(src).size
            scroll = cd.get("scroll") or [[cd["start"], 0]]
            CARDS.append({"id": cid, "img": f"assets/img/{base}", "w": iw, "h": ih, "s": s, "e": e,
                          "scroll": [[BT(tt), max(0, y - dy)] for tt, y in scroll],
                          "hl": [[BT(tt), y0 - dy, y1 - dy, fr] for tt, y0, y1, fr in cd.get("highlights", [])],
                          **({"box": [BT(cd["box"][0]), cd["box"][1] - dy, cd["box"][2] - dy]} if cd.get("box") else {})})
            what = "img:" + os.path.basename(cd["img"])
        footage.append(("card", cd["start"], cd["end"], s, e, what, cd.get("about"),
                        own_text(cd.get("scene"), cd.get("label"), cd.get("title"))))
    chips = c.get("chips") or {}
    CHIPS = [[BT(tt), txt, int(bool(star[0])) if star else 0] for tt, txt, *star in chips.get("items", [])]
    CHIP_END = BT(chips["end"]) if chips.get("end") is not None else (CARDS[-1]["e"] if CARDS else 0)
    if c.get("split"):
        SPLITS = [[BT(s), BT(e)] for s, e in c["split"]]
    else:  # derive from card windows, bridging short gaps so the face does not bounce
        SPLITS = []
        for cd in CARDS:
            if SPLITS and cd["s"] - SPLITS[-1][1] < 0.8:
                SPLITS[-1][1] = cd["e"]
            else:
                SPLITS.append([cd["s"], cd["e"]])
    PUNCH = [[BT(s), BT(e)] for s, e in c.get("punch", [])]

    # ---------------- PiP windows: screen layer + face tile
    PIPS = []
    for k, w in enumerate(sorted(pips, key=lambda w: float(w["start"]))):
        s, e = BT(w["start"]), BT(w["end"])
        win = {"id": f"pip{k}", "s": r(s), "e": r(e), "tag": w.get("tag"), "fit": w.get("fit"), "pos": w.get("position")}
        if w.get("video"):
            src, _ = screen_crop.clean(prj.p(w["video"]), w.get("crop"), prj.work)
            win.update(video=asset(src), media_start=float(w.get("media_start", 0) or 0))
            what = "video:" + os.path.basename(w["video"]) + (f" @{w.get('media_start', 0)}s" if w.get("media_start") else "")
        else:
            imgs = w.get("images") or ([w["image"]] if w.get("image") else [])
            if isinstance(imgs, str):                      # a folder: its images, sorted by name
                d = prj.p(imgs)
                imgs = [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(screen_crop.IMAGE_EXT)]
            if not imgs:
                raise SystemExit(f"pip[{k}]: needs video, image or images")
            win["images"] = [asset(screen_crop.clean(prj.p(f), w.get("crop"), prj.work)[0]) for f in imgs]
            what = f"images:{len(imgs)}"
        PIPS.append(win)
        footage.append(("pip", w["start"], w["end"], s, e, what, w.get("about"), own_text(w.get("tag"), w.get("label"))))
    PIPG = pip_layout(g) if PIPS else None

    chs = [list(x) for x in c.get("chapters") or []]
    if has_h and hcfg.get("chapter"):          # the hooks get their own chapter (else they sit before the bar)
        chs = [["hooks", hcfg["chapter"]]] + chs
    CHAP = [[when(x[0]), when(chs[i + 1][0]) if i + 1 < len(chs) else TOTAL, x[1]] for i, x in enumerate(chs)]
    BAR0 = 0.0 if (has_h and hcfg.get("chapter")) else H
    if ori == "vertical" and CHAP:  # chapter labels sit at the middle of their span: warn when they collide
        fs, span = g.get("chap_fs", 24), TOTAL - BAR0
        X = lambda t: g["bar_l"] + (t - BAR0) / span * g["bar_w"]
        wid = lambda txt: sum(fs if ord(ch) > 0x2E80 else fs * 0.55 for ch in txt)
        for (s0, e0, l0), (s1, e1, l1) in zip(CHAP, CHAP[1:]):
            if (X(s1) + X(e1)) / 2 - (X(s0) + X(e0)) / 2 < (wid(l0) + wid(l1)) / 2 + 8:
                print(f"warning: chapter labels '{l0}' / '{l1}' overlap on the {W}px bar: merge or shorten them")
    oc = c.get("outro") or {}
    OUTRO_PUNCH = OT(oc["punch_at"]) if has_o and oc.get("punch_at") is not None else None
    if footage:
        print_footage(footage, CHAP, said)

    # ---------------- media
    vdir = os.path.join(promo, "assets", "video")
    for name in ["body"] + (["montage"] if has_m else []) + (["outro"] if has_o else []) + (["hooks"] if has_h else []):
        link_or_copy(prj.w(f"{name}.mp4"), os.path.join(vdir, f"{name}.mp4"))
    if HOLD_AT is not None:
        os.makedirs(img_dir, exist_ok=True)
        media.run(["ffmpeg", "-y", "-ss", f"{TC:.3f}", "-i", prj.w("body.mp4"), "-frames:v", "1", "-q:v", "2",
             os.path.join(img_dir, "freeze.jpg")])
        if hold.get("image"):
            link_or_copy(prj.p(hold["image"]), os.path.join(img_dir, "hold-" + os.path.basename(hold["image"])))

    # ---------------- fonts (Noto Sans SC + STIX Two Text, subset to what this video uses)
    text = all_strings(c) + "".join(chr(i) for i in range(32, 127)) + "「」，。：？！—·×★→↓“”✓✗≈–"
    fdir = os.path.join(promo, "assets", "fonts")
    faces = font_faces(fdir, None if (a.no_fonts and os.path.isdir(fdir)) else text)

    DATA = dict(T_HOLD=T_HOLD, HOLD=HOLD, H=H, M=M, TZ=TZ, O=O, E=E, TOTAL=TOTAL, cues=cues, mlab=mlab,
                CARDS=CARDS, CHIPS=CHIPS, CHIP_END=CHIP_END, SPLITS=SPLITS, PUNCH=PUNCH,
                OUTRO_PUNCH=OUTRO_PUNCH, CW=g["CW"],
                SPLIT=g["split_inset"], SPLIT_X=g["split_x"], SPLIT_Y=g["split_y"],
                SCR_IN=g["scr_in"], SCR_Y=g["scr_y"], SCR_DRIFT=g["scr_drift"],
                FLY=hold.get("fly_from", [380, -150]), HAS_M=has_m, HAS_O=has_o, HAS_END=bool(endc),
                HAS_HOLD=HOLD_AT is not None, INK=INK)
    # progress bar + chapter labels on a scrim, and the cue style: shared HyperFrames snippets
    prog = overlays.hf_progress(CHAP, BAR0, TOTAL, geo=g, font_family="CJK", track_index=8)
    cue_css = overlays.hf_cue_css(g, font_family="CJK", highlight=HL)
    if has_h and ori == "horizontal":        # two-line hook captions: grow upwards from the one-line baseline
        cue_css += f".cue.hook {{ top: auto; bottom: {int(Hc - g['cue_t'] - g['cue_fs'] * 1.2)}px; }}\n"
    extras = dict(card_inner=card_inner, scene_js="".join(scene_js), scene_css=hf.scene_css(pal) if scene_js else "",
                  card_video=has_card_video, pips=PIPS, pip_geo=PIPG,
                  hooks=dict(items=hook_items, punch=float(hcfg.get("punch", 1.08) or 1.0),
                             transition=hcfg.get("transition", "flash")) if has_h else None)

    html = render_html(g, DATA, faces, c, D, BR, MR, Mdur, Odur, END, hold, mcfg, oc, endc,
                       dict(ACC=ACC, HL=HL, INK=INK, GROUND=GROUND, GOLD=GOLD), prog, cue_css, extras)
    open(os.path.join(promo, "index.html"), "w", encoding="utf-8").write(html)
    tl_extra = {}
    if prof is not None:
        tl_extra = {"platform": prof.key, "canvas": [W, Hc], "boxes": g.get("boxes")}
        if PIPG and tl_extra["boxes"] is not None:
            tl_extra["boxes"] = dict(tl_extra["boxes"], pip_tile=PIPG["tile"], pip_frame=PIPG["frame"])
        for wmsg in PF.check_length(prof, TOTAL):
            print("warning:", wmsg)
    json.dump({"orientation": ori, **tl_extra, "total": TOTAL, "hooks": [0.0, H] if has_h else None,
               "body_start": H, "body_end": M + TZ, "montage": [M, O] if has_m else None,
               "outro": [O, E] if has_o else None, "chapters": [[r(s), r(e), lab] for s, e, lab in CHAP],
               "pip": [[w["s"], w["e"], w.get("tag") or ""] for w in PIPS]},
              open(os.path.join(promo, "timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{promo}/index.html  {W}x{Hc}  total {TOTAL:.1f}s · " + (f"hooks→{H:.1f} · " if has_h else "")
          + f"body→{M:.1f} · montage→{O:.1f} · outro→{E:.1f}")
    print("Next: cd into it, `npx hyperframes check`, snapshot mid-transition frames, then scripts/export.sh")


def own_text(*parts):
    """Every string a card / pip window shows by itself (scene title, items, foot, label, pip tag ...), joined:
    an `about` label that is on the footage itself is not a mismatch."""
    out = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            out.append(str(x))
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("kind", "colors"):
                    walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    for p in parts:
        walk(p)
    return " ".join(out)


def about_mismatch(about, said="", chapter="", own=""):
    """True when the creator's `about` label is in none of: the captions of the window, its chapter, the text
    the footage shows itself (scene title / items, pip tag)."""
    return bool(about) and about.lower() not in " ".join((said, chapter, own)).lower()


def print_footage(rows, chap, said):
    """What is on screen vs what is being said: raw time -> chapter -> footage (+ the creator's `about`
    label and the caption at that moment). `!` = the about label is in neither the captions of the window,
    its chapter nor the footage's own text (scene title / items, pip tag): likely the wrong footage here."""
    def chapter_at(t):
        lab = ""
        for s, e, l in chap:
            if s <= t + 1e-3:
                lab = l
        return lab
    print("footage map (raw -> final | chapter | footage | about | said):")
    for kind, ra, rb, fa, fb, what, about, *own in sorted(rows, key=lambda x: x[3]):
        txt = " ".join(t for s, e, t in said if s < fb and e > fa).replace("\n", " ")
        ch = chapter_at(fa)
        flag = "!" if about_mismatch(about, txt, ch, own[0] if own else "") else " "
        print(f" {flag} {kind:4} {float(ra):7.1f}-{float(rb):<7.1f} -> {fa:7.1f}-{fb:<7.1f} | {ch[:10]:10} | {what[:34]:34} | "
              f"{(about or '')[:12]:12} | {txt[:40]}")


def render_html(g, DATA, faces, c, D, BR, MR, Mdur, Odur, END, hold, mcfg, oc, endc, col, prog, cue_css, X=None):
    X = X or {}
    W, Hc = g["W"], g["H"]
    H, M, TZ, O, E, TOTAL = DATA["H"], DATA["M"], DATA["TZ"], DATA["O"], DATA["E"], DATA["TOTAL"]
    T_HOLD, HOLD = DATA["T_HOLD"], DATA["HOLD"]
    TC = (T_HOLD - H) * BR
    B = D["body"] / BR + HOLD
    ff = lambda fam, key, extra: f'@font-face {{ font-family: "{fam}"; src: url("{faces[key][0]}") format("{faces[key][1]}"); {extra} }}'
    want = [("CJK", "cjk-400", "font-weight: 400;"), ("CJK", "cjk-700", "font-weight: 700;"),
            ("Serif", "serif", "font-style: normal;"), ("Serif", "serif-italic", "font-style: italic;")]
    missing = [k for _, k, _ in want if k not in faces]
    if missing:    # fonts not installed (./install.sh): the page falls back to system fonts instead of crashing
        print(f"warning: fonts not found ({', '.join(missing)}); run install.sh for Noto Sans SC / STIX Two Text",
              file=sys.stderr)
    fonts_css = "\n".join(ff(*w) for w in want if w[1] in faces)
    ACC, INK, GROUND, GOLD = col["ACC"], col["INK"], col["GROUND"], col["GOLD"]
    CW, CHH = g["CW"], g["CHH"]

    J = hf.JS
    # effect snippets (vstudio.hf); the page keeps its numbers in `const D`, the snippets reference D.*
    subs = hf.subtitles(J("D.cues"), height=Hc)
    split = hf.split_screen(J("D.SPLITS"), J("D.SPLIT"), J("D.SPLIT_X"), J("D.SPLIT_Y"))
    punch = hf.punch_in(J("D.PUNCH"))
    inner = X.get("card_inner") or {}
    cards = hf.screenshot_cards([dict(cd, inner=inner[cd["id"]]) if cd["id"] in inner else cd for cd in DATA["CARDS"]],
                                CW, CHH, g["card_l"], g["card_t"], ACC, cards_js=J("D.CARDS"), card_w_js=J("D.CW"))
    cvid = hf.card_video("x", "", 0, 1, gold=GOLD) if X.get("card_video") else hf._out()
    pip = hf._out()
    pip["overlay"] = ""
    if X.get("pips"):
        pg = X["pip_geo"]
        pip = hf.pip_windows(X["pips"], pg["clip"], pg["scale"], pg["x"], pg["y"], pg["tile"], pg["frame"],
                             gold=GOLD, tile_radius=pg["tile_radius"])
    hk = X.get("hooks")
    hook_html, hook_js, flash = "", "", hf._out()
    if hk:
        hook_html = ('<div id="hookwrap" class="wrap"><div id="hook-zoom" class="wrap">'
                     f'<video id="hooks" class="full" src="assets/video/hooks.mp4" playsinline data-has-audio="true" data-start="0" '
                     f'data-duration="{r(H)}" data-track-index="2" data-volume="1"></video></div></div>')
        hook_js = 'tl.set("#hook-zoom", { scale: 1 }, 0);\n'
        for k, it in enumerate(hk["items"]):          # alternate framing per hook: a jump cut, not a jump
            if k and hk["punch"] and hk["punch"] != 1.0:
                hook_js += f'tl.set("#hook-zoom", {{ scale: {hk["punch"] if k % 2 else 1} }}, {r(it["s"])});\n'
        if hk["transition"] == "flash":
            flash = hf.flash(H)
        elif hk["transition"] == "punch":
            hook_js += (f'tl.fromTo("#face-zoom", {{ scale: 1.12 }}, {{ scale: 1, duration: 0.5, ease: "power2.out", '
                        f'immediateRender: false }}, {r(H)});\n')
    chips = hf.chips(DATA["CHIPS"], J("D.CHIP_END"), g["chips_l"], g["chips_t"], g["chips_w"], INK, GOLD, items_js=J("D.CHIPS"))
    himg = "assets/img/hold-" + os.path.basename(hold["image"]) if hold.get("image") else ""
    freeze = hf.freeze_hold(J("D.T_HOLD"), J("D.HOLD"), J("D.FLY"), hold.get("label", ""), himg,
                            g["pz_l"], g["pz_t"], g["pz_w"], ACC, GOLD, clip=(T_HOLD, HOLD))
    screen = hf.framed_screen("assets/video/montage.mp4", M, Mdur + TZ, J("D.O"), MR,
                              g["scr_l"], g["scr_t"], g["scr_w"], g["scr_h"])
    zoom = hf.zoom_through(J("D.M"), J("D.O"), J("D.SCR_IN"), J("D.SCR_Y"), J("D.SCR_DRIFT"))
    steps = hf.step_labels(DATA["mlab"], M + TZ, Mdur, g["mlabel_l"], g["mlabel_t"], INK, GOLD, labels_js=J("D.mlab"))
    mtag = hf.tag(mcfg.get("tag"), M + TZ, Mdur, J("D.M + 0.8"), g["mtag_css"])
    mbadge = hf.badge(mcfg.get("badge"), M + TZ, Mdur, J("D.M + 0.6"), g["mbadge_l"], g["mbadge_t"], ACC)
    mtitle = hf.title_card(mcfg.get("title"), M + TZ, J("D.M + D.TZ"), mcfg.get("title_sub"), g["mtitle_t"], g["mtitle_fs"], GOLD)
    ow = hf.enter_zoom("#ow", J("D.O"))
    opunch = hf.punch_at("#ow", J("D.OUTRO_PUNCH"))
    stamp = hf.stamp(oc.get("stamp"), O, Odur, J("D.OUTRO_PUNCH + 0.9"), g["stamp_l"], g["stamp_t"], ACC)
    end = hf.end_card(E, END, endc.get("kicker", ""), endc.get("main", ""), endc.get("sub", ""), J("D.E"), g["end_fs"], GOLD)
    I = hf.indent

    if DATA["HAS_HOLD"]:
        body_html = hf.freeze_clips("assets/video/body.mp4", "assets/img/freeze.jpg", H, TC, HOLD, D["body"], BR)
        pz_html = freeze["html"]
    else:
        body_html = f'<video id="body" class="full" src="assets/video/body.mp4" playsinline data-has-audio="true" data-start="{r(H)}" data-duration="{r(B)}" data-playback-rate="{BR}" data-track-index="2" data-volume="1"></video>'
        pz_html = ""

    m_html = ""
    if DATA["HAS_M"]:
        m_html = "\n  ".join(x for x in (screen["html"], steps["html"], mtag["html"], mbadge["html"], mtitle["html"]) if x)

    o_html = ""
    if DATA["HAS_O"]:
        o_html = f'<div id="ow" class="wrap"><video id="outro" class="full" src="assets/video/outro.mp4" playsinline data-has-audio="true" data-start="{r(O)}" data-duration="{r(Odur)}" data-playback-rate="{BR}" data-track-index="2" data-volume="1"></video></div>'
        if stamp["html"]:
            o_html += "\n  " + stamp["html"]
    end_html = end["html"] if DATA["HAS_END"] else ""

    # a card with a playing clip: the clip is the timed element, so #cards must be a plain container
    # (data-start on both = HyperFrames video_nested_in_timed_element)
    cards_attrs = ('class="full"' if X.get("card_video")
                   else f'class="clip full" data-start="{r(H)}" data-duration="{r(B)}" data-track-index="4"')
    css = (hf.grid_backdrop_css()
           + f".wrap {{ position: absolute; inset: 0; width: {W}px; height: {Hc}px; transform-origin: 50% 40%; }}\n"
           + split["css"] + screen["css"] + ow["css"] + cards["css"] + chips["css"] + subs["css"]
           + cue_css + prog["css"] + steps["css"] + freeze["css"] + mbadge["css"] + mtitle["css"] + mtag["css"]
           + stamp["css"] + end["css"] + pip["css"] + cvid["css"] + X.get("scene_css", "") + flash["css"]
           + g.get("extra_css", ""))
    js = ("// subtitles\n" + subs["js"]
          + ("\n// hook montage: alternating framing, transition into the body\n" + hook_js + flash["js"] if hk else "")
          + "\n// talking head: split-screen moves (clip + slide) and punch-ins\n" + split["js"] + punch["js"]
          + ("\n// picture-in-picture: screen layer + face tile\n" + pip["js"] if X.get("pips") else "")
          + "\n// cards: 3D slide-in, scroll, highlights, box\n" + cards["js"] + chips["js"]
          + ("// animated scene cards\n" + X["scene_js"] if X.get("scene_js") else "")
          + "\n// prompt hold: dim, fly the prompt out of the screenshot card, hold, fly back\n"
          + "if (D.HAS_HOLD) {\n" + I(freeze["js"], 2) + "}\n"
          + "if (D.HAS_M) {\n"
          + "  // body -> montage: zoom through into the framed screen (body2 is still playing underneath)\n"
          + I(zoom["js"] + steps["js"] + mtag["js"] + mbadge["js"] + mtitle["js"], 2)
          + "  // montage -> outro: frame shrinks away (montage clip runs TZ past O so it is alive while it leaves)\n"
          + I(screen["js"], 2) + "}\n"
          + "if (D.HAS_O) {\n" + I(ow["js"], 2)
          + "  if (D.OUTRO_PUNCH !== null) {\n" + I(opunch["js"] + stamp["js"], 4) + "  }\n}\n"
          + "if (D.HAS_END) {\n" + I(end["js"], 2) + "}\n")

    return f'''<!doctype html>
<html lang="{c.get("language", "zh")}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={W}, height={Hc}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
{fonts_css}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {W}px; height: {Hc}px; overflow: hidden; background: {GROUND}; }}
#root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {GROUND}; font-family: "CJK", sans-serif; }}
.full {{ position: absolute; inset: 0; width: {W}px; height: {Hc}px; }}
video.full, img.full {{ object-fit: cover; object-position: {g["face_pos"]}; }}
#plate {{ background: radial-gradient(ellipse 70% 60% at 50% 42%, #16203d 0%, {GROUND} 62%, #070a14 100%); }}
{css}</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="{W}" data-height="{Hc}" data-duration="{TOTAL}">
  <div id="plate" class="full clip" data-start="0" data-duration="{TOTAL}" data-track-index="0"></div>

  {hook_html}
  {pip["html"]}
  <!-- body: talking head (split-screen + punch-ins). hooks, body + freeze + body2 share track 2 back to back -->
  <div id="face" class="wrap"><div id="face-zoom" class="wrap">
    {body_html}
  </div></div>
  <div id="cards" {cards_attrs} style="pointer-events:none">
    {cards["html"]}
    {chips["html"]}
  </div>
  {pip["overlay"]}
  {pz_html}

  <!-- montage: highlights in a framed screen; own track (3) because it overlaps body2 during the zoom-through -->
  {m_html}

  <!-- outro + end card -->
  {o_html}
  {end_html}

  {flash["html"]}
  {hf.subtitles_html(0, E)}
  {prog["html"]}
</div>
<script>
(function () {{
const D = {json.dumps(DATA, ensure_ascii=False)};
{hf.prelude()}
{js}
// progress bar + chapters on a scrim (vstudio.overlays.hf_progress)
{prog["js"]}
window.__timelines = window.__timelines || {{}};
window.__timelines["main"] = tl;
}})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
