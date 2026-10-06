"""In-review job edits (``job edit``) and targeted re-runs (``job rerun``).

    python -m vstudio.batch job edit  --batch B --job ep02 --op caption --cue 7 --text "这是 RAG 的核心"
    python -m vstudio.batch job edit  --batch B --job ep02 --op trim --start 315.2 --end 360.0
    python -m vstudio.batch job edit  --batch B --job ep02 --op hook --pick 1          # -1 = no cold open
    python -m vstudio.batch job edit  --batch B --job ep02 --op cover --t 12.5 --text "RAG的上限｜数据质量"
    python -m vstudio.batch job edit  --batch B --job ep02 --op copy --title "..." --body "..." --tags RAG,LLM
    python -m vstudio.batch job edit  --batch B --job ep02 --op undo                    # last edit of the job
    python -m vstudio.batch job rerun --batch B --job ep02 [--json-events]

Every op changes the job's params (stored in ``batch.db``; the edit itself goes to the ``edits`` table, so a later
``plan`` re-applies it) and returns which stages it made stale: the stages whose input key changes (the same
keys the scheduler uses), e.g. caption / cover -> export, verify-free; trim -> cleanup and everything after.
``job rerun`` runs exactly those (the scheduler re-checks the job, unchanged stages are cache hits) and puts the
job back for review. ``longform-split`` keeps the caption-free vertical masters of the last export
(``jobs/<id>/export.masters/``), so a caption / cover edit only re-burns and re-exports (no re-cut, no master
render).

Ops:
  caption --cue I --text T   the captions must match the audio: accepted only when ``vstudio.proofread.faithful``
                             passes against the cue as shown, the ASR text under it, or the re-ASR (verify) of the
                             cut - mis-heard spans swapped for sound-alikes, no word added or dropped. Stored as
                             ``caption_overrides`` [{i, from, to}] (applied at export, so the proofread / LLM pass
                             is not repeated); the fixed spans are appended to the batch client's glossary.
  trim --start A --end B     new source range, snapped to word edges (``vstudio.cleanup.snap_range``).
  hook --pick K              K-th of ``hook_candidates`` (plan-segments) / ``hooks``; -1 removes the cold open.
  cover --t S --text T       cover frame at S output seconds (longform-split: mapped to the source through the
                             compose timeline -> ``cover_shot``) and cover text (``big1 | big2``).
  copy --title --body --tags post copy with the platform title-length checks; the published post files are
                             rewritten in place (no render), the stage keys keep the original copy
                             (``_copy_orig``), only QC (title length) re-runs.
  undo                       reverts the job's last edit (params before it).
"""
import os
import re
import time

from . import recipes as RC  # noqa: F401
from .run import job_dict, load_recipe, stage_key
from .store import Store
from .util import read_json, write_json

OPS = ("caption", "trim", "hook", "cover", "copy")
MIN_CLIP_S = 3.0


class EditError(ValueError):
    pass


# --------------------------------------------------------------------------- helpers
def _rows_out(rows, st):
    return (rows.get(st) or {}).get("out") or {}


def stale_stages(recipe, spec, job, new_params, rows):
    """Stages that will (re-)run for ``job`` with ``new_params``: key changed, not done, or downstream of one."""
    nj = dict(job, params=new_params)
    out, keys = [], {}
    for st in recipe.order():
        if not st.enabled(nj, spec):
            continue
        dep_rows = {}
        for d in st.deps:
            r = dict(rows.get(d) or {})
            if d in keys and d in out:
                r.update(key=keys[d], state="done", out=dict(r.get("out") or {}, digest="~stale"))
            dep_rows[d] = r
        k = stage_key(st, nj, spec, dep_rows)
        keys[st.name] = k
        r = rows.get(st.name)
        if not r or r["state"] != "done" or r["key"] != k:
            out.append(st.name)
    return out


REVIEWED = ("done", "approved", "packaged", "needs-replan")


def adopt_drift(store, recipe, spec, job, rows):
    """A rendered job whose stage keys drifted since its run (an engine update, a learned confirm policy): the
    reviewer is looking at those outputs, so they are adopted under the current keys - an edit then re-runs only
    what IT changes, never a silent re-cut. -> adopted stage names (``rows`` updated in place)."""
    adopted, cur = [], {}
    for st in recipe.order():
        if not st.enabled(job, spec):
            continue
        r = rows.get(st.name)
        if not r or r["state"] != "done":
            return adopted                            # not fully rendered: nothing to protect
        cur[st.name] = stage_key(st, job, spec, {d: rows.get(d) for d in st.deps})
    for st in recipe.order():
        if st.name not in cur:
            continue
        k = stage_key(st, job, spec, {d: rows.get(d) for d in st.deps})   # with the deps adopted so far
        if rows[st.name]["key"] != k:
            store.set_stage(job["id"], st.name, key=k)
            rows[st.name] = dict(rows[st.name], key=k)
            adopted.append(st.name)
    if adopted:
        store.log("edit", f"kept the reviewed outputs of {', '.join(adopted)} (stage keys drifted since the run)",
                  job["id"])
    return adopted


def apply_caption_overrides(cues, overrides):
    """[{i, from, to}] onto cue dicts (``text``): by index when the text still matches, else the nearest cue with
    that text. -> (cues, applied, missed)."""
    cues = [dict(c) for c in cues or []]
    applied, missed = [], []
    for o in overrides or []:
        i, a, b = int(o.get("i", -1)), o.get("from"), o.get("to")
        k = None
        if 0 <= i < len(cues) and (a is None or cues[i].get("text") == a):
            k = i
        else:
            hits = [j for j, c in enumerate(cues) if c.get("text") == a]
            if hits:
                k = min(hits, key=lambda j: abs(j - i))
        if k is None:
            missed.append(o)
            continue
        cues[k]["text"] = b
        cues[k]["edited"] = True
        applied.append(dict(o, at=k))
    return cues, applied, missed


def effective_copy(p):
    return dict(title=p.get("title") or "", body=p.get("body") or "", tags=list(p.get("tags") or []))


def key_copy(p, k):
    """The copy value the stage keys see: the original one when the copy was edited in review."""
    o = p.get("_copy_orig") or {}
    return o[k] if k in o else p.get(k)


def _load_cues(rows):
    pr = _rows_out(rows, "proofread").get("cues")
    if pr and os.path.exists(pr):
        return (read_json(pr, {}) or {}).get("cues") or []
    cm = _rows_out(rows, "compose").get("cues")
    if cm and os.path.exists(cm):
        d = read_json(cm, {})
        return d.get("cues") if isinstance(d, dict) else (d or [])
    return []


def _compose_cues(rows):
    cm = _rows_out(rows, "compose").get("cues")
    d = read_json(cm, {}) if cm else {}
    return d.get("cues") if isinstance(d, dict) else (d or [])


def _overlap_text(cues, a, b):
    from vstudio.cleanup import join_words
    return join_words([dict(w=c.get("text", "")) for c in cues if a - 0.05 <= (c["start"] + c["end"]) / 2 <= b + 0.05])


def _heard_text(rows, a, b):
    """Re-ASR (verify heard.json, final time) of the cue window."""
    vf = _rows_out(rows, "verify")
    rep = read_json(vf.get("report"), {}) if vf.get("report") else {}
    hp = vf.get("heard") or (os.path.join(os.path.dirname(vf["report"]), "heard.json") if vf.get("report") else None)
    tr = read_json(hp) if hp and os.path.exists(hp) else None
    if not tr:
        return None
    from vstudio import cleanup as C
    try:
        W = C.load_words(tr)
    except Exception:  # noqa: BLE001
        return None
    ws = [w for w in W if a - 0.1 <= (w["t"] + w["te"]) / 2 <= b + 0.1]
    del rep
    return C.join_words(ws) if ws else None


def source_words(rows, spec, p):
    from vstudio import cleanup as C
    tr = _rows_out(rows, "asr").get("transcript") or p.get("transcript") or (spec.get("inputs") or {}).get("transcript")
    if not tr or not os.path.exists(tr):
        return []
    return C.load_words(tr)


def _final_to_source(rows, t):
    """Output second -> source second through the longform-split compose timeline (None when unknown)."""
    cm = _rows_out(rows, "compose")
    tl = read_json(cm.get("timeline"), None) if cm.get("timeline") else None
    if not tl:
        return None
    clips = [it for it in tl if it.get("kind") != "card"]
    for it in clips:
        a = float(it["final_t0"])
        b = a + (float(it["t1"]) - float(it["t0"])) / float(it.get("speed") or 1.0)
        if a <= t < b:
            return round(float(it["t0"]) + (t - a) * float(it.get("speed") or 1.0), 3)
    nxt = [it for it in clips if float(it["final_t0"]) >= t]
    return round(float((nxt[0] if nxt else clips[-1])["t0"]), 3) if clips else None


def _split_cover_text(text):
    if text is None:
        return None, None
    t = str(text).strip()
    for sep in ("\n", "|", "｜"):
        if sep in t:
            a, _, b = t.partition(sep)
            return a.strip(), b.strip()
    from .lfsplit import _title_parts
    return _title_parts(t)


def check_copy(title, body, tags, platforms):
    """Platform title-length / text checks -> (ok, warnings)."""
    from vstudio import platform as PF
    from vstudio import publish
    warns, ok = [], True
    for t in platforms or []:
        try:
            prof = PF.parse_targets([t])[0]
        except Exception:  # noqa: BLE001
            continue
        if title:
            good, n, hints = publish.check_title(title, prof.name)
            if not good:
                ok = False
                warns.append(f"{t}: title {n:g}/{publish.title_max(prof.name)} - " + "; ".join(hints[:2]))
        try:
            warns += [f"{t}: {w}" for w in PF.check_text(prof, body=body, tags=tags)]
        except Exception:  # noqa: BLE001
            pass
    return ok, list(dict.fromkeys(warns))


def patch_post(text, old, new, platform=None):
    """Rewrite a published post.md for a copy edit: title line, body block and the hashtag line."""
    lines = (text or "").split("\n")
    if old.get("title") != new.get("title"):
        if lines and old.get("title") and lines[0].strip() == old["title"].strip():
            lines[0] = new["title"]
        elif new.get("title"):
            lines = [new["title"], ""] + lines
    out = "\n".join(lines)
    ob, nb = (old.get("body") or "").strip(), (new.get("body") or "").strip()
    if ob != nb:
        if ob and ob in out:
            out = out.replace(ob, nb, 1)
        elif nb:
            parts = out.split("\n", 2)
            out = "\n".join(parts[:2] + [nb, ""] + parts[2:]) if len(parts) >= 2 else out + "\n" + nb + "\n"
    ot, nt = list(old.get("tags") or []), list(new.get("tags") or [])
    if ot != nt:
        ls = out.rstrip("\n").split("\n")
        idx = next((k for k in range(len(ls) - 1, -1, -1) if ls[k].strip().startswith("#")), None)
        newtags = [f"#{t.lstrip('#')}" for t in nt]
        if idx is not None:
            toks = [x for x in ls[idx].split() if x.lstrip("#") not in {t.lstrip("#") for t in ot}]
            ls[idx] = " ".join(dict.fromkeys(newtags + toks))
        elif newtags:
            ls += ["", " ".join(newtags)]
        out = "\n".join(ls) + "\n"
    return out


def _post_body_of(recipe_name, p):
    if recipe_name == "longform-split":
        from .lfsplit import _post_body
        return _post_body(p)
    return p.get("body") or ""


def _rewrite_posts(rows, recipe_name, old_p, new_p):
    ex = _rows_out(rows, "export").get("exports") or []
    old = dict(effective_copy(old_p), body=_post_body_of(recipe_name, old_p))
    new = dict(effective_copy(new_p), body=_post_body_of(recipe_name, new_p))
    done = []
    for e in ex:
        pp = e.get("post")
        if not pp or not os.path.exists(pp):
            continue
        with open(pp, encoding="utf-8") as f:
            txt = f.read()
        nt = patch_post(txt, old, new, e.get("platform"))
        if nt != txt:
            with open(pp, "w", encoding="utf-8") as f:       # in place: package hard links see it too
                f.write(nt)
            done.append(pp)
    return done


def _text_cover(frame_path, text, out_path):
    """A frame + the cover text (bottom gradient, bold CJK) -> out_path. Falls back to the bare frame."""
    from PIL import Image, ImageDraw
    im = Image.open(frame_path).convert("RGB")
    if text:
        try:
            from vstudio.config import font
            from PIL import ImageFont
            W, H = im.size
            grad = Image.new("L", (1, 256))
            for y in range(256):
                grad.putpixel((0, y), int(200 * y / 255))
            band = grad.resize((W, H // 3))
            dark = Image.new("RGB", (W, H // 3), (0, 0, 0))
            im.paste(dark, (0, H - H // 3), band)
            d = ImageDraw.Draw(im)
            lines = [x for x in re.split(r"[|｜\n]", text) if x.strip()][:3]
            size = max(28, int(W / max(6, max(len(x) for x in lines) + 1)))
            f = ImageFont.truetype(font("cjk-bold"), size)
            y = H - int(size * 1.25) * len(lines) - int(H * 0.08)
            for ln in lines:
                w = d.textlength(ln, font=f)
                d.text(((W - w) / 2, y), ln, font=f, fill=(255, 255, 255), stroke_width=max(2, size // 18),
                       stroke_fill=(0, 0, 0))
                y += int(size * 1.25)
        except Exception:  # noqa: BLE001  (no font: the bare frame is still a valid cover)
            pass
    im.save(out_path, quality=92)
    return out_path


# --------------------------------------------------------------------------- the ops
def _op_caption(ctx, a):
    rows, p = ctx["rows"], ctx["params"]
    if a.get("cue") is None or a.get("text") is None:
        raise EditError("caption: --cue I --text T")
    i, text = int(a["cue"]), str(a["text"]).strip()
    base = _load_cues(rows)
    if not base:
        raise EditError("caption: this job has no captions yet (run it first)")
    if not 0 <= i < len(base):
        raise EditError(f"caption: no cue {i} (0-{len(base) - 1})")
    ov = [dict(o) for o in p.get("caption_overrides") or []]
    shown, _, _ = apply_caption_overrides(base, ov)
    cue = shown[i]
    before = cue["text"]
    if not text:
        return dict(ok=False, faithful=False, reason="empty caption (captions must match the audio)")
    from vstudio import proofread as PR
    refs = [("caption", before), ("asr", _overlap_text(_compose_cues(rows), cue["start"], cue["end"])),
            ("heard", _heard_text(rows, cue["start"], cue["end"]))]
    reasons, matched = [], None
    for name, ref in refs:
        if not ref:
            continue
        why = PR.faithful(ref, text)
        if why is None:
            matched = name
            break
        reasons.append(f"vs {name}: {why}")
    if matched is None:
        return dict(ok=False, faithful=False, reason=reasons[0] if reasons else "not faithful to the audio",
                    reasons=reasons, cue=i, before=before)
    orig = base[i]["text"]
    ov = [o for o in ov if int(o.get("i", -1)) != i]
    if text != orig:
        ov.append(dict(i=i, **{"from": orig, "to": text}))
    gloss = []
    if matched in ("caption", "asr", "heard"):
        for fa, fb in PR.diff_spans(before, text):
            fa, fb = fa.strip(), fb.strip()
            if fa and fb and fa.lower() != fb.lower() and len(fa) <= 30 and len(fb) <= 30 and re.search(r"\w", fb):
                gloss.append(dict(wrong=fa, right=fb))
    return dict(delta=dict(caption_overrides=ov), before=dict(cue=i, text=before), value=dict(cue=i, text=text),
                faithful=True, matched=matched, glossary=gloss)


def _op_trim(ctx, a):
    rows, p, spec = ctx["rows"], ctx["params"], ctx["spec"]
    if a.get("start") is None or a.get("end") is None:
        raise EditError("trim: --start A --end B (source seconds)")
    s, e = float(a["start"]), float(a["end"])
    if e - s < MIN_CLIP_S:
        raise EditError(f"trim: a clip must be at least {MIN_CLIP_S:g} s")
    total = float(p.get("_src_dur") or 0) or None
    if s < 0 or (total and s >= total):
        raise EditError(f"trim: start {s} outside the recording")
    if total:
        e = min(e, total)
    W = source_words(rows, spec, p)
    if W:
        from vstudio import cleanup as C
        sa, sb = C.snap_range(W, s, e)
        if sb - sa >= MIN_CLIP_S:
            s, e = sa, sb
    rng = [round(s, 3), round(e, 3)]
    return dict(delta=dict(range=rng), before=dict(range=p.get("range")), value=dict(range=rng, snapped=bool(W)))


def hook_candidates(p):
    from . import spec as S
    raw = p.get("hook_candidates") or p.get("hooks") or []
    out = [h for h in (S._hook(x) for x in raw) if h]
    for h, x in zip(out, raw):
        if isinstance(x, dict) and x.get("text") and not h.get("lines"):
            h["lines"] = [x["text"]]
    if not out and p.get("hook"):
        out = [p["hook"]]
    return out


def _op_hook(ctx, a):
    p = ctx["params"]
    if a.get("pick") is None:
        raise EditError("hook: --pick K (-1 = no cold open)")
    k = int(a["pick"])
    cands = hook_candidates(p)
    if k == -1:
        return dict(delta=dict(hook=None, hook_pick=-1), before=dict(hook=p.get("hook"), pick=p.get("hook_pick")),
                    value=dict(hook=None, pick=-1))
    if not 0 <= k < len(cands):
        raise EditError(f"hook: no candidate {k} ({len(cands)} available)")
    h = cands[k]
    return dict(delta=dict(hook=h, hook_pick=k), before=dict(hook=p.get("hook"), pick=p.get("hook_pick")),
                value=dict(hook=h, pick=k))


def _op_cover(ctx, a):
    rows, p, recipe = ctx["rows"], ctx["params"], ctx["recipe"].name
    t, text = a.get("t"), a.get("text")
    if t is None and text is None:
        raise EditError("cover: --t S and/or --text T")
    cur = p.get("cover") if isinstance(p.get("cover"), dict) else {}
    cov = dict(cur)
    delta = {}
    if t is not None:
        cov["t"] = round(float(t), 3)
    if text is not None:
        cov["text"] = str(text)
    if recipe == "longform-split":
        if t is not None:
            src = _final_to_source(rows, float(t))
            if src is None:
                raise EditError("cover: no compose timeline yet (run the job first)")
            cov["src"] = src
            delta["cover_shot"] = src
        if text is not None:
            b1, b2 = _split_cover_text(text)
            delta.update(big1=b1, big2=b2)
    else:
        cm = _rows_out(rows, "compose")
        master = cm.get("master") or cm.get("final")
        if not master or not os.path.exists(master):
            raise EditError("cover: no composed master yet (run the job first)")
        from vstudio import media
        d = os.path.join(ctx["batch_dir"], "jobs", ctx["job"]["id"], "edits")
        os.makedirs(d, exist_ok=True)
        tt = float(cov.get("t") or 0.0)
        frame = os.path.join(d, f"cover_{int(round(tt * 1000))}.png")
        media.grab_frame(master, tt, frame)
        img = os.path.join(d, f"cover_{int(round(tt * 1000))}_{abs(hash(cov.get('text') or '')) % 10 ** 8}.jpg")
        cov["file"] = _text_cover(frame, cov.get("text"), img)
    delta["cover"] = cov
    return dict(delta=delta, before={k: p.get(k) for k in ("cover", "cover_shot", "big1", "big2")}, value=cov)


def _op_copy(ctx, a):
    p = ctx["params"]
    if a.get("title") is None and a.get("body") is None and a.get("tags") is None:
        raise EditError("copy: --title / --body / --tags")
    cur = effective_copy(p)
    new = dict(cur)
    if a.get("title") is not None:
        new["title"] = str(a["title"]).strip()
    if a.get("body") is not None:
        new["body"] = str(a["body"])
    if a.get("tags") is not None:
        tg = a["tags"]
        new["tags"] = [t.strip().lstrip("#") for t in (tg if isinstance(tg, list) else re.split(r"[,|，\s]+", tg))
                       if t.strip()]
    if not new["title"]:
        raise EditError("copy: the title cannot be empty")
    ok, warns = check_copy(new["title"], new["body"], new["tags"], p.get("platforms"))
    orig = dict(p.get("_copy_orig") or cur)
    delta = dict(title=new["title"], body=new["body"], tags=new["tags"], _copy_orig=orig)
    return dict(delta=delta, before=cur, value=new, title_ok=ok, warnings=warns)


OP_FN = dict(caption=_op_caption, trim=_op_trim, hook=_op_hook, cover=_op_cover, copy=_op_copy)


def apply_delta(params, delta):
    p = dict(params)
    for k, v in (delta or {}).items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def _pending(store):
    return store.meta("pending", {}) or {}


def _set_pending(store, jid, stages, order):
    pend = _pending(store)
    have = set(pend.get(jid) or []) | set(stages)
    if have:
        pend[jid] = [s for s in order if s in have]
    else:
        pend.pop(jid, None)
    store.set_meta("pending", pend)
    return pend.get(jid) or []


# --------------------------------------------------------------------------- public
def edit(batch_dir, jid, op, **args):
    """Apply one edit -> dict(ok, op, faithful, reason, rerun, pending, edit, value, warnings, glossary_added)."""
    if op == "undo":
        return undo(batch_dir, jid)
    if op not in OP_FN:
        raise EditError(f"unknown op {op!r}: {' | '.join(OPS)} | undo")
    store = Store(batch_dir)
    try:
        row = store.job(jid)
        if not row:
            raise KeyError(f"unknown job {jid}")
        if row["state"] == "running":
            from .run import runner_active
            if runner_active(store.dir):
                raise EditError(f"{jid} is running; edit it when the run is over")
        spec = store.spec
        recipe = load_recipe(spec)
        job = job_dict(row)
        rows = store.stage_rows(jid)
        ctx = dict(store=store, spec=spec, recipe=recipe, job=job, rows=rows, params=dict(job["params"]),
                   batch_dir=store.dir)
        res = OP_FN[op](ctx, args)
        if recipe.name == "longform-split" and res.get("ok") is not False:
            from .lfsplit import ensure_stash
            try:
                ensure_stash(store.dir, jid, rows, spec)
            except OSError:
                pass
        if res.get("ok") is False:
            store.log("edit", f"{op} refused: {res.get('reason')}", jid)
            return dict(ok=False, op=op, faithful=res.get("faithful", False), reason=res.get("reason"),
                        reasons=res.get("reasons") or [], rerun=[], pending=_pending(store).get(jid) or [],
                        glossary_added=[], undone=None)
        new_p = apply_delta(job["params"], res["delta"])
        order = [s.name for s in recipe.order()]
        adopted = adopt_drift(store, recipe, spec, job, rows) if row["state"] in REVIEWED else []
        rerun = stale_stages(recipe, spec, job, new_p, rows)
        store.set_job(jid, params=new_p)
        _write_job_json(store.dir, row, new_p)
        rewritten = _rewrite_posts(rows, recipe.name, job["params"], new_p) if op == "copy" else []
        before = dict(res.get("before") or {}, _params={k: job["params"].get(k) for k in res["delta"]})
        n = store.add_edit(jid, op, res["delta"], before, res.get("value"), rerun)
        pending = _set_pending(store, jid, rerun, order)
        added = []
        if op == "caption" and res.get("glossary"):
            from . import clients as CL
            cdir = CL.batch_client_dir(spec)
            if cdir:
                added = CL.add_glossary(cdir, [dict(g, source="caption-fix", batch=spec.get("name") or "", job=jid,
                                                    at=time.strftime("%Y-%m-%d")) for g in res["glossary"]])
                if added:
                    store.set_edit(n, result=dict(res.get("value") or {}, glossary_added=added))
        store.log("edit", f"#{n} {op} -> stale: {', '.join(rerun) or 'none'}", jid)
        return dict(ok=True, op=op, edit=n, faithful=res.get("faithful", True), reason=None,
                    matched=res.get("matched"), value=res.get("value"), before=res.get("before"), rerun=rerun,
                    pending=pending, warnings=res.get("warnings") or [], title_ok=res.get("title_ok"),
                    glossary_added=added, posts_rewritten=rewritten, undone=None, adopted=adopted)
    finally:
        store.close()


def undo(batch_dir, jid):
    """Revert the job's last (not yet undone) edit: params go back to what they were before it."""
    store = Store(batch_dir)
    try:
        row = store.job(jid)
        if not row:
            raise KeyError(f"unknown job {jid}")
        eds = store.edits(jid)
        if not eds:
            raise EditError("nothing to undo")
        last = eds[-1]
        spec = store.spec
        recipe = load_recipe(spec)
        job = job_dict(row)
        rows = store.stage_rows(jid)
        prev = dict((last["before"] or {}).get("_params") or {})   # the params the edit replaced
        for k in last["args"] or {}:
            prev.setdefault(k, None)
        new_p = apply_delta(job["params"], prev)
        order = [s.name for s in recipe.order()]
        rerun = stale_stages(recipe, spec, job, new_p, rows)
        store.set_job(jid, params=new_p)
        _write_job_json(store.dir, row, new_p)
        if last["op"] == "copy":
            _rewrite_posts(rows, recipe.name, job["params"], new_p)
        removed = (last["result"] or {}).get("glossary_added") or []
        if removed:                                   # the caption fix taught the client glossary: unlearn it
            from . import clients as CL
            cdir = CL.batch_client_dir(spec)
            if cdir and os.path.exists(CL.yaml_path(cdir)):
                CL.update(cdir, dict(glossary_remove=[dict(wrong=g["wrong"], right=g["right"]) for g in removed]))
        store.set_edit(last["n"], undone=1)
        pend = _pending(store)
        pend[jid] = [s for s in order if s in set(rerun)]
        if not pend[jid]:
            pend.pop(jid)
        store.set_meta("pending", pend)
        store.log("edit", f"undo #{last['n']} {last['op']} -> stale: {', '.join(rerun) or 'none'}", jid)
        return dict(ok=True, op="undo", undone=dict(n=last["n"], op=last["op"], args=last["args"],
                                                     before=last["before"]),
                    faithful=True, reason=None, rerun=rerun, pending=pend.get(jid) or [], glossary_added=[])
    finally:
        store.close()


def _write_job_json(bdir, row, params):
    jd = os.path.join(bdir, "jobs", row["id"])
    if os.path.isdir(jd):
        write_json(os.path.join(jd, "job.json"), dict(id=row["id"], item=row.get("item"), variant=row.get("variant"),
                                                      recipe=row.get("recipe"), params=params))


def reapply(store, jobs):
    """``plan``: the stored (not undone) edits of each job on top of its freshly expanded params."""
    try:
        eds = store.edits()
    except Exception:  # noqa: BLE001  (a store without the table: nothing to re-apply)
        return jobs
    if not eds:
        return jobs
    by = {}
    for e in eds:
        by.setdefault(e["job"], []).append(e)
    out = []
    for j in jobs:
        if j["id"] in by:
            p = j["params"]
            for e in by[j["id"]]:
                p = apply_delta(p, e["args"])
            j = dict(j, params=p)
        out.append(j)
    return out


def history(store, jid):
    return [dict(n=e["n"], op=e["op"], value=e["result"], before=e["before"], rerun=e["rerun"], at=e["ts"],
                 undone=bool(e["undone"])) for e in store.edits(jid, include_undone=True)]


def rerun(batch_dir, jid, on_event=None, echo=True):
    """Re-run the stale stages of one job (``job edit``), then put it back for review."""
    from .run import run_batch
    store = Store(batch_dir)
    try:
        row = store.job(jid)
        if not row:
            raise KeyError(f"unknown job {jid}")
        pend = _pending(store).get(jid) or []
        prev_review = row.get("review")
        store.set_job(jid, state="planned", review=None, review_reason=None)
    finally:
        store.close()
    t0 = time.time()
    r = run_batch(batch_dir, only={jid}, targeted=True, on_event=on_event, echo=echo)
    secs = round(time.time() - t0, 2)
    store = Store(batch_dir)
    try:
        j = store.job(jid)
        if j and j["state"] == "done":
            p = _pending(store)
            p.pop(jid, None)
            store.set_meta("pending", p)
        store.log("rerun", f"{len(r.get('ran') or [])} stage(s) in {secs:.1f}s (was review={prev_review})", jid)
        ran = [s for (x, s) in r.get("ran") or [] if x == jid]
        return dict(ok=r["exit_code"] == 0, job=jid, state=j["state"] if j else None, qc=j.get("qc") if j else None,
                    stages=ran, expected=pend, seconds=secs, status=r["status"], exit_code=r["exit_code"])
    finally:
        store.close()
