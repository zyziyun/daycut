"""`intake plan` / `intake revise`: a natural-language request + materials -> an editable PLAN of sub-projects.

    plan = make_plan("把这节课切成 20 条竖屏", ["lesson.mp4"])          # dict (kind vstudio.intake.plan)
    plan = revise(plan, "只要小红书")

The model (``vstudio.llm`` task ``intake``; whatever the persona / client routes it to - the creator's own
Claude Code login when ``llm.default`` is ``claude-code``) proposes the sub-projects; the code then **validates
everything** against the recipe manifests (recipe ids, input keys / kinds / extensions, param JSON Schemas, item
keys), fills defaults (recipe < persona < client < materials < prompt), and adds what the model must not
make up: checkpoints that will need the creator, cost / time estimates, focus ranges clamped to the media. When no
model is routed, the call fails or returns nothing usable, the rule planner (``rules.py``: the SKILL.md phrase
table + material heuristics) produces the plan instead (``planner.fallback: true``).
"""
import copy
import json
import os
import re
import time

from vstudio import messages as MSG

from vstudio import llm as LLM
from vstudio.project import manifests as M

from . import estimate as EST
from . import inventory as I
from . import rules as R

PLAN_VERSION = 1
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "plan.schema.json")
TASK = "intake"
METHODS = ("per-file", "single", "planner", "focus", "episodes", "list")
FOCUS_FULL_ASR_MAX_S = 45 * 60          # transcribe a whole video at plan time only up to this length
TRANSCRIPT_CHARS = 60000
PLATFORM_ZH = {"xiaohongshu": "小红书", "douyin": "抖音", "tiktok": "TikTok", "youtube": "YouTube",
               "youtube-shorts": "YouTube Shorts", "bilibili": "B站", "wechat-channels": "视频号", "x": "X",
               "instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn", "threads": "Threads",
               "reddit": "Reddit", "pinterest": "Pinterest", "snapchat": "Snapchat", "kuaishou": "快手", "weibo": "微博",
               "zhihu": "知乎", "dailymotion": "Dailymotion", "kwai": "Kwai"}
ORIENT_ZH = {"full": "竖屏 9:16", "vertical": "竖屏 3:4", "horizontal": "横屏"}
ORIENT_EN = {"full": "9:16", "vertical": "3:4", "horizontal": "16:9"}
PLATFORM_EN = dict(PLATFORM_ZH, xiaohongshu="Xiaohongshu", douyin="Douyin", bilibili="Bilibili",
                   **{"wechat-channels": "WeChat Channels"}, kuaishou="Kuaishou", weibo="Weibo", zhihu="Zhihu")


class PlanError(ValueError):
    pass


# --------------------------------------------------------------------------- context (persona / client defaults)
def context(client=None):
    from vstudio.config import persona
    P = persona() or {}
    eff, cfg, cdir = {}, None, None
    if client:
        from vstudio.batch import clients as CL
        cdir = CL.resolve(client)
        eff = CL.effective(CL.load(cdir))
        cfg = {"llm": eff["llm"]} if eff.get("llm") else None
    plat_default = (P.get("platforms") or {}).get("default") or "xiaohongshu"
    from vstudio import platform as PF
    shapes = {k: v.get("default") for k, v in PF.PLATFORMS.items() if v.get("default") in ("full", "vertical")}
    shapes.update({k: v.get("post_shape") for k, v in (P.get("platforms") or {}).items()
                   if isinstance(v, dict) and v.get("post_shape") in ("full", "vertical", "horizontal")})
    return dict(client=cdir, client_name=eff.get("name") or None, llm_config=cfg, shapes=shapes,
                burned=str(((P.get("intake") or {}).get("burned_captions")) or "band"),
                platforms=[x.split(":")[0] for x in (eff.get("platforms") or [])] or [plat_default],
                speed=float((P.get("speed") or {}).get("body") or 1.1),
                cleanup=(eff.get("cleanup_profile") or (P.get("cleanup") or {}).get("profile") or "standard"),
                cleanup_client=bool(eff.get("cleanup_profile")),
                language=eff.get("language") or (P.get("creator") or {}).get("language") or "zh",
                style=eff.get("style") or "", source="client" if client else "persona")


# --------------------------------------------------------------------------- recipe catalog (for the model)
def catalog():
    out = []
    for rid, m in sorted(M.all_manifests().items()):
        if rid == "batch":                    # the batch board is an engine view, not a deliverable
            continue
        props = M.resolved_params(m)           # format defaults (speed, cleanup ...) as the creator gets them
        params = {}
        for k, v in props.items():
            d = {x: v[x] for x in ("type", "enum", "default", "minimum", "maximum") if x in v}
            d["zh"] = v.get("x-zh") or v.get("title")
            if v.get("x-scope") == "item":
                d["per_item"] = True
            params[k] = d
        out.append(dict(id=rid, label=m["labels"]["zh"], what=(m.get("description") or {}).get("zh"),
                        category=m.get("category"),
                        inputs=[dict(key=i["key"], kind=i["kind"], required=bool(i.get("required")),
                                     multiple=bool(i.get("multiple")), scope=i.get("scope"),
                                     accept=i.get("accept")) for i in m["inputs"]],
                        items=dict(sources=m["items"].get("sources"), from_input=m["items"].get("from_input"),
                                   planner=bool(m["items"].get("planner")), per_item=m["items"].get("per_item")),
                        params=params, platforms=m["outputs"].get("platforms"),
                        checkpoints=[c["id"] for c in m["checkpoints"]]))
    return out


PHRASE_TABLE = "\n".join(f"- {rid}: {', '.join(ph)}" for rid, ph, _ in R.PHRASES)

SYSTEM = """You are the intake planner of video-studio, a video-editing toolkit for a Chinese creator (小红书 / 抖音 /
YouTube / B站). The creator described what she wants in natural language and dropped some materials. Turn that into
a PLAN of one or more sub-projects, each run by exactly one RECIPE from the catalog (never invent a recipe, an
input key or a param; mixing recipes across sub-projects is fine, e.g. a course recording -> longform slices + an
explainer series from the PDF + 口播 scripts from the notes).

Rules:
- Use only the recipe ids, input keys and param names in the catalog. Material ids (f1, f2, g1 ...) refer to the
  materials list; a group id (g1) means all files of that group.
- Only set params the request or the materials justify; everything else keeps its recipe / persona default.
- Items (what becomes one output video): method per-file (one item per input file), single, planner (the recipe's
  segment planner picks N ranges of a long recording at run time), focus (the creator named WHICH content to cut out:
  give rows with exact "range": [start_s, end_s] when a transcript is provided, else describe the focus), episodes
  (N episodes), list (one row per topic / script).
- A finished edit (burned-in captions, "final" export) cut into shorter pieces: talkinghead layout "band" (the old
  burned captions are cropped off, the picture sits in a band, NEW captions go below it: captions=true,
  crop_bottom ~0.28), gentle cleanup, speed 1.0 unless asked. Only when the creator says to keep the old captions:
  captions=false.
- Ask a question ONLY when the answer can't be defaulted and changes the result (e.g. whose face to hide). Never ask
  about things a checkpoint already covers (segment approval, filler cuts, cover pick, publish review).
- Platforms: use the ids in the recipe's "platforms" list ("xiaohongshu:full" = 9:16, "xiaohongshu:vertical" = 3:4).
  Give a bare platform name ("xiaohongshu") unless the creator named a shape: the creator's persona picks it.
- summary_zh: ONE short paragraph for the creator, in the language of her request (Chinese for a Chinese request,
  English for an English one): what will be made from what, key settings, what she will be asked to confirm.
  No markdown.

Phrase table (what the creator typically says -> recipe):
{phrases}

Return ONE JSON object:
{{"projects": [{{"recipe": "<catalog id>", "name": "<short name>", "why": "<zh, one line>",
   "materials": ["f1"], "inputs": {{"<input key>": ["f1"] or "<text>"}},
   "items": {{"method": "per-file|single|planner|focus|episodes|list", "count": <int or null>, "focus": "<zh or null>",
             "rows": [{{"id": "<slug>", "title": "<zh>", "range": [<start_s>, <end_s>], "inputs": {{}}, "params": {{}},
                       "why": "<zh>"}}]}},
   "params": {{"<param>": <value>}}}}],
 "questions": [{{"project": <index>, "text": "<zh>", "options": ["..."], "default": "..."}}],
 "risks": ["<zh>"],
 "summary_zh": "<zh paragraph>"}}"""


def _prompt_doc(prompt, analysis, ctx, transcripts, current=None, instruction=None):
    comp = I.compact(analysis)
    doc = dict(request=prompt, materials=comp,
               defaults=dict(platforms=ctx["platforms"], cleanup=ctx["cleanup"],      # speed: each recipe's own
                             language=ctx["language"], client=ctx.get("client_name"), style=ctx.get("style") or None),
               catalog=catalog())
    parts = []
    if current is not None:
        parts.append("CURRENT PLAN (edit it; keep what the instruction does not change):\n" +
                     json.dumps(dict(projects=[_for_model(p) for p in current["projects"]],
                                     questions=current.get("questions"), risks=current.get("risks")),
                                ensure_ascii=False))
        parts.append(f"FOLLOW-UP INSTRUCTION: {instruction}")
    parts.insert(0, json.dumps(doc, ensure_ascii=False))
    for fid, tr in transcripts.items():
        lines = [f"[{_ts(s['t'])}-{_ts(s['te'])}] {s['text']}" for s in tr["sentences"]]
        body, size = [], 0
        for ln in lines:
            size += len(ln) + 1
            if size > TRANSCRIPT_CHARS:
                body.append("... (truncated)")
                break
            body.append(ln)
        parts.append(f"TRANSCRIPT of {fid} (times in seconds as m:ss; give ranges in seconds):\n" + "\n".join(body))
    return "\n\n".join(parts)


def _ts(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def _for_model(p):
    return {k: p.get(k) for k in ("recipe", "name", "why", "materials", "inputs", "items", "params")}


# --------------------------------------------------------------------------- normalisation / validation
def _strip_x(sch):
    return {k: v for k, v in sch.items() if not k.startswith("x-") and k not in ("title",)}


def _valid(value, sch):
    try:
        import jsonschema
    except ImportError:
        return True
    try:
        jsonschema.validate(value, _strip_x(sch))
        return True
    except jsonschema.ValidationError:
        return False


def norm_platform(m, name, orientation=None, shapes=None):
    """'xiaohongshu' / '小红书' / 'xiaohongshu:full' -> the recipe's platform id (orientation preference), or None.
    ``shapes``: the persona's per-platform default shape ({"xiaohongshu": "vertical"} = 3:4) for a bare name."""
    outs = m["outputs"].get("platforms") or []
    if not name:
        return None
    s = str(name).strip()
    for w, p in R.PLATFORM_WORDS:
        if s.lower() == w:
            s = p
    if s in outs:
        return s
    base = s.split(":")[0]
    cands = [o for o in outs if o.split(":")[0] == base]
    if base == "youtube" and orientation == "vertical" and "youtube-shorts" in outs:
        return "youtube-shorts"
    if not cands:
        if base == "youtube-shorts" and "youtube" in outs:
            return "youtube"
        return None
    if orientation == "horizontal":
        for o in cands:
            if o.endswith(":horizontal") or ":" not in o:
                return o
    if orientation == "vertical":
        pref = (shapes or {}).get(base)
        if pref in ("full", "vertical") and f"{base}:{pref}" in cands:
            return f"{base}:{pref}"
        for o in cands:
            if o.endswith(":full") or o.endswith(":vertical"):
                return o
    return cands[0]


def _resolve_refs(vals, analysis):
    """['f1', 'g2', '/abs/x.mp4'] -> [abs paths]"""
    byid = {f["id"]: f for f in analysis["files"]}
    gr = {g["id"]: g for g in analysis.get("groups") or []}
    out = []
    for v in vals if isinstance(vals, list) else [vals]:
        if not isinstance(v, str):
            continue
        if v in byid:
            out.append(byid[v]["path"])
        elif v in gr:
            out += [byid[x]["path"] for x in gr[v]["files"] if x in byid]
        elif os.path.isabs(v) and os.path.exists(v):
            out.append(v)
    return list(dict.fromkeys(out))


def _accepts(inp, path):
    acc = [a.lower() for a in inp.get("accept") or []]
    return not acc or os.path.splitext(path)[1].lower() in acc


def _material_ids(paths, analysis):
    byp = {f["path"]: f["id"] for f in analysis["files"]}
    return [byp[p] for p in paths if p in byp]


def _duration_of(path, analysis):
    for f in analysis["files"]:
        if f["path"] == path:
            return f.get("duration")
    return None


def normalize_project(raw, idx, analysis, intent, ctx, warn):
    rid = raw.get("recipe")
    try:
        m = M.get(rid)
    except KeyError:
        warn.append(MSG.cs("intake.warning.unknown-recipe", "en", recipe=repr(rid)))
        return None
    if rid == "batch":
        warn.append(MSG.cs("intake.warning.batch-recipe", "en"))
        return None
    props = m["params"]["properties"]
    known_inputs = {i["key"]: i for i in m["inputs"]}
    p = dict(id=f"p{idx + 1}", recipe=rid, recipe_label=m["labels"]["zh"], name=_name(raw.get("name"), rid, idx),
             why=str(raw.get("why") or "")[:200])
    # ---- inputs
    ins = {}
    for k, v in (raw.get("inputs") or {}).items():
        if k not in known_inputs:
            warn.append(MSG.cs("intake.warning.unknown-input", "en", project=p["id"], recipe=rid, key=repr(k)))
            continue
        inp = known_inputs[k]
        if inp["kind"] in ("text", "url-free"):
            ins[k] = v if isinstance(v, str) else " ".join(map(str, v)) if isinstance(v, list) else str(v)
            continue
        paths = _resolve_refs(v, analysis)
        bad = [x for x in paths if not _accepts(inp, x)]
        if bad:
            warn.append(MSG.cs("intake.warning.input-not-accepted", "en", project=p["id"], recipe=rid, key=k,
                                  files=", ".join(os.path.basename(b) for b in bad)))
        paths = [x for x in paths if x not in bad]
        if not paths:
            continue
        ins[k] = paths if inp.get("multiple") else paths[0]
        if not inp.get("multiple") and len(paths) > 1:
            warn.append(MSG.cs("intake.warning.input-single", "en", project=p["id"], recipe=rid, key=k,
                                  file=os.path.basename(paths[0])))
    # ---- items
    it = dict(raw.get("items") or {})
    method = it.get("method") if it.get("method") in METHODS else None
    fi = m["items"].get("from_input")
    if not method:
        method = "planner" if m["items"].get("planner") else "per-file" if fi and fi in ins else "single"
    if method == "per-file" and not (fi and fi in ins):
        method = "single"
    if method == "planner" and not m["items"].get("planner"):
        method = "per-file" if fi and fi in ins else "single"
    items = dict(method=method)
    try:
        if it.get("count") is not None:
            items["count"] = max(1, int(it["count"]))
    except (TypeError, ValueError):
        pass
    if it.get("focus"):
        items["focus"] = str(it["focus"])[:300]
    if it.get("max_s"):
        items["max_s"] = it["max_s"]
    allowed_item = set(m["items"].get("per_item") or []) | set(props) | {"range"}
    rows = []
    src_path = _first_path(ins.get(fi) if fi else None) or _first_path(ins.get("source"))
    src_dur = _duration_of(src_path, analysis) if src_path else None
    for k, r in enumerate(it.get("rows") or []):
        if not isinstance(r, dict):
            continue
        rp = {kk: vv for kk, vv in (r.get("params") or {}).items() if kk in allowed_item}
        for kk in ("title", "hook", "notes", "tags", "chapter", "body"):
            if r.get(kk) and kk in allowed_item:
                rp.setdefault(kk, r[kk])
        rng = r.get("range") or rp.get("range") or ([r["start"], r["end"]] if "start" in r and "end" in r else None)
        rp.pop("range", None)
        if rng:
            try:
                a, b = float(rng[0]), float(rng[1])
            except (TypeError, ValueError, IndexError):
                a = b = None
            if a is not None:
                if src_dur:
                    a, b = max(0.0, min(a, src_dur)), max(0.0, min(b, src_dur))
                if b - a >= 3:
                    rp["range"] = [round(a, 2), round(b, 2)]
                else:
                    warn.append(MSG.cs("intake.warning.range-dropped", "en", project=p["id"], row=k + 1, range=rng))
                    continue
        rins = {}
        for kk, vv in (r.get("inputs") or {}).items():
            if kk not in known_inputs:
                continue
            if known_inputs[kk]["kind"] in ("text", "url-free"):
                rins[kk] = str(vv)
            else:
                pp = _resolve_refs(vv, analysis)
                if pp:
                    rins[kk] = pp[0] if not known_inputs[kk].get("multiple") or len(pp) == 1 else pp
        if method == "focus" and fi and fi in ins and fi not in rins and rp.get("range"):
            rins[fi] = _first_path(ins[fi])
        row = dict(id=_slug(r.get("id") or f"{k + 1:02d}"), inputs=rins, params=rp)
        if r.get("why"):
            row["why"] = str(r["why"])[:160]
        if r.get("notes") and isinstance(r["notes"], list):
            row["notes"] = r["notes"]
        rows.append(row)
    if rows:
        items["rows"] = rows
        items["count"] = len(rows)
    if method == "focus" and not rows:
        items["unresolved"] = True              # apply finds the ranges (full transcript + the focus)
    # ---- params: recipe default < persona / client < materials (raw rules) < model < prompt
    params, sources = {}, {}
    orient = None
    raw_params = dict(raw.get("params") or {})
    orient = raw_params.pop("_orientation", None) or intent.get("orientation")
    for k, v in raw_params.items():
        if k not in props:
            warn.append(MSG.cs("intake.warning.unknown-param", "en", project=p["id"], recipe=rid, key=repr(k)))
            continue
        params[k], sources[k] = v, "planner"
    _apply_ctx_defaults(m, params, sources, ctx, ins, analysis)
    _apply_intent(m, params, sources, intent, items)
    # platforms -> the recipe's ids
    if "platforms" in props:
        plats = params.get("platforms")
        if plats is None:
            plats, sources["platforms"] = list(ctx["platforms"]), ctx["source"]
        fixed = []
        shapes = dict(ctx.get("shapes") or {})
        if intent.get("shape"):                          # "9:16" / "3:4" in the request: every platform
            shapes = {k: intent["shape"] for k in set(shapes) | {"xiaohongshu"}}
        for x in plats if isinstance(plats, list) else [plats]:
            if sources.get("platforms") == "planner" and isinstance(x, str) and ":" in x and not intent.get("shape"):
                x = x.split(":")[0]                      # the model's shape guess: the persona decides
            n = norm_platform(m, x, orient or _orientation_hint(rid, ins, analysis), shapes)
            if n and n not in fixed:
                fixed.append(n)
            elif not n:
                warn.append(MSG.cs("intake.warning.platform-unsupported", "en", project=p["id"], recipe=rid,
                                      platform=repr(x)))
        if not fixed:
            fixed = [d for d in (props["platforms"].get("default") or [])][:1] or (m["outputs"].get("platforms") or [])[:1]
            sources["platforms"] = "recipe"
        params["platforms"] = fixed
    if items.get("count") and "count" in props and method in ("planner", "focus"):
        params.setdefault("count", items["count"])
        sources.setdefault("count", "prompt" if intent.get("count") else "planner")
    for k in list(params):
        if not _valid(params[k], props[k]):
            warn.append(MSG.cs("intake.warning.param-invalid", "en", project=p["id"], recipe=rid, key=k,
                              value=repr(params[k])))
            params.pop(k)
            sources.pop(k, None)
    if "min_s" in params and "max_s" in params and params["min_s"] > params["max_s"]:
        params["min_s"] = max(5, params["max_s"] // 2)
    # required inputs
    for inp in m["inputs"]:
        if inp["required"] and inp["key"] not in ins and not (rows and all(inp["key"] in r["inputs"] for r in rows)):
            fill = _auto_fill(inp, raw, analysis)
            if fill:
                ins[inp["key"]] = fill if inp.get("multiple") else fill[0]
            else:
                warn.append(MSG.cs("intake.warning.required-input-missing", "en", project=p["id"], recipe=rid,
                                      key=inp["key"]))
                return None
    if method == "per-file":
        items["count"] = len(ins.get(fi) or []) if isinstance(ins.get(fi), list) else 1
    if method == "single":
        items["count"] = 1
    p["inputs"] = ins
    mats = [x for x in (raw.get("materials") or []) if any(f["id"] == x for f in analysis["files"])]
    for v in ins.values():
        mats += _material_ids(v if isinstance(v, list) else [v], analysis)
    p["materials"] = list(dict.fromkeys(mats))
    p["items"] = items
    p["params"] = params
    p["param_sources"] = sources
    return p


def _first_path(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _orientation_hint(rid, ins, analysis):
    if rid in ("talkinghead", "longform-to-short", "call-clips", "vlog", "photo-story", "ai-video", "lesson-clips",
               "interview-qa"):
        return "vertical"
    return None


def _auto_fill(inp, raw, analysis):
    kind = {"video": "video", "photos": "image", "audio": "audio"}.get(inp["kind"])
    if not kind:
        return []
    mats = _resolve_refs(raw.get("materials") or [], analysis)
    fs = [x for x in mats if I.kind_of(x) == kind and _accepts(inp, x)]
    if not fs:
        fs = [f["path"] for f in analysis["files"] if f["kind"] == kind and _accepts(inp, f["path"])]
        if len(fs) > 1 and not inp.get("multiple"):
            fs = sorted(fs, key=lambda x: -(_duration_of(x, analysis) or 0))
    return fs


def _src_file(ins, analysis):
    for v in ins.values():
        for x in (v if isinstance(v, list) else [v]):
            for f in analysis["files"]:
                if f["path"] == x:
                    return f
    return None


BAND_CROP = {"lower": 0.28}      # source height fraction cropped off per burned-caption band (inventory cap_low .72-.96)


def _burned_defaults(src, ctx):
    """A finished edit with burned-in captions, cut again: crop the old captions off and lay the picture out in a
    band with NEW captions below (talkinghead layout "band"), unless the persona says ``intake.burned_captions:
    keep`` (old captions stay, no new ones) or the old captions sit mid-frame (cannot be cropped cleanly)."""
    if not src or not src.get("burned_captions"):
        return dict(captions=False) if src and I.material_role(src) == "finished-edit" else {}
    crop = BAND_CROP.get(src.get("caption_band") or "lower")
    if ctx.get("burned") == "keep" or crop is None:
        return dict(captions=False)
    return dict(layout="band", crop_bottom=crop, captions=True)


def _apply_ctx_defaults(m, params, sources, ctx, ins, analysis):
    props = m["params"]["properties"]
    src = _src_file(ins, analysis)
    finished = bool(src and (src.get("burned_captions") or I.material_role(src) == "finished-edit"))
    fmt = M.param_defaults(m) if m.get("format") else {}
    from_format = {k for k, v in props.items() if "x-format" in v}     # the format decides these (vstudio.formats)
    if "speed" in props and "speed" not in params and m["id"] in ("talkinghead",) and not finished:
        if "speed" in from_format:
            params["speed"], sources["speed"] = fmt["speed"], "format"
        else:
            params["speed"], sources["speed"] = ctx["speed"], ctx["source"]
    if "cleanup_profile" in props and "cleanup_profile" not in params:
        if finished:
            params["cleanup_profile"], sources["cleanup_profile"] = "gentle", "material"
        elif "cleanup_profile" in from_format and not ctx.get("cleanup_client"):
            params["cleanup_profile"], sources["cleanup_profile"] = fmt["cleanup_profile"], "format"
        elif ctx["cleanup"] in ("gentle", "standard", "tight"):
            params["cleanup_profile"], sources["cleanup_profile"] = ctx["cleanup"], ctx["source"]
    if finished and m["id"] == "talkinghead":
        bd = _burned_defaults(src, ctx)
        for k, v in bd.items():
            if k in props and k not in params:
                params[k], sources[k] = v, "material"
        if params.get("layout") == "band" and params.get("captions") is False and sources.get("captions") != "prompt":
            params["captions"], sources["captions"] = True, "material"   # band = old captions cropped: new ones
        if "speed" not in params:
            params["speed"], sources["speed"] = 1.0, "material"
    if "language" in props and "language" not in params:
        lang = (src or {}).get("language") or ctx["language"]
        if lang in (props["language"].get("enum") or [lang]):
            params["language"], sources["language"] = lang, "material" if (src or {}).get("language") else ctx["source"]
    if m["id"] == "longform-to-short" and "layout_mode" not in params and src:
        params["layout_mode"], sources["layout_mode"] = ("split" if src.get("screen_share") else "reframe"), "material"


def _apply_intent(m, params, sources, intent, items):
    """What the creator literally said wins over everything else."""
    props = m["params"]["properties"]
    if intent.get("platforms") and "platforms" in props:
        params["platforms"], sources["platforms"] = list(intent["platforms"]), "prompt"
    if intent.get("speed") and "speed" in props:
        params["speed"], sources["speed"] = intent["speed"], "prompt"
    if intent.get("language") and "language" in props:
        params["language"], sources["language"] = intent["language"], "prompt"
    if intent.get("cleanup") and "cleanup_profile" in props:
        params["cleanup_profile"], sources["cleanup_profile"] = intent["cleanup"], "prompt"
    if intent.get("max_s"):
        if "max_s" in props:
            params["max_s"], sources["max_s"] = intent["max_s"], "prompt"
            if params.get("min_s", props.get("min_s", {}).get("default", 0)) > intent["max_s"]:
                params["min_s"], sources["min_s"] = max(5, intent["max_s"] // 2), "prompt"
        items["max_s"] = intent["max_s"]
    if intent.get("style") and m["id"] == "vlog":
        params["style"], sources["style"] = intent["style"], "prompt"
    if intent.get("mask") is not None and m["id"] == "call-clips":
        params["no_mask"], sources["no_mask"] = (not intent["mask"]), "prompt"
    if intent.get("mask") is not None and "mask" in props and m["id"] in ("lesson-clips", "interview-qa"):
        params["mask"], sources["mask"] = ("sticker" if intent["mask"] else "off"), "prompt"
    if intent.get("subtitles") and "subtitles" in props:
        params["subtitles"], sources["subtitles"] = intent["subtitles"], "prompt"
        if intent.get("subtitle_lang") and "subtitle_lang" in props:
            params["subtitle_lang"], sources["subtitle_lang"] = intent["subtitle_lang"], "prompt"
    if intent.get("hook") is not None and "hook_default" in props:
        params["hook_default"], sources["hook_default"] = (0 if intent["hook"] else -1), "prompt"
    if intent.get("orientation") and m["id"] == "promo-recut":
        params["orientation"], sources["orientation"] = intent["orientation"], "prompt"
    if intent.get("keep_captions") and "captions" in props:
        params["captions"], sources["captions"] = False, "prompt"
        if sources.get("layout") == "material":                       # keep the old captions: no band crop
            params.pop("layout", None)
            params.pop("crop_bottom", None)
            sources.pop("layout", None)
            sources.pop("crop_bottom", None)
    if intent.get("narration") is False and m["id"] == "photo-story":
        params["mode"], sources["mode"] = "music", "prompt"


def _name(n, rid, idx):
    n = str(n or "").strip()
    return (n or f"{rid}-{idx + 1}")[:40]


def _slug(s):
    from vstudio.batch.util import slug
    return slug(str(s))[:40] or "item"


# --------------------------------------------------------------------------- checkpoints / estimates / summary
def checkpoints_for(p, auto=()):
    m = M.get(p["recipe"])
    out = []
    for c in m["checkpoints"]:
        a = c.get("auto", "never")
        needs = c["kind"] in ("budget-approval", "consent") or a == "never" or c["id"] not in auto
        if a == "skip-if-empty":
            needs = False
        out.append(dict(id=c["id"], kind=c["kind"], label=c["labels"]["zh"], scope=c.get("scope", "item"),
                        needs_you=bool(needs), auto=a))
    return out


def _out_seconds(p, analysis):
    m = M.get(p["recipe"])
    items, params = p["items"], p["params"]
    rows = items.get("rows") or []
    speed = float(params.get("speed") or 1.0)
    src = sum((_duration_of(x, analysis) or 0) for v in p["inputs"].values()
              for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and os.path.isabs(x)
              and I.kind_of(x) in ("video", "audio"))
    ranged = [r["params"]["range"] for r in rows if (r.get("params") or {}).get("range")]
    if ranged:
        out = sum(b - a for a, b in ranged) / speed
    elif items["method"] in ("planner", "focus"):
        mn = params.get("min_s") or (m["params"]["properties"].get("min_s") or {}).get("default") or 45
        mx = params.get("max_s") or (m["params"]["properties"].get("max_s") or {}).get("default") or 120
        n = items.get("count") or params.get("count") or (m["params"]["properties"].get("count") or {}).get("default") or 5
        out = n * (mn + mx) / 2 / speed
    elif items["method"] == "per-file":
        out = src * 0.85 / speed
    else:
        d = EST.DEFAULT_OUT_S.get(p["recipe"], 60)
        if isinstance(d, dict):
            d = d.get(params.get("mode") or "long", 120)
        out = d * (items.get("count") or 1)
        if p["recipe"] == "polish":
            out = src
    return src, out


def enrich(p, analysis, ctx, auto=()):
    from vstudio.platform import ordered
    m = M.get(p["recipe"])
    if p["params"].get("platforms"):           # stored in registry order (international first), never request order
        p["params"]["platforms"] = ordered(p["params"]["platforms"])
    p["checkpoints"] = checkpoints_for(p, auto)
    p["auto"] = list(auto)
    src, out = _out_seconds(p, analysis)
    n_items = p["items"].get("count") or 1
    p["estimate"] = EST.project(p, src, out, n_items, len(p["params"].get("platforms") or [None]), ctx.get("llm_config"))
    p["outputs"] = dict(platforms=p["params"].get("platforms") or [], videos=n_items * max(1, len(
        p["params"].get("platforms") or [None])), workflow_md=m["agent"]["workflow_md"])
    return p


def _plat_zh(ps):
    out = []
    for x in ps or []:
        base, _, o = x.partition(":")
        out.append(PLATFORM_ZH.get(base, base) + (f"（{ORIENT_ZH.get(o, o)}）" if o else ""))
    return "、".join(out)


def template_summary(plan):
    """The template summary in the request's language (an English request gets an English paragraph)."""
    from vstudio.publish import detect_lang
    return summary_en(plan) if detect_lang(plan.get("prompt") or "") == "en" else summary_zh(plan)


def summary_en(plan):
    """English template summary (same content as summary_zh)."""
    ps = plan["projects"]
    if not ps:
        return "Could not put together a project from these files and this request: " + "; ".join(
            str(r) for r in (plan.get("risks") or ["add material or say what to make"]))
    parts = []
    for k, p in enumerate(ps):
        it = p["items"]
        n = it.get("count")
        what = {"focus": f"cut out {n or 'the'} part(s) you described", "planner": f"pick {n or 'the best'} segments",
                "per-file": f"one video per file ({n})", "single": "make 1 video", "episodes": f"make {n} episodes",
                "list": f"make {n} videos"}[it["method"]]
        mats = ", ".join(os.path.basename(_first_path(v)) for v in p["inputs"].values()
                         if isinstance(_first_path(v), str) and os.path.isabs(_first_path(v)))[:60]
        settings = []
        pr = p["params"]
        if pr.get("platforms"):
            plats = []
            from vstudio.platform import ordered
            for x in ordered(pr["platforms"]):          # international first, Chinese after
                base, _, o = x.partition(":")
                plats.append(PLATFORM_EN.get(base, base) + (f" ({ORIENT_EN.get(o, o)})" if o else ""))
            settings.append("for " + ", ".join(plats))
        if "speed" in pr:
            settings.append(f"{pr['speed']}x")
        if pr.get("cleanup_profile"):
            settings.append({"gentle": "light pause cleanup", "standard": "standard filler cleanup",
                             "tight": "strict filler cleanup", "off": "no cleanup"}[pr["cleanup_profile"]])
        label = M.get(p["recipe"])["labels"].get("en") or p["recipe"]
        parts.append(f"({k + 1}) {label}: {what}" + (f" from {mats}" if mats else "") +
                     (f" ({', '.join(settings)})" if settings else ""))
    labels = {c["id"]: c for p in ps for c in M.get(p["recipe"])["checkpoints"]}
    need = sorted({(labels.get(c["id"]) or {}).get("labels", {}).get("en") or c["label"] for p in ps
                   for c in p["checkpoints"] if c["needs_you"]})
    est = plan.get("estimate") or {}
    s = f"I'll make {len(ps)} project{'s' if len(ps) > 1 else ''}: " + "; ".join(parts) + "."
    if need:
        s += f" You'll confirm: {', '.join(need)}."
    s += f" One pilot clip first; the whole run takes about {max(1, round(est.get('wall_min', 0)))} min on this Mac"
    s += f", about ${est.get('api_usd', 0):.2f} in API costs" if est.get("api_usd") else ", no API costs"
    return s + "."


def summary_zh(plan):
    """Template summary (used when the model gave none, and after every rule revision)."""
    ps = plan["projects"]
    if not ps:
        return "没能从这些素材和描述里拼出可执行的项目：" + "；".join(plan.get("risks") or ["请补充素材或说明要做什么"])
    parts = []
    for k, p in enumerate(ps):
        it = p["items"]
        n = it.get("count") or "若干"
        what = {"focus": f"按你说的内容截出 {n} 段", "planner": f"自动选出 {n} 段", "per-file": f"{n} 条素材各出一条",
                "single": "做成 1 条", "episodes": f"做 {n} 集", "list": f"做 {n} 条"}[it["method"]]
        mats = "、".join(os.path.basename(_first_path(v)) for v in p["inputs"].values()
                        if isinstance(_first_path(v), str) and os.path.isabs(_first_path(v)))[:60]
        settings = []
        pr = p["params"]
        if pr.get("platforms"):
            settings.append(f"发{_plat_zh(pr['platforms'])}")
        if "speed" in pr:
            settings.append(f"{pr['speed']}×")
        if pr.get("layout") == "band":
            settings.append("裁掉旧字幕、上下条带版式、重新加字幕")
        elif pr.get("captions") is False:
            settings.append("保留原字幕不再叠加")
        if pr.get("cleanup_profile"):
            settings.append({"gentle": "轻度去气口", "standard": "标准去气口", "tight": "严格去气口", "off": "不去气口"}[
                pr["cleanup_profile"]])
        if it.get("focus"):
            settings.append(f"内容：{it['focus']}")
        parts.append(f"{'①②③④⑤⑥⑦⑧⑨'[k] if k < 9 else k + 1} {p['recipe_label']}：{('用 ' + mats + ' ') if mats else ''}{what}"
                     f"（{'，'.join(settings)}）")
    need = sorted({c["label"] for p in ps for c in p["checkpoints"] if c["needs_you"]})
    est = plan.get("estimate") or {}
    s = f"我会做 {len(ps)} 个项目：" + "；".join(parts) + "。"
    if need:
        s += f"需要你确认：{'、'.join(need)}。"
    s += f"先试做 1 条（pilot）给你看，全部跑完本机约 {max(1, round(est.get('wall_min', 0)))} 分钟"
    s += f"，API 费用约 ${est.get('api_usd', 0):.2f}" if est.get("api_usd") else "，不产生 API 费用"
    if est.get("credits"):
        s += "，AI 视频积分在预算检查点报价"
    return s + "。"


# --------------------------------------------------------------------------- the model call
# s per CLI provider attempt (claude-code / codex), then the next one in the chain: the same 90 s per-attempt policy as
# Create (VSTUDIO_CREATE_AI_TIMEOUT) and the publish copy calls
DEFAULT_CLI_TIMEOUT = 90


def _call_model(prompt, analysis, ctx, transcripts, provider=None, model=None, current=None, instruction=None,
                call=None, timeout=None, on_event=None):
    route = LLM.route(TASK, provider, model, ctx.get("llm_config"))
    info = dict(provider=route.provider, model=route.model, route=route.source)
    if route.provider == "none" and call is None:
        info.update(fallback=True, reason="no model routed for task intake (rule planner)")
        return None, info
    I.emit(on_event, stage="model", provider=route.provider, model=route.model)
    system = SYSTEM.format(phrases=PHRASE_TABLE)
    body = _prompt_doc(prompt, analysis, ctx, transcripts, current, instruction)
    t0 = time.time()
    try:
        if call is not None:
            res = call(system, body)
        else:
            ct = timeout if timeout is not None else (None if os.environ.get("VSTUDIO_LLM_CLI_TIMEOUT")
                                                      else DEFAULT_CLI_TIMEOUT)
            res = LLM.complete(TASK, system, body, schema=True, provider=provider, model=model,
                               config=ctx.get("llm_config"), max_tokens=12000, timeout=600, cli_timeout=ct)
    except Exception as e:  # noqa: BLE001 - auth / network / CLI errors: fall back, say why
        info.update(fallback=True, reason=f"{type(e).__name__}: {str(e)[:240]}", seconds=round(time.time() - t0, 1),
                    failure=LLM.failure_code(e))
        if isinstance(e, LLM.LLMError):
            ei = LLM.error_info(e)
            info.update(attempts=ei["attempts"], tried=ei["tried"], codes=ei["codes"])
        return None, info
    info.update(model=res.get("model") or info["model"], cost_usd=res.get("cost_usd", 0.0),
                usage=res.get("usage"), seconds=round(time.time() - t0, 1), routed=route.provider,
                provider=res.get("provider") or info["provider"], provider_fallback=res.get("fallback"))
    js = res.get("json")
    if not isinstance(js, dict) or not isinstance(js.get("projects"), list):
        info.update(fallback=True, reason="the model returned no usable plan JSON")
        return None, info
    info["fallback"] = False
    return js, info


# --------------------------------------------------------------------------- focus at plan time
def _needs_transcript(intent, analysis):
    if not intent.get("extract"):
        return []
    out = []
    for f in analysis["files"]:
        if f["kind"] in ("video", "audio") and f.get("speech") is not False and (f.get("duration") or 0) <= \
                FOCUS_FULL_ASR_MAX_S and not f.get("transcript") and I.material_role(f) in (
                "talking-head", "finished-edit", "lecture", "call", "screen-recording", "podcast-audio", "voice"):
            out.append(f)
    return out[:3]


def _transcript_events(on_event):
    """The full-ASR pass re-reads files the first pass already reported: only its transcription is news (a file
    whose full analysis is cached is a transcript reused from that cache)."""
    if on_event is None:
        return None

    def ev(e):
        if e.get("stage") == "transcribe":
            on_event(e)
        elif e.get("stage") == "probe" and e.get("cached"):
            on_event(dict(e, stage="transcribe", cached="analysis"))
    return ev


def _upgrade_transcripts(analysis, files, language=None, echo=None, on_event=None):
    """Full ASR (cached) for the files the request selects content from; merged into the analysis."""
    paths = [f["path"] for f in files]
    if not paths:
        return analysis
    full = I.analyze(paths, asr="full", language=language, echo=echo, on_event=_transcript_events(on_event))
    byp = {f["path"]: f for f in full["files"]}
    for f in analysis["files"]:
        g = byp.get(f["path"])
        if g and g.get("transcript"):
            for k in ("transcript", "sentences", "speech_s", "chars_per_min", "speech", "speech_basis", "language"):
                if k in g:
                    f[k] = g[k]
            f["excerpt"] = g.get("excerpt") or f.get("excerpt")
    return analysis


def _transcripts(analysis):
    out = {}
    for f in analysis["files"]:
        tr = I.load_transcript(f)
        if tr and tr.get("sentences"):
            out[f["id"]] = tr
    return out


def resolve_focus(p, analysis, intent, warn):
    """A focus sub-project without rows + a transcript of its source -> rows from the rule matcher."""
    it = p["items"]
    if it["method"] != "focus" or it.get("rows"):
        return p
    m = M.get(p["recipe"])
    fi = m["items"].get("from_input") or "source"
    src = _first_path(p["inputs"].get(fi) or p["inputs"].get("source"))
    f = next((x for x in analysis["files"] if x["path"] == src), None)
    tr = I.load_transcript(f) if f else None
    if not tr:
        return p
    mx = p["params"].get("max_s") or it.get("max_s") or 150
    picks = R.focus_ranges(tr["sentences"], f.get("duration"), intent.get("focus") or
                           [dict(topic=it.get("focus") or "", terms=[it.get("focus") or ""], where=None)],
                           count=it.get("count"), min_s=min(20, mx / 2), max_s=mx)
    if not picks:
        warn.append(MSG.cs("intake.warning.focus-unmatched", "en", project=p["id"]))
        return p
    rows = []
    for k, x in enumerate(picks):
        params = dict(range=[x["start"], x["end"]], title=x["title"])
        rows.append(dict(id=f"s{k + 1:02d}", inputs={fi: src} if fi in [i["key"] for i in m["inputs"]] and
                         m["items"].get("from_input") else {}, params=params, why=f"{x['focus']}：{x['why']}"))
    it["rows"], it["count"] = rows, len(rows)
    it.pop("unresolved", None)
    return p


# --------------------------------------------------------------------------- public
def _plan_id(prompt):
    from vstudio.batch.util import slug
    s = re.sub(r"[^\w一-鿿]+", "-", prompt or "plan")[:16].strip("-")
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(s) or 'plan'}"


def make_plan(prompt, inputs=None, client=None, provider=None, model=None, analysis=None, asr="auto", auto=None,
              call=None, echo=None, language=None, timeout=None, on_event=None):
    """-> plan dict. ``call(system, prompt) -> {json, model, cost_usd}`` replaces the model (tests). ``on_event``:
    progress, one dict per step - the inventory's (scan / probe / listen / faces / transcribe, see ``inventory``),
    then {event: stage, stage: model, provider, model} for the AI call and {event: stage, stage: write}."""
    if analysis is None:
        if not inputs:
            raise PlanError("no inputs (files / folders) given")
        analysis = I.analyze(inputs, asr="off" if asr == "off" else "sample", language=language, echo=echo,
                             on_event=on_event)
    ctx = context(client)
    intent = R.parse_prompt(prompt)
    if asr != "off" and asr != "sample":
        need = _needs_transcript(intent, analysis) if asr == "auto" else [
            f for f in analysis["files"] if f["kind"] in ("video", "audio")]
        if need:
            analysis = _upgrade_transcripts(analysis, need, language, echo, on_event)
    transcripts = _transcripts(analysis) if intent.get("extract") else {}
    js, info = _call_model(prompt, analysis, ctx, transcripts, provider, model, call=call, timeout=timeout,
                           on_event=on_event)
    I.emit(on_event, stage="write")
    warn = []
    questions, risks, summary = [], [], None
    raw_projects = None
    if js is not None:
        raw_projects = js.get("projects") or []
        questions = [q for q in js.get("questions") or [] if isinstance(q, dict) and q.get("text")]
        risks = [str(r) for r in js.get("risks") or [] if r]
        summary = js.get("summary_zh") if isinstance(js.get("summary_zh"), str) else None
    projects = []
    if raw_projects:
        for k, rp in enumerate(raw_projects):
            if isinstance(rp, dict):
                p = normalize_project(rp, len(projects), analysis, intent, ctx, warn)
                if p:
                    projects.append(p)
        if not projects:
            info.update(fallback=True, reason="no sub-project of the model's plan passed validation")
            summary = None
    if not projects:
        rp, rq, rr = R.rule_projects(intent, analysis, ctx)
        for x in rp:
            p = normalize_project(x, len(projects), analysis, intent, ctx, warn)
            if p:
                projects.append(p)
        questions, risks = (questions or rq), (risks + [r for r in rr if r not in risks])
        info["fallback"] = True
        info.setdefault("reason", "rule planner")
    for p in projects:
        resolve_focus(p, analysis, intent, warn)
    if intent.get("unsupported_platforms"):
        risks.append(MSG.cs("intake.risk.unsupported-platform", platforms="、".join(intent["unsupported_platforms"])))
    auto_ids = list(auto or [])
    for p in projects:
        enrich(p, analysis, ctx, auto_ids)
    plan = dict(version=PLAN_VERSION, kind="vstudio.intake.plan", id=_plan_id(prompt), created=time.strftime(
        "%Y-%m-%dT%H:%M:%S"), prompt=prompt, revisions=[], client=ctx.get("client"),
        planner=info, analysis=dict(digest=analysis["digest"], inputs=analysis["inputs"], totals=analysis["totals"],
                                    asr=analysis.get("asr"), notes=analysis.get("notes") or []),
        materials=_materials(analysis), projects=projects,
        series=_series_for(projects, prompt), questions=_norm_questions(questions, projects), risks=risks,
        warnings=warn, run=dict(pilot=1, auto=auto_ids))
    plan["estimate"] = EST.total(projects)
    plan["summary_zh"] = summary if (summary and not info.get("fallback")) else template_summary(plan)
    errs = validate(plan)
    if errs:
        plan["warnings"] = warn + [MSG.Coded(f"schema: {e}", MSG.msg("intake.warning.schema", error=e)) for e in errs]
    return _messages(plan)


def _messages(plan):
    """code + params next to every engine text the desk shows (references/MESSAGES.md): risks_info,
    warnings_info, questions[].message, checkpoints[].label_info, planner.message, summary_info. The plain
    string lists stay as they were (older desks, the CLI)."""
    plan["risks_info"] = [MSG.info_of(r, "intake.risk") for r in plan.get("risks") or []]
    plan["warnings_info"] = [MSG.info_of(w, "intake.warning") for w in plan.get("warnings") or []]
    for q in plan.get("questions") or []:
        q["message"] = MSG.info_of(q.get("text_info") or q.get("text"), "intake.question")
        q.pop("text_info", None)
    for p in plan.get("projects") or []:
        for c in p.get("checkpoints") or []:
            c["label_info"] = MSG.checkpoint(c.get("kind"))["label"]
        p["recipe_info"] = MSG.recipe(M.get(p["recipe"]))["label"]
    pl = plan.get("planner") or {}
    if pl.get("fallback"):
        why = pl.get("reason") or "rule planner"
        if pl.get("failure"):                         # the model call failed (every provider tried: pl.attempts)
            pl["message"] = MSG.msg("intake-model-fallback", reason=pl["failure"], error=why, tried=pl.get("tried"))
        elif pl.get("provider") == "none":
            pl["message"] = MSG.msg("intake-no-model")
        else:
            pl["message"] = MSG.msg("intake-rule-plan", reason=why)
    plan["summary_info"] = MSG.coded("intake.summary" if pl.get("fallback") else "ai-summary",
                                     plan.get("summary_zh") or "")
    return plan


def _materials(analysis):
    out = []
    for f in analysis["files"]:
        if f["kind"] == "other":
            continue
        d = dict(id=f["id"], path=f["path"], kind=f["kind"], role=I.material_role(f), qhash=f.get("qhash"))
        for k in ("duration", "orientation", "speech", "burned_captions", "talking_head", "multi_person", "screen_share",
                  "shape", "title", "transcript"):
            if f.get(k) not in (None, "", []):
                d[k] = f[k]
        out.append(d)
    return out


def _series_for(projects, prompt):
    if len(projects) < 2:
        return None
    from vstudio.batch.util import slug
    s = re.sub(r"[^\w一-鿿]+", "-", prompt or "")[:20].strip("-")
    return dict(id=f"intake-{slug(s) or 'mix'}-{time.strftime('%m%d%H%M')}", name=(prompt or "")[:30])


def _norm_questions(qs, projects):
    out = []
    for k, q in enumerate(qs):
        pi = q.get("project")
        pid = projects[pi]["id"] if isinstance(pi, int) and 0 <= pi < len(projects) else (
            pi if isinstance(pi, str) and any(p["id"] == pi for p in projects) else None)
        out.append(dict(id=f"q{k + 1}", project=pid, text=str(q["text"])[:200], text_info=getattr(q["text"], "info", None),
                        options=[str(o) for o in (q.get("options") or [])][:6], default=q.get("default")))
    return out


def revise(plan, instruction, provider=None, model=None, call=None, client=None, echo=None, timeout=None,
           on_event=None):
    """Follow-up instruction -> updated plan (model first, rules as the fallback). The analysis is re-read from
    the cache (no media work unless the cache was cleared). ``on_event``: as ``make_plan``."""
    plan = copy.deepcopy(plan)
    analysis = I.analyze(plan["analysis"]["inputs"], asr=plan["analysis"].get("asr") or "sample", echo=echo,
                         on_event=on_event)
    if any(x.get("transcript") for x in plan.get("materials") or []):
        fs = [f for f in analysis["files"] if any(x["path"] == f["path"] and x.get("transcript")
                                                   for x in plan["materials"])]
        analysis = _upgrade_transcripts(analysis, fs, echo=echo, on_event=on_event)
    ctx = context(client or plan.get("client"))
    intent = R.parse_prompt(plan["prompt"] + "\n" + instruction)
    follow = R.parse_prompt(instruction)
    intent_now = dict(intent, platforms=follow["platforms"] or intent["platforms"])
    for k in ("count", "max_s", "speed", "language", "cleanup", "orientation", "style", "mask", "hook"):
        if follow.get(k) is not None:
            intent_now[k] = follow[k]
    transcripts = _transcripts(analysis) if intent.get("extract") else {}
    js, info = _call_model(plan["prompt"], analysis, ctx, transcripts, provider, model, current=plan,
                           instruction=instruction, call=call, timeout=timeout, on_event=on_event)
    I.emit(on_event, stage="write")
    warn, notes = [], []
    projects = []
    summary = None
    if js is not None:
        for rp in js.get("projects") or []:
            if isinstance(rp, dict):
                p = normalize_project(rp, len(projects), analysis, _only_explicit(follow, instruction), ctx, warn)
                if p:
                    projects.append(p)
        if js.get("projects") == [] and R.negations(instruction):
            projects = []
        elif not projects:
            js = None
    if js is None:
        raw, notes = R.revise_rules(plan, instruction)
        for x in raw:
            x = dict(x)
            pr = dict(x.get("params") or {})
            x["params"] = pr
            p = normalize_project(x, len(projects), analysis, _only_explicit(follow, instruction), ctx, warn)
            if p:
                p["name"] = x.get("name") or p["name"]
                projects.append(p)
        info["fallback"] = True
        if not notes:
            warn.append(MSG.cs("intake.warning.revise-not-understood", instruction=instruction))
    else:
        summary = js.get("summary_zh") if isinstance(js.get("summary_zh"), str) else None
        plan["questions"] = _norm_questions([q for q in js.get("questions") or [] if isinstance(q, dict) and
                                             q.get("text")], projects)
        plan["risks"] = [str(r) for r in js.get("risks") or [] if r] or plan.get("risks") or []
    for p in projects:
        resolve_focus(p, analysis, intent_now, warn)
        enrich(p, analysis, ctx, plan.get("run", {}).get("auto") or [])
    kept = {p["id"] for p in projects}
    plan["questions"] = [q for q in plan.get("questions") or [] if not q.get("project") or q["project"] in kept]
    plan["projects"] = projects
    plan["series"] = _series_for(projects, plan["prompt"]) if len(projects) > 1 else None
    plan["revisions"] = list(plan.get("revisions") or []) + [dict(prompt=instruction, at=time.strftime(
        "%Y-%m-%dT%H:%M:%S"), planner=info, changes=notes)]
    plan["planner"] = info
    plan["warnings"] = warn
    plan["estimate"] = EST.total(projects)
    plan["summary_zh"] = summary if (summary and not info.get("fallback")) else template_summary(plan)
    return _messages(plan)


def _only_explicit(follow, instruction=""):
    """For a revision only the follow-up's own explicit values override what the plan already has; platforms only
    when the follow-up restricts them ("只要小红书"), not when it adds one ("也发抖音": the model / rules merge)."""
    keep = {k: follow.get(k) for k in ("platforms", "speed", "language", "cleanup", "max_s", "style", "mask", "hook",
                                       "orientation", "narration")}
    keep["platforms"] = (follow.get("platforms") or []) if re.search(r"只(要|发|做|保留|留)", instruction or "") else []
    return dict(keep, count=follow.get("count"))


# --------------------------------------------------------------------------- schema
def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate(plan):
    """JSON Schema of the plan + every sub-project against its recipe manifest. -> [errors]."""
    errs = []
    try:
        import jsonschema
        v = jsonschema.Draft202012Validator(schema())
        errs += [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in v.iter_errors(plan)]
    except ImportError:
        pass
    for p in plan.get("projects") or []:
        try:
            m = M.get(p.get("recipe"))
        except KeyError:
            errs.append(f"{p.get('id')}: unknown recipe {p.get('recipe')!r}")
            continue
        props = m["params"]["properties"]
        for k, val in (p.get("params") or {}).items():
            if k not in props:
                errs.append(f"{p['id']}: unknown param {k}")
            elif not _valid(val, props[k]):
                errs.append(f"{p['id']}: param {k}={val!r} invalid")
        known = {i["key"] for i in m["inputs"]}
        for k in p.get("inputs") or {}:
            if k not in known:
                errs.append(f"{p['id']}: unknown input {k}")
        if (p.get("items") or {}).get("method") not in METHODS:
            errs.append(f"{p['id']}: items.method must be one of {METHODS}")
    return errs
