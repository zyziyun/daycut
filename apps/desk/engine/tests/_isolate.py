"""Imported first by every test module: per-user stores go to a throwaway folder.

The engine registers every planned batch in ``$VSTUDIO_HOME/batches.json`` (default ``~/.config/vstudio``) and keeps
clients under ``$VSTUDIO_HOME/clients``; the desk keeps its registry under ``$DESK_DATA_DIR`` (default
``~/.vstudio-desk``). Without this, test batches in temp folders ended up in the user's real registry. The variables
are set in ``os.environ`` so engine subprocesses (``python -m vstudio.batch ...``) inherit them too.
"""
import atexit
import os
import shutil
import sys
import tempfile

# test this checkout's engine: an editable install elsewhere (e.g. another worktree) must not shadow it, here or in the
# engine subprocesses the tests start (PYTHONPATH comes before .pth entries)
_REPO_LIB = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "lib"))
sys.path.insert(0, _REPO_LIB)
os.environ["PYTHONPATH"] = os.pathsep.join([_REPO_LIB] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])

# the test engine (fake batches, rule plans, fake Create services) lives here, never in desk_engine
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))

ROOT = tempfile.mkdtemp(prefix="desk-engine-tests-")
HOME = os.path.join(ROOT, "vstudio-home")
DATA = os.path.join(ROOT, "desk-data")
for d in (HOME, DATA):
    os.makedirs(d, exist_ok=True)

os.environ["VSTUDIO_HOME"] = HOME
os.environ["VSTUDIO_CLIENTS"] = os.path.join(HOME, "clients")
os.environ["DESK_DATA_DIR"] = DATA
os.environ["DESK_HISTORY_WATCH"] = ""          # never scan the real ~/Desktop/video-studio-demos  (check-skill: allow)
os.environ.setdefault("VSTUDIO_BATCH_BENCH", os.path.join(ROOT, "bench.json"))
# the creator's private persona (skill checkout / $VSTUDIO_HOME) must not change test expectations (AI routes, speeds)
os.environ["VSTUDIO_DEFAULT_PERSONA"] = "1"

atexit.register(shutil.rmtree, ROOT, True)
