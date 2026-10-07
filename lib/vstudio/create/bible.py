"""Series planning: one sentence (+ a format) -> a series draft (bible + ideas), revise the bible in plain
language, more ideas. LLM first (ai.ask), rule fallback from the format when no model is set up.

    plan_series(prompt, fmt=None, budget=None, platforms=None, lang="en") -> draft (not saved)
    create_series(draft) -> sid       revise_bible(sid, instruction|patch) -> bible       more_ideas(sid, n)
"""
import re
import statistics

from . import ai, formats as F, store
from .i18n import CreateError

FORMAT_WORDS = [
    ("record", r"口播|record myself|record yourself|teleprompter|提词|录一?条|自己录"),
    ("interview", r"采访|街采|interview|street|q ?& ?a|问答|vox"),
    ("talk-show", r"脱口秀|talk.?show|stand.?up|单口"),
    ("series-ad", r"系列广告|series ads?|ad series|campaign"),
    ("product-spot", r"产品短片|product spot|\bspot\b|单条广告|卖点|product video"),
    ("sketch", r"情景|sketch|comedy|喜剧|小品|段子"),
    ("series-ad", r"广告|\bads?\b"),
]
CN = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": list(F.IDS)},
        "name": {"type": "string"},
        "engine": {"type": "string"},
        "cast": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": {"type": "string"}, "essence": {"type": "string"},
            "look": {"type": "string"}}, "required": ["id", "name", "essence", "look"]}},
        "always": {"type": "array", "items": {"type": "string"}},
        "never": {"type": "array", "items": {"type": "string"}},
        "ideas": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "logline": {"type": "string"}, "notes": {"type": "string"}},
            "required": ["title", "logline"]}},
    },
    "required": ["format", "name", "engine", "cast", "always", "never", "ideas"],
}

SYSTEM = ("You are the head writer of a short-video studio. You plan series of vertical short videos: series ads, "
          "product spots, interviews / street Q&A, talk-show bits and comedy sketches (never anime or micro-drama). "
          "Keep every episode producible cheaply: few locations, the same cast every episode, no text inside generated "
          "shots (text is added in the edit), no real brand names or real public figures. Write in {lang}.")


def _num(s):
    if s is None:
        return None
    return int(s) if s.isdigit() else CN.get(s)


def guess_format(prompt):
    t = str(prompt or "").lower()
    for fid, pat in FORMAT_WORDS:
        if re.search(pat, t, re.I):
            return fid
    return "series-ad"


def parse_prompt(prompt):
    t = str(prompt or "")
    out = {}
    m = re.search(r"(\d+|[一两二三四五六七八九十])\s*[- ]?(?:episodes?|eps?\b|集|期)", t, re.I)
    if m:
        out["episodes"] = _num(m.group(1))
    m = re.search(r"(\d{1,3})\s*(?:s\b|sec|seconds?|秒)", t, re.I)
    if m:
        out["length_s"] = int(m.group(1))
    langs = []
    if re.search(r"chinese|中文|中英|普通话|汉语", t, re.I):
        langs.append("zh")
    if re.search(r"english|英文|中英|英语", t, re.I):
        langs.append("en")
    if re.search(r"french|法语|法文|français", t, re.I):
        langs.append("fr")
    out["languages"] = langs
    out["cjk"] = bool(re.search(r"[一-鿿]", t))
    return out


def _clean_name(t):
    t = re.sub(r"^(please |i want |make |create |plan |给我的|帮我的|给我|帮我|我想做|我要做|我想|我要|做(一个|个)?)\s*", "", t,
               flags=re.I)
    t = re.sub(r"^(a |an |the )?\d+[- ]?(episodes?|eps?|part)\s*", "", t, flags=re.I)
    t = re.sub(r"^[\d一两二三四五六七八九十]+\s*(集|期|条)(的)?", "", t)
    words = r"series ads?|ad series|product spots?|spots?|interviews?|talk.?show bits?|talk.?shows?|comedy sketch(es)?|" \
            r"sketch(es)?|ads?|系列广告|产品短片|采访|街采|脱口秀(段子)?|情景段子|段子|广告"
    t = re.sub(rf"^((a |an )?({words})\s*(about|for|on|of)?\s*)+", "", t, flags=re.I).strip()
    t = re.sub(r"^(关于|讲讲|讲|给)\s*", "", t)
    if re.search(r"[一-鿿]", t) and "做" in t[1:]:
        t = t.split("做")[0]
    return t.strip()


def _name_from(prompt, fmt, lang):
    """A short series name from the request: no counts / lengths / format words, cut at a word boundary."""
    text = re.sub(r"\s+", " ", str(prompt or "")).strip(" .。")
    t = ""
    for clause in re.split(r"[,，;；。.!！?？]", text)[:3]:
        t = _clean_name(clause.strip())
        if t:
            break
    if not t:
        return F.label(fmt, lang)
    cjk = bool(re.search(r"[一-鿿]", t))
    limit = 16 if cjk else 36
    if len(t) > limit:
        t = t[:limit] if cjk else t[:limit].rsplit(" ", 1)[0]
    return t[:1].upper() + t[1:]


def idea_cny(fmt):
    if fmt["recipe"] != "ai-video":
        return 0
    return round(statistics.mean(fmt["length_s"]) * 0.95)


def rule_ideas(fmt, topic, n, start=1, lang="en"):
    zh = lang.startswith("zh")
    seeds_en = ["the first try", "it gets worse", "nobody reads the fine print", "the update nobody asked for",
                "the free trial", "the upgrade", "customer support", "the sequel"]
    seeds_zh = ["第一次尝试", "越来越糟", "没人看的小字", "没人要的更新", "免费试用", "升级版", "客服来了", "续集"]
    out = []
    for i in range(n):
        k = (start - 1 + i) % len(seeds_en)
        title = seeds_zh[k] if zh else seeds_en[k].capitalize()
        out.append(dict(title=title, logline=(f"{topic}：{title}。" if zh else f"{topic}: {seeds_en[k]}."),
                        notes=""))
    return out


def rules_draft(prompt, fmt, lang, info):
    zh = lang.startswith("zh")
    topic = _name_from(prompt, fmt, lang)
    cast = [dict(id=c["id"], name=F.text(c.get("role"), lang), essence="", look="", own=bool(c.get("own")))
            for c in fmt["cast_slots"]]
    return dict(name=topic, engine=F.text(fmt.get("engine"), lang), cast=cast,
                always=[F.text(r, lang) for r in fmt["rules"].get("always") or []],
                never=[F.text(r, lang) for r in fmt["rules"].get("never") or []],
                ideas=rule_ideas(fmt, topic, 4, lang="zh" if zh else lang), source="rules")


def plan_series(prompt, fmt=None, budget=None, platforms=None, lang="en", episodes=None):
    prompt = str(prompt or "").strip()
    if not prompt and not fmt:
        raise CreateError("bad-input", field="prompt")
    info = parse_prompt(prompt)
    if info["cjk"] and lang == "en":
        lang = "zh"
    fid = fmt or guess_format(prompt)
    f = F.get(fid)
    got = ai.ask(SYSTEM.format(lang=ai.lang_name(lang)),
                 f"Request: {prompt}\nSuggested format: {fid} ({F.label(f, 'en')}: {F.text(f['blurb'], 'en')}).\n"
                 f"Beats of the format: {', '.join(b['label'] for b in F.expand_beats(f, 'en'))}.\n"
                 f"Cast slots: {', '.join(c['id'] + ' = ' + F.text(c['role'], 'en') for c in f['cast_slots'])}.\n"
                 "Return the series plan: format, a short name, the engine (one sentence: what every episode does), "
                 "the cast (id A/B..., name, essence, a concrete look), always / never rules, and 4 episode ideas.",
                 PLAN_SCHEMA)
    if got and got.get("format") in F.IDS:
        f = F.get(got["format"]) if not fmt else f
        d = dict(name=got["name"][:60], engine=got["engine"], cast=[dict(c, own=False) for c in got["cast"][:4]],
                 always=got["always"][:6], never=got["never"][:6], ideas=got["ideas"][:6], source="ai")
    else:
        d = rules_draft(prompt, f, lang, info)
    est = idea_cny(f)
    ideas = [dict(id=f"i{i + 1}", title=x["title"], logline=x.get("logline", ""), notes=x.get("notes", ""),
                  est_cny=est, picked=i < 2) for i, x in enumerate(d["ideas"])]
    languages = info["languages"] or ["zh" if lang.startswith("zh") else lang]
    length = info.get("length_s") or round(statistics.mean(f["length_s"]))
    return dict(schema_version=1, prompt=prompt, format=f["id"], recipe=f["recipe"], name=d["name"], lang=lang,
                bible=dict(engine=d["engine"], beats=F.expand_beats(f, lang), cast=d["cast"],
                           rules=dict(always=d["always"], never=d["never"]), gags=[], hooks=[], languages=languages,
                           aspect=f["aspect"], length_s=length, ai_generated=f["recipe"] == "ai-video"),
                ideas=ideas, episodes=episodes or info.get("episodes") or f.get("episodes") or 4,
                budget_cny=budget, platforms=list(platforms or []), source=d["source"])


def create_series(draft):
    f = F.get(draft["format"])
    sid = store.new_sid(draft.get("name") or f["id"])
    meta = dict(format=f["id"], budget_cny=draft.get("budget_cny"), languages=draft["bible"].get("languages") or [],
                episodes=draft.get("episodes"), lang=draft.get("lang", "en"), created=store.stamp(),
                prompt=draft.get("prompt", "")[:500], routing={}, sample=bool(draft.get("sample")))
    store.save_series_file(dict(id=sid, name=draft.get("name") or sid, recipe=f["recipe"],
                                params=dict(platforms=draft.get("platforms") or []), cadence={}, accounts=[],
                                spec=dict(create=meta), notes=None))
    store.save_bible(sid, draft["bible"])
    store.save_ideas(sid, draft.get("ideas") or [])
    return sid


REVISE_SCHEMA = {
    "type": "object",
    "properties": {
        "engine": {"type": "string"},
        "cast": PLAN_SCHEMA["properties"]["cast"],
        "always": {"type": "array", "items": {"type": "string"}},
        "never": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["engine", "cast", "always", "never"],
}


def revise_bible(sid, instruction=None, patch=None):
    bible = store.load_bible(sid)
    if patch:
        for k in ("engine", "cast", "rules", "languages", "length_s", "aspect", "gags", "hooks"):
            if k in patch:
                bible[k] = patch[k]
        store.save_bible(sid, bible)
        return bible
    text = str(instruction or "").strip()
    if not text:
        raise CreateError("bad-input", field="instruction")
    s = store.load_series_file(sid)
    lang = store.create_meta(s).get("lang", "en")
    got = ai.ask(SYSTEM.format(lang=ai.lang_name(lang)),
                 f"Current bible (YAML-ish): engine={bible.get('engine')!r} cast={bible.get('cast')!r} "
                 f"rules={bible.get('rules')!r}\nChange request: {text}\nReturn the full revised engine, cast, "
                 "always and never.", REVISE_SCHEMA)
    if got:
        bible["engine"] = got["engine"]
        bible["cast"] = [dict(c, own=next((o.get("own", False) for o in bible.get("cast") or [] if o.get("id") == c["id"]),
                                         False)) for c in got["cast"]]
        bible["rules"] = dict(always=got["always"], never=got["never"])
    else:
        rules = bible.setdefault("rules", dict(always=[], never=[]))
        if re.match(r"^\s*(never|don'?t|no\b|不要|别|禁止|不能)", text, re.I):
            rules.setdefault("never", []).append(text)
        else:
            rules.setdefault("always", []).append(text)
    store.save_bible(sid, bible)
    return bible


IDEAS_SCHEMA = {"type": "object", "properties": {"ideas": PLAN_SCHEMA["properties"]["ideas"]}, "required": ["ideas"]}


def more_ideas(sid, n=4):
    n = max(1, min(int(n or 4), 8))
    s = store.load_series_file(sid)
    meta = store.create_meta(s)
    f = F.get(meta["format"])
    bible = store.load_bible(sid)
    have = store.load_ideas(sid)
    lang = meta.get("lang", "en")
    got = ai.ask(SYSTEM.format(lang=ai.lang_name(lang)),
                 f"Series: {s.get('name')}. Engine: {bible.get('engine')}. Cast: {bible.get('cast')}. Already used: "
                 f"{[i['title'] for i in have]}. Write {n} NEW episode ideas (title, logline, notes).", IDEAS_SCHEMA)
    new = (got or {}).get("ideas") or rule_ideas(f, s.get("name") or "", n, start=len(have) + 1, lang=lang)
    est = idea_cny(f)
    base = max([int(i["id"][1:]) for i in have if re.match(r"^i\d+$", str(i.get("id")))] + [0])
    rows = [dict(id=f"i{base + k + 1}", title=x["title"], logline=x.get("logline", ""), notes=x.get("notes", ""),
                 est_cny=est, picked=False) for k, x in enumerate(new[:n])]
    store.save_ideas(sid, have + rows)
    return rows
