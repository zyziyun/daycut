"""Bundle-time patch: mlx_whisper without scipy.

The app's runtime ships no scipy (its compiled extensions import non-public Accelerate BLAS symbols - App Review 2.5.1
rejected Reelfold 0.2.1 for scipy's SuperLU extension - and the engine itself needs none of it). mlx-whisper imports
scipy for exactly one call: ``signal.medfilt`` in ``mlx_whisper/timing.py`` (the median filter over the attention
weights that word timestamps are aligned on). This replaces ``from scipy import signal`` with a numpy ``medfilt`` of the
same semantics for the kernels timing.py uses ((1, ..., 1, k): along the last axis, zero-padded like scipy, the
median of each window). ``packaging/runtime.lock.json`` drops scipy from the pins (uv override), so the import would
otherwise fail at the first transcription with word timestamps.

    python patch_mlx_whisper.py <site-packages>     # run by scripts/runtime/bundle.mjs after pip install

Fails loudly when timing.py no longer looks as expected (a new mlx-whisper release): re-check and update the patch.
tests: scripts/runtime/test_patch_mlx_whisper.py (output identical to scipy's medfilt and to the unpatched module).
"""
import os
import sys

IMPORT = "from scipy import signal\n"
MARK = "# Reelfold runtime: scipy-free medfilt"
SHIM = f'''{MARK} (apps/desk/scripts/runtime/patch_mlx_whisper.py)
class signal:  # noqa: N801  (stands in for scipy.signal: only medfilt is used here)
    @staticmethod
    def medfilt(volume, kernel_size):
        """scipy.signal.medfilt for kernels (1, ..., 1, k), k odd: zero-padded median along the last axis."""
        k = tuple(int(n) for n in kernel_size) if np.ndim(kernel_size) else (int(kernel_size),) * np.ndim(volume)
        if len(k) != np.ndim(volume) or any(n != 1 for n in k[:-1]) or k[-1] % 2 != 1:
            raise ValueError(f"medfilt shim: unsupported kernel_size {{kernel_size}} for shape {{np.shape(volume)}}")
        w = k[-1]
        x = np.asarray(volume)
        if w == 1:
            return x.copy()
        pad = [(0, 0)] * (x.ndim - 1) + [(w // 2, w // 2)]
        windows = np.lib.stride_tricks.sliding_window_view(np.pad(x, pad), w, axis=-1)
        return np.median(windows, axis=-1).astype(x.dtype, copy=False)
'''


def patch_source(src):
    """timing.py source -> patched source (idempotent)."""
    if MARK in src:
        return src
    if src.count(IMPORT) != 1 or src.count("signal.") != 1 or "signal.medfilt(" not in src:
        raise SystemExit("mlx_whisper/timing.py changed: expected exactly one `from scipy import signal` and one "
                         "signal.medfilt call - update apps/desk/scripts/runtime/patch_mlx_whisper.py")
    if "import numpy as np\n" not in src.split(IMPORT)[0]:
        raise SystemExit("mlx_whisper/timing.py: numpy must be imported (as np) before scipy")
    return src.replace(IMPORT, SHIM)


def main(site):
    path = os.path.join(site, "mlx_whisper", "timing.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    out = patch_source(src)
    if out != src:
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
    print(f"patched {path}")


if __name__ == "__main__":
    main(sys.argv[1])
