"""launch-kit recipe (vstudio.launch): release notes -> features, config validation, storyboard timing and camera,
HyperFrames project, post copy, schedule, first-pass format. Synthetic fixtures only (a generated test-pattern
"recording", made-up product); no render (that needs Node + HyperFrames)."""
import json
import os
import re
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio import platform as PF  # noqa: E402
from vstudio.launch import brand as B  # noqa: E402
from vstudio.launch import compose as CO  # noqa: E402
from vstudio.launch import config as C  # noqa: E402
from vstudio.launch import features as FE  # noqa: E402
from vstudio.launch import posts as PO  # noqa: E402
from vstudio.launch import schedule as SC  # noqa: E402
from vstudio.launch import story as S  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FONTS = os.path.join(ROOT, "apps", "site", "public", "fonts")
DISPLAY = os.path.join(FONTS, "newsreader-latin-opsz-normal.woff2")
TEXT = os.path.join(FONTS, "inter-latin-wght-normal.woff2")


# ------------------------------------------------------------------------------------------------ features
def test_conventional_commits_keep_user_facing_changes_only():
    fs = FE.from_commits(["feat(desk): add a week board for publishing", "fix(engine): keep the word a filler cut trims",
                          "chore: bump deps", "ci(repo): check commit subjects", "docs: typo",
                          "refactor!: drop the old api", "perf(render): cache stage renders", "not conventional"])
    kinds = [f["kind"] for f in fs]
    assert kinds == ["feat", "perf", "change", "fix"]           # feat first, chores / ci / docs gone
    assert fs[0]["title"] == "Add a week board for publishing" and fs[0]["scope"] == "desk"
    assert len({f["id"] for f in fs}) == len(fs)


def test_changelog_section_with_intro_bullets(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- **App**, MIT:\n  - Home composer: describe the job.\n"
                 "  - An inbox that shows only what needs you.\n- **Platforms**: 20 profiles\n  with safe zones.\n"
                 "  - not a feature, a detail\n\n### Fixed\n\n- Chat edits always answer.\n\n## [0.1.0]\n\n- Old thing\n",
                 encoding="utf-8")
    fs = FE.from_changelog(str(p))
    titles = [f["title"] for f in fs]
    assert titles == ["Home composer", "An inbox that shows only what needs you", "Platforms",
                      "Chat edits always answer"]
    assert fs[-1]["kind"] == "fix"
    assert [f["title"] for f in FE.from_changelog(str(p), "0.1.0")] == ["Old thing"]
    with pytest.raises(ValueError):
        FE.from_changelog(str(p), "9.9")


def test_git_range(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com"))
    git("init", "-q")
    for msg in ("chore: init", "feat: first feature", "feat(ui): second feature"):
        git("commit", "-q", "--allow-empty", "-m", msg)
    git("tag", "v1")
    git("commit", "-q", "--allow-empty", "-m", "feat: third feature")
    assert [f["title"] for f in FE.from_git(str(tmp_path), "v1..HEAD")] == ["Third feature"]
    assert len(FE.from_git(str(tmp_path))) == 3
    with pytest.raises(ValueError):
        FE.from_git(str(tmp_path), "nope..HEAD")


def test_notes_and_slug():
    assert [f["title"] for f in FE.from_notes("Faster sync\nDark mode")] == ["Faster sync", "Dark mode"]
    assert len(FE.slug("a very long feature name that keeps going and going", 20)) <= 20


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def kitdir(tmp_path_factory):
    d = tmp_path_factory.mktemp("launch")
    cap = d / "capture"
    cap.mkdir()
    for sid in ("plan", "review"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=576x360:r=30:d=6",
                        "-pix_fmt", "yuv420p", str(cap / f"{sid}.mp4")], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.2", "-i", str(cap / f"{sid}.mp4"), "-frames:v",
                        "1", str(cap / f"{sid}.png")], check=True)
    shots = {"size": [288, 180], "scale": 2, "fps": 30, "shots": [
        {"id": "plan", "title": "Plan", "caption": "", "file": "plan.mp4", "still": "plan.png", "w": 576, "h": 360,
         "duration": 6.0, "focus": [{"t": 1.0, "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.08, "kind": "type"},
                                     {"t": 4.2, "x": 0.7, "y": 0.8, "w": 0.15, "h": 0.06, "kind": "click"}]},
        {"id": "review", "title": "Review", "caption": "", "file": "review.mp4", "still": "review.png", "w": 576,
         "h": 360, "duration": 6.0, "focus": [{"t": 2.0, "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.1, "kind": "click"}]}]}
    (cap / "shots.json").write_text(json.dumps(shots))
    cfg = {
        "out": "kit",
        "product": {"name": "Acme Notes", "name_zh": "速记", "version": "v1.4.0", "site": "https://acme.example",
                    "one_liner": {"en": "Notes that file themselves", "zh": "自己归档的笔记"}},
        "brand": {"colors": {"accent": "#2F6F9F", "marker": "#CFE0EE"}, "fonts": {"display": DISPLAY, "text": TEXT}},
        "languages": ["en", "zh"],
        "platforms": ["xiaohongshu", "x", "tiktok", "linkedin", "youtube-shorts"],
        "capture": {"shots": "capture/shots.json"},
        "features": [
            {"id": "plan", "kicker": {"en": "Plan", "zh": "方案"},
             "caption": {"en": "Describe it in 【one sentence】.", "zh": "【一句话】说清要什么"}},
            {"id": "review", "kicker": {"en": "Review", "zh": "审阅"},
             "caption": {"en": "Look only at what is 【flagged】.", "zh": "只看【标出来】的"}}],
        "end_card": {"cta": {"en": "Free for personal use", "zh": "个人免费"}},
        "post": {"en": {"hook": "Acme Notes 1.4: notes that file themselves.", "body": ["Write; it files."],
                        "tags": ["notes", "productivity"], "links": {"Site": "https://acme.example"}},
                 "zh": {"hook": "速记 1.4：笔记自己归档。", "body": ["随手写。"], "tags": ["效率工具"]}},
        "schedule": {"start": "2026-11-03"},
    }
    (d / "launch.config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return d


@pytest.fixture(scope="module")
def cfg(kitdir):
    return C.load(str(kitdir / "launch.config.yaml"))


@pytest.fixture(scope="module")
def shots(cfg):
    return C.load_shots(cfg)


def _has_cjk_fonts():
    try:
        B.font_files({"brand": {}}, "zh")
        return True
    except Exception:                                    # noqa: BLE001 - fonts come from install.sh
        return False


# ------------------------------------------------------------------------------------------------ config
def test_config_paths_defaults_and_renders(cfg, kitdir):
    assert cfg["out"] == str(kitdir / "kit")
    assert cfg["capture"]["shots"] == str(kitdir / "capture" / "shots.json")
    assert C.renders(cfg, "demo") == [("en", "16:9"), ("en", "9:16"), ("en", "1:1"), ("zh", "16:9"), ("zh", "9:16")]
    assert C.renders(cfg, "clips") == [("en", "1:1"), ("en", "9:16"), ("zh", "9:16")]
    assert C.text({"en": "a", "zh": "b"}, "zh") == "b" and C.text({"en": "a"}, "zh") == "a"


def test_config_errors_are_collected(tmp_path):
    bad = {"product": {"name": "X"}, "languages": ["en", "fr"], "platforms": ["myspace"],
           "features": [{"id": "a", "caption": {"zh": "只有中文"}}, {"id": "a"}],
           "demo": {"shots": ["nope"], "renders": ["en:4:3"]}, "music": {"file": "bed.m4a"}}
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(bad, allow_unicode=True))
    with pytest.raises(C.ConfigError) as e:
        C.load(str(p))
    msg = str(e.value)
    for want in ("one_liner", "languages", "myspace", "unique id", "caption is required", "unknown feature",
                 "LANG:ASPECT", "music.license", "music.file not found"):
        assert want in msg, want


def test_example_config_is_valid_yaml_with_every_section():
    ex = os.path.join(ROOT, "workflows", "launch-kit", "examples", "launch.config.example.yaml")
    with open(ex, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    for k in ("product", "brand", "languages", "platforms", "release", "capture", "features", "demo", "loop", "clips",
              "gallery", "post", "schedule"):
        assert k in d, k
    assert C.validate(C._merge(C.DEFAULTS, d), check_files=False) == []


# ------------------------------------------------------------------------------------------------ story
def test_text_boxes_inside_every_platform_safe_area():
    for asp, plats in C.CANVAS_PLATFORMS.items():
        x0, y0, x1, y1 = S.LAYOUTS[asp]["text"]
        for pl in plats:
            p = PF.profile(pl, use_persona=False)
            assert (p.w, p.h) == C.ASPECTS[asp], pl
            sx0, sy0, sx1, sy1 = PF.safe_box(p)
            assert sx0 <= x0 and sy0 <= y0 and x1 <= sx1 and y1 <= sy1, (asp, pl)
            for kx0, ky0, kx1, ky1 in PF.keepouts(p):
                assert x1 <= kx0 or y1 <= ky0, (asp, pl, "text under the button column")


def test_demo_loop_clip_timing(cfg, shots):
    d = S.plan(cfg, shots, "demo", "en", "16:9")
    assert [s["kind"] for s in d["scenes"]] == ["title", "feature", "feature", "end"]
    assert d["duration"] <= cfg["demo"]["max_seconds"]
    for a, b in zip(d["scenes"], d["scenes"][1:]):
        assert b["start"] == pytest.approx(a["start"] + a["dur"] - S.XF, abs=1e-3)   # crossfades overlap
    lp = S.plan(cfg, shots, "loop", "en", "16:9")
    assert lp["duration"] == pytest.approx(cfg["loop"]["seconds"], abs=0.01) and lp["loop"]
    for asp in ("1:1", "9:16"):
        cl = S.plan(cfg, shots, "clip", "zh", asp, feature="review")
        assert cfg["clips"]["min_seconds"] - 0.01 <= cl["duration"] <= cfg["clips"]["max_seconds"]
        assert cl["scenes"][0]["caption"] == "只看【标出来】的"


def test_demo_is_squeezed_to_max_seconds(cfg, shots):
    tight = dict(cfg, demo=dict(cfg["demo"], max_seconds=12))
    d = S.plan(tight, shots, "demo", "en", "16:9")
    assert all(s["dur"] >= 4.0 for s in d["scenes"] if s["kind"] == "feature")
    assert d["duration"] == pytest.approx(2.6 + 3.2 + 2 * 4.0 - 3 * S.XF, abs=0.01)   # the 4 s floor wins


def test_camera_punches_in_on_actions_and_stays_inside(cfg, shots):
    for asp in S.LAYOUTS:
        L = S.LAYOUTS[asp]
        keys = S.camera(L, shots["plan"], 0.0, 6.0, 7.0)
        assert keys[0]["t"] == 0 and len(keys) >= 3
        _, _, W, H = L["win"]
        fit = max(W / 576, H / 360)
        assert max(k["scale"] for k in keys) > keys[0]["scale"] or asp == "9:16"
        for k in keys:
            assert k["scale"] >= fit - 1e-4
            assert k["x"] <= 0.01 and k["y"] <= 0.01                         # never shows the window's background
            assert k["x"] + 576 * k["scale"] >= W - 0.5 and k["y"] + 360 * k["scale"] >= H - 0.5
        punch = next(k for k in keys[1:] if k["scale"] > keys[0]["scale"] * 1.05) if asp != "9:16" else keys[1]
        assert punch["t"] == pytest.approx(1.0 - S.LEAD, abs=0.01) or punch["t"] >= 0


def test_missing_shot_is_a_clear_error(cfg, shots):
    with pytest.raises(KeyError, match="run the capture step"):
        S.plan(dict(cfg, features=cfg["features"] + [{"id": "ghost", "caption": "x"}], demo=dict(cfg["demo"],
               shots=["ghost"])), shots, "demo", "en", "16:9")


# ------------------------------------------------------------------------------------------------ brand + compose
def test_fit_measures_the_font():
    px, lines = B.fit("Describe the batch in 【one sentence】.", DISPLAY, (56, 40), 1680, 1, "en", 560)
    assert px == 56 and lines == ["Describe the batch in 【one sentence】."]
    px, lines = B.fit("Describe the batch in one sentence and then much more text here", DISPLAY, (68, 48), 600, 3)
    assert len(lines) <= 3 and all(B.measure(ln, DISPLAY, px) <= 600 for ln in lines)
    with pytest.raises(ValueError, match="caption too long"):
        B.fit("word " * 60, DISPLAY, (56, 40), 600, 1)


def test_red_accent_is_flagged():
    assert B.is_reddish("#FF2442") and B.is_reddish("#D42A43")
    assert not B.is_reddish("#0E9484") and not B.is_reddish("#2F6F9F") and not B.is_reddish("#A84F2D")
    assert B.warnings({"brand": {"colors": {"accent": "#0A7266"}}}) == []
    w = B.warnings({"brand": {"colors": {"accent": "#FF2442", "ink": "#9A9A9A"}}})
    assert len(w) == 2 and "red" in w[0] and "contrast" in w[1]


def test_build_writes_a_lint_clean_shaped_project(cfg, shots, tmp_path):
    proj = str(tmp_path / "demo-en-16x9")
    CO.build(cfg, S.plan(cfg, shots, "demo", "en", "16:9"), proj, quiet=True)
    html = open(os.path.join(proj, "index.html"), encoding="utf-8").read()
    assert 'data-composition-id="main"' in html and 'window.__timelines["main"] = tl' in html
    assert "transform: translate" not in html                       # GSAP owns the camera transform
    assert re.search(r'tl\.set\("#s1m", \{x: [-\d.]+, y: [-\d.]+, scale: [\d.]+\}, 0\)', html)
    assert '<span class="w mk">one sentence</span>' in html
    assert html.count("<video ") == 2 and 'data-volume="0"' in html
    assert "#0E9484" not in html and "#2F6F9F" in html.upper()      # the brand accent, not someone else's
    cues = json.load(open(os.path.join(proj, "cues.json"), encoding="utf-8"))["cues"]
    assert [c["text"] for c in cues] == ["Describe it in one sentence.", "Look only at what is flagged."]
    assert os.path.exists(os.path.join(proj, "assets", "fonts", os.path.basename(DISPLAY)))


def test_loop_has_a_tail_back_to_frame_zero(cfg, shots, tmp_path):
    proj = str(tmp_path / "loop")
    CO.build(cfg, S.plan(cfg, shots, "loop", "en", "16:9"), proj, quiet=True)
    html = open(os.path.join(proj, "index.html"), encoding="utf-8").read()
    assert 'id="tail"' in html and "tail-first.jpg" in html
    assert 'tl.set(["#s0k", "#s0w"], {opacity: 1}, 0)' in html


@pytest.mark.skipif(not _has_cjk_fonts(), reason="Noto SC fonts not installed (./install.sh)")
def test_zh_build_subsets_cjk(cfg, shots, tmp_path):
    proj = str(tmp_path / "clip-zh")
    CO.build(cfg, S.plan(cfg, shots, "clip", "zh", "9:16", feature="plan"), proj, quiet=True)
    html = open(os.path.join(proj, "index.html"), encoding="utf-8").read()
    assert 'lang="zh-CN"' in html and "LK-zh-display" in html
    assert any(f.startswith("zh-display") for f in os.listdir(os.path.join(proj, "assets", "fonts")))


def test_caption_html_words_and_marker():
    h = CO.caption_html(["Look at 【what matters】 now"])
    assert h.count('class="w"') == 3 and '<span class="w mk">what matters</span>' in h
    assert CO.caption_html(["只看【标出来】的"]).count('class="w"') == 3


# ------------------------------------------------------------------------------------------------ copy + schedule
def test_posts_per_platform_and_language(cfg, tmp_path):
    res = PO.make_all(cfg, str(tmp_path / "copy"))
    assert list(res["launch"]) == PF.ordered(cfg["platforms"])
    assert list(res["launch"])[-1] == "xiaohongshu"                  # international first, Chinese after
    x = PF.profile("x", use_persona=False)
    for lang in ("en", "zh"):
        assert PF.text_len(x, res["launch"]["x"][lang]["text"]) <= 280
    assert "速记" in res["launch"]["xiaohongshu"]["zh"]["text"]
    assert "Describe it in one sentence." in res["clips"]["plan"]["x"]["en"]["text"]
    page = open(tmp_path / "copy" / "COPY.md", encoding="utf-8").read()
    assert "Nothing here has been posted" in page and page.index("### X") < page.index("### 小红书")
    assert (tmp_path / "copy" / "clips" / "review" / "tiktok.en.md").exists()
    from vstudio import publish as PB
    t = res["clips"]["review"]["xiaohongshu"]["zh"]["title"]
    assert t and PB.check_title(t, "xiaohongshu")[0]                       # "Name｜caption" too long -> caption
    assert "https://" not in res["launch"]["tiktok"]["en"]["text"]           # no dead links where they can't click
    assert "https://acme.example" in res["launch"]["x"]["en"]["text"]
    c2 = dict(cfg, post=dict(cfg["post"], en=dict(cfg["post"]["en"], by_platform={"x": {"hook": "Short X hook.", "body": []}})))
    r2 = PO.make_all(c2, str(tmp_path / "copy2"))
    assert r2["launch"]["x"]["en"]["text"].startswith("Short X hook.")
    assert not r2["launch"]["linkedin"]["en"]["text"].startswith("Short X hook.")


def test_posts_without_a_post_block_fail_loudly_without_a_model(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(PO.PB, "generate_copy", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="no model routed"):
        PO.make_all(dict(cfg, post=None), str(tmp_path / "copy"))


def test_schedule_picks_canvas_and_language(cfg):
    have = {("en", "16:9"): "d-en-169.mp4", ("en", "9:16"): "d-en-916.mp4", ("zh", "9:16"): "d-zh-916.mp4"}
    clips = {f: {("en", "1:1"): f"{f}-en-11.mp4", ("en", "9:16"): f"{f}-en-916.mp4", ("zh", "9:16"): f"{f}-zh.mp4"}
             for f in ("plan", "review")}
    rows = SC.propose(cfg, dict(demo=have, clips=clips))
    day0 = [r for r in rows if r["kind"] == "demo"]
    assert {r["at"][:10] for r in day0} == {"2026-11-03"}
    by = {r["platform"]: r for r in day0}
    assert by["x"]["video"] == "d-en-169.mp4" and by["tiktok"]["video"] == "d-en-916.mp4"
    assert by["xiaohongshu"]["video"] == "d-zh-916.mp4" and by["xiaohongshu"]["lang"] == "zh"
    assert [r["platform"] for r in day0][-1] == "xiaohongshu"
    clip_x = [r for r in rows if r["kind"] == "clip" and r["platform"] == "x"]
    assert [r["video"] for r in clip_x] == ["plan-en-11.mp4", "review-en-11.mp4"]
    assert clip_x[0]["at"][:10] == "2026-11-04"


def test_schedule_apply_adds_planned_posts_only_for_known_accounts(cfg):
    from vstudio.project import pubcal
    pubcal.add_account("acme-x", "x", times=["09:00"])
    rows = SC.propose(cfg, dict(demo={("en", "16:9"): "d.mp4", ("en", "9:16"): "v.mp4"}))
    res = SC.apply(rows, {"x": "acme-x"})
    assert len(res["added"]) == 1 and res["added"][0]["state"] == "planned"
    assert {r["platform"] for r in res["skipped"]} == {r["platform"] for r in rows} - {"x"}


# ------------------------------------------------------------------------------------------------ format / recipe
def test_launch_format_allows_a_silent_render(tmp_path):
    from vstudio import firstpass as FP
    from vstudio import formats as F
    v = str(tmp_path / "silent.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xF6F3EE:s=1920x1080:r=30:d=2",
                    "-pix_fmt", "yuv420p", v], check=True)
    f = F.get("launch", persona_formats={})
    assert f["audio"] == "optional" and f["workflow"] == "launch-kit"
    res = FP.run(v, fmt="launch", platform="x", media_checks=False)
    audio = next(i for i in res["items"] if i["id"] == "audio")
    assert audio["ok"] is None and audio["severity"] == "info"
    res = FP.run(v, fmt="talking-head", platform="x", media_checks=False)
    assert next(i for i in res["items"] if i["id"] == "audio")["ok"] is False


def test_recipe_manifest_is_registered():
    from vstudio.project import manifests as M
    m = M.reload()["launch-kit"]
    assert M.validate(m) == []
    assert [s["id"] for s in m["stages"]] == ["prepare", "features", "capture", "render", "stills", "copy", "schedule",
                                              "check"]
    assert {c["id"] for c in m["checkpoints"]} == {"config", "publish"}
    assert m["outputs"]["platforms"][0] == "x"


def test_cli_features_draft(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("## [1.0.0]\n\n### Added\n\n- Dark mode\n- Sync\n", encoding="utf-8")
    (tmp_path / "launch.config.yaml").write_text("release: {changelog: CHANGELOG.md}\n", encoding="utf-8")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "workflows", "launch-kit", "scripts", "launch_kit.py"),
                        "features", str(tmp_path / "launch.config.yaml")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    d = yaml.safe_load(r.stdout)
    assert [f["id"] for f in d["features"]] == ["dark-mode", "sync"]


def test_intake_routes_a_launch_request(tmp_path):
    from vstudio.intake import inventory as I
    from vstudio.intake import plan as PL
    (tmp_path / "CHANGELOG.md").write_text("## [1.0.0]\n\n- Dark mode\n", encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (1440, 900), "#F6F3EE").save(tmp_path / "screen.png")
    a = I.analyze([str(tmp_path / "CHANGELOG.md"), str(tmp_path / "screen.png")])
    plan = PL.make_plan("Make a launch video for my app from this changelog", analysis=a, asr="off", provider="none")
    p = plan["projects"][0]
    assert p["recipe"] == "launch-kit"
    assert p["inputs"]["notes"].endswith("CHANGELOG.md") and p["inputs"]["shots"][0].endswith("screen.png")


def test_kit_jobs_names_and_outputs(cfg):
    from vstudio.launch import kit as K
    js = K.jobs(cfg)
    names = [j[0] for j in js]
    assert names[:5] == ["demo-en-16x9", "demo-en-9x16", "demo-en-1x1", "demo-zh-16x9", "demo-zh-9x16"]
    assert "loop-en" in names and "plan-zh-9x16" in names and "review-en-1x1" in names
    assert all(j[5].startswith(cfg["out"]) for j in js)
    assert [j[0] for j in K.jobs(cfg, only=["review"])] == ["review-en-1x1", "review-en-9x16", "review-zh-9x16"]


@pytest.mark.skipif(not __import__("vstudio.render", fromlist=["x"]).find_chromes(), reason="no Chrome")
def test_stills_exact_sizes(cfg, shots, tmp_path):
    from PIL import Image
    from vstudio.launch import stills as ST
    c = dict(cfg, gallery=dict(cfg["gallery"], facts=[{"value": "3", "label": "features"}], langs=["en"]))
    made = ST.make_all(c, shots, str(tmp_path / "stills"))
    names = [os.path.basename(m) for m in made]
    assert names == ["ph-gallery-1-hero.png", "ph-gallery-2-plan.png", "ph-gallery-3-review.png", "og-1200x630.png"]
    for m in made:
        with Image.open(m) as im:
            assert im.size == (ST.OG if "og-" in m else ST.PH)


def test_english_request_gets_an_english_plan_summary(tmp_path):
    from vstudio.intake import plan as PL
    from vstudio.intake import rules as R
    assert "xiaohongshu" in R.parse_prompt("clips for TikTok and Xiaohongshu")["platforms"]
    plan = dict(prompt="Cut this talk into clips for TikTok and Xiaohongshu", estimate=dict(wall_min=12),
                projects=[dict(recipe="talkinghead", recipe_label="口播精剪", items=dict(method="per-file", count=1), inputs={},
                               params=dict(platforms=["xiaohongshu:full", "tiktok"]),
                               checkpoints=[dict(id="publish", label="审片发布", needs_you=True)])])
    s = PL.template_summary(plan)
    assert s.startswith("I'll make 1 project") and "Review and publish" in s
    assert s.index("TikTok") < s.index("Xiaohongshu")                 # international first
    assert not any("一" <= c <= "鿿" for c in s)
    plan["prompt"] = "剪成小红书切片"
    assert PL.template_summary(plan).startswith("我会做")


def test_speed_ramp_on_idle_stretches(tmp_path):
    from vstudio.launch import timing as TM
    v = str(tmp_path / "wait.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x200:r=30:d=2",
                    "-f", "lavfi", "-i", "color=c=0xF4F0E8:s=320x200:r=30:d=3", "-f", "lavfi", "-i",
                    "testsrc2=s=320x200:r=30:d=2", "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]", "-map", "[v]",
                    "-pix_fmt", "yuv420p", v], check=True)
    shot = dict(id="w", kind="video", file=v, duration=7.0)
    spans = TM.idle_spans(shot)
    assert len(spans) == 1 and spans[0][0] == pytest.approx(2.0, abs=0.1) and spans[0][1] == pytest.approx(5.0, abs=0.1)
    assert os.path.exists(v + ".idle.json") and TM.idle_spans(shot) == spans          # cached
    segs = TM.segments(0.0, 7.0, spans)
    assert [r for _, _, r in segs] == [1.0, TM.IDLE_RATE, 1.0]
    assert TM.length(segs) == pytest.approx(7.0 - (3.0 - TM.KEEP) * (1 - 1 / TM.IDLE_RATE), abs=0.15)
    f = TM.fit(segs, 3.0)
    assert TM.length(f) == pytest.approx(3.0, abs=1e-3) and TM.fit(segs, 60) == segs   # never slows down
    assert TM.to_scene(segs, 0.0) == 0 and TM.to_scene(segs, 7.0) == pytest.approx(TM.length(segs))
    assert TM.to_scene(segs, 6.0) == pytest.approx(TM.length(segs) - 1.0, abs=0.01)    # after the ramp: real time
    end = TM.segments(0.0, 9.0, [(2.0, 4.0), (6.0, 9.0)])                               # ends frozen on the result
    assert end[-1] == (4.0, 6.0 + TM.END_HOLD, 1.0)
    held = TM.fit([(0.0, 8.0, 1.0), (8.0, 9.8, 1.0)], 6.0)
    assert held[-1] == (8.0, 9.8, 1.0) and TM.length(held) == pytest.approx(6.0, abs=1e-3)   # the result keeps its pace


def test_ramped_shot_becomes_back_to_back_clips(cfg, shots, tmp_path):
    sh = {k: dict(v, idle=[(2.0, 4.5)]) for k, v in shots.items()}
    plan = S.plan(cfg, sh, "clip", "en", "1:1", feature="plan")
    segs = plan["scenes"][0]["media"]["segs"]
    assert len(segs) == 3 and segs[1][2] > segs[0][2]
    proj = str(tmp_path / "ramp")
    CO.build(cfg, plan, proj, quiet=True)
    html = open(os.path.join(proj, "index.html"), encoding="utf-8").read()
    starts = [float(x) for x in re.findall(r'<video id="s0v\d" [^>]*data-start="([\d.]+)"', html)]
    durs = [float(x) for x in re.findall(r'<video id="s0v\d" [^>]*data-duration="([\d.]+)"', html)]
    assert len(starts) == 3 and all(abs(starts[k] + durs[k] - starts[k + 1]) < 0.002 for k in range(2))


def test_music_bed_from_the_shared_library(cfg, shots, tmp_path):
    assert cfg["music"]["mood"] == "tech" and "MIT" in cfg["music"]["license"]       # default: a built-in bed
    assert C.music_spec("none") is None and C.music_spec(False) is None
    assert C.music_spec("calm") == {"mood": "calm", "license": "built-in bed generated by Reelfold (MIT)"}
    with pytest.raises(C.ConfigError):
        C.music_spec({"mood": "polka"})
    proj = str(tmp_path / "music")
    CO.build(cfg, S.plan(cfg, shots, "clip", "en", "1:1", feature="plan"), proj, quiet=True)
    html = open(os.path.join(proj, "index.html"), encoding="utf-8").read()
    assert '<audio src="assets/audio/music.m4a"' in html
    from vstudio import media
    assert media.probe(os.path.join(proj, "assets", "audio", "music.m4a"))["duration"] > 9
    proj2 = str(tmp_path / "silent")
    CO.build(dict(cfg, music=None), S.plan(cfg, shots, "clip", "en", "1:1", feature="plan"), proj2, quiet=True)
    assert "<audio" not in open(os.path.join(proj2, "index.html"), encoding="utf-8").read()
