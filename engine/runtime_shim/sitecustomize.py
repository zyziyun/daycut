"""H.264 encoder fallback for the bundled (LGPL) ffmpeg, loaded automatically by Python (``sitecustomize``).

The video-studio library hard-codes ``-c:v libx264`` in several places. The desk ships an LGPL ffmpeg without
libx264, so when ``DESK_H264_ENCODER`` names another encoder (h264_videotoolbox on macOS, h264_mf on Windows),
every ffmpeg command line started through ``subprocess`` is rewritten before it runs:

  -c:v / -vcodec / -codec:v libx264  ->  the configured encoder
  -crf N                             ->  a quality/bitrate setting for that encoder
  -preset / -tune / -x264-params / -x264opts  ->  dropped (x264-only)

Nothing happens when the variable is unset, empty or ``libx264``, or for commands that are not ffmpeg.
This is a desk-side stopgap until the engine exposes the encoder itself (see docs/RELEASING.md, engine requests).
The desk puts this folder on PYTHONPATH only for its own engine processes.
"""
import os
import subprocess
import sys

ENCODER = (os.environ.get("DESK_H264_ENCODER") or "").strip()
X264_ONLY = {"-preset", "-tune", "-x264-params", "-x264opts"}
CODEC_FLAGS = ("-c:v", "-vcodec", "-codec:v")


def _is_codec_flag(a):
    return a in CODEC_FLAGS or a.startswith(("-c:v:", "-codec:v:"))


def _crf_to_bitrate(crf):
    # rough 1080p targets; the engine's delivery step re-encodes with its own caps where it matters
    return "24M" if crf <= 14 else "14M" if crf <= 18 else "8M" if crf <= 23 else "4M" if crf <= 28 else "1500k"


def rewrite(args, encoder=None, machine=None):
    """Return a rewritten copy of an ffmpeg argv (list) or the same object if nothing applies."""
    enc = encoder if encoder is not None else ENCODER
    if not enc or enc == "libx264" or not isinstance(args, (list, tuple)) or not args:
        return args
    exe = os.path.basename(str(args[0])).lower()
    if not exe.startswith("ffmpeg"):
        return args
    argv = [str(a) for a in args]
    if not any(_is_codec_flag(a) and b == "libx264" for a, b in zip(argv, argv[1:])):
        return args
    if machine is None:
        machine = os.uname().machine if hasattr(os, "uname") else ""
    out, i, crf = [], 0, None
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if _is_codec_flag(a) and nxt == "libx264":
            out += [a, enc]
            i += 2
            continue
        if a in X264_ONLY and nxt is not None:
            i += 2
            continue
        if a == "-crf" and nxt is not None:
            try:
                crf = float(nxt)
            except ValueError:
                crf = 18.0
            i += 2
            continue
        if enc == "h264_mf" and a in ("-profile:v", "-level", "-level:v") and nxt is not None:
            i += 2
            continue
        if enc == "h264_mf" and a == "-pix_fmt" and nxt == "yuv420p":
            out += [a, "nv12"]
            i += 2
            continue
        out.append(a)
        i += 1
    crf = 18.0 if crf is None else crf
    extra = []
    if enc == "h264_videotoolbox":
        extra = ["-allow_sw", "1"]  # VMs / CI have no hardware encoder
        if machine == "arm64":      # constant quality exists on Apple silicon only
            extra += ["-q:v", str(int(max(1, min(100, round(105 - 2.2 * crf)))))]
        else:
            extra += ["-b:v", _crf_to_bitrate(crf)]
    elif enc == "h264_mf":
        extra = ["-b:v", _crf_to_bitrate(crf)]
        if os.environ.get("DESK_H264_MF_HW") == "1":
            extra += ["-hw_encoding", "1"]
    # insert the encoder options right after the (last) codec selection so they bind to that output
    idx = max(j for j, a in enumerate(out[:-1]) if _is_codec_flag(a) and out[j + 1] == enc) + 2
    return out[:idx] + extra + out[idx:]


if ENCODER and ENCODER != "libx264":
    _orig_init = subprocess.Popen.__init__

    def _init(self, args, *a, **kw):
        new = rewrite(args)
        if new is not args and os.environ.get("DESK_H264_DEBUG") == "1":
            print(f"[desk-h264] {' '.join(new[:40])}", file=sys.stderr)
        _orig_init(self, new, *a, **kw)

    subprocess.Popen.__init__ = _init
