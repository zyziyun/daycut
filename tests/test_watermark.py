"""vstudio.watermark: settings (persona <- file), off unless set up, default / per-job / per-platform switches, the
three kinds (text, image with alpha, generated badge), corner placement inside each platform's safe area and above
the captions, and the real render paths: vstudio.export (ffmpeg fast path + frame pipe) and the output render
(project.outrender encode + frame pass), never drawn twice on an already-marked export. Synthetic media only."""
import json
import os
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from vstudio import platform as P
from vstudio import watermark as WM

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
media = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("VSTUDIO_WATERMARK_FILE", raising=False)
    WM._SRC.clear()


# ----------------------------------------------------------------------------------- settings
def test_off_until_set_up_then_default_switch():
    cfg = WM.load()
    assert cfg["default"] is False and not WM.configured(cfg)
    assert WM.resolve("tiktok") is None
    assert WM.resolve("tiktok", override=True) is None           # nothing to draw: even "on" draws nothing
    WM.save(dict(text="@me"))
    assert WM.configured(WM.load()) and WM.resolve("tiktok") is None   # set up but not on by default
    assert WM.resolve("tiktok", override=True)                    # a job may ask for it
    WM.save(dict(default=True))
    assert WM.resolve("tiktok:vertical")
    assert WM.resolve("tiktok", override=False) is None           # per job / clip off
    assert WM.resolve("tiktok", override="off") is None
    WM.save(dict(platforms={"douyin": False}))
    assert WM.resolve("douyin:vertical") is None and WM.resolve("douyin", override="on")
    assert WM.resolve("youtube")
    with open(WM.settings_path(), encoding="utf-8") as f:
        assert json.load(f) == dict(text="@me", default=True, platforms={"douyin": False})


def test_validate_rejects_bad_values_and_file_is_lenient(tmp_path):
    for bad in (dict(kind="video"), dict(position="middle"), dict(size=2), dict(opacity="x"), dict(color="red"),
                dict(default="yes"), dict(nope=1), dict(text="x" * 60), dict(image="/a/logo.gif")):
        with pytest.raises(ValueError):
            WM.save(bad)
    os.makedirs(os.path.dirname(WM.settings_path()), exist_ok=True)
    with open(WM.settings_path(), "w") as f:
        json.dump(dict(text="@me", size=9, position="nowhere", default=True), f)
    cfg = WM.load()                                               # bad values dropped, good ones kept
    assert cfg["text"] == "@me" and cfg["size"] == WM.DEFAULTS["size"] and cfg["position"] == "bottom-right"
    assert cfg["default"] is True


def test_persona_layer_under_the_file(monkeypatch):
    from vstudio import config
    monkeypatch.setattr(config, "persona", lambda: dict(watermark=dict(text="@persona", position="top-left",
                                                                        default=True)))
    cfg = WM.load()
    assert cfg["text"] == "@persona" and cfg["position"] == "top-left" and WM.resolve("x")
    WM.save(dict(text="@file"))
    cfg = WM.load()
    assert cfg["text"] == "@file" and cfg["position"] == "top-left"


# ----------------------------------------------------------------------------------- drawing
@pytest.mark.parametrize("style", WM.STYLES)
def test_generate_draws_a_transparent_logo(tmp_path, style):
    out = WM.generate("@ziyun", style, "#FFD60A", out=str(tmp_path / f"{style}.png"))
    im = Image.open(out)
    assert im.mode == "RGBA" and im.width > im.height > 40
    a = np.asarray(im)[..., 3]
    assert a.max() == 255 and a[0, 0] == 0                        # opaque mark, transparent corners
    again = WM.generate("@ziyun", style, "#FFD60A")               # cached by content in the watermark folder
    assert again.startswith(WM.asset_dir()) and WM.generate("@ziyun", style, "#FFD60A") == again
    with pytest.raises(ValueError):
        WM.generate("   ")


def test_generated_logo_is_safe_to_draw_from_parallel_requests():
    """The desk asks for two previews at once: no request may read a half-written generated PNG."""
    from concurrent.futures import ThreadPoolExecutor
    cfg = dict(WM.DEFAULTS, kind="generate", text="@race", style="monogram")

    def one(_):
        WM._SRC.clear()
        return WM.preview(cfg, "9:16", height=64).size
    with ThreadPoolExecutor(8) as ex:
        assert len(set(ex.map(one, range(32)))) == 1
    assert not [f for f in os.listdir(WM.asset_dir()) if f.endswith(".part")]


def test_image_logo_keeps_alpha_and_is_placed_by_what_shows(tmp_path):
    logo = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    logo.paste(Image.new("RGBA", (200, 100), (255, 0, 0, 255)), (100, 150))      # a wide transparent margin
    p = str(tmp_path / "logo.png")
    logo.save(p)
    stored = WM.import_logo(p)
    assert stored.startswith(WM.asset_dir()) and stored.endswith(".png")
    cfg = WM.save(dict(kind="image", image=stored, default=True, opacity=1.0))
    assert WM.configured(cfg)
    arr, (x, y) = WM.layer(cfg, 1080, 1920, P.profile("tiktok", "vertical"))
    assert arr.shape[1] == round(cfg["size"] * 1080) and abs(arr.shape[1] / arr.shape[0] - 2.0) < 0.05
    assert arr[..., 3].max() == 255 and tuple(arr[arr.shape[0] // 2, arr.shape[1] // 2, :3]) == (255, 0, 0)
    with pytest.raises(ValueError):
        WM.import_logo(str(tmp_path / "missing.png"))
    (tmp_path / "bad.png").write_text("not an image")
    with pytest.raises(ValueError):
        WM.import_logo(str(tmp_path / "bad.png"))
    os.remove(stored)
    assert not WM.configured(WM.load())                            # the logo is gone: nothing is drawn


def test_opacity_is_applied():
    cfg = dict(WM.DEFAULTS, text="@me", opacity=0.5)
    full = dict(cfg, opacity=1.0)
    a, _ = WM.layer(cfg, 1080, 1920)
    b, _ = WM.layer(full, 1080, 1920)
    assert abs(int(a[..., 3].max()) - 128) <= 2 and b[..., 3].max() == 255


VERTICAL = ["tiktok:vertical", "douyin:vertical", "instagram:vertical", "youtube-shorts:vertical",
            "wechat-channels:vertical", "xiaohongshu:full", "xiaohongshu:vertical"]


@pytest.mark.parametrize("key", VERTICAL + ["youtube:horizontal", "bilibili:horizontal", "x:horizontal"])
@pytest.mark.parametrize("pos", WM.POSITIONS)
@pytest.mark.parametrize("kind", ["text", "generate"])
def test_every_corner_stays_in_the_safe_area_and_off_the_captions(key, pos, kind):
    n, o = key.split(":")
    prof = P.profile(n, o)
    cfg = dict(WM.DEFAULTS, kind=kind, text="@a.long.handle", position=pos, default=True)
    x, y, w, h = WM.box(cfg, prof.w, prof.h, prof)
    safe, cap = WM.areas(prof.w, prof.h, prof)
    assert safe[0] - 1 <= x and x + w <= safe[2] + 1 and safe[1] - 1 <= y and y + h <= safe[3] + 1
    assert not WM._hits((x, y, x + w, y + h), cap)
    if prof.h > prof.w:                                            # vertical: the whole caption band is kept clear
        cx0, cy0, cx1, cy1 = P.caption_box(prof)
        assert y + h <= cy0 or y >= cy1 or x + w <= cx0 or x >= cx1
    assert (x + w / 2 < prof.w / 2) == pos.endswith("left")
    assert (y + h / 2 < prof.h / 2) == pos.startswith("top")


def test_bottom_corner_of_a_vertical_canvas_moves_above_the_captions():
    prof = P.profile("tiktok", "vertical")
    cfg = dict(WM.DEFAULTS, text="@me", position="bottom-right")
    x, y, w, h = WM.box(cfg, prof.w, prof.h, prof)
    assert y + h <= P.caption_box(prof)[1]
    assert x + w <= P.safe_box(prof)[2]                            # clear of the like / comment column


def test_canvas_without_profile_uses_the_closest_platform():
    cfg = dict(WM.DEFAULTS, text="@me")
    a = WM.box(cfg, 1080, 1920)
    b = WM.box(cfg, 1080, 1920, P.profile("tiktok", "vertical", use_persona=False))
    assert a == b
    x, y, w, h = WM.box(cfg, 1000, 1000)                           # square: plain margins
    assert x + w <= 960 + 1 and y + h <= 960 + 1


def test_preview_and_spec():
    assert WM.preview(dict(WM.DEFAULTS), "16:9", height=180).size == (320, 180)    # not set up: sample only
    cfg = dict(WM.DEFAULTS, text="@me", kind="generate", style="monogram")
    url = WM.preview_data_url(cfg, "9:16", height=320)
    assert url.startswith("data:image/jpeg;base64,") and len(url) > 1000
    s = WM.spec(cfg, 1080, 1920, P.profile("tiktok", "vertical"))
    assert WM.from_spec(json.loads(json.dumps(s)))["style"] == "monogram" and len(s["box"]) == 4


def test_cli_set_show_generate(tmp_path):
    assert WM.main(["set", "--text", "@cli", "--position", "top-left", "--default", "on", "--platform", "x=off"]) == 0
    cfg = WM.load()
    assert cfg["text"] == "@cli" and cfg["default"] and cfg["platforms"] == {"x": False}
    assert WM.main(["generate", "--text", "@cli", "--out", str(tmp_path / "g.png")]) == 0
    assert os.path.exists(tmp_path / "g.png")
    assert WM.main(["set", "--size", "3"]) == 2


# ----------------------------------------------------------------------------------- real render paths
def _clip(path, w=540, h=960, d=1.2):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x404040:s={w}x{h}:d={d}:r=25",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={d}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return str(path)


_N = [0]


def _frame(video, t=0.5):
    from vstudio import media as M
    _N[0] += 1
    out = video + f".{_N[0]}.png"
    M.grab_frame(video, t, out)
    return np.asarray(Image.open(out).convert("RGB")).astype(np.int16)


def _marked(img, box):
    """The mark's box differs clearly from the flat grey picture (the median)."""
    x, y, w, h = box
    base = np.median(img.reshape(-1, 3), axis=0)
    return float(np.abs(img[y:y + h, x:x + w] - base).mean()) > 12


@media
@pytest.mark.parametrize("with_cues", [False, True])
def test_export_draws_it_by_default_and_a_job_can_turn_it_off(tmp_path, with_cues):
    from vstudio import export as X
    master = _clip(tmp_path / "m.mp4")
    WM.save(dict(text="@me", default=True, opacity=1.0, size=0.3))
    prof = P.profile("tiktok", "vertical")
    cues = None
    if with_cues:                                                  # captions = the frame pipe, not the fast path
        cues = str(tmp_path / "cues.json")
        with open(cues, "w") as f:
            json.dump([dict(start=0.0, end=1.2, text="字幕")], f)
    os.makedirs(tmp_path / "on")
    on = X.export_one(master, prof, str(tmp_path / "on"), cues=cues)
    assert on["watermark"]["kind"] == "text" and on["watermark"]["text"] == "@me"
    box = on["watermark"]["box"]
    assert _marked(_frame(str(tmp_path / "on" / on["file"])), box)
    os.makedirs(tmp_path / "off")
    off = X.export_one(master, prof, str(tmp_path / "off"), cues=cues, watermark=False)
    assert off["watermark"] is None and not _marked(_frame(str(tmp_path / "off" / off["file"])), box)


@media
def test_export_never_marks_a_marked_export_twice(tmp_path):
    from vstudio import export as X
    master = _clip(tmp_path / "m.mp4")
    WM.save(dict(text="@me", default=True))
    man = X.export(master, ["tiktok:vertical"], out_dir=str(tmp_path / "ex"))
    e = man["exports"][0]
    assert e["watermark"] and WM.already_marked(str(tmp_path / "ex" / e["file"]))
    os.makedirs(tmp_path / "ex2")
    again = X.export_one(str(tmp_path / "ex" / e["file"]), P.profile("tiktok", "vertical"), str(tmp_path / "ex2"))
    assert again["watermark"] is None and any("already carries" in w for w in again["warnings"])


def _work(tmp_path, video):
    w = tmp_path / "work"
    (w / "final").mkdir(parents=True)
    shutil.copy(video, w / "final" / "clip.mp4")
    (w / "REPORT.md").write_text("# clip\n")
    from vstudio.project import works
    works.adopt(str(w))
    return str(w), "final/clip.mp4"


@media
def test_output_render_final_has_it_preview_does_not(tmp_path):
    from vstudio.project import outputs as O
    from vstudio.project import outrender as R
    w, oid = _work(tmp_path, _clip(tmp_path / "src.mp4"))
    r0 = R.render(w, oid, quality="final")                         # not set up: the untouched picture (remux)
    assert r0["targets"][0]["watermark"] is False
    WM.save(dict(text="@me", default=True, opacity=1.0, size=0.3))
    rp = R.render(w, oid, quality="preview")
    assert rp["targets"][0]["watermark"] is False
    r1 = R.render(w, oid, quality="final")                         # encode path with the ffmpeg overlay
    t = r1["targets"][0]
    assert t["watermark"] is True and t["cached"] is False
    rec = O.resolve(w, oid)
    tg = R.targets_of(rec, O._load(w, oid)[1].state())[0]
    box = WM.box(WM.load(), tg["w"], tg["h"], tg["profile"])
    assert _marked(_frame(t["file"]), box)
    off = R.render(w, oid, quality="final", watermark=False)
    assert off["targets"][0]["watermark"] is False and not _marked(_frame(off["targets"][0]["file"]), box)
    O.edit(w, oid, [dict(op="effect_add", effect="stamp", start=0.2, params=dict(text="亲测"))])
    r2 = R.render(w, oid, quality="final")                         # frame pass draws it too
    assert r2["targets"][0]["watermark"] is True and _marked(_frame(r2["targets"][0]["file"]), box)


@media
def test_output_render_skips_a_flattened_file_that_is_already_marked(tmp_path):
    from vstudio.project import outrender as R
    w, oid = _work(tmp_path, _clip(tmp_path / "src.mp4"))
    with open(os.path.join(w, "final", "manifest.json"), "w") as f:
        json.dump(dict(exports=[dict(file="clip.mp4", watermark=dict(kind="text"))]), f)
    WM.save(dict(text="@me", default=True))
    assert R.render(w, oid, quality="final")["targets"][0]["watermark"] is False


@media
def test_apply_file(tmp_path):
    src = _clip(tmp_path / "a.mp4", 1280, 720)
    cfg = WM.save(dict(text="@me", opacity=1.0, size=0.3))
    out = WM.apply_file(src, str(tmp_path / "b.mp4"), cfg)
    assert _marked(_frame(out), WM.box(cfg, 1280, 720))
