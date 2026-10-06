"""Shared adapters: the checkpoint payload / apply pairs most recipes use, candidate stages (hooks, cover frames)
and output collectors.

Checkpoints
  author      a file the human / agent writes (script, spec, edit list, timeline): payload = the path, whether it
              exists, its template + format doc; answer {done: true} or {content: "..."} (written for you). The
              digest is the file's hash, so a later edit (by the agent) asks again and re-runs what depends on it.
  publish     final look: exports, cover, post copy, QC; answer {approve: true} / {approve: false, reason}.
  filler      the cleanup CONFIRM rows of a speech recipe (vstudio.cleanup): answer {approve: [ids], keep: [ids],
              kinds: [kind...], all: bool} -> the item's ``cleanup_reply`` ("确认 3,5 / 保留 7").
  hook        ranked cold-open candidates from the transcript: answer {pick: k} (-1 = no hook) or
              {start, end, text} -> the item's ``hook``.
  cover       candidate frames of the composed master: answer {pick: k, text: "a|b"} or {t: s, text} -> a
              frame + text card -> the item's ``cover`` (export uses the file).
  choice      generic single-pick over options -> ``set`` param.
"""
import json
import os
import re
import shutil
import subprocess

from vstudio.batch.util import read_json, sha1_json, write_json

from .. import manifests as M
from ..build import file_sha, static_tctx


# --------------------------------------------------------------------------- author
def _author_path(env_or_ctx, cp):
    m = env_or_ctx.m
    return M.fmt(cp["author"]["file"], static_tctx(m, env_or_ctx.params, env_or_ctx.job))


def author_payload(env, cp):
    a = cp["author"]
    path = _author_path(env, cp)
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    text = None
    if exists and os.path.getsize(path) < 200_000:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            text = None
    return dict(file=path, exists=exists, template=os.path.join(M.ROOT, a["template"]) if a.get("template") else None,
                format=a.get("format"), doc=os.path.join(M.ROOT, a["doc"]) if a.get("doc") else None,
                content=text, options=[dict(file=path, sha=file_sha(path))], digest=file_sha(path) or "missing",
                default=dict(done=True) if exists else None,
                previews=[dict(kind="text", path=path)] if exists else [])


def author_apply(a):
    path = a.payload.get("file") or M.fmt(a.cp["author"]["file"], a.tctx())
    v = a.value or {}
    if v.get("content") is not None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(v["content"])
    if not os.path.exists(path):
        raise ValueError(f"{a.cp['id']}: {path} does not exist yet - write it (or answer with content)")
    return dict(params={}, digest=file_sha(path))


# --------------------------------------------------------------------------- publish
def _exports_of(env):
    ex = (env.inputs.get("export") or {}).get("exports") or []
    return [dict(platform=e.get("platform"), orientation=e.get("orientation"), file=e.get("file"),
                 cover=e.get("cover"), post=e.get("post"), duration=e.get("duration")) for e in ex]


def publish_payload(env, cp):
    files = []
    for dep, out in (env.inputs or {}).items():
        files += [f for f in (out or {}).get("files") or [] if os.path.exists(str(f))]
    exports = _exports_of(env)
    qc = env.inputs.get("qc") or {}
    previews = []
    for e in exports:
        previews += [dict(kind="video", path=e["file"], platform=e["platform"])]
        if e.get("cover"):
            previews.append(dict(kind="image", path=e["cover"], platform=e["platform"]))
    if not previews:
        previews = [dict(kind=_kind_of(f), path=f) for f in files[:12]]
    pv = env.inputs.get("preview") or {}
    for k in ("sheet", "snippet"):
        if pv.get(k):
            previews.append(dict(kind="image" if k == "sheet" else "video", path=pv[k]))
    p = env.params
    return dict(options=[dict(file=x["path"], sha=file_sha(x["path"])) for x in previews],
                exports=exports, qc=dict(status=qc.get("status"), reasons=qc.get("reasons") or [],
                                         warnings=qc.get("warnings") or []),
                copy=dict(title=p.get("title"), body=p.get("body"), tags=p.get("tags")),
                default=dict(approve=True) if qc.get("status") != "red" else None, previews=previews)


def publish_apply(a):
    return dict(params={}, review="approved" if (a.value or {}).get("approve") else "needs-replan",
                reason=(a.value or {}).get("reason"))


def _kind_of(path):
    ext = os.path.splitext(str(path))[1].lower()
    if ext in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
        return "video"
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return "image"
    if ext in (".wav", ".m4a", ".mp3", ".aac"):
        return "audio"
    if ext in (".md", ".txt", ".srt"):
        return "text"
    if ext == ".json":
        return "json"
    if ext == ".html":
        return "html"
    return "file"


# --------------------------------------------------------------------------- filler confirm (vstudio.cleanup)
def filler_payload(env, cp):
    out = env.inputs.get(cp["after"]) or {}
    cf = out.get("confirm_file")
    rows = read_json(cf, []) if cf else []
    opts = [dict(id=int(e["id"]), kind=e.get("kind"), part=e.get("part", "body"), text=e.get("text", ""),
                 t0=e.get("t0"), t1=e.get("t1"), before=e.get("before", ""), after=e.get("after", ""),
                 reason=e.get("reason", ""), confidence=e.get("confidence")) for e in rows or []]
    kinds = {}
    for o in opts:
        kinds.setdefault(o["kind"] or "?", []).append(o["id"])
    previews = [dict(kind="markdown", path=f) for f in (out.get("review"),) if f and os.path.exists(f)]
    for f in os.listdir(os.path.dirname(cf)) if cf and os.path.exists(cf) else []:
        if f.endswith("_review.md"):
            previews.append(dict(kind="markdown", path=os.path.join(os.path.dirname(cf), f)))
    return dict(options=opts, kinds=kinds, auto_cuts=out.get("auto"), saved_s=out.get("saved_s"),
                source=env.params.get("source"), default=dict(approve=[], keep=[]), previews=previews,
                skip=not opts, skip_reason="no CONFIRM edits (only AUTO cuts)")


def reply_from(value, options):
    """{approve, keep, kinds, all} -> the vstudio.cleanup reply text ("确认 3,5 / 保留 7", "全部确认")."""
    v = value or {}
    if v.get("all"):
        keep = sorted(set(int(x) for x in v.get("keep") or []))
        return "全部确认" + (f" / 保留 {','.join(map(str, keep))}" if keep else "")
    ids = set(int(x) for x in v.get("approve") or [])
    kinds = set(v.get("kinds") or [])
    for o in options or []:
        k = o.get("kind") or ""
        if any(k == x or k.startswith(x + "/") or k.startswith(x + "-") for x in kinds):
            ids.add(int(o["id"]))
    keep = set(int(x) for x in v.get("keep") or []) - ids
    parts = []
    if ids:
        parts.append("确认 " + ",".join(map(str, sorted(ids))))
    if keep:
        parts.append("保留 " + ",".join(map(str, sorted(keep))))
    return " / ".join(parts)


def filler_apply(a):
    return dict(params=dict(cleanup_reply=reply_from(a.value, a.payload.get("options")) or None))


# --------------------------------------------------------------------------- hooks (cold open candidates)
HOOK_CUES = ("其实", "但是", "千万", "一定", "为什么", "不是", "没想到", "关键", "核心", "最", "秘密", "错",
             "真相", "竟然", "因为", "所以", "you", "never", "why", "secret", "mistake", "actually")
OPENERS = ("然后", "所以", "那", "就是", "而且", "and ", "so ", "then ")


def _transcript_of(env):
    for dep in ("asr", "transcribe"):
        out = env.inputs.get(dep) or {}
        for k in ("transcript", "whisper"):
            if out.get(k) and os.path.exists(out[k]):
                return out[k]
    return None


def rank_hooks(transcript, n=6, min_s=1.8, max_s=9.0, rng=None):
    """Sentences of the transcript that work as a cold open: 2-9 s, no leading connective, a contrast / number /
    question cue scores up. -> [{index, start, end, text, dur, score}] best first."""
    from vstudio.batch.segplan import sentences_of
    from vstudio.cleanup import load_words
    W = load_words(transcript)
    if not W:
        return []
    sents = sentences_of(W, max_len=max_s)
    out = []
    for s in sents:
        d = s["te"] - s["t"]
        if not min_s <= d <= max_s:
            continue
        if rng and not (rng[0] - 0.05 <= s["t"] and s["te"] <= rng[1] + 0.05):
            continue
        txt = s["text"].strip()
        low = txt.lower()
        sc = 1.0 - abs(d - 4.5) / 9.0
        sc += 0.6 * sum(c in low for c in HOOK_CUES)
        sc += 0.5 if re.search(r"\d|[一二三四五六七八九十百千万两]+[个种点步年倍]", txt) else 0
        sc += 0.4 if re.search(r"[?？吗呢]$", txt) else 0
        sc -= 0.8 if low.startswith(OPENERS) else 0
        sc -= 0.3 * (s["k"] == 0)
        out.append(dict(start=round(s["t"], 3), end=round(s["te"], 3), text=txt, dur=round(d, 2),
                        score=round(sc, 3)))
    out.sort(key=lambda h: -h["score"])
    out = out[:n]
    for k, h in enumerate(out):
        h["index"] = k
    return out


def hook_candidates(env):
    tr = _transcript_of(env)
    if not tr:
        raise RuntimeError("hook candidates: no transcript from the asr stage")
    hooks = rank_hooks(tr, n=int(env.params.get("hook_count") or 6), rng=env.params.get("range"))
    path = write_json(env.path("hooks.json"), dict(candidates=hooks, transcript=tr))
    return dict(candidates=path, n=len(hooks), files=[path])


def hook_payload(env, cp):
    out = env.inputs.get(cp["after"]) or {}
    c = (read_json(out.get("candidates"), {}) or {}).get("candidates") if out.get("candidates") else []
    pick = env.params.get("hook_default", -1)
    return dict(options=c or [], default=dict(pick=int(pick) if c else -1),
                previews=[dict(kind="json", path=out.get("candidates"))] if out.get("candidates") else [],
                skip=not c, skip_reason="no hook-worthy sentence")


def hook_apply(a):
    v = a.value or {}
    if "start" in v and "end" in v:
        h = dict(src=[float(v["start"]), float(v["end"])], lines=[v["text"]] if v.get("text") else [])
        return dict(params=dict(hook=h))
    k = int(v.get("pick", -1))
    if k < 0:
        return dict(params=dict(hook=None))
    opts = a.payload.get("options") or []
    if k >= len(opts):
        raise ValueError(f"hook: pick {k} out of range (0..{len(opts) - 1})")
    o = opts[k]
    return dict(params=dict(hook=dict(src=[o["start"], o["end"]], lines=[v.get("text") or o["text"]])))


# --------------------------------------------------------------------------- cover frames
def grab_frame(video, t, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1",
                    "-q:v", "2", out], check=True)
    return out


def cover_frames(env):
    """Candidate cover frames of the composed (caption-free) master: face-ranked when a face model is there
    (``vstudio.cover.score_frames``), else evenly spaced; + a contact sheet."""
    from vstudio import media
    comp = env.inputs.get("compose") or {}
    video = comp.get("master") or comp.get("final") or env.params.get("source")
    if not video or not os.path.exists(video):
        raise RuntimeError("cover frames: no composed master")
    dur = media.duration(video)
    n = int(env.params.get("cover_candidates") or 6)
    ts = []
    if env.params.get("cover_face_rank", True):
        try:
            from vstudio.cover import score_frames
            ts = [p["t"] for p in score_frames(video, top_n=n, step=6, min_gap=max(1.0, dur / (2 * n)))]
        except Exception as e:  # noqa: BLE001  (no face model / no face: evenly spaced frames)
            env.log(f"face ranking skipped: {str(e)[:120]}")
    if not ts:
        ts = [dur * (k + 0.5) / n for k in range(n)]
    cands = []
    for k, t in enumerate(ts):
        f = grab_frame(video, t, env.path(f"cand_{k}.jpg"))
        cands.append(dict(index=k, t=round(t, 3), image=f))
    sheet = env.path("sheet.jpg")
    try:
        media.contact_sheet(video, sheet, every=max(0.5, dur / 8), cols=4, thumb_w=200, max_frames=8)
    except Exception:  # noqa: BLE001
        sheet = None
    path = write_json(env.path("cover_candidates.json"), dict(video=video, candidates=cands))
    return dict(candidates=path, video=video, sheet=sheet, files=[path] + [c["image"] for c in cands])


def cover_payload(env, cp):
    out = env.inputs.get(cp["after"]) or {}
    d = read_json(out.get("candidates"), {}) or {}
    c = d.get("candidates") or []
    title = env.params.get("cover_text") or env.params.get("title") or ""
    return dict(options=[dict(index=x["index"], t=x["t"], image=x["image"]) for x in c], video=d.get("video"),
                default=dict(pick=0, text=title) if c else None,
                previews=[dict(kind="image", path=x["image"]) for x in c], skip=not c)


def cover_apply(a):
    from vstudio.batch.edits import _text_cover
    v = a.value or {}
    opts = a.payload.get("options") or []
    if "t" in v:
        frame = grab_frame(a.payload["video"], float(v["t"]), a.answer_path(f"cover_frame_{int(float(v['t']) * 1000)}.jpg"))
        t = float(v["t"])
    else:
        k = int(v.get("pick", 0))
        if not 0 <= k < len(opts):
            raise ValueError(f"cover: pick {k} out of range")
        frame, t = opts[k]["image"], opts[k]["t"]
    text = v.get("text") or ""
    out = a.answer_path(f"cover_{int(t * 1000)}_{sha1_json(text)[:8]}.jpg")
    _text_cover(frame, text, out)
    return dict(params=dict(cover=dict(file=out, t=t, text=text)))


# --------------------------------------------------------------------------- generic choice
def choice_payload(env, cp):
    out = env.inputs.get(cp["after"]) or {}
    opts = out.get("options") or []
    if out.get("options_file"):
        opts = read_json(out["options_file"], []) or []
    return dict(options=opts, default=dict(pick=0) if opts else None,
                previews=[dict(kind=_kind_of(o.get("path")), path=o.get("path")) for o in opts if o.get("path")],
                skip=not opts)


def choice_apply(a):
    k = int((a.value or {}).get("pick", 0))
    opts = a.payload.get("options") or []
    if not 0 <= k < len(opts):
        raise ValueError("pick out of range")
    o = opts[k]
    return dict(params=dict(o.get("set") or {}))


# --------------------------------------------------------------------------- collectors
def collect_batch_exports(project, job, rows):
    ex = ((rows.get("export") or {}).get("out") or {}).get("exports") or []
    return [dict(platform=e.get("platform"), orientation=e.get("orientation"), kind="video", file=e.get("file"),
                 cover=e.get("cover"), post=e.get("post"), duration=e.get("duration")) for e in ex]


def collect_files(project, job, rows):
    """``outputs.files`` templates of the manifest (item dir relative), the ones that exist."""
    m = project.manifest
    t = static_tctx(m, job["params"], job["id"])
    out = []
    for tpl in m["outputs"].get("files") or []:
        try:
            p = M.fmt(tpl, t)
        except M.Missing:
            continue
        for f in sorted(_glob(p)):
            out.append(dict(platform=None, orientation=None, kind=_kind_of(f), file=f))
    return out


def _glob(p):
    import glob as G
    return [x for x in G.glob(p) if os.path.isfile(x)] if any(c in p for c in "*?[") else ([p] if os.path.isfile(p) else [])


def collect_all(project, job, rows):
    return collect_batch_exports(project, job, rows) + collect_files(project, job, rows)


def copy_into(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
