"""promo-recut tight_cut on the shared speech cleanup (vstudio.cleanup): --suggest = cleanup.analyze over the
KEEP spans, the cut = cleanup.apply per part (AUTO only unless cut.reply confirms), legacy cut.drop / cut.patch
translated to cleanup approvals or word-safe editor cuts, --verify = cleanup.verify.
Synthetic media only (tone bursts as "words", testsrc picture, a fake whisper transcript).

    python3 -m pytest tests/test_promo_cleanup.py -q
"""
import importlib
import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = ROOT / "workflows" / "promo-recut" / "scripts"
sys.path[:0] = [str(ROOT / "lib"), str(S)]

from vstudio import audio  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _standard_persona(tmp_path_factory):
    """Hermetic: a creator's persona.local.yaml (e.g. cleanup.profile: tight) must not change the defaults
    these tests assert. VSTUDIO_PERSONA is merged last, also in the scripts run as subprocesses."""
    from vstudio import config as _config
    p = tmp_path_factory.mktemp("persona") / "persona.yaml"
    p.write_text("cleanup:\n  profile: standard\n", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("VSTUDIO_PERSONA", str(p))
        _config.persona.cache_clear()                  # persona() is lru_cached
        yield
    _config.persona.cache_clear()


HAS_FF = bool(shutil.which("ffmpeg"))
pytestmark = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")

# (text, start, end): 嗯 = auto filler, isolated 那个 = confirm filler, 0.7 s pause inside the body, 很 = a plain word
WORDS = [("大家", 0.40, 0.75), ("好。", 0.80, 1.10), ("嗯", 1.50, 1.75), ("今天", 2.05, 2.40), ("讲", 2.45, 2.70),
         ("一个", 3.40, 3.75), ("那个", 4.05, 4.40), ("很", 4.65, 4.85), ("好的", 4.90, 5.25), ("问题。", 5.30, 5.75),
         ("谢谢", 6.60, 7.00), ("大家。", 7.05, 7.45)]
DUR = 8.0


def _track(sr):
    t = np.arange(int(DUR * sr)) / sr
    x = 3e-4 * np.random.default_rng(2).standard_normal(len(t))
    for k, (_, a, b) in enumerate(WORDS):
        m = (t >= a) & (t < b)
        x[m] += 0.3 * np.sin(2 * np.pi * (240 + 37 * k) * t[m])
    return x


@pytest.fixture()
def proj(tmp_path):
    x = _track(48000)
    audio.write_wav(str(tmp_path / "talk.wav"), np.stack([x, x], 1).astype(np.float32), 48000)
    (tmp_path / "input").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30", "-i",
                    str(tmp_path / "talk.wav"), "-t", str(DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(tmp_path / "input" / "talk.mp4")], check=True)
    (tmp_path / "work").mkdir()
    words = [dict(word=w, start=round(a - 0.04, 3), end=round(b - 0.03, 3)) for w, a, b in WORDS]
    json.dump(dict(language="zh", text="", segments=[dict(start=0.36, end=7.42, text="", words=words)]),
              open(tmp_path / "work" / "audio.json", "w"), ensure_ascii=False)
    cfg = dict(talk="input/talk.mp4", language="zh", work_dir="work",
               cut=dict(body=[[0.3, 5.9]], outro=[[6.5, 7.6]], drop=[[4.6, 4.70]]))
    (tmp_path / "promo.config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _run(proj, *args, ok=True):
    r = subprocess.run([sys.executable, str(S / "tight_cut.py"), str(proj / "promo.config.json"), *args],
                       capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def _cfg(proj, **cut):
    c = json.loads((proj / "promo.config.json").read_text(encoding="utf-8"))
    c["cut"].update(cut)
    (proj / "promo.config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def test_suggest_cut_reply_and_legacy_drop(proj):
    r = _run(proj, "--suggest")
    assert "待确认" in r.stdout and (proj / "work" / "cleanup_review.md").exists()
    assert "editor cut" in r.stdout and "'很'" in r.stdout            # legacy drop of a plain word -> editor cut
    edl = json.load(open(proj / "work" / "cleanup.json", encoding="utf-8"))
    um = next(e for e in edl["edits"] if e["text"] == "嗯")
    nage = next(e for e in edl["edits"] if e["text"] == "那个")
    assert um["action"] == "auto" and nage["action"] == "confirm"
    assert any(e["kind"] == "pause" for e in edl["edits"])

    _run(proj)                                                          # AUTO + the legacy drop, no reply
    L = json.load(open(proj / "work" / "layout.json", encoding="utf-8"))
    said = [w["w"] for w in L["words"]["body"]]
    assert "嗯" not in said and "很" not in said and "那个" in said and "好的" in said
    assert [w["w"] for w in L["words"]["outro"]] == ["谢谢", "大家。"]
    side = json.load(open(proj / "work" / "body.cleanup.json", encoding="utf-8"))
    assert abs(side["duration"] - L["D"]["body"]) < 0.08
    for w in L["words"]["body"]:                                        # layout maps = raw -> cut file
        from vstudio.cut import TimeMap
        assert abs(TimeMap.from_list(L["maps"]["body"]).to_final(w["raw"], snap="fwd") - w["t"]) < 0.05
    d1 = L["D"]["body"]

    _cfg(proj, reply=f"确认 {nage['id']} / 保留 {um['id']}")             # the creator's answer
    _run(proj)
    L2 = json.load(open(proj / "work" / "layout.json", encoding="utf-8"))
    said = [w["w"] for w in L2["words"]["body"]]
    assert "那个" not in said and "嗯" in said and L2["D"]["body"] != d1

    tc = importlib.import_module("tight_cut")
    from common import Project
    prj = Project(str(proj / "promo.config.json"))
    ok = {p: [dict(w=w["w"], t=w["t"], te=w["te"]) for w in L2["words"][p]] for p in ("body", "outro")}
    assert tc.verify(prj, transcriber=lambda f: ok["body" if "body" in f else "outro"]) == 0
    lost = {p: [w for w in v if w["w"] != "问题。"] for p, v in ok.items()}
    assert tc.verify(prj, transcriber=lambda f: lost["body" if "body" in f else "outro"]) == 1

    # changing the KEEP spans renumbers the edits: with a reply by id in the config that is refused
    _cfg(proj, body=[[0.3, 4.5]])
    r = _run(proj, "--draft-subs", ok=False)
    assert r.returncode != 0 and "--suggest" in (r.stdout + r.stderr)


def test_legacy_patch_and_drop_translate_to_approvals(proj):
    tc = importlib.import_module("tight_cut")
    from common import Project
    _cfg(proj, drop=[[4.0, 4.37], [4.6, 4.70]], patch=[[1.46, 1.7]])
    prj = Project(str(proj / "promo.config.json"))
    edl = tc.get_edl(prj)
    from vstudio import cleanup
    en = cleanup.energy_of(tc.audio_wav(prj), edl["words"], edl["ranges"])
    ap, kp, allc, extra, notes = tc.translate(edl, prj, en)
    nage = next(e for e in edl["edits"] if e["text"] == "那个")
    assert nage["id"] in ap and not kp and not allc                    # drop covering 那个 -> approve its edit
    assert any(x[2] == "drop:很" for x in extra)                        # 很 has no edit -> word-safe editor cut
    c = next(x for x in extra if x[2] == "drop:很")
    assert 4.37 <= c[0] <= 4.65 and 4.83 <= c[1] <= 4.90               # ends in the 50 ms gap: 好的 (4.90) kept whole
    assert any(x[2] == "patch" for x in extra)                          # no merged-filler edit -> editor cut
