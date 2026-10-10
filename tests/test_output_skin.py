"""Skin smoothing / beauty as an output-edit effect (``portrait-retouch``, 磨皮美颜): in the catalogue the chat's model
reads, its aliases (磨皮 / 美颜 / skin / beauty), the no-model rule ("磨个皮?"), the knobs per strength and mode, the
frame layer smoothing the tracked face only (texture kept, the background untouched), and a real render of an
output with it (the frame pass runs the layer; the clip comes out with the face area changed and nothing else).
Synthetic media and landmarks only (the face tracker is replaced by the synthetic face); no network."""
import json
import os
import shutil
import subprocess
import types

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
import _batch_helpers as H  # noqa: E402
from test_retouch import synth_face, synth_image  # noqa: E402
from vstudio import face as F  # noqa: E402
from vstudio import retouch as RT  # noqa: E402
from vstudio.project import outfx as FX  # noqa: E402
from vstudio.project import outputs as O  # noqa: E402
from vstudio.project import outrender as R  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


class FakeTracker:
    """VideoFaceTracker stand-in: the synthetic face on every frame (strictly increasing indices checked)."""

    def __init__(self, pts):
        self.pts, self.last, self.sm = pts, -1, types.SimpleNamespace(resets=0)

    def __call__(self, bgr, idx):
        assert idx > self.last
        self.last = idx
        return {"pts": self.pts, "raw": self.pts, "blend": {}}

    def close(self):
        pass


@pytest.fixture()
def face(monkeypatch):
    """The tracker sees the synthetic face; masks come from the landmarks (no segmentation model)."""
    def use(pts):
        monkeypatch.setattr(F, "VideoFaceTracker", lambda fps, **k: FakeTracker(pts))
    monkeypatch.setattr(RT, "segment_face", lambda *a, **k: None)
    return use


def test_catalogue_aliases_and_validation():
    row = {r["id"]: r for r in FX.catalogue()}["portrait-retouch"]
    assert (row["stage"], row["kind"], row["default_dur"]) == ("frame", "look", None)
    assert row["label"] == dict(en="Skin smoothing", zh="磨皮美颜")
    assert set(row["params"]) == {"strength", "mode"} and row["params"]["mode"]["enum"] == ["skin", "beauty"]
    for a in ("磨皮", "磨个皮", "美颜", "skin", "beauty", "retouch", "Skin smoothing"):
        assert FX.resolve(a) == "portrait-retouch", a
    clean, warns = FX.validate("磨皮", dict(strength=3, mode="glam"))
    assert clean == dict(strength=1.0, mode="skin") and len(warns) == 2


def test_no_model_rule_understands_skin_smoothing():
    assert O._rule_ops("磨个皮?", 10.0) == [dict(op="effect_add", effect="portrait-retouch", start=0,
                                                 params=dict(strength=0.5, mode="skin"))]
    (op,) = O._rule_ops("美颜，强一点", 10.0)
    assert op["params"] == dict(strength=0.8, mode="beauty")
    (op,) = O._rule_ops("smooth her skin a bit", 10.0)
    assert op["params"] == dict(strength=0.3, mode="skin")


def test_knobs_skin_keeps_the_face_shape_beauty_adds_a_little():
    a, b = RT.video_knobs(0.3), RT.video_knobs(1.0)
    assert a["slim"] == a["eye"] == a["makeup"] == 0 and a["smooth"] < b["smooth"] <= 0.85
    assert b["pores"] >= 0.65                                    # texture kept even at full strength
    c = RT.video_knobs(1.0, "beauty")
    assert 0 < c["slim"] <= 0.06 and c["makeup"] > 0 and c["smooth"] == b["smooth"]


def test_layer_smooths_the_tracked_face_only(face):
    pts = synth_face()
    img = synth_image(pts=pts)
    face(pts)
    inst = dict(effect="portrait-retouch", params=dict(strength=1.0, mode="skin"), start=0.0, end=2.0)
    L = FX.make_layer(inst, img.shape[1], img.shape[0])
    assert L.camera                                              # drawn on the source frame, before reframing
    out = img.copy()
    for k in range(3):
        out = img.copy()
        L.draw(out, k / 30, 2.0)
    L.close()
    c = pts[F.CHEEK_APPLE_L].mean(0).astype(int)
    patch = (slice(c[1] - 12, c[1] + 12), slice(c[0] - 12, c[0] + 12))
    g = lambda a: cv2.cvtColor(np.ascontiguousarray(a[patch]), cv2.COLOR_BGR2GRAY).astype(float).std()
    assert g(out) < g(img) * 0.9                                  # smoother skin (texture lowered, not wiped)
    assert g(out) > g(img) * 0.2
    assert np.abs(out[:30, :60].astype(int) - img[:30, :60]).max() <= 1               # background untouched
    assert L.rt.faces == 3


def test_no_face_or_no_model_passes_through(monkeypatch):
    monkeypatch.setattr(F, "VideoFaceTracker", lambda fps, **k: (_ for _ in ()).throw(FileNotFoundError("no model")))
    rt = RT.VideoRetoucher(RT.video_knobs(0.5))
    img = synth_image()
    assert rt(img, 0.0) is img and "no model" in rt.missing


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_render_with_skin_smoothing(tmp_path, monkeypatch, face):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    words = [("大家", .4), ("好", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35), ("方法", .4)]
    x, truth, dur = H.synth_speech(words)
    w = tmp_path / "work"
    (w / "final").mkdir(parents=True)
    f = str(w / "final" / "clip.mp4")
    H.make_video(f, x, 48000, dur)
    (w / "REPORT.md").write_text("# clip\n")
    from vstudio.project import works
    works.adopt(str(w))
    monkeypatch.setattr(O, "TRANSCRIBE", lambda path, language=None: [{k: t[k] for k in ("w", "t", "te")} for t in truth])
    pts = synth_face(w=360, h=640, cx=180, cy=280, fw=200)
    face(pts)
    oid = "final/clip.mp4"
    r = O.edit(str(w), oid, dict(op="effect_add", effect="磨皮", start=0, params=dict(strength=1.0)))
    (e,) = r["state"]["effects"]
    assert (e["effect"], e["start"]) == ("portrait-retouch", 0.0) and e["end"] > dur - 0.3   # the whole clip
    with pytest.raises(O.OutputError) as ei:                     # one per clip: effect_update changes it
        O.edit(str(w), oid, dict(op="effect_add", effect="美颜", start=0))
    assert ei.value.info["code"] == "duplicate-effect"
    res = R.render(str(w), oid, quality="preview", targets=["primary"])
    (t,) = res["targets"]
    from vstudio import media as M
    assert abs(M.probe(t["file"])["duration"] - dur) < 0.25
    # the same frame of the original and of the render: changed on the face, not in the corner
    def frame(path, at=1.0):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", path, "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(640, 360, 3).astype(int)
    a, b = frame(f), frame(t["file"])
    c = pts[F.CHEEK_APPLE_L].mean(0).astype(int)
    cheek = (slice(c[1] - 10, c[1] + 10), slice(c[0] - 10, c[0] + 10))
    assert np.abs(a[cheek] - b[cheek]).mean() > 2.0              # smoothed where the face is
    assert np.abs(a[:40, :40] - b[:40, :40]).mean() < 2.5        # the corner: encoding noise only
    show = O.show(str(w), oid)
    assert any(x["effect"] == "portrait-retouch" and x["stage"] == "frame" for x in show["effects"])
    json.dumps(show, ensure_ascii=False, default=str)
