"""Storyboard: config + shots -> a timed plan per cut (demo / loop / one feature clip), language and canvas.

    from vstudio.launch import story as S
    plan = S.plan(cfg, shots, "demo", "en", "16:9")      # {cut, lang, aspect, W, H, duration, layout, scenes}
    S.plan(cfg, shots, "clip", "zh", "9:16", feature="plan")

Pure functions (no rendering), so the timing and the camera are unit-tested. Scenes:
  title    product mark + name + one-liner (demo only)
  feature  kicker + kinetic caption + the product shot in a window; the camera follows the shot's focus boxes
           (punch-in on each click / typed field, pull back between actions)
  end      logo, call to action, site
Consecutive scenes overlap by ``XF`` seconds (crossfade). A loop ends on a crossfade back into its first frame.
"""
from . import config as C
from . import timing as TM

XF = 0.35                     # scene crossfade
LEAD = 0.55                   # the camera starts moving this long before the action it frames
HOLD = 1.5                    # minimum time the camera stays on an action
MERGE = 0.6                   # actions closer than this share one camera move

# canvas layouts (px). Text boxes stay inside the intersection of the safe boxes of every platform the canvas is
# posted to (config.CANVAS_PLATFORMS; asserted in tests); the product window may run under platform UI.
LAYOUTS = {
    "16:9": dict(text=(120, 64, 1800, 196), kicker_px=24, caption_px=(56, 40), caption_lines=1,
                 win=(328, 214, 1264, 776), base_zoom=1.0, punch=1.45, title_px=124, oneliner_px=44),
    "1:1": dict(text=(72, 62, 1008, 288), kicker_px=22, caption_px=(50, 36), caption_lines=2,
                win=(60, 318, 960, 640), base_zoom=1.0, punch=1.5, title_px=104, oneliner_px=38),
    "9:16": dict(text=(72, 300, 920, 660), kicker_px=30, caption_px=(84, 56), caption_lines=3,
                 win=(40, 720, 1000, 940), base_zoom=1.0, punch=1.45, title_px=112, oneliner_px=46),
}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def shot_for(feat, shots):
    sid = feat.get("shot") or feat["id"]
    if sid not in shots:
        raise KeyError(f"feature '{feat['id']}': no shot '{sid}' (have: {', '.join(sorted(shots)) or 'none'}); "
                       "run the capture step or add capture.images")
    return shots[sid]


def media_window(feat, shot):
    """(in, out) seconds of the shot this feature plays (feature.trim [a, b], default the whole shot)."""
    a, b = (feat.get("trim") or [0, shot.get("duration") or 6.0])[:2]
    b = min(float(b), float(shot.get("duration") or b))
    if b - float(a) < 1.0:
        raise ValueError(f"feature '{feat['id']}': trim {a}-{b} is shorter than 1 s")
    return float(a), b


# ------------------------------------------------------------------------------------------------ camera
def _fit(win, shot):
    """Cover-fit scale of the shot (its pixel size) into the window."""
    _, _, W, H = win
    sw, sh = float(shot.get("w") or W), float(shot.get("h") or H)
    return max(W / sw, H / sh), sw, sh


def cam_pose(win, shot, cx, cy, zoom):
    """Window-local GSAP transform {x, y, scale} (transform-origin 0 0) that puts the normalised shot point
    (cx, cy) at the window centre at ``zoom`` x the cover fit, clamped so the shot always covers the window."""
    _, _, W, H = win
    fit, sw, sh = _fit(win, shot)
    s = fit * max(1.0, zoom)
    x = clamp(W / 2 - cx * sw * s, W - sw * s, 0.0)
    y = clamp(H / 2 - cy * sh * s, H - sh * s, 0.0)
    return dict(x=round(x, 1), y=round(y, 1), scale=round(s, 5))


def focus_events(shot, t0, t1, tmap=None):
    """The shot's focus boxes inside [t0, t1] (media seconds) -> [(scene_t, cx, cy, box_w, box_h)], merged when
    closer than MERGE. tmap: media second -> scene second (default: t - t0)."""
    tmap = tmap or (lambda m: m - t0)
    ev = []
    for f in sorted(shot.get("focus") or [], key=lambda f: f["t"]):
        if not (t0 <= f["t"] <= t1):
            continue
        t = tmap(f["t"])
        cx, cy = f["x"] + f.get("w", 0) / 2, f["y"] + f.get("h", 0) / 2
        if ev and t - ev[-1][0] < MERGE:
            continue
        ev.append((t, cx, cy, f.get("w", 0.1), f.get("h", 0.1)))
    return ev


def camera(layout, shot, t0, t1, dur, tmap=None):
    """Keyframes [{t, x, y, scale, d, ease}] for one feature scene: open framed on the whole shot (or, on a
    narrow window, the first action), punch in on each action, pull back when the next one is far off."""
    win = layout["win"]
    z0, punch = layout["base_zoom"], layout["punch"]
    ev = focus_events(shot, t0, t1, tmap)
    fit, sw, sh = _fit(win, shot)
    narrow = (win[2] / win[3]) < (sw / sh) * 0.8          # the window shows a crop: follow the action
    first = (ev[0][1], ev[0][2]) if ev and narrow else (0.5, 0.5)
    keys = [dict(t=0.0, d=0.0, ease="none", **cam_pose(win, shot, *first, z0))]
    for i, (t, cx, cy, bw, bh) in enumerate(ev):
        # do not zoom past the point where the acted-on element fills ~60 % of the window
        zmax = max(1.0, min(2.6, 0.6 / max(bw * sw * fit / win[2], bh * sh * fit / win[3], 1e-3)))
        z = clamp(z0 * punch, 1.0, max(z0, zmax))
        start = max(keys[-1]["t"] + keys[-1]["d"], t - LEAD)
        if start >= dur - 0.4:
            break
        keys.append(dict(t=round(start, 3), d=round(min(LEAD + 0.15, dur - start), 3), ease="power2.inOut",
                         **cam_pose(win, shot, cx, cy, z)))
        nxt = ev[i + 1][0] if i + 1 < len(ev) else dur
        if nxt - t > HOLD + LEAD + 0.9 and t + HOLD < dur - 1.0:
            back = (cx, cy) if narrow else (0.5, 0.5)
            keys.append(dict(t=round(t + HOLD, 3), d=0.7, ease="power2.inOut", **cam_pose(win, shot, *back, z0)))
    return keys


# ------------------------------------------------------------------------------------------------ plans
def _feature_scene(cfg, shots, fid, lang, layout, dur_hint, cut):
    feat = C.feature(cfg, fid)
    shot = shot_for(feat, shots)
    a, b = media_window(feat, shot)
    rate = float(feat.get("rate", 1.0))
    # idle stretches of a recording (waiting for the app) play fast unless the feature says ramp: false
    spans = TM.idle_spans(shot) if shot["kind"] == "video" and feat.get("ramp", True) else []
    segs = TM.segments(a, b, spans, rate)
    natural = TM.length(segs)
    return dict(kind="feature", id=fid, shot=shot["id"], media=dict(kind=shot["kind"], file=shot["file"],
                still=shot.get("still"), w=shot.get("w"), h=shot.get("h"), at=a, until=b, rate=rate, segs=segs),
                natural=natural, dur=dur_hint(natural),
                kicker=C.text(feat.get("kicker"), lang), caption=C.text(feat.get("caption"), lang),
                vo=C.text(feat.get("vo"), lang) if (cfg.get("voiceover") or {}).get("enabled") else "")


def _place(scenes, layout, shots, cfg):
    t = 0.0
    for i, s in enumerate(scenes):
        s["start"] = round(t, 3)
        if s["kind"] == "feature":
            feat = C.feature(cfg, s["id"])
            shot = shot_for(feat, shots)
            m = s["media"]
            m["segs"] = TM.fit(m["segs"], s["dur"])                    # a short scene plays the take faster
            s["play"] = round(min(s["dur"], TM.length(m["segs"])), 3)   # the rest holds the last frame
            segs = m["segs"]
            s["cam"] = camera(layout, shot, m["at"], m["until"], s["dur"], lambda t, g=segs: TM.to_scene(g, t))
        t += s["dur"] - (XF if i < len(scenes) - 1 else 0.0)
    return round(t, 3)


def plan(cfg, shots, cut, lang, aspect, feature=None):
    """cut: demo | loop | clip (clip needs ``feature``)."""
    if aspect not in LAYOUTS:
        raise ValueError(f"aspect {aspect}: one of {', '.join(LAYOUTS)}")
    W, H = C.ASPECTS[aspect]
    layout = dict(LAYOUTS[aspect])
    scenes = []
    if cut == "demo":
        d = cfg["demo"]
        ids = C.cut_features(cfg, "demo")
        fixed = d["title_seconds"] + d["end_seconds"] - XF * (len(ids) + 1)
        scenes = [_feature_scene(cfg, shots, fid, lang, layout, lambda n: clamp(n, 4.5, 9.0), cut) for fid in ids]
        body = sum(s["dur"] for s in scenes)
        if fixed + body > d["max_seconds"]:                  # squeeze every scene evenly, never under 4 s
            k = (d["max_seconds"] - fixed) / body
            for s in scenes:
                s["dur"] = round(max(4.0, s["dur"] * k), 3)
        elif fixed + body < d["min_seconds"]:                # hold each shot's last frame a little longer
            extra = (d["min_seconds"] - fixed - body) / max(1, len(scenes))
            for s in scenes:
                s["dur"] = round(s["dur"] + min(extra, 2.5), 3)
        scenes = ([dict(kind="title", dur=d["title_seconds"])] + scenes + [dict(kind="end", dur=d["end_seconds"])])
    elif cut == "loop":
        lp = cfg["loop"]
        ids = C.cut_features(cfg, "loop")
        each = (lp["seconds"] + XF * len(ids)) / len(ids)    # the closing crossfade back to frame 0 overlaps too
        scenes = [_feature_scene(cfg, shots, fid, lang, layout, lambda n, e=each: e, cut) for fid in ids]
    elif cut == "clip":
        cp = cfg["clips"]
        if not feature:
            raise ValueError("clip needs a feature id")
        lo, hi = cp["min_seconds"] - cp["end_seconds"] + XF, cp["max_seconds"] - cp["end_seconds"] + XF
        scenes = [_feature_scene(cfg, shots, feature, lang, layout,
                                 lambda n: clamp(n + 1.2, lo, hi), cut), dict(kind="end", dur=cp["end_seconds"])]
    else:
        raise ValueError(f"cut {cut}: demo | loop | clip")
    total = _place(scenes, layout, shots, cfg)
    if cut == "loop":
        total = round(total - XF, 3)                         # last scene crossfades into the first frame
    return dict(cut=cut, lang=lang, aspect=aspect, W=W, H=H, duration=total, layout=layout, scenes=scenes,
                feature=feature, xf=XF, loop=cut == "loop")


def caption_cues(p):
    """[{start, end, text}] of the on-screen captions (firstpass checks their spelling / terms)."""
    out = []
    for s in p["scenes"]:
        if s["kind"] == "feature" and s.get("caption"):
            out.append(dict(start=s["start"], end=round(s["start"] + s["dur"], 3), text=C.plain(s["caption"])))
    return out


def frames(n, total):
    """n evenly spaced sample times inside (0, total) - used for snapshot checks."""
    return [round(total * (i + 0.5) / n, 2) for i in range(n)] if n > 0 and total > 0 else []
