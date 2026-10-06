#!/usr/bin/env python3
"""Step 8c: vertical slices (3:4 / 9:16) from the horizontal recording, per platform target.

For every vertical target canvas (config targets / platform, e.g. ["xiaohongshu:vertical", "douyin"]):
  1. a caption-free vertical MASTER of the whole cut (work/vertical/<W>x<H>/master.mp4): every timeline item
     is re-composed from the SOURCE recording (not from the 16:9 render) in a vertical layout, chapter cards /
     hook / 记笔记 panels are re-drawn for the canvas, audio is taken from <out>/final.mp4 (same timeline);
  2. per episode (config.episodes, else the whole cut) and per target, `vstudio.export.export_one`: captions
     from work/cues.json re-laid into the profile's caption box (bigger font, <= max chars per line, long cues
     split; no caption starts / ends on a filler, ``vstudio.proofread.fix_filler_edges``; none while a hook's
     lines are on screen - vertical.hook_captions: hide (default) | show), loudness to the profile target, length / title / description checks, cover fitted to the
     profile's cover size, post stub -> <out>/vertical/ep<N>/<platform>-<orientation>.mp4 (+ .cover.jpg,
     .post.md, .crop.json) and <out>/vertical/manifest.json (sizes, loudness, warnings; merged across runs, so
     a second `--targets youtube-shorts:vertical` run adds to the 小红书 entries instead of replacing them).

Layout per item (config.vertical.mode, per-episode episodes.items[].vertical, per source window
vertical.segments [{"src": [t0, t1], "mode": ..}], or --mode): split (default: speaker cam on top, screen
below; no speaker region / no face -> title band with the current chapter), screen (content-following
crop of the shared page), speaker, pad-blur. See _vertical.py for the tracking details.

Privacy: the screen crop never leaves the item's crop (geometry crop span: shared page minus browser
chrome / bookmark bar, or the code-zoom box); the speaker crop never leaves vertical.speaker.region;
vertical.exclude rects (participant tiles, name tags) are painted out of the source first. Episode covers take
their screenshot from <out>/final.mp4 (the 16:9 render); with render.audio_only (no picture there) or
vertical.cover_from_source they take it from the SOURCE instead, through the same guards: the frame at that
moment, exclude rects painted out, cut to the timeline item's crop. cards.number [i, n] overrides the
"i / n" on the chapter card (batch jobs: the job's place in the series).

Usage: python3 make_vertical.py work/config.py [--targets xiaohongshu:vertical,xiaohongshu:full]
       [--mode split|screen|speaker|pad-blur] [--episodes 1,2] [--master-only] [--preset veryfast]
       [--reuse-masters]   (keep vertical/<WxH>/master.mp4 + plan.json from an earlier run: captions / cover /
                            post re-export only - the batch uses it for in-review caption edits)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import json
import os
import subprocess

import cv2
import numpy as np

import _lfc
import _vertical as V
import make_cover as MC
from vstudio import draw, media, overlays
from vstudio.config import persona


def extra(ap):
    ap.add_argument("--targets", "--platform", dest="targets", default=None,
                    help="comma list of targets; vertical ones are rendered (default: config targets/platform, "
                         "else <persona platforms.default>:vertical)")
    ap.add_argument("--mode", choices=V.MODES, default=None, help="layout for every item (overrides config)")
    ap.add_argument("--episodes", default=None, help="comma list of episode numbers to export (default all)")
    ap.add_argument("--master-only", action="store_true", help="render the vertical masters, skip exports")
    ap.add_argument("--preset", default="veryfast", help="x264 preset for the intermediate master")
    ap.add_argument("--reuse-masters", action="store_true",
                    help="keep an existing vertical/<WxH>/master.mp4 + plan.json (caption / cover / post re-export)")


cfg, args = _lfc.load(description=__doc__, extra=extra)
profs, explicit = _lfc.targets(cfg, args.targets)
vprofs = _lfc.vertical(profs)
if not vprofs:
    from vstudio import platform as PF
    d = (persona().get("platforms") or {}).get("default") or "xiaohongshu"
    vprofs = [PF.profile(d, "vertical")]
    print(f"no vertical target in {[p.key for p in profs]}; using {vprofs[0].key}")
FINAL = os.path.join(cfg.out, "final.mp4")
if not os.path.exists(FINAL):
    sys.exit("render.py first: the vertical masters take their audio from <out>/final.mp4")
SRC = cfg.src
REC = cfg.path_of(cfg.get("demo.rec")) if cfg.get("demo.enabled") else None
FPS = cfg.get("render.fps", 24)
VC = cfg.get("vertical", {}) or {}
SPK = VC.get("speaker") or {}
SPK_REGION = SPK.get("region")
EXCLUDE = [list(r) for r in (VC.get("exclude") or [])]
SCREEN_O = dict(V.SCREEN_DEFAULTS, **(VC.get("screen") or {}))
SPLIT = dict(V.SPLIT_DEFAULTS, **(VC.get("split") or {}))
PAL = _lfc.palette(cfg)
T = _lfc.theme(cfg)
timeline = _lfc.load_json("timeline.json")
tm = _lfc.timemap(timeline)
total = _lfc.total_duration(timeline)
eps_all = _lfc.episode_ranges(cfg, timeline)
info = media.probe(SRC)
SW, SH = info["display_w"], info["display_h"]
zooms = _lfc.load_json("zoom_windows.json") if os.path.exists("zoom_windows.json") else []
os.makedirs("vertical", exist_ok=True)

# chapter per item, final windows, frame counts
chap, cur, n_cards = [], (0, ""), sum(1 for it in timeline if it["kind"] == "card")
for it in timeline:
    if it["kind"] == "card":
        cur = (cur[0] + 1, it["title"])
    chap.append(cur)
nfr = [g[0] for g in _lfc.segment_grid(timeline, FPS)]      # same frame grid as render.py


def mode_for(k, it):
    mid = (it["t0"] + it["t1"]) / 2
    for s in VC.get("segments") or []:
        if s["src"][0] <= mid < s["src"][1]:
            return s["mode"]
    for ep in eps_all:
        if ep.get("vertical") and ep["a"] <= it["final_t0"] < (ep["b"] or total + 1):
            return ep["vertical"]
    if it.get("demo_slice") is not None:
        return "screen" if (args.mode or VC.get("mode", "split")) in ("split", "speaker") else (args.mode or VC.get("mode"))
    return args.mode or VC.get("mode", "split")


def series_label():
    return VC.get("series") or cfg.get("episodes.series") or cfg.get("publish.title") or ""


def zoom_center(it):
    for z in zooms:
        if z["t0"] <= it["t0"] and it["t1"] <= z["t1"] and it["crop"] and it["crop"][0] == cfg.get("zoom.box", [736, 336])[0]:
            return (z["cx"], z["cy"])
    return None


def region_of(it):
    if it.get("demo_slice") is not None:
        p = media.probe(REC)
        return [0, 0, p["display_w"], p["display_h"]]
    cw, ch, cx, cy = it["crop"]
    return [cx, cy, cx + cw, cy + ch]


# ------------------------------------------------------------------------------------------- speaker plans
speaker_plans, speaker_info = {}, {}
if SPK_REGION:
    det = V.make_detector(SPK.get("detector", "mediapipe"), SPK.get("color"))


def speaker_band_for(L, key):
    """Decide per canvas whether the top band is the speaker (face found often enough) or a title band."""
    if not SPK_REGION:
        return "title", {}
    need = [k for k, it in enumerate(timeline) if it["kind"] != "card" and it.get("demo_slice") is None
            and mode_for(k, it) in ("split", "speaker")]
    if not need:
        return "title", {}
    hits, frames_n = 0.0, 0
    for k in need:
        it = timeline[k]
        bx = V.boxes(L, "split" if mode_for(k, it) == "split" else "speaker", "speaker",
                     SPLIT["speaker_frac"], SPLIT["band_frac"], SPLIT["screen_to"])["speaker"]
        tmp = f"vertical/spk_{k:03d}.mp4"
        rects, inf = V.plan_speaker(SRC, it["t0"], it["t1"], it["speed"], FPS, SPK_REGION, bx, tmp, det,
                                    zoom=SPK.get("zoom", 1.0), min_hit=SPK.get("min_hit", 0.3))
        speaker_plans[(key, k)] = rects
        speaker_info[(key, k)] = inf
        hits += (inf.get("hit_rate") or 0.0) * nfr[k]
        frames_n += nfr[k]
    rate = hits / max(1, frames_n)
    band = "speaker" if rate >= SPK.get("min_hit", 0.3) else "title"
    return band, dict(speaker_hit_rate=round(rate, 3))


# ------------------------------------------------------------------------------------------- master per canvas
def vertical_panels(L, band):
    """记笔记 panels re-drawn for the canvas: <= 62 % of the safe width, right-aligned in the safe box, at the
    top of the screen area (below the speaker / title band), scaled to stay above the caption box."""
    sx0, sy0, sx1, sy1 = L["safe"]
    top = V.boxes(L, "split", band, SPLIT["speaker_frac"], SPLIT["band_frac"], SPLIT["screen_to"])["screen"][1]
    pw = int(min(620, (sx1 - sx0) * 0.62))
    out = []
    for p in cfg.get("panels", []):
        rows = [part for ln in p["lines"] for part in ln.split("\n")]
        im = overlays.notes_panel(p["title"], rows, theme=T, width=pw, tag=cfg.get("panel_tag", "记笔记"))
        room = (L["caption"][1] - 20) - (top + 16)
        if im.height > room:
            im = im.resize((int(im.width * room / im.height), room))
        span = tm.map_span(p["src"][0], p["src"][1], tag="body")
        if span:
            out.append(dict(img=np.asarray(im), x=sx1 - im.width, a=span[0], b=span[1]))
    return out


def render_master(group):
    W, H = group[0].w, group[0].h
    key = f"{W}x{H}"
    L = V.layout(group, gap=SPLIT["gap"])
    d = os.path.join("vertical", key)
    os.makedirs(d, exist_ok=True)
    band, binfo = speaker_band_for(L, key)
    margin = L["safe"][0] + 24
    panels = vertical_panels(L, band)
    hook_lines = cfg.get("hook.lines") or []
    master = os.path.join(d, "master.mp4")
    enc = [media.ffmpeg_bin(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", FINAL, "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", args.preset, "-crf", str(VC.get("crf", 16)), "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-t", f"{sum(nfr) / FPS:.6f}", "-movflags", "+faststart", master]
    pe = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    report, bands, privacy_hits, ov_rects = [], {}, 0, []
    ground = np.zeros((H, W, 3), np.uint8)
    ground[:] = PAL["bg"][::-1]
    for k, it in enumerate(timeline):
        n = nfr[k]
        if n <= 0:
            continue
        if it["kind"] == "card":
            ci, cn = cfg.get("cards.number") or (chap[k][0], n_cards)
            card = overlays.chapter_card(ci, cn, it["title"], size=(W, H), theme=T, ground=PAL["bg"])
            img = V.pil_bgr(card)
            for _ in range(n):
                pe.stdin.write(img.tobytes())
            report.append(dict(item=k, kind="card", frames=n))
            continue
        mode = mode_for(k, it)
        b = band if mode in ("split", "speaker") else "title"
        bx = V.boxes(L, mode, b, SPLIT["speaker_frac"], SPLIT["band_frac"], SPLIT["screen_to"])
        src = REC if it.get("demo_slice") is not None else SRC
        t0 = it["demo_slice"][0] if it.get("demo_slice") is not None else it["t0"]
        t1 = t0 + (it["t1"] - it["t0"])
        region = region_of(it)
        still = None
        if it["kind"] == "freeze":
            media.grab_frame(SRC, it["still_at"], "vertical/still.png")
            still = V.paint_out(cv2.imread("vertical/still.png"), EXCLUDE)
        prects = speaker_plans.get((key, k)) if "speaker" in bx else None
        if "speaker" in bx and prects is None:          # no plan for this item -> title band
            bx["band"] = bx.pop("speaker")
        base = ground.copy()
        if "band" in bx:
            x0, y0, x1, y1 = bx["band"]
            hk = (it.get("hook_lines") or hook_lines) if it.get("hook") else None
            ck = (x1 - x0, y1 - y0, chap[k], bool(hk))
            if ck not in bands:
                bands[ck] = V.title_band((x1 - x0, y1 - y0), series_label(), chap[k][1] or cfg.get("publish.title", ""),
                                         PAL, margin, hook=hk)
            base[y0:y1, x0:x1] = bands[ck]
        rec = dict(item=k, kind=it["kind"], mode=mode, band=b if "band" in bx or "speaker" in bx else None,
                   frames=n, region=region, box=list(bx["screen"]) if "screen" in bx else None)
        srects = None
        if "screen" in bx and mode != "pad-blur":
            srects, st = V.analyse_screen(src, t0, t1, it["speed"], FPS, n, region, bx["screen"],
                                          zoom_center(it), still, SCREEN_O, vis_h=V.visible_h(L, bx["screen"]))
            rec["screen"] = st
            dim = V.scrim(L, bx["screen"], st["draw_h"], SPLIT["scrim"]) if bx["screen"][3] > L["content"][3] else None
        if (key, k) in speaker_info:
            rec["speaker"] = speaker_info[(key, k)]
        hook_ov = None
        hl = (it.get("hook_lines") or hook_lines) if it.get("hook") else None
        if hl and "band" not in bx:
            hb = V.hook_box(hl, L["safe"][2] - L["safe"][0] - 40, PAL)
            hook_ov = (np.asarray(hb), (W - hb.width) // 2, L["content"][1] + 24)
            ov_rects.append(dict(a=it["final_t0"], b=it["final_t0"] + n / FPS,
                                 rect=[hook_ov[1], hook_ov[2], hook_ov[1] + hb.width, hook_ov[2] + hb.height]))
        panel_y = (bx["screen"][1] if "screen" in bx and len(bx) > 1 else L["content"][1]) + 16
        for p in panels:                                # overlay rects for the output popup scan (never a popup)
            a_, b_ = max(p["a"], it["final_t0"]), min(p["b"], it["final_t0"] + n / FPS)
            if b_ > a_:
                h_, w_ = p["img"].shape[:2]
                ov_rects.append(dict(a=a_, b=b_, rect=[p["x"], panel_y, p["x"] + w_, panel_y + h_]))
        last = None
        pops = (rec.get("screen") or {}).get("popups") or []
        keep_clean = {p["clean"] for p in pops if p.get("masked") and not p.get("future")}
        clean = {}
        for p in pops:                                  # popups open from the clip start: decode the clean page
            if p.get("masked") and p.get("future"):     # (the frame after they close) before the loop
                ts = t0 + p["clean"] / FPS * it["speed"]
                g = V.frames(V.decode_cmd(src, ts, min(t1, ts + 0.5), it["speed"], FPS), SW if src == SRC else region[2],
                             SH if src == SRC else region[3])
                f_ = next(g, None)
                g.close()
                if f_ is not None:
                    clean[p["clean"]] = V.paint_out(f_, EXCLUDE).copy()
        gen = V.frames(V.decode_cmd(src, t0, t1, it["speed"], FPS), SW if src == SRC else region[2],
                       SH if src == SRC else region[3])
        for i in range(n):
            fr = next(gen, None)
            fr = last if fr is None else V.paint_out(fr, EXCLUDE)
            if fr is None:
                fr = still if still is not None else np.zeros((SH, SW, 3), np.uint8)
            if pops:                                    # transient editor popups: the page as it was before
                fr = V.mask_popups(fr, i, pops, clean)
            if i in keep_clean:                         # kept AFTER masking: a clean frame inside another masked
                clean[i] = fr.copy()                    # popup (one open from the clip start) is clean too
            last = fr
            img = base.copy()
            scr = still if still is not None else fr
            if "screen" in bx:
                x0, y0, x1, y1 = bx["screen"]
                if mode == "pad-blur":
                    img[y0:y1, x0:x1] = V.pad_blur(scr, region, (x1 - x0, y1 - y0))
                else:
                    r = srects[min(i, len(srects) - 1)]
                    privacy_hits += V.overlaps(r, EXCLUDE)
                    dh, dy = st["draw_h"], st.get("draw_y", 0)
                    tile = V.warp(scr, r, (x1 - x0, dh), SCREEN_O.get("sharpen", 0.0))
                    if dim is not None:
                        tile = (tile * dim[:, None, None]).astype(np.uint8)
                    img[y0 + dy:y0 + dy + dh, x0:x1] = tile
            if "speaker" in bx:
                x0, y0, x1, y1 = bx["speaker"]
                r = prects[min(i, len(prects) - 1)]
                img[y0:y1, x0:x1] = V.warp(fr, r, (x1 - x0, y1 - y0))
                if "screen" in bx:
                    img[y1:bx["screen"][1]] = PAL["bg"][::-1]
            if hook_ov is not None:
                draw.alpha_paste(img, hook_ov[0], hook_ov[1:], bgr=True)
            t = it["final_t0"] + i / FPS
            for p in panels:
                if p["a"] <= t < p["b"]:
                    draw.alpha_paste(img, p["img"], (p["x"], panel_y), bgr=True)
            pe.stdin.write(np.ascontiguousarray(img).tobytes())
        gen.close()
        report.append(rec)
        if k % 6 == 0:
            print(f"  [{key}] item {k + 1}/{len(timeline)} {mode}", flush=True)
    pe.stdin.close()
    err = pe.stderr.read().decode("utf-8", "replace")
    if pe.wait() != 0:
        sys.exit(f"vertical master encode failed:\n{err[-1500:]}")
    plan = dict(canvas=[W, H], targets=[p.key for p in group], layout=L, band=band, **binfo,
                exclude=EXCLUDE, privacy_overlap_frames=int(privacy_hits), items=report, overlays=ov_rects)
    output_scans(master, plan)
    _lfc.dump_json(plan, os.path.join(d, "plan.json"))
    print(f"{master}  band={band} {binfo}  privacy_overlap_frames={privacy_hits}")
    return master, plan


def output_scans(master, plan, only_missing=False):
    """QC scans of a rendered master, into plan: editor popups still visible (``visible_popups``, 2 fps) and
    persistent UI panels - a menu / toolbar left open over whole items (``static_overlays``). A scan error is
    recorded (``*_error``), never fails the render. only_missing: a reused master, scans its plan lacks."""
    L = plan.get("layout") or {}
    segs = V.output_segments(plan, timeline, FPS, SPLIT)
    cap = None if SPLIT["screen_to"] == "caption" else (L.get("caption") or [0, None])[1]
    ov = plan.get("overlays") or []
    scans = []
    if (SCREEN_O.get("popups") or "off") != "off":     # QC: popups still visible in what was rendered (2 fps)
        scans.append(("visible_popups", lambda: V.scan_popups(master, segs, ov, caption_top=cap, o=SCREEN_O,
                                                              scan=cfg.get("vertical.popup_scan") or None)))
    osc = cfg.get("vertical.overlay_scan")
    if osc is not False:                               # QC: toolbars / menus that stay open (static overlays)
        scans.append(("static_overlays", lambda: V.scan_static_overlays(master, segs, ov, caption_top=cap,
                                                                        scan=osc if isinstance(osc, dict) else None)))
    done = False
    for key, fn in scans:
        if only_missing and key in plan:
            continue
        try:
            plan[key] = fn()
            plan.pop(f"{key}_error", None)
        except Exception as e:  # noqa: BLE001  (a QC scan never fails the render)
            plan[f"{key}_error"] = f"{type(e).__name__}: {e}"
        done = True
    return done


def reuse_master(group):
    """--reuse-masters: the caption-free master of this canvas from an earlier run (the caller guarantees it
    matches the timeline / layout), else None."""
    if not args.reuse_masters:
        return None
    d = os.path.join("vertical", f"{group[0].w}x{group[0].h}")
    master, plan = os.path.join(d, "master.mp4"), os.path.join(d, "plan.json")
    if not (os.path.exists(master) and os.path.exists(plan)):
        return None
    print(f"{master}  reused (--reuse-masters)")
    pl = _lfc.load_json(plan)
    if output_scans(master, pl, only_missing=True):    # a master from before a QC scan existed: scan it now
        _lfc.dump_json(pl, plan)
    return master, pl


# ------------------------------------------------------------------------------------------- exports
def source_shot(t_final, png):
    """Cover screenshot straight from the source at final time t_final (the clip item playing then, else the next
    one): exclude rects painted out, cut to that item's crop - nothing outside the screen region can show."""
    from PIL import Image
    clips = [it for it in timeline if it["kind"] != "card" and it.get("demo_slice") is None and it.get("crop")]
    if not clips:
        sys.exit("no source clip with a crop for the cover screenshot")
    it = next((c for c in clips if c["final_t0"] <= t_final < c["final_t0"] + (c["t1"] - c["t0"]) / c["speed"]), None) \
        or next((c for c in clips if c["final_t0"] >= t_final), clips[-1])
    ts = it["still_at"] if it["kind"] == "freeze" else \
        min(it["t1"] - 0.05, it["t0"] + max(0.0, t_final - it["final_t0"]) * it["speed"])
    media.grab_frame(SRC, ts, png)
    fr = V.paint_out(cv2.imread(png), EXCLUDE)
    cw, ch, cx, cy = [int(v) for v in it["crop"]]
    return Image.fromarray(cv2.cvtColor(fr[cy:cy + ch, cx:cx + cw], cv2.COLOR_BGR2RGB))


def episode_covers(ep, N, sizes, ddir):
    t_shot = _lfc.map_src(timeline, ep["shot_src"], "fwd") if ep.get("shot_src") is not None else \
        ep["a"] + min(60.0, ((ep["b"] or total) - ep["a"]) / 2)
    if cfg.get("render.audio_only") or VC.get("cover_from_source"):
        shot = source_shot(t_shot, "vertical/ep_shot.png")
    else:
        shot = MC.shot_at(cfg, t_shot, "vertical/ep_shot.png")
    paths = []
    for name, size in sizes.items():
        p = os.path.join(ddir, f"cover_{name}.png")
        MC.episode_cover(cfg, ep, shot, N, size).save(p)
        paths.append(p)
    return paths


def hook_windows():
    """Final-time windows [(a, b)] of the hook items that show their lines (title band or hook box)."""
    out = []
    for it in timeline:
        if it.get("hook") and it["kind"] != "card" and ((it.get("hook_lines") or cfg.get("hook.lines"))):
            a = float(it["final_t0"])
            out.append((a, a + (float(it["t1"]) - float(it["t0"])) / float(it["speed"])))
    return out


def main():
    from vstudio import export as X
    from vstudio.subs import Cue
    groups = {}
    for p in vprofs:
        groups.setdefault((p.w, p.h), []).append(p)
    masters = {wh: reuse_master(g) or render_master(g) for wh, g in groups.items()}
    if args.master_only:
        return
    cues = [Cue.from_dict(c) for c in _lfc.load_json("cues.json")] if os.path.exists("cues.json") else []
    if not cues:
        print("WARN no work/cues.json (run build_subs.py): vertical slices without captions")
    eps = eps_all or [{"n": 1, "a": 0.0, "b": None, "title": cfg.get("publish.title", "")}]
    pick = {int(x) for x in args.episodes.split(",")} if args.episodes else None
    cards = _lfc.chapters_from_timeline(timeline)
    short = cfg.get("publish.short_labels", {}) or {}
    sizes = {"3x4": (1080, 1440)}
    sizes.update(MC.extra_cover_sizes(vprofs, base=("3x4", "16x9")))
    root = os.path.join(cfg.out, "vertical")
    manifest = dict(targets=[p.key for p in vprofs], masters={f"{w}x{h}": m[0] for (w, h), m in masters.items()},
                    episodes=[], warnings=[])
    cap_profs = {p.key: p for p in vprofs}       # vstudio.platform.fit_text_size fits the caption box height itself
    from vstudio import platform as PF
    from vstudio import proofread as PRF
    hooks = hook_windows()
    if hooks and VC.get("hook_captions", "hide") == "hide":   # the hook's lines are on screen: no second copy
        cues = [c for c in cues if not any(a - 0.05 <= (c.start + c.end) / 2 < b for a, b in hooks)]
    relaid, edge_log = {}, {}
    for p in vprofs:
        rc = [c.to_dict() for c in V.relayout_cues(cues, cap_profs[p.key])]
        rc, edge_log[p.key] = PRF.fix_filler_edges(rc, fits=lambda t, _p=cap_profs[p.key]: PF.fit_text_size(_p, t)["fits"])
        relaid[p.key] = [Cue.from_dict(c) for c in rc]
    for p in vprofs:
        _lfc.dump_json([c.to_dict() for c in relaid[p.key]], f"vertical/cues.{p.name}-{p.orientation}.json")
        _lfc.dump_json(edge_log[p.key], f"vertical/filler_edges.{p.name}-{p.orientation}.json")
    for ep in eps:
        if pick and ep["n"] not in pick:
            continue
        a, b = ep["a"], ep["b"] or total
        ddir = os.path.join(root, f"ep{ep['n']}")
        os.makedirs(ddir, exist_ok=True)
        covers = episode_covers(ep, len(eps), sizes, ddir)
        chapters = [(t - a, short.get(title, title)) for t, title in cards if a <= t < b]
        post = dict(title=ep.get("title") or cfg.get("publish.title", ""), body=ep.get("body") or cfg.get("publish.body", ""),
                    chapters=chapters or None, tags=cfg.get("publish.tags", []))
        entries = []
        for p in vprofs:
            master = masters[(p.w, p.h)][0]
            print(f"[export] ep{ep['n']} {p.key} {a:.1f}-{b:.1f}s")
            e = X.export_one(master, cap_profs[p.key], ddir, cues=relaid[p.key], covers=covers, post=post, start=a, dur=b - a,
                             preset=cfg.get("vertical.export_preset", "medium"))
            entries.append(e)
            manifest["warnings"] += [f"ep{ep['n']} {p.key}: {w}" for w in e["warnings"]]
        manifest["episodes"].append(dict(n=ep["n"], a=round(a, 3), b=round(b, 3), dir=os.path.relpath(ddir, cfg.out),
                                         exports=entries))
        ep_man = os.path.join(ddir, "manifest.json")
        old = _lfc.load_json(ep_man) if os.path.exists(ep_man) else []
        _lfc.dump_json(V.merge_exports(old, entries), ep_man)
    man_path = os.path.join(root, "manifest.json")
    manifest = V.merge_manifest(_lfc.load_json(man_path) if os.path.exists(man_path) else None, manifest)
    _lfc.dump_json(manifest, man_path)
    for e in manifest["episodes"]:
        for x in e["exports"]:
            print(f"ep{e['n']} {x['file']:28s} {x['w']}x{x['h']} {x['duration']:.1f}s "
                  f"{(x['loudness'] or {}).get('i', '-')} LUFS")
    for w in manifest["warnings"]:
        print("WARN", w)
    print(os.path.join(root, "manifest.json"))


if __name__ == "__main__":
    main()
