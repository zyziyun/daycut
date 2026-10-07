"""Run every test against persona.example.yaml defaults, never the creator's private persona.local.yaml."""
import os

os.environ["VSTUDIO_DEFAULT_PERSONA"] = "1"

# v0.2 client workspaces / batch registry: never touch the real ~/.config/vstudio from tests
import tempfile  # noqa: E402

os.environ.setdefault("VSTUDIO_HOME", tempfile.mkdtemp(prefix="vstudio-home-"))

# CLI lookup: PATH only (tests mock shutil.which; the real ~/.local/bin/claude must not be found)
os.environ["VSTUDIO_CLI_EXTRA_DIRS"] = ""


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_auth_cache(tmp_path, monkeypatch):
    """vstudio.llm_auth keeps known-expired logins in a cache file: one per test, so no test sees another's."""
    monkeypatch.setenv("VSTUDIO_AUTH_CACHE", str(tmp_path / "auth-cache.json"))
