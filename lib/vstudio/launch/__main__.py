"""python -m vstudio.launch <step> CONFIG [options]  (see vstudio.launch and workflows/launch-kit/WORKFLOW.md)

  features CONFIG [--json]                 draft features from release.changelog / release.git / release.notes
  capture CONFIG                           run scripts/capture.mjs on capture.shot_list -> capture.shots
  build CONFIG [--only demo,loop,clip,<feature>,<name>]
  render CONFIG [--only ...] [--quality draft|looks|delivery] [--no-build]
  stills CONFIG                            Product Hunt gallery + OG image
  copy CONFIG                              post copy per platform x language -> copy/COPY.md
  schedule CONFIG [--apply]                proposal -> schedule/; --apply = planned posts on the publish calendar
  check CONFIG                             vstudio.firstpass on every video (exit 1 on a must-fix item)
  all CONFIG [--quality ...]               build, render, stills, copy, schedule, check
"""
import argparse
import json
import os
import subprocess
import sys

from . import config as C
from . import features as FE
from . import kit as K

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CAPTURE = os.path.join(ROOT, "workflows", "launch-kit", "scripts", "capture.mjs")


def _features(cfg_path, as_json):
    import yaml
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    rel = dict(raw.get("release") or {})
    root = os.path.dirname(os.path.abspath(cfg_path))
    if rel.get("changelog"):
        rel["changelog"] = os.path.join(root, os.path.expanduser(rel["changelog"]))
    if (rel.get("git") or {}).get("repo"):
        rel["git"] = dict(rel["git"], repo=os.path.join(root, os.path.expanduser(rel["git"]["repo"])))
    feats = FE.load(rel)
    if as_json:
        print(json.dumps(feats, ensure_ascii=False, indent=1))
        return 0
    print("# draft: pick 3-6, give each a shot id, write the on-screen caption (【term】 = highlighted word)")
    print("features:")
    for f in feats:
        print(f"  - id: {f['id']}            # {f['kind']}{'(' + f['scope'] + ')' if f.get('scope') else ''}")
        print(f"    shot: {f['id']}")
        print(f"    caption: {{en: {json.dumps(f['title'], ensure_ascii=False)}}}")
    return 0


def capture(cfg):
    cap = cfg.get("capture") or {}
    if not cap.get("shot_list"):
        raise C.ConfigError("capture.shot_list is not set (a shots.yaml for scripts/capture.mjs)")
    out = os.path.dirname(cap["shots"]) if cap.get("shots") else os.path.join(cfg["out"], "capture")
    cmd = ["node", CAPTURE, "--shots", cap["shot_list"], "--out", out]
    if cap.get("app"):
        cmd += ["--electron", cap["app"]]
    elif cap.get("url"):
        cmd += ["--url", cap["url"]]
    else:
        raise C.ConfigError("capture: set app (an Electron app dir) or url")
    for k, v in (cap.get("env") or {}).items():
        cmd += ["--env", f"{k}={v}"]
    if cap.get("env_json"):
        cmd += ["--env-json", cap["env_json"]]
    if cap.get("size"):
        cmd += ["--size", str(cap["size"])]
    if cap.get("scale"):
        cmd += ["--scale", str(cap["scale"])]
    print(" ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.launch", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n", 1)[1])
    ap.add_argument("step", choices=["features", "capture", "build", "render", "stills", "copy", "schedule", "check",
                                     "all"])
    ap.add_argument("config")
    ap.add_argument("--only", default="", help="comma list: demo, loop, clip, a feature id or a render name")
    ap.add_argument("--quality", default="delivery", choices=["draft", "looks", "delivery"])
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.step == "features":
        return _features(a.config, a.json)
    try:
        cfg = C.load(a.config)
    except C.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    from . import brand as B
    for w in B.warnings(cfg):
        print("warning:", w, file=sys.stderr)
    only = [x for x in a.only.split(",") if x] or None
    if a.step == "capture":
        return capture(cfg)
    if a.step == "build":
        K.build(cfg, only)
    elif a.step == "render":
        K.render(cfg, only, a.quality, rebuild=not a.no_build)
    elif a.step == "stills":
        for p in K.stills(cfg):
            print(p)
    elif a.step == "copy":
        res = K.posts(cfg)
        for w in res["warnings"]:
            print("check:", w)
        print(os.path.join(cfg["out"], "copy", "COPY.md"))
    elif a.step == "schedule":
        res = K.schedule(cfg, apply=a.apply)
        print(f"{len(res['rows'])} posts proposed -> {os.path.join(cfg['out'], 'schedule', 'SCHEDULE.md')}")
        if a.apply:
            print(f"calendar: {len(res['added'])} planned, {len(res['skipped'])} without an account (schedule.accounts)")
    elif a.step == "check":
        return 0 if K.check(cfg)["ok"] else 1
    elif a.step == "all":
        K.render(cfg, only, a.quality)
        K.stills(cfg)
        K.posts(cfg)
        K.schedule(cfg)
        return 0 if K.check(cfg)["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
