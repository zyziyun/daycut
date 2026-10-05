"""Shared helper for the V-track cut passes: keep ranges of a body (video-only mp4 + 48 kHz wav, the files
every step passes on), frame-exact. The cutting itself is ``vstudio.cut.cut_segments`` (accurate pre-seek,
frame-grid snap, sample-exact audio with 12 ms edge fades, so A/V cannot drift); the time map is
``vstudio.cut.TimeMap``. What to cut (气口 / fillers / repeats / restarts, word-safe edges) is decided by the
shared ``vstudio.cleanup`` tool on the RAW clips; the bottom of this file only translates its raw-clip keep
spans to the body timeline (pass 1 carries the raw -> body map); every body cut writes its sidecar with
``cleanup.write_sidecar``, so ``python -m vstudio.cleanup verify`` works on every body."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
import os
import numpy as np
from vstudio import audio, cut, media

F = 30


# Snap every video timestamp to the 1/30 s grid while stream-copying. Bodies made by joining parts with the
# concat demuxer carry ~1 ms timestamp jitter; cut.cut_segments seeks with an accurate -ss, so a frame that sits
# 1 ms before its nominal time is dropped and the whole range shifts by one frame (and loses its last frame).
SNAP_BSF = f"setts=pts=round(PTS*TB*{F})/(TB*{F}):dts=round(DTS*TB*{F})/(TB*{F})"


def mux(in_v, in_a, out):
    """Stream-copy video (timestamps snapped to the frame grid) + wav into one file (.mov keeps the video
    timescale; mkv rounds pts to whole ms). Returns out."""
    media.run(["ffmpeg", "-y", "-i", in_v, "-i", in_a, "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-bsf:v", SNAP_BSF, out])
    return out


def q(t):
    """Snap to the 30 fps frame grid."""
    return round(t * F) / F


def remap(keep):
    """f(old_t) -> new_t for a sorted list of kept (s, e) ranges; a cut-out time maps to where the next
    kept range starts (vstudio TimeMap, snap="fwd")."""
    tm = cut.TimeMap.from_segments(keep)

    def m(t):
        v = tm.to_final(t, snap="fwd")
        return round(tm.duration if v is None else v, 3)
    return m


def cut_sources(segs, out_v, out_a, tmp="segtmp", crf=12, fade=0.012):
    """segs: [(src, t0, t1), ...] in output order; each src carries video AND audio. Consecutive ranges of
    one source go through one cut.cut_segments call. Writes out_v (video only) + out_a (48 kHz stereo
    PCM wav). Returns the total length in seconds (frame-quantised)."""
    groups = []
    for src, a, b in segs:
        if groups and groups[-1][0] == src:
            groups[-1][1].append((a, b))
        else:
            groups.append((src, [(a, b)]))
    os.makedirs(tmp, exist_ok=True)
    parts, pcm, total = [], [], 0.0
    for k, (src, rng) in enumerate(groups):
        p = os.path.join(tmp, f"g{k:03d}.mov")
        tm = cut.cut_segments(src, rng, p, fps=F, crf=crf, fade=fade, workers=6, tmpdir=os.path.join(tmp, f"g{k:03d}"))
        parts.append(p); pcm.append(audio.decode_audio(p)); total += tm.duration
    lst = os.path.join(tmp, "groups.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
    media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v:0", "-c", "copy", out_v])
    audio.write_wav(out_a, np.concatenate(pcm), audio.SR)
    return total


def cut_body(in_v, in_a, keep, out_v, out_a, tmp="segtmp"):
    """Keep `keep` [(s, e)] of the body (in_v video-only + in_a wav) -> out_v + out_a. Returns seconds."""
    os.makedirs(tmp, exist_ok=True)
    av = mux(in_v, in_a, os.path.join(tmp, "body_av.mov"))     # cut_segments wants a/v in one file
    return cut_sources([(av, s, e) for s, e in keep], out_v, out_a, tmp)


# ---------------------------------------------------------------- pass bookkeeping (idempotent re-runs)
# Every cut pass derives from an IMMUTABLE parent, never from whatever segs.json currently holds:
#   cut_pass1  -> segs.pass1.json  (root; body_v.mp4 / body_rt.mp4 timeline)
#   strict     -> segs.strict.json (always from segs.pass1.json)
#   drop       -> segs.drop.json   (from segs.strict.json, or segs.pass1.json when no strict pass was run)
# segs.json is a copy of the newest stage (what anchors.py / compose.py read). Each pass checks that the body it
# is given has the parent's length, so applying a pass to the wrong (already cut) body is refused, not silently
# mis-cut.
STAGES = ("pass1", "strict", "drop")


def stage_path(stage):
    return f"segs.{stage}.json"


def save_stage(stage, d, parent=None):
    import json
    d = dict(d, stage=stage, parent=parent)
    for later in STAGES[STAGES.index(stage) + 1:]:       # a re-run invalidates every stage cut from the old one
        if os.path.exists(stage_path(later)):
            os.replace(stage_path(later), f"segs.{later}.stale.json")
            print(f"note: segs.{later}.json was cut from the previous {stage} body -> segs.{later}.stale.json; "
                  f"re-run that pass on the new body")
    for p in (stage_path(stage), "segs.json"):
        with open(p, "w") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    return d


def load_stage(stage):
    """segs.<stage>.json; a pre-versioning work dir (only segs.json, no 'stage' key) counts as pass1."""
    import json
    if os.path.exists(stage_path(stage)):
        return json.load(open(stage_path(stage)))
    if stage == "pass1" and os.path.exists("segs.json"):
        d = json.load(open("segs.json"))
        if d.get("stage") in (None, "pass1") and "words" not in d:
            return d
    return None


def wav_seconds(path):
    import soundfile as sf
    return sf.info(path).duration


def pick_parent(in_audio, candidates, tol=0.07):
    """First stage in `candidates` whose body length matches the wav `in_audio` (within ~2 frames).
    Raises SystemExit with an explanation when none does (stale / wrong body)."""
    dur = wav_seconds(in_audio); seen = []
    for st in candidates:
        d = load_stage(st)
        if d is None: continue
        seen.append(f"{st} {d['total']:.2f}s")
        if abs(d['total'] - dur) <= tol:
            return st, d
    raise SystemExit(f"{in_audio} is {dur:.2f}s but no parent cut matches it ({', '.join(seen) or 'no segs.*.json'}). "
                     "Pass the body that stage was cut from (strict: the pass-1 / retouched body; drop: the strict "
                     "body, or the pass-1 body when no strict pass was run), or re-run the earlier pass.")


# ---------------------------------------------------------------- vstudio.cleanup glue (raw clip <-> body)
# cut_pass1 runs cleanup.analyze on every raw clip (only the hand-written ranges) -> cleanup.c<N>.json, with edit
# ids unique across clips so ONE reply ("确认 3,5,9 / 保留 7") covers the whole video. segs.pass1.json records each
# body segment's raw span (clip, t0, t1) and body span (b0, b1); later passes intersect the cleanup keep spans with
# it to get body ranges, so the retouched body is cut and never re-rendered. Every body cut writes its verify
# sidecar with ``cleanup.write_sidecar`` (source = the parent body, words = ``on_body(body words)``).
PAUSE_KINDS = ("pause", "breath", "lead", "tail")     # 气口: applied in pass 1 (squeezed, not deleted)


def edl_name(clip):
    return f"cleanup.c{clip}.json"


def cleanup_overrides(mod):
    """cleanup overrides from an edit_list / strict module: CLEANUP = {...} plus the legacy pass-1 knobs
    MAXGAP (pauses longer than this are squeezed -> pause_min) and KEEPGAP (what they are squeezed to)."""
    ov = dict(getattr(mod, "CLEANUP", None) or {})
    if hasattr(mod, "MAXGAP"):
        ov.setdefault("pause_min", float(mod.MAXGAP))
    if hasattr(mod, "KEEPGAP"):
        k = float(mod.KEEPGAP)
        for key in ("gap_min", "gap_max", "gap_sentence"):
            ov.setdefault(key, k)
    return ov


def load_edls(stage):
    """{clip: EDL dict} named by segs.pass1.json."""
    import json
    out = {}
    for c, name in (stage.get("edls") or {}).items():
        if not os.path.exists(name):
            raise SystemExit(f"{name} is missing: re-run cut_pass1.py (it writes the cleanup EDLs)")
        with open(name, encoding="utf-8") as f:
            out[int(c)] = json.load(f)
    return out


def intersect(spans, a, b, min_len=1e-3):
    """Pieces of sorted spans [(s, e)] inside [a, b]."""
    return [(max(s, a), min(e, b)) for s, e in spans if min(e, b) - max(s, a) > min_len]


def body_spans(segs, keep_by_clip):
    """Pass-1 body ranges [(b0, b1)] that survive: each pass-1 segment (clip, raw t0..t1 -> body b0..b1)
    intersected with that clip's cleanup keep spans (raw seconds). Merged, in body order."""
    out = []
    for s in segs:
        for a, b in intersect(keep_by_clip.get(s["clip"], []), s["t0"], s["t1"]):
            a, b = s["b0"] + a - s["t0"], s["b0"] + b - s["t0"]
            if out and a - out[-1][1] < 1e-6:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
    return [tuple(x) for x in out]


def raw_to_body(segs, clip, t):
    """Pass-1 body second of raw second t of `clip` (a cut-out time -> the start of the next kept segment)."""
    nxt = None
    for s in segs:
        if s["clip"] != clip:
            continue
        if s["t0"] - 1e-6 <= t <= s["t1"] + 1e-6:
            return s["b0"] + t - s["t0"]
        if s["t0"] > t and (nxt is None or s["t0"] < nxt["t0"]):
            nxt = s
    return nxt["b0"] if nxt else None


def word_remap(words, keep):
    """Words {w, b0, b1, sid} whose midpoint survives `keep` (body seconds) -> new body seconds."""
    tm = cut.TimeMap.from_segments(list(keep))
    out = []
    for w in words:
        if tm.to_final((w["b0"] + w["b1"]) / 2) is None:
            continue
        a, b = tm.to_final(w["b0"], snap="fwd"), tm.to_final(w["b1"], snap="back")
        if a is None or b is None:
            continue
        out.append(dict(w, b0=round(a, 3), b1=round(max(a, b), 3)))
    return out


def on_body(words):
    """Body words {w, b0, b1, ...} -> {w, t, te} on the body timeline (the shape ``cleanup.write_sidecar`` /
    ``cleanup.load_words`` read; body words also carry the RAW clip time as ``t``, which must not be used)."""
    return [dict(w=w["w"], t=w["b0"], te=w["b1"]) for w in words]
