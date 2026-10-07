"""Structured (JSON-able) views of a batch for UIs - the desk app and ``python -m vstudio.batch <cmd> --json``.

    from vstudio.batch import api
    api.recipes()                       # [{name, label, description, inputs [...], row_keys, stages}]
    api.review_items(batch_dir)         # review cards, every path absolute
    api.job_detail(batch_dir, "ep02")   # job + stages + events + transcript of its range + cleanup edits (cut state
                                        # under the current reply) + captions (proofread changes) + QC + exports
    api.verify_manifest(manifest)       # recompute the package confirmation code

Paths are absolute; nothing here writes to the batch.
"""
import os

from .store import Store
from .util import read_json, sha1_json

REVIEW_STATES = ("done", "approved", "needs-replan", "packaged", "failed")


def _copy_drafted(p, rows):
    """Which post-copy fields the copy stage drafted (still unedited) and from what: {keys, source, notes}."""
    from .edits import drafted_copy
    d, src = drafted_copy(rows)
    keys = [k for k in d if not p.get(k)]
    return dict(keys=keys, source=src, notes=list(((rows.get("copy") or {}).get("out") or {}).get("notes") or [])) \
        if keys else None


def recipes():
    from . import recipes as R
    return [R.REGISTRY[n].meta() for n in R.names()]


def verify_manifest(manifest):
    """Recompute a package manifest's confirmation code (``package`` writes it): dict(ok, code, stored, items,
    reason). ``manifest``: the dict or a path to manifest.json."""
    man = read_json(manifest) if isinstance(manifest, str) else manifest
    if not isinstance(man, dict) or "items" not in man:
        return dict(ok=False, code=None, stored=None, items=0, reason="no manifest")
    code = sha1_json(dict(batch=man.get("batch"), schedule=man.get("schedule"), items=man.get("items")))[:12]
    ok = code == man.get("confirmation_code")
    return dict(ok=ok, code=code, stored=man.get("confirmation_code"), items=len(man.get("items") or []),
                reason=None if ok else "manifest changed after packaging (code mismatch)")


def review_items(batch_dir):
    """``review.collect`` with absolute paths (sheet, snippet, files) plus each export's platform / cover / post."""
    from . import review
    st = Store(batch_dir)
    try:
        items = review.collect(st)
        rows = {j["id"]: st.stage_rows(j["id"]) for j in st.jobs(REVIEW_STATES)}
    finally:
        st.close()
    rdir = os.path.join(os.path.abspath(batch_dir), "review")
    for it in items:
        for k in ("sheet", "snippet"):
            if it.get(k):
                it[k] = os.path.normpath(os.path.join(rdir, it[k]))
        it["files"] = [os.path.normpath(os.path.join(rdir, f)) for f in it.get("files") or [] if f]
        ex = ((rows.get(it["id"]) or {}).get("export") or {}).get("out") or {}
        it["exports"] = [dict(platform=e.get("platform"), orientation=e.get("orientation"), file=e.get("file"),
                              cover=e.get("cover"), post=e.get("post"), duration=e.get("duration"),
                              variant=e.get("variant")) for e in ex.get("exports") or []]
        qc = ((rows.get(it["id"]) or {}).get("qc") or {}).get("out") or {}
        it["suggestions"] = qc.get("suggestions") or []
    return items


def _cut_state(edits, reply):
    from vstudio.cleanup import parse_reply
    r = parse_reply(reply) if reply else dict(approve=set(), keep=set(), all_confirm=False)
    out = []
    for e in edits or []:
        eid = e["id"]
        if e["action"] == "auto":
            cut = eid not in r["keep"]
        elif e["action"] == "confirm":
            cut = (eid in r["approve"] or r["all_confirm"]) and eid not in r["keep"]
        else:
            cut = eid in r["approve"]
        out.append(dict(id=eid, t0=e["t0"], t1=e["t1"], kind=e["kind"], text=e.get("text", ""), action=e["action"],
                        reason=e.get("reason", ""), confidence=e.get("confidence"), words=e.get("words") or [],
                        before=e.get("before", ""), after=e.get("after", ""), cut=bool(cut)))
    return out


def _screen_scans(export_out):
    """What the output scans of each rendered vertical master saw inside the screen crop, per canvas ("1080x1440"):
    {canvas: dict(visible_popups [dict(t, dur, cover, box)], static_overlays [dict(t, dur, box, cover, evidence,
    hug, items)])} - a list is None when that master predates the scan; {} for jobs without a screen crop."""
    plans = (((export_out or {}).get("privacy") or {}).get("plans")) or {}
    return {c: dict(visible_popups=(pl.get("screen") or {}).get("visible"),
                    static_overlays=(pl.get("screen") or {}).get("static")) for c, pl in plans.items()}


def job_detail(batch_dir, jid, words=True):
    """Everything about one job: row, stages, last events, the transcript of its source range (each word with
    ``cut``: removed by an applied cleanup edit / row cut under the current reply), the cleanup edits with their
    effective state, captions (final cues + proofread changes / rejected / low-confidence words), verify, QC
    (checks, suggestions, ``screen``: the screen-crop output scans per canvas) and exports. Raises KeyError for
    an unknown job."""
    st = Store(batch_dir)
    try:
        j = st.job(jid)
        if not j:
            raise KeyError(f"unknown job {jid}")
        rows = st.stage_rows(jid)
        evs = st.events(30, job=jid)
        spec = st.spec
        from . import edits as ED
        hist = ED.history(st, jid)
        pending = (st.meta("pending", {}) or {}).get(jid) or []
        timing = [dict(event=t["event"], what=t["what"], seconds=t["seconds"], ts=t["ts"]) for t in st.timing(jid)]
    finally:
        st.close()
    out = lambda s: (rows.get(s) or {}).get("out") or {}  # noqa: E731
    p = j["params"] or {}
    reply = p.get("cleanup_reply") or ""
    cl, cm, pr, vf, qc, ex, pv = (out(s) for s in ("cleanup", "compose", "proofread", "verify", "qc", "export",
                                                   "preview"))
    parts, patched = [], []
    for part in ("body", "hook"):
        E = read_json(cl.get(part)) if cl.get(part) else None
        if E:
            parts.append(dict(part=part, ranges=E.get("ranges"), stats=E.get("stats"),
                              edits=_cut_state(E.get("edits"), reply)))
            cut_ids = {e["id"] for e in parts[-1]["edits"] if e["cut"]}
            patched += [e for e in E.get("edits") or [] if e["id"] in cut_ids and e.get("patch")]
    he = cl.get("hook_edge")
    transcript = None
    tr_path = out("asr").get("transcript")
    if words and tr_path:
        from vstudio import cleanup as C
        tr = read_json(tr_path)
        raw = [w for sg in (tr.get("segments") or []) for w in sg.get("words") or []] if isinstance(tr, dict) else []
        if raw and all("start" in w and "end" in w for w in raw):     # whisper words keep their leading spaces
            W = [dict(w=str(w.get("word", "")), t=float(w["start"]), te=float(w["end"])) for w in raw]
        else:
            W = [dict(w=w["w"], t=w["t"], te=w["te"]) for w in C.load_words(tr)]
        if patched:                                   # a filler-merged cut keeps the word it trimmed (its caption too)
            W = C.patch_onsets(W, patched, {e["id"] for e in patched})
        cuts = [(e["t0"], e["t1"]) for pt in parts for e in pt["edits"] if e["cut"]]
        cuts += [(float(c[0]), float(c[1])) for c in cl.get("cuts") or []]
        spans = [tuple(cl.get("edges") or p.get("range") or (0, 0))]
        if he:
            spans.append(tuple(he["edge"]))
        elif (p.get("hook") or {}).get("src"):
            spans.append(tuple(p["hook"]["src"]))
        transcript = []
        for a, b in spans:
            seg = []
            for w in W:
                m = (w["t"] + w["te"]) / 2
                if a <= m <= b:
                    seg.append(dict(w=w["w"], t=w["t"], te=w["te"], cut=any(x <= m <= y for x, y in cuts)))
            transcript.append(dict(range=[a, b], text="".join(w["w"] for w in seg if not w["cut"]).strip(),
                                   words=[dict(w, w=w["w"].strip()) for w in seg]))
    prr = read_json(pr.get("report"), {}) if pr.get("report") else {}
    cues = (read_json(pr.get("cues"), {}) or {}).get("cues") if pr.get("cues") else \
        ((read_json(cm.get("cues"), {}) or {}).get("cues") if cm.get("cues") else None)
    vr = read_json(vf.get("report"), {}) if vf.get("report") else {}
    ov_missed = []
    if cues and p.get("caption_overrides"):            # review caption edits, as they will be burned
        asr_cues = (read_json(cm.get("cues"), {}) or {}).get("cues") if cm.get("cues") else None
        tl = read_json(cm.get("timeline")) if cm.get("timeline") else None
        to_out = None
        if tl:
            from .lfsplit import _out_time
            to_out = lambda t: _out_time(tl, t)  # noqa: E731
        cues, _, ov_missed = ED.apply_caption_overrides(cues, p["caption_overrides"], asr_cues=asr_cues, to_out=to_out)
    if cues:
        cues = [dict(c, i=k) for k, c in enumerate(cues)]
    from .metrics import review_seconds
    edit = dict(range=p.get("range"), hook=p.get("hook"), hook_pick=p.get("hook_pick"),
                hook_candidates=ED.hook_candidates(p), cover=p.get("cover") if isinstance(p.get("cover"), dict) else None,
                copy=ED.effective_copy(p, rows), copy_drafted=_copy_drafted(p, rows), caption_overrides=p.get("caption_overrides") or [],
                caption_overrides_missed=ov_missed, history=hist,
                pending=pending, review_s=review_seconds(timing))
    return dict(
        job={k: j[k] for k in ("id", "item", "variant", "state", "qc", "qc_reasons", "review", "review_reason",
                                "pilot", "sample", "cost", "params")},
        recipe=spec.get("recipe"),
        stages=[dict(name=k, state=r["state"], seconds=r["seconds"], error=r["error"], cached=bool(r["cached"]),
                     attempts=r["attempts"]) for k, r in rows.items()],
        events=evs,
        cleanup=dict(reply=reply, parts=parts, row_cuts=cl.get("cuts") or [], edges=cl.get("edges"), hook_edge=he,
                     confirm=cl.get("confirm"), saved_s=cl.get("saved_s")),
        transcript=transcript,
        captions=dict(cues=cues, provider=prr.get("provider"), model=prr.get("model"), changes=prr.get("changes") or [],
                      rejected=prr.get("rejected") or [], warnings=prr.get("warnings") or [],
                      low_confidence=prr.get("low_confidence") or [], fillers_left=prr.get("fillers_left") or [],
                      filler_edges=prr.get("filler_edges") or []),
        verify={k: dict(ok=v.get("ok"), missing=v.get("missing"), variants=v.get("variants"))
                for k, v in (vr or {}).items() if isinstance(v, dict)},
        qc=dict(status=qc.get("status"), reasons=qc.get("reasons") or [], warnings=qc.get("warnings") or [],
                checks=qc.get("checks") or [], suggestions=qc.get("suggestions") or [],
                screen=_screen_scans(ex)),
        media=dict(final=cm.get("final") or cm.get("master"), duration=cm.get("duration"), sheet=pv.get("sheet"),
                   snippet=pv.get("snippet"), exports=ex.get("exports") or [], length_fit=ex.get("length_fit") or []),
        edit=edit)


__all__ = ["recipes", "review_items", "job_detail", "verify_manifest"]
