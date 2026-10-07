"""The launch kit, end to end: what gets made, where it lands, and the checks it passes before anyone sees it.

    from vstudio.launch import kit as K
    K.build(cfg)            # HyperFrames projects for every cut x language x canvas  -> <out>/build/
    K.render(cfg)           # -> <out>/demo/, <out>/readme/ (loop MP4 + GIF), <out>/clips/ (+ a cover per video)
    K.stills(cfg)           # -> <out>/stills/ (Product Hunt gallery 1270x760, OG 1200x630)
    K.posts(cfg)            # -> <out>/copy/ (COPY.md, per platform x language)
    K.schedule(cfg)         # -> <out>/schedule/ (proposal; --apply puts it on the publish calendar as planned posts)
    K.check(cfg)            # vstudio.firstpass on every video -> <video>.firstpass.md + <out>/firstpass.json

Every step reads the files the previous one wrote, so each can be re-run alone after an edit to the config.
"""
import glob
import json
import os

from . import compose as CO
from . import config as C
from . import story as S

CANVAS_TAG = {"16:9": "16x9", "9:16": "9x16", "1:1": "1x1"}
# the platform a render is checked against (first-pass: safe area, canvas); international first
CHECK_PLATFORM = {("en", "16:9"): "x", ("en", "9:16"): "tiktok", ("en", "1:1"): "x:square",
                  ("zh", "16:9"): "bilibili", ("zh", "9:16"): "xiaohongshu:full", ("zh", "1:1"): "x:square"}


def jobs(cfg, only=None):
    """[(name, cut, lang, aspect, feature, video path)] for everything the config asks for."""
    out_dir = cfg["out"]
    js = []
    for lang, asp in C.renders(cfg, "demo"):
        n = f"demo-{lang}-{CANVAS_TAG[asp]}"
        js.append((n, "demo", lang, asp, None, os.path.join(out_dir, "demo", n + ".mp4")))
    for lang, asp in C.renders(cfg, "loop"):
        n = f"loop-{lang}"
        js.append((n, "loop", lang, asp, None, os.path.join(out_dir, "readme", n + ".mp4")))
    for fid in C.cut_features(cfg, "clips"):
        for lang, asp in C.renders(cfg, "clips"):
            n = f"{fid}-{lang}-{CANVAS_TAG[asp]}"
            js.append((n, "clip", lang, asp, fid, os.path.join(out_dir, "clips", n + ".mp4")))
    if only:
        keep = set(only)
        js = [j for j in js if j[1] in keep or j[0] in keep or (j[4] and j[4] in keep)]
    return js


def shots(cfg):
    sh = C.load_shots(cfg)
    if not sh:
        raise C.ConfigError("no shots: run the capture step (capture.shot_list) or list capture.images")
    return sh


def build(cfg, only=None):
    sh = shots(cfg)
    made = []
    for name, cut, lang, asp, fid, _ in jobs(cfg, only):
        plan = S.plan(cfg, sh, cut, lang, asp, feature=fid)
        made.append(CO.build(cfg, plan, os.path.join(cfg["out"], "build", name)))
    return made


def cover_time(plan):
    """A frame that reads as a cover: the title fully in (demo), else the first caption fully in."""
    sc = plan["scenes"]
    if sc[0]["kind"] == "title":
        return min(sc[0]["dur"] - 0.5, 2.0)
    s = next(x for x in sc if x["kind"] == "feature")
    return s["start"] + min(s["dur"] - 0.4, 2.4)


def render(cfg, only=None, quality="delivery", rebuild=True):
    if rebuild:
        build(cfg, only)
    done = []
    for name, cut, lang, asp, fid, video in jobs(cfg, only):
        proj = os.path.join(cfg["out"], "build", name)
        print(f"render {name} ...", flush=True)
        CO.render(proj, video, quality=quality)
        with open(os.path.join(proj, "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
        CO.cover(video, cover_time(plan), video[:-4] + ".cover.jpg")
        if cut == "loop":
            CO.gif(video, video[:-4] + ".gif", width=cfg["loop"]["width"], fps=cfg["loop"]["gif_fps"])
        done.append(video)
    write_manifest(cfg)
    return done


def stills(cfg):
    from . import stills as ST
    out = ST.make_all(cfg, shots(cfg), os.path.join(cfg["out"], "stills"))
    write_manifest(cfg)
    return out


def _media_index(cfg):
    demo, clips, covers = {}, {}, {}
    for name, cut, lang, asp, fid, video in jobs(cfg):
        if not os.path.exists(video):
            continue
        cv = video[:-4] + ".cover.jpg"
        if os.path.exists(cv):
            covers[video] = cv
        if cut == "demo":
            demo[(lang, asp)] = video
        elif cut == "clip":
            clips.setdefault(fid, {})[(lang, asp)] = video
    return demo, clips, covers


def posts(cfg):
    from . import posts as PO
    from . import schedule as SC
    demo, clips, _ = _media_index(cfg)
    langs = cfg["languages"]
    demo_for, clip_for = {}, {}
    for pl in cfg["platforms"]:
        sel = SC.pick(pl, "demo", demo, langs)
        if sel:
            demo_for[pl] = demo[sel]
        for fid, have in clips.items():
            sel = SC.pick(pl, "clip", have, langs)
            if sel:
                clip_for[(fid, pl)] = have[sel]
    gallery = sorted(glob.glob(os.path.join(cfg["out"], "stills", "ph-gallery-*.png")))
    lead = demo.get((langs[0], "16:9"))
    res = PO.make_all(cfg, os.path.join(cfg["out"], "copy"),
                      kit=dict(demo=lead, gallery=gallery, demo_for=demo_for, clip_for=clip_for))
    write_manifest(cfg)
    return res


def schedule(cfg, apply=False):
    from . import schedule as SC
    demo, clips, covers = _media_index(cfg)
    copy_dir = os.path.join(cfg["out"], "copy")
    cp = {}
    for path in glob.glob(os.path.join(copy_dir, "*.*.md")) + glob.glob(os.path.join(copy_dir, "clips", "*", "*.*.md")):
        base = os.path.basename(path)[:-3]
        pl, _, lang = base.rpartition(".")
        fid = os.path.basename(os.path.dirname(path)) if os.sep + "clips" + os.sep in path else "launch"
        for real in cfg["platforms"]:
            if real.replace(":", "-") == pl:
                cp[(fid, real, lang)] = path
    rows = SC.propose(cfg, dict(demo=demo, clips=clips, covers=covers, copy=cp))
    SC.write(rows, os.path.join(cfg["out"], "schedule"), product=cfg["product"]["name"])
    res = dict(rows=rows)
    if apply:
        res.update(SC.apply(rows, (cfg.get("schedule") or {}).get("accounts") or {}, project=cfg["out"]))
    write_manifest(cfg)
    return res


def check(cfg, lang_report="en"):
    """vstudio.firstpass (format "launch") on every rendered video; -> {ok, results}."""
    from vstudio import firstpass as FP
    results, ok = [], True
    for name, cut, lang, asp, fid, video in jobs(cfg):
        if not os.path.exists(video):
            results.append(dict(video=video, ok=False, missing=True))
            ok = False
            continue
        proj = os.path.join(cfg["out"], "build", name)
        cues = os.path.join(proj, "cues.json")
        cover = video[:-4] + ".cover.jpg"
        res = FP.run(video, fmt="launch", platform=CHECK_PLATFORM[(lang, asp)], cues=cues if os.path.exists(cues) else None,
                     cover=cover if os.path.exists(cover) else None, locale=lang)
        with open(video[:-4] + ".firstpass.md", "w", encoding="utf-8") as f:
            f.write(FP.report(res, lang_report))
        ok = ok and res["ok"]
        bad = [i["id"] for i in res["items"] if i["ok"] is False]
        results.append(dict(video=video, ok=res["ok"], failed=bad))
        print(f"{'ok ' if res['ok'] else 'FIX'} {os.path.basename(video)}" + (f"  ({', '.join(bad)})" if bad else ""))
    with open(os.path.join(cfg["out"], "firstpass.json"), "w", encoding="utf-8") as f:
        json.dump(dict(ok=ok, results=results), f, ensure_ascii=False, indent=1)
    return dict(ok=ok, results=results)


def write_manifest(cfg):
    """<out>/kit.json: every file of the kit, grouped, relative to the kit folder."""
    out = cfg["out"]

    def rel(pats):
        return sorted(os.path.relpath(p, out) for pat in pats for p in glob.glob(os.path.join(out, pat)))
    man = dict(product=cfg["product"]["name"], version=cfg["product"].get("version"),
               demo=rel(["demo/*.mp4"]), readme=rel(["readme/*.mp4", "readme/*.gif"]), clips=rel(["clips/*.mp4"]),
               covers=rel(["demo/*.cover.jpg", "clips/*.cover.jpg", "readme/*.cover.jpg"]),
               stills=rel(["stills/*.png"]), copy=rel(["copy/COPY.md", "copy/*.md"]),
               schedule=rel(["schedule/*"]))
    with open(os.path.join(out, "kit.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    return man
