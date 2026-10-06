#!/usr/bin/env python3
"""QC: editor popups / context menus still VISIBLE in a rendered vertical video (master or export).

make_vertical.py runs the same scan on every master it renders (plan.json ``visible_popups``); this script
re-checks any rendered file, e.g. an export made before the scan existed. The video is sampled at 2 fps, each
screen item of plan.json is cut out (记笔记 panels / hook boxes painted flat: plan ``overlays``, or for an older
plan the widest box a config panel can take), pans are stabilised and ``_vertical.detect_popups`` runs forward
and backward. Prints one line per popup longer than --min-s; exit 1 when there is one.

Usage: python3 scan_popups.py VIDEO --plan work/vertical/1080x1440/plan.json [--timeline work/timeline.json]
       [--config work/config.json] [--fps 24] [--hz 2] [--min-s 1.0] [--min-cover 0.02] [--json out.json]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

import _vertical as V


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--timeline", help="default: timeline.json two folders above the plan (work/)")
    ap.add_argument("--config", help="work/config.json (panels for a plan without overlays)")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--min-s", type=float, default=1.0)
    ap.add_argument("--min-cover", type=float, default=0.02)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan, encoding="utf-8"))
    work = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(a.plan))))
    tl = json.load(open(a.timeline or os.path.join(work, "timeline.json"), encoding="utf-8"))
    cfgp = a.config or os.path.join(work, "config.json")
    cfg = json.load(open(cfgp, encoding="utf-8")) if os.path.exists(cfgp) else {}
    vc = cfg.get("vertical") or {}
    ov = plan.get("overlays")
    if ov is None:
        ov = V.legacy_overlays(cfg.get("panels"), plan, tl, vc.get("split"))
    sp = dict(V.SPLIT_DEFAULTS, **(vc.get("split") or {}))
    L = plan.get("layout") or {}
    exported = tuple(plan.get("canvas") or ()) and os.path.basename(a.video) != "master.mp4"
    cap = L.get("caption", [0, None])[1] if (exported or sp["screen_to"] != "caption") else None
    found = V.scan_popups(a.video, V.output_segments(plan, tl, a.fps, vc.get("split")), ov, caption_top=cap,
                          o=dict(V.SCREEN_DEFAULTS, **(vc.get("screen") or {})), scan=dict(hz=a.hz))
    bad = [x for x in found if x["dur"] > a.min_s and (x.get("cover") or 0) >= a.min_cover]
    for x in bad:
        print(f"popup visible {x['t']:.1f}-{x['t'] + x['dur']:.1f}s ({x['dur']:.1f}s, item {x['item']}, box {x['box']})")
    if not bad:
        print("no visible popup")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(dict(video=a.video, popups=found, flagged=bad), f, ensure_ascii=False, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
