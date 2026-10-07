"""One sentence -> a posting rule (发布 page, 「一句话排期」). Preview only: nothing here writes.

``parse(text)`` reads the few shapes creators actually type, in Chinese, English and French:

  每天晚上8点发一条小红书，周末不发        every weekday at 20:00 on xiaohongshu, 1 a day
  工作日中午12点发抖音和X                   weekdays 12:00 on douyin + x
  每周一三五 19:30 小红书                   Mon / Wed / Fri at 19:30
  next week, 2 posts a day on TikTok at 9am and 6pm is NOT supported (one time per rule; the 2nd post goes +2 h)
  tous les soirs à 20h sur Instagram, pas le week-end

-> dict(time "HH:MM" | None, days [0..6] (Mon = 0) | None, per_day int, platforms [...], next_week bool,
        understood bool, matched [what was recognised]).  Unknown words are ignored; when nothing at all is
recognised ``understood`` is False and the desk says so instead of guessing.
"""
import re

ZH_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# longest names first so "youtube shorts" wins over "youtube"
PLATFORM_WORDS = [
    (r"youtube\s*shorts|油管短视频|shorts", "youtube-shorts"),
    (r"小红书|红书|rednote|xiaohongshu|\bxhs\b", "xiaohongshu"),
    (r"抖音|douyin", "douyin"),
    (r"tiktok|tik\s*tok", "tiktok"),
    (r"视频号|wechat\s*channels|channels", "wechat-channels"),
    (r"b站|哔哩哔哩|bilibili", "bilibili"),
    (r"youtube|油管", "youtube"),
    (r"instagram|\binsta\b|\big\b|\bins\b", "instagram"),
    (r"推特|twitter|(?<![a-z])x(?![a-z])", "x"),
    (r"快手|kuaishou", "kuaishou"),
    (r"微博|weibo", "weibo"),
    (r"知乎|zhihu", "zhihu"),
    (r"linkedin|领英", "linkedin"),
    (r"facebook|脸书", "facebook"),
    (r"threads", "threads"),
]

WEEKDAY_WORDS = [
    ("monday|lundi|\\bmon\\b", 0), ("tuesday|mardi|\\btue\\b", 1), ("wednesday|mercredi|\\bwed\\b", 2),
    ("thursday|jeudi|\\bthu\\b", 3), ("friday|vendredi|\\bfri\\b", 4), ("saturday|samedi|\\bsat\\b", 5),
    ("sunday|dimanche|\\bsun\\b", 6),
]
ZH_DAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "七": 6}

NO_WEEKEND = re.compile(r"周末不发|周末休息|周末停|周末不|不包括周末|除了周末|除周末|no\s+weekends?|not\s+on\s+(the\s+)?weekends?|"
                        r"skip\s+(the\s+)?weekends?|weekends?\s+off|except\s+(on\s+)?weekends?|pas\s+le\s+week-?end|"
                        r"sauf\s+le\s+week-?end|hors\s+week-?end", re.I)
WEEKDAYS = re.compile(r"工作日|周一到周五|周一至周五|星期一到星期五|weekdays?\b|mon(day)?\s*(-|–|to|through)\s*fri(day)?|en\s+semaine|"
                      r"du\s+lundi\s+au\s+vendredi|jours\s+ouvrés", re.I)
WEEKENDS = re.compile(r"(只在|仅在|只)?周末(发|更)?(?!不)|weekends?\s+only|only\s+(on\s+)?weekends?|on\s+weekends|le\s+week-?end\s+seulement|"
                      r"seulement\s+le\s+week-?end", re.I)
DAILY = re.compile(r"每天|每日|天天|日更|every\s*day|daily|each\s+day|tous\s+les\s+(jours|soirs|matins)|chaque\s+(jour|soir|matin)", re.I)
ALT = re.compile(r"隔天|每隔一天|every\s+other\s+day|un\s+jour\s+sur\s+deux", re.I)
NEXT_WEEK = re.compile(r"下周|下个?星期|下礼拜|next\s+week|semaine\s+prochaine", re.I)

EVENING = re.compile(r"晚上|晚|傍晚|夜里|下午|evening|night|tonight|\bpm\b|p\.m\.|soir|après-midi", re.I)
NOON = re.compile(r"中午|noon|midi", re.I)


def _zh_int(s):
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + ZH_NUM.get(s[1:], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return ZH_NUM.get(a, 0) * 10 + (ZH_NUM.get(b, 0) if b else 0)
    return ZH_NUM.get(s)


def _time(text):
    """-> ("HH:MM", matched) or (None, None)."""
    t = text.lower()
    m = re.search(r"(\d{1,2})\s*:\s*(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if m.group(3) and m.group(3).startswith("p") and h < 12:
            h += 12
        elif m.group(3) and m.group(3).startswith("a") and h == 12:
            h = 0
        elif not m.group(3) and h < 12 and EVENING.search(t[:m.start()][-6:] + t[m.end():m.end() + 4]):
            h += 12
        return (f"{h:02d}:{mi:02d}", m.group(0)) if h < 24 and mi < 60 else (None, None)
    m = re.search(r"(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)", t)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(2).startswith("p") else 0)
        return f"{h:02d}:00", m.group(0)
    m = re.search(r"(\d{1,2})\s*h\s*(\d{2})?", t)                     # fr: 20h, 20h30
    if m and re.search(r"\d\s*h(\d|\b|\s|$)", t):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h < 12 and EVENING.search(t):
            h += 12
        return (f"{h:02d}:{mi:02d}", m.group(0)) if h < 24 and mi < 60 else (None, None)
    m = re.search(r"([0-9]{1,2}|[一二两三四五六七八九十]{1,3})\s*[点時时](?:\s*(半|[0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*分?)?", text)
    if m:
        h = _zh_int(m.group(1))
        if h is None:
            return None, None
        mi = 30 if m.group(2) == "半" else (_zh_int(m.group(2)) or 0) if m.group(2) else 0
        before = text[max(0, m.start() - 4):m.start()]
        if h < 12 and EVENING.search(before):
            h += 12
        elif h < 12 and NOON.search(before) and h < 6:
            h += 12
        return (f"{h:02d}:{mi:02d}", m.group(0)) if h < 24 and mi < 60 else (None, None)
    if NOON.search(t):
        return "12:00", "noon"
    return None, None


def _days(text):
    """-> (sorted weekday list or None, what matched)."""
    t = text.lower()
    if NO_WEEKEND.search(t) or WEEKDAYS.search(t):
        return [0, 1, 2, 3, 4], "weekdays"
    m = re.search(r"(?:每周|每星期|每个?礼拜|周|星期|礼拜)([一二三四五六日天七](?:[、,，和及与]?[一二三四五六日天七])*)", text)
    if m:
        ds = sorted({ZH_DAY[c] for c in m.group(1) if c in ZH_DAY})
        if ds:
            return ds, "days"
    ds = sorted({d for pat, d in WEEKDAY_WORDS if re.search(pat, t)})
    if ds:
        return ds, "days"
    if WEEKENDS.search(t):
        return [5, 6], "weekends"
    if ALT.search(t):
        return [0, 2, 4, 6], "alternate"
    if DAILY.search(t):
        return list(range(7)), "daily"
    return None, None


def _per_day(text):
    m = re.search(r"(?:每天|每日|一天|天天)?\s*([0-9]+|[一二两三四五])\s*(?:条|個|个|篇|支)", text)
    if m:
        n = _zh_int(m.group(1))
        if n:
            return max(1, min(4, n))
    m = re.search(r"([0-9]+|one|two|three|four|une?|deux|trois)\s*(?:posts?|videos?|clips?|vidéos?|publications?)\s*"
                  r"(?:a|per|par|each)\s*(?:day|jour)", text, re.I)
    if m:
        w = m.group(1).lower()
        n = {"one": 1, "un": 1, "une": 1, "two": 2, "deux": 2, "three": 3, "trois": 3, "four": 4}.get(w) or int(w)
        return max(1, min(4, n))
    return 1


def _platforms(text):
    t = text.lower()
    out = []
    for pat, pid in PLATFORM_WORDS:
        if re.search(pat, t, re.I) and pid not in out:
            if pid == "youtube" and "youtube-shorts" in out:
                continue
            out.append(pid)
            t = re.sub(pat, " ", t, flags=re.I)
    return out


def parse(text):
    text = (text or "").strip()
    time_, tm = _time(text)
    days, dm = _days(text)
    pfs = _platforms(text)
    matched = [x for x in (tm and "time", dm, pfs and "platforms") if x]
    return dict(time=time_, days=days, days_kind=dm, per_day=_per_day(text), platforms=pfs,
                next_week=bool(NEXT_WEEK.search(text)), understood=bool(matched), matched=matched)
