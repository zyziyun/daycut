"""Shot list -> generation units -> per-model prompts, validation and a cost plan. No network, no spend.

Project file (see templates/project.yaml):
    title, aspect, language, provider, model, resolution, style, negative, acting,
    characters: {A: {look, ref, element, voice}},  scenes: {name: {description, master}},
    shots: [{id, scene, chars, dur, camera, action, lines: [{who, text}], audio, unit, dense_check, ref_extra}]
    rates: {...}   (optional override of providers.RATES)

A *unit* is what one generation call produces. Shots that share a set-up (same scene + characters + camera
position) can be grouped with `unit:` and cut apart in the edit - the sessions did this to fit 2-3 s shots into
a 5 s Kling clip, and Seedance segments of up to 15 s carry several shots with in-prompt timecodes.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from providers import CAPS, Job, get_provider  # noqa: E402

DEFAULT_NEGATIVE = ("No text, letters, subtitles, logos or watermark anywhere in frame (screens and paper stay blank). "
                    "No plastic or airbrushed skin, no oversaturated colour, no extra fingers.")
DEFAULT_ACTING = ("Acting: grounded and restrained, small real reactions, mouth mostly closed between lines; "
                  "nobody looks into the camera; no grinning, gurning or cartoon expressions.")
DEFAULT_TEXTURE = "Natural skin with visible pores and fine texture, flyaway hairs, real-world imperfections."

FAMILY = {"kling": "kling", "seedance": "seedance", "seedream": "seedance", "minimax": "minimax", "hailuo": "minimax"}


def family(model: str) -> str:
    m = (model or "").lower()
    for k, v in FAMILY.items():
        if k in m:
            return v
    return "generic"


@dataclass
class Unit:
    id: str
    shots: list
    scene: str = ""
    chars: list = field(default_factory=list)
    dur: float = 0.0             # requested (sum of shots + pad)
    gen_dur: float = 0.0         # snapped to what the model accepts
    audio: str = "native"
    warnings: list = field(default_factory=list)


def load(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("aspect", "9:16")
    cfg.setdefault("resolution", "1080p")
    cfg.setdefault("provider", "manual")
    cfg.setdefault("characters", {})
    cfg.setdefault("scenes", {})
    cfg.setdefault("shots", [])
    cfg["_dir"] = os.path.dirname(os.path.abspath(path))
    return cfg


def snap_duration(want: float, caps: dict):
    """Smallest accepted duration >= want (sessions: resolve discrete/integer limits in the PLAN, not at submit).
    Returns (seconds, warning or None)."""
    d = caps.get("durations")
    if not d:
        return round(want, 2), None
    if isinstance(d, (list, set)):
        ok = sorted(d)
        for v in ok:
            if v >= want - 1e-6:
                return float(v), None
        return float(ok[-1]), f"needs {want:.1f}s but the model max is {ok[-1]}s - split the unit"
    lo, hi = d
    v = max(lo, math.ceil(want - 1e-6))
    if v > hi:
        return float(hi), f"needs {want:.1f}s but the model max is {hi}s - split the unit"
    return float(v), None


def compile_units(cfg, pad=None):
    """Group shots into units (explicit `unit:` or one per shot), sum durations, snap to the model."""
    caps = CAPS.get(cfg.get("model", ""), {})
    pad = cfg.get("unit_pad", 0.5) if pad is None else pad
    order, groups = [], {}
    for s in cfg["shots"]:
        uid = str(s.get("unit") or s["id"])
        if uid not in groups:
            order.append(uid)
            groups[uid] = []
        groups[uid].append(s)
    units = []
    for uid in order:
        shots = groups[uid]
        scenes = {s.get("scene", "") for s in shots}
        chars = sorted({c for s in shots for c in (s.get("chars") or [])})
        u = Unit(uid, shots, scene=shots[0].get("scene", ""), chars=chars,
                 audio=shots[0].get("audio", "native"))
        u.dur = round(sum(float(s.get("dur", 0)) for s in shots) + pad, 2)
        u.gen_dur, w = snap_duration(u.dur, caps)
        if w:
            u.warnings.append(w)
        if len(scenes) > 1:
            u.warnings.append(f"unit mixes scenes {sorted(scenes)} - one generation keeps one set; split it")
        for c in chars:
            if c not in cfg["characters"]:
                u.warnings.append(f"character {c!r} has no bible entry")
        units.append(u)
    return units


def _who(cfg, c, fam, ref_idx):
    """How a character is named in a prompt: always the bible label + look, bound to its reference."""
    look = cfg["characters"].get(c, {}).get("look", "")
    tail = f": {look}" if look else ""
    if fam == "kling" and cfg["characters"].get(c, {}).get("element"):
        return f"{c} (<<<{c}>>>{tail})"
    if fam == "seedance" and c in ref_idx:
        return f"{c} (@图片{ref_idx[c]}{tail})"
    if c in ref_idx:
        return f"{c} (the person in image {ref_idx[c]}{tail})"
    return f"{c} ({look})" if look else c


def _lines(cfg, shot, voice_lang):
    out = []
    for ln in shot.get("lines") or []:
        how = ln.get("how", "")
        how = f" {how}" if how else ""
        out.append(f'{ln.get("who", "")} says{how} in natural {voice_lang}: "{ln["text"]}"')
    return " ".join(out)


def ref_index(cfg, unit):
    """Characters with a reference image -> 1-based image index (scene master first if present)."""
    idx, n = {}, 0
    sc = cfg["scenes"].get(unit.scene, {})
    if sc.get("master"):
        n += 1
        idx["__scene__"] = n
    for c in unit.chars:
        if cfg["characters"].get(c, {}).get("ref"):
            n += 1
            idx[c] = n
    return idx


def render_prompt(cfg, unit: Unit) -> str:
    """Per-model prompt for one unit. Rules baked in from the sessions:
    one shot per prompt for Kling/MiniMax; timecoded multi-shot for Seedance; camera language instead of
    'cinematic'; restrained acting; texture words against plastic skin; no generated text, ever."""
    fam = family(cfg.get("model", ""))
    lang = cfg.get("voice_language", "American English" if cfg.get("language", "en") == "en" else "Mandarin Chinese")
    idx = ref_index(cfg, unit)
    sc = cfg["scenes"].get(unit.scene, {})
    parts = []
    if "__scene__" in idx:
        parts.append(f"Image {idx['__scene__']} is the scene master: keep the same set, layout, light direction and positions."
                     if fam != "seedance" else f"@图片{idx['__scene__']} 是场景母版：同一场景、同样布局、光线方向和站位。")
    if fam == "kling" and idx and any(c in idx for c in unit.chars):
        parts.append("Keep every face, glasses, hair and outfit exactly as in the reference images; do not beautify.")
    if sc.get("description"):
        parts.append(f"Setting: {sc['description']}.")
    t = 0.0
    for s in unit.shots:
        who = ", ".join(_who(cfg, c, fam, idx) for c in (s.get("chars") or []))
        cam = s.get("camera", "")
        body = " ".join(x for x in [cam + ":" if cam else "", who + "." if who else "", s.get("action", ""),
                                    _lines(cfg, s, lang)] if x).strip()
        if fam == "seedance" or len(unit.shots) > 1:
            t1 = t + float(s.get("dur", 0))
            parts.append(f"[{t:.1f}-{t1:.1f}s] {body}")
            t = t1
        else:
            parts.append(body)
    if len(unit.shots) > 1 or fam == "seedance":
        parts.append(f"[{t:.1f}-{unit.gen_dur:.1f}s] hold the last frame.")
    parts.append(cfg.get("acting", DEFAULT_ACTING))
    parts.append(cfg.get("texture", DEFAULT_TEXTURE))
    if cfg.get("style"):
        parts.append(cfg["style"])
    au = unit.audio
    if au == "native":
        parts.append("Sound: dialogue and natural ambience only, no music.")
    elif au in ("post", "none"):
        parts.append("Picture only: no speech, no music (sound is added in post).")
    parts.append(cfg.get("negative", DEFAULT_NEGATIVE))
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return " ".join(text.split())          # single line: newlines submit some web forms


def unit_refs(cfg, unit):
    refs, idx = {}, ref_index(cfg, unit)
    sc = cfg["scenes"].get(unit.scene, {})
    if "__scene__" in idx:
        refs[f"image_{idx['__scene__']}"] = sc["master"]
    for c in unit.chars:
        if c in idx:
            refs[f"image_{idx[c]}"] = cfg["characters"][c]["ref"]
    for s in unit.shots:
        for k, v in (s.get("ref_extra") or {}).items():
            refs[k] = v
    return refs


def unit_job(cfg, unit) -> Job:
    els = [{"id": cfg["characters"][c]["element"], "bindName": c} for c in unit.chars
           if cfg["characters"].get(c, {}).get("element")]
    prompt = render_prompt(cfg, unit)
    if els:
        for e in els:
            prompt = prompt.replace(f"<<<{e['bindName']}>>>", f"<<<{e['id']}>>>")
    return Job(unit=unit.id, kind="video", model=cfg.get("model", ""), prompt=prompt, duration=unit.gen_dur,
               aspect=cfg["aspect"], resolution=cfg["resolution"], refs=unit_refs(cfg, unit),
               count=int(cfg.get("takes_per_unit", 1)), audio=unit.audio == "native", elements=els,
               rate_key=cfg.get("rate_key"))


def validate(cfg, units, jobs):
    """Plan-time checks (the sessions lost credits on every one of these at submit time)."""
    caps = CAPS.get(cfg.get("model", ""), {})
    warns = []
    if caps:
        if cfg["aspect"] not in caps.get("aspects", [cfg["aspect"]]):
            warns.append(f"aspect {cfg['aspect']} not in {caps['aspects']} for {cfg['model']}")
        if cfg["resolution"] not in caps.get("resolutions", [cfg["resolution"]]):
            warns.append(f"resolution {cfg['resolution']} not in {caps['resolutions']} for {cfg['model']}")
    for u, j in zip(units, jobs):
        warns += [f"{u.id}: {w}" for w in u.warnings]
        mx = caps.get("max_prompt_chars")
        if mx and len(j.prompt) > mx:
            warns.append(f"{u.id}: prompt {len(j.prompt)} chars > {mx} - one shot per prompt, cut adjectives")
        if caps.get("max_refs") is not None and len(j.refs) > caps["max_refs"]:
            warns.append(f"{u.id}: {len(j.refs)} refs > {caps['max_refs']}")
        for k, v in j.refs.items():
            p = v if os.path.isabs(v) or str(v).startswith("http") else os.path.join(cfg.get("_dir", "."), v)
            if not str(v).startswith("http") and os.path.exists(p):
                warns += [f"{u.id}: {w}" for w in check_ref_file(p)]
        if any(len(s.get("lines") or []) > 0 for s in u.shots) and u.audio != "native":
            warns.append(f"{u.id}: has dialogue but audio={u.audio} - lip-sync must then come from post")
    return warns


def check_ref_file(path, max_edge=1024, max_video_mb=100):
    """Upload limits hit in the sessions: 'some image too large' (fixed by <=1024 px long edge JPEG) and a
    100 MB cap on reference videos."""
    out = []
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
        try:
            from PIL import Image
            with Image.open(path) as im:
                if max(im.size) > max_edge * 2:
                    out.append(f"{os.path.basename(path)} is {im.size[0]}x{im.size[1]} - run `generate.py prep-refs` "
                               f"(<= {max_edge} px long edge)")
        except Exception:
            pass
    elif ext in (".mp4", ".mov", ".m4v") and os.path.getsize(path) > max_video_mb * 1e6:
        out.append(f"{os.path.basename(path)} > {max_video_mb} MB - re-encode to 720p before uploading")
    return out


def build(cfg):
    """-> (units, jobs, estimates, total or None, warnings)"""
    units = compile_units(cfg)
    jobs = [unit_job(cfg, u) for u in units]
    prov = get_provider(cfg["provider"])
    ests = [prov.estimate(j, cfg.get("rates")) for j in jobs]
    total = None if any(e is None for e in ests) else round(sum(ests), 2)
    return units, jobs, ests, total, validate(cfg, units, jobs)


def format_plan(cfg, units, jobs, ests, total, warns, show_prompts=True):
    lines = [f"# Generation plan: {cfg.get('title', '(untitled)')}",
             f"provider={cfg['provider']} model={cfg.get('model', '-')} aspect={cfg['aspect']} res={cfg['resolution']}",
             "", "| unit | shots | want s | gen s | refs | est. credits |", "|---|---|---|---|---|---|"]
    for u, j, e in zip(units, jobs, ests):
        lines.append(f"| {u.id} | {','.join(str(s['id']) for s in u.shots)} | {u.dur:g} | {u.gen_dur:g} | "
                     f"{len(j.refs)} | {'unknown' if e is None else f'{e:g}'} |")
    retry = cfg.get("retry_allowance", 0.4)
    lines += ["", f"Estimated total: {'UNKNOWN (rate missing)' if total is None else f'{total:g} credits'}"
                  + ("" if total is None else f"  (+{retry:.0%} retry allowance = {total * (1 + retry):.0f})")]
    if warns:
        lines += ["", "Warnings:"] + [f"- {w}" for w in warns]
    if show_prompts:
        lines += [""] + [f"## {j.unit}\n{j.prompt}\n" for j in jobs]
    return "\n".join(lines)
