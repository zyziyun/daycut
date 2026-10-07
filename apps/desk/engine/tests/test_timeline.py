"""Timeline media (desk_engine/timeline.py): tile plan, audio peaks, the sprite sheet + peaks of a real file (cached),
and 「听一遍这条片子」 with the test engine (words from an .srt next to the file, kept in the desk data dir, returned by
show); without the engine it fails and says so."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_mock import MockStrips  # noqa: E402

from desk_engine import outputs as OU  # noqa: E402
from desk_engine import timeline as TL  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from test_v04 import make_fuye  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def make_video(path, dur=4, w=180, h=320, audio=True):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={dur}", "-shortest", "-c:a", "aac"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)


class PlanTest(unittest.TestCase):
    def test_tiles_per_half_second_capped(self):
        p = TL.plan(97.9, 1080, 1920)
        self.assertEqual((p["interval"], p["n"], p["tile"]), (0.5, 196, [54, 96]))
        self.assertEqual(p["rows"], 17)
        long = TL.plan(1800, 1920, 1080)
        self.assertEqual(long["n"], TL.MAX_TILES)
        self.assertAlmostEqual(long["interval"], 7.5)
        self.assertEqual(long["tile"], [170, 96])
        self.assertEqual(TL.plan(0, None, None)["n"], 1)

    def test_peaks_normalised_and_compressed(self):
        pk = TL.peaks_from_pcm([0, 100, -200, 50] * 100 + [0] * 400, 800, 10)
        self.assertEqual(len(pk), 10)
        self.assertEqual(max(pk), 1.0)
        self.assertEqual(pk[-1], 0.0)
        self.assertEqual(TL.peaks_from_pcm([], 8000, 50), [])

    def test_srt_and_tokens(self):
        cues = TL.parse_srt("1\n00:00:01,000 --> 00:00:02,500\n每个线程 有自己的 index\n\n2\n00:00:03,000 --> 00:00:04,000\nwarp 是三十二\n")
        self.assertEqual(cues[0][:2], (1.0, 2.5))
        self.assertEqual(TL.tokens(cues[0][2]), ["每个", "线程", "有自", "己的", "index"])
        self.assertEqual(TL.tokens("warp 是三十二"), ["warp", "是三", "十二"])


@unittest.skipUnless(FFMPEG, "ffmpeg needed")
class StripTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.s = TL.Strips(os.path.join(self.root, "desk"), None, mock.Mock())

    def test_sprite_and_peaks_made_once(self):
        f = os.path.join(self.root, "a.mp4")
        make_video(f, dur=4)
        t = time.time()
        m = self.s.build(f)
        self.assertTrue(os.path.exists(m["sprite"]))
        self.assertEqual(m["n"], 8)
        self.assertEqual(m["tile"], [54, 96])
        self.assertTrue(m["has_audio"])
        self.assertAlmostEqual(len(m["peaks"]) / m["peaks_rate"], 4, delta=0.2)
        first = time.time() - t
        t = time.time()
        self.assertEqual(self.s.build(f), m)                    # cached (strip.json)
        self.assertLess(time.time() - t, max(0.2, first / 2))
        # the sprite is cols x rows tiles
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", m["sprite"]],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, f"{12 * 54},{1 * 96}")
        self.assertTrue(m["sprite"].startswith(os.path.join(self.root, "desk", "strips")))  # never next to her file

    def test_no_audio(self):
        f = os.path.join(self.root, "silent.mp4")
        make_video(f, dur=2, w=320, h=180, audio=False)
        m = self.s.build(f)
        self.assertFalse(m["has_audio"])
        self.assertEqual(m["peaks"], [])
        self.assertEqual(m["tile"], [170, 96])


class TranscribeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.watch = os.path.join(self.root, "demos")
        self.d = make_fuye(self.watch)
        with open(os.path.join(self.d, "final", "zh.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,500 --> 00:00:02,000\n自媒体 是一个 放大器\n")
        self.env = mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": self.watch, "DESK_MOCK_ASR_STEP": "0.05",
                                                "VSTUDIO_HOME": os.path.join(self.root, "home")})
        self.env.start()
        data = os.path.join(self.root, "desk")
        self.h = History(data, Registry(data))
        self.bus = EventBus()
        self.o = OU.Outputs(data, self.h, bus=self.bus)
        self.s = MockStrips(data, self.o, self.h, self.bus)
        self.item = next(r["id"] for r in self.h.list()["items"] if r["dir"] == self.d)

    def tearDown(self):
        self.env.stop()

    def test_listen_fills_the_words(self):
        q = self.bus.subscribe()
        self.assertEqual(self.o.show(self.item, "B_自媒体")["words"], [])
        self.assertEqual(self.s.route("GET", self.item, "B_自媒体", "transcribe"), {"state": "idle"})
        self.assertEqual(self.s.route("POST", self.item, "B_自媒体", "transcribe")["state"], "running")
        evs, t0 = [], time.time()
        while time.time() - t0 < 10 and not any(e.get("state") == "done" for e in evs):
            try:
                evs.append(q.get(timeout=0.5))
            except Exception:  # noqa: BLE001
                pass
        mine = [e for e in evs if e.get("type") == "output-transcribe"]
        self.assertEqual([e["state"] for e in mine], ["running", "done"])
        words = self.o.show(self.item, "B_自媒体")["words"]
        self.assertEqual([w["w"] for w in words][:3], ["自媒", "体", "是一"])
        self.assertAlmostEqual(words[0]["t"], 0.5)
        self.assertLessEqual(words[-1]["te"], 2.0)
        self.assertEqual(self.s.transcribe_state(self.item, "B_自媒体")["state"], "done")
        # nothing written into her folder
        self.assertFalse(any(n.endswith(".asr.json") and n.startswith("B_") for n in os.listdir(os.path.join(self.d, "final"))))
        # a clip that already has words keeps them
        self.assertEqual([w["w"] for w in self.o.show(self.item, "A_换圈子")["words"]][:2], ["你在", "副业"])

    def test_unknown_clip(self):
        with self.assertRaises(KeyError):
            self.s.route("POST", self.item, "nope", "transcribe")


if __name__ == "__main__":
    unittest.main()
