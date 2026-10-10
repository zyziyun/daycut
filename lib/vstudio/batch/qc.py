"""QC gates: every job ends green (all red-severity checks pass) or red (with reasons).

Existing library checks are reused: loudness from the export manifest (measured by ``audio.measure_loudness``;
re-measured when missing), lost words from ``cleanup.verify``, caption hallucinations through
``asr.drop_hallucinations``, length / title from ``platform.check_length`` / ``publish.check_title``, safe zone
and caption box from the export manifest. New here: A/V stream-duration sync and black / frozen frame detection
(ffmpeg blackdetect / freezedetect).

spec ``qc:`` keys (defaults): lufs_tol 1.0, tp_tol 0.5, av_tol 0.1 (s), black_min 0.5 (s), black_pix 0.10,
freeze_min 3.0 (s), freeze red|warn (talkinghead-clips: red, longform-slices / longform-split: warn - slides
sit still),
sample_pct 10 (% of greens flagged for a human look), seed 0, verify true, title_required false.
Length: an export over its platform's sweet spot (or the spec ``max_len``) gets a ``length-plan`` warning with a
suggestion (``lengthfit.suggestions``: speed needed, cold open / pending edits that could go, trim candidates in
source seconds) - also in ``suggestions`` of the result; over a spec ``max_len`` after the variant -> red.

Each check: {name, ok (True / False / None = skipped), severity red|warn, value, reason, target}.
"""
import hashlib
import re

LECTURE_RECIPES = ("longform-slices", "longform-split")
DEFAULTS = dict(lufs_tol=1.0, tp_tol=0.5, av_tol=0.1, black_min=0.5, black_pix=0.10, freeze_min=3.0, freeze=None,
                sample_pct=10.0, seed=0, verify=True, title_required=False)


def opts(spec, recipe=None):
    o = dict(DEFAULTS, **((spec or {}).get("qc") or {}))
    if o["freeze"] is None:
        o["freeze"] = "warn" if (recipe or (spec or {}).get("recipe")) in LECTURE_RECIPES else "red"
    return o


def _c(name, ok, value=None, reason="", severity="red", target=None, **params):
    """One check; a failed one carries ``message`` {code qc.<name>, params, message, message_zh} (MESSAGES.md)."""
    d = dict(name=name, ok=ok, value=value, reason=reason if ok is False else "", severity=severity, target=target)
    if ok is False:
        from vstudio import messages as MSG
        code = f"qc.{name}" if f"qc.{name}" in MSG.CATALOG else "qc.other"
        pv = value if not isinstance(value, list) else len(value)
        d["message"] = MSG.msg(code, None, None, name=name, value=pv, reason=reason, target=target, **params)
    return d


# --------------------------------------------------------------------------- individual checks
def check_loudness(path, target, measured=None, lufs_tol=1.0, tp_tol=0.5, label=None):
    from vstudio import audio
    m = measured
    if not m:
        mm = audio.measure_loudness(path, target["lufs"], target["tp"])
        m = dict(i=mm["input_i"], tp=mm["input_tp"])
    out = []
    i_ok = m["i"] is not None and abs(m["i"] - target["lufs"]) <= lufs_tol
    out.append(_c("loudness", i_ok, round(m["i"], 2) if m["i"] is not None else None,
                  f"integrated {m['i']:.1f} LUFS vs target {target['lufs']} (±{lufs_tol})", target=label,
                  lufs=target["lufs"]))
    tp_ok = m["tp"] <= target["tp"] + tp_tol
    out.append(_c("true-peak", tp_ok, round(m["tp"], 2), f"true peak {m['tp']:.1f} dBTP over {target['tp']}",
                  target=label, tp=target["tp"]))
    return out


def stream_durations(path):
    from vstudio import media
    v = media.ffprobe_value(path, "stream=duration", "v:0", float)
    a = media.ffprobe_value(path, "stream=duration", "a:0", float)
    return v, a


def check_av_sync(path, tol=0.1, label=None):
    v, a = stream_durations(path)
    if a is None:
        return _c("av-sync", False, None, "no audio stream", target=label)
    if v is None:
        return _c("av-sync", False, None, "no video stream", target=label)
    d = abs(v - a)
    return _c("av-sync", d <= tol, round(d, 3), f"video {v:.2f}s vs audio {a:.2f}s (Δ {d:.2f}s > {tol}s)", target=label)


_BLACK = re.compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)")
_FREEZE_S = re.compile(r"freeze_start:\s*([\d.]+)")
_FREEZE_D = re.compile(r"freeze_duration:\s*([\d.]+)")


def detect_black_frozen(path, black_min=0.5, black_pix=0.10, freeze_min=3.0, noise_db=-60):
    """-> (black spans [(t0, t1)], freeze spans [(t0, dur)]) via ffmpeg blackdetect + freezedetect."""
    from vstudio import media
    vf = (f"blackdetect=d={black_min}:pix_th={black_pix},"
          f"freezedetect=n={noise_db}dB:d={freeze_min}")
    r = media.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", path, "-map", "0:v:0", "-vf", vf,
                   "-an", "-f", "null", "-"], capture=True)
    txt = r.stderr_text
    black = [(float(a), float(b)) for a, b, _ in _BLACK.findall(txt)]
    starts = [float(x) for x in _FREEZE_S.findall(txt)]
    durs = [float(x) for x in _FREEZE_D.findall(txt)]
    freezes = list(zip(starts, durs))
    if len(starts) > len(durs):                          # frozen until the end: no duration line
        from vstudio.media import duration
        freezes.append((starts[-1], duration(path) - starts[-1]))
    return black, freezes


def check_black_frozen(path, o, label=None, allow=()):
    """allow: [(t0, t1)] output windows that are dark on purpose (chapter cards); black spans inside them pass."""
    black, frz = detect_black_frozen(path, o["black_min"], o["black_pix"], o["freeze_min"])
    black = [(a, b) for a, b in black if not any(x - 0.15 <= a and b <= y + 0.15 for x, y in allow or ())]
    out = [_c("black-frames", not black, [[round(a, 2), round(b, 2)] for a, b in black],
              "black " + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in black), target=label,
              spans=", ".join(f"{a:.1f}-{b:.1f}s" for a, b in black))]
    out.append(_c("frozen-frames", not frz, [[round(a, 2), round(d, 2)] for a, d in frz],
                  "frozen " + ", ".join(f"{a:.1f}s for {d:.1f}s" for a, d in frz),
                  severity="red" if o["freeze"] == "red" else "warn", target=label,
                  spans=", ".join(f"{a:.1f}s ({d:.1f}s)" for a, d in frz)))
    return out


def check_length(prof, seconds, label=None):
    from vstudio import platform as P
    w = P.check_length(prof, seconds)
    hard = [x for x in w if "sweet spot" not in x]
    out = [_c("length", not hard, round(seconds, 2), "; ".join(hard), target=label)]
    if w and not hard:
        out.append(_c("length-sweet-spot", False, round(seconds, 2), "; ".join(w), severity="warn", target=label))
    return out


def check_title(title, platform, required=False, label=None):
    from vstudio import publish
    if not title:
        return _c("title", None if not required else False, None, "no title", severity="red" if required else "warn",
                  target=label)
    pl = "youtube" if platform == "youtube-shorts" else platform
    ok, n, hints = publish.check_title(title, pl)
    return _c("title", ok, n, f"title {n:g} over the {pl} limit: " + "; ".join(hints[:2]), target=label, platform=pl)


def check_safe_zone(entry, prof, label=None):
    from vstudio import platform as P
    out = []
    size_ok = (entry.get("w"), entry.get("h")) == (prof.w, prof.h)
    out.append(_c("canvas", size_ok, [entry.get("w"), entry.get("h")], f"{entry.get('w')}x{entry.get('h')} "
                  f"is not the {prof.key} canvas {prof.w}x{prof.h}", target=label))
    sx0, sy0, sx1, sy1 = entry.get("safe_box") or P.safe_box(prof)
    cx0, cy0, cx1, cy1 = entry.get("caption_box") or P.caption_box(prof)
    inside = sx0 <= cx0 and sy0 <= cy0 and cx1 <= sx1 and cy1 <= sy1
    bad = [w for w in entry.get("warnings") or [] if "overlap" in w or "caption too long" in w]
    out.append(_c("safe-zone", inside and not bad, len(bad),
                  "; ".join(bad) or "caption box outside the safe box", target=label))
    return out


def check_hallucinations(cues):
    """Caption text whisper typically invents (字幕志愿者…, 请不吝点赞…) left in the burned cues -> red."""
    from vstudio import asr
    segs = [dict(start=c["start"], end=c["end"], text=c["text"]) for c in cues]
    kept = asr.drop_hallucinations(segs)
    bad = [s for s in segs if s not in kept]
    return _c("caption-hallucination", not bad, len(bad),
              "invented caption text: " + " / ".join(s["text"][:20] for s in bad[:3]))


def check_lost_words(verify_out):
    if not verify_out:
        return _c("lost-words", None, None, "verify skipped", severity="warn")
    rep = verify_out.get("report")
    from .util import read_json
    data = read_json(rep, {}) if rep else {}
    miss = [m for r in data.values() for m in r.get("missing", [])]
    return _c("lost-words", bool(verify_out.get("ok")), len(miss),
              "lost: " + "; ".join(f"'{m['text']}' @{m.get('t_out')}s" for m in miss[:4]))


# --------------------------------------------------------------------------- job gate
def sampled(job_id, pct, seed=0):
    """Deterministic pseudo-random sample: the same job is always (not) sampled for a given seed / pct."""
    h = int(hashlib.sha1(f"{seed}:{job_id}".encode()).hexdigest()[:8], 16) % 10000
    return h < float(pct) * 100


def run_gates(job, spec, ins, extra=()):
    """All gates for one job; ``extra`` = recipe-specific checks (``_c`` dicts, e.g. longform-split privacy)."""
    from vstudio import platform as P
    from .util import read_json
    o = opts(spec, job.get("recipe"))
    p = job["params"]
    checks = []
    cues = (read_json(ins["compose"]["cues"], {}) or {}).get("cues", []) if ins.get("compose") else []
    checks.append(check_hallucinations(cues))
    if o["verify"]:
        checks.append(check_lost_words(ins.get("verify")))
    man = read_json(ins["export"]["manifest"], {}) if ins.get("export") else {}
    from . import lengthfit as LF
    exps = (ins.get("export") or {}).get("exports") or []
    sug = LF.suggestions(job, spec, ins, exps,
                         lambda x: (P.profile(x["platform"], x["orientation"]).length.get("sweet") or [0, 0])[1] or None)
    sug_for = {f"{x['platform']}:{x['orientation']}": x for x in sug}
    for e in man.get("exports", []):
        label = f"{e['platform']}:{e['orientation']}"
        prof = P.profile(e["platform"], e["orientation"])
        f = next(x["file"] for x in ins["export"]["exports"]
                 if x["platform"] == e["platform"] and x["orientation"] == e["orientation"])
        checks += check_loudness(f, e.get("target_loudness") or prof.loudness, e.get("loudness"), o["lufs_tol"],
                                 o["tp_tol"], label)
        checks.append(check_av_sync(f, o["av_tol"], label))
        lc = check_length(prof, e["duration"], label)
        if label in sug_for:                          # the plan suggestion replaces the bare sweet-spot warning
            lc = [c for c in lc if c["name"] != "length-sweet-spot"]
            lc.append(_c("length-plan", False, sug_for[label]["speed_needed"], sug_for[label]["text"], severity="warn",
                         target=label))
        lim = LF.limit_for(p, spec, e["platform"], e["orientation"])[0]
        if lim:
            lc.append(_c("max-len", e["duration"] <= lim + 0.5, round(e["duration"], 2),
                         f"{e['duration']:.1f}s over the spec max_len {lim:g}s for {e['platform']} (add trims)",
                         target=label))
        checks += lc
        checks.append(check_title(p.get("title") or (ins.get("export") or {}).get("title"), e["platform"],
                                  o["title_required"], label))   # the creator's, else the drafted one
        checks += check_safe_zone(e, prof, label)
        checks += check_black_frozen(f, o, label, (ins.get("compose") or {}).get("cards") or ())
        for w in e.get("warnings") or []:
            if not any(k in w for k in ("overlap", "caption too long", "loudness", "true peak", "duration", "title")):
                checks.append(_c("export-warning", False, None, w, severity="warn", target=label))
    if not man.get("exports"):
        checks.append(_c("exports", False, 0, "no exports"))
    miss = (((ins.get("export") or {}).get("caption_overrides") or {}).get("missed")) or []
    if miss:                                          # a creator caption edit that could not be placed: say so
        checks.append(_c("caption-edit-missed", False, len(miss), "caption edit(s) not applied (the cue changed): " +
                         "; ".join(f"#{m.get('i')} {m.get('from')!r} -> {m.get('to')!r}" for m in miss[:3]),
                         severity="warn"))
    cl = (ins.get("export") or {}).get("caption_lang") or {}
    if cl and cl.get("asked") != cl.get("spoken") and not cl.get("translated"):
        checks.append(_c("caption-language", False, cl.get("spoken"),
                         f"captions asked in {cl.get('asked')}, made in {cl.get('spoken')} (not translated: "
                         f"{cl.get('error') or 'no translation model'})", severity="warn"))
    checks += list(extra or ())
    red = [c for c in checks if c["ok"] is False and c["severity"] == "red"]
    warn = [c for c in checks if c["ok"] is False and c["severity"] == "warn"]
    fmt = lambda c: (f"[{c['target']}] " if c.get("target") else "") + f"{c['name']}: {c['reason']}"  # noqa: E731
    status = "red" if red else "green"
    return dict(status=status, reasons=[fmt(c) for c in red], warnings=[fmt(c) for c in warn], checks=checks,
                reasons_info=[c.get("message") for c in red], warnings_info=[c.get("message") for c in warn],
                suggestions=sug, sample=status == "green" and sampled(job["id"], o["sample_pct"], o["seed"]))
