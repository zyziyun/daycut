"""Built-in recipes and their stages (all real: built on vstudio.media / asr / cleanup / subs / export).

longform-slices     one long recording (lecture, webinar, livestream, podcast) + a job list of source ranges
                    -> one vertical short per range (cleaned, captioned, per-platform exports, cover, post stub)
talkinghead-clips   a folder of raw 口播 clips -> one cleaned + captioned short per clip

Stage DAG (both):
  probe(io, shared) -> extract(io, shared: 16 kHz wav) -> asr(asr, shared: ONE transcript per source, reused by
  every job cut from it) -> cleanup(cpu: vstudio.cleanup.analyze on the job's range + hook range) ->
  apply(cpu-render: auto edits + the creator's reply) -> compose(cpu-render: hook cold open + body, speed,
  final-time cues.json + post.json) -> export(cpu-render | face: vstudio.export per platform: reframe, captions in
  the caption box, loudness, cover, post) -> verify(asr: cleanup.verify re-ASR, lost words) ->
  qc(cpu: gates) ; preview(cpu-render: contact sheet + 3 s snippet for the review page)

The vertical layout here is ``vstudio.export``'s reframe (``layout``: face / center / pad-blur / letterbox) of the
whole frame, so longform-slices refuses to run while ``privacy.exclude`` is set (a pad-blur / reframe of the full
frame would show the excluded participant tiles). Screen-share lectures: recipe ``longform-split``
(``lfsplit.py``), which runs every job through the longform-to-short split layout (title / speaker band +
text-following screen crop, chapter card, 记笔记 panel, hook, captions, cover, post) and honours the excludes.
"""
import glob
import os

from . import spec as S
from .recipes import Recipe, Stage, register
from .util import import_ref, read_json, slug, write_json

PRICE_WHISPER_PER_MIN = 0.006           # OpenAI whisper-1 (estimate table; override with spec prices.openai_whisper_min)


# --------------------------------------------------------------------------- helpers
def _p(job):
    return job["params"]


def _src(job):
    return _p(job)["source"]


def _asr_opts(job, spec):
    a = dict(spec.get("asr") or {})
    p = _p(job)
    return dict(language=p.get("language") or a.get("language"), prompt=p.get("asr_prompt") or a.get("prompt"),
                backend=a.get("backend", "auto"), transcriber=a.get("transcriber"))


def _given_transcript(job, spec):
    return _p(job).get("transcript") or (spec.get("inputs") or {}).get("transcript")


def _transcriber(spec):
    ref = (spec.get("asr") or {}).get("transcriber")
    return import_ref(ref) if ref else None


def _price(spec, key, default):
    return float((spec.get("prices") or {}).get(key, default))


def _plats(job):
    return list(_p(job).get("platforms") or [])


def _dur(job, spec):
    return float(_p(job).get("_dur") or 0.0)


def _src_dur(job, spec):
    return float(_p(job).get("_src_dur") or _p(job).get("_dur") or 0.0)


# --------------------------------------------------------------------------- stages
def probe(ctx):
    from vstudio import asr, media
    src = _src(ctx.job)
    info = media.probe(src)
    if not info["has_video"]:
        raise ValueError(f"{src}: no video stream")
    if not info["has_audio"]:
        raise ValueError(f"{src}: no audio stream (speech recipes need one)")
    sha = asr.file_hash(src)
    out = {k: info[k] for k in ("duration", "display_w", "display_h", "fps", "has_audio", "hdr")}
    return dict(out, path=src, sha1=sha, digest=sha, files=[src])


def extract(ctx):
    from vstudio import media
    wav = ctx.path("audio16k.wav")
    media.extract_wav(_src(ctx.job), wav, sr=16000, channels=1)
    return dict(wav=wav, files=[wav])


def run_asr(ctx):
    from vstudio import asr
    given = _given_transcript(ctx.job, ctx.spec)
    o = _asr_opts(ctx.job, ctx.spec)
    if given:
        tr = read_json(given)
        if tr is None:
            raise ValueError(f"transcript {given} unreadable")
        path = given
    else:
        from . import transcripts as TS
        sha = (ctx.inputs.get("probe") or {}).get("sha1")
        fn = _transcriber(ctx.spec)
        hit_path, tr = (None, None) if fn else TS.lookup(sha, o["language"], o["prompt"], o["backend"])
        if tr is not None:                                # plan-segments already transcribed this recording
            ctx.log(f"transcript reused from the shared per-source cache ({os.path.basename(hit_path)})")
            given = hit_path
        elif fn:
            tr = fn(ctx.inputs["extract"]["wav"], language=o["language"], prompt=o["prompt"])
        else:
            tr = asr.transcribe(ctx.inputs["extract"]["wav"], language=o["language"], prompt=o["prompt"],
                                backend=o["backend"])
            TS.save(sha, tr, o["language"], o["prompt"], o["backend"])
        path = write_json(ctx.path("transcript.json"), tr)
    nw = len(tr.get("words") or []) if isinstance(tr, dict) else len(tr or [])
    cost = 0.0
    if not given and o["backend"] == "openai":
        cost = _src_dur(ctx.job, ctx.spec) / 60.0 * _price(ctx.spec, "openai_whisper_min", PRICE_WHISPER_PER_MIN)
    return dict(transcript=path, words=nw, dropped=len(tr.get("dropped") or []) if isinstance(tr, dict) else 0,
                files=[path], cost_usd=cost)


def cleanup_overrides(p):
    """Batch cleanup overrides: the row's ``cleanup_overrides`` + the confirm policy (on unless the row / defaults
    say ``cleanup_policy: false``): low-risk confirm edits are answered from the policy + the creator's history."""
    ov = dict(p.get("cleanup_overrides") or {})
    ov.setdefault("policy", bool(p.get("cleanup_policy", True)))
    return ov


def cleanup_params(*keys, optional=()):
    """Stage params of a cleanup stage: the row keys + the confirm policy digest (a learned change re-runs it).
    ``optional`` keys only count when set (a new key never re-keys the jobs that do not use it)."""
    def f(job, spec):
        from vstudio import cleanup as C
        d = {k: _p(job).get(k) for k in keys}
        d.update({k: _p(job)[k] for k in optional if _p(job).get(k)})
        if _p(job).get("cleanup_policy", True) is not False:
            d["policy"] = C.policy_digest()
        return d
    return f


def run_cleanup(ctx):
    from vstudio import cleanup as C
    p, src = ctx.params, _src(ctx.job)
    tr = ctx.inputs["asr"]["transcript"]
    prof = p.get("cleanup_profile")
    prof = None if prof in (None, "off") else prof
    rng = p.get("range")
    kw = dict(transcript=tr, language=p.get("language") or (ctx.spec.get("asr") or {}).get("language"),
              profile=prof, overrides=cleanup_overrides(p), force=True)
    ranges = [tuple(rng)] if rng else None
    if p.get("cuts"):                                 # `job edit --op cut`: inner cuts (word-snapped) leave the range
        from .lfsplit import _cuts, _subtract
        a0, b0 = (float(rng[0]), float(rng[1])) if rng else (0.0, _src_dur(ctx.job, ctx.spec) or 1e9)
        ranges = _subtract(a0, b0, [c[:2] for c in _cuts(p["cuts"])])
        if not ranges:
            raise ValueError("the row cuts leave nothing of the range")
    body = C.analyze(src, ranges=ranges, out=ctx.path("body.cleanup.json"),
                     review=ctx.path("body_review.md"), **kw)
    out = dict(body=body["_path"], hook=None, files=[body["_path"]])
    edits = [dict(e, part="body") for e in body["edits"]]
    if p.get("hook"):
        hk = C.analyze(src, ranges=[tuple(p["hook"]["src"])], out=ctx.path("hook.cleanup.json"),
                       review=ctx.path("hook_review.md"), id_offset=len(body["edits"]), **kw)
        out["hook"] = hk["_path"]
        out["files"].append(hk["_path"])
        edits += [dict(e, part="hook") for e in hk["edits"]]
    confirm = [dict(id=e["id"], part=e["part"], kind=e["kind"], text=e.get("text", ""), t0=e["t0"], t1=e["t1"],
                    before=e.get("before", ""), after=e.get("after", ""), reason=e.get("reason", ""),
                    confidence=e.get("confidence")) for e in edits if e["action"] == "confirm"]
    write_json(ctx.path("confirm.json"), confirm)
    out.update(confirm=len(confirm), auto=sum(e["action"] == "auto" for e in edits),
               confirm_file=ctx.path("confirm.json"), policy=C.policy_counts(edits),
               saved_s=round(body["stats"]["source_s"] - body["stats"]["auto_s"], 2))
    return out


def run_apply(ctx):
    from vstudio import cleanup as C
    p, src = ctx.params, _src(ctx.job)
    reply = p.get("cleanup_reply")
    r = C.parse_reply(reply) if reply else dict(approve=set(), keep=set(), all_confirm=False)
    off = p.get("cleanup_profile") == "off"
    out = dict(files=[])
    for part in ("body", "hook"):
        edl = ctx.inputs["cleanup"].get(part)
        if not edl:
            continue
        E = read_json(edl)
        ids = {e["id"] for e in E["edits"]}
        keep = ids if off else (set(r["keep"]) & ids)
        res = C.apply(edl, approve=set(r["approve"]) & ids, keep=keep, all_confirm=bool(r["all_confirm"]) and not off,
                      out=ctx.path(f"{part}.mp4"), media_path=src, force=True)
        out[part] = res["out"]
        out[f"{part}_sidecar"] = res["sidecar"]
        out[f"{part}_dur"] = round(res["duration"], 3)
        out["files"].append(res["out"])
    return out


def _cues_from(sidecar, max_chars=None):
    from vstudio import subs
    S_ = read_json(sidecar) or {}
    return subs.cues_from_words(S_.get("words") or [], max_chars=max_chars)


def run_compose(ctx):
    from vstudio import media, subs
    p, ins = ctx.params, ctx.inputs["apply"]
    s = float(p.get("speed") or 1.0)
    hs = float(p.get("hook_speed") or s)
    pieces, cues, t = [], [], 0.0
    mc = p.get("max_chars")
    if ins.get("hook"):
        hd = ins["hook_dur"] / hs
        lines = list((p.get("hook") or {}).get("lines") or [])
        if lines:
            step = hd / len(lines)
            cues += [subs.Cue(k * step, (k + 1) * step, ln, meta={"kind": "hook"}) for k, ln in enumerate(lines)]
        else:
            cues += [subs.Cue(c.start / hs, c.end / hs, c.text, meta={"kind": "hook"})
                     for c in _cues_from(ins["hook_sidecar"], mc)]
        pieces.append((ins["hook"], hs))
        t = hd
    cues += [subs.Cue(t + c.start / s, t + c.end / s, c.text) for c in _cues_from(ins["body_sidecar"], mc)]
    pieces.append((ins["body"], s))
    master = ctx.path("master.mp4")
    if len(pieces) == 1 and abs(s - 1.0) < 1e-6:
        media.link_or_copy(ins["body"], master)
    else:
        fps = media.probe(ins["body"])["fps"] or 30
        args, graph = [], []
        for i, (path, sp) in enumerate(pieces):
            args += ["-i", path]
            vs = f"setpts=(PTS-STARTPTS)/{sp:.6g}" if abs(sp - 1) > 1e-6 else "setpts=PTS-STARTPTS"
            at = media.atempo_chain(sp) + "," if abs(sp - 1) > 1e-6 else ""
            graph.append(f"[{i}:v:0]{vs},fps={fps:.6g},format=yuv420p[v{i}]")
            graph.append(f"[{i}:a:0]{at}aresample=48000,asetpts=PTS-STARTPTS[a{i}]")
        n = len(pieces)
        graph.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
        media.run(["ffmpeg", "-y", *args, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
                   "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", master])
    dur = media.probe(master)["duration"]
    cues_path = write_json(ctx.path("cues.json"), {"cues": [c.to_dict() for c in cues]})
    hook_lines = (p.get("hook") or {}).get("lines") or []
    post = dict(title=p.get("title") or "", hook=p.get("post_hook") or "".join(hook_lines[:1]),
                body=p.get("body") or "", tags=p.get("tags") or None,
                use_persona_tags=p.get("use_persona_tags", True), tag_set=p.get("tag_set"))
    write_json(ctx.path("post.json"), post)
    return dict(master=master, cues=cues_path, post=ctx.path("post.json"), duration=round(dur, 3),
                hook_dur=round(t, 3), n_cues=len(cues), files=[master, cues_path])


def _export_resource(job, spec):
    return "face" if _p(job).get("layout") == "face" else "cpu-render"


def entity_post(post, fixes=None):
    """Post copy with the captions' named-entity fixes (one truth: the title / body / tags say 洪都拉斯 when the
    captions do), plus the rule-based check of the copy itself (CLDR place names, when proofread did not run)."""
    from vstudio import entities as ENT
    if not isinstance(post, dict):
        return post
    fx = list(fixes or [])
    txt = "\n".join(str(v) for v in post.values() if isinstance(v, str)) + "\n" + "\n".join(
        str(x) for v in post.values() if isinstance(v, list) for x in v if isinstance(x, str))
    have = {f["from"] for f in fx}
    fx += [f for f in ENT.verify(txt)["fixes"] if f["from"] not in have]
    return ENT.fix_post(post, fx)


def run_export(ctx):
    from vstudio import export as X
    p, c = ctx.params, ctx.inputs["compose"]
    post = read_json(c["post"])
    if p.get("_copy_orig"):                           # copy edited in review: the post says the new copy
        post.update(title=p.get("title") or "", body=p.get("body") or "", tags=p.get("tags") or None)
    post = entity_post(post, (ctx.inputs.get("proofread") or {}).get("entity_fixes"))
    covers = p.get("cover")
    if isinstance(covers, dict):                      # `job edit --op cover`: {t, text, file}
        covers = [covers["file"]] if covers.get("file") else None
    ctx.caption_edits = None
    man = X.export(c["master"], _plats(ctx.job), out_dir=ctx.path("exports"),
                   cues=caption_cues(ctx) if p.get("captions", True) else None, covers=covers, post=post,
                   mode=p.get("layout") or "pad-blur", preset=p.get("preset") or "medium",
                   captions=bool(p.get("captions", True)),
                   **({"crop_bottom": float(p.get("crop_bottom", 0.28))} if p.get("layout") == "band" else {}))
    files = [ctx.path("exports", e["file"]) for e in man["exports"]]
    exports = [dict(platform=e["platform"], orientation=e["orientation"], file=ctx.path("exports", e["file"]),
                    cover=ctx.path("exports", e["cover"]) if e.get("cover") else None,
                    post=ctx.path("exports", e["post"]) if e.get("post") else None,
                    duration=e["duration"]) for e in man["exports"]]
    from .lengthfit import fit_exports
    fit = fit_exports(exports, p, ctx.spec, None, preset=p.get("preset") or "medium")
    if fit:                                           # shorter platform variants: the manifest follows
        for e in man["exports"]:
            x = next(x for x in exports if (x["platform"], x["orientation"]) == (e["platform"], e["orientation"]))
            if x.get("variant"):
                e.update(duration=x["duration"], variant=x["variant"])
                e.pop("loudness", None)
        write_json(ctx.path("exports", "manifest.json"), man)
    out = dict(manifest=ctx.path("exports", "manifest.json"), files=files, exports=exports,
               warnings=man["warnings"], length_fit=fit)
    if getattr(ctx, "caption_edits", None):
        out["caption_overrides"] = ctx.caption_edits
    return out


ZH_HINT = "以下是普通话的句子，使用简体中文。"


def hear_opts(job, spec):
    """ASR options of the verify re-hearing: the source's, plus (Chinese) a simplified-Chinese hint - whisper on a
    finished cut sometimes switches to traditional characters, and every one of those reads as a lost word."""
    o = dict(_asr_opts(job, spec))
    if str(o.get("language") or "").lower().startswith("zh"):
        o["prompt"] = ZH_HINT + (str(o["prompt"]) if o.get("prompt") else "")
    return o


def run_verify(ctx):
    from vstudio import cleanup as C
    o = hear_opts(ctx.job, ctx.spec)
    fn = _transcriber(ctx.spec)
    tfn = (lambda path: fn(path, language=o["language"], prompt=o["prompt"])) if fn else None
    ins = ctx.inputs["apply"]
    reps, heard = {}, {}
    for part in ("body", "hook"):
        if ins.get(part):
            got = hear(ins[part], tfn, o)
            heard[part] = write_json(ctx.path(f"{part}.heard.json"), got)
            r = C.verify(ins[part], got=got, write=False, recheck=True, transcriber=tfn, language=o["language"],
                         prompt=o["prompt"])
            reps[part] = dict(ok=r["ok"], missing=r["missing"], leftovers=r["leftovers"], variants=r["variants"],
                              ignored=r["ignored"], rechecked=r["rechecked"])
    path = write_json(ctx.path("verify.json"), reps)
    cost = 0.0
    if not fn and o["backend"] == "openai":
        cost = _dur(ctx.job, ctx.spec) / 60.0 * _price(ctx.spec, "openai_whisper_min", PRICE_WHISPER_PER_MIN)
    return dict(ok=all(r["ok"] for r in reps.values()), report=path, files=[path] + list(heard.values()), cost_usd=cost,
                missing=sum(len(r["missing"]) for r in reps.values()), heard=heard)


def hear(path, tfn, o):
    """A fresh ASR of a finished cut (the configured transcriber, else ``asr.transcribe``), kept for proofread."""
    from vstudio import asr
    got = tfn(path) if tfn else asr.transcribe(path, language=o["language"], prompt=o["prompt"],
                                               backend=o.get("backend") or "auto")
    return got if isinstance(got, (dict, list)) else list(got)


# --------------------------------------------------------------------------- proofread
def proofread_opts(spec):
    """Spec ``proofread: {provider: auto|claude|openai|<any vstudio.llm provider>|none, model, low_conf, enabled,
    glossary, glossary_provider, glossary_model, filler_edges}`` with the providers resolved now (a key appearing /
    vanishing changes the stage key). ``auto`` follows the llm routes for tasks proofread / glossary."""
    from vstudio import proofread as PR
    o = dict(spec.get("proofread") or {})
    return dict(provider=PR.resolve_provider(o.get("provider")), model=o.get("model"),
                low_conf=float(o.get("low_conf", 0.5)), enabled=o.get("enabled", True) is not False,
                call=o.get("call"), glossary=o.get("glossary", True) is not False,
                glossary_model=o.get("glossary_model"), filler_edges=o.get("filler_edges", True) is not False,
                glossary_provider=PR.resolve_provider(o.get("glossary_provider") or o.get("provider"), task="glossary"))


def _proofread_on(job, spec):
    return proofread_opts(spec)["enabled"] and _p(job).get("captions", True) is not False


def _proofread_resource(job, spec):
    pr = proofread_opts(spec)["provider"]
    return "cpu" if pr == "none" else f"api:{pr}"


def _proofread_params(job, spec):
    o = proofread_opts(spec)
    d = dict(provider=o["provider"], model=o["model"], low_conf=o["low_conf"], call=o["call"],
             term_fixes=(spec.get("subtitles") or {}).get("term_fixes"), filler_edges=o["filler_edges"], v=2)
    if o["provider"] != "none" or o["call"]:          # the LLM prompt's context (a review copy edit does not re-ask;
        from .edits import key_copy                   # the notes are a hint only: a notes edit never re-proofreads)
        d.update(asr=(spec.get("asr") or {}).get("prompt"), title=key_copy(_p(job), "title"), chapter=_p(job).get("chapter"),
                 series=_p(job).get("series"))
    return d


def _glossary_on(job, spec):
    o = proofread_opts(spec)
    return _proofread_on(job, spec) and o["glossary"] and (o["glossary_provider"] != "none" or bool(o["call"]))


def _glossary_model(o):
    return o["glossary_model"] or (o["model"] if o["glossary_provider"] == o["provider"] else None)


def _glossary_params(job, spec):
    """Shared per source: everything here must be the same for every job cut from that source."""
    o = proofread_opts(spec)
    return dict(provider=o["glossary_provider"], model=_glossary_model(o), call=o["call"],
                term_fixes=(spec.get("subtitles") or {}).get("term_fixes"), asr=(spec.get("asr") or {}).get("prompt"),
                series=(spec.get("vertical") or {}).get("series") or _p(job).get("series"), v=1)


def _gloss_context(spec, series=None):
    gl = [x.strip() for x in str((spec.get("asr") or {}).get("prompt") or "").split(",") if x.strip()]
    gl += [str(f[1]) for f in (spec.get("subtitles") or {}).get("term_fixes") or [] if isinstance(f, (list, tuple))]
    return gl


def transcript_text(transcript, term_fixes=None):
    """The whole transcript as caption-like text (one line per whisper segment), term fixes applied."""
    from vstudio import asr
    from vstudio import cleanup as C
    segs = transcript.get("segments") if isinstance(transcript, dict) else None
    if segs and all("text" in s_ for s_ in segs):        # the segment text is what build_subs burns
        return "\n".join(asr.apply_term_fixes(str(s_["text"]).strip(), term_fixes or None) for s_ in segs
                         if str(s_["text"]).strip())
    W = C.load_words(transcript)
    lines, cur = [], []
    for w in W:
        cur.append(w)
        if w["end"]:
            lines.append(C.join_words(cur))
            cur = []
    if cur:
        lines.append(C.join_words(cur))
    return "\n".join(asr.apply_term_fixes(x, term_fixes or None) for x in lines)


def run_glossary(ctx):
    """ONE proofreading glossary per source (shared): domain terms + recurring ASR confusions from the whole
    transcript, validated (vstudio.proofread.build_glossary); every job's proofread applies the same fixes."""
    from vstudio import proofread as PR
    o = proofread_opts(ctx.spec)
    tr = read_json(ctx.inputs["asr"]["transcript"])
    tf = (ctx.spec.get("subtitles") or {}).get("term_fixes")
    text = transcript_text(tr, tf)
    series = (ctx.spec.get("vertical") or {}).get("series") or ctx.params.get("series")
    call = import_ref(o["call"]) if o["call"] else None
    res = PR.build_glossary(text, context=dict(topic=series, glossary=_gloss_context(ctx.spec)),
                            provider=o["glossary_provider"], model=_glossary_model(o), call=call, prices=ctx.spec.get("prices"))
    path = write_json(ctx.path("glossary.json"), res)
    ctx.log(f"glossary ({res['provider']}): {len(res['terms'])} term(s), {len(res['fixes'])} fix(es), "
            f"{len(res['rejected'])} rejected")
    from .util import sha1_json
    return dict(glossary=path, terms=len(res["terms"]), fixes=len(res["fixes"]), files=[path],
                cost_usd=res["cost_usd"], digest=sha1_json([res["terms"], res["fixes"]]))


def _heard_words(ctx):
    """The verify re-ASR words in OUTPUT (cue) time: the longform-split verify hears the final cut itself; the
    speech recipes hear hook / body separately (cut time) -> / speed, body after the hook."""
    from vstudio import proofread as PR
    v = ctx.inputs.get("verify") or {}
    heard = v.get("heard") or {}
    if isinstance(heard, str):
        return PR.words_of(read_json(heard))
    p = ctx.params
    s = float(p.get("speed") or 1.0)
    hs = float(p.get("hook_speed") or s)
    off = float((ctx.inputs.get("compose") or {}).get("hook_dur") or 0.0)
    out = []
    for part, sp, t0 in (("hook", hs, 0.0), ("body", s, off)):
        if heard.get(part):
            for w in PR.words_of(read_json(heard[part])):
                w = dict(w)
                for k in ("start", "end", "t", "te"):
                    if w.get(k) is not None:
                        w[k] = t0 + float(w[k]) / sp
                out.append(w)
    return out


def run_proofread(ctx):
    """Caption proofreading before burn-in: term fixes, the source glossary, minimal LLM corrections (provider
    claude / openai / none) validated against the audio (no deleted / added words), low-confidence words, then no
    caption starting / ending on a filler; corrected cues.json + proofread.json (every change logged)."""
    from vstudio import proofread as PR
    from .edits import locked_cues
    o = proofread_opts(ctx.spec)
    c = ctx.inputs["compose"]
    cues = (read_json(c["cues"], {}) or {}).get("cues", [])
    p = ctx.params
    context = proofread_context(ctx.spec, p)
    call = import_ref(o["call"]) if o["call"] else None
    g = (ctx.inputs.get("glossary") or {}).get("glossary")
    glossary = read_json(g, {}) if g else None
    locked = locked_cues(cues, p.get("caption_overrides"))       # the creator's own caption fixes are final
    res = PR.proofread(cues, term_fixes=(ctx.spec.get("subtitles") or {}).get("term_fixes"), provider=o["provider"],
                       model=o["model"], context=context, heard=_heard_words(ctx), low_conf=o["low_conf"], call=call,
                       prices=ctx.spec.get("prices"), glossary=glossary, cache=proofread_cache(ctx.batch_dir),
                       locked=locked)
    out_cues = res.pop("cues")
    if o["filler_edges"]:
        out_cues, res["filler_edges"] = PR.fix_filler_edges(out_cues, max_chars=int(p.get("max_chars") or 24),
                                                            locked=locked)
    cues_path = write_json(ctx.path("cues.json"), {"cues": out_cues})
    rep = write_json(ctx.path("proofread.json"), res)
    cs = res.get("cache") or {}
    ctx.log(f"proofread ({res['provider']}): {len(res['changes'])} change(s), {len(res['rejected'])} rejected, "
            f"{len(res['low_confidence'])} low-confidence word(s); cache {cs.get('hits', 0)} hit(s), "
            f"{cs.get('sent', 0)} cue(s) sent" + (f", {len(locked)} locked (caption edits)" if locked else ""))
    ent = (res.get("entities") or {}).get("fixes") or []
    ent += [dict(f, source="glossary") for f in (glossary or {}).get("fixes") or []
            if str(f.get("checked") or "").startswith("entity:")]
    return dict(cues=cues_path, report=rep, files=[cues_path, rep], cost_usd=res["cost_usd"],
                changes=len(res["changes"]), provider=res["provider"], digest=sha1_file(cues_path),
                entity_fixes=[{k: f.get(k) for k in ("from", "to", "kind", "source", "why")} for f in ent])


def proofread_context(spec, p):
    """The LLM context of one job's proofread: topic (series / chapter / the planned title), the term list, the
    notes (a hint only - not part of the cache key)."""
    from .edits import key_copy
    topic = [(spec.get("vertical") or {}).get("series"), p.get("series"), p.get("chapter"), key_copy(p, "title")]
    return dict(topic=" / ".join(dict.fromkeys(str(x) for x in topic if x)), glossary=_gloss_context(spec),
                notes=[str(x) for x in list(p.get("notes") or [])[:6]])


def proofread_cache(batch_dir):
    """``<batch>/cache/proofread-cues``: the per-cue LLM results (``vstudio.proofread.CueCache``)."""
    from vstudio import proofread as PR
    return PR.CueCache(os.path.join(batch_dir, "cache", "proofread-cues")) if batch_dir else None


def seed_proofread_cache(batch_dir, spec, job, rows):
    """A job proofread before the per-cue cache existed: put its reviewed LLM results into the cache (per compose
    cue: the text after term fixes + glossary -> the text after the LLM), so its next proofread re-sends nothing
    the creator already saw. Skipped when that proofread degraded (provider warnings) or nothing matches.
    -> number of cues seeded."""
    from vstudio import proofread as PR
    o = proofread_opts(spec)
    pr = (rows.get("proofread") or {}).get("out") or {}
    cm = (rows.get("compose") or {}).get("out") or {}
    if o["provider"] == "none" and not o["call"] or not pr.get("report") or not cm.get("cues"):
        return 0
    rep = read_json(pr["report"], {}) or {}
    if rep.get("cache") is not None or rep.get("provider") in (None, "none") or \
            any(w.get("source") == "provider" for w in rep.get("warnings") or []):
        return 0
    d = read_json(cm["cues"], {}) or {}
    cues = d.get("cues") if isinstance(d, dict) else d
    if not cues:
        return 0
    g = ((rows.get("glossary") or {}).get("out") or {}).get("glossary")
    glossary = read_json(g, {}) if g else None
    p = job["params"]
    tf = (spec.get("subtitles") or {}).get("term_fixes")
    context = proofread_context(spec, p)
    pre = PR.proofread(cues, term_fixes=tf, provider="none", glossary=glossary, context=context)["cues"]
    mdl = rep.get("model") or o["model"] or PR.default_model(rep["provider"])
    ch = PR.context_hash(rep["provider"], mdl, glossary, PR.ascii_boundaries(tf), context, 2)
    cc = proofread_cache(batch_dir)
    llm = {}
    for c in rep.get("changes") or []:
        if c.get("source") == "llm" and isinstance(c.get("i"), int):
            llm.setdefault(c["i"], []).append(c)
    if any(i >= len(cues) or llm[i][0].get("before") != pre[i]["text"] for i in llm):
        return 0                                       # the report does not belong to these compose cues
    n = 0
    for i, c in enumerate(cues):
        key = PR.cue_key(c["text"], ch)
        if cc.get(key) is not None:
            continue
        mine = [{k: v for k, v in x.items() if k not in ("i", "start", "end")} for x in llm.get(i, [])]
        cc.put(key, dict(pre=pre[i]["text"], text=mine[-1]["after"] if mine else pre[i]["text"], changes=mine,
                         seeded=True))
        n += 1
    return n


def sha1_file(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def caption_cues(ctx):
    """The cues to burn: proofread's when it ran, else compose's; review caption edits (``caption_overrides``)
    applied on top (written to the stage folder)."""
    pr = ctx.inputs.get("proofread") or {}
    path = pr.get("cues") or ctx.inputs["compose"]["cues"]
    ov = ctx.params.get("caption_overrides")
    if not ov:
        return path
    from .edits import apply_caption_overrides
    d = read_json(path, {}) or {}
    cues = d.get("cues") if isinstance(d, dict) else d
    cm = read_json(ctx.inputs["compose"]["cues"], {}) or {}
    asr_cues = cm.get("cues") if isinstance(cm, dict) else cm
    cues, applied, missed = apply_caption_overrides(cues, ov, asr_cues=asr_cues)
    for m in missed:
        ctx.log(f"caption edit not applied (cue changed since): #{m.get('i')} {m.get('from')!r} -> {m.get('to')!r}")
    ctx.caption_edits = overrides_report(applied, missed)
    out = dict(d, cues=cues) if isinstance(d, dict) else dict(cues=cues)
    return write_json(ctx.path("cues.edited.json"), out)


def overrides_report(applied, missed):
    """Export-stage record of the creator's caption edits: how many landed, which could not be placed (QC warns)."""
    return dict(applied=len(applied), missed=[dict(i=m.get("i"), **{"from": m.get("from"), "to": m.get("to")})
                                              for m in missed])


def run_qc(ctx):
    from .qc import run_gates
    res = run_gates(ctx.job, ctx.spec, ctx.inputs)
    path = write_json(ctx.path("qc.json"), res)
    return dict(res, report=path, files=[path])


def run_preview(ctx):
    from vstudio import media
    ex = ctx.inputs["export"]["exports"]
    if not ex:
        raise ValueError("no exports to preview")
    f = ex[0]["file"]
    dur = media.duration(f)
    sheet = ctx.path("sheet.jpg")
    n = 8
    media.contact_sheet(f, sheet, every=max(0.25, dur / n), cols=4, thumb_w=200, max_frames=n,
                        start=max(0.0, dur / (2 * n)))
    snip = ctx.path("snippet.mp4")
    t0 = max(0.0, min(dur - 3.0, dur / 3.0))
    # same resolution, low bitrate (BATCH v0.2: proxies keep the final layout, only the bitrate drops)
    media.run(["ffmpeg", "-y", "-ss", f"{t0:.3f}", "-i", f, "-t", "3", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "34", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", snip])
    return dict(sheet=sheet, snippet=snip, source=f, files=[sheet, snip])


# --------------------------------------------------------------------------- stage lists
def _stat_params(job, spec):
    src = _src(job)
    try:
        st = os.stat(src)
        return dict(path=src, size=st.st_size, mtime=int(st.st_mtime))
    except OSError:
        return dict(path=src, missing=True)


def _keyp(*keys):
    return lambda job, spec: {k: _p(job).get(k) for k in keys}


def _export_params(job, spec):
    d = dict(_keyp("platforms", "layout", "crop_bottom", "captions", "cover", "preset", "trims")(job, spec),
             max_len=_p(job).get("max_len") or spec.get("max_len"))
    if _p(job).get("caption_overrides"):              # only when set: older batches keep their keys
        d["caption_overrides"] = _p(job)["caption_overrides"]
    return d


def _compose_params(job, spec):
    from .edits import key_copy
    d = _keyp("speed", "hook_speed", "hook", "post_hook", "max_chars", "use_persona_tags", "tag_set")(job, spec)
    d.update({k: key_copy(_p(job), k) for k in ("title", "body", "tags")})   # post.json; review copy edits are
    return d                                                                 # applied at export


def _no_given(job, spec):
    return not _given_transcript(job, spec)


def _asr_resource(job, spec):
    return "api:openai" if (spec.get("asr") or {}).get("backend") == "openai" else "asr"


def _asr_cost(units):
    def f(job, spec):
        if (spec.get("asr") or {}).get("backend") != "openai":
            return 0.0
        return units(job, spec) / 60.0 * _price(spec, "openai_whisper_min", PRICE_WHISPER_PER_MIN)
    return f


def _verify_on(job, spec):
    return (spec.get("qc") or {}).get("verify", True) is not False


def speech_stages():
    return [
        Stage("probe", "io", probe, shared=True, params=_stat_params, units=lambda j, s: 1.0, retries=1),
        Stage("extract", "io", extract, deps=("probe",), shared=True, params=lambda j, s: dict(sr=16000),
              units=_src_dur, enabled=_no_given, purge=("*.wav",)),
        Stage("asr", _asr_resource, run_asr, deps=("probe", "extract"), shared=True,
              params=lambda j, s: dict(_asr_opts(j, s), given=_given_transcript(j, s)),
              units=lambda j, s: _src_dur(j, s) if _no_given(j, s) else 0.0,     # a given transcript is only read
              cost=lambda j, s: _asr_cost(_src_dur)(j, s) if _no_given(j, s) else 0.0, retries=3),
        Stage("cleanup", "cpu", run_cleanup, deps=("probe", "asr"),
              params=cleanup_params("range", "hook", "cleanup_profile", "cleanup_overrides", "cleanup_policy", "language",
                                    optional=("cuts",)),
              units=_dur, version=4),
        Stage("apply", "cpu-render", run_apply, deps=("cleanup",), params=_keyp("cleanup_reply", "cleanup_profile"),
              units=_dur, purge=("*.mp4", "*.wav", "*.asr.json")),
        Stage("compose", "cpu-render", run_compose, deps=("apply",), params=_compose_params,
              units=_dur, purge=("master.mp4",)),
        Stage("glossary", _proofread_resource, run_glossary, deps=("asr",), shared=True, params=_glossary_params,
              enabled=_glossary_on, units=lambda j, s: 1.0, cost=lambda j, s: 0.05, retries=2),
        Stage("proofread", _proofread_resource, run_proofread, deps=("compose", "verify", "glossary"),
              params=_proofread_params, enabled=_proofread_on, units=lambda j, s: 1.0,
              cost=lambda j, s: 0.02 if proofread_opts(s)["provider"] != "none" else 0.0),
        Stage("export", _export_resource, run_export, deps=("compose", "proofread"),
              params=_export_params,
              units=lambda j, s: _dur(j, s) * max(1, len(_plats(j))), purge=("exports/*.mp4", "exports/*.mov")),
        Stage("verify", "asr", run_verify, deps=("apply",), params=lambda j, s: hear_opts(j, s), units=_dur,
              enabled=_verify_on, cost=_asr_cost(_dur), version=5),
        Stage("qc", "cpu", run_qc, deps=("cleanup", "apply", "compose", "export", "verify"),
              params=lambda j, s: dict(qc=s.get("qc") or {}, title=_p(j).get("title"), recipe=j.get("recipe")),
              units=lambda j, s: _dur(j, s) * max(1, len(_plats(j)))),
        Stage("preview", "cpu-render", run_preview, deps=("export",), units=lambda j, s: 1.0),
    ]


# --------------------------------------------------------------------------- expansion
def _probe_dur(path):
    from vstudio import media
    return float(media.probe(path)["duration"])


def expand_longform(spec, rows):
    src = (spec.get("inputs") or {}).get("source")
    if not src:
        raise ValueError("longform-slices: inputs.source (the long recording) is required")
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    total = _probe_dur(src)
    excl = (spec.get("privacy") or {}).get("exclude")
    items = []
    for r in rows:
        p = S.with_defaults(spec, r)
        if excl:
            from .lfsplit import PrivacyError
            raise PrivacyError(
                f"longform-slices: privacy.exclude is set but job {r['id']} would be reframed with layout "
                f"{p.get('layout') or 'pad-blur'!r} - vstudio.export's pad-blur / face / center reframe uses the WHOLE "
                "frame, so the excluded region (participant tiles) would show. Use recipe: longform-split (split "
                "layout from the screen region, excludes painted out) for screen-share recordings.")
        if not p.get("range"):
            raise ValueError(f"longform-slices: job {r['id']} has no range (start/end)")
        a, b = p["range"]
        a, b = max(0.0, a), min(total, b)
        if b - a < 1.0:
            raise ValueError(f"job {r['id']}: range {p['range']} is empty / outside the {total:.1f}s recording")
        p["range"] = [a, b]
        p["source"] = src
        hook = p.get("hook") or (p.get("hooks") or [None])[0]
        p["_dur"] = round(b - a + ((hook["src"][1] - hook["src"][0]) if hook else 0.0), 3)
        p["_src_dur"] = round(total, 3)
        items.append(dict(item=r["id"], params=p))
    return items


VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm")


def expand_clips(spec, rows):
    inp = spec.get("inputs") or {}
    clips = list(inp.get("clips") or [])
    if inp.get("folder"):
        pats = S.split_list(inp.get("glob")) or ["*"]
        for pat in pats:
            clips += sorted(f for f in glob.glob(os.path.join(inp["folder"], pat))
                            if f.lower().endswith(VIDEO_EXT) and not os.path.basename(f).startswith("."))
    clips = list(dict.fromkeys(clips))
    if not clips:
        raise ValueError("talkinghead-clips: no clips (inputs.folder [+ glob] or inputs.clips)")
    by = {}
    for r in rows:
        key = r.get("file") or r["id"]
        by[os.path.splitext(os.path.basename(str(key)))[0]] = r
    items = []
    for c in clips:
        stem = os.path.splitext(os.path.basename(c))[0]
        r = by.get(stem) or by.get(slug(stem)) or {"id": slug(stem), "_auto_id": True}
        if r.get("skip"):
            continue
        p = S.with_defaults(spec, r)
        p.pop("file", None), p.pop("_auto_id", None)
        p["source"] = os.path.abspath(c)
        d = _probe_dur(c)
        rng = p.get("range")
        p["_dur"] = round((rng[1] - rng[0]) if rng else d, 3)
        p["_src_dur"] = round(d, 3)
        items.append(dict(item=slug(stem) if r.get("_auto_id") else r["id"], params=p))
    return items


VIDEO_ACCEPT = [".mp4", ".mov", ".m4v", ".mkv", ".webm"]
IN_TRANSCRIPT = dict(key="inputs.transcript", label="Existing transcript (optional)", kind="file", required=False,
                     accept=[".json"], help="an asr.transcribe / whisper JSON of the same recording: skips ASR")
IN_SEGMENTS = dict(key="segments", label="Job list", kind="file", required=True, accept=[".yaml", ".yml", ".csv", ".json"],
                   help="one row per short: id, start / end (source s), title, hook, tags, platforms ...")
COMMON_ROW = ["id", "range", "start", "end", "title", "body", "tags", "hook", "hooks", "platforms", "layout", "speed",
              "cleanup_profile", "cleanup_reply", "cover", "captions", "max_chars", "max_len", "trims"]

register(Recipe("longform-slices", speech_stages(), expand_longform,
                "one long recording + a job list of ranges -> cleaned, captioned vertical slices per platform",
                label="Long recording -> vertical slices",
                inputs=[dict(key="inputs.source", label="Long recording", kind="file", required=True, accept=VIDEO_ACCEPT,
                             help="lecture / webinar / podcast video (read-only, never copied)"),
                        IN_SEGMENTS, IN_TRANSCRIPT],
                row_keys=COMMON_ROW))
register(Recipe("talkinghead-clips", speech_stages(), expand_clips,
                "a folder of raw 口播 clips -> one cleaned, captioned short per clip per platform",
                label="口播 clips -> shorts",
                inputs=[dict(key="inputs.folder", label="Clip folder", kind="dir", required=True,
                             help="a folder of raw talking-head clips (or inputs.clips: a file list)"),
                        dict(key="inputs.glob", label="File pattern", kind="text", required=False,
                             help='e.g. "*.mp4,*.MOV"'),
                        dict(IN_SEGMENTS, required=False, help="optional per-clip rows (file, title, hook, skip ...)")],
                row_keys=COMMON_ROW + ["file", "skip"]))


from . import lfsplit  # noqa: E402,F401  (registers longform-split; it reuses the stages above)
from . import podcast  # noqa: E402,F401  (registers podcast-clips: workflows/call-clips per job)
from . import thfolder  # noqa: E402,F401  (registers talkinghead-folder: the talkinghead V pipeline per clip)
