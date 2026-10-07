"""The built-in sample recording behind "Try with a sample" (first run and Home).

A ~2-minute narrated screen lesson made by the Reelfold project (no camera, no people, CC0; packaging/sample/,
rebuilt by scripts/sample/make_sample.py) ships inside the app. It goes through the same real pipeline as her own
footage (ASR, cleanup, captions, export); the only differences are that the file is copied out of the read-only app
bundle first (the engine writes caches next to its inputs) and that the projects made from it are marked as a
sample, so the desk can label them and delete them in one click.

    GET  /api/sample            -> {available, path, duration, size, licence}
    POST /api/sample/remove     {dir} -> {ok, removed}   (only a project marked as a sample, under VSTUDIO_HOME)
"""
import json
import os
import shutil
import time

from .common import need, write_json

FILE = "reelfold-sample.mp4"
MARKER = os.path.join(".vstudio", "sample.json")


def bundled_dir():
    """<app>/packaging/sample: Resources/packaging/sample in a packaged app, apps/desk/packaging/sample in dev
    (both are the engine folder's sibling)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.environ.get("DESK_SAMPLE_DIR") or os.path.join(os.path.dirname(here), "packaging", "sample")


def is_sample(d):
    return os.path.isfile(os.path.join(d, MARKER))


class Sample:
    def __init__(self, data_dir, home_fn):
        self.dir = os.path.join(data_dir, "sample")
        self.home_fn = home_fn                     # -> VSTUDIO_HOME (where projects live)

    @property
    def path(self):
        return os.path.join(self.dir, FILE)

    def info(self):
        """Copy the bundled sample into the desk data folder (once; again if the bundled one changed)."""
        src = os.path.join(bundled_dir(), FILE)
        if not os.path.isfile(src):
            return dict(available=False)
        os.makedirs(self.dir, exist_ok=True)
        if not os.path.isfile(self.path) or os.path.getsize(self.path) != os.path.getsize(src):
            tmp = self.path + ".part"
            shutil.copyfile(src, tmp)
            os.replace(tmp, self.path)
        meta = {}
        try:
            with open(os.path.join(bundled_dir(), "script.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        return dict(available=True, path=self.path, size=os.path.getsize(self.path), duration=meta.get("duration"),
                    licence="CC0 1.0")

    def uses_sample(self, inputs):
        rp = os.path.realpath(self.path)
        return any(os.path.realpath(p) == rp for p in inputs or [])

    def mark(self, dirs):
        for d in dirs:
            if d and os.path.isdir(d):
                os.makedirs(os.path.join(d, ".vstudio"), exist_ok=True)
                write_json(os.path.join(d, MARKER), dict(sample=True, source=FILE, at=time.time()))

    def remove(self, d):
        """Delete a sample project's folder (and its now-empty plan folder). Refuses anything that is not marked as
        a sample or lives outside VSTUDIO_HOME/projects."""
        need(isinstance(d, str) and os.path.isabs(d), "dir: an absolute path")
        rp = os.path.realpath(d)
        root = os.path.realpath(os.path.join(self.home_fn(), "projects"))
        need(rp.startswith(root + os.sep), "not a project folder")
        need(is_sample(rp), "only the sample project can be deleted here")
        shutil.rmtree(rp)
        parent = os.path.dirname(rp)
        if parent != root and os.path.isdir(parent):
            left = [x for x in os.listdir(parent) if x not in ("intake.json",)]
            if not left:
                shutil.rmtree(parent, ignore_errors=True)
        return dict(ok=True, removed=d)
