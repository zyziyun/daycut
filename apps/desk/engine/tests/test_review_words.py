"""The engine's own status words never reach the screen as they are: "0/1 jobs", "done: 3 jobs", "checkpoint: publish"
and stage ids ("s003:export") become a code + params and a bare stage list (desk_engine.common.live_words); a waiting
run keeps neither the last running stage nor its 100 %."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine.common import live_status, live_words  # noqa: E402
from desk_engine.pilot import progress_feed  # noqa: E402


class LiveWords(unittest.TestCase):
    def test_running_jobs_and_stages(self):
        w = live_words(dict(status="running", stage="s001:asr, s002:cleanup", message="0/3 jobs"), "running")
        self.assertEqual(w["code"], "jobs")
        self.assertEqual(w["params"], dict(done=0, total=3))
        self.assertIsNone(w["message"])
        self.assertEqual(w["stages"], [dict(job="s001", stage="asr"), dict(job="s002", stage="cleanup")])
        self.assertEqual(w["stage"], "asr")
        self.assertEqual((w["jobs_done"], w["jobs_total"]), (0, 3))
        # structured fields from a newer runner win over parsing
        w = live_words(dict(status="running", message="1/2 jobs", live_code="jobs", jobs_done=1, jobs_total=2), "running")
        self.assertEqual(w["params"], dict(done=1, total=2))

    def test_finished_and_failed_lines(self):
        self.assertEqual(live_words(dict(message="done: 3 jobs"), "done")["code"], "finished")
        self.assertEqual(live_words(dict(message="done: 3 jobs"), "done")["params"], dict(n=3))
        self.assertEqual(live_words(dict(message="done, 4 jobs; some failed"), "failed")["code"], "some-failed")
        self.assertEqual(live_words(dict(message="2 item(s) failed"), "failed")["params"], dict(n=2))
        self.assertEqual(live_words(dict(message="refused: over budget"), "failed")["code"], "over-budget")
        self.assertEqual(live_words(dict(message="pilot finished: review it, then confirm the pilot"), "waiting")["code"], "pilot")
        # an agent's own words stay as written
        w = live_words(dict(message="Rendering the promo", stage="render"), "running")
        self.assertNotIn("code", w)
        self.assertEqual(w["stage"], "render")

    def test_waiting_at_a_checkpoint_drops_the_old_stage_and_100(self):
        w = live_words(dict(status="waiting", stage="s003:export", progress=1.0, message="checkpoint: publish"), "waiting")
        self.assertEqual(w["code"], "checkpoint")
        self.assertEqual(w["params"], dict(kinds=["publish"]))
        self.assertEqual(w["stage"], "cp_publish")          # the step of the question, not the last running stage
        self.assertIsNone(w["progress"])
        self.assertEqual(w["stages"], [])

    def test_a_newer_engine_codes_its_lines(self):
        w = live_words(dict(status="running", stage="cp_cover-pick", message="deciding: cover-pick", live_code="deciding",
                            live_params=dict(kind="cover-pick", item="s001")), "running")
        self.assertEqual((w["code"], w["params"]["kind"], w["stage"]), ("deciding", "cover-pick", "cp_cover-pick"))
        w = live_words(dict(status="waiting", stage="cp_publish", message="checkpoint: publish", live_code="checkpoint",
                            live_params=dict(ids=["publish"], kinds=["publish"])), "waiting")
        self.assertEqual((w["code"], w["params"]["kinds"]), ("checkpoint", ["publish"]))

    def test_live_status_reads_the_file(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, ".vstudio"))
        with open(os.path.join(d, ".vstudio", "status.json"), "w") as f:
            json.dump(dict(status="waiting", needs_you=True, heartbeat=time.time() - 300, stage="s003:export",
                           progress=1.0, message="checkpoint: filler-confirm, publish"), f)
        st = live_status(d)
        self.assertEqual((st["state"], st["code"], st["stage"], st["progress"]), ("waiting", "checkpoint", "cp_filler-confirm", None))
        self.assertIsNone(st["message"])


class Feed(unittest.TestCase):
    def test_the_runs_events_as_codes_only(self):
        d = tempfile.mkdtemp()
        evs = [dict(event="run-start", ts=1, jobs=["s001", "s002"]), dict(event="log", msg="[batch] /tmp/x/secret"),
               dict(event="stage-start", ts=2, job="s001", stage="asr", resource="asr"),
               dict(event="stage-done", ts=3, job="s001", stage="probe", cached=True),
               dict(event="stage-fail", ts=4, job="s002", stage="export", error="ffmpeg: /tmp/x/a.mp4 bad"),
               dict(event="auto-answer", ts=5, checkpoint="cover", kind="cover-pick", item="s001", by="ai"),
               dict(event="job-done", ts=6, job="s001", state="done", qc="green")]
        with open(os.path.join(d, "desk-pilot.log"), "w") as f:
            f.write("\n".join(json.dumps(e) for e in evs) + "\nTraceback (most recent call last):\n")
        out = progress_feed(d)
        self.assertFalse(out["running"])
        self.assertEqual([e["event"] for e in out["events"]],
                         ["run-start", "stage-start", "stage-fail", "auto-answer", "job-done"])   # no log text, no cache hits
        self.assertEqual(out["events"][0]["n"], 2)
        self.assertEqual(out["events"][3]["kind"], "cover-pick")
        self.assertNotIn("error", out["events"][2])                                   # never the engine's text / paths
        self.assertEqual(len(progress_feed(d, 2)["events"]), 2)


if __name__ == "__main__":
    unittest.main()
