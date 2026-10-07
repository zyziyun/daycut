"""Sync two recordings of the same session (a screen share + a camera, two cameras, a call + a local mic).

    from vstudio import avsync
    s = avsync.sync("screen.mp4", "camera.mov")      # {offset, method, confidence, ...}
    t_cam = t_screen + s["offset"]                   # the same moment in the second file

    python -m vstudio.avsync screen.mp4 camera.mov [--method audio|timestamps|auto] [--max-offset 600]

``offset`` = seconds to ADD to a time in the first file to reach the same moment in the second one (the camera
started 3 s before the screen recording -> offset +3.0).

audio (auto when both files have sound): the onset envelopes (10 ms log-energy rises) of both tracks are
cross-correlated (FFT) within +-max_offset; the peak is refined to sub-hop precision. ``confidence`` = how far the
peak stands above the rest of the correlation (z-score / 10, capped at 1): below ~0.3 the match is a guess, so the
sync raises instead of guessing (pass the offset by hand). Two mics in one room correlate fine (the same speech, different
rooms tone); a muted file cannot be synced by audio.
timestamps: container ``creation_time`` tags (cameras and screen recorders stamp the recording start); offset =
start(first) - start(second). Coarse (whole seconds, clock drift between devices): auto uses it only when a file
has no sound; otherwise ask for it with ``--method timestamps``.
"""
import argparse
import json
import sys
from datetime import datetime

import numpy as np

HOP = 0.01
SR = 4000


def envelope(x, sr=SR, hop=HOP):
    """Mono samples -> onset envelope (positive log-energy change per hop), zero-mean / unit-variance."""
    x = np.asarray(x, np.float32)
    if x.ndim > 1:
        x = x.mean(1)
    n = int(round(hop * sr))
    m = len(x) // n
    if m < 4:
        return np.zeros(max(m, 1), np.float32)
    e = np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(1) + 1e-10)
    le = np.log(e + 1e-4)
    on = np.maximum(0.0, np.diff(le, prepend=le[0]))
    on = on - on.mean()
    sd = on.std()
    return (on / sd).astype(np.float32) if sd > 0 else on.astype(np.float32)


def _decode(path, start=None, dur=None):
    from .audio import decode_audio
    return decode_audio(path, sr=SR, channels=1, start=start, dur=dur)[:, 0]


def offset_from_envelopes(ea, eb, max_offset=600.0, hop=HOP):
    """-> (offset seconds, confidence 0..1): the lag that best aligns ``eb`` to ``ea`` (t_b = t_a + offset)."""
    n = len(ea) + len(eb)
    size = 1 << int(np.ceil(np.log2(max(2, n))))
    fa = np.fft.rfft(ea, size)
    fb = np.fft.rfft(eb, size)
    cc = np.fft.irfft(np.conj(fa) * fb, size)          # cc[k] = sum ea[i] * eb[i + k]
    lags = np.concatenate([np.arange(0, len(eb)), np.arange(-len(ea) + 1, 0)])
    vals = np.concatenate([cc[:len(eb)], cc[size - len(ea) + 1:]]) if len(ea) > 1 else cc[:len(eb)]
    maxlag = int(max_offset / hop)
    keep = np.abs(lags) <= maxlag
    lags, vals = lags[keep], vals[keep]
    if not len(vals):
        return 0.0, 0.0
    order = np.argsort(lags)
    lags, vals = lags[order], vals[order]
    k = int(np.argmax(vals))
    peak = float(vals[k])
    frac = 0.0
    if 0 < k < len(vals) - 1:                         # parabolic refinement
        y0, y1, y2 = vals[k - 1], vals[k], vals[k + 1]
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den else 0.0
    rest = np.delete(vals, slice(max(0, k - 20), k + 21))
    z = (peak - rest.mean()) / (rest.std() + 1e-9) if len(rest) > 10 else 0.0
    conf = float(max(0.0, min(1.0, z / 10.0)))
    return round(float((lags[k] + frac) * hop), 3), round(conf, 3)


def offset_by_audio(a, b, max_offset=600.0, window=None):
    """Audio cross-correlation of two media files. ``window`` = (start, dur) of the first file to use (a long
    lesson: 5 minutes from the middle is plenty and 10x faster); the second file is searched +-max_offset around
    it. -> dict(offset, confidence, method)."""
    if window:
        s, d = window
        xa = _decode(a, start=s, dur=d)
        s2 = max(0.0, s - max_offset)
        xb = _decode(b, start=s2, dur=d + 2 * max_offset)
        off, conf = offset_from_envelopes(envelope(xa), envelope(xb), max_offset=max_offset + s - s2 + d)
        off = off + s2 - s
    else:
        off, conf = offset_from_envelopes(envelope(_decode(a)), envelope(_decode(b)), max_offset=max_offset)
    return dict(offset=round(off, 3), confidence=conf, method="audio")


def creation_time(path):
    from . import media
    v = media.ffprobe_value(path, "format_tags=creation_time")
    if not v:
        v = media.ffprobe_value(path, "stream_tags=creation_time", stream="v:0")
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def offset_by_timestamps(a, b):
    ta, tb = creation_time(a), creation_time(b)
    if ta is None or tb is None:
        return None
    return dict(offset=round(ta - tb, 3), confidence=0.3, method="timestamps")


class SyncError(RuntimeError):
    pass


def sync(a, b, method="auto", max_offset=600.0, min_confidence=0.3, offset=None):
    """Offset of ``b`` relative to ``a`` (t_b = t_a + offset). ``offset`` given -> taken as is (method "manual").
    auto = audio when both files have sound, else the container timestamps; an unsure audio match (confidence
    under ``min_confidence``) or missing timestamps raise ``SyncError`` - pass the offset by hand then."""
    if offset is not None:
        return dict(offset=float(offset), confidence=1.0, method="manual")
    from . import media
    ia, ib = media.probe(a), media.probe(b)
    both_audio = ia["has_audio"] and ib["has_audio"]
    if method == "audio" or (method == "auto" and both_audio):
        if not both_audio:
            raise SyncError("audio sync needs sound in both files")
        dur = ia["duration"]
        win = (max(0.0, dur / 2 - 150), 300.0) if dur > 900 else None
        res = offset_by_audio(a, b, max_offset=max_offset, window=win)
        if res["confidence"] < min_confidence:
            raise SyncError(f"the two recordings do not line up by sound (confidence {res['confidence']:.2f}, "
                            f"best guess {res['offset']:+.2f} s): pass the offset (camera = source + offset) or "
                            f"--method timestamps")
        return res
    res = offset_by_timestamps(a, b)
    if res is None:
        raise SyncError("no creation_time in one of the files: pass the offset by hand")
    return res


def _cli(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.avsync", description=__doc__.split("\n\n")[0])
    ap.add_argument("first")
    ap.add_argument("second")
    ap.add_argument("--method", default="auto", choices=["auto", "audio", "timestamps"])
    ap.add_argument("--max-offset", type=float, default=600.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        res = sync(a.first, a.second, a.method, a.max_offset)
    except SyncError as e:
        print(json.dumps(dict(error=str(e))), file=sys.stderr)
        return 2
    txt = json.dumps(res, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
