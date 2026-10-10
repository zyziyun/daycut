"""A request with no files is planned, never failed (her "read my Notion, make popular-science videos for my IP"
ended in "PlanError: no inputs"): from its words (an explainer / a series), from the links in it (a web page, a
public Notion page; a fake fetcher), from an exported Notion folder (Markdown / HTML); what only she can give comes
back as ``needs`` (her recordings for a request that cuts footage, her Notion pages when they could not be read)
and the plan waits for it - or plans without it (``--ignore-needs``). No model in these tests (the rule planner)."""
import json
import os
import subprocess
import sys

import pytest

from vstudio.intake import plan as PL
from vstudio.intake import sources as S

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NOTION = "https://me.notion.site/AI-1a2b3c4d5e6f708192a3b4c5d6e7f809"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("vstudio.intake.inventory.cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setenv("VSTUDIO_LLM_PROVIDER", "none")
    monkeypatch.setenv("VSTUDIO_LLM_INTAKE_PROVIDER", "none")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def notion_http(blocks, calls=None):
    """A fake fetcher answering Notion's public page endpoint (loadPageChunk) with these blocks."""
    def http(url, data=None, timeout=None):
        if calls is not None:
            calls.append((url, data))
        assert url.endswith("/api/v3/loadPageChunk") and data["pageId"] == "1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f809"
        rec = {bid: dict(value=v) for bid, v in blocks.items()}
        return json.dumps(dict(recordMap=dict(block=rec), cursor=dict(stack=[]))).encode(), "application/json"
    return http


PAGE = {"1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f809": dict(type="page", properties=dict(title=[["我的 AI 经验"]]),
                                                       content=["b1", "b2", "b3", "b4"]),
        "b1": dict(type="header", properties=dict(title=[["第一期：为什么要学提示词"]])),
        "b2": dict(type="text", properties=dict(title=[["提示词就是你和模型之间的合同，", [["b"]]], ["写清楚角色、目标和格式。"]])),
        "b3": dict(type="header", properties=dict(title=[["第二期：三个常见误区"]])),
        "b4": dict(type="bulleted_list", properties=dict(title=[["把模型当搜索引擎；一次问太多；不给例子。"]]))}


def test_words_only_request_is_an_explainer_series_not_a_failure():
    p = PL.make_plan("做一个 5 集的时间管理讲解系列", [], ui_lang="en")
    assert [x["recipe"] for x in p["projects"]] == ["explainer"]
    assert p["projects"][0]["items"]["count"] == 5 and not p.get("needs")
    p = PL.make_plan("Make a video about how sleep works", [], ui_lang="en")
    assert [x["recipe"] for x in p["projects"]] == ["explainer"] and not p.get("needs")


def test_a_request_that_cuts_footage_asks_for_the_recordings():
    p = PL.make_plan("帮我把这条口播剪干净，去气口", [], ui_lang="zh")
    assert p["projects"] == [] and [n["code"] for n in p["needs"]] == ["intake.need.footage"]
    assert p["summary_zh"].startswith("把要剪的录像拖进来")
    assert p["planner"]["route"] == "needs"                     # no model call while it waits for her
    p = PL.make_plan("cut my podcast into clips", [], ui_lang="en")
    assert p["needs"][0]["message"].startswith("Add the recordings")


def test_her_notion_with_no_link_asks_for_the_pages_and_can_go_on_without():
    prompt = "阅读我的notion，尝试做一下有丰富交互的科普经验类视频，做ip"
    p = PL.make_plan(prompt, [], ui_lang="zh")
    assert [n["code"] for n in p["needs"]] == ["intake.need.notion"]
    assert "Export" in p["needs"][0]["message"] and "导出" in p["needs"][0]["message_zh"]
    assert [x["recipe"] for x in p["projects"]] == ["explainer"]          # what it would make, shown while it waits
    go = PL.make_plan(prompt, [], ui_lang="zh", ignore_needs=True)
    assert not go.get("needs") and [x["recipe"] for x in go["projects"]] == ["explainer"]


def test_a_public_notion_link_is_read_and_planned_from(tmp_path):
    calls = []
    p = PL.make_plan(f"用我的 Notion 笔记做科普视频 {NOTION}", [], ui_lang="zh", http=notion_http(PAGE, calls))
    assert not p.get("needs") and p["sources"] == [dict(url=NOTION, title="我的 AI 经验", chars=p["sources"][0]["chars"],
                                                        notion=True)]
    txt = [m for m in p["materials"] if m["kind"] == "text"]
    assert len(txt) == 1 and txt[0]["path"].endswith(".md")
    body = open(txt[0]["path"], encoding="utf-8").read()
    assert body.startswith("# 我的 AI 经验") and "# 第一期：为什么要学提示词" in body and "- 把模型当搜索引擎" in body
    ex = p["projects"][0]
    assert ex["recipe"] == "explainer" and ex["items"]["count"] >= 2          # one per heading of her notes
    assert any("第一期" in r["inputs"]["topic"] for r in ex["items"]["rows"])
    # read once: the second plan uses the cached page
    PL.make_plan(f"再做一次 {NOTION} 科普", [], ui_lang="zh", http=notion_http(PAGE, calls))
    assert len(calls) == 1


def test_a_private_notion_page_says_so_plainly():
    def http(url, data=None, timeout=None):
        return json.dumps(dict(recordMap=dict(block={}))).encode(), "application/json"
    p = PL.make_plan(f"用这个做科普 {NOTION}", [], ui_lang="en", http=http)
    assert [n["code"] for n in p["needs"]] == ["intake.need.notion-private"]
    assert NOTION in p["needs"][0]["message"] and "isn't shared to the web" in p["needs"][0]["message"]


def test_a_web_page_link_and_an_exported_notion_folder(tmp_path):
    html = (b"<html><head><title>Sleep 101</title><script>x=1</script></head><body><nav>menu</nav><h1>Why we sleep"
            b"</h1><p>" + b"Sleep clears the brain of waste. " * 8 + b"</p><h2>Stages</h2><p>REM and deep sleep.</p>"
            b"</body></html>")

    def http(url, data=None, timeout=None):
        return html, "text/html; charset=utf-8"
    p = PL.make_plan("make an explainer from https://example.org/sleep", [], ui_lang="en", http=http)
    body = open(p["materials"][0]["path"], encoding="utf-8").read()
    assert "# Why we sleep" in body and "menu" not in body and "x=1" not in body
    assert p["sources"][0]["title"] == "Sleep 101"
    # a Notion export (unzipped folder of HTML / Markdown) dropped as her notes: no need, the notes are the content
    exp = tmp_path / "Notion export"
    exp.mkdir()
    (exp / "Ideas 1a2b.html").write_text("<html><head><title>Ideas</title></head><body><h1>Ideas</h1><h2>Episode one"
                                         "</h2><p>" + "Prompts are contracts. " * 10 + "</p></body></html>")
    (exp / "More.md").write_text("# More\n\n## Episode two\n\nThree mistakes.\n")
    p = PL.make_plan("read my Notion and make explainers", [str(exp)], ui_lang="en")
    assert not p.get("needs") and {m["kind"] for m in p["materials"]} == {"text"}
    assert p["projects"][0]["recipe"] == "explainer"


def test_unreadable_link_and_nothing_at_all():
    def http(url, data=None, timeout=None):
        raise S.SourceError("http", f"{url}: HTTP 403")
    p = PL.make_plan("explain https://paywalled.example.com/a", [], ui_lang="en", http=http)
    assert p["needs"][0]["code"] == "intake.need.page-unreadable"
    with pytest.raises(PL.PlanError) as e:
        PL.make_plan("  ", [])
    assert e.value.code == "empty"


def test_cli_ignore_needs_and_coded_errors(tmp_path):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib"), VSTUDIO_LLM_PROVIDER="none")
    run = lambda *a: subprocess.run([sys.executable, "-m", "vstudio.intake", "plan", *a, "--json"],  # noqa: E731
                                    capture_output=True, text=True, env=env)
    r = run("--prompt", "read my Notion and make explainers about AI")
    assert r.returncode == 0 and json.loads(r.stdout)["needs"][0]["code"] == "intake.need.notion"
    r = run("--prompt", "read my Notion and make explainers about AI", "--ignore-needs")
    assert r.returncode == 0 and "needs" not in json.loads(r.stdout)
    r = run("--prompt", " ")
    assert r.returncode == 5 and json.loads(r.stdout) == dict(ok=False, error="nothing to plan: no request and no files",
                                                              code="plan-empty")
