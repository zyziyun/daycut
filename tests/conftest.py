"""Run every test against persona.example.yaml defaults, never the creator's private persona.local.yaml."""
import os

os.environ["VSTUDIO_DEFAULT_PERSONA"] = "1"

# v0.2 client workspaces / batch registry: never touch the real ~/.config/vstudio from tests
import tempfile  # noqa: E402

os.environ.setdefault("VSTUDIO_HOME", tempfile.mkdtemp(prefix="vstudio-home-"))

# CLI lookup: PATH only (tests mock shutil.which; the real ~/.local/bin/claude must not be found)
os.environ["VSTUDIO_CLI_EXTRA_DIRS"] = ""
