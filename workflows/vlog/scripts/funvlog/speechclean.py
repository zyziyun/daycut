"""Speech-clip cleanup for the vlog (fun + calm): the ONE shared tool, ``vstudio.cleanup`` (气口 / filler /
repeat / 口误). See references/CLEANUP.md.

Knob (edit.json, top level and / or per shot / segment; the shot wins):
    "cleanup": false                       off
    "cleanup": true | "gentle"             on (profile gentle = the vlog default: long pauses squeezed,
                                           hesitations only, breaths kept)
    "cleanup": "standard" | "tight" | "pauses"   stronger profiles; "pauses" = 气口 only (no word edits)
    "cleanup": {"enabled": true, "profile": "gentle", "approve": [3, 5], "keep": [7],
                "reply": "确认 3,5 / 保留 7", "all_confirm": false}      per-shot creator decisions
Legacy ``"tighten": true`` = profile "standard" (it used ``cut.tighten``; now the shared tool).

Only ``auto`` edits are cut unless the creator approves more: every run writes the EDL and a review sheet
(``<cache>/cleanup/<clip>_<a>-<b>.cleanup.json`` + ``.review.md``); the ids in ``approve`` / ``keep`` /
``reply`` refer to that sheet.
"""
import os
import re

from vstudio import cleanup as CL

DEFAULT_PROFILE = "gentle"
PAUSE_KINDS = {"pause", "breath", "lead", "tail"}
PROFILES = tuple(CL.PROFILES) + ("pauses",)


def options(cfg, shot, default=True):
    """Resolved knob: dict(enabled, profile, approve, keep, reply, all_confirm). ``default`` = enabled when
    neither the config nor the shot says anything (fun speech shots: True; calm: False)."""
    o = dict(enabled=bool(default), profile=None, approve=None, keep=None, reply=None, all_confirm=False)
    if cfg.get("tighten") or shot.get("tighten"):
        o.update(enabled=True, profile="standard")
    for level, v in (("config", cfg.get("cleanup")), ("shot", shot.get("cleanup"))):
        if v is None:
            continue
        if isinstance(v, bool):
            o["enabled"] = v
        elif isinstance(v, str):
            o.update(enabled=True, profile=v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k in ("approve", "keep", "reply", "all_confirm") and level == "config":
                    continue                            # ids belong to one clip's review sheet
                if k in o:
                    o[k] = x
            o["enabled"] = bool(v.get("enabled", True))
        else:
            raise ValueError(f"cleanup: expected false / true / profile / dict, got {v!r}")
    o["profile"] = o["profile"] or DEFAULT_PROFILE
    if o["profile"] not in PROFILES:
        raise ValueError(f"cleanup profile {o['profile']!r}: one of {', '.join(PROFILES)}")
    return o


def _ids(v):
    if v is None or v == "":
        return set()
    if isinstance(v, (int, float)):
        return {int(v)}
    if isinstance(v, str):
        return CL.parse_reply("approve " + v)["approve"]
    return {int(x) for x in v}


def decisions(o, edits):
    """(approve, keep, all_confirm) from the knob, unknown ids dropped (returned as the 4th item)."""
    approve, keep, allc = _ids(o.get("approve")), _ids(o.get("keep")), bool(o.get("all_confirm"))
    if o.get("reply"):
        r = CL.parse_reply(o["reply"])
        approve |= r["approve"]
        keep |= r["keep"]
        allc = allc or r["all_confirm"]
    if o["profile"] == "pauses":                        # 气口 only: every word edit stays
        keep |= {e["id"] for e in edits if e["kind"] not in PAUSE_KINDS}
    known = {e["id"] for e in edits}
    bad = sorted((approve | keep) - known)
    return approve & known, keep & known, allc, bad


def _stem(src, a, b):
    base = re.sub(r"[^\w.-]", "_", os.path.splitext(os.path.basename(src))[0])
    return f"{base}_{a:.2f}-{b:.2f}"


def analyze(src, transcript, a, b, o, workdir):
    """``vstudio.cleanup.analyze --ranges a-b`` on one speech clip -> EDL (written to ``workdir``)."""
    os.makedirs(workdir, exist_ok=True)
    stem = os.path.join(workdir, _stem(src, a, b))
    prof = "standard" if o["profile"] == "pauses" else o["profile"]
    # force: the creator's decisions live in edit.json (approve / keep / reply), never in this EDL
    return CL.analyze(src, transcript=transcript, ranges=[(a, b)], profile=prof, out=stem + ".cleanup.json",
                      review=stem + ".review.md", force=True)


def _log(edl, o, approve, keep, allc, kept_s, bad):
    ids = CL.applied_ids(edl["edits"], approve, keep, allc)
    pend = [e["id"] for e in edl["edits"] if e["action"] == "confirm" and e["id"] not in ids and e["id"] not in keep]
    path = edl.get("_path") or ""
    review = path[:-len(".cleanup.json")] + ".review.md" if path.endswith(".cleanup.json") else None
    lg = dict(profile=o["profile"], edl=path, review=review, applied=ids, confirm_pending=pend,
              source_s=round(sum(b - a for a, b in edl["ranges"]), 3), kept_s=round(kept_s, 3))
    if bad:
        lg["unknown_ids"] = bad
    return lg


def clean_window(src, words, a, b, o, workdir, warnings):
    """Fun style (no render): kept source pieces [(a, b)] of the speech window after cleanup + a log dict.
    ``words``: the clip's words ({w, t, te}); captions follow the pieces through ``remap_words``."""
    edl = analyze(src, words, a, b, o, workdir)
    approve, keep, allc, bad = decisions(o, edl["edits"])
    if bad:
        warnings.append(f"{os.path.basename(src)}: cleanup ids {bad} not in {os.path.basename(edl['_path'])}; ignored")
    pieces = CL.keep_segments(edl["edits"], edl["ranges"], approve, keep, allc, words=edl["words"])
    pieces = [tuple(p) for p in pieces] or [(a, b)]
    return pieces, _log(edl, o, approve, keep, allc, sum(y - x for x, y in pieces), bad)


def clean_file(src, transcript, a, b, o, workdir, warnings):
    """Calm style: analyze + apply -> (cleaned clip path, its duration, log). The cleaned file starts at the
    source time ``a`` (its t=0) and replaces [a, b] of the source."""
    edl = analyze(src, transcript, a, b, o, workdir)
    approve, keep, allc, bad = decisions(o, edl["edits"])
    if bad:
        warnings.append(f"{os.path.basename(src)}: cleanup ids {bad} not in {os.path.basename(edl['_path'])}; ignored")
    res = CL.apply(edl["_path"], approve=approve, keep=keep, all_confirm=allc)
    lg = _log(edl, o, approve, keep, allc, res["duration"], bad)
    lg["out"] = res["out"]
    return res["out"], float(res["duration"]), lg


def words_sidecar(src, given=None):
    """Transcript path for a clip: ``given`` (relative to the clip's folder) or ``<clip>.words.json``."""
    if given:
        p = given if os.path.isabs(given) or os.path.exists(given) else os.path.join(os.path.dirname(src), given)
        return p if os.path.exists(p) else None
    side = os.path.splitext(src)[0] + ".words.json"
    return side if os.path.exists(side) else None
