"""P1-4: engine-originated user text carries code + params (English message + message_zh kept); every code is in
references/MESSAGES.md (en / zh / fr) for the desk to map."""
import json
import subprocess
import sys
import pathlib

from vstudio import messages as M

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_messages_md_is_current_and_has_french():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_messages_md.py"), "--check"], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_msg_shape_and_coded_strings():
    m = M.msg("qc.loudness", value=-9.1, lufs=-14)
    assert m == dict(code="qc.loudness", params=dict(value=-9.1, lufs=-14), message="Loudness -9.1 LUFS (target -14)",
                     message_zh="响度 -9.1 LUFS（目标 -14）")
    s = M.cs("intake.risk.no-video", recipe="vlog")
    assert s == "vlog: 没有找到视频素材" and json.dumps([s], ensure_ascii=False) == '["vlog: 没有找到视频素材"]'
    assert M.info_of(s)["code"] == "intake.risk.no-video" and M.info_of("free text")["code"] == "status-text"
    assert M.stage("asr")["message_zh"] == "语音转文字" and M.stage("weird")["code"] == "stage.other"
    assert M.state("job-state", "planned")["message_zh"] == "待做" and M.state("qc-state", None)["message_zh"] == "未验证"


def test_qc_check_message():
    from vstudio.batch import qc
    c = qc._c("loudness", False, -9.1, "integrated -9.1 LUFS vs target -14", target="douyin:full", lufs=-14)
    assert c["message"]["code"] == "qc.loudness" and c["message"]["params"]["lufs"] == -14
    assert "message" not in qc._c("loudness", True, -14.0, "x")


def test_status_json_codes(tmp_path):
    from vstudio.batch import livestatus as LS
    rec = LS.write(str(tmp_path), "running", stage="asr", message="12 of 40 files")
    assert rec["status_info"]["code"] == "status.running" and rec["stage_info"]["code"] == "stage.asr"
    assert rec["message_info"] == dict(code="status-text", params=dict(text="12 of 40 files"), message="12 of 40 files",
                                       message_zh="12 of 40 files")
    rec = LS.write(str(tmp_path), "waiting", message_code="inbox.cover-pick", message_params={"n": 6})
    assert rec["message_info"]["code"] == "inbox.cover-pick"


def test_intake_plan_messages(tmp_path):
    from test_intake import build
    from vstudio.intake import plan as PL
    p = PL.make_plan("播客里有意思的部分剪出来，嘉宾遮脸", analysis=build("podcast", tmp_path), asr="off")
    assert p["questions"][0]["message"]["code"] == "intake.question.mask-faces"
    assert p["questions"][0]["text"] == p["questions"][0]["message"]["message_zh"]
    assert p["planner"]["message"]["code"] == "intake-no-model"
    cps = p["projects"][0]["checkpoints"]
    assert all(c["label_info"]["code"] == f"checkpoint.{c['kind']}" for c in cps)
    assert p["projects"][0]["recipe_info"]["code"] == "recipe.call-clips.label"
    p2 = PL.make_plan("旅行素材剪个卡点 vlog 发抖音", analysis=build("pdf", tmp_path / "x"), asr="off")
    assert all(r["code"].startswith("intake.risk") for r in p2["risks_info"])
    assert len(p2["risks_info"]) == len(p2["risks"]) and len(p2["warnings_info"]) == len(p2["warnings"])


def test_recipe_messages():
    from vstudio.project import manifests as MF
    from vstudio.project.core import public_manifest
    d = public_manifest(MF.get("talkinghead"))
    assert d["messages"]["label"]["code"] == "recipe.talkinghead.label" and d["messages"]["label"]["message_zh"] == "口播精剪"
    assert d["messages"]["description"]["message"].startswith("talking-head")


def test_inbox_entry_codes():
    from vstudio.project import inbox as IB
    e = IB._entry(None, dict(project="/p", item="i1", id="cover", kind="cover-pick", scope="item",
                             labels={"zh": "选封面", "en": "Pick the cover"}, options=[{"id": 1}, {"id": 2}]))
    assert e["label_info"]["code"] == "checkpoint.cover-pick" and e["reason"]["code"] == "inbox.cover-pick"
    assert e["reason"]["params"]["n"] == 2 and e["reason"]["message_zh"]
