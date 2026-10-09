"""Autopilot in the desk: what the engine decided for a project, taking one decision back, and switching a project
between autopilot and "ask me first" (``python -m vstudio.project decisions | reopen | autopilot``, the engine's
references/PROJECTS.md section 3).

  GET  /api/autopilot/<item>              {supported, autopilot {on, spend_cap, judge, lang, ask}, decisions [...],
                                           running, queued}
  POST /api/autopilot/<item>/reopen {checkpoint, item}   the decision goes back to her: the project runs on to that
                                           checkpoint and stops there (the Inbox asks) -> {ok, rerun}
  POST /api/autopilot/<item>/mode {on}    switch; turning autopilot on also continues a project that waits (its
                                           questions are then decided by the engine) -> {ok, autopilot, resumed}

Only recipe projects (``project.yaml``) have checkpoints to decide; other folders answer ``supported: false``.
"""
import os

from . import pilot
from .common import BadRequest, need


class Autopilot:
    def __init__(self, history, runner, bus=None, intake=None):
        self.history, self.runner, self.bus = history, runner, bus

    def _project(self, item):
        e = self.history.find(item)
        d = e.get("dir") or ""
        return e, d, e.get("kind") == "project" and os.path.isfile(os.path.join(d, "project.yaml"))

    def _cli(self):
        need(self.runner is not None, "the engine is not available")
        return self.runner.sibling("vstudio.project")

    def get(self, item):
        e, d, ok = self._project(item)
        base = dict(item=item, running=bool(pilot.running(d)) if d else False, queued=pilot.queued(d) if d else None)
        if not ok:
            return dict(base, supported=False, autopilot=None, decisions=[])
        doc = self._cli().json(["decisions", "--dir", d, "--json"], timeout=60)
        return dict(base, supported=True, autopilot=doc.get("autopilot"), decisions=doc.get("decisions") or [])

    def _resume(self, d, autopilot=None):
        """Continue the project in the background (unless it runs / waits in line already)."""
        if pilot.running(d) or pilot.queued(d):
            return False
        py = self.runner.python
        args = [py, "-m", "vstudio.project", "resume", "--dir", d, "--json-events"]
        if autopilot is True:
            args.insert(-1, "--autopilot")
        pilot.spawn(py, self.runner.env, d, bus=self.bus, args=args)
        return True

    def reopen(self, item, checkpoint, sub="*"):
        need(isinstance(checkpoint, str) and 0 < len(checkpoint) <= 60, "checkpoint: the decision's checkpoint id")
        need(isinstance(sub, str) and 0 < len(sub) <= 120, "item: the clip's item id (or *)")
        _e, d, ok = self._project(item)
        need(ok, "only a recipe project has decisions to take back")
        if pilot.running(d):
            raise BadRequest("the project is running; take this back when it has finished")
        r = self._cli().json(["reopen", "--dir", d, "--id", checkpoint, "--item", sub, "--json"], timeout=120)
        resumed = self._resume(d)
        if self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")
        return dict(r if isinstance(r, dict) else {}, ok=True, resumed=resumed)

    def mode(self, item, on):
        need(isinstance(on, bool), "on: true (autopilot) or false (ask me first)")
        _e, d, ok = self._project(item)
        need(ok, "only a recipe project can switch to autopilot")
        doc = self._cli().json(["autopilot", "--dir", d, "--on" if on else "--off", "--json"], timeout=60)
        resumed = False
        if on:                                     # her questions waiting in it are now the engine's to decide
            st = self._cli().json(["status", "--dir", d, "--brief", "--json"], timeout=120)
            if isinstance(st, dict) and st.get("state") in ("needs-you", "planned", "paused", "interrupted", "new"):
                resumed = self._resume(d, autopilot=True)
        if self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")
        return dict(ok=True, autopilot=(doc or {}).get("autopilot"), resumed=resumed)
