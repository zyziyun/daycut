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

TITLE_MAX_DEFAULT = {"xiaohongshu": 20, "youtube": 100, "bilibili": 80, "tiktok": 55, "douyin": 55}
XHS_CHAPTER_LABEL_MAX = 14


def _p(path, default=None):
    cur = persona()
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def platform_name(platform=None):
    return (platform or _p("platforms.default", "xiaohongshu") or "xiaohongshu").lower()


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
    if pl == "youtube":
        clean = [re.sub(r"\s+", "", t) for t in clean]
    return " ".join("#" + t for t in clean)


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
        sep = ": " if pl == "youtube" else "："
        out += [""] + [f"{lab}{sep}{url}" for lab, url in links]
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
