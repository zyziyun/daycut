"""Recipe ``talkinghead-folder``: a folder of 口播 clips -> one short per clip through the talkinghead V-track
pipeline (``workflows/talkinghead/scripts/vertical``; its scripts run unchanged on per-job files the batch writes):
HDR -> SDR + whisper, every sentence kept, 气口 squeezed + AUTO fillers cut (the cleanup reply cuts the CONFIRM
rows), face track, the compositor (progress bar, captions, the STYLE switches), then ``vstudio.export`` per
platform.

    recipe: talkinghead-folder
    inputs: {folder: raw/, glob: "*.MOV,*.mp4"}        # or clips: [a.mov, b.mov]
    segments: clips.yaml                               # optional rows: file, title, body, tags, cleanup_reply, skip
    talkinghead:                                       # all optional
      style: {progress: classic, zoom: false}          # compose.py STYLE switches (default: its notes-board look)
      keywords: [RAG, LLM]                             # yellow keywords in captions
      hook_speed: 1.5                                  # else the talking-head format (vstudio.formats)
      body_speed: 1.25
      face: true                                       # face track (punch-in caps, overlays off the face)
    defaults: {platforms: [xiaohongshu:full, douyin]}

Stages: probe -> asr(prep_sources.sh -> sdr1.mp4, a1.wav, a1.json) -> cleanup(cpu-render: edit_list.py with
every whisper sentence -> cut_pass1.py (word-safe edges, 气口) -> strict_pass.py apply (AUTO rows + the job's
``cleanup_reply``); the review page lists the CONFIRM rows) -> face(face: face_track.py) -> compose(cpu-render:
config.py -> compose.py all --clean-master: caption-free master + cues with keep-outs) -> proofread -> export ->
qc -> preview. The verify re-hearing of the V track is ``strict_pass.py verify`` (manual); the batch's lost-word
gate is skipped here.
"""
import os
import subprocess
import sys

from . import stages as ST
from .recipes import Recipe, Stage, register
from .util import read_json, write_json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
VDIR = os.path.join(ROOT, "workflows", "talkinghead", "scripts", "vertical")
LIB = os.path.join(ROOT, "lib")


def _th(spec):
    return dict(spec.get("talkinghead") or {})


def _run(cmd, cwd, log, env=None, timeout=None):
    e = dict(os.environ)
    e["PYTHONPATH"] = LIB + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e.update(env or {})
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, env=e, timeout=timeout)
    with open(os.path.join(cwd, log), "w", encoding="utf-8") as f:
        f.write(" ".join(map(str, cmd)) + "\n\n" + (r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or ""))
    if r.returncode != 0:
        raise RuntimeError(f"talkinghead {os.path.basename(str(cmd[1]))} failed (exit {r.returncode}): "
                           f"{((r.stderr or '') + (r.stdout or ''))[-1500:]}")
    return r.stdout


def _py(script, *args):
    return [sys.executable, os.path.join(VDIR, script), *args]


def _link(src, dst):
    from vstudio import media
    return media.link_or_copy(src, dst)


# --------------------------------------------------------------------------- per-job files
def sentence_spans(whisper, rng=None):
    """[[t0, t1, text], ...] in source seconds, index = sid (the rows ``edit_list`` writes)."""
    return [[r[1][0][0], r[1][0][1], r[2]] for r in _rows(whisper, rng)]


def edit_list(whisper, profile=None, rng=None):
    """Every whisper sentence of clip 1 kept (within ``rng`` = the job's [start, end] when set - ``job edit --op
    trim``): E = [(1, [(t0, t1)], text), ...] (sid = list index)."""
    rows = _rows(whisper, rng)
    if not rows:
        raise ValueError(f"{whisper}: no sentences (silent clip?)")
    head = "# written by vstudio.batch talkinghead-folder: every whisper sentence kept (sid = index)\n"
    if profile:
        head += f"PROFILE = {profile!r}\n"
    return head + "E = [\n" + "".join(f"    {r!r},\n" for r in rows) + "]\n", len(rows)


def _rows(whisper, rng=None):
    data = read_json(whisper, {}) or {}
    rows = []
    for s in data.get("segments") or []:
        ws = [w for w in s.get("words") or [] if str(w.get("word", "")).strip()]
        if not ws:
            continue
        t0, t1 = float(ws[0]["start"]), float(ws[-1]["end"])
        text = "".join(str(w["word"]).strip() for w in ws) if not any(
            str(w["word"]).startswith(" ") for w in ws[1:]) else "".join(str(w["word"]) for w in ws).strip()
        if rng and not (float(rng[0]) - 0.05 <= (t0 + t1) / 2 <= float(rng[1]) + 0.05):
            continue
        if t1 - t0 >= 0.15 and text:
            rows.append((1, [(round(t0, 3), round(t1, 3))], text))
    return rows


def strict_file(reply):
    return ("# written by vstudio.batch talkinghead-folder: the creator's answer to cleanup_review.md\n"
            f"REPLY = {str(reply or '')!r}\n")


def hook_ranges(hook, sids, subs):
    """The picked hook (source seconds, ``hook.src``) -> HOOKS ranges on the cleaned body: the sentences it covers
    (by sid) at their body times. [] when it covers none (cut away / out of the job's range)."""
    if not hook or not hook.get("src"):
        return []
    s0, s1 = (float(x) for x in hook["src"])
    keep = set()
    for sid, (t0, t1, _txt) in enumerate(sids or []):
        ov = min(s1, t1) - max(s0, t0)
        if ov > 0 and ov >= 0.5 * (t1 - t0):
            keep.add(sid)
    body = [(float(x["start"]), float(x["end"])) for x in subs or [] if x.get("sid") in keep]
    if not body:
        return []
    return [[(round(min(a for a, _ in body), 3), round(max(b for _, b in body), 3))]]


def draft_notes(subs, platforms, glossary=None, term_fixes=None, complete=None):
    """记笔记 panels, progress-bar chapters, highlight keywords and the post title drafted from the cleaned body's
    sentences (vstudio.clipcopy: the ``copy`` model when one is routed), after the glossary / persona term fixes so
    a card never shows an ASR slip."""
    from vstudio import asr, clipcopy
    from vstudio import proofread as PR
    fixes = (glossary or {}).get("fixes") or []
    sents = []
    for x in clipcopy.sentences_from_subs(subs):
        t = asr.apply_term_fixes(x["text"], term_fixes or None, clean=False)
        sents.append(dict(x, text=PR.apply_glossary(t, fixes) if fixes else t))
    return clipcopy.draft(sents, platforms, glossary_terms=(glossary or {}).get("terms") or [], complete=complete)


def config_file(p, spec, has_face, hooks=None, notes=None):
    th = _th(spec)
    plats = list(p.get("platforms") or [])
    lines = ["# written by vstudio.batch talkinghead-folder (compose.py config)",
             'BODY = "body2_v.mp4"', 'AUDIO = "body2_a.wav"', f'OUT = "out/{p["_clip_id"]}.mp4"',
             f"HOOKS = {list(hooks or [])!r}"]
    if has_face:
        lines.append('FACE = "face.npy"')
    if plats:
        lines.append(f"PLATFORM = {plats[0]!r}")
    style = dict(th.get("style") or {})
    style.update(p.get("style") or {})
    if style:
        lines.append(f"STYLE = {style!r}")
    kw = list(th.get("keywords") or []) + list(p.get("keywords") or []) + list((notes or {}).get("keywords") or [])
    if kw:
        lines.append(f"KEYWORDS = {list(dict.fromkeys(kw))!r}")
    if notes and notes.get("panels"):
        lines.append(f"PANELS = {[tuple(x) for x in notes['panels']]!r}")
    if notes and notes.get("chapters"):
        lines.append(f"CHAPTERS = {[tuple(x) for x in notes['chapters']]!r}")
    hs = p.get("hook_speed") or th.get("hook_speed")
    bs = p.get("speed") if p.get("speed") is not None else th.get("body_speed")     # 1.0 = no speed-up, kept
    if hs:
        lines.append(f"HOOK_SPEED = {float(hs)!r}")
    if bs:
        lines.append(f"BODY_SPEED = {float(bs)!r}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- stages
def run_prep(ctx):
    p = ctx.params
    o = ST._asr_opts(ctx.job, ctx.spec)
    env = {"PLATFORM": (list(p.get("platforms") or ["xiaohongshu:full"])[0]).split(":")[0]}
    if o.get("prompt"):
        env["PROMPT"] = str(o["prompt"])
    if _th(ctx.spec).get("orient"):
        env["ORIENT"] = _th(ctx.spec)["orient"]
    _run(["bash", os.path.join(VDIR, "prep_sources.sh"), ctx.dir, p["source"]], ctx.dir, "prep_sources.log", env)
    files = [ctx.path(f) for f in ("sdr1.mp4", "a1.wav", "a1.json")]
    for f in files:
        if not os.path.exists(f):
            raise RuntimeError(f"prep_sources.sh wrote no {os.path.basename(f)}")
    out = dict(sdr=files[0], wav=files[1], whisper=files[2], transcript=files[2], files=files)
    if os.path.exists(ctx.path("prep.json")):
        out["prep"] = ctx.path("prep.json")
    return out


def run_cleanup_th(ctx):
    pr, p = ctx.inputs["asr"], ctx.params
    for k, name in (("sdr", "sdr1.mp4"), ("wav", "a1.wav"), ("whisper", "a1.json")):
        _link(pr[k], ctx.path(name))
    if pr.get("prep"):
        _link(pr["prep"], ctx.path("prep.json"))
    prof = p.get("cleanup_profile")
    txt, n = edit_list(ctx.path("a1.json"), None if prof in (None, "off") else prof, p.get("range"))
    with open(ctx.path("edit_list.py"), "w", encoding="utf-8") as f:
        f.write(txt)
    write_json(ctx.path("sids.json"), sentence_spans(ctx.path("a1.json"), p.get("range")))
    with open(ctx.path("strict.py"), "w", encoding="utf-8") as f:
        f.write(strict_file(p.get("cleanup_reply")))
    _run(_py("cut_pass1.py", "edit_list.py"), ctx.dir, "cut_pass1.log")
    _run(_py("strict_pass.py", "apply", "strict.py", "body_v.mp4", "body_a.wav", "body2_v.mp4", "body2_a.wav"),
         ctx.dir, "strict_pass.log")
    edl = ctx.path("cleanup.c1.json")
    E = read_json(edl, {}) or {}
    confirm = [dict(id=e["id"], part="body", kind=e.get("kind"), text=e.get("text", ""), t0=e["t0"], t1=e["t1"],
                    reason=e.get("reason", "")) for e in E.get("edits") or [] if e.get("action") == "confirm"]
    write_json(ctx.path("confirm.json"), confirm)
    files = [ctx.path(f) for f in ("body2_v.mp4", "body2_a.wav", "segs.json", "sids.json")]
    return dict(body=edl if os.path.exists(edl) else None, sentences=n, confirm=len(confirm),
                confirm_file=ctx.path("confirm.json"), review=ctx.path("cleanup_review.md"),
                video=files[0], audio=files[1], segs=files[2], sids=files[3], files=files)


def run_face_th(ctx):
    cl = ctx.inputs["cleanup"]
    if _th(ctx.spec).get("face", True) is False:
        return dict(face=None, files=[])
    try:
        _run(_py("face_track.py", cl["video"], ctx.path("face.npy")), ctx.dir, "face_track.log")
    except RuntimeError as e:                         # no face model / no face: compose works without it
        ctx.log(f"face track skipped: {str(e)[:200]}")
        return dict(face=None, files=[])
    return dict(face=ctx.path("face.npy"), files=[ctx.path("face.npy")])


def run_compose_th(ctx):
    from vstudio import media
    cl, fc, p = ctx.inputs["cleanup"], ctx.inputs.get("face") or {}, ctx.params
    for src, name in ((cl["video"], "body2_v.mp4"), (cl["audio"], "body2_a.wav"), (cl["segs"], "segs.json")):
        _link(src, ctx.path(name))
    prep = os.path.join(os.path.dirname(cl["segs"]), "prep.json")
    if os.path.exists(prep):
        _link(prep, ctx.path("prep.json"))
    if fc.get("face"):
        _link(fc["face"], ctx.path("face.npy"))
    os.makedirs(ctx.path("out"), exist_ok=True)
    subs = (read_json(ctx.path("segs.json"), {}) or {}).get("subs") or []
    hooks = hook_ranges(p.get("hook"), read_json(cl.get("sids") or "", []) if cl.get("sids") else [], subs)
    if p.get("hook") and not hooks:
        ctx.log("hook: the picked sentences were cut from the body; no hook montage")
    notes = None
    if p.get("note_cards", True) is not False:
        g = (ctx.inputs.get("glossary") or {}).get("glossary")
        call = ST.import_ref(_th(ctx.spec)["notes_call"]) if _th(ctx.spec).get("notes_call") else None
        try:
            notes = draft_notes(subs, p.get("platforms"), read_json(g, {}) if g else None,
                                (ctx.spec.get("subtitles") or {}).get("term_fixes"), complete=call)
        except Exception as e:                        # noqa: BLE001 - reported, the render goes on without cards
            notes = dict(title="", keywords=[], chapters=[], panels=[], source=None,
                         notes=[f"notes not drafted: {type(e).__name__}: {str(e)[:300]}"])
        write_json(ctx.path("notes.json"), notes)
        ctx.log(f"notes ({notes.get('source') or 'failed'}): {len(notes['panels'])} panel(s), "
                f"{len(notes['chapters'])} chapter(s), keywords {', '.join(notes['keywords']) or '-'}"
                + "".join(f"; {n}" for n in notes.get("notes") or []))
    with open(ctx.path("config.py"), "w", encoding="utf-8") as f:
        f.write(config_file(p, ctx.spec, bool(fc.get("face")), hooks, notes))
    _run(_py("compose.py", ctx.path("config.py"), "all", "--clean-only"), ctx.dir, "compose.log")
    cid = p["_clip_id"]
    master = ctx.path("out", f"{cid}.clean.mp4")
    cj = ctx.path("out", f"{cid}.cues.json")
    if not os.path.exists(master):
        raise RuntimeError("compose.py wrote no clean master")
    d = read_json(cj, {}) or {}
    cues_path = write_json(ctx.path("cues.json"), dict(d, cues=d.get("cues") or []))
    post = dict(title=p.get("title") or "", body=p.get("body") or "", tags=p.get("tags") or None)
    write_json(ctx.path("post.json"), post)
    hook_dur = read_json(ctx.path("timeline.json"), {}).get("BODY_START", 0.0) if hooks else 0.0
    return dict(master=master, final=master, cues=cues_path, post=ctx.path("post.json"),
                duration=round(media.probe(master)["duration"], 3), n_cues=len(d.get("cues") or []),
                hook_dur=round(float(hook_dur or 0.0), 3), notes=ctx.path("notes.json") if notes else None,
                notes_warnings=list((notes or {}).get("notes") or []),
                files=[master, cues_path])


def expand_folder(spec, rows):
    import re
    items = ST.expand_clips(spec, rows)
    for it in items:
        it["params"]["_clip_id"] = re.sub(r"[^A-Za-z0-9_-]+", "_", it["item"])
    return items


def _no_verify(ctx):
    return {}


def _keys(*ks):
    return lambda j, s: {k: j["params"].get(k) for k in ks}


def _compose_params(job, spec):
    from .edits import key_copy
    d = _keys("platforms", "speed", "hook_speed", "style", "keywords", "hook", "note_cards")(job, spec)
    d.update({k: key_copy(job["params"], k) for k in ("title", "body", "tags")})
    th = {k: v for k, v in _th(spec).items() if k not in ("orient", "face")}
    if d.get("note_cards") is not False:              # the drafted cards follow the routed copy model
        from vstudio import llm
        th["copy_route"] = llm.route("copy").provider
    return dict(d, th=th)


def th_stages():
    base = {s.name: s for s in ST.speech_stages()}
    dur = lambda j, s: float(j["params"].get("_dur") or 0)  # noqa: E731
    return [
        base["probe"],
        Stage("asr", "asr", run_prep, deps=("probe",), units=dur,
              params=lambda j, s: dict(ST._asr_opts(j, s), platform=(j["params"].get("platforms") or [None])[0],
                                       orient=_th(s).get("orient")), purge=("sdr1.mp4", "a1.wav")),
        Stage("cleanup", "cpu-render", run_cleanup_th, deps=("asr",), units=dur,
              params=_keys("cleanup_reply", "cleanup_profile", "range"), purge=("body_v.mp4", "*.wav"), version=2),
        Stage("face", "face", run_face_th, deps=("cleanup",), units=dur, params=lambda j, s: dict(on=_th(s).get("face", True))),
        base["glossary"],                             # before compose: the drafted 记笔记 cards use its fixes
        Stage("compose", "cpu-render", run_compose_th, deps=("cleanup", "face", "glossary"),
              units=lambda j, s: dur(j, s) * 3, params=_compose_params, purge=("*.mp4", "out/*.mp4"), version=4),
        Stage("verify", "asr", _no_verify, deps=("compose",), enabled=lambda j, s: False),
        base["proofread"],
        ST.copy_stage(),                              # post title + body drafted from the final captions
        Stage("export", ST._export_resource, ST.run_export, deps=("compose", "proofread", "copy"),
              params=ST._export_params,
              units=lambda j, s: dur(j, s) * max(1, len(j["params"].get("platforms") or [])),
              purge=("exports/*.mp4",)),
        Stage("qc", "cpu", ST.run_qc, deps=("compose", "export", "verify"),
              params=lambda j, s: dict(qc=s.get("qc") or {}, title=j["params"].get("title"), recipe=j.get("recipe")),
              units=lambda j, s: 1.0),
        Stage("preview", "cpu-render", ST.run_preview, deps=("export",), units=lambda j, s: 1.0),
    ]


register(Recipe("talkinghead-folder", th_stages(), expand_folder,
                "a folder of 口播 clips -> one short per clip through the talkinghead V pipeline (去气口 / fillers, "
                "captions, progress bar and the STYLE switches, face-aware layout) + per-platform exports",
                label="口播 folder -> styled shorts",
                inputs=[dict(key="inputs.folder", label="Clip folder", kind="dir", required=True,
                             help="raw talking-head clips (iPhone HDR is tone-mapped); or inputs.clips: a list"),
                        dict(key="inputs.glob", label="File pattern", kind="text", required=False),
                        dict(ST.IN_SEGMENTS, required=False, help="optional per-clip rows (file, title, cleanup_reply)")],
                row_keys=ST.COMMON_ROW + ["file", "skip", "style", "keywords"]))
