"""vstudio.batch recipe longform-split: the longform-to-short split layout per batch job, on a synthetic
screen-share (a white "page" with text lines + a magenta "participant tile" column at x >= 480).

Privacy: with privacy.exclude on the tile column no magenta pixel may reach any output (exports, covers, preview
sheet), even when screen.region is (wrongly) the whole frame; pad-blur is refused while an exclude is set."""
import json
import os
import shutil
import subprocess

import numpy as np
import pytest
import yaml
from PIL import Image

import _batch_helpers as H
from vstudio.batch import estimate as EST
from vstudio.batch import lfsplit as LS
from vstudio.batch import review
from vstudio.batch.package import package
from vstudio.batch.plan import plan_batch
from vstudio.batch.recipes import Ctx
from vstudio.batch.run import load_recipe, resolve_limits, run_batch
from vstudio.batch.store import Store

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

WORDS = [("大家", .4), ("好", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("检索", .4), ("增强", .4), ("生成", .4),
         ("一条", .35), ("写", .3), ("一条", .35), ("读", .3), ("这个", .3), ("切块", .4), ("很", .25), ("重要", .4),
         ("最后", .4), ("拼", .3), ("提示词", .5), ("交给", .4), ("模型", .4)]
SW, SH, TILE_X = 640, 360, 480


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))


def make_share(path, x, sr, dur):
    """Fake meeting recording: dark canvas, white page (x 20..460) with dark text lines that change over time
    (typing), and a magenta participant tile column x >= 480 with a moving 'face' box."""
    wav = path + ".wav"
    H.audio.write_wav(wav, np.stack([x, x], 1), sr)
    vf = ["drawbox=x=20:y=40:w=440:h=290:color=white:t=fill"]
    for k in range(14):
        y = 70 + k * 18
        w = 380 - (k * 37) % 160
        vf.append(f"drawbox=x=40:y={y}:w={w}:h=7:color=0x202020:t=fill:enable='gte(t,{k * 0.5:.2f})'")
    vf.append(f"drawbox=x={TILE_X}:y=0:w={SW - TILE_X}:h={SH}:color=0xFF00FF:t=fill")
    vf.append(f"drawbox=x='{TILE_X + 40}+20*sin(t)':y=120:w=60:h=60:color=0xFF40FF:t=fill")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x141414:s={SW}x{SH}:r=24",
                    "-i", wav, "-t", f"{dur:.3f}", "-vf", ",".join(vf), "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", path], check=True)
    os.remove(wav)
    return path


@pytest.fixture(scope="module")
def share(tmp_path_factory):
    d = tmp_path_factory.mktemp("share")
    x, truth, dur = H.synth_speech(WORDS)
    src = make_share(str(d / "lecture.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    return dict(dir=d, src=src, truth=str(tp), dur=dur, words=truth)


def magenta_px(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    return int(((a[..., 0] > 170) & (a[..., 2] > 170) & (a[..., 1] < 110)).sum())


def video_frames(path, n=6):
    from vstudio import media
    d = media.duration(path)
    out = []
    for k in range(n):
        png = path + f".f{k}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{d * (k + 0.5) / n:.3f}", "-i", path,
                        "-frames:v", "1", png], check=True)
        out.append(Image.open(png).convert("RGB"))
        os.remove(png)
    return out


def _seg_yaml(tmp, share, **kw):
    w = share["words"]
    rows = [dict(id="ep01", start=w[0]["t"], end=w[15]["te"] + 0.1, title="RAG就两条线：一条写一条读", chapter="RAG全景",
                 hook=dict(text="一条写，一条读，这就是RAG的两条线", start=w[8]["t"], end=w[11]["te"]),
                 cuts=[[w[12]["t"] - 0.02, w[12]["te"] + 0.02, "repeat"]],
                 notes=["写：parse → chunk → embedding", "读：检索 → rerank → 生成"], tags=["RAG", "LLM"],
                 why="开篇", risk="ASR 需修", source_speech_s=5.0, est_output_s=4.0),
            dict(id="ep02", start=w[12]["t"], end=w[20]["te"] + 0.1, title="切块很重要", chapter="切块",
                 hook=dict(start=w[13]["t"], end=w[15]["te"]), cuts=[], notes=["切块决定上限"], tags=["chunking"],
                 prior="already rendered")]
    seg = dict(source=share["src"], series="RAG 面试细节", speed=1.2, segments=rows)
    seg.update(kw)
    p = tmp / "segments.yaml"
    p.write_text(yaml.safe_dump(seg, allow_unicode=True, sort_keys=False))
    return str(p)


def _spec(tmp, share, segs, **kw):
    spec = dict(name="split", recipe="longform-split", segments=os.path.basename(segs), plugins=["_batch_helpers"],
                asr=dict(transcriber="_batch_helpers:fake_transcriber", language="zh"),
                privacy=dict(exclude=["x >= 480"]),
                screen=dict(region=[0, 0, SW, SH], max_scale=3.0),        # deliberately the WHOLE frame
                vertical=dict(master_preset="ultrafast"),
                defaults=dict(platforms=["xiaohongshu:vertical", "douyin"], preset="ultrafast"),
                qc=dict(sample_pct=0), budget=dict(max_hours=2))
    spec.update(kw)
    p = tmp / "batch.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False))
    return str(p)


# --------------------------------------------------------------------------- units
def test_privacy_rects_and_clip():
    assert LS.resolve_rects(["x >= 960", [None, 600, None, None], {"x0": 10, "y1": 50}], 1280, 720) == \
        [[960, 0, 1280, 720], [0, 600, 1280, 720], [10, 0, 1280, 50]]
    with pytest.raises(ValueError):
        LS.resolve_rects(["left half"], 1280, 720)
    assert LS.clip_region([0, 90, 1280, 630], [[960, 0, 1280, 720]]) == ([0, 90, 960, 630], [])
    assert LS.clip_region([0, 163, 958, 615], [[960, 0, 1280, 720]]) == ([0, 163, 958, 615], [])
    assert LS.clip_region([100, 0, 500, 400], [[0, 0, 200, 400]])[0] == [200, 0, 500, 400]
    assert LS.clip_region([0, 0, 600, 400], [[0, 300, 600, 400]])[0] == [0, 0, 600, 300]
    assert LS.clip_region([0, 0, 600, 400], [[0, 0, 600, 400]])[0] is None
    reg, partial = LS.clip_region([0, 0, 600, 400], [[500, 10, 560, 60]])       # a name tag: paint-out only
    assert reg == [0, 0, 600, 400] and partial == [[500, 10, 560, 60]]
    assert LS._hook_lines(dict(lines=["一条写，一条读，这就是RAG的两条线"])) == ["一条写，一条读", "这就是RAG的两条线"]
    assert LS._title_parts("RAG就两条线：一条写一条读") == ("RAG就两条线", "一条写一条读")


def test_title_parts_split_on_word_boundaries():
    assert LS._title_parts("Every index makes writes slower") == ("Every index makes", "writes slower")
    assert LS._title_parts("Two rules for storing passwords") == ("Two rules for", "storing passwords")
    assert LS._title_parts("向量数据库的两条主线") == ("向量数据库", "的两条主线")
    assert LS._title_parts("一行代码搞定Postgres全文搜索") == ("一行代码搞定", "Postgres全文搜索")
    assert LS._title_parts("Supercalifragilistic") == ("Supercalifragilistic", "")


def test_segments_yaml_adapter_plan_and_estimate(tmp_path, share):
    segs = _seg_yaml(tmp_path, share)
    r = plan_batch(_spec(tmp_path, share, segs, inputs={}), echo=False)    # source from the segments header
    assert r["jobs"] == ["ep01", "ep02"]
    st = Store(r["batch_dir"])
    p = st.job("ep01")["params"]
    assert p["source"] == share["src"] and p["speed"] == 1.2 and p["series"] == "RAG 面试细节"
    assert p["hook"]["lines"] == ["一条写，一条读，这就是RAG的两条线"] and p["hook"]["src"][0] == share["words"][8]["t"]
    assert p["layout"] == "split" and p["_exclude"] == [[480, 0, SW, SH]] and p["_series_no"] == [1, 2]
    assert len(p["cuts"]) == 1 and p["cuts"][0][2] == "repeat" and p["notes"][0].startswith("写")
    assert p["why"] == "开篇" and st.job("ep02")["params"]["prior"] == "already rendered"
    assert st.job("ep02")["params"]["hook"]["lines"] == []
    spec = st.spec
    est = EST.estimate(st, load_recipe(spec), spec, resolve_limits(spec))
    st.close()
    assert est["jobs"] == 2 and est["budget"]["ok"]
    assert est["stages"]["geometry"]["n"] == 1 and est["stages"]["asr"]["n"] == 1      # shared: once per source
    assert est["stages"]["export"]["units"] > est["stages"]["compose"]["units"] * 2
    cfg = LS.lfc_config(p, spec, dict(share=[0, 0, 480, 360], default_crop=[480, 360, 0, 0]), "out")
    assert cfg["vertical"]["exclude"] == [[480, 0, SW, SH]] and cfg["render"]["audio_only"] is True
    assert cfg["episodes"]["items"][0]["hook"]["lines"] == ["一条写，一条读", "这就是RAG的两条线"]
    assert cfg["episodes"]["items"][0]["eyebrow"] == "RAG 面试细节 · 1/2" and cfg["cards"]["number"] == [1, 2]
    assert cfg["panels"][0]["lines"] == p["notes"] and cfg["targets"] == ["xiaohongshu:vertical", "douyin"]


def test_pad_blur_refused_with_privacy_exclude(tmp_path, share):
    segs = _seg_yaml(tmp_path, share)
    with pytest.raises(LS.PrivacyError, match="pad-blur"):        # the generic reframe recipe
        plan_batch(_spec(tmp_path, share, segs, recipe="longform-slices"), echo=False)
    with pytest.raises(LS.PrivacyError, match="pad-blur"):        # the split recipe's own pad-blur mode
        plan_batch(_spec(tmp_path, share, segs, vertical=dict(mode="pad-blur")), echo=False)
    with pytest.raises(LS.PrivacyError, match="speaker.region"):
        plan_batch(_spec(tmp_path, share, segs, vertical=dict(speaker=dict(region=[500, 0, 640, 200]))), echo=False)
    with pytest.raises(ValueError, match="not a vertical target"):
        plan_batch(_spec(tmp_path, share, segs, defaults=dict(platforms=["youtube"])), echo=False)
    # without an exclude pad-blur is allowed (no privacy region to protect)
    r = plan_batch(_spec(tmp_path, share, segs, privacy={}, vertical=dict(mode="pad-blur")), echo=False)
    assert r["jobs"] == ["ep01", "ep02"]


def test_geometry_stage_detects_page_and_clips(tmp_path, share):
    """The workflow's geometry step finds the white page; a whole-frame screen.region is cut at the exclude."""
    job = dict(id="g", params=dict(source=share["src"], _exclude=[[TILE_X, 0, SW, SH]]))
    spec = dict(screen=dict(geometry=dict(step=2)))
    d = tmp_path / "geo"
    d.mkdir()
    out = LS.run_geometry(Ctx(job, spec, str(d), {}, str(tmp_path)))
    x0, y0, x1, y1 = out["share"]
    assert 15 <= x0 <= 25 and x1 <= 462 and y0 >= 40 and y1 <= 332
    assert out["frame"] and os.path.exists(out["frame"]) and not os.path.exists(d / "work" / "geo")
    d2 = tmp_path / "geo2"
    d2.mkdir()
    out2 = LS.run_geometry(Ctx(job, dict(screen=dict(region=[0, 0, SW, SH])), str(d2), {}, str(tmp_path)))
    assert out2["share"] == [0, 0, TILE_X, SH]


# --------------------------------------------------------------------------- end to end
def test_longform_split_end_to_end_privacy(tmp_path, share, monkeypatch):
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", share["truth"])
    assert magenta_px(video_frames(share["src"], 1)[0]) > 10000            # the tile IS in the source
    segs = _seg_yaml(tmp_path, share)
    r = plan_batch(_spec(tmp_path, share, segs), echo=False)
    bdir = r["batch_dir"]
    res = run_batch(bdir, echo=False)
    assert res["exit_code"] == 0, res
    assert sum(1 for _, s in res["ran"] if s == "asr") == 1 and sum(1 for _, s in res["ran"] if s == "geometry") == 1
    st = Store(bdir)
    for j in st.jobs():
        assert j["state"] == "done", (j["id"], j["qc_reasons"])
        assert j["qc"] == "green", (j["id"], j["qc_reasons"])
    ex = st.stage("ep01", "export")["out"]
    comp = st.stage("ep01", "compose")["out"]
    cl = st.stage("ep01", "cleanup")["out"]
    qcr = st.stage("ep01", "qc")["out"]
    pv = st.stage("ep01", "preview")["out"]
    st.close()
    # the workflow ran: split layout, title band, hook first, chapter card, cut removed, captions
    tl = json.load(open(comp["timeline"], encoding="utf-8"))
    assert tl[0].get("hook") and tl[1]["kind"] == "card" and tl[1]["title"] == "RAG全景"
    cut = share["words"][12]
    body = [it for it in tl if it["kind"] == "clip" and not it.get("hook")]
    assert not any(it["t0"] < (cut["t"] + cut["te"]) / 2 < it["t1"] for it in body)       # the row's cut is gone
    assert comp["n_cues"] >= 2 and comp["hook_dur"] > 1.0 and cl["cuts"]
    assert {(e["platform"], e["orientation"]) for e in ex["exports"]} == {("xiaohongshu", "vertical"),
                                                                           ("douyin", "vertical")}
    assert ex["privacy"]["overlap_frames"] == 0 and ex["privacy"]["modes"] == ["split"]
    assert any(c["name"] == "privacy-overlap" and c["ok"] for c in qcr["checks"])
    for pl in ex["privacy"]["plans"].values():
        assert pl["band"] == "title" and pl["exclude"] == [[TILE_X, 0, SW, SH]]
    # NO pixel of the participant tile anywhere: exports (several frames each), covers, preview sheet
    for e in ex["exports"]:
        from vstudio import media
        info = media.probe(e["file"])
        assert (info["display_w"], info["display_h"]) in ((1080, 1440), (1080, 1920))
        for k, fr in enumerate(video_frames(e["file"], 8)):
            assert magenta_px(fr) == 0, (e["file"], k)
        assert e["cover"] and magenta_px(Image.open(e["cover"])) == 0
        assert e["post"] and "RAG就两条线" in open(e["post"], encoding="utf-8").read()
    assert magenta_px(Image.open(pv["sheet"])) == 0
    # covers carry the series eyebrow + the cover copy; the split layout put text on screen (not a blur)
    man = json.load(open(ex["manifest"], encoding="utf-8"))
    assert all(px is None or px > 10 for p_ in man["plans"].values() for px in p_["text_px"])
    assert sorted(os.listdir(share["dir"])) == ["lecture.mp4", "truth.json"]            # source untouched
    # a title change re-runs export (+ qc / preview) only; the shared ASR / geometry and the cut are reused
    data = yaml.safe_load(open(segs, encoding="utf-8"))
    data["segments"][1]["title"] = "切块决定RAG上限"
    open(segs, "w", encoding="utf-8").write(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    plan_batch(os.path.join(os.path.dirname(segs), "batch.yaml"), echo=False)
    res2 = run_batch(bdir, echo=False)
    assert res2["exit_code"] == 0
    assert {s for _, s in res2["ran"]} <= {"export", "qc", "preview"} and all(j == "ep02" for j, _ in res2["ran"])
    # review + package work on the split exports
    review.generate(bdir)
    review.apply_decisions(bdir, {"decisions": {"ep01": {"decision": "approve"}, "ep02": {"decision": "approve"}}})
    pk = package(bdir, per_day=1, start="2026-10-10")
    assert pk["items"] == 4
    assert os.path.exists(os.path.join(pk["dir"], "douyin-vertical", "001_ep01", "video.mp4"))
