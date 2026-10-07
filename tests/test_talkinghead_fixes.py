"""talkinghead demo-round fixes (2026-10-05) on the shared speech cleanup (vstudio.cleanup): pass 1 analyses the raw
clip and applies only 气口, strict applies the creator's reply ("确认 N / 保留 N", AUTO only by default), idempotent
passes (segs.pass1.json root, stale apply refused), cleanup.verify on the body, word-safe range snap,
per-platform cover names, export cues with keep-outs + keyword markup.
Synthetic media only (tone bursts as "words", testsrc picture).

    python3 -m pytest tests/test_talkinghead_fixes.py -q
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
V = ROOT / "workflows" / "talkinghead" / "scripts" / "vertical"
sys.path[:0] = [str(ROOT / "lib"), str(V), str(V.parent)]

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
need_ff = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")

# "words": (text, start, end) tone bursts of the synthetic clip (a filler 嗯 = auto, an isolated 那个 = confirm,
# two long pauses = 气口). Transcript timing is whisper-like (starts 40 ms early, ends 30 ms early).
WORDS = [("大家", 0.30, 0.65), ("好。", 0.70, 1.00), ("嗯", 1.60, 1.85), ("今天", 2.15, 2.50), ("讲", 3.10, 3.35),
         ("那个", 3.60, 3.95), ("问题。", 4.20, 4.65), ("谢谢", 5.40, 5.80), ("大家。", 5.85, 6.20)]
DUR = 6.5
RANGES = [(0.25, 1.05), (1.55, 3.40), (3.55, 4.70), (5.35, 6.25)]


def _tone_track(sr, dur=DUR, words=WORDS):
    t = np.arange(int(dur * sr)) / sr
    x = 3e-4 * np.random.default_rng(1).standard_normal(len(t))
    for k, (_, a, b) in enumerate(words):
        m = (t >= a) & (t < b)
        x[m] += 0.3 * np.sin(2 * np.pi * (220 + 40 * k) * t[m])
    return x


def _asr(words=WORDS):
    return [dict(w=w, t=round(a - 0.04, 3), te=round(b - 0.03, 3)) for w, a, b in words]


# ------------------------------------------------------------------ word-aware snap (pure, vstudio.cleanup)
def test_snap_range_does_not_pull_in_neighbour_word():
    from vstudio import cleanup
    old = [(0.30, 0.70), (0.80, 1.20), (1.36, 1.80), (2.40, 2.80), (2.90, 3.30), (3.90, 4.40), (4.50, 4.90)]
    words = [dict(w=f"w{k}", t=a, te=b) for k, (a, b) in enumerate(old)]
    x = _tone_track(16000, 5.4, [(f"w{k}", a, b) for k, (a, b) in enumerate(old)])
    en = cleanup.energy_of((x, 16000), words)
    # keep word 2 (1.36-1.80) only; whisper start is early (swallows the pause) -> t0 = 1.22
    a, b = cleanup.snap_range(words, 1.22, 1.80, en)
    assert a >= 1.20, (a, b)                                    # never before the previous word's end
    assert 1.80 <= b <= 2.40, (a, b)                            # tail kept, next word not reached
    # range ending right before a close next word: the tail padding stops before its start
    w2 = [dict(w="a", t=0.3, te=0.7), dict(w="b", t=0.76, te=1.2)]
    tt = np.arange(32000) / 16000
    x2 = np.where((tt < 0.7) | (tt >= 0.76), 0.3 * np.sin(np.arange(32000) * 0.1), 0.0)
    assert cleanup.snap_range(w2, 0.3, 0.7, cleanup.energy_of((x2, 16000), w2))[1] <= 0.76 + 1e-9


# ------------------------------------------------------------------ cleanup-driven passes (ffmpeg)
def _run(script, *args, cwd, ok=True):
    r = subprocess.run([sys.executable, str(V / script), *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


@pytest.fixture()
def work(tmp_path):
    if not HAS_FF:
        pytest.skip("ffmpeg not installed")
    x48 = _tone_track(48000)
    audio.write_wav(str(tmp_path / "src.wav"), np.stack([x48, x48], 1).astype(np.float32), 48000)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=96x160:rate=30", "-i",
                    str(tmp_path / "src.wav"), "-t", str(DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(tmp_path / "sdr1.mp4")], check=True)
    audio.write_wav(str(tmp_path / "a1.wav"), _tone_track(16000).astype(np.float32), 16000)
    json.dump(dict(words=_asr()), open(tmp_path / "a1.json", "w"), ensure_ascii=False)
    (tmp_path / "edit_list.py").write_text(
        "E = [" + ", ".join(f"(1, [{r}], '{t}')" for r, t in zip(RANGES, "ABCD")) + "]\n")
    return tmp_path


def _edits(w):
    return json.load(open(w / "cleanup.c1.json", encoding="utf-8"))["edits"]


def _strict(w, reply="", extra=""):
    (w / "strict.py").write_text(f"REPLY = {reply!r}\nTEXT = {{}}\n{extra}", encoding="utf-8")
    return _run("strict_pass.py", "apply", "strict.py", "body_v.mp4", "body_a.wav", "body2_v.mp4", "body2_a.wav", cwd=w)


def _said(d):
    return [x["w"] for x in d["words"]]


@need_ff
def test_pass1_analyzes_raw_clip_and_applies_only_pauses(work):
    _run("cut_pass1.py", "edit_list.py", cwd=work)
    p1 = json.load(open(work / "segs.pass1.json"))
    assert p1["stage"] == "pass1" and [s["sid"] for s in p1["subs"]] == [0, 1, 2, 3]
    E = _edits(work)
    assert (work / "cleanup_review.md").exists() and "待确认" in (work / "cleanup_review.md").read_text(encoding="utf-8")
    um = [e for e in E if e["kind"] == "filler" and e["text"] == "嗯"]
    nage = [e for e in E if e["kind"] == "filler" and e["text"] == "那个"]
    assert um and um[0]["action"] == "auto"
    assert nage and nage[0]["action"] == "confirm"
    kinds = {e["id"]: e["kind"] for e in E}
    assert p1["applied"]["1"] and all(kinds[i] in ("pause", "breath", "lead", "tail") for i in p1["applied"]["1"])
    assert "嗯" in [w["w"] for w in p1["body_words"]]                 # word edits wait for the creator
    assert p1["total"] < sum(b - a for a, b in RANGES) - 0.2                # the 0.6 s pause was squeezed
    # strict review = the cleanup sheet + a draft with an empty REPLY and the CONFIRM rows listed
    r = _run("strict_pass.py", "transcribe", "body_a.wav", cwd=work)
    assert "待确认" in r.stdout
    draft = (work / "strict_draft.py").read_text(encoding="utf-8")
    assert 'REPLY = ""' in draft and f"{nage[0]['id']:>3}  filler" in draft


@need_ff
def test_strict_reply_idempotent_and_refuses_stale_bodies(work):
    _run("cut_pass1.py", "edit_list.py", cwd=work)
    E = _edits(work)
    um = next(e for e in E if e["text"] == "嗯")
    nage = next(e for e in E if e["text"] == "那个")
    pause = next(e for e in E if e["kind"] in ("pause", "breath") and e["action"] == "auto")
    _strict(work)                                                        # default: AUTO only
    st1 = json.load(open(work / "segs.strict.json"))
    assert "嗯" not in _said(st1) and "那个" in _said(st1)
    assert (work / "body2_a.cleanup.json").exists()
    _run("drop_pass.py", "1", "body2_v.mp4", "body2_a.wav", "body3_v.mp4", "body3_a.wav", cwd=work)
    dr = json.load(open(work / "segs.json"))
    assert dr["stage"] == "drop" and dr["parent"] == "strict" and 1 not in [s["sid"] for s in dr["subs"]]
    assert (work / "body3_a.cleanup.json").exists()
    # the creator confirms 那个: re-applied from pass 1 (never from the dropped segs.json)
    _strict(work, f"确认 {nage['id']}")
    st2 = json.load(open(work / "segs.json"))
    assert st2["stage"] == "strict" and [s["sid"] for s in st2["subs"]] == [0, 1, 2, 3]
    assert "那个" not in _said(st2) and 0 < st1["total"] - st2["total"] < 0.8
    assert not (work / "segs.drop.json").exists() and (work / "segs.drop.stale.json").exists()
    _strict(work, f"确认 {nage['id']}")                                  # same decisions -> same result
    assert json.load(open(work / "segs.json"))["subs"] == st2["subs"]
    # 保留 an auto word edit -> it stays
    _strict(work, f"保留 {um['id']}")
    st3 = json.load(open(work / "segs.json"))
    assert "嗯" in _said(st3) and st3["total"] > st1["total"]
    # a 气口 already squeezed in pass 1 cannot be kept here: refused with the fix
    (work / "strict.py").write_text(f"REPLY = '保留 {pause['id']}'\n", encoding="utf-8")
    r = _run("strict_pass.py", "apply", "strict.py", "body_v.mp4", "body_a.wav", "x_v.mp4", "x_a.wav", cwd=work, ok=False)
    assert r.returncode != 0 and "cut_pass1" in (r.stdout + r.stderr)
    # unknown ids are refused
    (work / "strict.py").write_text("REPLY = '确认 999'\n", encoding="utf-8")
    r = _run("strict_pass.py", "apply", "strict.py", "body_v.mp4", "body_a.wav", "x_v.mp4", "x_a.wav", cwd=work, ok=False)
    assert r.returncode != 0 and "unknown edit ids" in (r.stdout + r.stderr)
    # a strict apply on an already-dropped body is refused, not silently mis-cut
    _strict(work)
    _run("drop_pass.py", "1", "body2_v.mp4", "body2_a.wav", "body3_v.mp4", "body3_a.wav", cwd=work)
    (work / "strict.py").write_text("REPLY = ''\n", encoding="utf-8")
    r = _run("strict_pass.py", "apply", "strict.py", "body3_v.mp4", "body3_a.wav", "x_v.mp4", "x_a.wav", cwd=work, ok=False)
    assert r.returncode != 0 and "no parent cut matches" in (r.stdout + r.stderr)
    # drop again on the strict body: same list, same result; a dropped body as input is refused
    d2 = json.load(open(work / "segs.drop.json"))
    _run("drop_pass.py", "1", "body2_v.mp4", "body2_a.wav", "body3_v.mp4", "body3_a.wav", cwd=work)
    assert json.load(open(work / "segs.drop.json"))["subs"] == d2["subs"]
    r = _run("drop_pass.py", "2", "body3_v.mp4", "body3_a.wav", "y_v.mp4", "y_a.wav", cwd=work, ok=False)
    assert r.returncode != 0


@need_ff
def test_strict_verify_and_legacy_del(work):
    _run("cut_pass1.py", "edit_list.py", cwd=work)
    _strict(work)
    side = json.load(open(work / "body2_a.cleanup.json", encoding="utf-8"))
    assert [w["w"] for w in side["expected"]] == _said(json.load(open(work / "segs.strict.json")))
    json.dump(side["words"], open(work / "got.json", "w"), ensure_ascii=False)
    r = _run("strict_pass.py", "verify", "strict.py", "body2_a.wav", "--transcript", "got.json", cwd=work)
    assert "OK" in r.stdout
    lost = [w for w in side["words"] if w["w"] != "问题。"]
    json.dump(lost, open(work / "got.json", "w"), ensure_ascii=False)
    r = _run("strict_pass.py", "verify", "strict.py", "body2_a.wav", "--transcript", "got.json", cwd=work, ok=False)
    assert r.returncode == 1 and "问题" in r.stdout
    # legacy strict.py: DEL = {bw.json index} on the pass-1 body is still cut
    p1 = json.load(open(work / "segs.pass1.json"))
    st1 = json.load(open(work / "segs.strict.json"))
    w = next(x for x in p1["body_words"] if x["w"] == "今天")
    json.dump([dict(w=w["w"], b0=w["b0"], b1=w["b1"])], open(work / "bw.json", "w"), ensure_ascii=False)
    _strict(work, "", "DEL = {0}\n")
    st = json.load(open(work / "segs.strict.json"))
    assert "今天" not in _said(st) and st["total"] < st1["total"]


# ------------------------------------------------------------------ compose: cues.json with keep-outs + markup
@pytest.fixture()
def comp(tmp_path):
    if not HAS_FF:
        pytest.skip("ffmpeg not installed")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:size=1080x1920:rate=30", "-t", "4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(tmp_path / "body.mp4")], check=True)
    x = 0.2 * np.sin(np.arange(4 * 48000) * 0.05)
    audio.write_wav(str(tmp_path / "body_a.wav"), np.stack([x, x], 1).astype(np.float32), 48000)
    subs = [dict(sid=i, text=t, start=i * 1.0, end=(i + 1) * 1.0) for i, t in enumerate(["第一句讲关键词", "第二句", "第三句", "第四句收尾"])]
    json.dump(dict(subs=subs, total=4.0, stage="pass1"), open(tmp_path / "segs.json", "w"), ensure_ascii=False)
    ft = np.array([[t, 540, 860, 480, 300, 600, 780, 1190] for t in np.arange(0, 4, 0.2)], float)
    np.save(tmp_path / "face.npy", ft)
    (tmp_path / "config.py").write_text('''from anchors import S, E
BODY = "body.mp4"; AUDIO = "body_a.wav"; FACE = "face.npy"; OUT = "out.mp4"
HOOK_SPEED = 1.3; BODY_SPEED = 1.1; XF = 0.3
KEYWORDS = ["关键词"]
STYLE = dict(pops=True, stamps=True, panels=True, sfx=False)
HOOK_TITLE = ["标题一", "标题二"]
HOOKS = [[(1.0, 1.9)]]
CHAPTERS = [(0, S(2), "开场"), (S(2), E(3), "结论")]
POPS = [(S(1, .2), "重点", "Y", 540, 1320, 170, 0.6)]
STAMPS = [(S(0, .2), E(0), "第一", 420, 900, -6), (S(0, .4), E(0), "第二", 440, 990, 5)]
PANELS = [(S(2), E(3), "要点", [(S(2, .2), "第一点"), (S(3, .2), "第二点")])]
COVER = dict(SRC="body.mp4", T=1.0, OUT="cover.jpg", TITLE=["封面", "关键词"], STICKY=None, TAG=None)
''')
    return tmp_path


@need_ff
def test_compose_cues_carry_keepouts_and_keyword_markup(comp):
    r = _run("compose.py", "config.py", "cues", cwd=comp)
    assert "moved" in r.stdout                                   # the stamp stack on the face was moved off it
    d = json.load(open(comp / "out.cues.json"))
    assert d["size"] == [1080, 1920] and d["cues"]
    assert any("【关键词】" in c["text"] for c in d["cues"])
    kinds = {k["kind"] for k in d["keepouts"]}
    assert {"panel", "stamp", "pop", "hook_title"} <= kinds
    core = (300 + 0.08 * 480, 600 + 0.18 * 590, 780 - 0.08 * 480, 1190)
    for k in d["keepouts"]:
        x, y, w, h = k["box"]
        assert k["t1"] > k["t0"] and w > 0 and h > 0
        if k["kind"] == "stamp":
            assert y >= core[3] or x + w <= core[0] or x >= core[2], k
    # the panel is not shown in the hook, so its windows are all after the body starts
    hook_end = max(k["t1"] for k in d["keepouts"] if k["kind"] == "hook_title")
    assert all(k["t0"] >= hook_end - 0.5 for k in d["keepouts"] if k["kind"] == "panel")


@need_ff
def test_compose_clean_only_skips_the_captioned_render(comp):
    """vstudio.batch only uses the caption-free master + cues: --clean-only renders that once, not twice."""
    _run("compose.py", "config.py", "all", "--clean-only", cwd=comp)
    assert (comp / "out.clean.mp4").exists() and (comp / "out.cues.json").exists()
    assert not (comp / "out.mp4").exists()


@need_ff
def test_compose_wraps_an_overlong_sentence_into_caption_chunks(comp):
    """Batch runs have no hand-placed '|': a sentence longer than one caption line is split into balanced chunks."""
    segs = json.load(open(comp / "segs.json"))
    segs["subs"][1]["text"] = "只要是L5也就是比entry level要稍微高一个档进来的人都很不适应"
    json.dump(segs, open(comp / "segs.json", "w"), ensure_ascii=False)
    _run("compose.py", "config.py", "cues", cwd=comp)
    from vstudio import subs as S
    cues = json.load(open(comp / "out.cues.json"))["cues"]
    texts = [c["text"].replace("【", "").replace("】", "") for c in cues]
    assert all(S.text_width(t) <= 14 for t in texts), texts
    assert any(t.endswith("entry") for t in texts) and any(t.startswith("level") for t in texts)   # words whole


@need_ff
def test_cover_platform_names_do_not_overwrite(comp):
    _run("cover.py", "config.py", cwd=comp)
    assert (comp / "cover.jpg").exists()
    m0 = (comp / "cover.jpg").stat().st_mtime_ns
    _run("cover.py", "config.py", "--platform", "douyin", cwd=comp)
    assert (comp / "cover.jpg").stat().st_mtime_ns == m0           # the 小红书 cover is untouched
    from PIL import Image
    assert Image.open(comp / "cover.douyin-vertical.jpg").size == (1080, 1920)
    assert Image.open(comp / "cover.jpg").size == (1080, 1920)     # 9:16 video (xiaohongshu:full) -> 9:16 cover
