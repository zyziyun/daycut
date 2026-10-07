#!/usr/bin/env python3
"""Probe a set of B-roll clips (drone, phone, action cam, travel) and optionally
write a starter edit.json for build_vlog.py.

Prints one line per clip: resolution (display orientation), fps, duration, audio
yes/no, and whether the clip is HDR (HLG / PQ - typical for iPhone and newer DJI
"HLG" modes). The starter edit.json picks a master resolution and orientation
from the majority of clips.

    python3 probe.py footage/*.MP4
    python3 probe.py footage/*.MP4 --init work/edit.json
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re
from collections import Counter

from vstudio import media
from vstudio.oscompat import relpath as _relpath

HDR_NAMES = {"arib-std-b67": "HLG", "smpte2084": "PQ"}


def probe(path):
    """media.probe + display orientation (w/h swapped for 90/270 rotation) + HLG/PQ label."""
    i = media.probe(path)
    if not i["has_video"]:
        raise SystemExit(f"{path}: no video stream")
    w, h = i["w"], i["h"]
    if abs(i["rotation"]) % 180 == 90:
        w, h = h, w
    return {"path": path, "w": w, "h": h, "fps": round(i["fps"] or 30.0, 3), "dur": i["duration"],
            "audio": i["has_audio"], "hdr": HDR_NAMES.get(i["transfer"], "")}


def short_id(name, used):
    stem = os.path.splitext(os.path.basename(name))[0]
    m = re.findall(r"\d+", stem)
    cand = (m[-1] if m else stem)[-6:] or stem
    k, i = cand, 2
    while k in used:
        k, i = f"{cand}_{i}", i + 1
    used.add(k)
    return k


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--init", metavar="EDIT_JSON", help="write a starter edit.json (won't overwrite)")
    ap.add_argument("--style", choices=["calm", "fun"], default="calm",
                    help="starter for the calm crossfade vlog (default) or the fun beat-cut travel vlog")
    ap.add_argument("--platform", help="fun starter: platform[:orientation] (e.g. xiaohongshu:full, youtube)")
    ap.add_argument("--music", help="fun starter: music track path")
    ap.add_argument("--max-res", type=int, default=0,
                    help="cap master long edge (e.g. 1920 for a quick 1080p draft)")
    a = ap.parse_args()

    infos = [probe(p) for p in a.clips]
    for i in infos:
        print(f"{os.path.basename(i['path']):40s} {i['w']}x{i['h']} {i['fps']:6.2f}fps "
              f"{i['dur']:7.1f}s audio={'yes' if i['audio'] else 'no '} "
              f"{('HDR-' + i['hdr']) if i['hdr'] else 'SDR'}")
    if any(i["hdr"] for i in infos):
        print("note: HDR clips present -> build_vlog.py tone-maps them to BT.709 (\"hdr\": \"auto\")")
    if len({(i['w'] > i['h']) for i in infos}) > 1:
        print("note: mixed landscape/portrait -> build_vlog.py fills the master frame (\"fit\": \"crop\") "
              "or letterboxes with a blurred backdrop (\"fit\": \"blur\")")

    if not a.init:
        return
    if os.path.exists(a.init):
        sys.exit(f"{a.init} exists; not overwriting")
    w, h = Counter((i["w"], i["h"]) for i in infos).most_common(1)[0][0]
    if a.max_res and max(w, h) > a.max_res:
        s = a.max_res / max(w, h)
        w, h = int(round(w * s / 2) * 2), int(round(h * s / 2) * 2)
    base = os.path.dirname(os.path.abspath(a.init))
    used = set()
    clips = {short_id(i["path"], used): _relpath(os.path.abspath(i["path"]), base) for i in infos}
    if a.style == "fun":
        cfg = {
            "style": "fun", "platform": a.platform or "xiaohongshu:full", "src_dir": ".",
            "music": _relpath(os.path.abspath(a.music), base) if a.music else "MUSIC.mp3",
            "title": {"text": "TITLE", "sub": ""}, "end_card": {"text": "SEE YOU", "sub": ""},
            "clips": clips, "out": "fun_vlog.mp4",
            # no start/dur: windows are auto-picked; add "place", "day", "speech": "auto", "ramp", ...
            "shots": [dict({"clip": k}, **({"speech": "auto"} if i["audio"] else {})) for k, i in zip(clips, infos)],
        }
        os.makedirs(base, exist_ok=True)
        with open(a.init, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"fun starter -> {a.init} (set music, title, place/day per shot; see WORKFLOW.md 'Fun style')")
        if any(i["audio"] for i in infos):
            print('note: clips with audio start as "speech": "auto" - kept only when the transcript survives the '
                  "hallucination filter AND the loudness shows speech (see the build log / report 'speech'); "
                  'set "speech": false on clips that only carry music, "keep_audio": true to keep a clip\'s sound')
        return
    cfg = {
        "src_dir": ".",
        "clips": clips,
        "res": [w, h], "fps": 30, "xfade": 0.8, "fade_out": 1.5,
        "fit": "crop", "hdr": "auto", "ambient_audio": False,
        "seg_crf": 12, "final_crf": 18, "workers": 3,
        "out": "vlog_master.mp4",
        "segments": [{"clip": k, "start": 0, "dur": min(8, round(i["dur"], 1))}
                     for k, i in zip(clips, infos)],
    }
    os.makedirs(base, exist_ok=True)
    with open(a.init, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"starter edit list -> {a.init} (placeholder segments: replace after reading the contact sheets)")


if __name__ == "__main__":
    main()
