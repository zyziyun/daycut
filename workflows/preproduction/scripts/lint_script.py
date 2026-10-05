#!/usr/bin/env python3
"""Lint a spoken script against the craft rules (references/script_craft.md) + persona voice.*.

English checks: em-dashes, parentheses, creator-trope openers, generic CTAs, authority framing, AI-tell
vocabulary, meta/forward references, sentences > 25 words, possible fragments, digits under 10,
presence of an insight signpost, and word count vs. the length target at voice.en.wpm (default 165).
Chinese (口播) checks: em-dashes, parentheses, 口播 trope openers (家人们, 今天给大家分享...), generic CTAs
(点赞关注, 一键三连...), authority framing, AI-tell words, meta lines, emoji, phrases_avoid, signpost,
sentences > 40 字, and character count at voice.zh.cpm (default 270 字/min = 4.5 字/s).

Language: --lang auto (default) picks zh when CJK characters are >= 30% of the letters in the spoken
lines. The voice profile is voice.<lang>.* per key, falling back to the flat legacy voice.* keys, then
built-in defaults (a persona with only flat keys lints exactly as before).

Length target precedence: --platform wins. With --platform the target is the platform's sweet spot
(vstudio.platform profile.length.sweet, seconds) x pace, and the hard max is checked (ERROR when over).
Without --platform, --format picks the classic target (short / long-short / mid; default short).
If both are given, --format is ignored for length and a note is printed.

  python3 lint_script.py SCRIPT.md [--format short|long-short|mid] [--platform douyin] [--lang auto] [--strict]

Markdown headings, [bracket notes], ZH:/Delivery lines and code fences are ignored. Exit code 1 with
--strict if any error is found. Test overrides: VSTUDIO_PERSONA=path.yaml is merged over the persona.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import re

from vstudio.config import persona

OPENERS = ["ok so", "okay so", "quick thing", "you won't believe", "today we're", "today we are", "today i want to",
           "let me tell you", "buckle up", "here's something wild", "welcome back", "hey everyone", "hey guys"]
CTAS = ["follow for more", "subscribe", "hope that helps", "wild, right", "wild right", "smash", "like button",
        "comment your thoughts", "drop your thoughts", "let me know in the comments", "don't forget to"]
AUTHORITY = ["every time someone asks me", "as an expert", "the thing nobody is talking about",
             "nobody is talking about", "most people don't realize", "most people don't know"]
AI_TELL = ["delve", "dive into", "deep dive", "navigate", "leverage", "tapestry", "journey", "comprehensive", "robust",
           "seamless", "in today's fast-paced world", "it's important to note", "it is important to note", "realm",
           "unlock the power", "game-changer", "game changer"]
META = ["this slide", "this video", "if you remember one thing", "this is the most important", "we've got a lot to cover",
        "more on that later", "we'll come back to", "to recap", "as i mentioned", "in a few minutes"]
SIGNPOSTS = ["explained enough", "most explanations skip", "doesn't get talked about", "what's actually happening",
             "here's the detail", "the part that", "underneath"]
TARGETS = {"short": (165, 250), "long-short": (250, 510), "mid": (500, 1650)}
SMALL = {"1", "2", "3", "4", "5", "6", "7", "8", "9"}

# --- generic 中文口播 lists (not personal; extend per creator with voice.zh.phrases_avoid)
ZH_OPENERS = ["家人们", "宝子们", "姐妹们", "兄弟们", "大家好", "哈喽大家好", "今天给大家分享", "今天跟大家分享",
              "今天来聊聊", "今天跟大家聊聊", "今天我们来聊", "话不多说", "废话不多说", "你绝对想不到", "震惊"]
ZH_CTAS = ["点赞关注", "点赞收藏", "点个赞", "点个关注", "一键三连", "求关注", "记得关注", "关注我", "评论区告诉我",
           "评论区聊聊", "评论区见", "我们下期见", "下期见", "别忘了", "双击", "收藏起来"]
ZH_AUTHORITY = ["作为专家", "作为一个过来人", "经常有人问我", "很多人不知道", "99%的人都不知道", "没人告诉你",
                "90%的人"]
ZH_AI_TELL = ["赋能", "抓手", "闭环", "颗粒度", "值得注意的是", "综上所述", "总而言之", "在当今快节奏的时代",
              "在这个信息爆炸的时代", "不可或缺", "全方位", "一站式", "助力"]
ZH_META = ["这一页", "这页PPT", "本期视频", "这期视频", "后面再讲", "后面会讲", "前面说过", "前面提到",
           "如果你只记住一件事", "这是最重要的"]
ZH_SIGNPOSTS = ["很少有人讲", "很少有人提", "真正的问题是", "关键在于", "本质上", "真正决定", "说白了", "换个角度",
                "底层原因"]
ZH_THROAT = r"^(那么|好的|嗯|那个|OK|ok|好吧)[，,\s]"
ZH_SENT_MAX = 40                 # 字 per sentence before a warning (read-aloud breath unit)
ZH_CPM = 270                     # 字/min default (~4.5 字/s, natural 口播 pace)
FORMAT_SECS = {"short": (60, 90), "long-short": (90, 180), "mid": (180, 600)}   # craft §1, used for zh

CJK = r"[㐀-䶿一-鿿豈-﫿]"


def spoken_text(raw):
    out, fence = [], False
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith("```"):
            fence = not fence; continue
        if fence or not s or s.startswith(("#", "[", "ZH:", "zh:", "**Delivery", "Delivery:", ">", "<!--", "|", "---")):
            continue
        out.append(re.sub(r"\[[^\]]*\]", "", s))
    return " ".join(out)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", text) if s.strip()]


def zh_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;])\s*", text) if s.strip()]


def find_any(text_l, phrases):
    return [p for p in phrases if re.search(r"(?<![a-z])" + re.escape(p.lower()) + r"(?![a-z])", text_l)]


def find_zh(text, phrases):
    hits = [p for p in phrases if p and p.lower() in text.lower()]
    return [p for p in hits if not any(p != q and p in q for q in hits)]     # 下期见 inside 我们下期见 -> once


def detect_lang(text):
    """'zh' when CJK characters are >= 30% of letters (CJK + latin), else 'en'."""
    c = len(re.findall(CJK, text))
    l = len(re.findall(r"[A-Za-z]", text))
    return "zh" if c and c / (c + l) >= 0.3 else "en"


def zh_units(text):
    """Spoken length units for Chinese: CJK characters + 1 per latin word / number."""
    return len(re.findall(CJK, text)) + len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'.%]*", text))


def voice_for(lang):
    """voice.<lang>.<key> -> flat voice.<key> -> (caller default). The flat legacy pace key `wpm`
    is English words/min, so zh does not inherit it."""
    v = persona().get("voice", {}) or {}
    flat = {k: x for k, x in v.items() if k not in ("en", "zh")}
    if lang == "zh":
        flat.pop("wpm", None)
    per = v.get(lang) if isinstance(v.get(lang), dict) else {}
    return {**flat, **per}


def length_target(a, lang, pace):
    """-> (lo, hi, label, profile|None) in words (en) or 字 (zh)."""
    if a.platform:
        from vstudio import platform as P
        p = P.profile(a.platform)
        lo_s, hi_s = p.length.get("sweet") or (0, p.length.get("max") or 600)
        lab = f"{p.key} sweet spot {lo_s}-{hi_s}s, max {p.length.get('max')}s"
        return round(lo_s * pace / 60), round(hi_s * pace / 60), lab, p
    fmt = a.format or "short"
    if lang == "en":
        lo, hi = TARGETS[fmt]
    else:
        lo, hi = (round(s * pace / 60) for s in FORMAT_SECS[fmt])
    return lo, hi, fmt, None


def platform_checks(p, secs, errs, warns):
    mx = p.length.get("max")
    from vstudio import platform as P
    for w in P.check_length(p, secs):
        (errs if mx and secs > mx else warns).append(w)


def lint_en(a, text, v, errs, warns):
    wpm = float(v.get("wpm", 165))
    avoid = [p.lower() for p in v.get("phrases_avoid", [])]
    rules = " ".join(v.get("rules", [])).lower()
    tl = text.lower()
    sents = sentences(text)

    if "—" in text or "–" in text or " -- " in text:
        errs.append(f"em/en-dash x{text.count('—') + text.count('–') + text.count(' -- ')}: use a period or comma")
    if "parenthes" in rules and re.search(r"[()（）]", text):
        errs.append("parentheses in spoken lines (persona voice.rules)")
    first = " ".join(sents[:1]).lower()
    for p in find_any(first, OPENERS):
        errs.append(f"creator-trope opener: '{p}'")
    if re.match(r"^(so|alright|ok|okay|well)\b", first):
        errs.append("throat-clearing word before the first sentence")
    tail = " ".join(sents[-3:]).lower()
    for p in find_any(tail, CTAS):
        errs.append(f"generic CTA in closing: '{p}'")
    for label, lst in (("authority framing", AUTHORITY), ("AI-tell word", AI_TELL), ("meta/navigation", META),
                       ("persona voice.phrases_avoid", avoid)):
        for p in find_any(tl, lst):
            errs.append(f"{label}: '{p}'")
    if any(0x1F300 <= ord(c) <= 0x1FAFF for c in text):
        errs.append("emoji in spoken script")

    lens = []
    for s in sents:
        n = len(s.split()); lens.append(n)
        if n > 25:
            warns.append(f"{n}-word sentence (split it): {s[:70]}…")
        elif n <= 3 and not s.endswith("?"):
            warns.append(f"possible fragment: '{s}'")
    for m in re.finditer(r"(?<![\d.,])\b([1-9])\b(?![\d.,%])", text):
        warns.append(f"digit '{m.group(1)}' under 10: spell it out for speech"); break
    if not find_any(tl, SIGNPOSTS + [p.lower() for p in v.get("signposts", [])]):
        warns.append("no insight signpost found (every script needs one signposted reframe paragraph)")

    words = len(re.findall(r"[A-Za-z0-9']+", text)) + len(re.findall(r"[一-鿿]", text)) // 2
    lo, hi, label, prof = length_target(a, "en", wpm)
    secs = words / wpm * 60
    avg = sum(lens) / len(lens) if lens else 0
    print(f"{words} words ≈ {secs:.0f}s at {wpm:.0f} wpm (target {lo}-{hi} words for {label}); "
          f"{len(sents)} sentences, avg {avg:.1f} words")
    if prof:
        platform_checks(prof, secs, errs, warns)
    elif not lo <= words <= hi:
        warns.append(f"word count {words} outside {label} target {lo}-{hi}")
    if avg and not 8 <= avg <= 20:
        warns.append(f"average sentence length {avg:.1f} (aim 12-18)")


def lint_zh(a, text, v, errs, warns):
    cpm = float(v.get("cpm") or v.get("wpm") or ZH_CPM)       # voice.zh.wpm accepted as 字/min too
    avoid = list(v.get("phrases_avoid", []))
    rules = " ".join(v.get("rules", [])).lower()
    sents = zh_sentences(text)

    n_dash = len(re.findall(r"[—–]+| -- ", text))                # —— counts once
    if n_dash:
        errs.append(f"破折号/em-dash x{n_dash}: 用句号或逗号")
    if ("parenthes" in rules or "括号" in rules) and re.search(r"[()（）]", text):
        errs.append("parentheses in spoken lines (persona voice.rules)")
    first = sents[0] if sents else ""
    for p in find_zh(first, ZH_OPENERS):
        errs.append(f"口播套路开头 trope opener: '{p}'")
    if re.match(ZH_THROAT, first):
        errs.append("throat-clearing word before the first sentence")
    tail = "".join(sents[-3:])
    for p in find_zh(tail, ZH_CTAS):
        errs.append(f"generic CTA in closing: '{p}'")
    for label, lst in (("authority framing", ZH_AUTHORITY), ("AI-tell word", ZH_AI_TELL), ("meta/navigation", ZH_META),
                       ("persona voice.phrases_avoid", avoid)):
        for p in find_zh(text, lst):
            errs.append(f"{label}: '{p}'")
    if any(0x1F300 <= ord(c) <= 0x1FAFF for c in text):
        errs.append("emoji in spoken script")

    lens = []
    for s in sents:
        n = zh_units(s); lens.append(n)
        if n > ZH_SENT_MAX:
            warns.append(f"{n}-字 sentence (split it at a breath): {s[:30]}…")
    if not find_zh(text, ZH_SIGNPOSTS + list(v.get("signposts", []))):
        warns.append("no insight signpost found (every script needs one signposted reframe paragraph)")

    chars = zh_units(text)
    lo, hi, label, prof = length_target(a, "zh", cpm)
    secs = chars / cpm * 60
    avg = sum(lens) / len(lens) if lens else 0
    print(f"{chars} 字 ≈ {secs:.0f}s at {cpm:.0f} 字/min (target {lo}-{hi} 字 for {label}); "
          f"{len(sents)} sentences, avg {avg:.1f} 字")
    if prof:
        platform_checks(prof, secs, errs, warns)
    elif not lo <= chars <= hi:
        warns.append(f"length {chars} 字 outside {label} target {lo}-{hi}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--format", choices=list(TARGETS), default=None,
                    help="classic length target (default short); ignored for length when --platform is given")
    ap.add_argument("--platform", help="xiaohongshu | douyin | tiktok | youtube | youtube-shorts | bilibili "
                    "(optionally :orientation); length target = profile.length.sweet x pace; wins over --format")
    ap.add_argument("--lang", choices=["auto", "en", "zh"], default="auto",
                    help="script language -> voice.<lang> profile and rule set (default: auto-detect)")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    text = spoken_text(pathlib.Path(a.script).read_text(encoding="utf-8"))
    lang = detect_lang(text) if a.lang == "auto" else a.lang
    if a.platform:
        from vstudio import platform as P
        try:
            P.profile(a.platform)
        except KeyError as e:
            ap.error(str(e))
        if a.format:
            print(f"note: --platform {a.platform} sets the length target; --format {a.format} ignored for length")
    v = voice_for(lang)
    errs, warns = [], []
    (lint_zh if lang == "zh" else lint_en)(a, text, v, errs, warns)

    for e in errs:
        print("ERROR ", e)
    for w in warns:
        print("warn  ", w)
    if not errs and not warns:
        print("clean")
    sys.exit(1 if (a.strict and errs) else 0)


if __name__ == "__main__":
    main()
