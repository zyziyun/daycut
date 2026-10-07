"""preproduction lint (restored script-voice rules) + scripts/check_skill.py. Pure text, no media, no network."""
import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINT = ROOT / "workflows/preproduction/scripts/lint_script.py"
EXAMPLE = ROOT / "workflows/preproduction/examples/script.example.md"


def lint(path, *args):
    r = subprocess.run([sys.executable, str(LINT), str(path), *args], capture_output=True, text=True)
    return r.returncode, r.stdout


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_example_script_has_no_errors():
    code, out = lint(EXAMPLE, "--strict")
    assert code == 0, out
    assert "ERROR" not in out


def test_restored_en_rules(tmp_path):
    s = tmp_path / "bad.md"
    s.write_text(
        "## HOOK\n"
        "    You pay for parking every day. Most of that fee is set by one survey. The survey is twelve years old.\n"
        "## BODY\n"
        "    In this video we'll cover how the price is set. Don't worry if this sounds odd at first. "
        "So what I want to say is that the survey counts cars on a single Tuesday.\n"
        "## CLOSE\n"
        "    Next time a meter feels expensive, ask which Tuesday it was priced on.\n", encoding="utf-8")
    code, out = lint(s, "--strict", "--lang", "en")
    assert code == 1
    assert "self-narration about the medium: 'in this video'" in out
    assert "self-narration about the medium: 'we'll cover'" in out
    assert "filler reassurance: 'don't worry if'" in out
    assert "padding (cut it): 'so what i want to say is'" in out


def test_restored_zh_reassurance(tmp_path):
    s = tmp_path / "zh.md"
    s.write_text("    停车费其实是按一次调查定的。别担心，听起来有点复杂，其实说白了就是数车。"
                 "那次调查只在一个周二做过。下次觉得贵，可以问问是哪个周二定的价。\n", encoding="utf-8")
    code, out = lint(s, "--strict")
    assert code == 1
    assert "filler reassurance: '别担心'" in out
    assert "filler reassurance: '听起来有点复杂'" in out


def test_script_craft_keeps_restored_sections():
    t = (ROOT / "workflows/preproduction/references/script_craft.md").read_text(encoding="utf-8")
    for needle in ("## 0. Scope and stance", "### What to cut", "Pre-lock self-check", "three rungs",
                   "Pattern C (concrete action", "most explanations skip"):
        assert needle in t, needle


def test_sop_exists_and_points_at_shared_tools():
    t = (ROOT / "references/SOP_SHORT_VIDEO.md").read_text(encoding="utf-8")
    for needle in ("python -m vstudio.cleanup", "python -m vstudio.export", "lint_script.py", "make_drill.py",
                   "render_slides.py", "polish.py", "Descript", "## Time budget"):
        assert needle in t, needle
    assert "/" + "Users/" not in t and "~/" + "Desktop" not in t


def test_check_skill_helpers():
    cs = _load(ROOT / "scripts/check_skill.py", "check_skill")
    errs, warns = [], []
    cs.check_frontmatter("---\nname: my-skill\ndescription: short\n---\n# x\n", errs, warns)
    assert errs == [] and warns == []
    errs = []
    cs.check_frontmatter("# no frontmatter\n", errs, warns)
    assert errs and "frontmatter" in errs[0]
    errs = []
    cs.check_frontmatter("---\nname: Bad Name\ndescription: " + "x" * 1100 + "\n---\n", errs, warns)
    assert len(errs) == 2
    assert [c for _, c, _ in cs.emoji_hits("ok -> x ▶ ✓\nhi 🚀 there")] == ["🚀"]
    home, desk = "/" + "Users/", "~/" + "Desktop"          # split so this file doesn't trip the repo scan
    assert cs.personal_path_hits(f"see {home}someone/x and {home}.../y")[0][1] == home + "someone/"
    assert len(cs.personal_path_hits(f"{home}.../y")) == 0
    assert cs.personal_path_hits(desk + "/foo", soft=True) and not cs.personal_path_hits(desk + "/...", soft=True)
    assert not cs.personal_path_hits(f"{home}me/Movies/a.mp4") and not cs.personal_path_hits(f"{home}someone/x  (check-skill: allow)")
    fake = "sk" + "-proj-" + "A1b2C3d4" * 4                 # split so this file doesn't trip the repo scan
    assert cs.secret_hits(f"key = '{fake}'") and not cs.secret_hits("OPENAI_API_KEY=sk-...  xxxx-xxxx-xxxx-xxxx")
    assert cs.SECRET_FILES.search(".env") and cs.SECRET_FILES.search("DeveloperID.p12") and not cs.SECRET_FILES.search("env.ts")


def test_check_skill_repo_clean():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/check_skill.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
