"""Publish copy: title-length checks, chapter timestamp lines, post bodies for 小红书 / YouTube / B站,
and SRT/ASS-safe timestamps.

    from vstudio.publish import check_title, chapter_lines, post_body, srt_ts
    ok, n, hints = check_title("学习新模式｜让AI给你做3b1b讲解视频", "xiaohongshu")   # (True, 17.0, [])
    chapter_lines([(0, "开场"), (42.5, "方法")])         -> ["00:00 开场", "00:42 方法"]
    post_body(hook, body, chapters, links, platform="youtube")

Title length: 小红书 counts CJK/full-width = 1, latin/digit/space = 0.5 (config.xhs_len); other platforms
count characters. Limits: persona platforms.<name>.title_max, else built-in defaults.
"""
import re

from .config import persona, xhs_len

TITLE_MAX_DEFAULT = {"xiaohongshu": 20, "youtube": 100, "bilibili": 80, "tiktok": 55, "douyin": 55,
                     "wechat-channels": 16, "x": 0, "instagram": 0, "facebook": 0, "linkedin": 0, "threads": 0,
                     "reddit": 300, "pinterest": 100, "snapchat": 0, "kuaishou": 0, "weibo": 30, "zhihu": 30,
                     "dailymotion": 255, "kwai": 0}
# no title field: the title becomes the first line (hook) of the post text
NO_TITLE = {"x", "instagram", "facebook", "linkedin", "threads", "snapchat", "kuaishou", "kwai"}
# extra tags are dropped (with a warning): X 1-2 by convention, IG hard max 5, Threads one topic tag, Reddit /
# Pinterest none (topics / keywords instead); see vstudio.platform hashtags.max
HASHTAG_CAP = {"x": 2, "instagram": 5, "threads": 1, "reddit": 0, "pinterest": 0, "snapchat": 3, "linkedin": 3,
               "facebook": 5, "kuaishou": 4, "weibo": 3, "dailymotion": 15}
HASHTAG_FORMAT = {"weibo": "#{tag}#"}   # 微博 topics are #话题# (two hashes)
XHS_CHAPTER_LABEL_MAX = 14


def _p(path, default=None):
    cur = persona()
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def platform_name(platform=None):
    pl = (platform or _p("platforms.default", "xiaohongshu") or "xiaohongshu").lower()
    try:
        from .platform import canonical
        return canonical(pl.split(":")[0]) if pl not in ("xhs",) else pl
    except Exception:
        return pl


def title_max(platform=None):
    pl = platform_name(platform)
    return _p(f"platforms.{pl}.title_max", TITLE_MAX_DEFAULT.get(pl, 100))


def title_len(title, platform=None):
    return xhs_len(title) if platform_name(platform) in ("xiaohongshu", "xhs") else float(len(title))


def _default_hints(title, n, tmax, platform):
    over = n - tmax
    hints = [f"{over:g} over the {tmax} limit for {platform}"]
    if re.search(r"[（(].*?[）)]", title):
        hints.append("drop the parenthetical")
    if re.search(r"\s", title) and platform in ("xiaohongshu", "xhs"):
        hints.append("remove spaces (each costs 0.5)")
    if re.search(r"[！!？?。，,]{2,}|[！!]$", title):
        hints.append("trim repeated / trailing punctuation")
    if any(s in title for s in ("｜", "|", "：", ":")):
        hints.append("keep only one side of the separator, or move it to the cover")
    hints.append("move detail into the cover text or the first line of the body")
    return hints


def check_title(title: str, platform: str = None, suggest=None):
    """-> (ok, length, suggestions). suggest(title, length, limit, platform) -> list[str] overrides the
    built-in hints (e.g. an LLM rewrite hook); it is only called when the title is too long."""
    pl = platform_name(platform)
    n = title_len(title, pl)
    tmax = title_max(pl)
    if not tmax:
        return True, n, [f"{pl} has no title field: the title is used as the first line of the post"]
    if n <= tmax:
        return True, n, []
    hints = (suggest or _default_hints)(title, n, tmax, pl)
    return False, n, list(hints or [])


# ---------------------------------------------------------------- timestamps
def _ms(t):
    return max(0, int(round(float(t) * 1000)))


def srt_ts(t):
    """00:01:02,345 — rounds once to integer ms, so it can never print ',1000'."""
    ms = _ms(t); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_ts(t):
    cs = int(round(max(0.0, float(t)) * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def mmss(t):
    """Chapter timestamp: floor to the second (a label must never point past its start); H:MM:SS over an hour."""
    t = max(0, int(float(t) + 1e-6)); h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def write_srt(cues, path):
    """cues: [(start, end, text)] -> SRT file."""
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, txt) in enumerate(cues, 1):
            f.write(f"{i}\n{srt_ts(a)} --> {srt_ts(max(b, a + 0.001))}\n{txt}\n\n")
    return path


def chapter_lines(chapters, offset=0.0, end=None, intro_label="开场", cap=None, platform=None, warn=print):
    """Chapter list in FINAL-video seconds -> ["00:00 开场", "01:23 label", ...].

    chapters: [(t, label)] or [(start, end, label)] or dicts {start/t, label/title}. offset shifts times
    (episode cut start); chapters outside [offset, end) are dropped. A 00:00 line is always first
    (YouTube requires it). cap = max label chars (default 14 on 小红书)."""
    pl = platform_name(platform)
    if cap is None and pl in ("xiaohongshu", "xhs"):
        cap = XHS_CHAPTER_LABEL_MAX
    items = []
    for c in chapters:
        if isinstance(c, dict):
            items.append((float(c.get("start", c.get("t", 0))), str(c.get("label", c.get("title", "")))))
        elif len(c) >= 3:
            items.append((float(c[0]), str(c[2])))
        else:
            items.append((float(c[0]), str(c[1])))
    items.sort()
    out = []
    for t, label in items:
        if t < offset - 1e-6 or (end is not None and t >= end):
            continue
        if cap and len(label) > cap:
            if warn:
                warn(f"chapter label > {cap} chars, shorten it: {label}")
            label = label[:cap]
        out.append((t - offset, label))
    lines = [f"{mmss(t)} {lab}" for t, lab in out]
    if not lines or not lines[0].startswith("00:00"):
        lines.insert(0, f"00:00 {intro_label}")
    if pl == "youtube" and warn:
        ts = [0.0] + [t for t, _ in out if t >= 1]
        if len(lines) < 3 or any(b - a < 10 for a, b in zip(ts, ts[1:])):
            warn("YouTube chapters need >= 3 entries, each >= 10 s long")
    return lines


def chapters_from_body(chapters, body_start, body_speed):
    """Body/original-time chapters (start, end, label) -> final time (hook montage first, body sped up)."""
    return [(body_start + a / body_speed, body_start + b / body_speed, lab) for a, b, lab in chapters]


# ---------------------------------------------------------------- post copy
def persona_tags(tag_set=None, warn=print):
    """The persona's tag list: ``publish.tag_sets[tag_set]`` when a set is named (e.g. "art", "tech"),
    else ``publish.tags``. An unknown set name warns and returns [] (never the career tags by surprise)."""
    if tag_set:
        sets = _p("publish.tag_sets", {}) or {}
        if tag_set not in sets:
            if warn:
                warn(f"publish.tag_sets has no {tag_set!r} (have: {', '.join(sets) or 'none'}); no persona tags added")
            return []
        return list(sets[tag_set] or [])
    return list(_p("publish.tags", []) or [])


def hashtags(tags=None, platform=None, use_persona=True, tag_set=None, warn=print):
    """Hashtag line: ``tags`` first, then (use_persona) the persona tags - ``publish.tag_sets[tag_set]``
    if ``tag_set`` is given, else ``publish.tags``. Duplicates and leading '#' are removed."""
    pl = platform_name(platform)
    allt = list(tags or []) + (persona_tags(tag_set, warn) if use_persona else [])
    clean = list(dict.fromkeys(t.lstrip("#").strip() for t in allt if t and t.strip("# ")))
    if not clean:
        return ""
    if pl == "bilibili":
        return "标签：" + "，".join(clean)
    if pl in ("youtube", "youtube-shorts", "x", "instagram", "tiktok", "facebook", "linkedin", "threads", "snapchat",
              "dailymotion", "kwai", "weibo"):
        clean = [re.sub(r"\s+", "", t) for t in clean]
    cap = HASHTAG_CAP.get(pl)
    if cap == 0:
        if warn:
            warn(f"{pl}: hashtags are not used there, left out ({', '.join(clean)})")
        return ""
    if cap and len(clean) > cap:
        if warn:
            warn(f"{pl}: {len(clean)} hashtags, kept the first {cap} (dropped: {', '.join(clean[cap:])})")
        clean = clean[:cap]
    fmt = HASHTAG_FORMAT.get(pl, "#{tag}")
    return " ".join(fmt.replace("{tag}", t) for t in clean)


def voice_warnings(text):
    rules = " ".join(_p("voice.rules", []) or []).lower()
    w = []
    if "em-dash" in rules and "—" in text:
        w.append("contains an em-dash (persona voice rule)")
    return w


def post_body(hook, body, chapters=None, links=None, tags=None, platform=None, title=None,
              chapter_intro=None, warn=print, use_persona_tags=True, tag_set=None):
    """Assemble post copy. hook: first line; body: str or list of paragraphs; chapters as for chapter_lines
    (already final seconds); links: [(label, url)] or {label: url}.
    Tags: ``tags`` (the post's own) + persona tags. use_persona_tags=True (default, also when explicit
    ``tags`` are passed - the historical behaviour) appends ``publish.tag_sets[tag_set]`` if ``tag_set``
    is named, else ``publish.tags``; use_persona_tags=False = only ``tags`` (e.g. an art post that must
    not inherit career tags).
    小红书: hook + body + chapter line + timeline + #tags.  YouTube: chapters as a plain list (auto-chapters),
    links first.  B站: 标签 line instead of hashtags."""
    pl = platform_name(platform)
    out = []
    if pl in NO_TITLE:                   # X / Instagram: no title field - the title leads the text if there is no hook
        if title and not hook:
            hook = title
        title = None
        if chapters:
            if warn:
                warn(f"{pl}: no chapters; timeline left out of the post text")
            chapters = None
    if title:
        ok, n, hints = check_title(title, pl)
        if not ok and warn:
            warn(f"title {n:g}/{title_max(pl)}: " + "; ".join(hints))
        out += [title, ""]
    if hook:
        out += [hook, ""]
    paras = [body] if isinstance(body, str) else list(body or [])
    out += [p for p in paras if p is not None]
    links = list(links.items()) if isinstance(links, dict) else list(links or [])
    if links:
        def sep(lab):                     # a Chinese label takes the full-width colon, an English one ": "
            return "：" if pl != "youtube" and re.search(r"[\u4e00-\u9fff]", str(lab)) else ": "
        out += [""] + [f"{lab}{sep(lab)}{url}" for lab, url in links]
    if chapters:
        intro = chapter_intro if chapter_intro is not None else _p("publish.chapter_line", "")
        if pl == "youtube":
            intro = chapter_intro if chapter_intro is not None else (intro or "Chapters")
        out += [""] + ([intro] if intro else []) + chapter_lines(chapters, platform=pl, warn=warn)
    tg = hashtags(tags, pl, use_persona=use_persona_tags, tag_set=tag_set, warn=warn)
    if tg:
        out += ["", tg]
    text = "\n".join(out).strip() + "\n"
    if warn:
        for w in voice_warnings(text):
            warn(w)
    return text


# ---------------------------------------------------------------- language / platform copy
def detect_lang(texts):
    """"en" when Latin letters outnumber CJK characters in ``texts`` (str or list of str / cue objects), "zh" when
    CJK wins, None for no text."""
    if isinstance(texts, str):
        texts = [texts]
    s = " ".join(getattr(t, "text", t) or "" for t in (texts or []))
    cjk = sum(1 for c in s if "\u3400" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff" or "\uac00" <= c <= "\ud7af")
    lat = sum(1 for c in s if c.isascii() and c.isalpha())
    if not cjk and not lat:
        return None
    return "en" if lat > 2 * cjk else "zh"


_COPY_KEYS = ("title", "hook", "body", "tags", "chapters", "links")


def localize_post(post, platform, content_lang=None, lang=None, bilingual=None, warn=print):
    """post.json -> the flat {title, hook, body, tags, chapters, links, lang} for one platform.

    post may hold per-language blocks ``{"en": {title, hook, body, tags}, "zh": {...}}`` next to (or instead of)
    the flat keys, plus ``lang`` / ``bilingual`` / ``lang_by_platform`` {platform: "en"}.
    Language: ``lang`` arg > ``lang_by_platform`` > ``post.lang`` > the content language (``content_lang``, e.g.
    detected from the cues): English content -> English copy on X / Instagram / TikTok / YouTube (INTL_PLATFORMS);
    Chinese platforms take the content language too. A missing block falls back to the other language / flat keys.
    bilingual (arg or ``post.bilingual``): English first, then Chinese (titles "EN / 中文", tags merged)."""
    from .platform import INTL_PLATFORMS
    pl = platform_name(platform)
    pl = "youtube" if pl == "youtube-shorts" else pl
    flat = {k: post.get(k) for k in _COPY_KEYS if post.get(k) is not None}
    blocks = {k: dict(flat, **post[k]) for k in ("en", "zh") if isinstance(post.get(k), dict)}
    want = (lang or (post.get("lang_by_platform") or {}).get(pl) or post.get("lang") or content_lang
            or ("en" if pl in INTL_PLATFORMS and "en" in blocks else None) or ("zh" if "zh" in blocks else None))
    if bilingual is None:
        bilingual = bool(post.get("bilingual"))
    if bilingual and len(blocks) == 2:
        en, zh = blocks["en"], blocks["zh"]

        def paras(b):
            body = b.get("body") or []
            return [body] if isinstance(body, str) else list(body)
        out = dict(flat)
        te, tz = en.get("title"), zh.get("title")
        out["title"] = f"{te} / {tz}" if te and tz and te != tz else (te or tz)
        hooks = [h for h in (en.get("hook"), zh.get("hook")) if h]
        out["hook"] = "\n".join(dict.fromkeys(hooks))
        out["body"] = paras(en) + ([""] if paras(en) and paras(zh) else []) + paras(zh)
        out["tags"] = list(dict.fromkeys(list(en.get("tags") or []) + list(zh.get("tags") or [])))
        out["chapters"] = en.get("chapters") or zh.get("chapters")
        out["lang"] = "en+zh"
        return out
    if bilingual and warn:
        warn("bilingual copy needs both an 'en' and a 'zh' block in post.json; using one language")
    if want in blocks:
        b = dict(blocks[want])
    elif blocks:
        got = next(iter(blocks))
        if want and warn:
            warn(f"{pl}: no '{want}' copy in post.json; using '{got}'")
        b, want = dict(blocks[got]), got
    else:
        b = dict(flat)
    b["lang"] = want
    return b


def _sentences(text):
    return [x for x in re.split(r"(?<=[.!?。！？])\s*", text or "") if x.strip()]


def fit_copy(text, platform, warn=print):
    """Shorten a post text to the platform's length (X: 280 weighted) by dropping whole body sentences from the
    end - the first line (hook) and the trailing hashtag line are kept. Other platforms are returned as is (warn
    only): their limits are large and cutting copy silently is worse than a warning."""
    from . import platform as P
    pl = platform_name(platform)
    if pl not in P.PLATFORMS:
        return text
    prof = P.profile(pl)
    if not prof.desc_max or P.text_len(prof, text) <= prof.desc_max:
        return text
    if prof.desc_count != "x":
        if warn:
            warn(f"{pl}: post text {P.text_len(prof, text)}/{prof.desc_max}; shorten it")
        return text
    lines = text.rstrip("\n").split("\n")
    tags = lines.pop() if lines and lines[-1].startswith("#") else ""
    head = lines[0] if lines else ""
    rest = _sentences(" ".join(x for x in lines[1:] if x.strip()))

    def join(r):
        parts = [head] + ([" ".join(r)] if r else []) + ([tags] if tags else [])
        return "\n\n".join(p for p in parts if p).strip() + "\n"
    while rest and P.text_len(prof, join(rest)) > prof.desc_max:
        rest.pop()
    out = join(rest)
    if P.text_len(prof, out) > prof.desc_max:
        out = join([]) if P.text_len(prof, join([])) <= prof.desc_max else head[:max(1, prof.desc_max // 2)] + "\n"
    if warn:
        warn(f"{pl}: post text shortened to {P.text_len(prof, out)}/{prof.desc_max} weighted chars")
    return out


def platform_post(post, platform, content_lang=None, lang=None, bilingual=None, warn=print, fit=True):
    """post.json -> the finished post text for one platform: localize_post + post_body (+ fit_copy for X)."""
    c = localize_post(post, platform, content_lang=content_lang, lang=lang, bilingual=bilingual, warn=warn)
    use_p, tag_set = post.get("use_persona_tags", True), post.get("tag_set")
    if c.get("lang") == "en" and "use_persona_tags" not in post and not tag_set:
        # English copy never inherits the (usually Chinese) persona tags; publish.tag_sets.en is used if it exists
        if "en" in (_p("publish.tag_sets", {}) or {}):
            tag_set = "en"
        else:
            use_p = False
    text = post_body(c.get("hook", ""), c.get("body", ""), chapters=c.get("chapters"), links=c.get("links"),
                     tags=c.get("tags"), platform=platform, title=c.get("title"), warn=warn,
                     use_persona_tags=use_p, tag_set=tag_set)
    return (fit_copy(text, platform, warn=warn) if fit else text), c


COPY_SCHEMA = {"type": "object", "properties": {"hook": {"type": "string"}, "body": {"type": "string"},
                                                "tags": {"type": "array", "items": {"type": "string"}}},
               "required": ["hook", "body", "tags"]}


def copy_prompt(platform, source, lang="en", bilingual=False):
    """(system, prompt) for an LLM to write post copy for ``platform`` from ``source`` (transcript / summary)."""
    from . import platform as P
    pl = platform_name(platform)
    prof = P.profile(pl)
    unit = "weighted characters (CJK and emoji count 2, a URL 23)" if prof.desc_count == "x" else "characters"
    lo, hi = (prof.hashtags.get("recommend") or [1, prof.hashtags.get("max") or 5])
    language = "English first, then the same in Chinese" if bilingual else {"en": "English", "zh": "Simplified Chinese"}.get(lang, lang)
    rules = " ".join(_p("voice.rules", []) or [])
    system = (f"You write social post copy for {prof.label}. Language: {language}. Whole post <= {prof.desc_max} {unit} "
              f"including hashtags. First line = the hook (what the viewer gets, no clickbait). {lo}-{hi} specific "
              f"hashtags, no generic ones. No title field on this platform: put everything in hook + body. "
              + (f"Voice rules: {rules}" if rules else ""))
    prompt = f"Write the post for this video.\n\nSOURCE:\n{source.strip()[:6000]}"
    return system, prompt


def generate_copy(platform, source, lang="en", bilingual=False, provider=None, complete=None, warn=print):
    """LLM post copy (llm task ``copy``) -> {hook, body, tags, text}; the text is assembled with post_body and fitted
    to the platform limit (X weighted 280). ``complete`` = a stand-in for vstudio.llm.complete (tests). Returns None
    when no model is routed (provider ``none``) - write the copy by hand then."""
    if complete is None:
        from .llm import complete
    system, prompt = copy_prompt(platform, source, lang, bilingual)
    r = complete("copy", system, prompt, schema=COPY_SCHEMA, provider=provider)
    j = (r or {}).get("json")
    if not j:
        return None
    from . import entities as ENT                     # names spelled like the captions (宏都拉斯 -> 洪都拉斯)
    j = ENT.fix_post(j, ENT.verify(source + "\n" + "\n".join(str(v) for v in j.values() if isinstance(v, str)))["fixes"])
    text = post_body(j.get("hook", ""), j.get("body", ""), tags=j.get("tags"), platform=platform, warn=warn,
                     use_persona_tags=False)
    text = fit_copy(text, platform, warn=warn)
    return dict(j, text=text, lang="en+zh" if bilingual else lang)
