"""Test fixture for the real-engine inbox e2e: one talkinghead project on a tiny synthetic talk (tone-burst words +
the engine tests' fake transcriber, so no ASR model and no AI account), run with the REAL engine until it waits for
her: hook / cover answered by their defaults, a filler cut to confirm.

    python real_project.py ROOT [--pilot]   (VSTUDIO_HOME etc. from the environment) -> prints {dir, truth, ...}

``--pilot``: two clips, run as the desk starts a project (a pilot of one), which parks the first clip at its filler
question and leaves the second unmade. ``--autopilot``: run on autopilot (rules decide; no AI account) to the end, so
the clip is made and its decisions are in the autopilot log.
"""
import json
import os
import sys

ROOT = sys.argv[1]
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
TESTS = os.path.join(REPO, "tests")
sys.path[:0] = [os.path.join(REPO, "lib"), TESTS]

import _batch_helpers as H  # noqa: E402  (the engine tests' synthetic media + fake transcriber)

# (word, seconds, pause after). "然后" after a pause, running into the next words, is a taste call the engine asks
# about (a filler cut to confirm), with the words around it
WORDS = [("大家", .4, .12), ("好", .3, .12), ("今天", .4, .12), ("我们", .35, .12), ("讲", .3, .12), ("一个", .35, .12),
         ("方法", .4, .7), ("然后", .35, .05), ("来", .3, .12), ("看", .3, .6), ("第二", .4, .12), ("个", .25, .12),
         ("例子", .4, .12), ("也", .3, .12), ("很", .25, .12), ("重要", .4, .12), ("最后", .4, .12), ("总结", .4, .12),
         ("一下", .35, .12)]


def synth(words, sr=48000, lead=0.4):
    """Tone-burst speech with a pause after each word (the engine tests' synth_speech, with per-word pauses)."""
    import numpy as np
    rng = np.random.default_rng(1)
    t, ev, truth = lead, [], []
    for k, (text, dur, gap) in enumerate(words):
        f = 300 + 37 * k
        ev.append((t, t + dur, f))
        truth.append(dict(w=text, t=round(t - 0.02, 3), te=round(t + dur - 0.02, 3)))
        t += dur + gap
    n = int((t + 0.4) * sr)
    x = (3e-4 * rng.standard_normal(n)).astype(np.float32)
    ramp = int(0.008 * sr)
    r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp))
    for a, b, f in ev:
        i0, i1 = int(a * sr), int(b * sr)
        y = 0.25 * np.sin(2 * np.pi * f * np.arange(i1 - i0) / sr)
        y[:ramp] *= r
        y[-ramp:] *= r[::-1]
        x[i0:i1] += y.astype(np.float32)
    return x, truth, n / sr


media = os.path.join(ROOT, "media")
os.makedirs(media, exist_ok=True)
x, truth, dur = synth(WORDS)
PILOT = "--pilot" in sys.argv
AUTO = "--autopilot" in sys.argv
for name in (("talk.mp4", "talk2.mp4") if PILOT else ("talk.mp4",)):
    H.make_video(os.path.join(media, name), x, 48000, dur)
tp = os.path.join(ROOT, "truth.json")
with open(tp, "w", encoding="utf-8") as f:
    json.dump(truth, f, ensure_ascii=False)
os.environ["VSTUDIO_TEST_TRUTH"] = tp

from vstudio.project.core import Project  # noqa: E402

p = Project.create(os.path.join(ROOT, "projects", "talk"), recipe="talkinghead", folder=media, name="Short talk",
                   params=dict(pipeline="fast", platforms=["xiaohongshu:full"], preset="ultrafast", speed=1.0,
                               layout="pad-blur"),
                   auto=["hook", "cover"],
                   spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"], plugin_paths=[TESTS],
                             asr=dict(transcriber="_batch_helpers:fake_transcriber"), proofread=dict(enabled=False)))
r = p.run(pilot=1 if PILOT else None, autopilot=True if AUTO else None)
print(json.dumps(dict(dir=p.dir, truth=tp, plugin_path=TESTS, status=r["status"], items=[i["id"] for i in p.data["items"]],
                      pending=[(x["item"], x["id"]) for x in r["pending"]]), ensure_ascii=False))
