"""One H.264 encoder setting / ffmpeg paths / one cache root / platform requirements (desk packaging)."""
import os
import re
import subprocess
import sys

import pytest

from vstudio import h264, media

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_rewrite_maps_quality_flags_per_encoder():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-tune", "film",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "out.mp4"]
    vt = h264.rewrite(cmd, "h264_videotoolbox", machine="arm64")
    assert vt[vt.index("-c:v") + 1] == "h264_videotoolbox" and "-preset" not in vt and "-crf" not in vt
    assert "-tune" not in vt and vt[vt.index("-q:v") + 1] == "65" and "-allow_sw" in vt
    vt_x64 = h264.rewrite(cmd, "videotoolbox", machine="x86_64")
    assert "-b:v" in vt_x64 and "-q:v" not in vt_x64
    mf = h264.rewrite(cmd, "h264_mf")
    assert mf[mf.index("-c:v") + 1] == "h264_mf" and "-b:v" in mf and "-profile:v" not in mf
    assert mf[mf.index("-pix_fmt") + 1] == "nv12" and mf[-1] == "out.mp4"
    assert h264.rewrite(cmd, "libx264") is cmd
    assert h264.rewrite(["ffprobe", "-c:v", "libx264"], "h264_mf")[0] == "ffprobe"
    other = ["ffmpeg", "-i", "a", "-c:v", "prores", "o.mov"]
    assert h264.rewrite(other, "h264_mf") is other
    assert h264.crf_to_q(18) == 65 and h264.crf_to_bitrate(18).endswith("M")


def test_encoder_setting_env_persona_and_delivery_args(monkeypatch):
    monkeypatch.delenv("VSTUDIO_H264_ENCODER", raising=False)
    assert h264.encoder() == "libx264"
    monkeypatch.setenv("VSTUDIO_H264_ENCODER", "videotoolbox")
    assert h264.encoder() == "h264_videotoolbox"
    monkeypatch.setattr(h264, "works", lambda enc=None, ffmpeg=None: False)       # not available here
    assert h264.effective_encoder() == "libx264"
    a = media.delivery_args(crf=20)
    assert a[a.index("-c:v") + 1] == "libx264" and a[a.index("-crf") + 1] == "20"
    monkeypatch.setattr(h264, "works", lambda enc=None, ffmpeg=None: True)
    a = media.delivery_args(crf=18)
    assert a[a.index("-c:v") + 1] == "h264_videotoolbox" and "-crf" not in a
    a = media.delivery_args(crf=18, encoder="h264_mf", vbitrate="8M")
    assert a[a.index("-c:v") + 1] == "h264_mf" and a[a.index("-b:v") + 1] == "8000000" and a.count("-b:v") == 1
    assert media.delivery_args(encoder="libx264")[1] == "libx264"


def test_media_run_falls_back_to_libx264(monkeypatch, tmp_path):
    calls = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, b"", b"boom"

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return R(1 if "h264_mf" in cmd else 0)
    monkeypatch.setattr(h264, "effective_encoder", lambda *a: "h264_mf")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    media.run(["ffmpeg", "-i", "a.mp4", "-c:v", "libx264", "-crf", "18", "o.mp4"])
    assert "h264_mf" in calls[0] and "libx264" in calls[1] and len(calls) == 2


def test_ffmpeg_paths_from_env(monkeypatch, tmp_path):
    fake = tmp_path / "ffprobe-custom"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("VSTUDIO_FFPROBE", str(fake))
    media.ffprobe_bin.cache_clear()
    try:
        assert media.ffprobe_bin() == str(fake)
        assert h264.resolve_bin(["ffprobe", "-v"])[0] == str(fake)
        monkeypatch.setenv("VSTUDIO_FFPROBE", str(tmp_path / "missing"))
        media.ffprobe_bin.cache_clear()
        with pytest.raises(media.FFmpegError):
            media.ffprobe_bin()
    finally:
        monkeypatch.delenv("VSTUDIO_FFPROBE")
        media.ffprobe_bin.cache_clear()
    ff = tmp_path / "ffmpeg-custom"
    ff.write_text("#!/bin/sh\n")
    monkeypatch.setenv("VSTUDIO_FFMPEG", str(ff))
    media._ffmpeg_bin.cache_clear()
    try:
        assert media.ffmpeg_bin() == str(ff)
    finally:
        monkeypatch.delenv("VSTUDIO_FFMPEG")
        media._ffmpeg_bin.cache_clear()


def test_popen_hook_rewrites_subprocess_ffmpeg_lines(tmp_path):
    """A workflow script calling subprocess.run(["ffmpeg", ... "-c:v", "libx264" ...]) gets the encoder."""
    if os.name == "nt":                                   # a batch file stands in for ffmpeg.exe
        shim = tmp_path / "ffmpeg.cmd"
        shim.write_text('@echo %* > "%OUT%"\r\n')
    else:
        shim = tmp_path / "ffmpeg"
        shim.write_text("#!/bin/sh\necho \"$@\" > \"$OUT\"\n")
        shim.chmod(0o755)
    code = ("import subprocess, vstudio, vstudio.h264 as h; h._PROBED[r'%s|h264_mf'] = True; "
            "subprocess.run(['ffmpeg', '-i', 'a', '-c:v', 'libx264', '-crf', '23', 'o.mp4'])" % shim)
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib"), VSTUDIO_H264_ENCODER="h264_mf",
               VSTUDIO_FFMPEG=str(shim), OUT=str(tmp_path / "args.txt"))
    subprocess.run([sys.executable, "-c", code], env=env, check=True)
    args = (tmp_path / "args.txt").read_text().split()
    assert "h264_mf" in args and "libx264" not in args and "-b:v" in args and "-crf" not in args


def test_one_cache_root_reads_the_legacy_one(monkeypatch, tmp_path):
    from vstudio import config
    monkeypatch.delenv("VSTUDIO_CACHE", raising=False)
    monkeypatch.setattr(config, "CACHE", str(tmp_path / "new"))
    monkeypatch.setattr(config, "LEGACY_CACHE", str(tmp_path / "old"))
    (tmp_path / "old" / "asr").mkdir(parents=True)
    assert config.cache_dir("asr") == str(tmp_path / "new" / "asr") and os.path.isdir(tmp_path / "new" / "asr")
    assert config.cache_dirs("asr") == [str(tmp_path / "new" / "asr"), str(tmp_path / "old" / "asr")]
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "pinned"))
    assert config.cache_dirs("asr") == [str(tmp_path / "pinned" / "asr")]


def test_requirements_platform_markers_and_mediapipe_api():
    req = open(os.path.join(ROOT, "requirements.txt")).read()
    assert 'mlx-whisper; sys_platform == "darwin" and platform_machine == "arm64"' in req
    assert 'faster-whisper; sys_platform != "darwin" or platform_machine != "arm64"' in req
    assert 'mediapipe==0.10.21; sys_platform == "darwin" and platform_machine == "x86_64"' in req
    # only the mediapipe tasks API that 0.10.21 already has
    allowed = {"Image", "ImageFormat", "tasks", "FaceLandmarker", "FaceLandmarkerOptions", "ImageSegmenter",
               "ImageSegmenterOptions", "RunningMode", "BaseOptions", "python", "vision"}
    used = set()
    for d in ("lib", "workflows"):
        for root, _, files in os.walk(os.path.join(ROOT, d)):
            for f in files:
                if f.endswith(".py"):
                    src = open(os.path.join(root, f), encoding="utf-8").read()
                    if "mediapipe" in src:
                        used |= set(re.findall(r"\b(?:mp|vision|mp\.tasks|python)\.([A-Z][A-Za-z]+)", src))
    assert used <= allowed | {"T"}, used - allowed
