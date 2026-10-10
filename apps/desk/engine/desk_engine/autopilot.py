"""Autopilot in the desk: what the engine decided for a project, taking one decision back, and switching a project
between autopilot and "ask me first" (``python -m vstudio.project decisions | reopen | autopilot``, the engine's
references/PROJECTS.md section 3).

  GET  /api/autopilot/<item>              {supported, autopilot {on, spend_cap, judge, lang, ask}, decisions [...],
                                           running, queued}
  POST /api/autopilot/<item>/reopen {checkpoint, item}   the decision goes back to her: the project runs on to that
                                           checkpoint and stops there (the Inbox asks) -> {ok, rerun}
  POST /api/autopilot/<item>/mode {on}    switch; turning autopilot on also continues a project that waits (its
                                           questions are then decided by the engine) -> {ok, autopilot, resumed}
  POST /api/autopilot/<item>/change {checkpoint, item, answer {approve, keep}}   she changes one taste call in place
                                           (the clip editor's Undo / Change on a decision): her answer replaces the
                                           engine's, the affected stages re-run -> {ok, resumed, rerun}

The taste calls (the unsure filler cuts, the opening) come with their options in the inbox's plain-language shape,
each ``checked`` as decided, so the editor can show them as made decisions with Undo / Change per option.

Only recipe projects (``project.yaml``) have checkpoints to decide; other folders answer ``supported: false``.
"""
import json
import os

from . import inbox_labels as L
from . import pilot
from .common import BadRequest, need, read_json

# decisions the editor lists per clip, with their options (the others are listed on the project page as before)
TASTE = ("filler-confirm", "hook-pick")


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
        decs = [dict(x, options=options(x)) if x.get("kind") in TASTE else x for x in doc.get("decisions") or []]
        return dict(base, supported=True, autopilot=doc.get("autopilot"), decisions=decs)

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

    def change(self, item, checkpoint, sub, answer):
        """Her answer to one taste call the engine made (keep a cut it made, make one it kept, another opening): it
        replaces the auto-answer (the decision is hers from now on, the log keeps the engine's) and the project runs
        the stages it affects again in the background."""
        need(isinstance(checkpoint, str) and 0 < len(checkpoint) <= 60, "checkpoint: the decision's checkpoint id")
        need(isinstance(sub, str) and 0 < len(sub) <= 120, "item: the clip's item id")
        need(isinstance(answer, dict) and isinstance(answer.get("approve"), list) and len(answer["approve"]) <= 200,
             "answer: {approve: [option ids], keep: [option ids]}")
        _e, d, ok = self._project(item)
        need(ok, "only a recipe project has decisions to change")
        if pilot.running(d):
            raise BadRequest("the project is running; change this when it has finished")
        doc = self._cli().json(["decisions", "--dir", d, "--json"], timeout=60)
        dec = next((x for x in doc.get("decisions") or [] if x.get("checkpoint") == checkpoint and
                    x.get("item") == sub and not x.get("asked")), None)
        need(dec is not None, f"no decision {checkpoint} for {sub}")
        from .inbox import engine_answer
        value = engine_answer(dec.get("kind"), answer)
        need(value is not None, "answer: pick one option")
        r = self._cli().json(["checkpoint", "--dir", d, "--id", checkpoint, "--item", sub, "--answer",
                              json.dumps(value), "--json"], timeout=120)
        resumed = self._resume(d)
        if self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")
        return dict(ok=True, resumed=resumed, rerun=(r or {}).get("rerun") if isinstance(r, dict) else None)

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


def options(dec):
    """A taste decision's options (from the checkpoint payload the engine showed its judge) in the inbox's shape,
    ``checked`` = what the engine decided: a filler cut it made, the opening it picked (none: no cold open). A filler
    option carries the words around it (``ctx``, inbox_labels.engine_option) so the editor finds it in the clip."""
    pay = read_json(dec.get("payload"), None) if dec.get("payload") else None
    if not isinstance(pay, dict):
        return []
    v = dec.get("value") if isinstance(dec.get("value"), dict) else {}
    cut = {str(x) for x in v.get("approve") or []}
    out = []
    for i, o in enumerate([o for o in pay.get("options") or [] if isinstance(o, dict)][:60]):
        opt = L.engine_option(o, pay.get("default"), i)
        if dec.get("kind") == "filler-confirm":
            opt["checked"] = opt["id"] in cut
        else:
            opt["checked"] = str(i) == str(v.get("pick"))
            opt["kind"] = "opening"
        out.append(opt)
    return out
