"""promo-recut drafts (vstudio.project.drafts): the engine writes promo.config.yaml itself.

keep     (before the cut) her recording is transcribed (``work/audio.json``, the file tight_cut.py reads, so the
         ``suggest`` stage does not transcribe again) and the AI editor reads it with her request: what to cut
         (false starts, an unfinished opening, detours, self-corrections, every passage she asked to delete) and,
         when she asks for hooks, which lines open the video. -> ``cut.body`` KEEP spans (raw seconds; tight_cut
         snaps them word-safe), ``hooks.items`` in her order, the speeds she named (``rates.body``,
         ``hooks.speed``). Without a model nothing is cut (said plainly: she selects what to cut in the
         transcript). Review: the transcript as sentences, each kept or cut (with the AI's label), and
         "Keeps 9:40 of 12:44 - cuts the unfinished opening, the joke detour, the Hedra part".
package  (before the build) captions from the cut (``work/draft_subs.txt``) + where her screen recordings, finished
         clips and screenshots go (the AI reads the kept transcript and the file names: a screen recording full
         screen with her face small in the corner while she talks about it, a finished clip in the montage, a
         screenshot as a card beside her), chapters, the end card, the cover line and the post. Without a model:
         the captions only (the rest is said to be left out). Review: one plain line per part.
"""
import json
import os
import re

from vstudio.batch.util import read_json

from .. import drafts as D

SENT_GAP = 0.55          # a pause this long ends a sentence
SENT_MAX_S = 14.0
MERGE_GAP = 0.8          # kept sentences closer than this become one span
LINES_CHARS = 60000
SYSTEM_KEEP = (
    "You are the editor of a premium talking-head / promo recut. You get the creator's request and her recording's "
    "transcript as numbered lines (raw times). Decide what to CUT so the video is tight and clean: false starts, an "
    "opening she did not finish, detours, jokes that go nowhere, self-corrections (keep only the corrected take), "
    "repeated takes, and EVERY passage the request says to delete. Keep everything else, in order. When the request "
    "asks for hooks / a teaser / an opening montage, pick those lines too, in the order she asks. Reply JSON only: "
    '{"cuts": [{"from": <line>, "to": <line>, "label": "<what it is, 2-6 words>"}], '
    '"hooks": [{"from": <line>, "to": <line>}], "summary": "<one sentence>"}. Labels and summary in {lang}.')
SYSTEM_PACKAGE = (
    "You place the creator's supporting footage in her promo recut. You get her request, the kept transcript (raw "
    "times) and her files: screen recordings (shown full screen with her face small in a corner while she talks "
    "about what is on screen), finished clips (cut into a short montage near the end) and screenshots (a card "
    "beside her while she talks about it). Match each file to the moment she talks about it (file names and the "
    "transcript tell you). Never overlap two placements; stay inside the kept times. Reply JSON only: "
    '{"pip": [{"file": "<name>", "start": s, "end": s, "media_start": s, "tag": "<short label>"}], '
    '"cards": [{"file": "<name>", "start": s, "end": s}], '
    '"montage": [{"file": "<name>", "start": s, "end": s, "label": "<step label or null>"}], '
    '"chapters": [[<raw second or "start">, "<label>"]], "end_card": {"main": "<line>", "sub": "<line>"}, '
    '"cover": {"title": ["<line 1>", "<line 2>"], "talk_at": s}, '
    '"post": {"title": "<title>", "body": ["<paragraph>"], "tags": ["<tag>"]}, "summary": "<one sentence>"}. '
    "Texts in the language she speaks in the recording; the summary in {lang}.")
SCREEN_RE = re.compile(r"screen ?recording|屏幕录制|录屏|^rec.*\.mov$|capture", re.I)


# --------------------------------------------------------------------------- the transcript
def _talk(ctx):
    v = ctx.inputs.get("talk") or ctx.params.get("source")
    v = v[0] if isinstance(v, list) and v else v
    return v if isinstance(v, str) and os.path.isfile(v) else None


def _transcriber(ctx):
    """The project's own transcriber (``spec.asr.transcriber``, e.g. the tests' fake one), else None (vstudio.asr).
    Its ``plugin_paths`` are importable here too (a redraft runs outside the batch runner)."""
    spec = ctx.spec if (ctx.spec or {}).get("asr") else ((ctx.data or {}).get("spec") or {})
    ref = (spec.get("asr") or {}).get("transcriber")
    if ref:
        import sys
        for p in spec.get("plugin_paths") or ():
            if p not in sys.path:
                sys.path.append(p)
        from vstudio.batch.util import import_ref
        return import_ref(ref)
    return None


def transcript(ctx):
    """Her recording's words [{w, t, te}] (raw seconds), transcribed once into the item's ``work/audio.json``."""
    js = ctx.item_path("work", "audio.json")
    tr = read_json(js, None) if os.path.exists(js) else None
    if not tr:
        src = _talk(ctx)
        if not src:
            raise RuntimeError("no talking-head recording to transcribe")
        lang = ctx.params.get("language") or None
        fn = _transcriber(ctx)
        if fn:
            tr = fn(src, language=lang)
        else:
            from vstudio import asr
            tr = asr.transcribe(src, language=lang, cache=True, fix_terms=False)
        if isinstance(tr, list):                                   # a flat word list
            tr = dict(segments=[dict(words=[dict(word=w["w"], start=w["t"], end=w["te"]) for w in tr])])
        tr = {k: tr[k] for k in ("language", "text", "segments") if k in tr}
        os.makedirs(os.path.dirname(js), exist_ok=True)
        with open(js, "w", encoding="utf-8") as f:
            json.dump(tr, f, ensure_ascii=False, indent=1)
    words = []
    for s in tr.get("segments") or []:
        for w in s.get("words") or []:
            txt = str(w.get("word") or w.get("w") or "")
            if txt.strip():
                words.append(dict(w=txt, t=float(w.get("start", w.get("t", 0))), te=float(w.get("end", w.get("te", 0)))))
    return words


def sentences(words):
    """Words -> sentences [{i, t, te, text}]: a pause, an end mark or 14 s ends one."""
    out, cur = [], []

    def flush():
        if cur:
            text = "".join(w["w"] for w in cur)
            text = re.sub(r"\s+", " ", text).strip()
            out.append(dict(i=len(out) + 1, t=round(cur[0]["t"], 2), te=round(cur[-1]["te"], 2), text=text))
            cur.clear()
    for w in words:
        if cur and (w["t"] - cur[-1]["te"] > SENT_GAP or w["te"] - cur[0]["t"] > SENT_MAX_S):
            flush()
        cur.append(w)
        if re.search(r"[。！？!?.]\s*$", w["w"]):
            flush()
    flush()
    return out


def _mmss(t):
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


# --------------------------------------------------------------------------- speeds named in the request
def _speed_after(text, anchor_rx):
    for m in re.finditer(anchor_rx, text or "", re.I):
        n = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:倍|x\b|×)", text[m.end():m.end() + 40], re.I)
        if n:
            v = float(n.group(1))
            if 0.5 <= v <= 4:
                return v
    return None


def speeds(request):
    return dict(body=_speed_after(request, r"正文|主体|body|the rest"),
                hooks=_speed_after(request, r"hooks?|开场|预告|teaser"))


# --------------------------------------------------------------------------- keep spans
def _ask(complete, system, lang, body, max_tokens):
    """One model call (task planner, the route's fallbacks) -> (result | None, error | None): no model or a failed
    call is not an error of the draft - the rules draft it, and the review says the AI was not available."""
    if complete is None:
        from vstudio import llm
        complete = llm.complete
    try:
        return complete("planner", system.replace("{lang}", D.LANGS.get(lang, "English")), body, schema=True,
                        max_tokens=max_tokens, timeout=300, cli_timeout=300, retries=1), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:300]


def _ids(x, n):
    try:
        i = int(x)
    except (TypeError, ValueError):
        return None
    return i if 1 <= i <= n else None


def _spans(sents, keep):
    out = []
    for s in sents:
        if s["i"] not in keep:
            continue
        a, b = max(0.0, s["t"] - 0.05), s["te"] + 0.05
        if out and a - out[-1][1] < MERGE_GAP:
            out[-1][1] = round(b, 2)
        else:
            out.append([round(a, 2), round(b, 2)])
    return out


def _load_cfg(path):
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cfg(path, cfg, what):
    import yaml
    head = (f"# promo-recut config for this video - {what} by Reelfold (raw seconds of the recording).\n"
            "# You never have to edit this: the Inbox shows it in plain words. Edits here are kept.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=None, width=120))


def _keep_view(sents, cut_by, total, by, provider=None):
    segs = [dict(s, keep=s["i"] not in cut_by, label=cut_by.get(s["i"])) for s in sents]
    kept = round(sum(s["te"] - s["t"] for s in segs if s["keep"]), 1)
    labels = list(dict.fromkeys(v for v in cut_by.values() if v))
    return dict(kind="keep-spans", by=by, provider=provider, segments=segs, kept_s=kept, total_s=round(total, 1),
                summary=dict(code="draft.keep" if cut_by else ("draft.keep-all-rules" if by == "rules" else
                                                                "draft.keep-all"),
                             params=dict(kept=kept, total=round(total, 1), cuts=labels[:4], n=len(labels))))


def draft_keep(ctx, cp, path, template=None, instruction=None, complete=None):
    words = transcript(ctx)
    sents = sentences(words)
    if not sents:
        raise RuntimeError("the recording has no speech to cut")
    total = sents[-1]["te"] - sents[0]["t"]
    req = ctx.request()
    lang = ctx.lang()
    cut_by, hooks, by, provider, model = {}, [], "rules", None, None
    lines, size = [], 0
    for s in sents:
        ln = f"[{s['i']}] {_mmss(s['t'])}-{_mmss(s['te'])} {s['text']}"
        size += len(ln) + 1
        if size > LINES_CHARS:
            break
        lines.append(ln)
    prev = D.read_side(path, "keep") if instruction else None
    body = "\n".join(x for x in [
        f"Request: {req or '(none)'}",
        f"Instruction (change the current cut accordingly): {instruction}" if instruction else "",
        "Current cuts: " + json.dumps([dict(i=s["i"], label=s.get("label")) for s in
                                       (prev or {}).get("review", {}).get("segments", []) if not s.get("keep")],
                                      ensure_ascii=False) if prev else "",
        "Transcript:", *lines] if x)
    r, ai_error = _ask(complete, SYSTEM_KEEP, lang, body, 4000)
    js = r.get("json") if isinstance(r, dict) and r.get("provider") != "none" and isinstance(r.get("json"), dict) else None
    if js is not None:
        n = len(sents)
        for c in js.get("cuts") or []:
            if not isinstance(c, dict):
                continue
            a, b = _ids(c.get("from"), n), _ids(c.get("to") or c.get("from"), n)
            if a and b:
                for i in range(min(a, b), max(a, b) + 1):
                    cut_by[i] = str(c.get("label") or "").strip()[:60] or cut_by.get(i) or ""
        for h in js.get("hooks") or []:
            if isinstance(h, dict):
                a, b = _ids(h.get("from"), n), _ids(h.get("to") or h.get("from"), n)
                if a and b:
                    hooks.append([sents[min(a, b) - 1]["t"], sents[max(a, b) - 1]["te"]])
        if len(cut_by) >= len(sents):
            raise RuntimeError("the AI cut everything; nothing drafted")
        by, provider, model = "ai", r.get("provider"), r.get("model")
    keep = {s["i"] for s in sents} - set(cut_by)
    cfg = _load_cfg(path) if D.state(path, template, "keep", "promo-recut") in ("drafted", "hers") else {}
    cfg.setdefault("language", ctx.params.get("language") or "zh")
    cfg.setdefault("orientation", ctx.params.get("orientation") or "horizontal")
    cut = dict(cfg.get("cut") or {})
    cut["body"] = _spans(sents, keep)
    cut.setdefault("outro", [])
    cfg["cut"] = cut
    sp = speeds(req + "\n" + (instruction or ""))
    if sp["body"]:
        cfg["rates"] = dict(cfg.get("rates") or {}, body=sp["body"])
    if hooks:
        cfg["hooks"] = dict(cfg.get("hooks") or {}, items=[dict(spans=[[round(a, 2), round(b, 2)]]) for a, b in hooks],
                            **({"speed": sp["hooks"]} if sp["hooks"] else {}))
    elif js is not None and "hooks" in cfg and instruction:
        cfg.pop("hooks", None)
    _write_cfg(path, cfg, "drafted")
    rv = _keep_view(sents, cut_by, total, by, provider)
    if ai_error:
        rv["ai_error"] = ai_error
    rv["hooks"] = len(hooks)
    rv["speeds"] = {k: v for k, v in sp.items() if v}
    if js is not None and js.get("summary"):
        rv["ai_summary"] = str(js["summary"])[:300]
    return dict(by=by, provider=provider, model=model, instruction=instruction, review=rv)


def review_keep(ctx, cp, path, side=None):
    """The keep review: the draft's own (unchanged since), else her file read against the transcript."""
    if side and (side.get("review") or {}).get("kind") == "keep-spans":
        return side["review"]
    js = ctx.item_path("work", "audio.json")
    if not os.path.exists(js):
        return D.outline_review(path, None)
    sents = sentences(transcript(ctx))
    body = [(float(a), float(b)) for a, b in ((_load_cfg(path).get("cut") or {}).get("body") or [])]
    cut_by = {s["i"]: "" for s in sents if not any(a <= (s["t"] + s["te"]) / 2 <= b for a, b in body)}
    total = (sents[-1]["te"] - sents[0]["t"]) if sents else 0
    return _keep_view(sents, cut_by, total, "her")


def apply_keep(a):
    """Her answer to the keep review: {done: true} (the draft as it is), {spans: [[a, b], ...]} (she selected what
    to keep in the transcript: cut.body becomes exactly that), or {content} (an older desk: the file's text)."""
    v = a.value or {}
    path = a.payload.get("file")
    if isinstance(v.get("spans"), list) and path:
        spans = sorted([round(float(x), 2), round(float(y), 2)] for x, y in v["spans"] if float(y) - float(x) > 0.2)
        if not spans:
            raise ValueError("keep: nothing is kept")
        cfg = _load_cfg(path)
        cfg["cut"] = dict(cfg.get("cut") or {}, body=spans)
        _write_cfg(path, cfg, "drafted, then adjusted by you")
        side = D.read_side(path, "keep") or {}
        rv = side.get("review") or {}
        if rv.get("kind") == "keep-spans":
            segs = rv.get("segments") or []
            cut_by = {s["i"]: s.get("label") or "" for s in segs
                      if not any(x <= (s["t"] + s["te"]) / 2 <= y for x, y in spans)}
            new = _keep_view([{k: s[k] for k in ("i", "t", "te", "text")} for s in segs], cut_by,
                             rv.get("total_s") or 0, "her")
            D.write_side(path, "keep", dict(side, by="her", review=new))
    from .common import author_apply
    return author_apply(a)


# --------------------------------------------------------------------------- packaging
def _subs(ctx):
    p = ctx.item_path("work", "draft_subs.txt")
    try:
        with open(p, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    m = re.search(r"\[\s*\n(.*?)\n\]", text, re.S)
    if not m:
        return []
    try:
        rows = json.loads("[" + m.group(1) + "]")
    except ValueError:
        return []
    return [[float(a), float(b), str(t)] for a, b, t in rows if str(t).strip()]


def _files(ctx):
    """Her supporting files: [{name, path, kind screen | clip | shot, duration}]."""
    from vstudio import media
    out = []
    for key, kind in (("broll", None), ("highlights", "clip"), ("screenshots", "shot")):
        v = ctx.inputs.get(key) or []
        for p in (v if isinstance(v, list) else [v]):
            if not isinstance(p, str) or not os.path.isfile(p):
                continue
            k = kind or ("screen" if SCREEN_RE.search(os.path.basename(p)) else "clip")
            d = None
            if k != "shot":
                try:
                    d = round(float(media.duration(p)), 1)
                except Exception:  # noqa: BLE001
                    d = None
            out.append(dict(name=os.path.basename(p), path=p, kind=k, duration=d, key=key))
    return out


def _inside(a, b, spans):
    return any(x - 0.5 <= a and b <= y + 0.5 for x, y in spans)


def draft_package(ctx, cp, path, template=None, instruction=None, complete=None):
    cfg = _load_cfg(path)
    body = [(float(a), float(b)) for a, b in ((cfg.get("cut") or {}).get("body") or [])]
    subs = _subs(ctx)
    files = _files(ctx)
    lang = ctx.lang()
    js, by, provider, model = None, "rules", None, None
    kept = []  # chapters, cover and post need the model even with no files to place
    if os.path.exists(ctx.item_path("work", "audio.json")):
        kept = [s for s in sentences(transcript(ctx)) if _inside(s["t"], s["te"], body) or not body]
    lines = "\n".join(f"{_mmss(s['t'])}-{_mmss(s['te'])} ({s['t']:.1f}-{s['te']:.1f} s) {s['text']}"
                      for s in kept)[:LINES_CHARS]
    flist = "\n".join(f"- {f['name']} ({f['kind']}{', ' + str(f['duration']) + ' s' if f['duration'] else ''})"
                      for f in files) or "(none)"
    msg = "\n".join(x for x in [f"Request: {ctx.request() or '(none)'}",
                                f"Instruction: {instruction}" if instruction else "",
                                f"Files:\n{flist}", "Kept transcript:", lines] if x)
    r, ai_error = _ask(complete, SYSTEM_PACKAGE, lang, msg, 6000)
    if isinstance(r, dict) and r.get("provider") != "none" and isinstance(r.get("json"), dict):
        js, by, provider, model = r["json"], "ai", r.get("provider"), r.get("model")
    by_name = {f["name"]: f for f in files}
    for k in PACKAGE_KEYS:                                     # the packaging is drafted whole, every time
        cfg.pop(k, None)
    if subs:
        cfg["subtitles"] = dict(body=subs)
    taken = []

    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)
    placed = dict(pip=[], cards=[], montage=[])
    if js:
        for p in js.get("pip") or []:
            f = by_name.get(str((p or {}).get("file") or ""))
            try:
                a, b = float(p["start"]), float(p["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not f or f["kind"] == "shot" or b - a < 1.0 or not _inside(a, b, body) or not free(a, b):
                continue
            ms = max(0.0, float(p.get("media_start") or 0))
            if f.get("duration") and ms >= f["duration"]:
                ms = 0.0
            placed["pip"].append(dict(start=round(a, 2), end=round(b, 2), video=f["path"], media_start=round(ms, 2),
                                      **({"tag": str(p["tag"])[:40]} if p.get("tag") else {})))
            taken.append((a, b))
        for c in js.get("cards") or []:
            f = by_name.get(str((c or {}).get("file") or ""))
            try:
                a, b = float(c["start"]), float(c["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not f or f["kind"] != "shot" or b - a < 1.0 or not _inside(a, b, body) or not free(a, b):
                continue
            placed["cards"].append(dict(img=f["path"], start=round(a, 2), end=round(b, 2)))
            taken.append((a, b))
        for c in js.get("montage") or []:
            f = by_name.get(str((c or {}).get("file") or ""))
            try:
                a, b = float(c["start"]), float(c["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not f or f["kind"] == "shot" or b - a < 1.0 or (f.get("duration") and b > f["duration"] + 0.1):
                continue
            placed["montage"].append([f["name"], round(a, 2), round(b, 2), c.get("label") or None])
        if placed["pip"]:
            cfg["pip"] = placed["pip"]
        if placed["cards"]:
            cfg["cards"] = placed["cards"]
        if placed["montage"]:
            cfg["montage"] = dict(clips=placed["montage"])
        ch = [[x[0], str(x[1])[:24]] for x in js.get("chapters") or [] if isinstance(x, list) and len(x) == 2 and
              (x[0] == "start" or (isinstance(x[0], (int, float)) and _inside(float(x[0]), float(x[0]), body)))]
        if ch:
            cfg["chapters"] = ch
        ec = js.get("end_card") if isinstance(js.get("end_card"), dict) else None
        if ec and ec.get("main"):
            cfg["end_card"] = {k: str(ec[k])[:80] for k in ("main", "sub") if ec.get(k)}
        cv = js.get("cover") if isinstance(js.get("cover"), dict) else None
        if cv and cv.get("title"):
            t = cv["title"] if isinstance(cv["title"], list) else [cv["title"]]
            at = cv.get("talk_at")
            cfg["cover"] = dict(title=[str(x)[:30] for x in t[:2]],
                                **({"photo": {"talk_at": float(at)}} if isinstance(at, (int, float)) else {}))
        po = js.get("post") if isinstance(js.get("post"), dict) else None
        if po and po.get("title"):
            cfg["post"] = dict(title=str(po["title"])[:80], body=[str(x)[:600] for x in (po.get("body") or [])[:4]],
                               tags=[str(x)[:20] for x in (po.get("tags") or [])[:8]])
    _write_cfg(path, cfg, "drafted")
    rv = _package_view(cfg, files, by, provider)
    if ai_error:
        rv["ai_error"] = ai_error
    if js and js.get("summary"):
        rv["ai_summary"] = str(js["summary"])[:300]
    return dict(by=by, provider=provider, model=model, instruction=instruction, review=rv)


PACKAGE_KEYS = ("subtitles", "pip", "cards", "montage", "chapters", "end_card", "cover", "post")


def package_present(path):
    """The packaging part of a hand-written config (its captions / cards / montage ...) is there."""
    cfg = _load_cfg(path)
    return any(cfg.get(k) for k in ("subtitles", "pip", "cards", "montage"))


def _package_view(cfg, files, by, provider=None):
    n_screen = len([f for f in files if f["kind"] == "screen"])
    n_clip = len([f for f in files if f["kind"] == "clip"])
    n_shot = len([f for f in files if f["kind"] == "shot"])
    pip, cards = cfg.get("pip") or [], cfg.get("cards") or []
    mont = (cfg.get("montage") or {}).get("clips") or []
    subs = (cfg.get("subtitles") or {}).get("body") or []
    lines = [dict(code="draft.pkg.captions", params=dict(n=len(subs)))]
    if n_screen or pip:
        lines.append(dict(code="draft.pkg.pip", params=dict(n=len(pip), of=n_screen, at=[round(p["start"], 1) for p in pip][:6])))
    if n_shot or cards:
        lines.append(dict(code="draft.pkg.cards", params=dict(n=len(cards), of=n_shot)))
    if n_clip or mont:
        lines.append(dict(code="draft.pkg.montage", params=dict(n=len(mont), of=n_clip)))
    if cfg.get("chapters"):
        lines.append(dict(code="draft.pkg.chapters", params=dict(labels=[c[1] for c in cfg["chapters"]][:8])))
    if (cfg.get("end_card") or {}).get("main"):
        lines.append(dict(code="draft.pkg.end", params=dict(text=cfg["end_card"]["main"])))
    if (cfg.get("cover") or {}).get("title"):
        lines.append(dict(code="draft.pkg.cover", params=dict(text=" / ".join(cfg["cover"]["title"]))))
    left = (n_screen - len(pip)) + (n_shot - len(cards))
    return dict(kind="package", by=by, provider=provider, lines=lines,
                summary=dict(code="draft.package" if by != "rules" else "draft.package-rules",
                             params=dict(captions=len(subs), placed=len(pip) + len(cards) + len(mont), left=max(0, left))))


def review_package(ctx, cp, path, side=None):
    if side and (side.get("review") or {}).get("kind") == "package":
        return side["review"]
    return _package_view(_load_cfg(path), _files(ctx), "her")
