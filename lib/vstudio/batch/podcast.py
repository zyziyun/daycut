"""Recipe ``podcast-clips``: a call / interview / video-podcast recording -> masked, captioned vertical clips, one
job per row, through ``workflows/call-clips`` (its scripts run unchanged, as subprocesses, on a per-job
``clips.json`` the batch writes).

    recipe: podcast-clips
    inputs: {source: recordings/my-call.mp4}          # + transcript: an existing whisper JSON (skips ASR)
    segments: segments.yaml                            # plan-segments draft or hand-written rows
    call:
      host_region: "640,180,640,360"                   # x,y,w,h of the host tile (never masked)
      guests: [{name: guest, region: "0,180,640,360", sticker: assets/cat.png, label: "Speaker B"}]
      no_mask: false                                   # true: nobody hidden (then no coverage gate)
      renderer: render_vertical.py                     # | render_trio.py (3 tiles) - vertical renderers only
      name_mask: blur                                  # call-app name labels: blur | cover | off | {...}
      auto_trim: true                                  # shared speech cleanup per window (cut_profile classic)
      host_label: "Speaker A"
      renderer_args: ["scale=2.4"]                     # passed as --renderer-arg (sticker geometry too)
      notes_panels: true                               # rows' notes -> one 记笔记 panel (over the masked tile)
    defaults: {platforms: [xiaohongshu:full, douyin]}

Rows: ``id``, ``start``/``end`` (or ``windows: [[a, b], ...]`` + ``nodes``), ``title``, ``chapter`` (accent line),
``hook`` / ``hooks`` / ``hook_candidates`` / ``pulls: [[a, b], ..]`` (up to 2 cold-open pulls, source s),
``notes``, ``panels``
([anchor_s, dur_s, title, [bullets]]), ``body``, ``tags``, ``platforms``.

Stages (probe / extract / asr shared per recording):
  compose(face: clips.json -> build_clips.py --only <id> --clean-master: selection windows (auto-trimmed), hook
          montage, face tracks + masks / name blur, layout, captions -> caption-free master + cues)
  coverage(cpu: verify_coverage.py on every guest track - the geometric proof that the sticker hides the face on
          every frame; QC gate ``face-mask-coverage``: anything under 100 % is red)
  proofread / export / qc / preview as in the speech recipes (captions re-laid per platform by vstudio.export).
"""
import os
import re
import subprocess
import sys

from . import spec as S
from . import stages as ST
from .recipes import Recipe, Stage, register
from .util import parse_time, read_json, write_json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CC = os.path.join(ROOT, "workflows", "call-clips", "scripts")
LIB = os.path.join(ROOT, "lib")
RENDERERS = ("render_vertical.py", "render_trio.py")


def _call(spec):
    return dict(spec.get("call") or {})


def _script(name, cwd, *args, timeout=None):
    """Run a call-clips script in ``cwd`` (the job's project folder); output -> <name>.log there."""
    env = dict(os.environ)
    env["PYTHONPATH"] = LIB + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, os.path.join(CC, name), *map(str, args)]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout)
    with open(os.path.join(cwd, os.path.splitext(name)[0] + ".log"), "w", encoding="utf-8") as f:
        f.write(" ".join(cmd) + "\n\n" + (r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or ""))
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or ""))[-1500:]
        raise RuntimeError(f"call-clips {name} failed (exit {r.returncode}): {tail}")
    return r.stdout


def _title_lines(title, chapter=None):
    from .lfsplit import _title_parts
    a, b = _title_parts(title or "")
    lines = [[[a, False]]] if a else []
    if b:
        lines.append([[b, True]])
    return lines or [[[chapter or "", False]]]


def _hooks(p):
    if p.get("pulls"):                                 # [[a, b], ...] (expand: hook / hooks / hook_candidates)
        return [[float(a), float(b)] for a, b in p["pulls"]][:2]
    out = []
    for h in ([p.get("hook")] if p.get("hook") else []) + list(p.get("hooks") or []):
        h = S._hook(h) if not (isinstance(h, dict) and h.get("src")) else h
        if h and h.get("src"):
            out.append([float(h["src"][0]), float(h["src"][1])])
    return out[:2]


def clip_config(p, spec, project):
    """Job params + spec -> the call-clips clips.json (one clip: this job)."""
    c = _call(spec)
    windows = p.get("windows") or [list(p["range"])]
    clip = dict(id=p["_clip_id"], title=_title_lines(p.get("title"), p.get("chapter")), accent=p.get("chapter") or "",
                windows=[[float(a), float(b)] for a, b in windows], nodes=list(p.get("nodes") or []),
                hooks=_hooks(p), panels=[list(x) for x in p.get("panels") or []])
    if not clip["panels"] and p.get("notes") and c.get("notes_panels", True) and not c.get("no_mask"):
        a, b = windows[0][0], windows[-1][1]
        clip["panels"] = [[round(a + 0.6 * (b - a), 2), 14.0, p.get("chapter") or "要点",
                           [str(n)[:16] for n in p["notes"][:3]]]]
    cfg = dict(source=p["source"], whisper="work/audio16k.json", audio="work/audio16k.wav",
               auto_trim=bool(c.get("auto_trim", True)), host_region=c.get("host_region"),
               term_fix=[list(x) for x in (spec.get("subtitles") or {}).get("term_fixes") or []], clips=[clip])
    if c.get("guests"):
        cfg["guests"] = [dict(g) for g in c["guests"]]
    elif c.get("guest_region"):
        cfg["guest_region"] = c["guest_region"]
    for k in ("name_mask", "host_label", "guest_label", "cut_profile", "speakers", "track_host", "hook_tail",
              "extra_cuts"):
        if c.get(k) is not None:
            cfg[k] = c[k]
    for k in ("guest_label", "host_label"):
        if p.get(k):
            clip[k] = p[k]
    return cfg


def expand_podcast(spec, rows):
    from vstudio import media
    src = (spec.get("inputs") or {}).get("source")
    if not src:
        raise ValueError("podcast-clips: inputs.source (the call / podcast recording) is required")
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    c = _call(spec)
    if not c.get("host_region"):
        raise ValueError("podcast-clips: call.host_region (x,y,w,h of the host tile) is required")
    if not c.get("no_mask") and not (c.get("guests") or c.get("guest_region")):
        raise ValueError("podcast-clips: call.guests (the tiles to mask) or call.no_mask: true")
    if os.path.basename(c.get("renderer") or "render_vertical.py") not in RENDERERS:
        raise ValueError(f"podcast-clips: call.renderer {c.get('renderer')!r}: {' | '.join(RENDERERS)}")
    total = float(media.probe(src)["duration"])
    items = []
    for r in rows:
        p = S.with_defaults(spec, r)
        if p.get("windows"):
            p["windows"] = [[parse_time(a), parse_time(b)] for a, b in p["windows"]]
            p["range"] = [p["windows"][0][0], p["windows"][-1][1]]
        if not p.get("range"):
            raise ValueError(f"podcast-clips: job {r['id']} has no range (start/end or windows)")
        a, b = max(0.0, p["range"][0]), min(total, p["range"][1])
        if b - a < 1.0:
            raise ValueError(f"job {r['id']}: range {p['range']} is empty / outside the {total:.1f}s recording")
        if not p.get("pulls"):                       # variants drop `hooks`: keep the cold-open pulls apart
            cands = ([p["hook"]] if p.get("hook") else []) + list(p.get("hooks") or []) or \
                list(p.get("hook_candidates") or [])[:2]
            p["pulls"] = [list(h["src"]) for h in (x if isinstance(x, dict) and x.get("src") else S._hook(x)
                                                   for x in cands) if h][:2]
        p.update(range=[a, b], source=src, _clip_id=re.sub(r"[^A-Za-z0-9_-]+", "_", r["id"]))
        hk = sum(h[1] - h[0] for h in _hooks(p))
        span = sum(y - x for x, y in (p.get("windows") or [[a, b]]))
        p["_dur"] = round(span + hk, 3)
        p["_src_dur"] = round(total, 3)
        items.append(dict(item=r["id"], params=p))
    return items


# --------------------------------------------------------------------------- stages
def run_compose_call(ctx):
    """clips.json -> build_clips.py --only <id> --clean-master -> caption-free master + cues + face tracks."""
    from vstudio import media
    from .lfsplit import whisper_json
    p, spec = ctx.params, ctx.spec
    c = _call(spec)
    work = ctx.path("work")
    os.makedirs(work, exist_ok=True)
    whisper_json(ctx.inputs["asr"]["transcript"], os.path.join(work, "audio16k.json"))
    wav = (ctx.inputs.get("extract") or {}).get("wav")
    if wav and os.path.exists(wav):
        media.link_or_copy(wav, os.path.join(work, "audio16k.wav"))
    else:
        media.extract_wav(p["source"], os.path.join(work, "audio16k.wav"), sr=16000, channels=1)
    cfg = clip_config(p, spec, ctx.dir)
    write_json(ctx.path("clips.json"), cfg)
    plats = list(p.get("platforms") or [])
    args = ["--config", "clips.json", "--only", p["_clip_id"], "--clean-master"]
    if c.get("renderer"):
        args += ["--renderer", c["renderer"]]
    if plats:
        args += ["--platform", plats[0]]
    if c.get("no_mask"):
        args.append("--no-mask")
    if c.get("sticker"):
        args += ["--sticker", c["sticker"]]
    for kv in c.get("renderer_args") or []:
        args += ["--renderer-arg", str(kv)]
    if p.get("speed"):
        args += ["--body-speed", str(p["speed"])]
    if p.get("hook_speed"):
        args += ["--hook-speed", str(p["hook_speed"])]
    _script("build_clips.py", ctx.dir, *args)
    cid = p["_clip_id"]
    master = ctx.path("out", f"{cid}.clean.mp4")
    if not os.path.exists(master):
        raise RuntimeError(f"build_clips.py wrote no {os.path.relpath(master, ctx.dir)}")
    raw = read_json(ctx.path("work", f"{cid}.cues.json"), []) or []
    cues_path = write_json(ctx.path("cues.json"), dict(cues=raw))
    guests = cfg.get("guests") or []
    tracks = [dict(name=g.get("name"), track=ctx.path("work", f"{cid}.track.{g['name']}.json"),
                   sticker=g.get("sticker")) for g in guests] if guests else \
        ([dict(name="guest", track=ctx.path("work", f"{cid}.track.json"), sticker=c.get("sticker"))]
         if not c.get("no_mask") else [])
    dur = media.probe(master)["duration"]
    post = dict(title=p.get("title") or "", body=p.get("body") or "", tags=p.get("tags") or None)
    write_json(ctx.path("post.json"), post)
    return dict(master=master, final=master, cues=cues_path, post=ctx.path("post.json"), duration=round(dur, 3),
                tracks=tracks, n_cues=len(raw), files=[master, cues_path])


def coverage_geometry(spec):
    geo = []
    for kv in _call(spec).get("renderer_args") or []:
        k, _, v = str(kv).partition("=")
        if k in ("scale", "y-offset"):
            geo += [f"--{k}", v]
    return geo


def _resolve_sticker(path):
    if path and os.path.exists(path):
        return path
    for base in (os.path.dirname(CC), CC):
        cand = os.path.join(base, path or "assets/cat.png")
        if os.path.exists(cand):
            return cand
    return path


def parse_coverage(text):
    m = re.search(r"worst coverage=([\d.]+)%", text or "")
    return (float(m.group(1)) / 100.0 if m else None), ("PASS" in (text or "") and "FAIL" not in (text or ""))


def run_coverage(ctx):
    """verify_coverage.py on every guest track: the sticker must cover 100 % of the (grown) face box, every frame."""
    tracks = (ctx.inputs.get("compose") or {}).get("tracks") or []
    res = []
    for t in tracks:
        env = dict(os.environ, PYTHONPATH=LIB)
        cmd = [sys.executable, os.path.join(CC, "verify_coverage.py"), "--track", t["track"], "--sticker",
               _resolve_sticker(t.get("sticker")), *coverage_geometry(ctx.spec)]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        worst, ok = parse_coverage(r.stdout)
        res.append(dict(name=t.get("name"), track=t["track"], worst=worst, ok=bool(ok and r.returncode == 0),
                        log=(r.stdout or "")[-400:]))
    path = write_json(ctx.path("coverage.json"), dict(tracks=res))
    return dict(tracks=res, ok=all(x["ok"] for x in res), report=path, files=[path])


def coverage_checks(cov):
    from .qc import _c
    out = []
    for t in (cov or {}).get("tracks") or []:
        out.append(_c("face-mask-coverage", t["ok"], t.get("worst"),
                       f"sticker leaves part of {t.get('name') or 'a'} face visible (worst frame "
                       f"{(t.get('worst') or 0):.1%}); re-track / bigger --scale", target=t.get("name")))
    return out


def run_qc_call(ctx):
    from .qc import run_gates
    res = run_gates(ctx.job, ctx.spec, ctx.inputs, extra=coverage_checks(ctx.inputs.get("coverage")))
    path = write_json(ctx.path("qc.json"), res)
    return dict(res, report=path, files=[path])


def _no_verify(ctx):
    return {}


def _coverage_on(job, spec):
    return not _call(spec).get("no_mask")


def _compose_params(job, spec):
    from .edits import key_copy
    p = job["params"]
    d = {k: p.get(k) for k in ("range", "windows", "nodes", "hook", "pulls", "panels", "notes", "chapter", "speed",
                               "hook_speed", "platforms")}
    d.update({k: key_copy(p, k) for k in ("title", "body", "tags")})
    return dict(d, call=_call(spec), subtitles=spec.get("subtitles"))


def call_stages():
    base = {s.name: s for s in ST.speech_stages()}
    return [
        base["probe"], base["extract"], base["asr"],
        Stage("compose", "face", run_compose_call, deps=("asr", "extract"), params=_compose_params,
              units=lambda j, s: float(j["params"].get("_dur") or 0) * 4.0,
              purge=("work/*.mp4", "work/*.mov", "out/*.mp4")),
        Stage("coverage", "cpu", run_coverage, deps=("compose",), enabled=_coverage_on, units=lambda j, s: 1.0),
        # call-clips cuts from its own TimeMap (no cleanup sidecar to verify against): the lost-word gate is the
        # workflow's own (auto-trim edges are word-safe); proofread still gets its slot
        Stage("verify", "asr", _no_verify, deps=("compose",), enabled=lambda j, s: False),
        base["glossary"], base["proofread"],
        Stage("export", ST._export_resource, ST.run_export, deps=("compose", "proofread"), params=ST._export_params,
              units=lambda j, s: float(j["params"].get("_dur") or 0) * max(1, len(j["params"].get("platforms") or [])),
              purge=("exports/*.mp4",)),
        Stage("qc", "cpu", run_qc_call, deps=("compose", "export", "verify", "coverage"),
              params=lambda j, s: dict(qc=s.get("qc") or {}, title=j["params"].get("title"), recipe=j.get("recipe"),
                                       mask=not _call(s).get("no_mask")),
              units=lambda j, s: 1.0),
        Stage("preview", "cpu-render", ST.run_preview, deps=("export",), units=lambda j, s: 1.0),
    ]


register(Recipe("podcast-clips", call_stages(), expand_podcast,
                "call / interview / video-podcast recording -> masked, captioned vertical clips (workflows/call-clips: "
                "selection, face tracks + stickers, name-label blur, layouts, captions; coverage proof as a QC gate)",
                label="Call / podcast -> masked clips",
                inputs=[dict(key="inputs.source", label="Call recording", kind="file", required=True,
                             accept=ST.VIDEO_ACCEPT, help="Zoom / Meet / podcast video in gallery view"),
                        ST.IN_SEGMENTS, ST.IN_TRANSCRIPT,
                        dict(key="call.host_region", label="Host tile", kind="text", required=True,
                             help="x,y,w,h of the host's tile (not masked)"),
                        dict(key="call.guests", label="Masked guests", kind="text", required=False,
                             help='[{name, region "x,y,w,h", sticker, label}] - or call.no_mask: true')],
                row_keys=ST.COMMON_ROW + ["windows", "nodes", "panels", "notes", "chapter", "hook_candidates"]))
