"""promo-recut build_promo end to end on a synthetic project: hook montage in front (every later time shifted),
PiP windows (video + image series, bridged), scene / video / screenshot cards, privacy crop of a screen
recording, timeline.json for post_copy; `npx hyperframes lint` = 0 errors when node is available.

    python3 -m pytest tests/test_promo_build_e2e.py -q
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = ROOT / "workflows" / "promo-recut" / "scripts"
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import media  # noqa: E402
from vstudio.cut import TimeMap  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _clip(path, dur, size="640x360", color=None, top_bar=0, audio=True):
    src = f"testsrc2=s={size}:d={dur}:r=30" if color is None else f"color=c={color}:s={size}:d={dur}:r=30"
    if top_bar:
        src += f",drawbox=x=0:y=0:w=iw:h={top_bar}:color=0xE6E6E6:t=fill"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=440:d={dur}", "-shortest"]
    media.run(cmd + media.delivery_args(crf=30, preset="ultrafast", audio=audio) + [str(path)])


def _png(path, w=760, h=1600, color=(240, 240, 240)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    for y in range(100, h, 120):
        d.rectangle([40, y, w - 40, y + 40], fill=(60, 60, 60))
    im.save(path)


def make_project(tmp, hooks=True):
    work, inp = tmp / "work", tmp / "input"
    work.mkdir(parents=True)
    inp.mkdir()
    _clip(work / "body.mp4", 20)
    _clip(work / "montage.mp4", 6)
    _clip(work / "outro.mp4", 3)
    if hooks:
        _clip(work / "hooks.mp4", 5)
    _clip(inp / "clip.mp4", 4)
    _clip(inp / "rec1.mov", 5, color="0x101010", top_bar=42, audio=False)   # a "screen recording": auto crop
    _png(inp / "shot.png")
    (inp / "web").mkdir()
    _png(inp / "web" / "01.png", 1280, 720, (200, 220, 240))
    _png(inp / "web" / "02.png", 1280, 720, (240, 220, 200))
    tm = lambda d: TimeMap.from_segments([(0, d)]).to_list()
    layout = {"D": {"body": 20.0, "outro": 3.0, "montage": 6.0}, "maps": {"body": tm(20), "outro": tm(3)},
              "words": {}, "clips": [[0, 3], [3, 6.3]]}
    if hooks:
        layout["D"]["hooks"] = 5.0
        layout["hooks"] = [{"s": 0.0, "e": 2.5, "lines": ["第一句 hook", "控制【废片率】"]},
                           {"s": 2.5, "e": 5.0, "lines": ["第二句", "先出【480p】样片"]}]
    (work / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    cfg = {
        "talk": "input/talk.mp4", "language": "zh", "promo_dir": "promo", "orientation": "horizontal",
        "cut": {"body": [[0, 20]], "outro": [[30, 33]]},
        "rates": {"body": 1.25, "montage": 1.0},
        "subtitles": {"body": [[0.5, 2.0, "开头一句"], [6.6, 8.5, "成片和生成量【对比】"], [12.2, 14.0, "这是 MiniMax 的录屏"],
                               [14.8, 16.5, "再看 Hugging Face"]],
                      "outro": [[30.2, 32.5, "就这些"]]},
        "cards": [
            {"img": "input/shot.png", "start": 2.0, "end": 6.0, "scroll": [[2.0, 0], [4.0, 300]],
             "highlights": [[3.0, 100, 140, 0.6]], "about": "截图"},
            {"start": 6.5, "end": 9.0, "about": "对比",
             "scene": {"kind": "stat", "title": "废片率", "items": [[1, "分钟成片"], ["2.5–3", "分钟生成", True]],
                       "bars": [["成片", 36], ["生成", 100, True]], "foot": "大概 1.5–2 倍"}},
            {"video": "input/clip.mp4", "media_start": 0.5, "label": "成片节选", "start": 9.2, "end": 11.5},
        ],
        "pip": [
            {"start": 12.0, "end": 14.6, "video": "input/rec1.mov", "media_start": 0.5, "tag": "MiniMax · 录屏",
             "about": "MiniMax"},
            {"start": 14.7, "end": 17.5, "images": "input/web", "tag": "Hugging Face", "about": "Seedance"},
        ],
        "hold": {"at": 4.5, "duration": 1.5, "label": "prompt"},
        "punch": [[18.0, 19.0]],
        "montage": {"clips": [[0, 3, "第一段"], [3, 6.3, "第二段"]], "crossfade": 0.3, "title": "精选", "badge": "精选"},
        "outro": {"punch_at": 31.0, "stamp": "亲测"},
        "chapters": [["start", "背景"], [12.0, "录屏"], ["montage", "精选"], ["outro", "结尾"]],
        "end_card": {"kicker": "k", "main": "你最常用哪个？", "sub": "评论区 ↓", "duration": 2.0},
    }
    if hooks:
        cfg["hooks"] = {"speed": 2.0, "chapter": "开场",
                        "items": [{"spans": [[1.0, 6.0]], "lines": ["第一句 hook", "控制【废片率】"]},
                                  {"spans": [[8.0, 13.0]], "lines": ["第二句", "先出【480p】样片"]}]}
    (tmp / "promo.config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return tmp / "promo.config.json"


def build(cfg, *args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"))
    r = subprocess.run([sys.executable, str(S / "build_promo.py"), str(cfg), *args], capture_output=True, text=True,
                       env=env, cwd=str(cfg.parent))
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("promo")
    cfg = make_project(tmp)
    out = build(cfg)
    return tmp, out


def test_hooks_shift_everything_and_chapters(built):
    tmp, out = built
    tl = json.loads((tmp / "promo" / "timeline.json").read_text(encoding="utf-8"))
    assert tl["hooks"] == [0.0, 5.0] and tl["body_start"] == 5.0
    labels = [c[2] for c in tl["chapters"]]
    assert labels[0] == "开场" and tl["chapters"][0][:2] == [0.0, 5.0]
    bg = tl["chapters"][1]
    assert bg[2] == "背景" and bg[0] == 5.0                       # body chapter starts after the hooks
    assert abs(tl["chapters"][2][0] - (5.0 + 12.0 / 1.25 + 1.5)) < 0.01   # raw 12 -> after hooks + hold
    assert abs(tl["pip"][0][0] - (5.0 + 12.0 / 1.25 + 1.5)) < 0.01
    html = (tmp / "promo" / "index.html").read_text(encoding="utf-8")
    assert 'id="hooks"' in html and 'src="assets/video/hooks.mp4"' in html and 'id="flash"' in html
    cues = json.loads((tmp / "promo" / "cues.json").read_text(encoding="utf-8"))
    assert cues[0]["text"] == "第一句 hook\n控制【废片率】" and cues[0]["start"] < 1
    assert cues[2]["start"] >= 5.0                                 # first body caption after the hooks
    assert "footage map" in out


def test_pip_cards_and_crop(built):
    tmp, out = built
    html = (tmp / "promo" / "index.html").read_text(encoding="utf-8")
    # video window: wrapper untimed, video timed; image window: wrapper timed
    assert re.search(r'<div id="pip0" class="full pipscr"><div class="pipframe" id="pip0f"><video id="pip0v"', html)
    assert re.search(r'<div id="pip1" class="full clip pipscr" data-start=', html)
    assert html.count('class="pipring clip"') == 1                 # the two windows are bridged into one run
    assert 'class="scene" id="c2x"' in html and "sc-big" in html
    assert 'id="c3v"' in html and 'data-media-start="0.5"' in html
    assert '<div id="cards" class="full"' in html                  # card video -> #cards is a plain container
    assert "crop rec1.mov: [0, 44, 640, 316]" in out
    assert list((tmp / "work" / "clean").glob("rec1-*.mp4"))
    assert re.search(r"!\s+pip .*Seedance", out)                   # about vs captions mismatch is flagged
    assert not re.search(r"!\s+pip .*MiniMax", out)


def test_no_hooks_build_keeps_legacy_timing(tmp_path):
    cfg = make_project(tmp_path, hooks=False)
    build(cfg)
    tl = json.loads((tmp_path / "promo" / "timeline.json").read_text(encoding="utf-8"))
    assert tl["hooks"] is None and tl["chapters"][0][0] == 0.0
    html = (tmp_path / "promo" / "index.html").read_text(encoding="utf-8")
    assert 'id="hooks"' not in html and 'id="flash"' not in html


def test_post_copy_uses_shifted_chapters(built):
    tmp, _ = built
    env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"))
    cfg = json.loads((tmp / "promo.config.json").read_text(encoding="utf-8"))
    cfg["post"] = {"title": "t", "body": ["b"], "out": "post.md"}
    (tmp / "promo.config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(S / "post_copy.py"), str(tmp / "promo.config.json")], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, r.stderr
    text = (tmp / "post.md").read_text(encoding="utf-8")
    assert "00:00 开场" in text and "00:05 背景" in text


def test_pip_overlapping_card_is_an_error(tmp_path):
    cfg = make_project(tmp_path, hooks=False)
    c = json.loads(cfg.read_text(encoding="utf-8"))
    c["pip"][0]["start"] = 10.0                                   # into the video card [9.2, 11.5]
    cfg.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"))
    r = subprocess.run([sys.executable, str(S / "build_promo.py"), str(cfg)], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "overlaps card[2]" in r.stderr


NODE = next(iter(sorted(pathlib.Path.home().glob(".nvm/versions/node/*/bin"), reverse=True)), pathlib.Path("/nonexistent"))
NODE = str(NODE)
# lint flags a font family without @font-face; the subset fonts only exist after ./install.sh (not on CI runners)
from vstudio import config as _cfg  # noqa: E402


def _fonts_ok():
    try:
        return all(os.path.isfile(_cfg.font(r)) for r in ("cjk", "cjk-bold"))
    except Exception:  # noqa: BLE001 - MissingAsset when ./install.sh has not run
        return False


FONTS_OK = _fonts_ok()


@pytest.mark.skipif(not (shutil.which("npx") or os.path.exists(os.path.join(NODE, "npx"))), reason="node not installed")
@pytest.mark.skipif(not FONTS_OK, reason="fonts not installed (install.sh)")
@pytest.mark.parametrize("platform", [None, "douyin"])
def test_hyperframes_lint_zero_errors(built, platform):
    tmp, _ = built
    promo = tmp / "promo"
    if platform:
        build(tmp / "promo.config.json", "--platform", platform, "--out", "promo-v")
        promo = tmp / "promo-v"
    env = dict(os.environ, PATH=NODE + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run(["npx", "--yes", "hyperframes", "lint"], cwd=str(promo), capture_output=True, text=True,
                       env=env, timeout=600)
    out = r.stdout + r.stderr
    m = re.search(r"(\d+) error\(s\)", out)
    if m is None and "0 error" not in out and r.returncode != 0:
        pytest.skip("hyperframes lint unavailable: " + out[-300:])
    assert m is None or m.group(1) == "0", out


def test_example_config_builds_and_lints(tmp_path):
    """examples/promo.config.example.yaml as written (hooks, scene card, ...) builds on synthetic media."""
    import yaml
    ex = ROOT / "workflows" / "promo-recut" / "examples" / "promo.config.example.yaml"
    cfg = yaml.safe_load(ex.read_text(encoding="utf-8"))
    work, inp = tmp_path / "work", tmp_path / "input"
    work.mkdir()
    inp.mkdir()
    for cd in cfg["cards"]:
        if cd.get("img"):
            _png(tmp_path / cd["img"], 1200, 2400)
    _png(tmp_path / cfg["hold"]["image"], 1400, 300)
    body = TimeMap.from_segments([tuple(s) for s in cfg["cut"]["body"]])
    outro = TimeMap.from_segments([tuple(s) for s in cfg["cut"]["outro"]])
    nh = len(cfg["hooks"]["items"])
    D = {"body": round(body.duration, 3), "outro": round(outro.duration, 3), "montage": 30.0, "hooks": 2.0 * nh}
    _clip(work / "body.mp4", D["body"])
    _clip(work / "outro.mp4", D["outro"])
    _clip(work / "montage.mp4", D["montage"])
    _clip(work / "hooks.mp4", D["hooks"])
    layout = {"D": D, "maps": {"body": body.to_list(), "outro": outro.to_list()}, "words": {},
              "hooks": [{"s": 2.0 * k, "e": 2.0 * k + 2.0, "lines": it["lines"]} for k, it in enumerate(cfg["hooks"]["items"])]}
    (work / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    p = tmp_path / "promo.config.yaml"
    shutil.copy(ex, p)
    out = build(p)
    assert "hooks→" in out
    html = (tmp_path / "promo" / "index.html").read_text(encoding="utf-8")
    assert 'class="scene"' in html and 'id="hooks"' in html
    if FONTS_OK and (shutil.which("npx") or os.path.exists(os.path.join(NODE, "npx"))):
        env = dict(os.environ, PATH=NODE + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run(["npx", "--yes", "hyperframes", "lint"], cwd=str(tmp_path / "promo"), capture_output=True,
                           text=True, env=env, timeout=600)
        m = re.search(r"(\d+) error\(s\)", r.stdout + r.stderr)
        assert m is None or m.group(1) == "0", r.stdout + r.stderr
