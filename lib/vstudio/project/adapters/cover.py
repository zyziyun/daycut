"""cover: candidate frames (workflows/cover/scripts/extract_frames.py sheet --save-frames, unchanged) or the
given photos -> pick checkpoint -> split cover (workflows/cover/scripts/split_cover.py on a config the adapter
writes into the item folder: the agent / app can edit split_cover.json and refresh)."""
import glob
import json
import os
import re
import shutil

from vstudio.batch.util import read_json, write_json

from ..build import file_sha


def _inputs(env, key):
    v = (env.params.get("_inputs") or {}).get(key)
    return v if isinstance(v, list) else ([v] if v else [])


def frames(env):
    src = env.item_path("cover_src")
    os.makedirs(src, exist_ok=True)
    cands = []
    videos, photos = _inputs(env, "video"), _inputs(env, "photo")
    sheet = None
    if videos:
        for f in glob.glob(os.path.join(src, "cand_*.png")):
            os.remove(f)
        env.run([env.fmt("{python}"), os.path.join(env.workflow_dir, "scripts", "extract_frames.py"), "sheet",
                 videos[0], src, "--every", str(env.params.get("every") or 3), "--max",
                 str(env.params.get("max_frames") or 12), "--save-frames"], log="extract_frames.log")
        sheet = os.path.join(src, "contact_sheet.jpg")
        for f in sorted(glob.glob(os.path.join(src, "cand_*.png"))):
            t = float(re.search(r"cand_([\d.]+)\.png", f).group(1))
            cands.append(dict(t=t, image=f, source=videos[0]))
    for p in photos:
        cands.append(dict(t=None, image=os.path.abspath(p), source=p))
    if not cands:
        raise RuntimeError("cover: give a video or a photo")
    for k, c in enumerate(cands):
        c["index"] = k
    path = write_json(env.path("candidates.json"), dict(candidates=cands, sheet=sheet))
    files = [path] + ([sheet] if sheet else [])
    return dict(candidates=path, sheet=sheet, n=len(cands), files=files)


def pick_payload(env, cp):
    out = env.inputs.get("frames") or {}
    d = read_json(out.get("candidates"), {}) or {}
    c = d.get("candidates") or []
    p = env.params
    title = list(p.get("cover_title") or []) or ([x for x in re.split(r"[|｜\n]", p.get("title") or "") if x]
                                                  if p.get("title") else [])
    previews = ([dict(kind="image", path=d["sheet"])] if d.get("sheet") else []) + \
        [dict(kind="image", path=x["image"], index=x["index"]) for x in c]
    return dict(options=[dict(index=x["index"], t=x["t"], image=x["image"]) for x in c],
                default=dict(pick=min(1, len(c) - 1) if c else 0, title=title), previews=previews, skip=not c)


def pick_apply(a):
    v = a.value or {}
    opts = a.payload.get("options") or []
    k = int(v.get("pick", 0))
    if not 0 <= k < len(opts):
        raise ValueError(f"cover pick {k} out of range (0..{len(opts) - 1})")
    out = dict(cover_photo=opts[k]["image"])
    if v.get("title") is not None:
        out["cover_title"] = list(v["title"])
    if v.get("highlight") is not None:
        out["cover_highlight"] = list(v["highlight"])
    if v.get("quote") is not None:
        out["cover_quote"] = v["quote"]
    return dict(params=out)


def config(env):
    p = env.params
    photo = p.get("cover_photo")
    if not photo:
        raise RuntimeError("cover: no picked frame (answer the pick checkpoint)")
    lines = list(p.get("cover_title") or []) or [x for x in re.split(r"[|｜\n]", p.get("title") or "") if x] or [" "]
    cfg = dict(photo=photo, face_x="auto" if p.get("retouch") else 0.5, photo_lift=1.03,
               title=dict(lines=lines, highlight=list(p.get("cover_highlight") or [])))
    if p.get("retouch"):
        cfg["retouch"] = {"slim": 0.05, "eye": 0.04, "makeup": 0.5}
    if p.get("cover_quote"):
        cfg["quote"] = dict(text=p["cover_quote"], by="")
    if p.get("chips"):
        cfg["chips"] = list(p["chips"])
    if p.get("stamp"):
        cfg["stamp"] = dict(text=p["stamp"], rotate=8)
    if p.get("corner_tag"):
        cfg["corner_tag"] = dict(text=p["corner_tag"])
    thumb = (p.get("_inputs") or {}).get("thumbnail")
    if thumb:
        cfg["thumbnail"] = dict(path=thumb[0] if isinstance(thumb, list) else thumb)
    cfg["outputs"] = []
    return cfg


def render(env):
    p = env.params
    cfg = config(env)
    path = env.item_path("split_cover.json")
    old = read_json(path, None)
    if isinstance(old, dict) and old.get("_edited"):         # hand / agent edited: keep it, refresh photo only
        cfg = dict(old, photo=cfg["photo"])
    cdir = env.item_path("covers")
    shutil.rmtree(cdir, ignore_errors=True)
    os.makedirs(cdir, exist_ok=True)
    cfg["outputs"] = []
    write_json(path, cfg)
    plats = ",".join(p.get("platforms") or ["xiaohongshu"])
    env.run([env.fmt("{python}"), os.path.join(env.workflow_dir, "scripts", "split_cover.py"), path,
             "--platforms", plats], cwd=env.item_dir, log="split_cover.log")
    made = []
    for f in sorted(glob.glob(os.path.join(env.item_dir, "split_cover.*.jpg"))):
        dst = os.path.join(cdir, "cover." + os.path.basename(f)[len("split_cover."):])
        shutil.move(f, dst)
        made.append(dst)
    covers = [f for f in made if not f.endswith(".feed.jpg")]
    if not covers:
        raise RuntimeError("split_cover.py wrote no cover")
    return dict(config=path, covers=covers, files=made, digest=json.dumps([file_sha(f) for f in made])[:64])


def collect(project, job, rows):
    out = []
    for st in ("render", "render_html"):
        o = (rows.get(st) or {}).get("out") or {}
        if (rows.get(st) or {}).get("state") != "done":
            continue
        for f in o.get("covers") or [f for f in o.get("files") or [] if os.path.isfile(f)]:
            name = os.path.basename(f)
            mo = re.match(r"cover\.([a-z0-9-]+)-(vertical|horizontal|full|square)\.", name)
            out.append(dict(platform=mo.group(1) if mo else None, orientation=mo.group(2) if mo else None,
                            kind="image", file=f))
        if st == "render_html":
            out += [dict(platform=None, orientation=None, kind="image", file=f)
                    for f in sorted(glob.glob(os.path.join(job["params"]["_item_dir"], "covers", "*.png")))]
    return out
