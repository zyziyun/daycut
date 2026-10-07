"""v0.2 P1 batch recipes: podcast-clips (workflows/call-clips per job, coverage proof as a QC gate) and
talkinghead-folder (the talkinghead V pipeline per clip). The workflow scripts are replaced by fakes that write
their outputs (tiny real media), so the wiring, the configs the batch writes and the gates are tested without
long renders; verify_coverage.py itself runs for real on synthetic tracks."""
import json
import os
import shutil
import subprocess

import pytest
import yaml

from vstudio.batch import podcast as PC
from vstudio.batch import thfolder as TH
from vstudio.batch.plan import plan_batch
from vstudio.batch.run import run_batch
from vstudio.batch.store import Store

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CAT = os.path.join(ROOT, "workflows", "call-clips", "assets", "cat.png")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))


def tiny(path, dur=4.0, size="360x640"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s={size}:r=30:d={dur}", "-f", "lavfi",
                    "-i", f"sine=f=300:d={dur}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return str(path)


def whisper(path, sents, t0=0.3):
    segs, t = [], t0
    for s in sents:
        ws = []
        for ch in s:
            ws.append(dict(word=ch, start=round(t, 3), end=round(t + 0.15, 3)))
            t += 0.18
        segs.append(dict(start=ws[0]["start"], end=ws[-1]["end"], text=s, words=ws))
        t += 0.4
    json.dump(dict(language="zh", segments=segs), open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return str(path)


def track(path, n=30, cx=180, cy=200, w=60, h=70):
    json.dump(dict(fps=30.0, cx=[cx] * n, cy=[cy] * n, w=[w] * n, h=[h] * n), open(path, "w"))


# --------------------------------------------------------------------------- podcast-clips
def test_podcast_clip_config_and_coverage_gate(tmp_path):
    spec = dict(call=dict(host_region="640,180,640,360", auto_trim=True, name_mask="blur",
                          guests=[dict(name="guest", region="0,180,640,360", sticker="assets/cat.png", label="B")]),
                subtitles=dict(term_fixes=[["rag", "RAG"]]))
    p = dict(_clip_id="ep01", source="/x/call.mp4", range=[10.0, 70.0], title="RAG的核心：检索质量", chapter="检索",
             hooks=[dict(src=[30, 34], lines=["钩子"])], notes=["第一点", "第二点"])
    cfg = PC.clip_config(p, spec, str(tmp_path))
    c = cfg["clips"][0]
    assert cfg["whisper"] == "work/audio16k.json" and cfg["guests"][0]["region"] == "0,180,640,360"
    assert c["windows"] == [[10.0, 70.0]] and c["hooks"] == [[30.0, 34.0]]
    assert c["title"] == [[["RAG的核心", False]], [["检索质量", True]]] and c["panels"][0][3] == ["第一点", "第二点"]
    assert cfg["term_fix"] == [["rag", "RAG"]] and cfg["name_mask"] == "blur"
    # the coverage proof, for real: a face box inside the sticker passes, a huge one fails
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    track(good, w=60, h=70)
    track(bad, w=60, h=600)

    class Ctx:
        spec = dict(call=dict(renderer_args=["scale=2.4"]))
        inputs = dict(compose=dict(tracks=[dict(name="guest", track=str(good), sticker=CAT),
                                           dict(name="guest2", track=str(bad), sticker=CAT)]))
        dir = str(tmp_path)

        def path(self, *n):
            return os.path.join(str(tmp_path), *n)
    out = PC.run_coverage(Ctx())
    by = {t["name"]: t for t in out["tracks"]}
    assert by["guest"]["ok"] and by["guest"]["worst"] == 1.0
    assert not by["guest2"]["ok"] and not out["ok"]
    checks = PC.coverage_checks(out)
    assert [c["ok"] for c in checks] == [True, False] and checks[1]["severity"] == "red"
    assert PC.parse_coverage("frames=3  worst coverage=97.500% at t=0.1s\n  FAIL") == (0.975, False)


def test_podcast_recipe_end_to_end_with_fake_build(tmp_path, monkeypatch):
    src = tiny(tmp_path / "call.mp4", 6.0, "640x360")
    tr = whisper(tmp_path / "tr.json", ["大家好今天聊播客", "第二句话很重要"])
    calls = []

    def fake_script(name, cwd, *args, timeout=None):
        calls.append((name, args))
        cfg = json.load(open(os.path.join(cwd, "clips.json"), encoding="utf-8"))
        cid = cfg["clips"][0]["id"]
        os.makedirs(os.path.join(cwd, "out"), exist_ok=True)
        tiny(os.path.join(cwd, "out", f"{cid}.clean.mp4"), 3.0)
        json.dump([dict(start=0.2, end=1.5, text="大家好今天聊播客"), dict(start=1.6, end=2.8, text="第二句话很重要")],
                  open(os.path.join(cwd, "work", f"{cid}.cues.json"), "w", encoding="utf-8"), ensure_ascii=False)
        track(os.path.join(cwd, "work", f"{cid}.track.guest.json"))
        return "ok"
    monkeypatch.setattr(PC, "_script", fake_script)
    spec = dict(name="pod", recipe="podcast-clips", inputs=dict(source=src, transcript=tr), retry={"backoff": 0},
                call=dict(host_region="320,0,320,360", guests=[dict(name="guest", region="0,0,320,360",
                                                                    sticker=CAT)]),
                proofread={"provider": "none"}, qc={"sample_pct": 0},
                jobs=[dict(id="ep01", start=0.3, end=5.0, title="播客片段", hook_candidates=[dict(start=1, end=2, text="h")])],
                defaults=dict(platforms=["xiaohongshu:full"], preset="ultrafast"))
    sp = tmp_path / "batch.yaml"
    sp.write_text(yaml.safe_dump(spec, allow_unicode=True))
    r = plan_batch(str(sp), echo=False)
    res = run_batch(r["batch_dir"], echo=False)
    assert res["exit_code"] == 0, res
    name, args = calls[0]
    assert name == "build_clips.py" and "--clean-master" in args and args[args.index("--only") + 1] == "ep01"
    assert args[args.index("--platform") + 1] == "xiaohongshu:full"
    st = Store(r["batch_dir"])
    j = st.job("ep01")
    cov = st.stage("ep01", "coverage")["out"]
    ex = st.stage("ep01", "export")["out"]["exports"]
    st.close()
    assert cov["ok"] and os.path.exists(ex[0]["file"])
    assert j["state"] == "done" and any(c["name"] == "face-mask-coverage" and c["ok"]
                                        for c in json.load(open(os.path.join(r["batch_dir"], "jobs", "ep01", "qc",
                                                                             "qc.json")))["checks"])
    cfg = json.load(open(os.path.join(r["batch_dir"], "jobs", "ep01", "compose", "clips.json"), encoding="utf-8"))
    assert cfg["clips"][0]["hooks"] == [[1.0, 2.0]]                      # plan-segments hook candidate -> cold open


# --------------------------------------------------------------------------- talkinghead-folder
def test_talkinghead_folder_files(tmp_path):
    w = whisper(tmp_path / "a1.json", ["第一句话", "第二句话", "第三句"])
    txt, n = TH.edit_list(w, "tight")
    ns = {}
    exec(txt, ns)
    assert n == 3 and ns["PROFILE"] == "tight" and ns["E"][0][0] == 1 and ns["E"][1][2] == "第二句话"
    t0 = ns["E"][1][1][0][0]
    _, n2 = TH.edit_list(w, None, rng=[t0 - 0.1, 99])
    assert n2 == 2                                                       # a trimmed job keeps sentences 2-3
    ns = {}
    exec(TH.strict_file("确认 3 / 保留 4"), ns)
    assert ns["REPLY"] == "确认 3 / 保留 4"
    cfg = TH.config_file(dict(_clip_id="c1", platforms=["douyin"], speed=1.2, keywords=["RAG"]),
                         dict(talkinghead=dict(style=dict(progress="classic"), hook_speed=1.4)), True)
    ns = {}
    exec(cfg, ns)
    assert ns["BODY"] == "body2_v.mp4" and ns["FACE"] == "face.npy" and ns["PLATFORM"] == "douyin"
    assert ns["STYLE"] == {"progress": "classic"} and ns["BODY_SPEED"] == 1.2 and ns["HOOK_SPEED"] == 1.4
    assert ns["HOOKS"] == [] and ns["OUT"] == "out/c1.mp4" and ns["KEYWORDS"] == ["RAG"]


def test_talkinghead_folder_end_to_end_with_fake_scripts(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    tiny(raw / "clip one.mp4", 3.0)
    tiny(raw / "clip2.mp4", 3.0)
    seen = []

    def fake_run(cmd, cwd, log, env=None, timeout=None):
        name = os.path.basename(str(cmd[1]))
        seen.append((name, [str(c) for c in cmd[2:]], dict(env or {})))
        if name == "prep_sources.sh":
            src = str(cmd[3])
            shutil.copyfile(src, os.path.join(cwd, "sdr1.mp4"))
            open(os.path.join(cwd, "a1.wav"), "wb").write(b"RIFF")
            whisper(os.path.join(cwd, "a1.json"), ["你好", "今天讲方法"])
        elif name == "cut_pass1.py":
            json.dump(dict(edits=[dict(id=1, action="confirm", kind="filler", t0=0.5, t1=0.7, text="就是")]),
                      open(os.path.join(cwd, "cleanup.c1.json"), "w"))
            shutil.copyfile(os.path.join(cwd, "sdr1.mp4"), os.path.join(cwd, "body_v.mp4"))
        elif name == "strict_pass.py":
            shutil.copyfile(os.path.join(cwd, "body_v.mp4"), os.path.join(cwd, "body2_v.mp4"))
            open(os.path.join(cwd, "body2_a.wav"), "wb").write(b"RIFF")
            json.dump(dict(subs=[], total=2.0), open(os.path.join(cwd, "segs.json"), "w"))
        elif name == "face_track.py":
            raise RuntimeError("no face model")                       # compose must cope without a face track
        elif name == "compose.py":
            cfg = {}
            exec(open(os.path.join(cwd, "config.py"), encoding="utf-8").read(), cfg)
            stem = os.path.splitext(cfg["OUT"])[0]
            tiny(os.path.join(cwd, stem + ".clean.mp4"), 2.5)
            json.dump(dict(cues=[dict(start=0.2, end=1.2, text="你好"), dict(start=1.3, end=2.2, text="今天讲方法")],
                           keepouts=[dict(t0=0.0, t1=2.0, box=[10, 300, 340, 200], kind="panel")], size=[360, 640]),
                      open(os.path.join(cwd, stem + ".cues.json"), "w"), ensure_ascii=False)
        return "ok"
    monkeypatch.setattr(TH, "_run", fake_run)
    spec = dict(name="th", recipe="talkinghead-folder", inputs=dict(folder=str(raw)), retry={"backoff": 0},
                asr={"prompt": "RAG"}, proofread={"provider": "none"}, qc={"sample_pct": 0},
                talkinghead=dict(style=dict(progress="classic")),
                jobs=[dict(id="c2", file="clip2.mp4", title="第二条", cleanup_reply="确认 1")],
                defaults=dict(platforms=["douyin"], preset="ultrafast"))
    sp = tmp_path / "batch.yaml"
    sp.write_text(yaml.safe_dump(spec, allow_unicode=True))
    r = plan_batch(str(sp), echo=False)
    assert sorted(r["jobs"]) == ["c2", "clip-one"]
    res = run_batch(r["batch_dir"], echo=False)
    assert res["exit_code"] == 0, res
    names = [n for n, _, _ in seen]
    assert names.count("prep_sources.sh") == 2 and names.count("compose.py") == 2
    prep_env = next(e for n, _, e in seen if n == "prep_sources.sh")
    assert prep_env["PROMPT"] == "RAG" and prep_env["PLATFORM"] == "douyin"
    st = Store(r["batch_dir"])
    for jid in ("c2", "clip-one"):
        j = st.job(jid)
        assert j["state"] == "done", (jid, j["qc_reasons"])
        assert os.path.exists(st.stage(jid, "export")["out"]["exports"][0]["file"])
        man = json.load(open(st.stage(jid, "export")["out"]["manifest"], encoding="utf-8"))
        assert man["exports"][0]["keepouts"] == 1      # the panel keep-out survives proofread into the export
    cl = st.stage("c2", "cleanup")["out"]
    st.close()
    assert cl["confirm"] == 1 and cl["sentences"] == 2
    strict = open(os.path.join(r["batch_dir"], "jobs", "c2", "cleanup", "strict.py"), encoding="utf-8").read()
    assert "确认 1" in strict
