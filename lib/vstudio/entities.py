"""Named-entity verification for everything made from a transcript: captions, notes / quote cards, titles and
post copy. ASR writes proper nouns by sound, so 洪都拉斯 (Honduras) comes out as 宏都拉斯; this module finds such
names and gives ONE set of fixes that every text of a project applies the same way.

    from vstudio import entities as E
    r = E.verify("他去了宏都拉斯，后来去了纽西兰", locale="zh_Hans")
    r["fixes"]      # [{from: 宏都拉斯, to: 洪都拉斯, kind: place, source: cldr, guess: False, why}]
    r["entities"]   # every name found: {text, standard, kind, source, variant?}
    E.fix_text("宏都拉斯的咖啡", r["fixes"])          # -> 洪都拉斯的咖啡 (guesses are never applied)
    E.fix_post({"title": ..., "body": ..., "tags": [...]}, r["fixes"])

Rules
  places (zh)   country / region names from Unicode CLDR (``babel``: zh_Hans, zh_Hant, zh_Hant_HK) plus a curated
                list of major cities. A span that SOUNDS like the content locale's standard name (toneless pinyin,
                heteronyms allowed; 3+ characters, at most 1 character in 3 differs) but is written differently
                is a mis-heard / other-locale spelling: corrected to the standard (宏都拉斯 -> 洪都拉斯 in zh_Hans,
                the reverse in zh_Hant). A regional name that sounds DIFFERENT (纽西兰 vs 新西兰, 澳洲 vs 澳大利亚)
                is the speaker's own word: kept, reported as ``variant: regional``. Without a pinyin backend
                (pypinyin, or macOS Foundation) a candidate is only flagged (``guess``).
  glossary      the creator's / source glossary terms (any language): a span that differs only in case, or sounds
                alike (score >= 0.86, same word count) -> the glossary spelling ("wells fargo" -> "Wells Fargo").
  llm           ``check_prompt`` / ``parse_llm`` (one call per source, inside the glossary step): organisations,
                products, people, places with their standard spelling and ``certain``; an uncertain answer, or
                one that does not sound like the transcript, is kept as ``guess`` (shown to the creator, never
                applied).
Every applied fix also passes ``vstudio.proofread.faithful`` (the caption must still say what was said).
"""
from __future__ import annotations

import difflib
import functools
import re

CJK = r"㐀-鿿豈-﫿"
LOCALES = ("zh_Hans", "zh_Hant", "zh_Hant_HK")

# major cities (CLDR has no city names): zh_Hans standard -> {zh_Hant spelling}
CITIES = {
    "纽约": "紐約", "洛杉矶": "洛杉磯", "旧金山": "舊金山", "芝加哥": "芝加哥", "波士顿": "波士頓", "西雅图": "西雅圖",
    "华盛顿": "華盛頓", "拉斯维加斯": "拉斯維加斯", "迈阿密": "邁阿密", "休斯敦": "休士頓", "多伦多": "多倫多",
    "温哥华": "溫哥華", "蒙特利尔": "蒙特婁", "墨西哥城": "墨西哥城", "圣保罗": "聖保羅", "里约热内卢": "里約熱內盧",
    "布宜诺斯艾利斯": "布宜諾斯艾利斯", "伦敦": "倫敦", "巴黎": "巴黎", "柏林": "柏林", "罗马": "羅馬", "米兰": "米蘭",
    "马德里": "馬德里", "巴塞罗那": "巴塞隆納", "阿姆斯特丹": "阿姆斯特丹", "维也纳": "維也納", "布拉格": "布拉格",
    "苏黎世": "蘇黎世", "日内瓦": "日內瓦", "莫斯科": "莫斯科", "伊斯坦布尔": "伊斯坦堡", "迪拜": "杜拜", "开罗": "開羅",
    "东京": "東京", "大阪": "大阪", "京都": "京都", "首尔": "首爾", "曼谷": "曼谷", "吉隆坡": "吉隆坡", "雅加达": "雅加達",
    "河内": "河內", "胡志明市": "胡志明市", "马尼拉": "馬尼拉", "孟买": "孟買", "新德里": "新德里", "悉尼": "雪梨",
    "墨尔本": "墨爾本", "奥克兰": "奧克蘭", "北京": "北京", "上海": "上海", "广州": "廣州", "深圳": "深圳", "杭州": "杭州",
    "成都": "成都", "重庆": "重慶", "武汉": "武漢", "西安": "西安", "南京": "南京", "苏州": "蘇州", "天津": "天津",
    "厦门": "廈門", "青岛": "青島", "台北": "台北", "高雄": "高雄",
}
# regional names that sound different from the zh_Hans standard: the speaker's own word, never "corrected"
REGIONAL_ZH_HANS = {"纽西兰": "NZ", "澳洲": "AU", "义大利": "IT", "纽澳": None, "星加坡": "SG", "南韩": "KR",
                    "寮国": "LA", "柬埔寨": "KH", "雪梨": "悉尼", "杜拜": "迪拜", "纽约市": "纽约"}

# a span whose differing character is one of these is ordinary speech, not a place (圣诞到了 is not 圣诞岛)
COMMON_ZH = set("的了是在和有到也就都要会能说对这那你我他她它们个上下来去过着把被让给从向跟比还又很太更最没不")
MIN_LEN = 3                  # 2-character names (美国, 日本) are left alone: too many ordinary words look alike
GLOSSARY_MIN = 0.86          # sound-alike score a glossary-spelling fix needs (same word count)


# ------------------------------------------------------------------ names
@functools.lru_cache(maxsize=8)
def territories(locale="zh_Hans"):
    """{name: code} of CLDR territory names for ``locale`` (letter codes only; empty when babel is missing)."""
    try:
        from babel import Locale
        t = Locale.parse(locale).territories
    except Exception:  # noqa: BLE001 - babel missing / unknown locale: city list only
        return {}
    return {str(v): k for k, v in t.items() if re.fullmatch(r"[A-Z]{2}", k) and re.fullmatch(f"[{CJK}]+", str(v))}


def norm_locale(locale=None, text=""):
    """zh / zh-CN / zh_Hans -> zh_Hans; zh-TW / zh_Hant -> zh_Hant; zh-HK -> zh_Hant_HK; None -> from the text."""
    s = str(locale or "").replace("-", "_").lower()
    if s in ("zh_tw", "zh_hant", "zh_hant_tw", "tw"):
        return "zh_Hant"
    if s in ("zh_hk", "zh_hant_hk", "zh_mo", "hk"):
        return "zh_Hant_HK"
    if s.startswith("zh") or (not s and re.search(f"[{CJK}]", text or "")):
        return "zh_Hans"
    return None


@functools.lru_cache(maxsize=8)
def standard_names(locale="zh_Hans"):
    """{name: (kind, id)} the content locale writes: CLDR territories + cities."""
    out = {n: ("place", c) for n, c in territories(locale).items()}
    for hans, hant in CITIES.items():
        out[hans if locale == "zh_Hans" else hant] = ("city", hans)
    return out


@functools.lru_cache(maxsize=8)
def _index(locale):
    """(length, position, char) -> [names] for the char-overlap prefilter."""
    idx = {}
    for n in standard_names(locale):
        if len(n) >= MIN_LEN:
            for i, ch in enumerate(n):
                idx.setdefault((len(n), i, ch), []).append(n)
    return idx


@functools.lru_cache(maxsize=4096)
def _readings(ch):
    """Toneless pinyin readings of one character (all heteronyms with pypinyin), or None (no backend)."""
    try:
        from pypinyin import Style, pinyin
        return frozenset(pinyin(ch, heteronym=True, style=Style.NORMAL)[0])
    except Exception:  # noqa: BLE001
        from .proofread import pinyin_of
        p = pinyin_of(ch)
        return frozenset(p) if p else None


def homophone(a, b):
    """True / False whether two equal-length CJK spans sound the same (toneless), None when it cannot be told."""
    if len(a) != len(b):
        return False
    from .proofread import pinyin_of
    pa, pb = pinyin_of(a), pinyin_of(b)
    if pa is not None and pb is not None and pa == pb:
        return True
    for x, y in zip(a, b):
        if x == y:
            continue
        rx, ry = _readings(x), _readings(y)
        if rx is None or ry is None:
            return None
        if not rx & ry:
            return False
    return True


def _max_diff(n):
    return max(1, n // 3)


def _zh_places(text, locale):
    """Mis-heard / other-locale spellings of standard place names in ``text`` -> (fixes, entities)."""
    std = standard_names(locale)
    idx = _index(locale)
    lengths = sorted({len(n) for n in std if len(n) >= MIN_LEN}, reverse=True)
    fixes, ents, seen = {}, {}, set()
    regional = REGIONAL_ZH_HANS if locale == "zh_Hans" else {}
    for name in std:
        if len(name) >= 2 and name in text:
            ents[name] = dict(text=name, standard=name, kind=std[name][0], source="cldr" if std[name][0] == "place"
                              else "city")
    for name, code in regional.items():
        if name in text:
            ents[name] = dict(text=name, standard=name, kind="place", source="regional", variant="regional",
                              note=f"regional name (sounds different from the {locale} standard): kept")
    for i in range(len(text)):
        for L in lengths:
            sub = text[i:i + L]
            if len(sub) < L or not re.fullmatch(f"[{CJK}]+", sub) or sub in std or sub in seen:
                continue
            cands = {}
            for pos, ch in enumerate(sub):
                for n in idx.get((L, pos, ch), ()):
                    cands[n] = cands.get(n, 0) + 1
            for n, same in cands.items():
                if same < L - _max_diff(L) or same == L:
                    continue
                if any(x != y and x in COMMON_ZH for x, y in zip(sub, n)):
                    continue
                if any(sub in r or r in sub for r in regional if len(r) >= 2 and r in text[max(0, i - 2):i + L + 2]):
                    continue
                h = homophone(sub, n)
                if h is False:
                    continue
                seen.add(sub)
                kind = std[n][0]
                fixes[sub] = dict(**{"from": sub, "to": n}, kind=kind, source="cldr" if kind == "place" else "city",
                                  guess=h is None, why=(f"{sub} sounds like {n}, the {locale} standard name"
                                                        if h else f"{sub} looks like {n} (sound not checked: no pinyin)"))
                ents[sub] = dict(text=sub, standard=n, kind=kind, source=fixes[sub]["source"])
                break
    return list(fixes.values()), list(ents.values())


# ------------------------------------------------------------------ glossary terms (any language)
def _words(s):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9&'-]*", s or "")


def _glossary_fixes(text, terms):
    from .proofread import faithful, sound_alike
    out, ents = [], []
    toks = list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9&'-]*", text or ""))
    for term in dict.fromkeys(str(t).strip() for t in terms or () if str(t).strip()):
        if not re.search(r"[A-Za-z]", term):
            continue
        n = len(_words(term))
        if not n:
            continue
        for k in range(len(toks) - n + 1):              # every window of n words (overlapping)
            win = toks[k:k + n]
            if any(re.search(r"\S", text[x.end():y.start()]) for x, y in zip(win, win[1:])):
                continue                                  # words split by punctuation: not one name
            span = text[win[0].start():win[-1].end()]
            if span == term:
                ents.append(dict(text=span, standard=term, kind="term", source="glossary"))
                continue
            if span.lower() == term.lower():
                out.append(dict(**{"from": span, "to": term}, kind="term", source="glossary", guess=False,
                                why="the glossary spelling (case)"))
                continue
            sc = sound_alike(span, term)
            if sc is not None and sc >= GLOSSARY_MIN and span[:1].lower() == term[:1].lower() \
                    and not faithful(span, term):
                out.append(dict(**{"from": span, "to": term}, kind="term", source="glossary", guess=sc < 0.9,
                                why=f"sounds like the glossary term {term} ({sc:.2f})"))
    uniq = {}
    for f in out:
        uniq.setdefault((f["from"], f["to"]), f)
    return list(uniq.values()), ents


# ------------------------------------------------------------------ the LLM check (inside the glossary call)
LLM_RULES = """Also list the proper nouns of the transcript (countries, regions, cities, organisations, companies, \
products, people): "entities": [{"text": "<exactly as in the transcript>", "standard": "<the standard spelling in \
the transcript's language and script>", "kind": "place|org|product|person", "certain": true|false}] - "certain" \
only when you know the standard spelling for sure; never translate, never change what was said (a sound-alike \
spelling fix only)."""


def check_prompt():
    return LLM_RULES


def parse_llm(items, text=""):
    """The model's ``entities`` list -> (fixes, flagged): a certain, sound-alike, faithful fix is applied; anything
    else stays a guess for the creator to look at."""
    from .proofread import faithful, sound_alike
    fixes, flagged = [], []
    for e in items or []:
        if not isinstance(e, dict):
            continue
        a, b = str(e.get("text") or "").strip(), str(e.get("standard") or "").strip()
        if not a or not b or a == b or (text and a not in text):
            continue
        sc = sound_alike(a, b)
        ok = bool(e.get("certain")) and not faithful(a, b) and (sc is None or sc >= 0.8)
        f = dict(**{"from": a, "to": b}, kind=str(e.get("kind") or "entity"), source="llm", guess=not ok,
                 why="standard spelling (model, certain)" if ok else
                 f"model suggests the standard spelling {b}" + ("" if e.get("certain") else " (not certain)"))
        (fixes if ok else flagged).append(f)
    return fixes, flagged


# ------------------------------------------------------------------ public
def verify(text, locale=None, glossary=None, llm_entities=None):
    """-> {locale, fixes [applied ones], flagged [guesses], entities}. ``glossary``: terms (the creator's list /
    the source glossary); ``llm_entities``: the model's ``entities`` list (``check_prompt``)."""
    text = text or ""
    loc = norm_locale(locale, text)
    fixes, ents, flagged = [], [], []
    if loc:
        f, e = _zh_places(text, loc)
        fixes += f
        ents += e
    f, e = _glossary_fixes(text, glossary)
    fixes += f
    ents += e
    if llm_entities:
        f, fl = parse_llm(llm_entities, text)
        have = {x["from"] for x in fixes}
        fixes += [x for x in f if x["from"] not in have]
        flagged += fl
    flagged += [x for x in fixes if x.get("guess")]
    fixes = [x for x in fixes if not x.get("guess")]
    for f in fixes:
        f["count"] = len(_pat(f["from"]).findall(text))
    return dict(locale=loc, fixes=sorted(fixes, key=lambda x: -len(x["from"])), flagged=flagged, entities=ents)


def _pat(a):
    p = re.escape(a)
    if re.match(r"[A-Za-z0-9]", a):
        p = r"(?<![A-Za-z0-9])" + p
    if re.search(r"[A-Za-z0-9]$", a):
        p += r"(?![A-Za-z0-9])"
    return re.compile(p)


def fix_text(text, fixes):
    """``text`` with every non-guess fix applied (longest first, latin spans on word boundaries)."""
    if not text or not fixes:
        return text
    for f in sorted((x for x in fixes if not x.get("guess")), key=lambda x: -len(x["from"])):
        text = _pat(f["from"]).sub(f["to"].replace("\\", "\\\\"), text)
    return text


def fix_post(post, fixes):
    """A post / card dict (title, body, hook, notes [..], tags [..], text, quote) with the fixes applied."""
    if not isinstance(post, dict) or not fixes:
        return post
    out = dict(post)
    for k, v in post.items():
        if isinstance(v, str):
            out[k] = fix_text(v, fixes)
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = [fix_text(x, fixes) for x in v]
    return out


def for_texts(texts, locale=None, glossary=None):
    """The fixes for a set of texts (captions + cards + copy of one project), computed once on all of them."""
    return verify("\n".join(t for t in texts if t), locale, glossary)


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


__all__ = ["verify", "fix_text", "fix_post", "for_texts", "territories", "standard_names", "homophone",
           "check_prompt", "parse_llm", "norm_locale", "CITIES"]
