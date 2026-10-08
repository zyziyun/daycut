"""Render tooling outside Python: the Node resolver (vstudio.node), stage-error tails without progress bars
(vstudio.proctail, batch stage errors), the bundled ffmpeg / ffprobe pairing and promo-recut export.py's delivery."""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import media, node, proctail  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="stub node scripts are POSIX shell")

DYLD = ("dyld[4242]: Library not loaded: /opt/homebrew/opt/simdjson/lib/libsimdjson.29.dylib\n"
        "  Referenced from: <ABC> /opt/homebrew/Cellar/node/25.6.1/bin/node\n  Reason: tried: ... (no such file)")


def stub(d, body, name="node"):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return p


def broken(d):
    return stub(d, f"cat >&2 <<'EOF'\n{DYLD}\nEOF\nexit 1")


def version(d, v):
    return stub(d, f'echo "{v}"')


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(node, "SYSTEM_DIRS", ())          # never probe this machine's real Homebrew node
    node.clear_cache()
    yield
    node.clear_cache()


def env_with(*dirs):
    return {"PATH": os.pathsep.join(str(d) for d in dirs)}


# ------------------------------------------------------------------ resolver
def test_skips_broken_and_old_node_and_picks_newest_nvm(tmp_path):
    home = tmp_path / "home"
    brew = tmp_path / "opt" / "homebrew" / "bin"
    old = tmp_path / "old" / "bin"
    broken(brew)
    version(old, "v16.20.2")
    nvm = home / ".nvm" / "versions" / "node"
    version(nvm / "v20.11.0" / "bin", "v20.11.0")
    version(nvm / "v22.9.0" / "bin", "v22.9.0")
    version(nvm / "v9.0.0" / "bin", "v9.0.0")
    doc = node.resolve(env_with(brew, old), home=str(home))
    assert doc["version"] == "v22.9.0"
    assert doc["bin"] == str(nvm / "v22.9.0" / "bin")
    checked = {c["path"]: c for c in doc["checked"]}
    assert checked[str(brew / "node")]["ok"] is False
    assert "Library not loaded" in checked[str(brew / "node")]["error"]
    assert "too old" in checked[str(old / "node")]["error"]


def test_path_order_wins_when_it_works(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    version(a, "v18.0.0")
    version(b, "v22.1.0")
    assert node.resolve(env_with(a, b), home=str(tmp_path / "h"))["bin"] == str(a)


def test_volta_and_fnm_are_candidates(tmp_path):
    home = tmp_path / "home"
    version(home / ".volta" / "bin", "v22.0.0")
    assert node.resolve(env_with(), home=str(home))["bin"] == str(home / ".volta" / "bin")
    node.clear_cache()
    home2 = tmp_path / "home2"
    fnm = home2 / ".local" / "share" / "fnm" / "node-versions"
    version(fnm / "v20.0.0" / "installation" / "bin", "v20.0.0")
    version(fnm / "v22.3.0" / "installation" / "bin", "v22.3.0")
    assert node.resolve(env_with(), home=str(home2))["version"] == "v22.3.0"


def test_broken_only_raises_with_path_first_stderr_line_and_brew_fix(tmp_path):
    brew = tmp_path / "opt" / "homebrew" / "bin"
    broken(brew)
    with pytest.raises(node.NodeError) as ei:
        node.resolve(env_with(brew), home=str(tmp_path / "h"))
    msg = str(ei.value)
    assert str(brew / "node") in msg
    assert "dyld[4242]: Library not loaded: /opt/homebrew/opt/simdjson/lib/libsimdjson.29.dylib" in msg
    assert "brew reinstall node" in msg and "Node 22" in msg
    assert ei.value.code == "tool-node"
    assert node.health(env_with(brew), home=str(tmp_path / "h"))["ok"] is False      # health never raises


def test_old_only_and_none(tmp_path):
    old = tmp_path / "old"
    version(old, "v16.20.2")
    with pytest.raises(node.NodeError, match=r"v16\.20\.2.*18\+.*Install Node 22"):
        node.resolve(env_with(old), home=str(tmp_path / "h"))
    with pytest.raises(node.NodeError, match="not installed"):
        node.resolve(env_with(tmp_path / "empty"), home=str(tmp_path / "h"), refresh=True)


def test_cached_per_process(tmp_path, monkeypatch):
    a = tmp_path / "a"
    version(a, "v22.0.0")
    env = env_with(a)
    node.resolve(env, home=str(tmp_path / "h"))
    calls = []
    monkeypatch.setattr(node, "probe", lambda p, timeout=15: calls.append(p))
    assert node.resolve(env, home=str(tmp_path / "h"))["version"] == "v22.0.0"
    assert calls == []


def test_child_env_puts_the_good_node_first_and_npx_from_its_folder(tmp_path):
    brew = tmp_path / "opt" / "homebrew" / "bin"
    good = tmp_path / "good"
    broken(brew)
    version(good, "v22.0.0")
    stub(good, "exit 0", name="npx")
    ff = tmp_path / "ff"
    e = node.child_env(env_with(brew, good), home=str(tmp_path / "h"), extra_dirs=[str(ff)])
    parts = e["PATH"].split(os.pathsep)
    assert parts[:2] == [str(ff), str(good)] and str(brew) in parts
    assert node.npx("hyperframes", "render", env=e, home=str(tmp_path / "h"))[:2] == [str(good / "npx"), "hyperframes"]


def test_explicit_vstudio_node(tmp_path):
    p = version(tmp_path / "x", "v22.2.0")
    env = dict(env_with(), VSTUDIO_NODE=str(p))
    assert node.resolve(env, home=str(tmp_path / "h"))["path"] == str(p)


# ------------------------------------------------------------------ stderr tails
HF_OUT = ("\n◆  Rendering promo → renders/_raw.mp4\n"
          + "".join(f"  {'█' * (i // 4)}{'░' * (25 - i // 4)}  {i}%  Capturing frames\r" for i in range(0, 100, 5))
          + "\n@hf-progress {\"code\":\"capture\",\"pct\":50}\n"
          + '[INFO] [Render:trace] {"phase":"encode","status":"end","elapsedMs":1}\n'
          + "[initSession:screenshot] media + fonts + tailwind ready (746ms)\n" * 30
          + "\x1b[?25l│\n")


def test_tail_drops_progress_and_keeps_the_error():
    err = HF_OUT + "Error opening output out/promo.loud.mp4: No such file or directory\n"
    t = proctail.tail(err)
    assert t.splitlines()[-1] == "Error opening output out/promo.loud.mp4: No such file or directory"
    assert "%" not in t and "@hf-progress" not in t and "[INFO]" not in t and "initSession" not in t
    assert "█" not in t
    many = "\n".join(f"line {i}" for i in range(50))
    assert proctail.tail(many).splitlines() == [f"line {i}" for i in range(30, 50)]


def test_clean_error_keeps_head_and_meaningful_tail():
    msg = "export.py exit 1: " + HF_OUT + "error: delivery failed: No such file or directory"
    c = proctail.clean_error(msg)
    assert c.startswith("export.py exit 1:")
    assert c.endswith("error: delivery failed: No such file or directory")
    assert "█" not in c and "@hf-progress" not in c
    assert proctail.clean_error("plain message") == "plain message"
    assert proctail.clean_error("x exit 1: " + HF_OUT).startswith("x exit 1:")


def test_batch_stage_error_is_cleaned(tmp_path):
    from vstudio.batch import run as R
    src = (ROOT / "lib" / "vstudio" / "batch" / "run.py").read_text()
    assert "proctail.clean_error(e)" in src
    assert R.proctail is proctail


# ------------------------------------------------------------------ ffmpeg pairing
def test_ffprobe_next_to_the_named_ffmpeg(tmp_path, monkeypatch):
    d = tmp_path / "rt" / "ffmpeg" / "bin"
    stub(d, "exit 0", name="ffmpeg")
    stub(d, "exit 0", name="ffprobe")
    monkeypatch.setenv("VSTUDIO_FFMPEG", str(d / "ffmpeg"))
    monkeypatch.delenv("VSTUDIO_FFPROBE", raising=False)
    media.ffprobe_bin.cache_clear()
    media._ffmpeg_bin.cache_clear()
    try:
        assert media.ffprobe_bin() == str(d / "ffprobe")
        assert media.ffmpeg_dir() == str(d)
    finally:
        media.ffprobe_bin.cache_clear()
        media._ffmpeg_bin.cache_clear()


# ------------------------------------------------------------------ export.py delivery
@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_export_creates_the_output_folder(tmp_path):
    raw = tmp_path / "promo" / "renders" / "_raw.mp4"
    raw.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(raw)], check=True)
    out = tmp_path / "items" / "AIGC" / "out" / "promo.mp4"          # out/ does not exist yet (the app's case)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"))
    r = subprocess.run([sys.executable, str(ROOT / "workflows/promo-recut/scripts/export.py"), "--skip-render",
                        str(raw), str(out)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert out.exists() and not (out.parent / "promo.loud.mp4").exists()


def test_export_render_reports_a_broken_node(tmp_path):
    brew = tmp_path / "opt" / "homebrew" / "bin"
    broken(brew)
    proj = tmp_path / "promo"
    proj.mkdir()
    env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"), PATH=f"{brew}{os.pathsep}/usr/bin{os.pathsep}/bin",
               HOME=str(tmp_path / "home"))
    env["VSTUDIO_NODE"] = str(brew / "node")          # only the broken node, whatever this machine has
    r = subprocess.run([sys.executable, str(ROOT / "workflows/promo-recut/scripts/export.py"), str(proj),
                        str(tmp_path / "out" / "p.mp4")], capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "node unavailable" in r.stderr
    assert "Traceback" not in r.stderr
    assert "Library not loaded" in r.stderr and "brew reinstall node" in r.stderr


def test_tool_failure_codes():
    f = proctail.tool_failure("export.py exit 1: dyld: Library not loaded: /opt/homebrew/opt/simdjson/lib/"
                              "libsimdjson.29.dylib\n  Referenced from: /opt/homebrew/Cellar/node/25.6.1/bin/node")
    assert f == dict(code="tool-node", params=dict(tool="node", fix="brew-reinstall-node"))
    assert proctail.tool_failure("node unavailable: the Node.js at /x/node is v16.1.0; HyperFrames needs 18+")[
        "params"]["fix"] == "install-node"
    assert proctail.tool_failure("FFmpegError: VSTUDIO_FFMPEG=/Applications/Reelfold.app/x/ffmpeg does not exist") == \
        dict(code="tool-ffmpeg", params=dict(tool="ffmpeg", fix="reinstall-app"))
    assert proctail.tool_failure("Unknown bitstream filter h264_metadata")["code"] == "tool-ffmpeg"
    assert proctail.tool_failure("Error opening output out/promo.loud.mp4: No such file or directory") is None
    assert proctail.tool_failure("Node.js nodejs.org dyld something") is None
