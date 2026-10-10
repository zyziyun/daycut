"""Test fixture (fewerSteps e2e, real engine): the words of a talkinghead export = the cleaned body's words (its
cleanup sidecar, the engine tests' perfect ASR): the export keeps the body 1:1 here (no cold open, speed 1).
real_project.py --autopilot caches them for the clip editor (vstudio.project.outputs.words)."""
import json
import os


def words(path, language=None):
    job = path.split(os.sep + "export" + os.sep)[0]
    for sub in ("apply", "cleanup"):
        p = os.path.join(job, sub, "body.cleanup.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return [dict(w=w["w"], t=w["t"], te=w["te"]) for w in json.load(f)["words"]]
    raise RuntimeError(f"no cleanup sidecar for {path}")
