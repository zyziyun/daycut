"""The plan card's "things for you to decide" follow the desk's UI language: an English request on an English
desk used to get Chinese questions from the AI planner (its prompt asked for "<zh>" texts). The desk passes its UI
language (``lang``) to ``vstudio.intake plan / revise --ui-lang``; the engine tells the model to write questions,
risks and reasons in it.

Real engine (``python -m vstudio.intake`` in a subprocess, like the packaged app) with a fake ``claude`` CLI that
records the request document it is sent and answers in the language that document asks for."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _isolate  # noqa: E402,F401

from desk_engine import intake as IN  # noqa: E402
from desk_engine.caps import CliRunner  # noqa: E402
from desk_engine.common import BadRequest  # noqa: E402

ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
REQUEST = "Cut this talk into vertical clips for TikTok and Xiaohongshu"
QUESTION = {"English": "Who is the host?", "Simplified Chinese": "谁是主持人？", "French": "Qui est l'hôte ?"}

FAKE_CLAUDE = r'''#!{python}
import json, sys
body = sys.stdin.read()
doc = json.loads(body.split("\n\n")[0])
with open({log!r}, "a", encoding="utf-8") as f:
    f.write(json.dumps(dict(reply_language=doc.get("reply_language"), argv=sys.argv[1:3])) + "\n")
q = {questions!r}[doc["reply_language"]]
plan = dict(projects=[dict(recipe="talkinghead", name="talk", materials=["f1"], inputs=dict(video=["f1"]),
                           items=dict(method="per-file"))],
            questions=[dict(project=0, text=q, options=["A", "B"], default="A")], risks=[], summary_zh="Four clips.", summary_lang="en")
print(json.dumps(dict(type="result", is_error=False, result="", structured_output=plan)))
'''


@unittest.skipIf(os.name == "nt" or not shutil.which("ffmpeg"), "fake CLI is a script; needs ffmpeg for the video")
class PlanLanguageRealEngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="plang-")
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        self.log = os.path.join(tmp, "claude.log")
        exe = os.path.join(bindir, "claude")
        with open(exe, "w", encoding="utf-8") as f:
            f.write(FAKE_CLAUDE.format(python=sys.executable, log=self.log, questions=QUESTION))
        os.chmod(exe, 0o755)
        self.video = os.path.join(tmp, "talk.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=4",
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", self.video], check=True)
        routes = os.path.join(tmp, "llm-routes.json")
        with open(routes, "w", encoding="utf-8") as f:
            json.dump({"default": {"provider": "claude-code"}, "tasks": {"intake": {"provider": "claude-code"}}}, f)
        env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=os.path.join(tmp, "vhome"),
                   VSTUDIO_CACHE=os.path.join(tmp, "cache"), PATH=bindir + os.pathsep + os.environ.get("PATH", ""),
                   VSTUDIO_CLI_EXTRA_DIRS="", VSTUDIO_DEFAULT_PERSONA="1", VSTUDIO_LLM_ROUTES_FILE=routes)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_INTAKE_PROVIDER"):
            env.pop(k, None)
        self.it = IN.Intake(os.path.join(tmp, "desk"), None, CliRunner(sys.executable, env), "real")

    def wait(self, pid, limit=120):
        t0 = time.time()
        while time.time() - t0 < limit:
            j = self.it.get(pid)
            if j["state"] != "running":
                return j
            time.sleep(0.1)
        self.fail("the plan never finished")

    def asked(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(x)["reply_language"] for x in f]

    def test_questions_follow_the_ui_language(self):
        for lang, name in (("en", "English"), ("zh-CN", "Simplified Chinese"), ("fr", "French")):
            with self.subTest(lang=lang):
                j = self.wait(self.it.start(REQUEST, [self.video], lang=lang)["id"])
                self.assertEqual(j["state"], "done", j.get("error"))
                plan = j["plan"]
                self.assertFalse(plan["planner"].get("fallback"), plan["planner"])
                self.assertEqual(self.asked()[-1], name)
                self.assertEqual([q["text"] for q in plan["questions"]], [QUESTION[name]])
                self.assertEqual(plan["ui_lang"], IN.UI_LANGS[lang])
                self.assertEqual(plan["summary_lang"], "en")          # the summary: in the request's language

    def test_revise_keeps_the_language_and_follows_a_switch(self):
        pid = self.it.start(REQUEST, [self.video], lang="fr")["id"]
        self.wait(pid)
        self.it.revise(pid, "only TikTok")
        j = self.wait(pid)
        self.assertEqual((j["state"], self.asked()[-1], j["plan"]["ui_lang"]), ("done", "French", "fr"))
        self.it.revise(pid, "only TikTok", lang="en")                       # she switched the app to English
        j = self.wait(pid)
        self.assertEqual((self.asked()[-1], j["plan"]["questions"][0]["text"]), ("English", QUESTION["English"]))

    def test_a_fixed_intent_skips_the_model(self):
        """The recorder's 「把我的录制做成口播」 (and Home's talking-head start): the talking-head recipe straight away,
        by the rules - the AI planner is never called (it took ~2 min), and the plan is not flagged as a fallback."""
        prompt = "把我的录制做成口播视频：去掉停顿和「嗯」，加上字幕和封面。"   # 「封面」 alone would pick the cover recipe
        j = self.wait(self.it.start(prompt, [self.video], lang="zh-CN", recipe="talkinghead")["id"])
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertEqual([p["recipe"] for p in j["plan"]["projects"]], ["talkinghead"])
        self.assertEqual((j["plan"]["planner"]["route"], j["plan"]["planner"]["fallback"]), ("fixed", False))
        self.assertFalse(os.path.exists(self.log) and self.asked())             # no model call
        with self.assertRaises(BadRequest):
            self.it.start(prompt, [self.video], recipe="../x")

    def test_no_lang_follows_the_request(self):
        j = self.wait(self.it.start(REQUEST, [self.video])["id"])
        self.assertEqual((j["state"], self.asked()[-1]), ("done", "English"))


class PlanLanguageArgsTest(unittest.TestCase):
    def test_bad_lang_is_refused(self):
        it = IN.Intake(tempfile.mkdtemp(), None, None, "real")
        for bad in ("de", "zh-TW", 3):
            with self.assertRaises(BadRequest):
                it.start("x", [], lang=bad)

    def test_ui_lang_codes(self):
        self.assertEqual([IN.ui_lang(x) for x in ("en", "zh-CN", "zh", "fr", None)], ["en", "zh", "zh", "fr", None])
