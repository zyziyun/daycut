"""workflows/ai-video: prompt rendering, duration snapping, cost estimates, dry run + spend gate, mocked
providers (Kling MCP JSON-RPC, manual import), judge verdicts, EDL assembly, publish packages and the
per-post confirm gate. Synthetic data only; no network."""
import json
import os
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / "workflows" / "ai-video"
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(WF / "scripts"))

import assemble as AS  # noqa: E402
import generate as G  # noqa: E402
import judge as J  # noqa: E402
import package as PK  # noqa: E402
import plan as PL  # noqa: E402
import providers as PR  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def project(tmp_path, **over):
    import yaml
    cfg = yaml.safe_load((WF / "templates" / "project.yaml").read_text())
    cfg.update(over)
    p = tmp_path / "project.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return PL.load(str(p))


# ------------------------------------------------------------------------------------------- planning
def test_snap_duration_integer_and_discrete():
    assert PL.snap_duration(4.5, {"durations": (3, 10)}) == (5.0, None)
    assert PL.snap_duration(2.0, {"durations": (3, 10)}) == (3.0, None)
    d, w = PL.snap_duration(12.0, {"durations": (3, 10)})
    assert d == 10.0 and "split" in w
    assert PL.snap_duration(7.0, {"durations": [6, 10]}) == (10.0, None)
    assert PL.snap_duration(3.3, {}) == (3.3, None)


def test_units_group_shots_and_prompts_follow_rules(tmp_path):
    cfg = project(tmp_path)
    units = PL.compile_units(cfg)
    assert [u.id for u in units] == ["u01", "s03", "s04"]
    u01 = units[0]
    assert [s["id"] for s in u01.shots] == ["s01", "s02"] and u01.gen_dur == 5.0
    p = PL.render_prompt(cfg, u01)
    assert "\n" not in p                                   # newlines can submit web forms
    assert '"Morning coffee. Simple."' in p and "[0.0-2.5s]" in p and "[2.5-4.5s]" in p
    assert "No text" in p and "looks into the camera" in p and "pores" in p
    assert "image 1 is the scene master".lower() in p.lower()
    assert "A (the person in image 2" in p


def test_kling_elements_and_seedance_refs(tmp_path):
    cfg = project(tmp_path)
    cfg["characters"]["A"]["element"] = "el_123"
    job = PL.unit_job(cfg, PL.compile_units(cfg)[0])
    assert "<<<el_123>>>" in job.prompt and job.elements == [{"id": "el_123", "bindName": "A"}]
    assert job.refs == {"image_1": "refs/kitchen_master.jpg", "image_2": "refs/A_neutral.jpg"}
    sd = PL.load(str(WF / "examples" / "demo-skit-seedance" / "project.yaml"))
    j = PL.unit_job(sd, PL.compile_units(sd)[0])
    assert "@图片2" in j.prompt and "@图片3" in j.prompt and j.duration == 12.0


def test_cost_estimates_and_unknown(tmp_path):
    job = PR.Job(unit="x", duration=5, resolution="1080p")
    assert PR.estimate_cost(job, "kling-mcp") == 60.0          # observed: 1080p 5 s = 60 credits
    assert PR.estimate_cost(PR.Job(unit="x", kind="image", count=4), "kling-mcp") == 8.0
    assert PR.estimate_cost(PR.Job(unit="x", duration=12, resolution="480p"), "seedance") == 108.0
    assert PR.estimate_cost(PR.Job(unit="x", duration=6, resolution="768p"), "minimax") is None
    assert PR.estimate_cost(job, "kling-mcp", rates={"kling-mcp": {"video": {"1080p": 10}}}) == 50.0
    cfg = project(tmp_path)
    units, jobs, ests, total, warns = PL.build(cfg)
    assert ests == [60.0, 48.0, 48.0] and total == 156.0


def test_validate_flags_prompt_length_refs_and_mixed_scenes(tmp_path):
    cfg = project(tmp_path)
    cfg["shots"][1]["scene"] = "street"
    cfg["shots"][2]["action"] = "x " * 2000
    units, jobs, ests, total, warns = PL.build(cfg)
    text = "\n".join(warns)
    assert "mixes scenes" in text and "prompt" in text and "chars" in text
    from PIL import Image
    big = tmp_path / "big.jpg"
    Image.new("RGB", (3000, 4000), "gray").save(big)
    assert PL.check_ref_file(str(big)) and "prep-refs" in PL.check_ref_file(str(big))[0]
    out = G.prep_refs([str(big)], str(tmp_path / "up"))
    assert max(Image.open(out[0]).size) == 1024


# ------------------------------------------------------------------------------------------- spend gate
def test_check_spend_gate():
    with pytest.raises(G.SpendRefused, match="dry run"):
        G.check_spend(100, 500, yes=False)
    with pytest.raises(G.SpendRefused, match="budget"):
        G.check_spend(100, None, yes=True)
    with pytest.raises(G.SpendRefused, match="> budget"):
        G.check_spend(600, 500, yes=True)
    with pytest.raises(G.SpendRefused, match="unknown"):
        G.check_spend(None, 500, yes=True)
    with pytest.raises(G.SpendRefused, match="balance"):
        G.check_spend(100, 500, yes=True, balance=50)
    assert G.check_spend(100, 500, yes=True, balance=900) == 100
    assert G.check_spend(None, 500, yes=True, allow_unknown=True) == 500


class FakeProvider(PR.Provider):
    name = "kling-mcp"

    def __init__(self, fail_units=()):
        self.submitted, self.fail_units = [], set(fail_units)

    def balance(self):
        return 1000

    def submit(self, job):
        self.submitted.append(job.unit)
        return f"gid-{job.unit}"

    def poll(self, tid):
        u = tid[4:]
        if u in self.fail_units:
            return {"status": "failed", "urls": [], "raw": {"status": "FAILED"}}
        return {"status": "done", "urls": [f"https://example.invalid/{u}.mp4"], "raw": {}}

    def wait(self, tid, **kw):
        return self.poll(tid)

    def download(self, url, path, tries=4):
        pathlib.Path(path).write_bytes(b"fake")
        return path


def test_dry_run_never_submits_and_budget_refusal(tmp_path):
    cfg = project(tmp_path)
    fp = FakeProvider()
    with pytest.raises(G.SpendRefused):
        G.run(cfg, provider=fp, out=lambda *a: None)               # no --yes
    with pytest.raises(G.SpendRefused, match="> budget"):
        G.run(cfg, budget=100, yes=True, provider=fp, out=lambda *a: None)   # 156 > 100
    assert fp.submitted == []
    assert G.main(["plan", str(tmp_path / "project.yaml"), "--no-prompts"]) == 0
    assert G.main(["run", str(tmp_path / "project.yaml")]) == 2        # refused, nothing sent


def test_run_persists_and_never_resubmits_failures(tmp_path):
    cfg = project(tmp_path)
    fp = FakeProvider(fail_units={"s03"})
    st = G.run(cfg, only="u01,s03", budget=200, yes=True, provider=fp, out=lambda *a: None)
    assert fp.submitted == ["u01", "s03"]
    assert (tmp_path / "takes" / "u01_v1.mp4").exists()
    assert "s03" in st["failed"] and st["pending"] == {}
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["spent_estimate"] == 108.0 and saved["takes"]["u01"][0]["file"] == "u01_v1.mp4"
    G.collect(cfg, provider=fp, out=lambda *a: None)
    assert fp.submitted == ["u01", "s03"]                           # collect never submits


def test_manual_provider_refuses_run_and_imports(tmp_path):
    cfg = project(tmp_path, provider="manual:jimeng")
    with pytest.raises(G.SpendRefused, match="manual"):
        G.run(cfg, budget=999, yes=True, out=lambda *a: None)
    sheet = G.write_sheets(cfg, out=lambda *a: None)
    assert "Prompt (paste as ONE line" in pathlib.Path(sheet).read_text()
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "s03_take.mp4").write_bytes(b"x")
    (dl / "random.mp4").write_bytes(b"x")
    st = G.import_files(cfg, [str(dl / "s03_take.mp4"), str(dl / "random.mp4")], out=lambda *a: None)
    assert (tmp_path / "takes" / "s03_v1.mp4").exists() and list(st["takes"]) == ["s03"]


def test_kling_mcp_adapter_with_mock_transport():
    calls = []

    def transport(url, data, headers, method):
        body = json.loads(data) if data else {}
        calls.append((url, body, headers))
        if body.get("method") == "initialize":
            return b'{"jsonrpc":"2.0","id":1,"result":{}}', {"Mcp-Session-Id": "sess1"}
        if body.get("method") == "notifications/initialized":
            return b"", {}
        name = body["params"]["name"]
        if name == "image_to_video":
            res = {"generationId": "g1", "creditsConsumed": 60}
        elif name == "query_tasks":
            res = {"status": "COMPLETED", "works": [{"status": "COMPLETED", "url": "u-wm", "urlWithoutWatermark": "u-clean"}]}
        else:
            res = {}
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps(res)}]}}
        return ("event: message\ndata: " + json.dumps(payload) + "\n\n").encode(), {}

    k = PR.KlingMCP(token="t", transport=transport)
    job = PR.Job(unit="u1", model="kling-video-v3_0_omni", prompt="p", duration=5, refs={"image_1": "https://x/a.jpg"},
                 elements=[{"id": "e1", "bindName": "A"}])
    assert k.submit(job) == "g1"
    sent = calls[-1][1]["params"]
    assert sent["name"] == "image_to_video"
    args = {a["name"]: a["value"] for a in sent["arguments"]["arguments"]}
    assert args["duration"] == "5" and args["enable_audio"] == "true" and json.loads(args["elements"])[0]["id"] == "e1"
    assert sent["arguments"]["inputs"] == [{"name": "image_1", "inputType": "URL", "url": "https://x/a.jpg"}]
    assert calls[-1][2]["Mcp-Session-Id"] == "sess1" and calls[-1][2]["Authorization"] == "Bearer t"
    assert k.poll("g1") == {"status": "done", "urls": ["u-clean"], "raw": json.loads(json.dumps(
        {"status": "COMPLETED", "works": [{"status": "COMPLETED", "url": "u-wm", "urlWithoutWatermark": "u-clean"}]}))}


def test_retries_only_transport_errors_and_missing_key(monkeypatch):
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] < 3:
            raise PR.TransportError("503")
        return "ok"

    assert PR.with_retries(flaky, sleep=lambda s: None) == "ok" and n["i"] == 3

    def bad():
        raise PR.ProviderError("401")
    with pytest.raises(PR.ProviderError):
        PR.with_retries(bad, sleep=lambda s: None)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(PR.ProviderError, match="MINIMAX_API_KEY"):
        PR.MiniMax(transport=lambda *a: (b"{}", {})).submit(PR.Job(unit="x", prompt="p"))


# ------------------------------------------------------------------------------------------- judge
def test_judge_verdicts_and_line_match():
    card = J.blank_card("u1_v1")
    assert J.verdict(card)[0] == "redo"                         # unscored = not reviewed
    card["scores"] = {"A": 5, "B": 4, "C": 4}
    assert J.verdict(card)[0] == "pass"
    card["hard"]["generated_text"] = True
    assert J.verdict(card) == ("redo", ["hard: generated_text"])
    card["hard"]["generated_text"] = False
    card["scores"]["A"] = 3
    assert J.verdict(card)[0] == "redo"
    card["scores"]["A"] = 4
    for k in ("plastic_skin", "over_acting", "oversaturated"):
        card["soft"][k] = True
    assert J.verdict(card)[0] == "fix-in-post"
    assert J.line_match("Then pull me up!", "then pull me up") == 1.0
    assert J.line_match("Then pull me up!", "hey there") < 0.8
    assert len(J.sample_times(2.0, dense=True)) == 8 and len(J.sample_times(5.0)) == 12


# ------------------------------------------------------------------------------------------- assembly
def _clip(path, dur, size="480x854", audio=True, color="blue"):
    from vstudio import media
    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={dur}:r=24"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-shortest"]
    media.run(args + ["-pix_fmt", "yuv420p", str(path)])


@needs_ffmpeg
def test_assemble_edl_literal_and_no_audio_takes(tmp_path):
    from vstudio import media
    (tmp_path / "takes").mkdir()
    _clip(tmp_path / "takes" / "u01_v1.mp4", 3.0)
    _clip(tmp_path / "takes" / "u02_v1.mp4", 2.0, audio=False, color="red")
    import yaml
    tl = {"canvas": [360, 640], "fps": 24, "out": "master.mp4", "grade": {"saturation": 0.9, "grain": 2},
          "edl": [{"take": "u01_v1.mp4", "in": 0.5, "out": 2.0}, {"take": "u02_v1.mp4", "in": 0, "out": 1.5}]}
    (tmp_path / "timeline.yaml").write_text(yaml.safe_dump(tl))
    t = AS.load(str(tmp_path / "timeline.yaml"))
    assert AS.validate_edl(t) == []
    res = AS.assemble(t, asr=False, out=lambda *a: None)
    i = media.probe(res["master"])
    assert (i["w"], i["h"]) == (360, 640) and i["has_audio"] and abs(i["duration"] - 3.0) < 0.2
    t["edl"].append({"take": "u02_v1.mp4", "in": 1.0, "out": 9.0})
    t["edl"].append({"take": "nope.mp4"})
    errs = AS.validate_edl(t)
    assert any("beyond" in e for e in errs) and any("missing" in e for e in errs)


# ------------------------------------------------------------------------------------------- publishing
@pytest.fixture
def series(tmp_path):
    src = WF / "examples" / "demo-series" / "series.yaml"
    shutil.copy(src, tmp_path / "series.yaml")
    (tmp_path / "media").mkdir()
    for n in ("ep01-bilingual.mp4", "ep01-en.mp4"):
        (tmp_path / "media" / n).write_bytes(os.urandom(256))
    from PIL import Image
    Image.new("RGB", (1080, 1920), "navy").save(tmp_path / "media" / "ep01-9x16.png")
    return PK.load(str(tmp_path / "series.yaml"))


def test_build_post_copy_and_ai_labels(series):
    series["platforms"]["douyin"]["uploader"] = "manual"
    post = PK.build_post(series, 1, "douyin")
    assert post["ai_generated"] and post["ai_label"]["how"] == "manual"   # a person must tick it
    series["platforms"]["douyin"]["uploader"] = "sau"
    post = PK.build_post(series, 1, "douyin")
    assert post["ai_label"]["how"] == "auto"                              # sau --declaration
    assert post["body"].startswith("【智能家居翻车记·第1集】") and "#智能家居翻车记" in post["body"]
    yt = PK.build_post(series, 1, "youtube")
    assert yt["title"].endswith("| Smart Home Fails Ep.1") and yt["tags"][1] == "shorts"
    assert yt["ai_label"]["how"] == "auto"
    rd = PK.build_post(series, 1, "reddit_aivideo")
    assert rd["tags"] == [] and "#" not in rd["body"] and "Script by me" in rd["body"]
    log = {"0": {}, "1": {"douyin": {"url": "https://example.invalid/ep1"}}}
    series["episodes"].append(dict(series["episodes"][0], ep=2))
    assert "上一集：https://example.invalid/ep1" in PK.build_post(series, 2, "douyin", log)["body"]
    cmd, sched = PK.sau_command(PK.build_post(series, 1, "douyin"), "v.mp4", "c.jpg")
    assert "--declaration" in cmd and "内容由AI生成" in cmd and "--collection" in cmd


@needs_ffmpeg
def test_package_build_and_confirm_gate(series, tmp_path):
    made = PK.build(series, 1, out=lambda *a: None)
    assert set(made) == {"douyin", "youtube", "xiaohongshu", "reddit_aivideo"}
    pd = tmp_path / "out" / "ep01" / "xiaohongshu"
    for f in ("video.mp4", "cover.jpg", "post.json", "caption.txt", "CHECKLIST.md"):
        assert (pd / f).exists(), f
    from PIL import Image
    assert Image.open(pd / "cover.jpg").size == (1080, 1440)                # fitted, not cropped
    assert "AI label: manual" in (pd / "CHECKLIST.md").read_text()

    called = []

    def fake(post, video, cover, out=print):
        called.append(post["platform"])
        return {"status": "published", "url": "https://example.invalid/x"}
    ups = {"manual": fake, "sau": fake, "youtube": fake}
    r = PK.upload(series, 1, "xiaohongshu", confirm=None, uploaders=ups, out=lambda *a: None)
    assert r["status"] == "planned" and called == []                        # plan has no side effects
    assert "--confirm " + r["code"] in r["plan"] and "AI    : manual" in r["plan"]
    with pytest.raises(PK.UploadRefused, match="does not match"):
        PK.upload(series, 1, "xiaohongshu", confirm="deadbeef", uploaders=ups, out=lambda *a: None)
    assert called == []
    msgs = []
    PK.upload(series, 1, "xiaohongshu", confirm=r["code"], uploaders=ups, out=msgs.append)
    assert called == ["xiaohongshu"] and any("REMINDER" in m for m in msgs)
    log = json.loads((tmp_path / "publish_log.json").read_text())
    assert log["1"]["xiaohongshu"]["status"] == "published"
    PK.upload(series, 1, "xiaohongshu", confirm=r["code"], uploaders=ups, out=lambda *a: None)
    assert called == ["xiaohongshu"]                                        # never twice
    # changing the package invalidates the code
    r2 = PK.upload(series, 1, "douyin", confirm=None, uploaders=ups, out=lambda *a: None)
    post = json.loads((tmp_path / "out" / "ep01" / "douyin" / "post.json").read_text())
    post["title"] = "changed"
    (tmp_path / "out" / "ep01" / "douyin" / "post.json").write_text(json.dumps(post, ensure_ascii=False))
    with pytest.raises(PK.UploadRefused):
        PK.upload(series, 1, "douyin", confirm=r2["code"], uploaders=ups, out=lambda *a: None)
    # status gate
    series["episodes"][0]["status"] = "needs-fix"
    r3 = PK.upload(series, 1, "youtube", confirm=None, uploaders=ups, out=lambda *a: None)
    with pytest.raises(PK.UploadRefused, match="status"):
        PK.upload(series, 1, "youtube", confirm=r3["code"], uploaders=ups, out=lambda *a: None)
    assert PK.main(["upload", str(tmp_path / "series.yaml"), "1", "youtube"]) == 2   # no --confirm: plan only


@needs_ffmpeg
def test_youtube_shorts_guard_and_secrets_outside_repo(tmp_path, monkeypatch):
    _clip(tmp_path / "wide.mp4", 1.0, size="640x360")
    with pytest.raises(PK.UploadRefused, match="not a Short"):
        PK.youtube_shorts_guard(str(tmp_path / "wide.mp4"))
    _clip(tmp_path / "tall.mp4", 1.0, size="360x640")
    PK.youtube_shorts_guard(str(tmp_path / "tall.mp4"))
    monkeypatch.setenv("VSTUDIO_SECRETS", str(ROOT / "secrets"))
    with pytest.raises(PK.UploadRefused, match="inside the repository"):
        PK.secrets_dir()
