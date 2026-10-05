#!/usr/bin/env python3
"""Build a B-roll vlog master from silent or ambient clips (drone, phone, travel,
walking, nature, city).

Reads a JSON edit-decision list and produces one graded, speed-adjusted,
crossfaded master with a clean opening (NO black first frame) and a fade to
black at the end. Segments are rendered in parallel as intermediates, then
xfaded together.

    python3 build_vlog.py work/edit.json
    python3 build_vlog.py work/edit.json --dry-run      # print ffmpeg commands only

Relative paths in the config (src_dir, out) resolve against the config file's
folder. Full schema + worked example: ../references/recipes.md. Quick schema:
{
  "src_dir": "../footage",
  "clips": {"0079": "DJI_0079.MP4", "walk1": "IMG_1234.MOV"},   # id -> filename
  "res": [3840, 2160],       # master size; source res for true 4K, [1080,1920] for vertical
  "fps": 30,
  "xfade": 0.8, "fade_out": 1.5,
  "fit": "crop",             # crop | pad | blur | stretch  (how off-aspect clips fill the frame)
  "hdr": "auto",             # auto | true | false   (tone-map HLG/PQ phone/drone clips to BT.709)
  "ambient_audio": false,    # true = keep each clip's own sound (tempo-matched, crossfaded)
  "grade": {"brightness":0.05,"contrast":1.12,"saturation":1.18,"gamma":1.04},
  "warm": true, "sharpen": true, "stabilize": false,
  "seg_crf": 12, "final_crf": 18, "workers": 3,
  "out": "vlog_master.mp4",
  "segments": [
    {"clip":"0079","start":4,"dur":10,"kind":"empty","bright":0.08},   # establishing: faster
    {"clip":"walk1","start":6,"dur":20,"speed":1.15}
  ]
}
Per segment: clip, start, dur (SOURCE seconds), optional speed, kind
("subject" | "empty"), bright (added to grade.brightness), stabilize.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from vstudio.config import persona

COLORBALANCE = "colorbalance=rs=0.02:rm=0.02:bm=-0.02:bs=-0.03:rh=0.01:bh=-0.02"
UNSHARP = "unsharp=5:5:0.5:5:5:0.0"
DEFAULT_GRADE = {"brightness": 0.05, "contrast": 1.12, "saturation": 1.18, "gamma": 1.04}
HDR_TRC = {"arib-std-b67", "smpte2084"}


def vlog_persona():
    return persona().get("vlog", {}) or {}


@lru_cache(maxsize=1)
def has_filter(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines() if len(line.split()) > 1)


@lru_cache(maxsize=None)
def clip_info(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    streams = json.loads(out)["streams"]
    v = next(s for s in streams if s.get("codec_type") == "video")
    return {"trc": v.get("color_transfer", ""),
            "audio": any(s.get("codec_type") == "audio" for s in streams)}


def hdr_chain(cfg, src):
    mode = cfg.get("hdr", "auto")
    if mode is False or mode == "false":
        return ""
    if mode == "auto" and clip_info(src)["trc"] not in HDR_TRC:
        return ""
    if has_filter("zscale"):
        return ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
    # No libzimg in this ffmpeg build: gamut-only conversion. Highlights stay a bit flat;
    # the grade below compensates partly. Better: install an ffmpeg with zscale.
    print(f"[warn] {os.path.basename(src)} is HDR but ffmpeg lacks zscale; using approximate "
          "colorspace conversion (install ffmpeg with libzimg for proper tone-mapping)", flush=True)
    return "colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:fast=1,format=yuv420p,"


def fit_chain(cfg):
    W, H = cfg["res"]
    fit = cfg.get("fit", "crop")
    if fit == "stretch":
        return f"scale={W}:{H}:flags=lanczos"
    if fit == "pad":
        return (f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    if fit == "blur":
        return (f"split=2[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},gblur=sigma=40,eq=brightness=-0.08[bgb];"
                f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H},setsar=1")


def grade_chain(cfg, extra_bright):
    g = {**DEFAULT_GRADE, **(vlog_persona().get("grade") or {}), **(cfg.get("grade") or {})}
    parts = [f"eq=brightness={g['brightness'] + extra_bright:.3f}:contrast={g['contrast']}"
             f":saturation={g['saturation']}:gamma={g['gamma']}"]
    if cfg.get("warm", True):
        parts.append(COLORBALANCE)
    if cfg.get("sharpen", True):
        parts.append(UNSHARP)
    return ",".join(parts)


def stab_prefix(cfg, seg):
    """Optional in-pass stabilization (built-in `deshake`; no libvidstab needed).
    Runs on native frames BEFORE scale/speed; a small zoom-crop hides edge jitter.
    Top-level "stabilize": true or per-segment override. "stab_rx"/"stab_ry"
    (search range, multiple of 16, max 64) and "stab_zoom" (keep fraction)."""
    if not seg.get("stabilize", cfg.get("stabilize", False)):
        return ""
    snap = lambda v: max(16, min(64, round(v / 16) * 16))
    keep = cfg.get("stab_zoom", 0.93)
    return (f"deshake=rx={snap(cfg.get('stab_rx', 32))}:ry={snap(cfg.get('stab_ry', 32))}"
            f":edge=clamp,crop=iw*{keep}:ih*{keep},")


def seg_speed(cfg, seg):
    if "speed" in seg:
        return float(seg["speed"])
    vp = vlog_persona()
    if seg.get("kind") == "empty":
        return float(cfg.get("empty_speed", vp.get("speed_empty", 1.3)))
    # "deer_speed" accepted for configs written with the original drone skill
    return float(cfg.get("default_speed", cfg.get("deer_speed", vp.get("speed_subject", 1.2))))


def atempo(speed):
    """atempo accepts 0.5..2.0 per instance; chain for anything outside."""
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5"); s /= 0.5
    parts.append(f"atempo={s:.5f}")
    return ",".join(parts)


def render_seg(args):
    i, cfg, seg, segdir, dry = args
    src = os.path.join(cfg["_src_dir"], cfg["clips"][seg["clip"]])
    speed = seg_speed(cfg, seg)
    eb = seg.get("bright", 0.0)
    eff = seg["dur"] / speed
    vf = (stab_prefix(cfg, seg) + hdr_chain(cfg, src) + fit_chain(cfg) + "," + grade_chain(cfg, eb)
          + f",setpts=PTS/{speed},fps={cfg.get('fps', 30)}")
    dst = os.path.join(segdir, f"seg_{i:02d}.mp4")
    # -t BEFORE -i limits how much SOURCE is read, so the output length is dur/speed for
    # speed-ups AND slow-mo. After -i it would cap the OUTPUT and truncate slow-mo.
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(seg["start"]), "-t", str(seg["dur"]), "-i", src]
    if cfg.get("ambient_audio"):
        if clip_info(src)["audio"]:
            fc = (f"[0:v]{vf}[v];[0:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"{atempo(speed)},apad,atrim=0:{eff:.3f}[a]")
            cmd += ["-filter_complex", fc]
        else:
            cmd += ["-f", "lavfi", "-t", f"{eff:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                    "-filter_complex", f"[0:v]{vf}[v];[1:a]anull[a]"]
        cmd += ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        if ";" in vf or "[" in vf:   # blur fit uses labelled pads
            cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]"]
        else:
            cmd += ["-vf", vf]
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg.get("seg_crf", 12)),
            "-pix_fmt", "yuv420p", dst]
    print(f"[seg {i:02d}] {seg['clip']} {seg['start']}-{seg['start'] + seg['dur']}s "
          f"x{speed:g} +b{eb} -> {os.path.basename(dst)} ({eff:.2f}s)", flush=True)
    if dry:
        print("  " + " ".join(cmd))
    else:
        subprocess.run(cmd, check=True)
    return dst, eff


def main():
    ap = argparse.ArgumentParser(description="Grade + speed + crossfade B-roll clips into one master.")
    ap.add_argument("config", help="edit.json")
    ap.add_argument("--dry-run", action="store_true", help="print commands, render nothing")
    ap.add_argument("--workers", type=int, help="override parallel segment encodes")
    a = ap.parse_args()

    base = os.path.dirname(os.path.abspath(a.config))
    with open(a.config) as f:
        cfg = json.load(f)
    cfg["_src_dir"] = os.path.join(base, os.path.expanduser(cfg.get("src_dir", ".")))
    out = os.path.join(base, os.path.expanduser(cfg["out"]))
    segdir = os.path.join(os.path.dirname(out), "clips")
    os.makedirs(segdir, exist_ok=True)

    tasks = [(i, cfg, s, segdir, a.dry_run) for i, s in enumerate(cfg["segments"])]
    with ThreadPoolExecutor(max_workers=a.workers or cfg.get("workers", 3)) as ex:
        results = list(ex.map(render_seg, tasks))
    segs, durs = [r[0] for r in results], [r[1] for r in results]
    print("intermediates done", flush=True)

    D = cfg.get("xfade", 0.8)
    if D > 0 and min(durs) <= D:
        sys.exit(f"a segment is shorter on screen ({min(durs):.2f}s) than the crossfade ({D}s)")
    inputs = []
    for s in segs:
        inputs += ["-i", s]
    audio = bool(cfg.get("ambient_audio"))
    fc, prev, aprev, L = [], "0:v", "0:a", durs[0]
    for k in range(1, len(segs)):
        fc.append(f"[{prev}][{k}:v]xfade=transition={cfg.get('transition', 'fade')}"
                  f":duration={D}:offset={L - D:.3f}[x{k}]")
        prev = f"x{k}"
        if audio:
            fc.append(f"[{aprev}][{k}:a]acrossfade=d={D}[ax{k}]")
            aprev = f"ax{k}"
        L = L + durs[k] - D
    fo = cfg.get("fade_out", 1.5)
    # no fade-in on purpose (no black first frame); only fade out at the end
    fc.append(f"[{prev}]fade=t=out:st={L - fo:.3f}:d={fo}[vout]")
    maps = ["-map", "[vout]"]
    if audio:
        fc.append(f"[{aprev}]afade=t=out:st={L - fo:.3f}:d={fo}[aout]")
        maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", str(persona().get("export", {}).get("audio_bitrate", "192k"))]

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
           *inputs, "-filter_complex", ";".join(fc), *maps,
           "-c:v", "libx264", "-preset", "medium", "-crf", str(cfg.get("final_crf", 18)),
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-movflags", "+faststart", out]
    print(f"total timeline ~ {L:.1f}s; rendering final -> {out}", flush=True)
    if a.dry_run:
        print("  " + " ".join(cmd))
        return
    subprocess.run(cmd, check=True)
    print(f"DONE -> {out}", flush=True)


if __name__ == "__main__":
    main()
