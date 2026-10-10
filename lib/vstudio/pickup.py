"""Pickups (补录): splice a short re-recorded insert into a clip at a point, or in place of a range.

    from vstudio import pickup
    span = pickup.speech_span(words, duration)          # the insert's speech (+ short handles), or None
    info = pickup.splice(base, insert, at=12.3, end=14.1, out="spliced.mp4", span=span)

The output is ``base[0:at] + insert[span] + base[end:]`` (``end == at`` inserts without replacing), re-encoded once:
  - level: the insert's speech is gained to the base's speech level around the splice (gated frame RMS, +-12 dB);
  - room tone: when the base's noise floor is higher than the insert's, a loop of the base's quietest half second
    is mixed under the insert, so the background does not drop out for the pickup;
  - joins: an equal-power ``xfade`` (default 40 ms) audio crossfade centred on both joins, length-neutral (each
    side borrows audio from beyond its edge: the base past ``at`` / before ``end``, the insert's own handles);
  - picture: hard cuts on frame boundaries; the insert is scaled / padded to the base's size and frame rate.
Every cut point is snapped to the base's / insert's frame grid so the audio (sample exact) and the picture agree.
-> {out, at, end, inserted (s on the new timeline), span [a, b] in the insert, gain_db, room_db, base_db,
    insert_db, duration}
"""
import os
import tempfile

import numpy as np

from . import media
from .audio import SR, decode_audio, write_wav

FRAME_S = 0.05
MAX_GAIN_DB = 12.0


def _db(x):
    return 20 * np.log10(max(float(x), 1e-9))


def frame_rms(x, sr=SR, frame=FRAME_S):
    """(n, ch) or (n,) float audio -> RMS per ``frame`` seconds (mono mix)."""
    m = x.mean(1) if x.ndim > 1 else x
    n = max(1, int(frame * sr))
    k = len(m) // n
    if not k:
        return np.array([np.sqrt(np.mean(m ** 2)) if len(m) else 0.0])
    return np.sqrt(np.mean(m[:k * n].reshape(k, n) ** 2, axis=1))


def speech_level(x, sr=SR):
    """Gated speech level (dB): the mean of the louder 40 % of 50 ms frames above -60 dBFS (None: silence)."""
    r = frame_rms(x, sr)
    r = r[r > 1e-3]
    if not len(r):
        return None
    top = np.sort(r)[int(len(r) * 0.6):]
    return _db(np.sqrt(np.mean(top ** 2)))


def noise_floor(x, sr=SR):
    """Noise floor (dB): the 10th percentile of the 50 ms frame RMS."""
    r = frame_rms(x, sr)
    return _db(np.percentile(r, 10)) if len(r) else -120.0


def quietest(x, sr=SR, dur=0.5):
    """The quietest ``dur`` seconds of ``x`` (room tone)."""
    n = int(dur * sr)
    if len(x) <= n:
        return x.copy()
    r = frame_rms(x, sr)
    w = max(1, int(dur / FRAME_S))
    if len(r) <= w:
        return x[:n].copy()
    s = np.convolve(r ** 2, np.ones(w), "valid")
    i = int(np.argmin(s)) * int(FRAME_S * sr)
    return x[i:i + n].copy()


def loop_to(seg, n, xf=None):
    """Loop ``seg`` (n0, ch) to ``n`` samples with short equal-power crossfades at the seams."""
    if not len(seg):
        return np.zeros((n,) + seg.shape[1:], np.float32)
    xf = min(xf or int(0.05 * SR), len(seg) // 3)
    out = np.zeros((n,) + seg.shape[1:], np.float32)
    pos = 0
    step = len(seg) - xf if xf else len(seg)
    ang = np.linspace(0, np.pi / 2, xf, dtype=np.float32)[:, None] if xf else None
    while pos < n:
        piece = seg[: min(len(seg), n - pos)].copy()
        if pos and xf and len(piece) >= xf:
            piece[:xf] *= np.sin(ang)
            out[pos:pos + xf] *= np.cos(ang)
            out[pos:pos + len(piece)] += piece
        else:
            out[pos:pos + len(piece)] = piece
        pos += step
    return out


def speech_span(words, duration, pad_in=0.12, pad_out=0.2):
    """[{w, t, te}] of the insert -> (a, b) = its speech with short handles, or None when nothing was said."""
    ws = [w for w in words or [] if str(w.get("w", "")).strip()]
    if not ws:
        return None
    a = max(0.0, float(ws[0]["t"]) - pad_in)
    b = min(float(duration), float(ws[-1]["te"]) + pad_out)
    return (a, b) if b - a > 0.1 else None


def _grid(t, fps):
    return round(round(float(t) * fps) / fps, 6)


def _xfade(A, B):
    """Equal-power crossfade of two equal-length (n, ch) arrays."""
    ang = np.linspace(0, np.pi / 2, len(A), dtype=np.float32)[:, None]
    return A * np.cos(ang) + B * np.sin(ang)


def splice(base, insert, at, end=None, out=None, span=None, xfade=0.04, crf=18):
    """See the module doc. ``at`` / ``end`` in base seconds, ``span`` (a, b) in insert seconds (default: all)."""
    bi, ii = media.probe(base), media.probe(insert)
    fps = float(bi.get("fps") or 30.0)
    bdur, idur = float(bi["duration"]), float(ii["duration"])
    W = int(bi.get("display_w") or bi["w"]) // 2 * 2
    H = int(bi.get("display_h") or bi["h"]) // 2 * 2
    a = _grid(min(max(0.0, float(at)), bdur), fps)
    b = _grid(min(max(a, float(end if end is not None else at)), bdur), fps)
    ia, ib = span if span else (0.0, idur)
    ifps = float(ii.get("fps") or fps)
    ia, ib = _grid(max(0.0, ia), ifps), _grid(min(idur, ib), ifps)
    ins = round(round((ib - ia) * fps) / fps, 6)                     # what the insert lasts on the base's grid
    if ins < 2 / fps:
        raise ValueError("the pickup is too short")
    ib = ia + ins

    # ---- audio (48 kHz stereo, sample exact)
    h = max(1, int(round(xfade * SR / 2)))
    xb = decode_audio(base, SR, 2) if bi.get("has_audio") else np.zeros((int(bdur * SR), 2), np.float32)
    xi = decode_audio(insert, SR, 2) if ii.get("has_audio") else np.zeros((int(idur * SR), 2), np.float32)
    A, B = int(round(a * SR)), int(round(b * SR))
    I0, I1 = int(round(ia * SR)), int(round(ib * SR))
    nb = len(xb)
    xb = np.concatenate([xb, np.zeros((max(0, B + h - len(xb)), 2), np.float32)])
    xi = np.concatenate([np.zeros((h, 2), np.float32), xi, np.zeros((max(0, I1 + h - len(xi)) + h, 2), np.float32)])
    I0, I1 = I0 + h, I1 + h                                           # xi now has h samples of pre-roll
    around = np.concatenate([xb[max(0, A - 8 * SR):A], xb[B:B + 8 * SR]])
    body = xi[I0:I1]
    lb, li = speech_level(around), speech_level(body)
    gain_db = float(np.clip(lb - li, -MAX_GAIN_DB, MAX_GAIN_DB)) if lb is not None and li is not None else 0.0
    g = np.float32(10 ** (gain_db / 20))
    seg = xi[I0 - h:I1 + h] * g                                       # the insert with its handles, levelled
    room_db = None
    fb, fi = noise_floor(around), noise_floor(body * g)
    if fb > fi + 3 and len(around) > SR // 2:
        rt = quietest(around)
        need = 10 ** (fb / 10) - 10 ** (fi / 10)                       # power to add, so the floors match
        r = float(np.sqrt(np.mean(rt ** 2))) or 1e-9
        tone = loop_to(rt, len(seg)) * np.float32(np.sqrt(need) / r)
        seg = seg + tone
        room_db = round(_db(np.sqrt(need)), 1)
    left, right = xb[:A], xb[B:max(B, nb)]
    joined = np.concatenate([left, seg[h:-h], right])
    # centred crossfades: base -> insert at A, insert -> base at A + len(insert)
    if A >= h:
        joined[A - h:A + h] = _xfade(xb[A - h:A + h], seg[:2 * h])
    J = A + (len(seg) - 2 * h)
    if len(right) >= h:
        joined[J - h:J + h] = _xfade(seg[-2 * h:], xb[B - h:B + h])
    peak = float(np.max(np.abs(joined))) if len(joined) else 0.0
    if peak > 0.99:
        joined *= np.float32(0.99 / peak)

    # ---- picture: base[0:a] + insert[ia:ib] + base[b:], one encode
    out = out or os.path.splitext(base)[0] + ".pickup.mp4"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g}"
    parts, labels = [], []
    if a > 0:
        parts.append(f"[0:v]trim=0:{a:.6f},setpts=PTS-STARTPTS,{fit}[v0]")
        labels.append("[v0]")
    parts.append(f"[1:v]trim={ia:.6f}:{ib:.6f},setpts=PTS-STARTPTS,{fit}[v1]")
    labels.append("[v1]")
    if b < bdur - 0.5 / fps:
        parts.append(f"[0:v]trim=start={b:.6f},setpts=PTS-STARTPTS,{fit}[v2]")
        labels.append("[v2]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[v]")
    with tempfile.TemporaryDirectory() as td:
        wav = write_wav(os.path.join(td, "a.wav"), joined, SR)
        tmp = out + ".part.mp4"
        media.run(["ffmpeg", "-y", "-v", "error", "-i", base, "-i", insert, "-i", wav,
                   "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "2:a:0",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", tmp])
        os.replace(tmp, out)
    return dict(out=out, at=a, end=b, inserted=round(len(seg[h:-h]) / SR, 6), span=[ia, ib],
                gain_db=round(gain_db, 2), room_db=room_db,
                base_db=None if lb is None else round(lb, 1), insert_db=None if li is None else round(li, 1),
                duration=round(len(joined) / SR, 6))


def shift_words(words, at, end, inserted, pickup_words, span_start):
    """The spliced file's words: the base's before ``at`` + the insert's (shifted from ``span_start`` to ``at``) +
    the base's from ``end`` on (shifted by ``inserted - (end - at)``). Base words inside [at, end) are gone."""
    d = inserted - (end - at)
    out = []
    for w in words:
        mid = (float(w["t"]) + float(w["te"])) / 2
        if mid < at:
            out.append(dict(w))
    for w in pickup_words:
        t, te = float(w["t"]) - span_start + at, float(w["te"]) - span_start + at
        if te <= at or t >= at + inserted:
            continue
        out.append(dict(w, t=round(max(at, t), 3), te=round(min(at + inserted, te), 3)))
    for w in words:
        mid = (float(w["t"]) + float(w["te"])) / 2
        if mid >= end and not (mid < at):
            out.append(dict(w, t=round(float(w["t"]) + d, 3), te=round(float(w["te"]) + d, 3)))
    return out
