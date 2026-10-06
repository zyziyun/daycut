"""vlog: render through build_vlog.py (calm; delegates to build_fun.py for style fun), music bed (add_music.py)."""
import json
import os

from ..build import file_sha


def _edit(env):
    path = os.path.join(env.item_dir, "work", "edit.json")
    with open(path, encoding="utf-8") as f:
        return path, json.load(f)


def render(env):
    path, cfg = _edit(env)
    argv = [env.fmt("{python}"), os.path.join(env.workflow_dir, "scripts", "build_vlog.py"), path]
    plats = env.params.get("platforms") or []
    if plats:
        argv += ["--platform", plats[0]]
    if cfg.get("style") == "fun":
        argv = [env.fmt("{python}"), os.path.join(env.workflow_dir, "scripts", "build_fun.py"), path]
        if plats:
            argv += ["--platform", plats[0]]
        if env.params.get("preset"):
            argv += ["--preset", env.params["preset"]]
    env.run(argv, cwd=os.path.dirname(path), log="build.log")
    out = cfg.get("out") or ("fun_vlog.mp4" if cfg.get("style") == "fun" else "vlog_master.mp4")
    master = out if os.path.isabs(out) else os.path.join(os.path.dirname(path), out)
    if not os.path.exists(master):
        raise RuntimeError(f"vlog render wrote no {master}")
    return dict(master=master, style=cfg.get("style", "calm"), files=[master], digest=file_sha(master))


def music(env):
    track = (env.params.get("_inputs") or {}).get("music")
    track = track[0] if isinstance(track, list) else track
    master = env.inputs["render"]["master"]
    if not track or env.inputs["render"].get("style") == "fun":
        return dict(master=master, files=[master], skipped=True)
    out = os.path.join(env.item_dir, "out", "vlog_music.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    argv = [env.fmt("{python}"), os.path.join(env.workflow_dir, "scripts", "add_music.py"), master, track, out]
    plats = env.params.get("platforms") or []
    if plats:
        argv += ["--platform", plats[0]]
    env.run(argv, log="add_music.log")
    return dict(master=out, files=[out], digest=file_sha(out))
