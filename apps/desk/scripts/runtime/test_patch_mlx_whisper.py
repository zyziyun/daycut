"""The scipy-free mlx_whisper patch (patch_mlx_whisper.py) gives the same word timestamps as scipy.

Run: python3 -m unittest discover -s scripts/runtime (npm run test:scripts). The comparisons need mlx-whisper and scipy
in the Python running the tests (a dev environment); the end-to-end check also needs the cached whisper-small.en-mlx
model and ffmpeg, and is skipped without them (no download in a test)."""
import importlib
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_mlx_whisper as P  # noqa: E402

try:
    import mlx_whisper
    import mlx_whisper.timing  # noqa: F401
    from scipy import signal as scipy_signal
except Exception:  # noqa: BLE001  (no mlx / scipy here: the comparison tests skip)
    mlx_whisper = None

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "packaging", "sample", "reelfold-sample.mp4")
SMALL = "mlx-community/whisper-small.en-mlx"


class _NoScipy:
    """A meta-path finder that makes `import scipy` fail, as in the app's runtime."""

    def find_spec(self, name, path=None, target=None):
        if name == "scipy" or name.startswith("scipy."):
            raise ModuleNotFoundError(f"No module named {name!r} (blocked: the app ships no scipy)")
        return None


class PatchSourceTest(unittest.TestCase):
    SRC = "import numba\nimport numpy as np\nfrom scipy import signal\n\nx = signal.medfilt(a, kernel_size=(1, 1, 7))\n"

    def test_replaces_the_import_once_and_is_idempotent(self):
        out = P.patch_source(self.SRC)
        self.assertNotIn("from scipy", out)
        self.assertNotIn("import scipy", out)
        self.assertIn(P.MARK, out)
        self.assertEqual(P.patch_source(out), out)

    def test_refuses_a_changed_module(self):
        with self.assertRaises(SystemExit):
            P.patch_source(self.SRC + "y = signal.lfilter(b, a, x)\n")
        with self.assertRaises(SystemExit):
            P.patch_source("import numpy as np\nfrom scipy.signal import medfilt\n")


@unittest.skipUnless(mlx_whisper, "needs mlx-whisper and scipy (dev environment)")
class PatchedModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a copy of the installed package under another name, patched, imported with scipy blocked
        cls.tmp = tempfile.mkdtemp(prefix="mlxw-")
        pkg = os.path.join(cls.tmp, "mlx_whisper_rf")
        shutil.copytree(os.path.dirname(mlx_whisper.__file__), pkg, ignore=shutil.ignore_patterns("__pycache__"))
        timing = os.path.join(pkg, "timing.py")
        with open(timing, encoding="utf-8") as f:
            src = f.read()
        with open(timing, "w", encoding="utf-8") as f:
            f.write(P.patch_source(src))
        sys.path.insert(0, cls.tmp)
        blocker = _NoScipy()
        saved = {k: v for k, v in sys.modules.items() if k == "scipy" or k.startswith("scipy.")}
        for k in saved:
            del sys.modules[k]
        sys.meta_path.insert(0, blocker)
        try:
            cls.patched = importlib.import_module("mlx_whisper_rf")
            cls.ptiming = importlib.import_module("mlx_whisper_rf.timing")
        finally:
            sys.meta_path.remove(blocker)
            sys.modules.update(saved)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.tmp)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_patched_module_does_not_import_scipy(self):
        self.assertTrue(self.ptiming.signal.__module__.startswith("mlx_whisper_rf"))

    def test_medfilt_equals_scipy(self):
        rng = np.random.default_rng(0)
        for shape, k in [((3, 5, 40), (1, 1, 7)), ((1, 1, 9), (1, 1, 7)), ((2, 4, 1500), (1, 1, 7)), ((20,), (5,)),
                         ((4, 33), (1, 3)), ((2, 3, 10), (1, 1, 1))]:
            for dtype in (np.float32, np.float64):
                x = rng.normal(size=shape).astype(dtype)
                want = scipy_signal.medfilt(x, kernel_size=k)
                got = self.ptiming.signal.medfilt(x, kernel_size=k)
                self.assertEqual(got.dtype, want.dtype, (shape, k, dtype))
                np.testing.assert_array_equal(got, want, err_msg=f"{shape} {k} {dtype}")
        with self.assertRaises(ValueError):
            self.ptiming.signal.medfilt(np.zeros((3, 3)), kernel_size=(3, 3))

    def test_median_filter_equals_the_original(self):
        rng = np.random.default_rng(1)
        for shape in [(6, 40, 1500), (12, 7, 300), (50,), (2, 3, 3)]:  # 1-D and 3-D: what timing.py passes
            x = rng.random(shape, dtype=np.float32)
            np.testing.assert_array_equal(self.ptiming.median_filter(x, 7), mlx_whisper.timing.median_filter(x, 7), err_msg=str(shape))

    def test_word_timestamps_equal_the_original(self):
        from huggingface_hub import try_to_load_from_cache
        if not shutil.which("ffmpeg") or not os.path.exists(SAMPLE) or not isinstance(try_to_load_from_cache(SMALL, "config.json"), str):
            self.skipTest(f"needs ffmpeg, the sample recording and the cached {SMALL}")
        os.environ["HF_HUB_OFFLINE"] = "1"
        audio = mlx_whisper.audio.load_audio(SAMPLE)[: 16000 * 30]            # the first 30 s

        def words(mod):
            r = mod.transcribe(audio, path_or_hf_repo=SMALL, word_timestamps=True, temperature=0.0, language="en")
            return [(w["word"], round(w["start"], 3), round(w["end"], 3)) for s in r["segments"] for w in s["words"]]
        want = words(mlx_whisper)
        got = words(self.patched)
        self.assertGreater(len(want), 40)
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
