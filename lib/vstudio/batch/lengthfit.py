"""Platform length -> plan feedback: QC suggestions when a clip is over a platform's sweet spot, and the optional
per-platform shorter variant (``max_len``) made at export.

Spec / job keys (job rows override ``defaults``, which override the top level):

    max_len: {douyin: 60}                          # seconds per platform name (or "douyin:vertical")
    max_len: {douyin: {max: 60, via: speed, max_speed: 1.25}}
    trims: {douyin: [[201.5, 209.2], [272.1, 286.5]]}   # source seconds removed from that platform's variant only

``via``: ``speed`` (pitch-preserved speed-up up to ``max_speed`` x the job's own speed), ``trim`` (only the row's
``trims``), ``auto`` (default: trims first, then speed) or ``suggest`` (no change, QC suggestion only).
The other platforms keep the full export. QC (``suggestions``) always says what would fit: the speed factor
needed, the cold open (a repeat of the body) that could go, the cleanup edits still waiting for a yes, and the
longest caption sentences as trim candidates (source seconds, ready for ``trims:``).
"""
import os

from vstudio import media

DEFAULT_MAX_SPEED = 1.25


def _plat_key(platform, orientation=None):
    return [f"{platform}:{orientation}" if orientation else platform, platform]


def limit_for(p, spec, platform, orientation=None):
    """(max seconds, via, max_speed) for one export, or (None, ..) when no max_len applies."""
    ml = p.get("max_len")
    if ml is None:
        ml = (spec.get("defaults") or {}).get("max_len")
    if ml is None:
        ml = spec.get("max_len")
    if not isinstance(ml, dict):
        return None, None, None
    v = next((ml[k] for k in _plat_key(platform, orientation) if k in ml), None)
    if v is None:
        return None, None, None
    if isinstance(v, dict):
        return float(v.get("max") or 0) or None, v.get("via", "auto"), float(v.get("max_speed") or DEFAULT_MAX_SPEED)
    return float(v), "auto", DEFAULT_MAX_SPEED


def trims_for(p, platform, orientation=None):
    t = p.get("trims")
    if isinstance(t, dict):
        t = next((t[k] for k in _plat_key(platform, orientation) if k in t), None)
    out = []
    for x in t or ():
        a, b = float(x[0]), float(x[1])
        if b > a:
            out.append((a, b))
    return sorted(out)


# --------------------------------------------------------------------------- time maps (longform-split timeline)
def body_items(timeline):
    return [it for it in timeline or () if it.get("kind") != "card" and not it.get("hook")]


def src_to_out(timeline, a, b):
    """Output windows [(x, y)] playing source [a, b] (body items only)."""
    out = []
    for it in body_items(timeline):
        t0, t1, sp, f0 = float(it["t0"]), float(it["t1"]), float(it["speed"]), float(it["final_t0"])
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo:
            out.append((f0 + (lo - t0) / sp, f0 + (hi - t0) / sp))
    return out


def out_to_src(timeline, t):
    for it in body_items(timeline):
        t0, t1, sp, f0 = float(it["t0"]), float(it["t1"]), float(it["speed"]), float(it["final_t0"])
        if f0 <= t <= f0 + (t1 - t0) / sp:
            return t0 + (t - f0) * sp
    return None


# --------------------------------------------------------------------------- the shorter variant
def _keep_windows(dur, cuts):
    keep, cur = [], 0.0
    for a, b in sorted(cuts):
        a, b = max(0.0, a), min(dur, b)
        if b <= cur:
            continue
        if a > cur:
            keep.append((cur, a))
        cur = max(cur, b)
    if cur < dur:
        keep.append((cur, dur))
    return [(a, b) for a, b in keep if b - a > 0.05]


def render_variant(src, dst, cuts=(), speed=1.0, preset="medium"):
    """``src`` without the output windows ``cuts`` (30 / 40 ms audio fades at every join), sped up by ``speed``
    (pitch kept) -> ``dst``. Returns the new duration."""
    dur = media.duration(src)
    keep = _keep_windows(dur, cuts)
    graph, labels = [], []
    for i, (a, b) in enumerate(keep):
        graph.append(f"[0:v:0]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS[v{i}]")
        fo = max(0.0, (b - a) - 0.04)
        graph.append(f"[0:a:0]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:st=0:d=0.03,afade=t=out:st={fo:.4f}:d=0.04[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    graph.append("".join(labels) + f"concat=n={len(keep)}:v=1:a=1[vc][ac]")
    if abs(speed - 1.0) > 1e-3:
        graph.append(f"[vc]setpts=PTS/{speed:.6f}[v]")
        graph.append(f"[ac]{media.atempo_chain(speed)}[a]")
    else:
        graph.append("[vc]null[v]")
        graph.append("[ac]anull[a]")
    tmp = dst + ".tmp.mp4"
    media.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", ";".join(graph), "-map", "[v]",
               "-map", "[a]", "-c:v", "libx264", "-preset", preset, "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp])
    os.replace(tmp, dst)
    return media.duration(dst)


def fit_exports(exports, p, spec, timeline=None, preset="medium"):
    """Apply ``max_len`` to the exports of one job in place: the over-long platform files are replaced by their
    shorter variant (trims, then speed). Returns [{platform, before, after, speed, trims, ok, why}]."""
    log = []
    for e in exports:
        lim, via, max_speed = limit_for(p, spec, e["platform"], e.get("orientation"))
        if not lim or via == "suggest" or not os.path.exists(e["file"]):
            continue
        before = float(e.get("duration") or media.duration(e["file"]))
        if before <= lim + 0.05:
            continue
        cuts = []
        if via in ("auto", "trim") and timeline:
            for a, b in trims_for(p, e["platform"], e.get("orientation")):
                cuts += src_to_out(timeline, a, b)
        removed = sum(b - a for a, b in cuts)
        speed = 1.0
        if via in ("auto", "speed") and before - removed > lim:
            speed = min(max_speed, (before - removed) / lim)
        if not cuts and speed <= 1.0 + 1e-3:
            log.append(dict(platform=e["platform"], before=round(before, 2), after=round(before, 2), speed=1.0,
                            trims=[], ok=False, why=f"no trims and via={via}"))
            continue
        after = render_variant(e["file"], e["file"], cuts, speed, preset)
        e.update(duration=round(after, 3), variant=dict(max_len=lim, speed=round(speed, 3),
                                                        trims=[[round(a, 2), round(b, 2)] for a, b in cuts]))
        e.pop("loudness", None)
        log.append(dict(platform=e["platform"], before=round(before, 2), after=round(after, 2), speed=round(speed, 3),
                        trims=e["variant"]["trims"], ok=after <= lim + 0.5,
                        why="" if after <= lim + 0.5 else f"still {after:.1f}s > {lim:g}s at the {max_speed:g}x cap: "
                                                         "add trims"))
    return log


# --------------------------------------------------------------------------- QC suggestions
def suggestions(job, spec, inputs, exports, sweet_of):
    """One suggestion per over-long export: target length, speed needed, what could go."""
    from .util import read_json
    p = job["params"]
    cm = inputs.get("compose") or {}
    cl = inputs.get("cleanup") or {}
    tl = read_json(cm.get("timeline"), []) if cm.get("timeline") else []
    cues = (read_json(cm.get("cues"), {}) or {}).get("cues", []) if cm.get("cues") else []
    pend = read_json(cl.get("confirm_file"), []) if cl.get("confirm_file") else []
    sp = float(p.get("speed") or 1.0)
    out = []
    for e in exports:
        dur = float(e.get("duration") or 0)
        lim, via, max_speed = limit_for(p, spec, e["platform"], e.get("orientation"))
        target = lim or sweet_of(e)
        if not target or dur <= target + 0.5:
            continue
        need = dur / target
        s = dict(platform=e["platform"], orientation=e.get("orientation"), duration=round(dur, 2), target=target,
                 over=round(dur - target, 2), speed_needed=round(need, 3),
                 speed_ok=need <= (max_speed or DEFAULT_MAX_SPEED), hook_s=round(float(cm.get("hook_dur") or 0), 2),
                 confirm_s=round(sum(float(x["t1"]) - float(x["t0"]) for x in pend) / sp, 2), trims=[])
        cand = []
        for c in cues:
            mid = (c["start"] + c["end"]) / 2
            if any(it.get("hook") and float(it["final_t0"]) <= mid < float(it["final_t0"]) +
                   (float(it["t1"]) - float(it["t0"])) / float(it["speed"]) for it in tl if it.get("kind") != "card"):
                continue
            a, b = out_to_src(tl, c["start"]), out_to_src(tl, c["end"])
            if a is None or b is None:
                continue
            cand.append(dict(src=[round(a, 2), round(b, 2)], out=[round(c["start"], 2), round(c["end"], 2)],
                             dur=round(c["end"] - c["start"], 2), text=c["text"]))
        cand.sort(key=lambda x: -x["dur"])
        acc = 0.0
        for x in cand:
            if acc >= s["over"]:
                break
            s["trims"].append(x)
            acc += x["dur"]
        key = e["platform"]
        parts = [f"{key} {dur:.1f}s > {target:g}s ({'max_len' if lim else 'sweet spot'}): "
                 f"speed {need:.2f}x would fit" + ("" if s["speed_ok"] else f" (over the {max_speed or DEFAULT_MAX_SPEED:g}x cap)")]
        if s["hook_s"]:
            parts.append(f"dropping the cold open saves {s['hook_s']:.1f}s")
        if s["confirm_s"]:
            parts.append(f"cleanup edits waiting for a yes save {s['confirm_s']:.1f}s")
        if s["trims"]:
            parts.append("trim candidates (source s): " + ", ".join(f"{x['src'][0]:.1f}-{x['src'][1]:.1f}" for x in s["trims"][:4]))
        parts.append(f"set max_len: {{{key}: {target:g}}} (+ trims: {{{key}: [[a, b], ...]}}) for a shorter {key} variant")
        s["text"] = "; ".join(parts)
        out.append(s)
    return out


__all__ = ["limit_for", "trims_for", "fit_exports", "render_variant", "suggestions", "src_to_out", "out_to_src"]
