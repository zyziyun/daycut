"""Planner recipes (long recordings -> N items): longform-to-short slices, call-clips, the batch board.

  plan_items(project)    items from ``inputs.segments`` (a segments.yaml / CSV a human or agent wrote) or from
                         ``python -m vstudio.batch plan-segments`` (rule-based / any vstudio.llm provider; the CLI
                         is run unchanged, as a subprocess) -> draft rows {range, title, chapter, hook, notes, ...}
  segments checkpoint    project scope: every draft segment as an option; answer {approve: "all" | [ids],
                         drop: [ids], edits: {id: {start, end, title, hook}}} -> items edited / dropped in
                         project.yaml (the batch drops their jobs)
  privacy checkpoint     longform-split: the geometry frame + the screen crop + current excludes; answer
                         {confirm: true} or {exclude: [[x0, y0, x1, y1], ...]} -> spec privacy.exclude
  masks checkpoint       call-clips: face-mask coverage per guest track (verify_coverage.py) + preview frames;
                         answer {ok: true} | {ok: false, no_mask, guests} -> the call: section, re-render
"""
import json
import os
import subprocess
import sys

from vstudio.batch.util import read_json, sha1_json

from .. import manifests as M

SEG_KEYS = ("title", "chapter", "hook", "hook_candidates", "notes", "tags", "why", "risk", "score", "body", "cuts")


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _rows_from_file(path):
    from vstudio.batch import spec as S
    rows = S.read_rows(path, os.path.dirname(os.path.abspath(path)))
    out = []
    for r in rows:
        p = {k: v for k, v in r.items() if k not in ("id", "_auto_id")}
        out.append(dict(id=r["id"], params=p))
    return out


def plan_items(project, provider=None, count=None, min_s=None, max_s=None):
    ins = project.data.get("inputs") or {}
    P = project.params()
    seg = _first(ins.get("segments"))
    if seg:
        return _rows_from_file(seg)
    src = _first(ins.get("source"))
    if not src:
        raise ValueError("plan-items: inputs.source (the recording) or inputs.segments is required")
    out_dir = os.path.join(project.dir, "plan")
    cmd = [sys.executable, "-m", "vstudio.batch", "plan-segments", "--source", src, "--out", out_dir, "--json",
           "--provider", provider or P.get("planner") or "auto"]
    tr = _first(ins.get("transcript"))
    if tr:
        cmd += ["--transcript", tr]
    for flag, v in (("--count", count or P.get("count")), ("--min", min_s or P.get("min_s")),
                    ("--max", max_s or P.get("max_s"))):
        if v:
            cmd += [flag, str(v)]
    if P.get("platforms"):
        cmd += ["--platforms", ",".join(P["platforms"])]
    if project.data.get("client"):
        cmd += ["--client", project.data["client"]]
    e = dict(os.environ)
    e["PYTHONPATH"] = os.path.join(M.ROOT, "lib") + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    r = subprocess.run(cmd, capture_output=True, text=True, env=e)
    if r.returncode != 0:
        raise ValueError(f"plan-segments failed (exit {r.returncode}): {(r.stdout + r.stderr)[-800:]}")
    d = json.loads(r.stdout)
    rows = []
    for s in d.get("segments") or []:
        p = dict(range=[float(s["start"]), float(s["end"])], **{k: s[k] for k in SEG_KEYS if s.get(k) is not None})
        if isinstance(p.get("hook"), dict) and "start" in p["hook"]:
            h = p["hook"]
            p["hook"] = dict(src=[h["start"], h["end"]], lines=[h["text"]] if h.get("text") else [])
        rows.append(dict(id=s.get("id"), params=p))
    if d.get("transcript") and not ins.get("transcript"):
        project.data["inputs"]["transcript"] = d["transcript"]
    return rows


# --------------------------------------------------------------------------- segments checkpoint
def segment_options(items):
    out = []
    for it in items:
        p = it.get("params") or {}
        rng = p.get("range") or ([p.get("start"), p.get("end")] if p.get("start") is not None else None)
        h = p.get("hook") or {}
        out.append(dict(id=it["id"], start=rng[0] if rng else None, end=rng[1] if rng else None,
                        title=p.get("title"), chapter=p.get("chapter"),
                        hook=dict(start=(h.get("src") or [None, None])[0], end=(h.get("src") or [None, None])[1],
                                  text=" ".join(h.get("lines") or [])) if h else None,
                        why=p.get("why"), risk=p.get("risk"), score=p.get("score"), tags=p.get("tags")))
    return out


def _project_items(env):
    import yaml
    with open(os.path.join(env.project_dir, "project.yaml"), encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("items") or []


def segments_payload(env, cp):
    opts = segment_options(_project_items(env))
    src = env.params.get("source")
    return dict(options=opts, source=src, digest=sha1_json(opts)[:16], default=dict(approve="all"),
                previews=[dict(kind="video", path=src)] if src else [])


def segments_apply(a):
    v = a.value or {}
    items = [dict(i) for i in a.project.data["items"]]
    drop = set(v.get("drop") or [])
    if isinstance(v.get("approve"), list):
        drop |= {i["id"] for i in items} - set(v["approve"])
    patch = {i: None for i in drop}
    for iid, e in (v.get("edits") or {}).items():
        if iid in drop:
            continue
        p = {}
        if "start" in e or "end" in e:
            cur = next((x for x in segment_options(items) if x["id"] == iid), {})
            p["range"] = [float(e.get("start", cur.get("start"))), float(e.get("end", cur.get("end")))]
        for k in ("title", "chapter", "body", "tags", "notes"):
            if k in e:
                p[k] = e[k]
        if "hook" in e:
            h = e["hook"]
            p["hook"] = None if h is None else dict(src=[h["start"], h["end"]], lines=[h["text"]] if h.get("text") else [])
        patch[iid] = p
    after = []
    for it in items:
        if patch.get(it["id"], 0) is None:
            continue
        it = dict(it, params=dict(it.get("params") or {}, **(patch.get(it["id"]) or {})))
        after.append(it)
    if not after:
        raise ValueError("segments: every segment dropped")
    return dict(params={}, items_patch=patch, digest=sha1_json(segment_options(after))[:16])


# --------------------------------------------------------------------------- privacy (longform-split)
def privacy_payload(env, cp):
    g = env.inputs.get(cp["after"]) or {}
    excl = (env.spec.get("privacy") or {}).get("exclude") or []
    opts = [dict(frame=g.get("frame"), share=g.get("share"), size=g.get("size"), exclude=excl,
                 partial_excludes=g.get("partial_excludes"))]
    return dict(options=opts, frame=g.get("frame"), share=g.get("share"), size=g.get("size"), exclude=excl,
                default=None, previews=[dict(kind="image", path=g["frame"])] if g.get("frame") else [])


def privacy_apply(a):
    v = a.value or {}
    if v.get("exclude") is not None:
        return dict(params={}, project_params=dict(privacy_exclude=v["exclude"]), digest=None)
    if not v.get("confirm"):
        raise ValueError("privacy: confirm the frame or give exclude rects")
    return dict(params={})


# --------------------------------------------------------------------------- masks (call-clips)
def masks_payload(env, cp):
    cov = env.inputs.get(cp["after"]) or {}
    tracks = cov.get("tracks") or []
    comp = env.inputs.get("compose") or {}
    prev = []
    for k in ("master", "final"):
        if comp.get(k):
            prev.append(dict(kind="video", path=comp[k]))
    ok = bool(cov.get("ok", True))
    return dict(options=[dict(name=t.get("name"), worst=t.get("worst"), ok=t.get("ok")) for t in tracks],
                coverage_ok=ok, default=dict(ok=True) if ok and tracks else None,
                previews=prev + [dict(kind="json", path=cov.get("report"))] if cov.get("report") else prev,
                skip=not tracks and env.params.get("_no_mask_ok", False))


def masks_apply(a):
    v = a.value or {}
    if v.get("ok"):
        if a.payload.get("coverage_ok") is False:
            raise ValueError("masks: coverage under 100 % - fix the guest regions / sticker scale (or no_mask)")
        return dict(params={})
    pp = {}
    if "no_mask" in v:
        pp["no_mask"] = bool(v["no_mask"])
    if v.get("guests") is not None:
        pp["guests"] = v["guests"]
    return dict(params={}, project_params=pp, digest="re-render")
