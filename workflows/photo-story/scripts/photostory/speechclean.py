"""Opt-in 气口 / filler / repeat cleanup of video shots with speech: the ONE shared tool, ``vstudio.cleanup``
(references/CLEANUP.md). Ambient clips are left alone unless asked.

    ("vIMG_1234", 1, "still", dict(audio="keep", cleanup="gentle"))            # this clip only
    ("vIMG_1234", 1, "still", dict(audio="keep", cleanup=dict(profile="standard", reply="确认 3 / 保留 5")))
    CLEANUP = "gentle"     # spec-wide: every audio="keep" clip (the foreground speech ones); duck/mute stay as is

Values: False / True (= gentle) / "gentle" | "standard" | "tight" | "pauses" (气口 only, no word edits) /
dict(enabled, profile, approve, keep, reply, all_confirm). Only ``auto`` edits are cut unless the creator
approves more; the EDL + review sheet are written to ``<cache>/cleanup/`` (ids in approve / keep / reply refer
to that sheet). The cleaned clip covers the source from the shot's ``off`` to the clip end, so picture and
sound both play the cleaned speech from its start (``off`` becomes 0). Transcript: ``words=`` (path next to
the clip), ``<clip>.words.json``, else ASR (vstudio.asr, cached).
"""
import os
import re

from vstudio import cleanup as CL
from vstudio import media

DEFAULT_PROFILE = "gentle"
PAUSE_KINDS = {"pause", "breath", "lead", "tail"}
PROFILES = tuple(CL.PROFILES) + ("pauses",)


def options(C, sh):
    """Resolved knob for one shot: None (off) or dict(profile, approve, keep, reply, all_confirm)."""
    v = sh.get("cleanup")
    if v is None:
        g = getattr(getattr(C, "spec", None), "CLEANUP", None)
        if not g or str(sh.get("audio", "mute")).lower() != "keep":
            return None
        v = g
    if v is False:
        return None
    o = dict(profile=DEFAULT_PROFILE, approve=None, keep=None, reply=None, all_confirm=False)
    if isinstance(v, str):
        o["profile"] = v
    elif isinstance(v, dict):
        if not v.get("enabled", True):
            return None
        o.update({k: x for k, x in v.items() if k in o and x is not None})
    elif v is not True:
        raise ValueError(f"shot {sh.get('src')}: cleanup= expects False / True / profile / dict, got {v!r}")
    if o["profile"] not in PROFILES:
        raise ValueError(f"shot {sh.get('src')}: cleanup profile {o['profile']!r}: one of {', '.join(PROFILES)}")
    return o


def _ids(v):
    if v is None or v == "":
        return set()
    if isinstance(v, (int, float)):
        return {int(v)}
    if isinstance(v, str):
        return CL.parse_reply("approve " + v)["approve"]
    return {int(x) for x in v}


def _transcript(src, given):
    if given:
        p = given if os.path.isabs(given) else os.path.join(os.path.dirname(src), given)
        if os.path.exists(p):
            return p
        raise FileNotFoundError(f"cleanup words= {given!r} not found next to {src}")
    side = os.path.splitext(src)[0] + ".words.json"
    return side if os.path.exists(side) else None


def cleaned(C, sh, src):
    """(path, off) the shot should read: the original (src, sh.off) when cleanup is off, else the cleaned
    clip (analyze --ranges off-end -> apply, idempotent) and 0. Memoised per render on ``C``."""
    off = float(sh.get("off", 0.0))
    o = options(C, sh)
    if o is None or not src:
        return src, off
    memo = C.__dict__.setdefault("_cleaned", {})
    key = (src, off, repr(sorted(o.items())), sh.get("words"))
    if key in memo:
        return memo[key]
    info = media.probe(src)
    if not info["has_audio"]:
        print(f"! {sh['src']}: cleanup= but the clip has no sound; skipped")
        memo[key] = (src, off)
        return memo[key]
    wd = os.path.join(C.cache_dir, "cleanup")
    os.makedirs(wd, exist_ok=True)
    stem = os.path.join(wd, re.sub(r"[^\w.-]", "_", os.path.splitext(os.path.basename(src))[0]) + f"_{off:.2f}")
    prof = "standard" if o["profile"] == "pauses" else o["profile"]
    edl = CL.analyze(src, transcript=_transcript(src, sh.get("words")), ranges=[(off, info["duration"])],
                     profile=prof, out=stem + ".cleanup.json", review=stem + ".review.md", force=True)
    approve, keep, allc = _ids(o["approve"]), _ids(o["keep"]), bool(o["all_confirm"])
    if o["reply"]:
        r = CL.parse_reply(o["reply"])
        approve, keep, allc = approve | r["approve"], keep | r["keep"], allc or r["all_confirm"]
    if o["profile"] == "pauses":
        keep |= {e["id"] for e in edl["edits"] if e["kind"] not in PAUSE_KINDS}
    known = {e["id"] for e in edl["edits"]}
    if (approve | keep) - known:
        print(f"! {sh['src']}: cleanup ids {sorted((approve | keep) - known)} not in {stem}.review.md; ignored")
    res = CL.apply(edl["_path"], approve=approve & known, keep=keep & known, all_confirm=allc)
    pend = [e["id"] for e in edl["edits"] if e["action"] == "confirm" and e["id"] not in res["applied"]
            and e["id"] not in keep]
    print(f"cleanup {sh['src']} ({o['profile']}): {info['duration'] - off:.2f}s -> {res['duration']:.2f}s, "
          f"{len(res['applied'])} edits cut, {len(pend)} to confirm -> {stem}.review.md")
    memo[key] = (res["out"], 0.0)
    return memo[key]
