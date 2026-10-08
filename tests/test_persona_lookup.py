"""persona() lookup: the desktop app's bundled runtime has no persona.local.yaml next to its code, so the creator's
private persona is also read from the Claude Code skill checkout and from $VSTUDIO_HOME. Never touches real files:
HOME, VSTUDIO_HOME and the repo root are temp dirs."""
import os
import shutil

import pytest

from vstudio import config


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "bundle"
    repo.mkdir()
    shutil.copy(os.path.join(config.REPO, "persona.example.yaml"), repo / "persona.example.yaml")
    home = tmp_path / "home"
    vhome = tmp_path / "vhome"
    skill = home / ".claude" / "skills" / "video-studio"
    for d in (home, vhome, skill):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "REPO", str(repo))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VSTUDIO_HOME", str(vhome))
    monkeypatch.delenv("VSTUDIO_DEFAULT_PERSONA", raising=False)
    monkeypatch.delenv("VSTUDIO_PERSONA", raising=False)
    config.persona.cache_clear()
    yield dict(repo=repo, vhome=vhome, skill=skill, tmp=tmp_path)
    config.persona.cache_clear()


def _write(path, profile, extra=""):
    path.write_text(f"cleanup:\n  profile: {profile}\n{extra}", encoding="utf-8")


def test_defaults_only(env):
    assert config.persona()["cleanup"]["profile"] == "standard"
    assert [os.path.basename(p) for p in config.persona_sources()] == ["persona.example.yaml"]


def test_skill_checkout_persona_is_found_by_bundled_runtime(env):
    _write(env["skill"] / "persona.local.yaml", "tight", "subtitles:\n  term_fixes: {cloud code: Claude Code}\n")
    p = config.persona()
    assert p["cleanup"]["profile"] == "tight"
    assert p["subtitles"]["term_fixes"] == {"cloud code": "Claude Code"}


def test_precedence(env, monkeypatch):
    _write(env["skill"] / "persona.local.yaml", "gentle", "creator:\n  handle: skill\n")
    _write(env["repo"] / "persona.local.yaml", "standard", "creator:\n  name: repo\n")
    assert config.persona()["cleanup"]["profile"] == "standard"         # repo > skill
    assert config.persona()["creator"]["handle"] == "skill"             # merged per key
    _write(env["vhome"] / "persona.local.yaml", "tight")
    config.persona.cache_clear()
    p = config.persona()
    assert p["cleanup"]["profile"] == "tight"                           # $VSTUDIO_HOME > repo
    assert p["creator"]["name"] == "repo"
    explicit = env["tmp"] / "explicit.yaml"
    _write(explicit, "gentle")
    monkeypatch.setenv("VSTUDIO_PERSONA", str(explicit))
    config.persona.cache_clear()
    assert config.persona()["cleanup"]["profile"] == "gentle"           # $VSTUDIO_PERSONA > everything
    assert config.persona_sources()[-1] == str(explicit)


def test_default_persona_flag_skips_private_files(env, monkeypatch):
    _write(env["skill"] / "persona.local.yaml", "tight")
    _write(env["vhome"] / "persona.local.yaml", "tight")
    monkeypatch.setenv("VSTUDIO_DEFAULT_PERSONA", "1")
    config.persona.cache_clear()
    assert config.persona()["cleanup"]["profile"] == "standard"


def test_same_file_twice_is_merged_once(env, monkeypatch):
    os.symlink(env["skill"], env["tmp"] / "link")
    _write(env["skill"] / "persona.local.yaml", "tight")
    monkeypatch.setattr(config, "REPO", str(env["tmp"] / "link"))
    shutil.copy(env["repo"] / "persona.example.yaml", env["skill"] / "persona.example.yaml")
    srcs = config.persona_sources()
    assert len([s for s in srcs if s.endswith("persona.local.yaml")]) == 1
