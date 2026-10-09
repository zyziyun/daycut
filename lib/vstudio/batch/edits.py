"""In-review job edits (``job edit``) and targeted re-runs (``job rerun``).

    python -m vstudio.batch job edit  --batch B --job ep02 --op caption --cue 7 --text "这是 RAG 的核心"
    python -m vstudio.batch job edit  --batch B --job ep02 --op caption --cue 7 --text "..." --reasr
    python -m vstudio.batch job edit  --batch B --job ep02 --op trim --start 315.2 --end 360.0
    python -m vstudio.batch job edit  --batch B --job ep02 --op cut --start 482.3 --end 484.5 --why "aside"
    python -m vstudio.batch job edit  --batch B --job ep02 --op notes --set "要点一|要点二|要点三"   # "" clears
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
  caption --cue I --text T   the captions must match the audio: accepted when ``vstudio.proofread.faithful``
          [--reasr]          passes against the cue as shown, the ASR text under it, or the re-ASR (verify) of the
                             cut - mis-heard spans swapped for sound-alikes, no word added or dropped - else when a
                             re-hearing of the cue window (``rehear_text``) says the new text (``heard_accepts``;
                             ``--reasr``: the re-hearing decides). Refusals: {ok: False, faithful: False, reason,
                             reason_code, heard}. Stored as ``caption_overrides`` [{i, from, to, asr, t, src}]
                             (applied at export, found again after a re-proofread / re-cut; proofread never touches
                             them); the fixed spans are appended to the batch client's glossary (not a revert of a
                             proofread guess).
  trim --start A --end B     new source range, snapped to word edges (``vstudio.cleanup.snap_range``).
  cut --start A --end B      an inner cut inside the range on whole words (``snap_cut_to_words``), appended to the
      [--why TEXT]           row ``cuts`` [a, b, why] -> cleanup and everything after re-run.
  notes --set "a|b|c"        the 记笔记 panel lines ("" clears): only the panel render (export) and after re-run.
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

OPS = ("caption", "trim", "cut", "notes", "hook", "cover", "copy")
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


def _norm_text(t):
    return re.sub(r"[\s,，。.!?！？、;；:：\"'“”‘’]+", "", str(t or "")).lower()


def _sim(a, b):
    import difflib
    a, b = _norm_text(a), _norm_text(b)
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def _cue_mid(c):
    return (float(c["start"]) + float(c["end"])) / 2


def apply_caption_overrides(cues, overrides, asr_cues=None, to_out=None):
    """The creator's caption edits [{i, from, to[, asr, t, src]}] onto cue dicts (``text``) -> (cues, applied,
    missed). A re-proofread / re-cut may renumber or reword the cues, so an edit is found, in order, by:
    ``index`` (cue i still says ``from``), ``text`` (the cue that says ``from``, nearest in time / index), ``asr``
    (the cue whose ASR words - ``asr_cues``, the compose cues - are the ones the creator corrected), ``contains``
    (a merged cue holding ``from``: only that span is replaced) and ``time`` (the cue at the edit's time, ``src``
    mapped through ``to_out(src)`` or ``t``, saying nearly the same as ``from``). Applied entries carry ``at`` and
    ``how``; anything else is ``missed`` - callers log / warn, never drop it silently."""
    cues = [dict(c) for c in cues or []]
    applied, missed = [], []
    for n, o in enumerate(overrides or []):
        i, a, b = int(o.get("i", -1)), o.get("from"), o.get("to")
        at = None
        if o.get("src") is not None and to_out is not None:
            try:
                at = to_out(float(o["src"]))
            except Exception:  # noqa: BLE001  (no timeline: fall back to the stored output time)
                at = None
        if at is None and o.get("t") is not None:
            at = float(o["t"])

        def near(js):
            return min(js, key=lambda j: (abs(_cue_mid(cues[j]) - at) if at is not None and "start" in cues[j] else 0,
                                          abs(j - i)))
        k, how, sub = None, None, False
        if 0 <= i < len(cues) and (a is None or cues[i].get("text") == a):
            k, how = i, "index"
        if k is None:
            hits = [j for j, c in enumerate(cues) if c.get("text") == a]
            if hits:
                k, how = near(hits), "text"
        if k is None and o.get("asr") and asr_cues:
            want = _norm_text(o["asr"])
            hits = [j for j, c in enumerate(cues) if "start" in c and
                    _norm_text(_overlap_text(asr_cues, c["start"], c["end"])) == want]
            if hits:
                k, how = near(hits), "asr"
        if k is None and a and len(_norm_text(a)) >= 2:
            hits = [j for j, c in enumerate(cues) if a in (c.get("text") or "")]
            if hits:
                k, how, sub = near(hits), "contains", True
        if k is None and at is not None and a:
            hits = [j for j, c in enumerate(cues) if "start" in c and c["start"] - 0.3 <= at <= c["end"] + 0.3
                    and _sim(c.get("text"), a) >= 0.75]
            if hits:
                k, how = near(hits), "time"
        if k is None:
            missed.append(o)
            continue
        cues[k]["text"] = cues[k]["text"].replace(a, b, 1) if sub else b
        cues[k]["edited"] = True
        applied.append(dict(o, at=k, how=how, n=n))
    return cues, applied, missed


def locked_cues(cues, overrides):
    """Indices of ``cues`` (the compose / ASR cues proofread starts from) the creator's caption edits cover: the cue
    whose text is the edit's ``asr`` (or ``from``) text, nearest the edit's time / index. Proofread leaves them
    alone (the edit is final)."""
    out = set()
    for o in overrides or []:
        keys = {_norm_text(x) for x in (o.get("asr"), o.get("from")) if x}
        hits = [j for j, c in enumerate(cues or []) if _norm_text(c.get("text")) in keys]
        if not hits:
            continue
        t, i = o.get("t"), int(o.get("i", -1))
        out.add(min(hits, key=lambda j: (abs(_cue_mid(cues[j]) - float(t)) if t is not None and "start" in cues[j]
                                         else 0, abs(j - i))))
    return sorted(out)


def drafted_copy(rows):
    """The post copy the ``copy`` stage drafted for what the creator left empty -> ({key: text}, source)."""
    out = _rows_out(rows or {}, "copy")
    return {k: out.get(k) or "" for k in out.get("drafted") or []}, out.get("source")


def effective_copy(p, rows=None):
    """The post copy as published: the creator's, else (``rows`` given) the drafted one the posts carry."""
    d = dict(title=p.get("title") or "", body=p.get("body") or "", tags=list(p.get("tags") or []))
    for k, v in drafted_copy(rows)[0].items():
        if not d.get(k):
            d[k] = v
    return d


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


def patch_post(text, old, new, platform=None, hook=None):
    """Rewrite a published post.md for a copy edit: title line, body block and the hashtag line.

    ``hook``: the spoken line the export put where the body goes. Copy the export drafted on its own (no title /
    body in the params yet) is replaced, not stacked under the edit: the post's first line is then its title, and
    the hook stands in for the body."""
    lines = (text or "").split("\n")
    if not (old.get("body") or "").strip() and (new.get("body") or "").strip() and hook and hook.strip() in (text or ""):
        old = dict(old, body=hook.strip())
    if not old.get("title") and new.get("title") and lines and lines[0].strip() and \
            not lines[0].lstrip().startswith("#"):
        old = dict(old, title=lines[0].strip())
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
    return re.sub(r"\n{3,}", "\n\n", out)                 # a replaced block leaves no gap (as publish.post_body)


def _post_body_of(recipe_name, p):
    if recipe_name == "longform-split":
        from .lfsplit import _post_body
        return _post_body(p)
    return p.get("body") or ""


def _rewrite_posts(rows, recipe_name, old_p, new_p):
    ex = _rows_out(rows, "export").get("exports") or []
    old = effective_copy(old_p, rows)
    new = effective_copy(new_p, rows)
    if recipe_name == "longform-split":
        old["body"], new["body"] = _post_body_of(recipe_name, old_p), _post_body_of(recipe_name, new_p)
    pj = _rows_out(rows, "compose").get("post")
    hook = (read_json(pj, {}) or {}).get("hook") if pj and os.path.exists(pj) else None
    done = []
    for e in ex:
        pp = e.get("post")
        if not pp or not os.path.exists(pp):
            continue
        with open(pp, encoding="utf-8") as f:
            txt = f.read()
        nt = patch_post(txt, old, new, e.get("platform"), hook=hook if isinstance(hook, str) else None)
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
REHEAR_MIN = 0.9          # normalized similarity a caption edit needs with the re-heard cue window (re-ASR)
REHEAR_PAD = 0.25         # s of audio around the cue window the re-hearing gets


def _cue_media(rows):
    """The composed cut the cues are timed on (longform-split compose ``final``, the speech recipes' ``master``)."""
    cm = _rows_out(rows, "compose")
    m = cm.get("final") or cm.get("master")
    return m if m and os.path.exists(m) else None


def rehear_text(ctx, a, b):
    """Re-hear output seconds [a, b] of the job's composed cut: the window (+ ``REHEAR_PAD``) cut to 16 kHz mono,
    transcribed with the batch's transcriber (spec ``asr.transcriber``) else ``vstudio.asr.transcribe`` (backend:
    spec ``asr.rehear_backend`` > ``asr.backend``; the verify hearing's options), words outside the cue window
    dropped. -> text, or None when the job has no composed cut yet. Tests replace this function."""
    media_path = _cue_media(ctx["rows"])
    if not media_path:
        return None
    from vstudio import asr, media
    from vstudio import proofread as PR
    from .stages import _transcriber, hear_opts
    o = hear_opts(ctx["job"], ctx["spec"])
    d = os.path.join(ctx["batch_dir"], "jobs", ctx["job"]["id"], "edits")
    os.makedirs(d, exist_ok=True)
    t0 = max(0.0, float(a) - REHEAR_PAD)
    wav = os.path.join(d, f"rehear_{int(round(a * 1000))}_{int(round(b * 1000))}.wav")
    media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{float(b) - t0 + REHEAR_PAD:.3f}", "-i",
               media_path, "-vn", "-ac", "1", "-ar", "16000", wav])
    fn = _transcriber(ctx["spec"])
    if fn:
        got = fn(wav, language=o["language"], prompt=o["prompt"])
    else:
        be = (ctx["spec"].get("asr") or {}).get("rehear_backend") or o.get("backend") or "auto"
        got = asr.transcribe(wav, language=o["language"], prompt=o["prompt"], backend=be, skip_silence=None)
    ws = PR.words_of(got)
    if ws:
        lo, hi = float(a) - t0 - 0.1, float(b) - t0 + 0.1
        ws = [w for w in ws if lo <= (float(w.get("start", w.get("t", 0))) + float(w.get("end", w.get("te", 0)))) / 2
              <= hi]
        return PR.asr_join(ws).strip() or None
    txt = got.get("text") if isinstance(got, dict) else None
    return str(txt).strip() or None if txt else None


def hear_match(heard, text):
    """How well a caption matches what the audio says: normalized (case, spaces, punctuation) similarity 0..1."""
    return round(_sim(heard, text), 3)


def heard_accepts(heard, text):
    """(ok, score): the new caption says what the re-hearing heard - the same text up to case / spaces /
    punctuation, or nearly (similarity >= ``REHEAR_MIN`` and at most one character in ten more / fewer: an edge
    word the window caught or missed, never an added phrase). Stricter than ``faithful``: the re-hearing is the
    evidence, so no sound-alike leeway on top of it."""
    score = hear_match(heard, text)
    h, t = _norm_text(heard), _norm_text(text)
    return score >= REHEAR_MIN and abs(len(h) - len(t)) <= max(1, len(h) // 10), score


def _refuse(code, reason, heard=None, **kw):
    return dict(ok=False, faithful=False, reason=reason, reason_code=code, heard=heard, **kw)


def _reverts(asr_text, report):
    """-> rev(a, b): True when a caption-edit span only undoes a proofread guess (the caption said ``a``, the ASR /
    the creator say ``b``): never taught to the client glossary as ``a -> b`` (it would learn the reverse of a
    guess)."""
    from vstudio import proofread as PR
    pr_pairs = set()
    for c in (report or {}).get("changes") or []:
        for o, n in (c.get("diff") or PR.diff_spans(c.get("before", ""), c.get("after", ""))):
            if o and n:
                pr_pairs.add((_norm_text(o), _norm_text(n)))
    asr_n = _norm_text(asr_text)

    def rev(fa, fb):
        if (_norm_text(fb), _norm_text(fa)) in pr_pairs:      # proofread made fb -> fa: the creator goes back
            return True
        return bool(asr_n) and _norm_text(fb) in asr_n and _norm_text(fa) not in asr_n
    return rev


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
    comp = _compose_cues(rows)
    to_out = _to_out(rows)
    shown, applied, _ = apply_caption_overrides(base, ov, asr_cues=comp, to_out=to_out)
    cue = shown[i]
    before = cue["text"]
    if not text:
        return _refuse("empty-text", "The caption cannot be empty: captions must match the audio.", cue=i,
                       before=before)
    from vstudio import proofread as PR
    asr_text = _overlap_text(comp, cue["start"], cue["end"])
    refs = [("caption", before), ("asr", asr_text), ("heard", _heard_text(rows, cue["start"], cue["end"]))]
    labels = dict(caption="the current caption", asr="the ASR text under the cue", heard="the verify re-hearing")
    force = bool(a.get("reasr"))
    reasons, matched, heard, score, err = [], None, None, None, None
    if not force:
        for name, ref in refs:
            if not ref:
                continue
            why = PR.faithful(ref, text)
            if why is None:
                matched = name
                break
            reasons.append(f"vs {name}: {why}")
    if matched is None:                               # not a sound-alike of what we have: listen to the cue again
        try:
            heard = rehear_text(ctx, cue["start"], cue["end"])
        except Exception as e:  # noqa: BLE001  (no ffmpeg / ASR backend: refuse with the reason)
            err = f"{type(e).__name__}: {str(e)[:160]}"
        if heard:
            ok, score = heard_accepts(heard, text)
            if ok:
                matched = "reasr"
    if matched is None:
        extra = dict(reasons=reasons, cue=i, before=before, score=score)
        if heard:
            return _refuse("differs-from-audio", f"Cue {i} re-heard as \"{heard}\", which does not match the new "
                           f"text (similarity {score:.2f}); captions must say what the audio says.",
                           heard=heard, **extra)
        if err:
            return _refuse("rehear-failed", f"Re-hearing cue {i} failed ({err}); the text is not a sound-alike of the "
                           "caption either.", **extra)
        if force:
            return _refuse("rehear-unavailable", f"Cannot re-hear cue {i}: the job has no composed cut yet (run it "
                           "first).", **extra)
        first = reasons[0] if reasons else "not faithful to the audio"
        name, _, why = first.partition(": ")
        return _refuse("not-faithful", f"{why or first} (checked against "
                       f"{labels.get(name[3:], name)}; no rendered audio to re-hear).", **extra)
    orig = base[i]["text"]
    drop = {x["n"] for x in applied if x.get("at") == i}          # the edit(s) this cue showed are replaced
    ov = [o for n, o in enumerate(ov) if n not in drop and not (int(o.get("i", -1)) == i and n not in
                                                                 {x["n"] for x in applied})]
    if text != orig:
        mid = (float(cue["start"]) + float(cue["end"])) / 2
        o = dict(i=i, **{"from": orig, "to": text}, asr=asr_text or None, t=round(mid, 3))
        src = _final_to_source(rows, mid)
        if src is not None:
            o["src"] = src
        ov.append(o)
    gloss = []
    report = read_json(_rows_out(rows, "proofread").get("report"), {}) if _rows_out(rows, "proofread").get("report") \
        else {}
    rev = _reverts(asr_text, report)
    for fa, fb in PR.diff_spans(before, text):
        fa, fb = fa.strip(), fb.strip()
        if not (fa and fb and fa.lower() != fb.lower() and len(fa) <= 30 and len(fb) <= 30 and re.search(r"\w", fb)):
            continue
        if rev(fa, fb):
            continue                                  # undoing a guess: nothing to learn
        if matched == "reasr" and PR.faithful(fa, fb) is not None:
            continue                                  # a re-hearing, not a recurring mis-hearing of a term
        gloss.append(dict(wrong=fa, right=fb))
    return dict(delta=dict(caption_overrides=ov), before=dict(cue=i, text=before), value=dict(cue=i, text=text),
                faithful=True, matched=matched, glossary=gloss, heard=heard, score=score)


def _to_out(rows):
    """Source second -> output second through the longform-split compose timeline (None for other recipes)."""
    cm = _rows_out(rows, "compose")
    tl = read_json(cm.get("timeline"), None) if cm.get("timeline") else None
    if not tl:
        return None
    from .lfsplit import _out_time
    return lambda t: _out_time(tl, t)


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


def _subtract(a, b, cuts):
    from .lfsplit import _subtract as sub
    return sub(a, b, cuts)


def snap_cut_to_words(W, s, e):
    """A cut [s, e] -> (a, b) on whole words: ``a`` = the start of the first word the cut takes (the word under
    ``s`` when ``s`` is in its first half, else the next one), ``b`` = the end of the last word it takes (the word
    under ``e`` when ``e`` is in its second half, else the previous one). Never splits a word; None when no whole
    word is inside."""
    starts = [w for w in W if w["te"] > s]                     # words not entirely before s
    first = next((w for w in starts if not (w["t"] < s and s > (w["t"] + w["te"]) / 2)), None)
    ends = [w for w in W if w["t"] < e]                        # words not entirely after e
    last = next((w for w in reversed(ends) if not (w["te"] > e and e < (w["t"] + w["te"]) / 2)), None)
    if not first or not last or last["te"] <= first["t"]:
        return None
    return round(first["t"], 3), round(last["te"], 3)


def _op_cut(ctx, a):
    rows, p, spec, recipe = ctx["rows"], ctx["params"], ctx["spec"], ctx["recipe"]
    if a.get("start") is None or a.get("end") is None:
        raise EditError("cut: --start A --end B (source seconds) [--why TEXT]")
    if "cleanup" not in [st.name for st in recipe.order()]:
        raise EditError(f"cut: recipe {recipe.name} has no cleanup stage (no inner cuts)")
    s, e = float(a["start"]), float(a["end"])
    if e <= s:
        raise EditError("cut: --end must be after --start")
    rng = p.get("range")
    if rng:
        lo, hi = float(rng[0]), float(rng[1])
        if s < lo - 0.05 or e > hi + 0.05:
            raise EditError(f"cut: {s:g}-{e:g} is outside the job's range {lo:g}-{hi:g} (move an edge with --op trim)")
    else:
        lo, hi = 0.0, float(p.get("_src_dur") or p.get("_dur") or 0.0) or e
    W = source_words(rows, spec, p)
    words = ""
    if W:
        from vstudio import cleanup as C
        r = snap_cut_to_words(W, s, e)
        if not r:
            raise EditError(f"cut: {s:g}-{e:g} holds no whole word (a cut never splits a word)")
        s, e = r
        words = C.join_words([w for w in W if s <= (w["t"] + w["te"]) / 2 <= e])
    why = str(a.get("why") or "").strip()
    cur = [list(c)[:3] + [""] * (3 - len(list(c)[:3])) for c in p.get("cuts") or []]
    new = sorted(cur + [[s, e, why]], key=lambda c: (float(c[0]), float(c[1])))
    left = sum(y - x for x, y in _subtract(lo, hi, new))
    if left < MIN_CLIP_S:
        raise EditError(f"cut: only {left:.1f}s would be left (a clip must be at least {MIN_CLIP_S:g} s)")
    return dict(delta=dict(cuts=new), before=dict(cuts=p.get("cuts") or []),
                value=dict(cut=[s, e, why], words=words, snapped=bool(W), cuts=new, kept_s=round(left, 2)))


def _op_notes(ctx, a):
    p = ctx["params"]
    v = a.get("set")
    if v is None:
        raise EditError('notes: --set "line 1|line 2|line 3" (an empty string clears the notes panel)')
    lines = [str(x).strip() for x in v] if isinstance(v, (list, tuple)) else \
        [x.strip() for x in re.split(r"[|｜\n]", str(v))]
    lines = [x for x in lines if x]
    return dict(delta=dict(notes=lines or None), before=dict(notes=p.get("notes") or []), value=dict(notes=lines))


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
    cur = effective_copy(p, ctx["rows"])                 # a drafted title / body is the baseline (kept unless edited)
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


OP_FN = dict(caption=_op_caption, trim=_op_trim, cut=_op_cut, notes=_op_notes, hook=_op_hook, cover=_op_cover,
             copy=_op_copy)


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
                        reason_code=res.get("reason_code"), heard=res.get("heard"), score=res.get("score"),
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
        return dict(ok=True, op=op, edit=n, faithful=res.get("faithful", True), reason=None, reason_code=None,
                    heard=res.get("heard"), matched=res.get("matched"), value=res.get("value"), before=res.get("before"),
                    rerun=rerun,
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
        try:                                           # a job proofread before the per-cue cache: keep what was
            from .stages import seed_proofread_cache   # reviewed (its next proofread re-asks nothing seen)
            seeded = seed_proofread_cache(store.dir, store.spec, job_dict(row), store.stage_rows(jid))
            if seeded:
                store.log("rerun", f"proofread cache seeded with {seeded} reviewed cue(s)", jid)
        except Exception as e:  # noqa: BLE001  (a cache seed never blocks a re-run)
            store.log("rerun", f"proofread cache seed skipped: {type(e).__name__}: {e}", jid)
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
