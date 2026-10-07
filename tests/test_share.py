"""Share for review (vstudio.project.share): the static review page (folder layout, review.json schema, no local
paths, deterministic bytes, quality presets, footer toggle), privacy warnings from mask metadata, feedback codes
(code / JSON / email body / damaged), import -> feedback items (change pinned in the clip chat, approve -> ready,
re-import adds nothing) and the CLI JSON contract. Synthetic media only, no network."""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

from vstudio.project import outputs as O
from vstudio.project import share as SH

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("VSTUDIO_H264_ENCODER", raising=False)


def _clip(path, size="360x480", dur=1.5, freq=440):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("share-media")
    _clip(d / "A_hook.mp4", "720x960")
    _clip(d / "B_story.mp4", "1080x1920", freq=660)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "A_hook.mp4"), "-frames:v", "1",
                    str(d / "A_hook_cover.jpg")], check=True)
    return d


def _work(tmp_path, media):
    w = tmp_path / "work"
    (w / "final").mkdir(parents=True)
    for n in ("A_hook.mp4", "B_story.mp4", "A_hook_cover.jpg"):
        shutil.copy(media / n, w / "final" / n)
    (w / "final" / "A_hook.post.md").write_text("# Three habits\n\nBody of the caption\n\n#habits", encoding="utf-8")
    (w / "REPORT.md").write_text("# Week 12\n", encoding="utf-8")
    from vstudio.project import works
    works.adopt(str(w))
    return str(w)


def _files(d):
    out = {}
    for dp, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def _code(share, clips, reviewer="Mia"):
    short = dict(k="rf", v=1, s=share, n=reviewer, t="2026-10-07T10:00:00Z",
                 c=[[cid, "a" if d == "approve" else "c", com] for cid, d, com in clips])
    raw = json.dumps(short, ensure_ascii=False).encode()
    return "RFB1." + base64.urlsafe_b64encode(raw).decode().rstrip("=")


# --------------------------------------------------------------------------- the page
def test_page_folder_schema_no_paths_and_deterministic(tmp_path, media):
    w = _work(tmp_path, media)
    clips = SH.collect_clips(w)
    assert [c["id"] for c in clips] == ["A_hook", "B_story"]
    assert clips[0]["cover"] and "Three habits" in clips[0]["caption"] and clips[1]["caption"] is None
    r = SH.share(w, quality="small", title="Week 12", owner_name="Ziyun", expiry_note="Reply by Friday")
    d = r["dir"]
    assert d.startswith(os.path.join(w, "review-links"))
    for rel in ("index.html", "review.json", "README.txt"):
        assert os.path.isfile(os.path.join(d, rel))
    data = json.load(open(r["json"], encoding="utf-8"))
    assert data["kind"] == "reelfold-review" and data["version"] == 1 and data["share"] == r["share"]
    assert data["footer"] is True and data["footer_url"] == "https://reelfold.com"
    assert data["feedback"] == dict(kind=SH.FEEDBACK_KIND, version=1, code_prefix="RFB1.", endpoint=None)
    assert data["expiry_note"] == "Reply by Friday" and data["owner"] == "Ziyun"
    assert set(data["clips"][0]) == {"id", "title", "caption", "caption_file", "poster", "versions"}
    for c in data["clips"]:
        assert os.path.isfile(os.path.join(d, c["poster"]))
        for v in c["versions"]:
            assert set(v) == {"file", "platform", "label", "w", "h", "duration", "bytes"}
            assert os.path.isfile(os.path.join(d, v["file"])) and v["bytes"] > 0
            assert min(v["w"], v["h"]) <= 540
    assert data["clips"][0]["caption_file"] and data["clips"][1]["caption_file"] is None
    assert data["clips"][1]["versions"][0]["label"].startswith("9:16")
    html = open(r["index"], encoding="utf-8").read()
    for blob in (html, json.dumps(data)):
        assert str(tmp_path) not in blob and "/Users/" not in blob      # nothing names a local path
    assert "<script src" not in html and "http://" not in html           # no external scripts / tracking
    assert "connect-src 'none'" in html and '"share":"%s"' % r["share"] in html
    # the zip holds the same folder
    with zipfile.ZipFile(r["zip"]) as z:
        names = z.namelist()
    root = os.path.basename(d)
    assert f"{root}/index.html" in names and all(n.startswith(root + "/") for n in names)
    # deterministic: same clips + options -> same id, same bytes (zip included)
    first, zbytes = _files(d), open(r["zip"], "rb").read()
    r2 = SH.share(w, quality="small", title="Week 12", owner_name="Ziyun", expiry_note="Reply by Friday")
    assert r2["share"] == r["share"] and r2["dir"] == d
    assert _files(d) == first and open(r2["zip"], "rb").read() == zbytes
    other = SH.build_page(clips, str(tmp_path / "copy"), title="Week 12", quality="small", owner_name="Ziyun",
                          expiry_note="Reply by Friday", share_id=r["share"])
    assert _files(other["dir"]) == first


def test_quality_footer_selection_and_errors(tmp_path, media):
    w = _work(tmp_path, media)
    r = SH.share(w, outputs=["B_story"], quality="720p", footer=False, make_zip=False)
    data = json.load(open(r["json"], encoding="utf-8"))
    assert [c["id"] for c in data["clips"]] == ["B_story"] and r["zip"] is None and r["quality"] == "standard"
    assert data["footer"] is False and data["footer_url"] is None
    v = data["clips"][0]["versions"][0]
    assert (v["w"], v["h"]) == (720, 1280)
    with pytest.raises(SH.ShareError) as e:
        SH.share(w, quality="8k")
    assert e.value.info["code"] == "bad-quality"
    with pytest.raises(SH.ShareError) as e:
        SH.share(w, outputs=["nope"])
    assert e.value.info["code"] == "no-clips"
    with pytest.raises(SH.ShareError) as e:
        SH.share(w, host="cloud")
    assert e.value.info["code"] == "unknown-host"
    os.makedirs(tmp_path / "busy")
    (tmp_path / "busy" / "keep.txt").write_text("x")
    with pytest.raises(SH.ShareError) as e:
        SH.build_page(SH.collect_clips(w), str(tmp_path / "busy"))
    assert e.value.info["code"] == "out-not-empty"


def test_hosts_are_pluggable(tmp_path, media):
    w = _work(tmp_path, media)
    seen = []

    class Fake(SH.FolderHost):
        name, hosted = "fake", True

        def publish(self, folder, record):
            seen.append((folder, record["share"]))
            return dict(host="fake", url="https://example.invalid/r/x")
    SH.register_host("fake", Fake)
    try:
        r = SH.share(w, quality="small", make_zip=False, host="fake")
    finally:
        SH.HOSTS.pop("fake", None)
    assert r["url"] == "https://example.invalid/r/x" and seen == [(r["dir"], r["share"])]
    assert SH.get_host().publish("/x", {})["url"] is None and SH.get_host().fetch_feedback({}) == []


# --------------------------------------------------------------------------- privacy
def test_privacy_scan_reads_mask_metadata(tmp_path, media):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "project.yaml").write_text("recipe: call-clips\nparams:\n  guests: [{name: g1}]\n  no_mask: true\n")
    s = SH.privacy_scan(str(p))
    assert s["needs_ack"] and [w["code"] for w in s["warnings"]][0] == "unmasked-people"
    (p / "project.yaml").write_text("recipe: call-clips\nparams:\n  guests: [{name: g1}]\n  privacy_exclude: [[0,0,10,10]]\n")
    codes = {w["code"]: w["level"] for w in SH.privacy_scan(str(p))["warnings"]}
    assert codes == {"masked-people": "warn", "hidden-regions": "info", "guest-consent": "info"}
    w = _work(tmp_path, media)
    assert SH.privacy_scan(w) == dict(ok=True, warnings=[], needs_ack=False)
    # a privacy sticker added in the output editor counts as a masked person
    edir = O.list_outputs(w)["outputs"][0]["edit_dir"]
    os.makedirs(edir, exist_ok=True)
    json.dump(dict(state=dict(effects=[dict(effect="privacy-sticker", start=0)])), open(os.path.join(edir, "edit.json"), "w"))
    s = SH.privacy_scan(w)
    assert s["needs_ack"] and s["warnings"][0]["code"] == "masked-people"


# --------------------------------------------------------------------------- feedback
def test_parse_feedback_code_json_email_and_errors():
    sid = "a" * 20
    code = _code(sid, [("A_hook", "approve", ""), ("B_story", "change", "0:12 the caption covers my face")])
    doc = SH.parse_feedback(code)
    assert doc["share"] == sid and doc["reviewer"] == "Mia"
    assert doc["clips"] == [dict(id="A_hook", decision="approve", comment=""),
                            dict(id="B_story", decision="change", comment="0:12 the caption covers my face")]
    # inside an email, wrapped by the mail app, followed by a signature
    wrapped = "Hi!\n\nFeedback code:\n" + "\n".join(code[i:i + 60] for i in range(0, len(code), 60)) + "\n"
    assert SH.parse_feedback(wrapped)["clips"] == doc["clips"]
    assert SH.parse_feedback("see below " + code + " thanks")["share"] == sid
    full = dict(kind=SH.FEEDBACK_KIND, version=1, share=sid, reviewer="Mia", at=None,
                clips=[dict(id="A_hook", decision="approve", comment="  nice  "), dict(id="x", decision="maybe")])
    assert SH.parse_feedback(json.dumps(full))["clips"] == [dict(id="A_hook", decision="approve", comment="nice")]
    for bad, code_ in ((code[:30], "bad-feedback"), ("hello", "bad-feedback"),
                       (json.dumps(dict(full, version=9)), "feedback-version"),
                       (json.dumps(dict(full, clips=[])), "empty-feedback"),
                       (json.dumps(dict(full, kind="other")), "bad-feedback")):
        with pytest.raises(SH.ShareError) as e:
            SH.parse_feedback(bad)
        assert e.value.info["code"] == code_, bad


def test_import_pins_changes_marks_ready_and_dedupes(tmp_path, media):
    w = _work(tmp_path, media)
    r = SH.share(w, quality="small", make_zip=False)
    code = _code(r["share"], [("A_hook", "approve", ""), ("B_story", "change", "Shorter intro please"),
                              ("ghost", "approve", "")])
    imp = SH.import_feedback(code)
    assert imp["owner"] == w and imp["unknown"] == ["ghost"] and len(imp["items"]) == 2
    ch = next(x for x in imp["items"] if x["decision"] == "change")
    assert ch["pinned"] and ch["pinned"]["output"] == "final/B_story.mp4"
    turns = O.chat(w, "final/B_story.mp4")["turns"]
    assert turns[-1]["text"] == "Mia: Shorter intro please" and turns[-1]["status"] == "note"
    again = SH.import_feedback(code)
    assert again["items"] == [] and again["duplicates"] == 2
    assert len(SH.feedback_items(w)) == 2
    ap = next(x for x in imp["items"] if x["decision"] == "approve")
    res = SH.resolve(w, ap["id"])
    assert res["item"]["status"] == "done" and "A_hook" in SH.ready_marks(w)
    SH.resolve(w, ch["id"])
    assert SH.feedback_items(w) == [] and len(SH.feedback_items(w, "all")) == 2
    SH.mark_ready(w, "A_hook", undo=True)
    assert "A_hook" not in SH.ready_marks(w)
    with pytest.raises(SH.ShareError) as e:
        SH.import_feedback(_code("b" * 20, [("A_hook", "approve", "")]))
    assert e.value.info["code"] == "unknown-share"


def test_cli_share_and_feedback_json(tmp_path, media):
    w = _work(tmp_path, media)
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib"))
    run = lambda *a, inp=None: subprocess.run([sys.executable, "-m", "vstudio.project", *a], capture_output=True,  # noqa: E731
                                              text=True, env=env, input=inp)
    p = run("share", "--dir", w, "--scan", "--json")
    assert p.returncode == 0 and json.loads(p.stdout)["clips"][0]["id"] == "A_hook"
    p = run("share", "--dir", w, "--quality", "small", "--no-footer", "--title", "T", "--json")
    r = json.loads(p.stdout)
    assert p.returncode == 0 and r["ok"] and os.path.isfile(r["index"]) and r["footer"] is False
    f = tmp_path / "fb.reelfold.json"
    f.write_text(json.dumps(dict(kind=SH.FEEDBACK_KIND, version=1, share=r["share"], reviewer="Leo",
                                 clips=[dict(id="B_story", decision="change", comment="louder")])))
    p = run("feedback", "import", "--file", str(f), "--json")
    imp = json.loads(p.stdout)
    assert p.returncode == 0 and len(imp["items"]) == 1
    p = run("feedback", "list", "--dir", w, "--json")
    fid = json.loads(p.stdout)["items"][0]["id"]
    p = run("feedback", "resolve", "--dir", w, "--id", fid, "--json")
    assert json.loads(p.stdout)["item"]["status"] == "done"
    p = run("feedback", "import", "--json", inp="nothing here")
    assert p.returncode == 5 and json.loads(p.stdout)["code"] == "bad-feedback"
    p = run("share", "--dir", w, "--quality", "4k", "--json")
    assert p.returncode == 5 and json.loads(p.stdout)["code"] == "bad-quality"


# --------------------------------------------------------------------------- a recipe project
@pytest.fixture(scope="module")
def th(tmp_path_factory):
    """A talkinghead project run end to end with the fake transcriber (two platform exports of one item)."""
    import _batch_helpers as H
    d = tmp_path_factory.mktemp("share-th")
    words = [("大家", .4), ("好", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35), ("方法", .4), ("最后", .4)]
    x, truth, dur = H.synth_speech(words)
    src = H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    old = {k: os.environ.get(k) for k in ("VSTUDIO_TEST_TRUTH", "VSTUDIO_HOME", "VSTUDIO_BATCH_BENCH")}
    os.environ.update(VSTUDIO_TEST_TRUTH=str(tp), VSTUDIO_HOME=str(d / "home"), VSTUDIO_BATCH_BENCH=str(d / "b.json"))
    try:
        from vstudio.project.core import Project
        p = Project.create(str(d / "th"), recipe="talkinghead", inputs=dict(video=[src]),
                           params=dict(pipeline="fast", preset="ultrafast", speed=1.0, platforms=["xiaohongshu:full", "douyin"]),
                           auto=["hook", "filler", "cover"],
                           spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                     asr=dict(transcriber="_batch_helpers:fake_transcriber"),
                                     proofread=dict(enabled=False)))
        p.run()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return str(d / "th")


def test_project_clip_versions_and_approve_marks_ready(th, tmp_path):
    clips = SH.collect_clips(th)
    assert len(clips) == 1
    c = clips[0]
    assert len(c["versions"]) == 2 and c["ref"]["item"] == c["id"] and len(c["ref"]["outputs"]) == 2
    r = SH.share(th, quality="small", make_zip=False)
    data = json.load(open(r["json"], encoding="utf-8"))
    assert len(data["clips"][0]["versions"]) == 2
    assert {v["platform"] for v in data["clips"][0]["versions"]} == {p for p in (v["platform"] for v in c["versions"])}
    imp = SH.import_feedback(_code(r["share"], [(c["id"], "approve", "")]))
    res = SH.resolve(th, imp["items"][0]["id"])
    assert res["item"]["result"]["how"] in ("publish-checkpoint", "approved")
    from vstudio.batch.store import Store
    st = Store(os.path.join(th, "state"))
    try:
        j = st.job(c["id"])
    finally:
        st.close()
    assert j["review"] == "approved" or res["item"]["result"]["how"] == "publish-checkpoint"
    assert c["id"] in SH.ready_marks(th)


def test_a_plain_batch_is_never_adopted_as_a_work_folder(tmp_path):
    b = tmp_path / "batch"
    b.mkdir()
    (b / "batch.db").write_bytes(b"")
    assert SH.owner_dirs(str(b))[1] == "batch"
    SH.privacy_scan(str(b))
    assert SH.pin_comment(str(b), dict(ref=dict(outputs=["ep01/douyin"]), reviewer="x", comment="y", share="s",
                                       id="i", decision="change")) is None
    assert not (b / ".vstudio").exists()
