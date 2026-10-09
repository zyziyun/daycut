"""Windows support (desk preview): faster-whisper device choice, CLI lookup / npm .cmd shims, the H.264 fallback
without libx264 (LGPL ffmpeg), and media paths with spaces / CJK / brackets. Runs on every OS (CI: ubuntu, and the
Desk CI Windows smoke job); the Windows-only parts are simulated with explicit arguments."""
import os
import shutil
import subprocess

import pytest

from vstudio import asr, h264, llm, media


# ------------------------------------------------------------------ ASR device
@pytest.mark.parametrize("env, platform, cuda, want", [
    ({}, "nt", 1, ("cpu", "int8")),                                   # Windows: CPU unless asked (cuBLAS often missing)
    ({}, "posix", 0, ("cpu", "int8")),
    ({}, "posix", 2, ("cuda", "float16")),
    ({"VSTUDIO_WHISPER_DEVICE": "cuda"}, "nt", 0, ("cuda", "float16")),
    ({"VSTUDIO_WHISPER_DEVICE": "auto"}, "nt", 1, ("cuda", "float16")),
    ({"VSTUDIO_WHISPER_DEVICE": "auto"}, "nt", 0, ("cpu", "int8")),
    ({"VSTUDIO_WHISPER_DEVICE": "CPU", "VSTUDIO_WHISPER_COMPUTE": "float32"}, "posix", 1, ("cpu", "float32")),
])
def test_faster_whisper_device(env, platform, cuda, want):
    assert asr.faster_device(env=env, platform=platform, cuda_count=cuda) == want


def test_faster_whisper_cuda_failure_says_how_to_use_the_cpu(monkeypatch):
    import sys
    import types

    class Model:
        def __init__(self, name, device, compute_type):
            if device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(asr, "faster_device", lambda: ("cuda", "float16"))
    with pytest.raises(RuntimeError, match="VSTUDIO_WHISPER_DEVICE=cpu"):
        asr._run_faster("a.wav", "zh", None, True, None)


def test_faster_whisper_gets_samples_not_a_path(monkeypatch, tmp_path):
    import sys
    import types

    import numpy as np
    import soundfile as sf
    wav = tmp_path / "a16 语音.wav"
    sf.write(str(wav), np.zeros(16000, dtype="float32"), 16000)
    seen = {}

    class Seg:
        start, end, text, words = 0.0, 1.0, " ok", []

    class Model:
        def __init__(self, name, device, compute_type):
            seen["device"] = (device, compute_type)

        def transcribe(self, audio, **kw):
            seen["audio"] = audio
            return iter([Seg()]), None
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(asr, "faster_device", lambda: ("cpu", "int8"))
    out = asr._run_faster(str(wav), "zh", None, True, "tiny")
    assert out[0]["text"] == " ok" and seen["device"] == ("cpu", "int8")
    assert isinstance(seen["audio"], np.ndarray) and seen["audio"].dtype == np.float32 and seen["audio"].shape == (16000,)


# ------------------------------------------------------------------ CLIs (claude / codex) on Windows
NPM_SHIM = r"""@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0

IF EXIST "%dp0%\node.exe" (
  SET "_prog=%dp0%\node.exe"
) ELSE (
  SET "_prog=node"
  SET PATHEXT=%PATHEXT:;.JS;=;%
)

endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\node_modules\@anthropic-ai\claude-code\cli.js" %*
"""


def _npm_prefix(tmp_path, name="claude", shim=NPM_SHIM, script="node_modules/@anthropic-ai/claude-code/cli.js"):
    d = tmp_path / "Roaming 用户" / "npm"                      # spaces + CJK in the profile path
    (d / os.path.dirname(script)).mkdir(parents=True)
    (d / script).write_text("// cli\n")
    (d / f"{name}.cmd").write_text(shim, newline="\r\n")
    return d


def test_cli_argv_unwraps_npm_cmd_shims(tmp_path, monkeypatch):
    d = _npm_prefix(tmp_path)
    exe = str(d / "claude.cmd")
    script = os.path.normpath(str(d / "node_modules/@anthropic-ai/claude-code/cli.js"))
    monkeypatch.setattr(llm.shutil, "which", lambda n: "/usr/bin/node" if n == "node" else None)
    assert llm.cli_argv(exe, windows=True) == ["/usr/bin/node", script]
    (d / "node.exe").write_text("")                                  # node next to the shim wins
    assert llm.cli_argv(exe, windows=True) == [str(d / "node.exe"), script]
    assert llm.cli_argv(exe, windows=False) == [exe]                  # not Windows: run as is
    assert llm.cli_argv(str(d / "claude.exe"), windows=True) == [str(d / "claude.exe")]


def test_cli_argv_keeps_unknown_shims_and_native_targets(tmp_path, monkeypatch):
    d = _npm_prefix(tmp_path, shim="@echo off\r\nstart something\r\n")
    assert llm.cli_argv(str(d / "claude.cmd"), windows=True) == [str(d / "claude.cmd")]
    # pnpm-style shim pointing at a native executable
    d2 = tmp_path / "pnpm"
    (d2 / "bin").mkdir(parents=True)
    (d2 / "bin" / "codex.exe").write_text("")
    (d2 / "codex.cmd").write_text('@"%~dp0\\bin\\codex.exe"   %*\r\n')
    assert llm.cli_argv(str(d2 / "codex.cmd"), windows=True) == [os.path.normpath(str(d2 / "bin" / "codex.exe"))]
    # target missing (half-uninstalled package) or no node: the shim itself
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    d3 = _npm_prefix(tmp_path / "x")
    assert llm.cli_argv(str(d3 / "claude.cmd"), windows=True) == [str(d3 / "claude.cmd")]


def test_cli_names_on_windows(monkeypatch):
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD;.VBS;.JS")
    assert llm._exe_names("claude", True) == ["claude.com", "claude.exe", "claude.bat", "claude.cmd"]
    assert llm._exe_names("claude", False) == ["claude"]
    assert llm._exe_names("claude.exe", True) == ["claude.exe"]
    assert "%APPDATA%/npm" in llm.CLI_EXTRA_DIRS_WIN and "~/.local/bin" in llm.CLI_EXTRA_DIRS_WIN


def test_find_cli_extra_dirs_expand_variables(tmp_path, monkeypatch):
    d = tmp_path / "npm prefix"
    d.mkdir()
    exe = d / "codex"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    monkeypatch.setenv("VSTUDIO_TEST_PREFIX", str(tmp_path))
    monkeypatch.setenv("VSTUDIO_CLI_EXTRA_DIRS", os.pathsep.join(["%VSTUDIO_UNSET_VAR_X%/npm",
                                                                 "$VSTUDIO_TEST_PREFIX/npm prefix"]))
    if os.name == "nt":
        os.rename(exe, d / "codex.cmd")
        assert llm.find_cli("codex") == str(d / "codex.cmd")
    else:
        assert llm.find_cli("codex") == str(exe)


# ------------------------------------------------------------------ H.264 without libx264 (LGPL ffmpeg)
def test_openh264_rewrite_and_args():
    cmd = ["ffmpeg", "-i", "a.mp4", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "o.mp4"]
    o = h264.rewrite(cmd, "libopenh264")
    assert o[o.index("-c:v") + 1] == "libopenh264" and "-profile:v" not in o and "-crf" not in o
    assert "-b:v" in o and o[o.index("-pix_fmt") + 1] == "yuv420p" and o[-1] == "o.mp4"
    a = media.delivery_args(encoder="libopenh264", crf=18)
    assert a[a.index("-c:v") + 1] == "libopenh264" and "-profile:v" not in a and "-b:v" in a


@pytest.fixture
def fresh_probe(monkeypatch):
    monkeypatch.setattr(h264, "_PROBED", {})
    monkeypatch.setattr(h264, "_LISTED", {})
    monkeypatch.delenv("VSTUDIO_H264_PROBED", raising=False)


def test_fallback_without_libx264_is_openh264(monkeypatch, fresh_probe):
    h264._LISTED["ff-lgpl"] = {"h264_mf", "libopenh264", "mpeg4"}
    h264._LISTED["ff-gpl"] = {"libx264", "libopenh264"}
    h264._PROBED.update({"ff-lgpl|h264_mf": False, "ff-lgpl|libopenh264": True})
    monkeypatch.setenv("VSTUDIO_H264_ENCODER", "h264_mf")
    assert h264.effective_encoder("ff-lgpl") == "libopenh264"
    assert h264.fallback("h264_mf", "ff-lgpl") == "libopenh264"
    assert h264.fallback("libopenh264", "ff-gpl") == "libx264"
    h264._PROBED["ff-lgpl|libopenh264"] = False
    assert h264.fallback("h264_mf", "ff-lgpl") == "libx264"          # nothing works: the old default
    h264._LISTED["ff-unknown"] = None                                 # list unreadable: libx264 assumed
    assert h264.works("libx264", "ff-unknown")


def test_probe_cache_in_environment_keeps_several_entries(monkeypatch, fresh_probe):
    h264._LISTED["C:\\ff mpeg\\ffmpeg.exe"] = {"h264_mf", "h264_nvenc"}
    calls = []

    class P:
        def __init__(self, cmd, **kw):
            calls.append(cmd)
            self.rc = 0 if "h264_mf" in cmd else 1

        def wait(self, timeout=None):
            return self.rc
    monkeypatch.setattr(h264.subprocess, "Popen", P)
    ff = "C:\\ff mpeg\\ffmpeg.exe"
    assert h264.works("h264_mf", ff) and not h264.works("h264_nvenc", ff) and not h264.works("h264_qsv", ff)
    assert len(calls) == 2                                             # qsv is not listed: no test encode
    h264._PROBED.clear()
    assert h264.works("h264_mf", ff) and not h264.works("h264_nvenc", ff) and len(calls) == 2   # from the env


def test_media_run_falls_back_to_openh264(monkeypatch):
    calls = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, b"", b"boom"

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return R(1 if "h264_mf" in cmd else 0)
    monkeypatch.setattr(h264, "effective_encoder", lambda *a: "h264_mf")
    monkeypatch.setattr(h264, "fallback", lambda failed=None, ff=None: "libopenh264")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    monkeypatch.setattr(media, "STALL_S", 0)           # no stall watchdog: ffmpeg goes through subprocess.run
    media.run(["ffmpeg", "-i", "a.mp4", "-c:v", "libx264", "-crf", "18", "-profile:v", "high", "o.mp4"])
    assert "h264_mf" in calls[0] and "libopenh264" in calls[1] and "-profile:v" not in calls[1]


# ------------------------------------------------------------------ paths: spaces, CJK, brackets, '#', quotes
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


@needs_ffmpeg
@pytest.mark.parametrize("folder, name", [
    ("with space", "clip one.mp4"),
    ("中文 目录", "口播 第1条.mp4"),
    ("brackets [1] (copy)", "it's #2 & more.mp4"),
])
def test_media_paths_with_odd_names(tmp_path, folder, name):
    d = tmp_path / folder
    d.mkdir()
    src = d / name
    subprocess.run([media.ffmpeg_bin(), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1.2", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=1.2:r=10",
                    "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(src)], check=True)
    assert 1.0 < media.duration(str(src)) < 1.5
    wav = d / "音频 a.wav"
    media.extract_wav(str(src), str(wav), start=0.2, end=0.8)
    assert 0.5 < media.duration(str(wav)) < 0.7
    png = d / "帧 [0].png"
    media.grab_frame(str(src), 0.5, str(png))
    assert png.stat().st_size > 0
