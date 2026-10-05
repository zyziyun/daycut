"""ffmpeg / ffprobe plumbing shared by every workflow.

    from vstudio import media
    info = media.probe("talk.mp4")            # w, h, fps, duration, has_audio, transfer, hdr, bitrate ...
    media.extract_wav("talk.mp4", "a16.wav")  # 16 kHz mono for ASR
    media.grab_frame("talk.mp4", 61.2, "f.png")
    media.run(["ffmpeg", "-y", "-i", src, *media.delivery_args(), "out.mp4"])

Binary discovery: the system ffmpeg first; ``static_ffmpeg`` (pip install static-ffmpeg) only as a
fallback when the system build is missing or lacks a filter you ask for (``ffmpeg_bin(need=["ass"])``).
Unified from: longform-to-short ``_lfc.ffmpeg_bin/_has_filter/grab_frame``, polish ``polish.py:probe/
atempo_chain/BT709/step_finalize``, vlog ``build_vlog.py:hdr_chain/has_filter/atempo``, talkinghead
``prep_sources.sh:ffmpeg_sdr``, cover ``extract_frames.py:grab/cmd_sheet``, promo-recut ``common.py:run/
duration/extract_wav``.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from functools import lru_cache

BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
HDR_TRC = ("arib-std-b67", "smpte2084")          # HLG, PQ
SR = 48000                                       # every audio stem we produce is 48 kHz


class FFmpegError(RuntimeError):
    pass


# ------------------------------------------------------------------ discovery
@lru_cache(maxsize=None)
def _static_bins():
    try:
        from static_ffmpeg import run as _sr  # pip install static-ffmpeg
        return _sr.get_or_fetch_platform_executables_else_raise()
    except Exception:
        return None


@lru_cache(maxsize=None)
def _filters(binary):
    try:
        out = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return frozenset()
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s*[TSCA.|]{2,3}\s+(\S+)\s", line)
        if m:
            names.add(m.group(1))
    return frozenset(names)


def has_filter(name, binary=None):
    """True if ``binary`` (default: the chosen ffmpeg) has filter ``name`` (zscale, libplacebo, ass...).

    From longform-to-short ``_lfc._has_filter`` and vlog ``build_vlog.has_filter``.
    """
    return name in _filters(binary or ffmpeg_bin())


def ffmpeg_bin(need=None):
    """Path of an ffmpeg binary. ``need``: tuple/list of filter names that must be present.

    System ffmpeg first (it usually has VideoToolbox / the user's build flags); the static_ffmpeg
    build only as a fallback. Raises FFmpegError if nothing suitable exists.
    From longform-to-short ``_lfc.ffmpeg_bin``.
    """
    return _ffmpeg_bin(tuple(need or ()))


@lru_cache(maxsize=None)
def _ffmpeg_bin(need):
    sysbin = shutil.which("ffmpeg")
    if sysbin and all(n in _filters(sysbin) for n in need):
        return sysbin
    st = _static_bins()
    if st and all(n in _filters(st[0]) for n in need):
        return st[0]
    if sysbin:
        if need:
            raise FFmpegError(f"ffmpeg lacks filter(s) {need}; install a fuller build or `pip install static-ffmpeg`")
        return sysbin
    if st:
        return st[0]
    raise FFmpegError("ffmpeg not found (install it, or `pip install static-ffmpeg`)")


@lru_cache(maxsize=None)
def ffprobe_bin():
    """Path of ffprobe (system first, static_ffmpeg fallback)."""
    p = shutil.which("ffprobe")
    if p:
        return p
    st = _static_bins()
    if st:
        return st[1]
    raise FFmpegError("ffprobe not found")


def _resolve(cmd):
    cmd = [str(c) for c in cmd]
    if cmd and cmd[0] == "ffmpeg":
        cmd[0] = ffmpeg_bin()
    elif cmd and cmd[0] == "ffprobe":
        cmd[0] = ffprobe_bin()
    return cmd


def run(cmd, capture=False, check=True, quiet=True, input=None):
    """Run a command; a leading "ffmpeg"/"ffprobe" is replaced by the discovered binary.

    Args: cmd list; capture -> return CompletedProcess with text stdout/stderr; quiet adds
    ``-v error -nostdin`` hints to ffmpeg if no loglevel was given; input bytes for stdin.
    Raises FFmpegError (with the stderr tail) on failure when check=True.
    From promo-recut ``common.run``, polish ``polish.run``, call-clips ``build_clips.sh``.
    """
    cmd = _resolve(cmd)
    if quiet and os.path.basename(cmd[0]).startswith("ffmpeg") and not ({"-v", "-loglevel"} & set(cmd)):
        cmd[1:1] = ["-v", "error"]
    if os.path.basename(cmd[0]).startswith("ffmpeg") and "-nostdin" not in cmd and input is None:
        cmd[1:1] = ["-nostdin"]
    r = subprocess.run(cmd, capture_output=True, input=input)
    if check and r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else (r.stderr or "")
        raise FFmpegError(f"command failed ({r.returncode}): {' '.join(cmd[:8])} ...\n{err[-2500:]}")
    if capture:
        r.stdout_text = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, bytes) else r.stdout
        r.stderr_text = r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else r.stderr
    return r


def filter_complex_args(graph, workdir=None):
    """``-filter_complex`` args; graphs over ~20 kB go through a script file (ffmpeg >= 7.1 syntax
    ``-/filter_complex file`` when available, else ``-filter_complex_script``)."""
    if len(graph) < 20000:
        return ["-filter_complex", graph]
    fd, path = tempfile.mkstemp(suffix=".fgraph", dir=workdir)
    with os.fdopen(fd, "w") as f:
        f.write(graph)
    ver = _version()
    return (["-/filter_complex", path] if ver >= (7, 1) else ["-filter_complex_script", path])


@lru_cache(maxsize=None)
def _version():
    out = subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, text=True).stdout
    m = re.search(r"version n?(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


# ------------------------------------------------------------------ probing
def probe(path):
    """ffprobe summary of a media file.

    Returns dict: w, h, fps (float), fps_q (Fraction), duration (s), has_video, has_audio, vcodec,
    acodec, pix_fmt, transfer (color_transfer), primaries, hdr (bool: HLG/PQ), rotation (deg),
    sample_rate, channels, bitrate (container bps), vbitrate (video bps, estimated if missing),
    abitrate, display_w/display_h (the size as displayed: w/h swapped for a +-90/270 deg rotation).
    w/h are the coded size (rotation NOT applied; see ``rotation`` / ``display_w``).
    From polish ``polish.probe`` + vlog ``build_vlog.clip_info``/``probe.py``.
    """
    r = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path], capture=True)
    d = json.loads(r.stdout_text)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = d.get("format", {})
    info = dict(w=0, h=0, fps=0.0, fps_q=Fraction(0), duration=float(fmt.get("duration") or 0),
                has_video=v is not None, has_audio=a is not None, vcodec=None, acodec=None, pix_fmt=None,
                transfer="", primaries="", hdr=False, rotation=0, sample_rate=0, channels=0,
                bitrate=int(fmt.get("bit_rate") or 0), vbitrate=0, abitrate=0)
    if v is not None:
        fq = Fraction(0)
        for key in ("avg_frame_rate", "r_frame_rate"):
            try:
                fq = Fraction(v.get(key) or "0/1")
            except (ZeroDivisionError, ValueError):
                fq = Fraction(0)
            if fq:
                break
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = rot or int((v.get("tags") or {}).get("rotate", 0) or 0)
        info.update(w=int(v.get("width", 0)), h=int(v.get("height", 0)), fps=float(fq), fps_q=fq,
                    vcodec=v.get("codec_name"), pix_fmt=v.get("pix_fmt"),
                    transfer=v.get("color_transfer", "") or "", primaries=v.get("color_primaries", "") or "",
                    rotation=rot, vbitrate=int(v.get("bit_rate") or 0))
        info["hdr"] = info["transfer"] in HDR_TRC
        if not info["duration"] and v.get("duration"):
            info["duration"] = float(v["duration"])
    if a is not None:
        info.update(acodec=a.get("codec_name"), sample_rate=int(a.get("sample_rate") or 0),
                    channels=int(a.get("channels") or 0), abitrate=int(a.get("bit_rate") or 0))
    if v is not None and not info["vbitrate"] and info["bitrate"]:
        info["vbitrate"] = max(0, info["bitrate"] - (info["abitrate"] or (192000 if a else 0)))
    turned = abs(int(info["rotation"])) % 180 == 90
    info["display_w"], info["display_h"] = (info["h"], info["w"]) if turned else (info["w"], info["h"])
    return info


def ffprobe_value(path, entry="format=duration", stream=None, cast=None):
    """One ffprobe value (``-show_entries entry``, ``-select_streams stream`` e.g. "v:0"), robust to the
    trailing comma / extra lines newer ffprobe builds print with ``csv=p=0`` on stream entries.
    cast: optional type (float, int); returns None when the value is empty or "N/A"."""
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    r = run(cmd + ["-show_entries", entry, "-of", "default=nw=1:nk=1", os.fspath(path)], capture=True)
    vals = [v.strip().rstrip(",") for v in r.stdout_text.splitlines() if v.strip().rstrip(",")]
    if not vals or vals[0] == "N/A":
        return None
    return cast(vals[0]) if cast else vals[0]


def duration(path):
    """Container duration in seconds (float). From promo-recut ``common.duration``."""
    v = ffprobe_value(path, "format=duration", cast=float)
    if v is None:
        raise FFmpegError(f"no duration for {path}")
    return v


# ------------------------------------------------------------------ extraction
def extract_wav(src, dst, sr=16000, channels=1, start=None, end=None):
    """Decode the first audio stream of ``src`` to PCM s16 wav (default 16 kHz mono, ASR input).

    start/end in seconds (optional, accurate seek). Returns dst.
    From promo-recut ``common.extract_wav`` / longform ``analyze.py`` / talkinghead ``prep_sources.sh``.
    """
    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if end is not None:
        cmd += ["-t", f"{end - (start or 0):.3f}"]
    cmd += ["-map", "0:a:0", "-vn", "-ac", str(channels), "-ar", str(sr), "-c:a", "pcm_s16le", dst]
    run(cmd)
    return dst


def grab_frame(src, t, out, vf=None, preroll=25.0, quality=None):
    """Frame-accurate still at source time ``t`` -> image file ``out``; returns ``out``.

    Recordings with sparse keyframes (meetings, screen captures) make a plain ``-ss t -frames:v 1``
    land seconds off, so seek ``preroll`` s early and decode forward to the exact time.
    vf: optional extra filter chain (e.g. a crop). quality: JPEG ``-q:v`` (2 = best .. 31) for .jpg
    outputs (default: ffmpeg's). From longform-to-short ``_lfc.grab_frame``
    (cover ``extract_frames.grab`` is the fast-but-inexact variant).
    """
    pre = max(0.0, t - preroll)
    chain = f"trim=start={t - pre:.4f},setpts=PTS-STARTPTS" + ("," + vf if vf else "")
    q = ["-q:v", str(int(quality))] if quality is not None else []
    run(["ffmpeg", "-y", "-ss", f"{pre:.3f}", "-i", src, "-vf", chain, "-frames:v", "1", *q, "-update", "1", out])
    if not os.path.exists(out):
        raise FFmpegError(f"no frame decoded at t={t} from {src}")
    return out


def contact_sheet(src, out, every=5.0, cols=6, thumb_w=320, max_frames=48, label=True, start=None):
    """Labelled grid of stills, one every ``every`` s (first at every/2) -> JPEG/PNG ``out``.

    One decode pass (fps filter), then PIL composes the grid with a time label under each cell
    (font: vstudio.config.font("mono-bold") if installed, else PIL's default). Returns
    (out, [timestamps]). From cover ``extract_frames.cmd_sheet`` + vlog ``contact_sheets.sh`` +
    longform ``qa.py`` mosaic.
    """
    from PIL import Image, ImageDraw, ImageFont
    dur = duration(src)
    t0 = start if start is not None else every / 2
    with tempfile.TemporaryDirectory() as tmp:
        # select (not fps=1/N): fps emits the frame nearest the MIDDLE of each N-second bucket, so every
        # label was ~N/2 s early (a QA sheet must say exactly when an avatar / name tag shows).
        sel = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{every - 0.5 / 30:.4f})'"
        run(["ffmpeg", "-y", "-ss", f"{t0:.3f}", "-i", src, "-vf", f"{sel},scale={thumb_w}:-2",
             "-fps_mode", "vfr", "-frames:v", str(max_frames), os.path.join(tmp, "f%04d.png")])
        files = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        if not files:
            raise FFmpegError(f"no frames from {src}")
        thumbs = [Image.open(os.path.join(tmp, f)).convert("RGB") for f in files]
    ts = [t0 + i * every for i in range(len(thumbs)) if t0 + i * every < dur + every]
    tw, th = thumbs[0].size
    lab = 26 if label else 0
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + lab)), "black")
    d = ImageDraw.Draw(sheet)
    try:
        from .config import font
        fnt = ImageFont.truetype(font("mono-bold"), 18)
    except Exception:
        fnt = ImageFont.load_default()
    for i, im in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (th + lab)
        sheet.paste(im, (x, y))
        if label and i < len(ts):
            d.text((x + 6, y + th + 3), f"{ts[i]:.1f}s", font=fnt, fill="white")
    sheet.save(out, quality=88) if out.lower().endswith((".jpg", ".jpeg")) else sheet.save(out)
    return out, ts[:len(thumbs)]


# ------------------------------------------------------------------ colour
ZSCALE_TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
                  "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
PLACEBO_TONEMAP = ("libplacebo=tonemapping=bt.2390:colorspace=bt709:color_primaries=bt709:color_trc=bt709:"
                   "range=tv:format=yuv420p")
APPROX_TONEMAP = "colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:fast=1,format=yuv420p"


def hdr_to_sdr_args(src=None, transfer=None, force=False, warn=True):
    """Video filter chain (string, no trailing comma) that tone-maps HLG/PQ HDR to SDR bt709.

    Returns "" when the source is SDR (``transfer`` not HLG/PQ) unless force=True. Backend order:
    zscale+tonemap(hable) -> libplacebo(bt.2390) -> approximate ``colorspace`` (gamut only, highlights
    flat; prints a warning). For the best result on macOS see ``to_sdr(backend="avconvert")``.
    From talkinghead ``prep_sources.sh:ffmpeg_sdr``, vlog ``build_vlog.hdr_chain``, promo ``HDR_TONEMAP``.
    """
    if transfer is None and src is not None:
        transfer = probe(src)["transfer"]
    if not force and transfer not in HDR_TRC:
        return ""
    if has_filter("zscale"):
        return ZSCALE_TONEMAP
    if has_filter("libplacebo"):
        return PLACEBO_TONEMAP
    if warn:
        print(f"[vstudio.media] warn: {os.path.basename(str(src or 'source'))} is HDR ({transfer}) but ffmpeg "
              "has neither zscale nor libplacebo; using an approximate conversion (install ffmpeg with libzimg, "
              "or use avconvert on macOS)", file=sys.stderr)
    return APPROX_TONEMAP


def to_sdr(src, dst, backend="auto", fit=None, crf=14, preset="medium"):
    """Convert a (possibly HDR) phone clip to SDR bt709 H.264 + AAC 48 kHz.

    backend: "auto" (avconvert on macOS when the clip is HDR, else ffmpeg), "avconvert", "ffmpeg".
    fit: optional scale chain appended (e.g. fit inside 1080x1920). Returns dst.
    From talkinghead ``prep_sources.sh`` (avconvert Preset1920x1080 tone-maps HLG/Dolby Vision correctly).
    """
    info = probe(src)
    if backend == "auto":
        backend = "avconvert" if (info["hdr"] and shutil.which("avconvert")) else "ffmpeg"
    if backend == "avconvert":
        if not shutil.which("avconvert"):
            raise FFmpegError("avconvert not available (macOS only)")
        subprocess.run(["avconvert", "-s", src, "-p", "Preset1920x1080", "-o", dst, "--replace"],
                       check=True, capture_output=True)
        return dst
    chain = [c for c in (hdr_to_sdr_args(src, info["transfer"]), "format=yuv420p", fit) if c]
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", ",".join(chain), "-c:v", "libx264", "-crf", str(crf),
           "-preset", preset, *BT709]
    cmd += (["-c:a", "aac", "-b:a", "256k", "-ar", str(SR)] if info["has_audio"] else ["-an"])
    run(cmd + [dst])
    return dst


# ------------------------------------------------------------------ speed / delivery
def atempo_chain(rate):
    """Pitch-preserving ``atempo`` chain for any positive rate (each instance limited to 0.5..2.0).

    atempo_chain(3.0) -> "atempo=2,atempo=1.5". From polish ``atempo_chain`` / vlog ``atempo``.
    """
    if rate <= 0:
        raise ValueError("rate must be > 0")
    parts, s = [], float(rate)
    while s > 2.0:
        parts.append(2.0); s /= 2.0
    while s < 0.5:
        parts.append(0.5); s /= 0.5
    parts.append(s)
    return ",".join(f"atempo={p:.6g}" for p in parts)


def _persona_export():
    try:
        from .config import persona
        return persona().get("export", {}) or {}
    except Exception:
        return {}


def _bps(v):
    """'28M' / '900k' / 28e6 -> int bits per second."""
    if isinstance(v, (int, float)):
        return int(v)
    m = re.fullmatch(r"\s*([\d.]+)\s*([kKmM]?)\s*", str(v))
    if not m:
        raise ValueError(f"bitrate {v!r}")
    return int(float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()])


def delivery_args(crf=None, preset="medium", audio=True, audio_bitrate=None, faststart=True, fps=None,
                  maxrate=None, vbitrate=None, maxrate_factor=1.15, bufsize=None, encoder="libx264", quality=None):
    """Encoder args for a publishable MP4: H.264 High yuv420p, CRF (persona export.crf, 18),
    bt709 tags in the container AND the H.264 VUI (h264_metadata bsf, so iOS does not guess),
    AAC ``audio_bitrate`` (persona export.audio_bitrate, 192k) 48 kHz stereo, +faststart.

    fps: optional output rate (-r); maxrate: optional VBV cap like "30M".
    vbitrate: bitrate-target mode instead of CRF ("28M" or bps): -b:v, -maxrate vbitrate*maxrate_factor,
      -bufsize (default 2x maxrate) - match a source's bitrate (polish ``venc_args``).
    audio: True -> AAC args; False -> "-an" (drop audio); None -> no audio args at all (the caller
      maps/copies audio itself).
    encoder: "libx264" | "videotoolbox" (h264_videotoolbox, macOS hardware: ``-q:v quality`` (default
      65) unless vbitrate is given; no preset/crf). Returns an arg list to put between the
      inputs/filters and the output path.
    From polish ``BT709``/``venc_args``/``step_finalize``, call-clips loudnorm/export block, longform
    ``_lfc.video_encoder``.
    """
    ex = _persona_export()
    crf = ex.get("crf", 18) if crf is None else crf
    vt = encoder in ("videotoolbox", "h264_videotoolbox")
    if vt:
        args = ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-pix_fmt", "yuv420p"]
        if not vbitrate:
            args += ["-q:v", str(65 if quality is None else quality)]
    elif encoder == "libx264":
        args = ["-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", preset]
        if not vbitrate:
            args += ["-crf", str(crf)]
    else:
        raise ValueError(f"encoder={encoder!r} (libx264 | videotoolbox)")
    if vbitrate:
        vb = _bps(vbitrate)
        mr = _bps(maxrate) if maxrate else int(vb * maxrate_factor)
        args += ["-b:v", str(vb), "-maxrate", str(mr), "-bufsize", str(_bps(bufsize) if bufsize else 2 * mr)]
    elif maxrate:
        args += ["-maxrate", str(maxrate), "-bufsize", str(bufsize or maxrate)]
    if fps:
        args += ["-r", str(fps)]
    args += BT709 + ["-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
    if audio:
        args += ["-c:a", "aac", "-b:a", str(audio_bitrate or ex.get("audio_bitrate", "192k")),
                 "-ar", str(SR), "-ac", "2"]
    elif audio is not None:
        args += ["-an"]
    if faststart:
        args += ["-movflags", "+faststart"]
    return args


def link_or_copy(src, dst):
    """Hard-link ``src`` to ``dst`` (instant, no extra space), else copy it. Replaces dst. Returns dst."""
    src, dst = os.fspath(src), os.fspath(dst)
    if os.path.abspath(src) == os.path.abspath(dst):
        return dst
    d = os.path.dirname(os.path.abspath(dst))
    os.makedirs(d, exist_ok=True)
    if os.path.lexists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


def retag_bt709(src, dst):
    """Write bt709 colour tags into the bitstream VUI + container and move moov to the front,
    with NO re-encode (stream copy; h264_metadata / hevc_metadata bsf). Returns dst.
    From polish ``step_finalize``.
    """
    info = probe(src)
    bsf = {"h264": "h264_metadata", "hevc": "hevc_metadata"}.get(info["vcodec"])
    cmd = ["ffmpeg", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
    if bsf:
        cmd += ["-bsf:v", f"{bsf}=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
    if info["has_audio"] and info["acodec"] not in ("aac", "mp3", "alac") and dst.lower().endswith(".mp4"):
        cmd += ["-c:a", "aac", "-b:a", str(_persona_export().get("audio_bitrate", "192k")), "-ar", str(SR)]
    run(cmd + BT709 + ["-movflags", "+faststart", dst])
    return dst
