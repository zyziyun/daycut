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
import runpy
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from vstudio import media  # noqa: E402
from vstudio.config import persona  # noqa: E402
from vstudio.cut import TimeMap  # noqa: E402
from vstudio.draw import load_font, rgb  # noqa: E402
from vstudio.overlays import get_theme  # noqa: E402
from vstudio.publish import mmss  # noqa: E402,F401  (re-exported for the scripts)


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
        return float(d) if d else media.duration(self.src)


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
# ffmpeg discovery / run / probe / frame grabs live in vstudio.media (ffmpeg_bin, run, duration, grab_frame).
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
def palette(cfg):
    lf = persona().get("longform", {})
    return {
        "accent": rgb(cfg.get("style.accent") or lf.get("accent") or "#2DD4BF"),
        "bg": rgb(cfg.get("style.bg") or lf.get("ground") or "#0A0A0C"),
        "ink": (245, 245, 245),
        "muted": (160, 160, 165),
    }


def theme(cfg):
    """vstudio.overlays 'teal' panel theme with the per-video accent (style.accent) applied."""
    T = dict(get_theme("teal"))
    a = palette(cfg)["accent"]
    T.update(accent=a, tag_text=a + (255,), hl=a + (255,), dot=a + (255,), outline=a + (255,), chip_fill=a)
    return T


def font(size, bold=False, role=None):
    """PIL font from vstudio roles (vstudio.draw.load_font)."""
    return load_font(role or ("cjk-bold" if bold else "cjk"), size)


def speed(cfg, kind, default):
    lf = persona().get("longform", {}).get("speed", {})
    return float(cfg.get(f"speeds.{kind}", lf.get(kind, default)))


# --------------------------------------------------------------------------- json / time maps
def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, p, indent=1):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)


def timemap(timeline):
    """vstudio.cut.TimeMap of timeline.json: cards are holds, the cold-open hook is tagged "hook",
    every other clip / freeze is tagged "body" (map source times with ``tag="body"``)."""
    items = []
    for it in timeline:
        if it["kind"] == "card":
            items.append(dict(kind="hold", dur=float(it["dur"]), label=it.get("title"),
                              dst0=float(it["final_t0"]), xfade=0.0, tag="card"))
        else:
            items.append(dict(kind="clip", src0=float(it["t0"]), src1=float(it["t1"]), speed=float(it["speed"]),
                              source=0, dst0=float(it["final_t0"]), dur=(it["t1"] - it["t0"]) / it["speed"],
                              xfade=0.0, tag="hook" if it.get("hook") else "body"))
    return TimeMap(items)


def map_src(timeline, t, snap=None):
    """Source seconds -> final seconds through the body (hook excluded). snap: None | 'fwd' | 'back'."""
    tm = timeline if isinstance(timeline, TimeMap) else timemap(timeline)
    return tm.to_final(t, snap, tag="body")


def chapters_from_timeline(timeline):
    return [(it["final_t0"], it["title"]) for it in timeline if it["kind"] == "card"]


def total_duration(timeline):
    return timemap(timeline).duration
