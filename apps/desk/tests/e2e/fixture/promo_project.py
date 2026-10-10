"""Test fixture for the draft-review e2e: two promo-recut projects on a tiny synthetic talk (tone-burst words + the
engine tests' fake transcriber, so no ASR model; no AI account: the engine drafts by its rules), run with the REAL
engine until each waits at "Check what's kept":

    drafted    the engine drafted the keep spans itself (no model: nothing is cut, said so) - the Inbox shows the
               transcript with kept / cut sentences
    stuck      like her 0.2.3 project: the item still holds the seeded SYNTHETIC example and nothing was drafted
               (drafting is switched off for this run) - the Inbox offers "Draft it for me", never the YAML

    python promo_project.py ROOT   (VSTUDIO_HOME, VSTUDIO_TEST_TRUTH etc. from the environment) -> {drafted, stuck}
"""
import json
import os
import sys

ROOT = sys.argv[1]
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
TESTS = os.path.join(REPO, "tests")
sys.path[:0] = [os.path.join(REPO, "lib"), TESTS]

import _batch_helpers as H  # noqa: E402

WORDS = [("大家", .4), ("好", .3), ("嗯。", .3), ("今天", .4), ("讲", .3), ("可灵", .4), ("和", .2), ("Seedance。", .5),
         ("顺便", .4), ("说", .3), ("一下", .3), ("Hedra。", .5), ("最后", .4), ("总结", .4), ("一下。", .35)]

media = os.path.join(ROOT, "media")
os.makedirs(media, exist_ok=True)
x, truth, dur = H.synth_speech(WORDS)
talk = H.make_video(os.path.join(media, "AIGC talk.mp4"), x, 48000, dur)
tp = os.path.join(ROOT, "truth.json")
with open(tp, "w", encoding="utf-8") as f:
    json.dump([{k: w[k] for k in ("w", "t", "te")} for w in truth], f, ensure_ascii=False)
os.environ["VSTUDIO_TEST_TRUTH"] = tp

from vstudio.project import drafts as DR  # noqa: E402
from vstudio.project.core import Project  # noqa: E402

SPEC = dict(plugin_paths=[TESTS], asr=dict(transcriber="_batch_helpers:fake_transcriber"))


def make(name, title):
    p = Project.create(os.path.join(ROOT, "projects", name), recipe="promo-recut", name=title,
                       inputs=dict(talk=[talk]), params=dict(language="zh"), spec=SPEC)
    p.data["prompt"] = "剪辑这条口播：删掉开头没讲完的开场，以及讲 Hedra 的整段。正文 1.5 倍速。"
    p.save()
    return p


out = {}
p = make("drafted", "AIGC drafted")
p.run()
out["drafted"] = dict(dir=p.dir, pending=[(x["item"], x["id"]) for x in p.pending()])
real = DR.ensure
DR.ensure = lambda *a, **k: None                     # her 0.2.3 project: nothing drafted, the example in place
try:
    q = make("stuck", "AIGC stuck")
    q.run()
finally:
    DR.ensure = real
out["stuck"] = dict(dir=q.dir, pending=[(x["item"], x["id"]) for x in q.pending()])
print(json.dumps(out, ensure_ascii=False))
