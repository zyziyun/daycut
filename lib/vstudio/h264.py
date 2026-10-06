"""ONE H.264 encoder setting for every encode in the library and the workflows, + ffmpeg / ffprobe paths.

    VSTUDIO_H264_ENCODER=h264_videotoolbox   # or h264_mf (Windows Media Foundation), libx264 (default)
    VSTUDIO_FFMPEG=/opt/ffmpeg/bin/ffmpeg     # optional: these binaries instead of the ones on PATH
    VSTUDIO_FFPROBE=/opt/ffmpeg/bin/ffprobe

The encoder can also come from the persona (``export.h264_encoder``; the environment wins). Code that builds
its own args asks ``h264.args(crf, preset)``; ``media.delivery_args`` and ``media.run`` use it. Command lines
that still say ``-c:v libx264`` (scripts that call ffmpeg through ``subprocess`` themselves) are rewritten when
the variable names another encoder: importing ``vstudio`` installs a tiny ``subprocess.Popen`` hook (only then,
or when ``VSTUDIO_FFMPEG`` / ``VSTUDIO_FFPROBE`` are set) that maps

  -c:v / -vcodec libx264  -> the encoder;   -crf N -> -q:v (videotoolbox on Apple silicon) or -b:v;
  -preset / -tune / -x264-params / -x264opts -> dropped;   h264_mf: no -profile / -level, nv12 input;

and a bare ``ffmpeg`` / ``ffprobe`` argv[0] to the configured binaries. Fallback: the encoder is probed once
(a 0.1 s test encode); when it does not work on this machine nothing is rewritten (libx264 stays), and
``media.run`` re-runs a failed rewritten command with the original libx264 line.
"""
import os
import subprocess
import sys

DEFAULT = "libx264"
ALIASES = {"videotoolbox": "h264_videotoolbox", "vt": "h264_videotoolbox", "mf": "h264_mf", "x264": "libx264"}
KNOWN = ("libx264", "h264_videotoolbox", "h264_mf", "h264_nvenc", "h264_qsv", "h264_amf")
X264_ONLY = {"-preset", "-tune", "-x264-params", "-x264opts"}
CODEC_FLAGS = ("-c:v", "-vcodec", "-codec:v")
_PROBED = {}
_ORIG_INIT = None


def _norm(name):
    n = (name or "").strip().lower()
    return ALIASES.get(n, n)


def encoder():
    """The configured H.264 encoder: $VSTUDIO_H264_ENCODER, else persona export.h264_encoder, else libx264."""
    env = _norm(os.environ.get("VSTUDIO_H264_ENCODER"))
    if env:
        return env
    try:
        from .config import persona
        p = _norm((persona().get("export") or {}).get("h264_encoder"))
        if p:
            return p
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT


def crf_to_bitrate(crf, pixels=1920 * 1080):
    """Rough bitrate for a CRF on an encoder without constant quality (scaled by frame size)."""
    base = 24e6 if crf <= 14 else 14e6 if crf <= 18 else 8e6 if crf <= 23 else 4e6 if crf <= 28 else 1.5e6
    return f"{max(0.5, base * pixels / (1920 * 1080)) / 1e6:.1f}M"


def crf_to_q(crf):
    """libx264 CRF -> h264_videotoolbox -q:v (1-100, higher = better); CRF 18 -> 65."""
    return int(max(1, min(100, round(105 - 2.2 * float(crf)))))


def _machine():
    try:
        return os.uname().machine
    except AttributeError:
        return ""


def quality_args(enc, crf=18, machine=None):
    """The rate-control args of ``enc`` for a libx264-equivalent CRF."""
    machine = _machine() if machine is None else machine
    if enc == "libx264":
        return ["-crf", str(crf)]
    if enc == "h264_videotoolbox":
        out = ["-allow_sw", "1"]                    # VMs / CI have no hardware encoder
        return out + (["-q:v", str(crf_to_q(crf))] if machine == "arm64" else ["-b:v", crf_to_bitrate(crf)])
    if enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        return ["-b:v", crf_to_bitrate(crf)]
    return ["-b:v", crf_to_bitrate(crf)]            # h264_mf and anything else: bitrate


def args(crf=18, preset="medium", enc=None, pix_fmt="yuv420p", profile="high"):
    """Encoder args (codec, profile, pixel format, rate control) for ``enc`` (default: ``encoder()``)."""
    enc = _norm(enc) or encoder()
    if enc == "libx264":
        out = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
        out += ["-profile:v", profile] if profile else []
        return out + (["-pix_fmt", pix_fmt] if pix_fmt else [])
    out = ["-c:v", enc]
    if enc != "h264_mf" and profile:
        out += ["-profile:v", profile]
    if pix_fmt:
        out += ["-pix_fmt", "nv12" if enc == "h264_mf" and pix_fmt == "yuv420p" else pix_fmt]
    return out + quality_args(enc, crf)


def _is_codec_flag(a):
    return a in CODEC_FLAGS or a.startswith(("-c:v:", "-codec:v:"))


def rewrite(argv, enc=None, machine=None):
    """A copy of an ffmpeg argv with libx264 replaced by ``enc`` (default ``encoder()``); the same object when
    nothing applies (not ffmpeg, no libx264, encoder libx264)."""
    enc = _norm(enc) or encoder()
    if enc == "libx264" or not isinstance(argv, (list, tuple)) or not argv:
        return argv
    if not os.path.basename(str(argv[0])).lower().startswith("ffmpeg"):
        return argv
    a = [str(x) for x in argv]
    if not any(_is_codec_flag(x) and y == "libx264" for x, y in zip(a, a[1:])):
        return argv
    out, i, crf = [], 0, None
    while i < len(a):
        x, nxt = a[i], (a[i + 1] if i + 1 < len(a) else None)
        if _is_codec_flag(x) and nxt == "libx264":
            out += [x, enc]
            i += 2
            continue
        if x in X264_ONLY and nxt is not None:
            i += 2
            continue
        if x == "-crf" and nxt is not None:
            try:
                crf = float(nxt)
            except ValueError:
                crf = 18.0
            i += 2
            continue
        if enc == "h264_mf" and x in ("-profile:v", "-level", "-level:v") and nxt is not None:
            i += 2
            continue
        if enc == "h264_mf" and x == "-pix_fmt" and nxt == "yuv420p":
            out += [x, "nv12"]
            i += 2
            continue
        out.append(x)
        i += 1
    extra = quality_args(enc, 18.0 if crf is None else crf, machine)
    idx = max(j for j, x in enumerate(out[:-1]) if _is_codec_flag(x) and out[j + 1] == enc) + 2
    return out[:idx] + extra + out[idx:]


def ffmpeg_path():
    return os.environ.get("VSTUDIO_FFMPEG") or None


def ffprobe_path():
    return os.environ.get("VSTUDIO_FFPROBE") or None


def works(enc=None, ffmpeg=None):
    """True when ``enc`` can encode a tiny clip with this ffmpeg (cached per process and in the environment)."""
    enc = _norm(enc) or encoder()
    if enc == "libx264":
        return True
    ff = ffmpeg or ffmpeg_path() or "ffmpeg"
    key = f"{ff}|{enc}"
    if key in _PROBED:
        return _PROBED[key]
    mark = os.environ.get("VSTUDIO_H264_PROBED", "")
    if mark.startswith(key + "="):
        _PROBED[key] = mark.endswith("=1")
        return _PROBED[key]
    cmd = [ff, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=gray:s=128x128:d=0.2:r=10"] + \
        args(18, enc=enc) + ["-f", "null", "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             _vstudio_raw=True) if _ORIG_INIT else \
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        ok = p.wait(timeout=30) == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    _PROBED[key] = ok
    os.environ["VSTUDIO_H264_PROBED"] = f"{key}={int(ok)}"
    if not ok:
        print(f"!! video-studio: H.264 encoder {enc} does not work with {ff}; using libx264", file=sys.stderr)
    return ok


def effective_encoder():
    """``encoder()`` when it works here, else libx264."""
    enc = encoder()
    return enc if enc == "libx264" or works(enc) else "libx264"


def resolve_bin(argv):
    """A bare ``ffmpeg`` / ``ffprobe`` argv[0] -> $VSTUDIO_FFMPEG / $VSTUDIO_FFPROBE."""
    if not isinstance(argv, (list, tuple)) or not argv:
        return argv
    head = str(argv[0])
    if head == "ffmpeg" and ffmpeg_path():
        return [ffmpeg_path(), *argv[1:]]
    if head == "ffprobe" and ffprobe_path():
        return [ffprobe_path(), *argv[1:]]
    return argv


def install():
    """The Popen hook (idempotent): binaries from the environment, libx264 lines rewritten to the encoder."""
    global _ORIG_INIT
    if _ORIG_INIT is not None:
        return
    _ORIG_INIT = subprocess.Popen.__init__

    def _init(self, cmd, *a, _vstudio_raw=False, **kw):
        if not _vstudio_raw and isinstance(cmd, (list, tuple)):
            cmd = resolve_bin(cmd)
            enc = _norm(os.environ.get("VSTUDIO_H264_ENCODER"))
            if enc and enc != "libx264":
                new = rewrite(cmd, enc)
                if new is not cmd and works(enc, str(cmd[0])):
                    cmd = new
        _ORIG_INIT(self, cmd, *a, **kw)

    subprocess.Popen.__init__ = _init


def wanted():
    """Install the hook at import? Only when the environment asks for something."""
    enc = _norm(os.environ.get("VSTUDIO_H264_ENCODER"))
    return bool((enc and enc != "libx264") or os.environ.get("VSTUDIO_FFMPEG") or os.environ.get("VSTUDIO_FFPROBE"))
