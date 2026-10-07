"""Project-level 「让 AI 改」 (projask.py): every clip of the project page in one request, grouped cards, the fast
needs_rerender answer for burned-in text on flattened clips (no model), staged progress, Cancel kills the engine
process group (and the model CLI it started), the timeout -> fallback notice and the watchdog."""
import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402
from desk_engine import projask as PA  # noqa: E402
from desk_engine.common import BadRequest, EventBus, Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from test_v04 import make_fuye  # noqa: E402


def _wait(fn, t=8.0):
    t0 = time.time()
    while time.time() - t0 < t:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                                   # a zombie is dead too
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


class ProjectAskTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.watch = os.path.join(self.root, "demos")
        self.d = make_fuye(self.watch)
        os.makedirs(os.path.join(self.d, "work"), exist_ok=True)
        with open(os.path.join(self.d, "work", "clipdefs.py"), "w", encoding="utf-8") as f:
            f.write('CLIPS = dict(\n  A=dict(kicker="副业复盘"),\n)\n')
        self.env = mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": self.watch,
                                                "VSTUDIO_HOME": os.path.join(self.root, "home")})
        self.env.start()
        data = os.path.join(self.root, "desk")
        self.h = History(data, Registry(data))
        self.bus = EventBus()
        self.o = OU.Outputs(data, self.h, bus=self.bus)
        self.pa = PA.ProjectAsk(self.o, self.bus)
        self.item = next(r["id"] for r in self.h.list()["items"] if r["dir"] == self.d)

    def tearDown(self):
        self.env.stop()

    def _done(self, job):
        return _wait(lambda: (lambda j: j if j["state"] != "running" else None)(self.pa.get(job)))

    def test_classifier(self):
        c = PA.classify("把副业复盘01，02，03都去掉，这不是一组视频，是单独放的")
        self.assertEqual((c["kind"], c["stems"]), ("text-remove", ["副业复盘"]))
        self.assertEqual(PA.classify("字幕再大一点")["kind"], "caption-restyle")
        for t in ("去掉开头3秒", "把停顿都去掉", "再紧凑一点", "1.2倍速"):
            self.assertIsNone(PA.classify(t)["kind"], t)

    def test_burned_text_on_every_clip_needs_rerender_fast(self):
        t0 = time.time()
        job = self.pa.start(self.item, "把副业复盘01，02，03都去掉，这不是一组视频，是单独放的")["job"]
        j = self._done(job)
        self.assertLess(time.time() - t0, 2.0)
        r = j["result"]
        self.assertEqual((j["state"], r["answer"], r["model_called"]), ("done", "needs_rerender", False))
        nr = r["needs_rerender"]
        self.assertEqual(sorted(nr["clips"]), sorted(j["clips"]))          # every clip of the page, not just A
        self.assertGreaterEqual(len(nr["clips"]), 2)
        self.assertEqual(nr["code"], "burned-text")
        self.assertTrue(nr["reason"]["message_zh"])
        p = nr["paths"][0]
        self.assertEqual(p["kind"], "rerender-scripts")
        self.assertEqual(p["files"][0]["file"], os.path.join("work", "clipdefs.py"))
        self.assertEqual([a["kind"] for a in p["actions"]][:2], ["copy-prompt", "open-file"])
        self.assertEqual([s["stage"] for s in j["stages"]], ["read", "check", "plan"])

    def test_project_request_gives_grouped_cards_for_all_clips(self):
        job = self.pa.start(self.item, "所有片子都 1.2 倍速")["job"]
        r = self._done(job)["result"]
        self.assertEqual(r["answer"], "changes")
        self.assertEqual(sorted(g["clip"] for g in r["groups"]), sorted(self.pa.get(job)["clips"]))
        for g in r["groups"]:
            self.assertEqual(g["proposals"][0]["op"], dict(op="speed", value=1.2))
            self.o.edit(self.item, g["clip"], [p["op"] for p in g["proposals"]])        # each group applies
        with self.assertRaises(BadRequest):
            self.pa.start(self.item, "")

    def _fake_engine(self, body):
        """The real-engine path with a scripted engine process (no vstudio needed)."""
        self.pa._engine_ai = True
        script = os.path.join(self.root, "fake_engine.py")
        with open(script, "w") as f:
            f.write(textwrap.dedent(body))
        self.o._output_id = lambda e, c: "final/" + c["id"] + ".mp4"
        self.pa.command = lambda e, j, ids, ctx: ([sys.executable, script, os.path.join(self.root, "pids"),
                                                  json.dumps(ids)], dict(os.environ))

    def test_cancel_kills_the_engine_and_its_model_cli(self):
        self._fake_engine("""
            import json, subprocess, sys, time
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            open(sys.argv[1], "w").write(json.dumps([child.pid]))
            print(json.dumps(dict(event="stage", stage="read", n=2)), flush=True)
            print(json.dumps(dict(event="stage", stage="ask", n=2, provider="claude-code")), flush=True)
            time.sleep(60)
        """)
        job = self.pa.start(self.item, "所有片子加个进度条")["job"]
        _wait(lambda: any(s["stage"] == "ask" for s in self.pa.get(job)["stages"]))
        self.assertEqual(self.pa.get(job)["stages"][-1]["provider"], "claude-code")
        proc = self.pa.jobs[job]["proc"]
        with open(os.path.join(self.root, "pids")) as f:
            child = json.load(f)[0]
        r = self.pa.stop(job)
        self.assertTrue(r["killed"])
        self.assertEqual(self.pa.get(job)["state"], "cancelled")
        self.assertIsNotNone(_wait(lambda: proc.poll() is not None or None, 5))
        self.assertTrue(_wait(lambda: not _alive(child), 5), "the model CLI child must die with the engine")
        time.sleep(0.2)
        self.assertEqual(self.pa.get(job)["state"], "cancelled")

    def test_timeout_fallback_notice_and_result(self):
        self._fake_engine("""
            import json, sys
            ids = json.loads(sys.argv[2])
            def out(**e): print(json.dumps(e, ensure_ascii=False), flush=True)
            out(event="stage", stage="read", n=len(ids))
            out(event="stage", stage="ask", n=len(ids), provider="claude-code")
            out(event="partial", needs_rerender=dict(outputs=[ids[0]], titles=["x"], code="burned-text", paths=[]))
            out(event="fallback", **{"from": "claude-code"}, to="codex", code="timeout", error="timed out after 120 s")
            out(event="stage", stage="plan", n=len(ids))
            out(event="done", result=dict(answer="changes", model_called=True, provider="codex", model="m",
                fallback={"from": "claude-code", "to": "codex", "code": "timeout"}, seconds=1.0,
                groups=[dict(output=i, mode="flattened", proposed=[dict(op=dict(op="speed", value=1.1),
                    normalized=dict(op="speed", value=1.1), describe=dict(code="op-speed", params=dict(value=1.1)))])
                    for i in ids], needs_rerender=None))
        """)
        job = self.pa.start(self.item, "所有片子 1.1 倍速")["job"]
        j = self._done(job)
        self.assertEqual(j["state"], "done")
        self.assertEqual([n["code"] for n in j["notices"] if n["kind"] == "fallback"], ["timeout"])
        self.assertEqual(len(j["partial"]["clips"]), 1)                      # the early rule answer, mapped to clips
        r = j["result"]
        self.assertEqual((r["provider"], r["fallback"]["code"], r["engine"]), ("codex", "timeout", "real"))
        self.assertEqual(sorted(g["clip"] for g in r["groups"]), sorted(j["clips"]))
        self.assertEqual(r["groups"][0]["proposals"][0]["op"], dict(op="speed", value=1.1))

    def test_watchdog_stops_a_hung_engine(self):
        self._fake_engine("""
            import json, time
            print(json.dumps(dict(event="stage", stage="ask", n=1, provider="claude-code")), flush=True)
            time.sleep(60)
        """)
        with mock.patch.object(PA, "ENGINE_TIMEOUT", 0.1), mock.patch.object(PA, "WATCHDOG_GRACE", 0.4):
            job = self.pa.start(self.item, "所有片子加个进度条")["job"]
            j = self._done(job)
        self.assertEqual((j["state"], j["error"]["code"]), ("failed", "ask-timeout"))

    def test_engine_refusal_is_reported(self):
        self._fake_engine("""
            import json
            print(json.dumps(dict(event="failed", code="llm-failed", message="the model call failed",
                                  message_zh="模型调用失败", params=dict(provider="claude-code"))), flush=True)
            raise SystemExit(5)
        """)
        j = self._done(self.pa.start(self.item, "所有片子加个进度条")["job"])
        self.assertEqual((j["state"], j["error"]["code"]), ("failed", "llm-failed"))


if __name__ == "__main__":
    unittest.main()
