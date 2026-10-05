"""Shared helpers for the longform-to-short workflow.

Every script takes the per-video config file as argv[1] (``work/config.py`` or
``work/config.json``). The directory holding the config is the WORK dir: all
intermediate JSON / PNG / segment files live there and scripts ``chdir`` into it.
Paths inside the config are relative to the WORK dir unless absolute.

    import _lfc
    cfg = _lfc.load()                 # parses argv / --config, chdirs into WORK
    cfg.get("speeds.lecture", 1.2)    # dotted lookup with a default
    cfg.src, cfg.out                  # resolved source video + output dir
"""
import json
import os
import pathlib
import re
import runpy
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from vstudio.config import font as _font_path, persona  # noqa: E402


# --------------------------------------------------------------------------- config
class Config:
    def __init__(self, data, path):
        self.data = data
        self.path = os.path.abspath(path)
        self.work = os.path.dirname(self.path)

    def get(self, dotted, default=None):
        cur = self.data
        for k in dotted.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur if cur is not None else default

    def path_of(self, rel):
        if rel is None:
            return None
        rel = os.path.expanduser(rel)
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(self.work, rel))

    @property
    def src(self):
        p = self.path_of(self.get("src"))
        if not p:
            sys.exit("config: 'src' (the long recording) is required")
        return p

    @property
    def out(self):
        p = self.path_of(self.get("out", "../out"))
        os.makedirs(p, exist_ok=True)
        return p

    def duration(self):
        d = self.get("duration")
        return float(d) if d else probe_duration(self.src)


def read_config(path):
    if path.endswith(".py"):
        ns = runpy.run_path(path)
        if "CONFIG" not in ns:
            sys.exit(f"{path}: define a dict named CONFIG")
        return ns["CONFIG"]
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load(argv=None, description=None, extra=None):
    """Parse ``config`` (+ optional extra argparse args), chdir to WORK, return (cfg, args)."""
    import argparse
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("config", help="per-video config (work/config.py or work/config.json)")
    if extra:
        extra(ap)
    args = ap.parse_args(argv)
    cfg = Config(read_config(args.config), args.config)
    os.chdir(cfg.work)
    return cfg, args


# --------------------------------------------------------------------------- ffmpeg
def ffmpeg_bin(need_libass=False):
    """System ffmpeg first; static_ffmpeg only as a fallback (e.g. a build without libass)."""
    sysbin = shutil.which("ffmpeg")
    if sysbin and (not need_libass or _has_filter(sysbin, "ass")):
        return sysbin
    try:  # pip install static-ffmpeg
        from static_ffmpeg import run
        ff, _ = run.get_or_fetch_platform_executables_else_raise()
        if not need_libass or _has_filter(ff, "ass"):
            return ff
    except Exception:
        pass
    if shutil.which("static_ffmpeg"):
        return "static_ffmpeg"
    if sysbin:
        sys.exit("ffmpeg has no libass ('ass' filter). Install an ffmpeg with libass "
                 "or `pip install static-ffmpeg` as a fallback.")
    sys.exit("ffmpeg not found")


def _has_filter(binary, name):
    try:
        out = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:
        return False
    return re.search(rf"^\s*\S+\s+{name}\s", out, re.M) is not None


def run(cmd, **kw):
    kw.setdefault("check", True)
    return subprocess.run([str(c) for c in cmd], **kw)


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(out.stdout.strip())


def grab_frame(src, t, png, vf=None):
    """Accurate still at source time t.

    Meeting recordings have sparse keyframes: a fast input-seek + -frames:v 1 can land
    seconds off. Seek ~25s early and decode forward to the exact time instead.
    """
    pre = max(0.0, t - 25)
    sel = f"select='gte(t,{t - pre - 0.4:.3f})'"
    run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{pre:.3f}", "-i", src,
         "-vf", sel + ("," + vf if vf else ""), "-frames:v", "1", png])
    return png


def video_encoder(cfg):
    """('-c:v', ...) args. auto: VideoToolbox quality mode on macOS, else libx264 CRF.

    Never use a fixed -b:v with videotoolbox (balloons the file); for code/slides text
    libx264 at crf ~20 is crisper.
    """
    enc = cfg.get("burn.encoder", "auto")
    crf = str(cfg.get("render.crf", persona().get("export", {}).get("crf", 19)))
    if enc == "auto":
        enc = "videotoolbox" if sys.platform == "darwin" else "x264"
    if enc == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", str(cfg.get("burn.vt_quality", 60))]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p"]


# --------------------------------------------------------------------------- look
def rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def palette(cfg):
    lf = persona().get("longform", {})
    return {
        "accent": rgb(cfg.get("style.accent") or lf.get("accent") or "#2DD4BF"),
        "bg": rgb(cfg.get("style.bg") or lf.get("ground") or "#0A0A0C"),
        "ink": (245, 245, 245),
        "muted": (160, 160, 165),
    }


def font(size, bold=False, role=None):
    from PIL import ImageFont
    return ImageFont.truetype(_font_path(role or ("cjk-bold" if bold else "cjk")), size)


def font_family_name(role="cjk-bold"):
    """Family name of a vstudio font (for ASS styles). Falls back to Noto Sans SC."""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(_font_path(role), 10).getname()[0]
    except Exception:
        return "Noto Sans SC"


def speed(cfg, kind, default):
    lf = persona().get("longform", {}).get("speed", {})
    return float(cfg.get(f"speeds.{kind}", lf.get(kind, default)))


# --------------------------------------------------------------------------- time maps
def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, p, indent=1):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)


def map_src(timeline, t, snap=None):
    """Source seconds -> final seconds through timeline.json (hook clip excluded).

    snap='fwd' / 'back': when t falls in a removed gap, snap to the next kept item's
    start / previous kept item's end; None returns None.
    """
    clips = [it for it in timeline if it["kind"] != "card" and not it.get("hook")]
    for it in clips:
        if it["t0"] <= t <= it["t1"]:
            return it["final_t0"] + (t - it["t0"]) / it["speed"]
    if snap == "fwd":
        nxt = [it for it in clips if it["t0"] > t]
        return min((it["final_t0"] for it in nxt), default=None)
    if snap == "back":
        prev = [it for it in clips if it["t1"] < t]
        if not prev:
            return None
        it = max(prev, key=lambda x: x["t1"])
        return it["final_t0"] + (it["t1"] - it["t0"]) / it["speed"]
    return None


def chapters_from_timeline(timeline):
    return [(it["final_t0"], it["title"]) for it in timeline if it["kind"] == "card"]


def total_duration(timeline):
    it = timeline[-1]
    return it["final_t0"] + (it["dur"] if it["kind"] == "card" else (it["t1"] - it["t0"]) / it["speed"])


def mmss(t):
    t = int(t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
