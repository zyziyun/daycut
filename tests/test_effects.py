"""Effect registry (vstudio.effects) and cross-engine transition bridge (vstudio.xfade).

    python3 -m pytest tests/test_effects.py -q
"""
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import effects, hf, xfade  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------- registry

@pytest.mark.parametrize("eid", sorted(effects.REGISTRY))
def test_entry_fields(eid):
    e = effects.get(eid)
    for f in effects.REQUIRED:
        assert f in e, f"{eid}: missing {f}"
    for f in ("id", "name", "what", "where", "when", "duration", "max_uses", "reuse"):
        assert isinstance(e[f], str) and e[f].strip(), f"{eid}: empty {f}"
    assert e["category"] in effects.CATEGORIES
    assert e["energy"] in effects.ENERGIES
    assert e["engines"] and set(e["engines"]) <= set(effects.ENGINES)
    assert set(e["entry"]) <= set(e["engines"]), f"{eid}: entry engines not in engines"
    assert any(e["entry"].values()), f"{eid}: no entry points"
    assert e["params"], f"{eid}: no params"
    for p in e["params"]:
        assert len(p) == 3 and p[0], f"{eid}: param must be (name, default, feel)"
    assert e["tested"] == "no" or (ROOT / e["tested"]).exists(), f"{eid}: tested file {e['tested']} missing"


@pytest.mark.parametrize("eid", sorted(effects.REGISTRY))
def test_entry_points_resolve(eid):
    for eng, eps in effects.get(eid)["entry"].items():
        for ep in eps:
            ok, detail = effects.check_entry(ep)
            assert ok, f"{eid} [{eng}]: {detail}"


def test_find_and_available_in():
    assert effects.get("punch-in")["id"] == "punch-in"
    with pytest.raises(KeyError):
        effects.get("nope")
    hfx = effects.available_in("hyperframes")
    assert hfx and all("hyperframes" in e["engines"] for e in hfx)
    assert {e["id"] for e in effects.find(category="transitions", engine="ffmpeg")} >= {"xfade-joins", "light-leak"}
    assert effects.find(text="light leak")
    assert all(e["energy"] == "high" for e in effects.find(energy="high"))
    with pytest.raises(ValueError):
        effects.available_in("blender")


def test_effects_md_block_is_generated_and_stable():
    txt = effects.EFFECTS_MD.read_text(encoding="utf-8")
    assert effects.BEGIN in txt and effects.END in txt
    block = txt.split(effects.BEGIN, 1)[1].split(effects.END, 1)[0]
    assert block.strip() == effects.as_markdown().strip(), "run: PYTHONPATH=lib python3 -m vstudio.effects --write-md"
    assert effects.as_markdown() == effects.as_markdown()
    assert "## Recipes" in txt.split(effects.END, 1)[1], "hand-written recipes must stay after the block"


def test_write_md_roundtrip(tmp_path):
    p = tmp_path / "E.md"
    p.write_text(f"intro\n{effects.BEGIN}\nSTALE-PLACEHOLDER\n{effects.END}\n## Recipes\n", encoding="utf-8")
    assert effects.write_md(p) is True
    assert effects.write_md(p) is False
    t = p.read_text(encoding="utf-8")
    assert t.startswith("intro\n") and t.endswith("## Recipes\n") and "STALE-PLACEHOLDER" not in t


# ---------------------------------------------------------------- bridge

def test_every_hf_transition_is_bridged():
    for t in hf.TRANSITIONS:
        s = xfade.spec(t)
        assert s["hf"]["type"] == t
        assert xfade.ffmpeg_transition(t, check=False)
        assert callable(s["pil"][0])
    cov = xfade.coverage()
    for n in xfade.NAMES:
        assert set(cov[n]) == set(xfade.ENGINES)
        assert all(v in ("exact", "near", "approx") for v in cov[n].values())
        assert xfade.hf_type(n) in hf.TRANSITIONS


def test_aliases_resolve():
    assert xfade.resolve("leak") == "light-leak"
    assert xfade.resolve("circleopen") == "iris"
    assert xfade.resolve("Whip_Pan") == "whip"
    with pytest.raises(KeyError):
        xfade.resolve("nope")


@pytest.mark.parametrize("name", xfade.NAMES)
def test_blend_endpoints(name):
    r = np.random.default_rng(1)
    a = (r.random((36, 64, 3)) * 255).astype(np.float32)
    b = (r.random((36, 64, 3)) * 255).astype(np.float32)
    np.testing.assert_array_equal(xfade.blend(name, a, b, 0.0), a)
    np.testing.assert_array_equal(xfade.blend(name, a, b, 1.0), b)
    for p in (0.25, 0.5, 0.75):
        f = xfade.blend(name, a, b, p)
        assert f.shape == a.shape and f.dtype == np.float32 and np.isfinite(f).all()
        assert f.min() >= -1e-3 and f.max() <= 255 + 1e-3
    if name != "cut":
        mid = xfade.blend(name, a, b, 0.5)
        assert not np.array_equal(mid, a) or not np.array_equal(mid, b)


def test_blend_unit_range_and_shape_check():
    a = np.zeros((20, 30, 3), np.float32)
    b = np.ones((20, 30, 3), np.float32)
    f = xfade.blend("light-leak", a, b, 0.5)
    assert f.max() <= 1.0 + 1e-6
    with pytest.raises(ValueError):
        xfade.blend("fade", a, b[:10], 0.5)


def test_ffmpeg_expr_strings():
    s = xfade.ffmpeg_expr("iris", 0.8, 3.0)
    assert s == "xfade=transition=circleopen:duration=0.8000:offset=3.0000"
    assert xfade.ffmpeg_transition("whip").startswith("custom:expr='")
    assert "st(" not in xfade.ffmpeg_transition("light-leak")        # registers race across slice threads
    assert xfade.ffmpeg_expr("cut", 0.5, 1.0, fps=25).endswith("duration=0.0400:offset=1.0000")


def test_hf_transitions_mix_native_and_bridge():
    out = xfade.hf_transitions([("blur", "w-a", "w-b", 5.0, 0.8), ("whip", "w-b", "w-c", 9.0, 0.32),
                                ("light-leak", "w-c", "w-d", 12.0, 0.7), ("ink", "w-d", "w-e", 15.0, 0.6)])
    assert set(out) == {"css", "html", "js"}
    js = out["js"]
    assert '"type": "blur"' in js or "blur" in js
    assert 'tl.fromTo("#w-c", { x: 1920' in js and "immediateRender: false" in js
    assert "#tx-leak-2" in out["css"] and "opacity: 0" in out["css"].split("#tx-leak-2")[1].split("}")[0]
    assert '<div id="tx-leak-2"></div>' in out["html"]


def _clip(path, src, size="160x90", dur=1.5):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s={size}:d={dur}:r=30",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)


def _frame(path, t, w=160, h=90):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w, 3).astype(np.float32)


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
@pytest.mark.parametrize("name", ["iris", "whip", "light-leak"])
def test_ffmpeg_render_through_xfade_assemble(tmp_path, name):
    from vstudio import cut, media
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _clip(a, "testsrc2")
    _clip(b, "smptebars")
    asm = cut.xfade_assemble([(0, 0.0, 1.5), (1, 0.0, 1.5)], xfade=0.5, size="160:90", audio=False,
                             transition=xfade.ffmpeg_transition(name))
    out = tmp_path / f"{name}.mp4"
    cut.render_assembly(asm, [str(a), str(b)], str(out), args=["-c:v", "libx264", "-preset", "ultrafast",
                                                               "-pix_fmt", "yuv420p"])
    assert abs(media.duration(str(out)) - asm.total) < 0.1
    off = asm.offsets[1]
    first, mid, last = _frame(out, 0.2), _frame(out, off + 0.25), _frame(out, asm.total - 0.2)
    # mid-transition differs from both ends; no slice-thread noise (frame stays mostly smooth)
    assert np.abs(mid - first).mean() > 3 and np.abs(mid - last).mean() > 3
    assert np.abs(np.diff(mid, axis=1)).mean() < 40


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_ffmpeg_expr_direct_graph(tmp_path):
    out = tmp_path / "x.mp4"
    g = ("[0:v]format=yuv420p[a];[1:v]format=yuv420p[b];[a][b]" + xfade.ffmpeg_expr("blocks", 0.6, 0.5) + "[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:d=1.5:r=30",
                    "-f", "lavfi", "-i", "smptebars=s=160x90:d=1.5:r=30", "-filter_complex", g, "-map", "[v]",
                    "-c:v", "libx264", "-preset", "ultrafast", str(out)], check=True)
    mid = _frame(out, 0.8)
    navy = np.array(xfade.BLOCK_COLOR, np.float32)
    assert (np.abs(mid - navy).max(axis=2) < 30).mean() > 0.5        # panels cover the frame mid-way
