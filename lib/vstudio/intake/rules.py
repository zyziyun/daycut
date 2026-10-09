"""Rule-based intake: the SKILL.md phrase table + material heuristics, no model needed.

    intent = parse_prompt("把这节课切成 20 条竖屏，发小红书")
    projects = rule_projects(intent, analysis, ctx)      # draft sub-projects (normalised / validated by plan.py)

Also the follow-up edits ``revise_rules(plan, "只要小红书")`` for when no model is routed.
"""
import copy
import os
import re

from vstudio import messages as MSG

from . import docs as D
from . import inventory as I

# --------------------------------------------------------------------------- phrase table (SKILL.md section 1)
# (recipe, phrases, weight). Longer / more specific phrases first; weights break ties between recipes.
PHRASES = [
    ("ai-video", ["ai短剧", "ai 短剧", "短剧", "aigc", "ai生成", "ai 生成", "可灵", "即梦", "seedance", "海螺", "定妆照", "分镜prompt",
                  "积分", "连载"], 3),
    ("explainer", ["讲解视频", "讲解短视频", "讲解", "3b1b", "3blue1brown", "解释一个概念", "原理讲解", "科普", "explainer"], 2),
    ("lesson-clips", ["切成知识点", "按知识点", "知识点切片", "知识点", "教学点", "今日短语", "每日短语", "每个短语", "学习笔记",
                      "单词卡", "knowledge point", "knowledge-point", "teaching point", "today's phrase", "study notes",
                      "phrase of the day", "vocab clips"], 3),
    ("interview-qa", ["问答切片", "一问一答", "问答", "q&a", "q & a", "qa clips", "question and answer",
                      "questions and answers", "提问和回答"], 3),
    ("longform-course", ["剪成课程", "做成课程", "课程视频", "上课实录", "教学长视频", "完整课程", "剪成一节课"], 3),
    ("longform-to-short", ["切片", "切成", "分几集", "分集", "竖屏切片", "长视频切", "拆成", "拆条", "剪成多条", "批量切"], 2),
    ("call-clips", ["播客切", "访谈切", "对话切", "采访切", "podcast", "播客", "对话", "访谈", "采访", "嘉宾", "遮脸", "打码", "放个小猫", "三人同框", "zoom", "会议", "连麦"], 2),
    ("photo-story", ["文艺片", "看展", "照片做成", "照片和视频", "胶片感", "双语字幕故事", "照片故事", "配旁白", "photo story"], 2),
    ("vlog", ["vlog", "旅游", "旅行", "卡点", "快节奏", "无人机", "dji", "调色", "转场"], 2),
    ("launch-kit", ["发布视频", "上线视频", "产品发布", "更新视频", "版本更新", "演示视频", "更新日志", "launch video",
                    "launch kit", "launch-kit", "product hunt", "release video", "changelog", "release notes",
                    "demo video", "update video"], 3),
    ("promo-recut", ["宣传", "左右分栏", "分屏", "截图放进去", "高亮这句", "定格", "插一段精选", "精选插片", "promo"], 2),
    ("polish", ["收尾", "第一帧黑", "响度", "导出后", "descript", "capcut", "剪映导出"], 2),
    ("cover", ["做封面", "封面", "缩略图", "thumbnail"], 1),
    ("slides", ["幻灯片", "slides", "做ppt", "做 ppt"], 2),
    ("preproduction", ["写稿", "口播稿", "写脚本", "脚本", "发音练习", "跟读", "shadowing", "口播脚本"], 2),
    ("talkinghead", ["口播", "复盘", "合并剪辑", "二次剪辑", "精剪", "剪干净", "去气口", "去嗯啊", "加 hook", "加hook", "高光预告",
                     "快剪", "进度条", "气泡", "记笔记", "修图", "美颜", "瘦脸"], 1),
]
EXTRACT = re.compile(r"剪出来|截取|截出|挑出|摘出|单独(剪|发|拿)|有意思的(部分|片段|地方)|精彩(片段|部分)|高光片段|把.{1,30}(部分|片段|内容|那段|几段)")
POSITIONS = [("前面", (0.0, 0.4)), ("开头", (0.0, 0.3)), ("前半", (0.0, 0.5)), ("中间", (0.25, 0.75)),
             ("后半", (0.5, 1.0)), ("后面", (0.55, 1.0)), ("最后", (0.7, 1.0)), ("结尾", (0.75, 1.0))]
PLATFORM_WORDS = [("小红书", "xiaohongshu"), ("红书", "xiaohongshu"), ("xhs", "xiaohongshu"), ("xiaohongshu", "xiaohongshu"),
                  ("rednote", "xiaohongshu"), ("抖音", "douyin"),
                  ("douyin", "douyin"), ("tiktok", "tiktok"), ("youtube shorts", "youtube-shorts"),
                  ("shorts", "youtube-shorts"), ("油管", "youtube"), ("youtube", "youtube"), ("b站", "bilibili"),
                  ("bilibili", "bilibili"), ("哔哩", "bilibili"), ("视频号", "wechat-channels"),
                  ("wechat channels", "wechat-channels"), ("instagram", "instagram"), ("reels", "instagram"),
                  ("twitter", "x"), ("推特", "x"), ("x.com", "x")]
UNSUPPORTED_PLATFORMS = [("快手", "快手")]
# short names that are only platform names as a whole token: "ins" / "ig" -> Instagram, "x" -> X (not "1.2x")
TOKEN_PLATFORMS = {"ins": "instagram", "ig": "instagram", "insta": "instagram", "x": "x"}
NUM = r"(\d+|[一二两三四五六七八九十百]+)"


def _num(s):
    return D.cn_num(s)


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def recipe_scores(text):
    """{recipe: score} from the phrase table (longest phrase wins within a recipe)."""
    t = _norm(text)
    out = {}
    for rid, phrases, w in PHRASES:
        hits = [p for p in phrases if p in t]
        if hits:
            out[rid] = out.get(rid, 0) + w * (1 + 0.1 * max(len(h) for h in hits)) + 0.2 * (len(hits) - 1)
    return out


def clauses(text):
    """Split a request into clauses that may each name a deliverable ("…切成 20 条，另外用 PDF 做 5 条讲解")."""
    parts = re.split(r"[；;。\n]|，?(?:另外|还有|再|同时|以及|然后|并且|plus|and also)(?=[^的]{2})", text or "")
    return [p.strip(" ，,") for p in parts if p and p.strip(" ，,")]


def negations(text):
    """'不要讲解视频' / '别做封面' / 'no explainer' -> recipes excluded."""
    out = set()
    for m in re.finditer(r"(?:不要|别做|不做|去掉|不需要|no)\s*([^，,。；;]{1,12})", _norm(text)):
        frag = m.group(1)
        out |= set(recipe_scores(frag))
    return out


def platforms_of(text):
    """Platforms named in a request, in the platform registry's display order (international first, then Chinese,
    then the rest; ``vstudio.platform.ordered``), whatever order the request names them in."""
    from vstudio.platform import ordered
    t = _norm(text)
    out = []
    for w, p in PLATFORM_WORDS:
        if w in t and p not in out:
            if p == "youtube" and "youtube-shorts" in out and "shorts" in t and t.count("youtube") <= 1:
                continue
            out.append(p)
    toks = re.findall(r"[a-z0-9.]+|[^\sa-z0-9.]", t)
    for i, tok in enumerate(toks):
        p = TOKEN_PLATFORMS.get(tok)
        prev = toks[i - 1] if i else ""
        if p and p not in out and not (tok == "x" and re.fullmatch(r"[0-9.]+", prev or "")):
            out.append(p)
    unsup = [name for w, name in UNSUPPORTED_PLATFORMS if w in t]
    return ordered(out), unsup


def parse_prompt(text):
    """Natural-language request -> intent dict (what the rule planner and the summary need)."""
    t = _norm(text)
    plats, unsup = platforms_of(text)
    intent = dict(text=text, scores=recipe_scores(text), clauses=[], extract=bool(EXTRACT.search(text or "")),
                  platforms=plats, unsupported_platforms=unsup, exclude=sorted(negations(text)))
    for c in clauses(text):
        intent["clauses"].append(dict(text=c, scores=recipe_scores(c), count=_count(c)))
    intent["count"] = _count(text)
    m = re.search(rf"第?\s*{NUM}\s*季", text or "")
    if m:
        intent["season"] = _num(m.group(1))
    m = re.search(rf"{NUM}\s*集", text or "")
    if m:
        intent["episodes"] = _num(m.group(1))
    m = re.search(rf"(?:每条|每个|每集|单条)?\s*{NUM}\s*(秒|s|分钟|min)\s*(?:内|以内|之内|左右|以下)?", t)
    if m and re.search(r"内|以内|之内|以下|不超过|左右|每条|每个|每集|时长|控制在", t):
        v = _num(m.group(1))
        if v:
            sec = v * 60 if m.group(2) in ("分钟", "min") else v
            if "左右" in t[m.start():m.end() + 2]:
                intent["target_s"] = sec
            else:
                intent["max_s"] = sec
    m = re.search(r"(\d(?:\.\d+)?)\s*(?:倍|x|×)", t)
    if m and 0.5 <= float(m.group(1)) <= 2.0:
        intent["speed"] = float(m.group(1))
    elif re.search(r"不加速|原速|不要加速", t):
        intent["speed"] = 1.0
    if re.search(r"竖屏|竖版|9:16|3:4|vertical", t):
        intent["orientation"] = "vertical"
    elif re.search(r"横屏|横版|16:9|horizontal", t):
        intent["orientation"] = "horizontal"
    if re.search(r"9:16|全屏|满屏", t):              # an explicit shape beats the persona's per-platform default
        intent["shape"] = "full"
    elif re.search(r"3:4|4:3竖", t):
        intent["shape"] = "vertical"
    if re.search(r"保留(原|旧)?字幕|不(要)?(加|换|重做)字幕|字幕不(要)?动", t):
        intent["keep_captions"] = True
    sub = subtitles_of(t)
    if sub:
        intent.update(sub)
    tl = SUB_LANG_RX.sub(" ", t)                      # "中英字幕" / "Chinese and English subtitles" name captions, not speech
    if re.search(r"英文|英语|english", tl):
        intent["language"] = "en"
    elif re.search(r"中文|普通话", tl):
        intent["language"] = "zh"
    if re.search(r"剪干净|狠一点|去干净|tight|严格", t):
        intent["cleanup"] = "tight" if re.search(r"狠|tight|严格", t) else "standard"
    elif re.search(r"轻一点|轻度|保留口癖|gentle", t):
        intent["cleanup"] = "gentle"
    if re.search(r"不(用|要)?遮脸|露脸也行|同意露脸|不打码|(?:don'?t|do not|no need to) (?:mask|hide|blur)|no (?:face )?masks?\b", t):
        intent["mask"] = False
    elif re.search(r"遮脸|打码|放个小猫|挡住脸|遮一下|(?:mask|hide|blur)\b[^,.;，。]{0,24}\bfaces?\b", t):
        intent["mask"] = True
    if re.search(r"卡点|快节奏|燃|动感", t):
        intent["style"] = "fun"
    elif re.search(r"舒缓|安静|慢节奏|治愈", t):
        intent["style"] = "calm"
    if re.search(r"纯音乐|只要音乐|不要旁白|音乐卡点", t):
        intent["narration"] = False
    elif re.search(r"旁白|配音|解说", t):
        intent["narration"] = True
    if re.search(r"不要\s*hook|不加\s*hook|不要开头预告", t):
        intent["hook"] = False
    elif re.search(r"加\s*hook|高光预告|冷开场", t):
        intent["hook"] = True
    if re.search(r"三人同框|三人", t):
        intent["trio"] = True
    intent["focus"] = focus_of(text) if intent["extract"] else []
    intent["positions"] = [dict(word=w, span=s) for w, s in POSITIONS if w in (text or "")]
    return intent


SUB_LANG_RX = re.compile(r"(?:中英(?:文)?|英中|中文和英文|英文和中文|双语|chinese\s*(?:and|&|/|\+)\s*english|"
                         r"english\s*(?:and|&|/|\+)\s*chinese|bilingual|中文|英文|chinese|english)\s*(?:双语)?"
                         r"(?:的)?\s*(?:字幕|subtitles?|captions?|subs)", re.I)


def subtitles_of(t):
    """Caption language wishes -> {subtitles: mono|bilingual|translated, subtitle_lang?}."""
    t = (t or "").lower()
    if re.search(r"只要(?:中文|英文)?(?:翻译|译文)(?:字幕)?|只(?:要|放)(?:中文|英文)字幕|(?:translated|translation)[- ]only|"
                 r"only (?:the )?(?:chinese|english) (?:subtitles|captions)|(?:subtitles|captions) only in (?:chinese|english)", t):
        out = dict(subtitles="translated")
        m = re.search(r"中文|chinese", t)
        if m:
            out["subtitle_lang"] = "zh"
        elif re.search(r"英文|english", t):
            out["subtitle_lang"] = "en"
        return out
    if re.search(r"中英|英中|双语|bilingual|chinese\s*(?:and|&|/|\+)\s*english|english\s*(?:and|&|/|\+)\s*chinese|"
                 r"中文和英文|英文和中文|两种语言", t):
        return dict(subtitles="bilingual")
    if re.search(r"不要翻译|不用翻译|只要原文字幕|no translation|source[- ]language only", t):
        return dict(subtitles="mono")
    return {}


def _count(text):
    m = re.search(rf"{NUM}\s*(条|个|段|支|篇|期)", text or "")
    return _num(m.group(1)) if m else None


FOCUS_RX = [re.compile(r"(?:对于|关于|讲|聊|说)([^，,。；;、]{1,16}?)的(思考|想法|看法|观点|部分|内容|经验|感悟|故事|建议|分析|总结)"),
            re.compile(r"([^，,。；;、把将]{1,12}?)的(思考|想法|看法|观点|感悟|故事|经验|建议|部分|片段|内容)"),
            re.compile(r"(感悟|心得|金句|干货|故事|观点|建议|吐槽|彩蛋)")]
STOP_FOCUS = {"一些", "有些", "其中", "后面", "前面", "中间", "开头", "最后", "结尾", "后半", "前半", "里面", "这段", "那段", "有意思",
              "比较", "这个", "那个", "这些", "那些", "部分", "剪", "出来", "他", "她", "我", "我们", "嘉宾", "单独"}


def focus_of(text):
    """'把后面对于自媒体的思考，以及中间的一些感悟剪出来' -> [{topic: 自媒体的思考, terms: [自媒体], where: 后面},
    {topic: 感悟, terms: [感悟], where: 中间}]."""
    out = []
    for c in re.split(r"[，,；;。]|以及|还有|和(?=中间|后面|前面|开头|最后)", text or ""):
        c = c.strip()
        if not c:
            continue
        where = next((w for w, _ in POSITIONS if w in c), None)
        terms, topic = [], None
        for rx in FOCUS_RX:
            m = rx.search(c)
            if not m:
                continue
            g = [x for x in m.groups() if x]
            head = re.sub(r"^(把|将|对|我|在|从|中间|后面|前面|开头|最后|结尾|的|一些|其中)+", "", g[0])
            head = re.sub(r"(的|里|中)$", "", head)
            if head and head not in STOP_FOCUS:
                terms.append(head)
            if len(g) > 1 and g[1] not in ("部分", "片段", "内容"):
                terms.append(g[1])
            topic = "".join(g) if len(g) > 1 else g[0]
            topic = re.sub(r"^(把|将|对于|关于|后面|前面|中间|开头|最后|一些)+", "", topic)
            break
        if terms:
            out.append(dict(topic=topic, terms=list(dict.fromkeys(terms)), where=where))
    return out


# --------------------------------------------------------------------------- focus ranges from a transcript
GENERIC_TERMS = {
    "感悟": ["感悟", "体会", "觉得", "意识到", "发现", "其实", "我想说", "最大的", "学到", "反思", "成长", "心态", "认知"],
    "思考": ["思考", "我觉得", "我认为", "想法", "其实", "本质", "核心", "逻辑", "判断"],
    "故事": ["当时", "那时候", "有一次", "后来", "记得"],
    "建议": ["建议", "推荐", "一定要", "千万", "不要", "应该"],
    "金句": ["其实", "本质", "所以", "一定"],
    "干货": ["方法", "步骤", "第一", "第二", "技巧", "工具"],
}


def _terms_for(focus):
    out = []
    for t in focus.get("terms") or []:
        out.append((t, 3.0))
        for k, extra in GENERIC_TERMS.items():
            if k in t:
                out += [(e, 1.0) for e in extra]
    return out


def focus_ranges(sentences, duration, focus_list, count=None, min_s=20.0, max_s=150.0, target_s=None):
    """Rule-based: score sentence windows by focus terms (and the position words), return ranges
    [{start, end, title, focus, score, why}] - one or more per focus, at most ``count`` overall."""
    if not sentences or not focus_list:
        return []
    duration = duration or sentences[-1]["te"]
    picks = []
    per = max(1, (count or len(focus_list) * 2) // max(1, len(focus_list))) if count else None
    for f in focus_list:
        span = dict(POSITIONS).get(f.get("where")) if f.get("where") else (0.0, 1.0)
        lo, hi = span[0] * duration, span[1] * duration
        terms = _terms_for(f)
        sc = []
        for k, s in enumerate(sentences):
            if s["te"] < lo or s["t"] > hi:
                sc.append(0.0)
                continue
            v = sum(w * s["text"].count(t) for t, w in terms)
            sc.append(v)
        if not any(sc):
            continue
        # grow windows around the best-scoring sentences
        order = sorted(range(len(sc)), key=lambda k: -sc[k])
        used = set()
        n_here = per or (2 if f.get("where") else 1)
        want = target_s or min(max_s, max(min_s, 60.0))
        for k in order:
            if sc[k] <= 0 or len([p for p in picks if p["focus"] == f["topic"]]) >= n_here:
                break
            if k in used:
                continue
            a = b = k
            while sentences[b]["te"] - sentences[a]["t"] < want:
                left = sc[a - 1] if a > 0 and (a - 1) not in used and sentences[a - 1]["t"] >= lo else -1
                right = sc[b + 1] if b + 1 < len(sentences) and (b + 1) not in used and sentences[b + 1]["te"] <= hi else -1
                if left < 0 and right < 0:
                    break
                if right >= left:
                    b += 1
                else:
                    a -= 1
                if sentences[b]["te"] - sentences[a]["t"] > max_s:
                    break
            if sentences[b]["te"] - sentences[a]["t"] < min(min_s, 0.5 * want):
                continue
            used |= set(range(a, b + 1))
            txt = "".join(sentences[x]["text"] for x in range(a, b + 1))
            picks.append(dict(start=round(sentences[a]["t"], 2), end=round(sentences[b]["te"], 2),
                              title=_title_from(txt, f), focus=f["topic"], score=round(sum(sc[a:b + 1]), 1),
                              why=f"关键词命中：{'、'.join(t for t, w in terms if w >= 3)}"))
    picks.sort(key=lambda p: p["start"])
    if count and len(picks) > count:
        keep = sorted(sorted(picks, key=lambda p: -p["score"])[:count], key=lambda p: p["start"])
        picks = keep
    return picks


def _title_from(text, focus):
    t = re.sub(r"[，。！？,.!?]", " ", text).split()
    first = next((x for x in t if 6 <= len(x) <= 18), (t[0] if t else focus.get("topic") or ""))
    return first[:18]


# --------------------------------------------------------------------------- material helpers
def roles(analysis):
    return {f["id"]: I.material_role(f) for f in analysis["files"]}


def _files(analysis, *rs):
    rmap = roles(analysis)
    return [f for f in analysis["files"] if rmap[f["id"]] in rs]


def _by_kind(analysis, kind):
    return [f for f in analysis["files"] if f["kind"] == kind]


# --------------------------------------------------------------------------- rule planner
def choose_recipes(intent, analysis):
    """-> [(recipe, clause or None)] in request order. Phrases first (per clause), then the materials."""
    rmap = roles(analysis)
    present = set(rmap.values())
    excl = set(intent.get("exclude") or [])
    out = []
    for c in intent["clauses"] or [dict(text=intent["text"], scores=intent["scores"], count=intent.get("count"))]:
        sc = {r: v for r, v in c["scores"].items() if r not in excl}
        if not sc:
            continue
        r = _resolve(max(sc, key=sc.get), sc, intent, present, c)
        if r and r not in [x for x, _ in out]:
            out.append((r, c))
    if intent["extract"] and not any(r in ("talkinghead", "longform-to-short", "call-clips", "lesson-clips",
                                           "interview-qa") for r, _ in out):
        r = _extract_recipe(present)
        if r and r not in excl:
            out = [x for x in out if x[0] != "talkinghead"]
            out.insert(0, (r, dict(text=intent["text"], scores={}, count=intent.get("count"))))
    if not out:                                     # nothing named: one project per material family
        out = [(r, None) for r in material_recipes(analysis) if r not in excl]
    return out


def _extract_recipe(present):
    if "call" in present:
        return "call-clips"
    if "lecture" in present or "screen-recording" in present:
        return "longform-to-short"
    if present & {"finished-edit", "talking-head"}:
        return "talkinghead"
    return None


def _resolve(r, sc, intent, present, clause):
    """Phrase winner + materials -> the recipe (e.g. 切 + a finished horizontal 口播 -> talkinghead ranges)."""
    text = clause["text"]
    if r == "talkinghead" and intent["extract"]:
        return _extract_recipe(present) or r
    if r == "longform-to-short" and "call" in present and not ("lecture" in present or "screen-recording" in present):
        return "call-clips"
    if r == "explainer" and not (present & {"doc", "slides", "notes", "script"}) and "讲解" not in text:
        return r
    if r == "photo-story" and "photo" not in present and "footage" in present:
        return "vlog"
    if r == "vlog" and "photo" in present and "footage" not in present:
        return "photo-story"
    if r == "preproduction" and re.search(r"剧本", text) and "短剧" in text:
        return "ai-video"
    return r


def material_recipes(analysis):
    rmap = roles(analysis)
    present = list(dict.fromkeys(rmap.values()))
    out = []
    has = set(present)
    for role in present:
        r = {"call": "call-clips", "lecture": "longform-to-short", "screen-recording": "longform-to-short",
             "talking-head": "talkinghead", "finished-edit": "polish", "script": "ai-video", "slides": "explainer",
             "doc": "explainer", "notes": "preproduction", "podcast-audio": None, "voice": None,
             "subtitles": None, "music": None, "other": None}.get(role)
        if role in ("photo", "footage"):
            r = "photo-story" if "photo" in has and (len(_by_kind(analysis, "image")) >= len(_files(analysis, "footage"))) \
                else "vlog"
        if r and r not in out:
            out.append(r)
    return out


EDU_SOURCE = {"lesson-clips": ("lecture", "screen-recording", "talking-head", "finished-edit", "call"),
              "interview-qa": ("call", "talking-head", "lecture", "screen-recording", "finished-edit")}
FILE_INPUT = {"talkinghead": ("video", ("talking-head", "finished-edit")),
              "polish": ("video", ("finished-edit", "talking-head")),
              "cover": ("video", ("finished-edit", "talking-head")),
              "promo-recut": ("talk", ("talking-head", "finished-edit")),
              "longform-course": ("source", ("lecture", "screen-recording", "talking-head"))}


def _screen_and_camera(analysis, used=()):
    """(screen share, camera) of the same session: the longest screen recording + the talking-head video whose
    length is closest to it (within 25 %); None when the materials are not such a pair."""
    vids = [f for f in _by_kind(analysis, "video") if f["id"] not in used]
    screens = [f for f in vids if f.get("screen_share")]
    cams = [f for f in vids if f.get("talking_head") and not f.get("screen_share")]
    if not screens or not cams:
        return None
    src = max(screens, key=lambda f: f.get("duration") or 0)
    d = src.get("duration") or 0
    cam = min(cams, key=lambda f: abs((f.get("duration") or 0) - d))
    if d and not (0.8 <= (cam.get("duration") or 0) / d <= 1.25):
        return None
    return src, cam


def _pick_source(analysis, prefs):
    for r in prefs:
        fs = _files(analysis, r)
        if fs:
            return max(fs, key=lambda f: f.get("duration") or 0)
    return None


def rule_projects(intent, analysis, ctx):
    """-> (projects, questions, risks): draft projects in the plan's project shape (before validation)."""
    projects, questions, risks = [], [], []
    L = ctx.get("ui_lang") or "zh"                      # the language the plan card is read in (en | zh | fr)
    mask_opts = [MSG.cs(f"intake.option.mask.{k}", L) for k in ("all-but-me", "none", "pick")]
    narr_opts = [MSG.cs(f"intake.option.narration.{k}", L) for k in ("voice", "music")]
    rmap = roles(analysis)
    used = set()
    chosen = choose_recipes(intent, analysis)
    for rid, clause in chosen:
        p = dict(recipe=rid, materials=[], inputs={}, items={}, params={}, why="")
        ctext = (clause or {}).get("text") or ""
        cnt = (clause or {}).get("count") or (intent.get("count") if len(chosen) == 1 else None)
        if rid in EDU_SOURCE:
            src, cam = _pick_source(analysis, EDU_SOURCE[rid]), None
            if rid == "lesson-clips":                  # a screen share + a camera of the same lesson: one project
                src, cam = _screen_and_camera(analysis, used) or (src, None)
            if not src:
                risks.append(MSG.cs("intake.risk.no-source", L, recipe=rid))
                continue
            p["materials"] = [src["id"]]
            p["inputs"] = {"source": [src["path"]]}
            used.add(src["id"])
            if cam:
                p["inputs"]["camera"] = cam["path"]
                p["materials"].append(cam["id"])
                used.add(cam["id"])
                p["params"]["layout"] = "pip"
            if rid == "interview-qa":
                if intent.get("mask") is True:
                    p["params"]["mask"] = "sticker"
                elif intent.get("mask") is None:
                    questions.append(dict(project=len(projects), text=MSG.cs("intake.question.mask-faces", L),
                                          options=mask_opts, default=mask_opts[0]))
            if cnt:
                p["params"]["count"] = cnt
            p["items"] = dict(method="per-file", count=1)
            what = "按知识点切段 + 回顾 + 学习笔记" if rid == "lesson-clips" else "按一问一答切段"
            p["why"] = f"{src['rel']}（{_fmt_dur(src.get('duration'))}，{_role_zh(rmap[src['id']])}）→ {what}" + \
                ("（加摄像头画中画）" if p["inputs"].get("camera") else "")
        elif rid in ("longform-to-short", "call-clips"):
            prefs = ("call",) if rid == "call-clips" else ("lecture", "screen-recording", "talking-head", "finished-edit", "call")
            src = _pick_source(analysis, prefs) or _pick_source(analysis, ("talking-head", "finished-edit", "lecture",
                                                                             "screen-recording", "call"))
            if not src:
                risks.append(MSG.cs("intake.risk.no-source", L, recipe=rid))
                continue
            p["materials"] = [src["id"]]
            p["inputs"] = {"source": src["path"]}
            used.add(src["id"])
            if rid == "longform-to-short":
                p["params"]["layout_mode"] = "split" if src.get("screen_share") else "reframe"
                if src.get("burned_captions"):
                    risks.append(MSG.cs("intake.risk.burned-longform", L, file=src["rel"]))
            if rid == "call-clips":
                if intent.get("mask") is False:
                    p["params"]["no_mask"] = True
                if intent.get("trio"):
                    p["params"]["renderer"] = "render_trio.py"
                if intent.get("mask") is not False:
                    questions.append(dict(project=len(projects), text=MSG.cs("intake.question.mask-faces", L),
                                          options=mask_opts, default=mask_opts[0]))
            p["why"] = f"{src['rel']}（{_fmt_dur(src.get('duration'))}，{_role_zh(rmap[src['id']])}）→ {'选段' if not intent['extract'] else '按你说的内容截取'}"
            p["items"] = dict(method="focus" if intent["extract"] and intent.get("focus") else "planner", count=cnt,
                              focus=_focus_text(intent))
            if intent.get("max_s"):
                p["params"]["max_s"] = intent["max_s"]
                p["params"]["min_s"] = min(p["params"].get("min_s", 30), max(10, intent["max_s"] // 2))
            if cnt:
                p["params"]["count"] = cnt
        elif rid in FILE_INPUT:
            key, prefs = FILE_INPUT[rid]
            fs = [f for f in analysis["files"] if rmap[f["id"]] in prefs and f["id"] not in used]
            if not fs:
                fs = [f for f in _by_kind(analysis, "video") if f["id"] not in used]
            if not fs:
                risks.append(MSG.cs("intake.risk.no-video", L, recipe=rid))
                continue
            if rid == "longform-course":
                fs = fs[:8]
            used |= {f["id"] for f in fs}
            p["materials"] = [f["id"] for f in fs]
            p["inputs"] = {key: [f["path"] for f in fs]}
            if rid == "talkinghead" and intent["extract"]:
                p["items"] = dict(method="focus", count=cnt, focus=_focus_text(intent))
                src = fs[0]
                p["materials"] = [src["id"]]
                p["inputs"] = {key: [src["path"]]}
                if src.get("burned_captions"):
                    p["params"].update(cleanup_profile="gentle", speed=1.0)   # layout: plan._burned_defaults
                p["why"] = f"从 {src['rel']}（{_fmt_dur(src.get('duration'))}）里截出你说的内容，每段一条"
            else:
                p["items"] = dict(method="per-file", count=len(fs))
                p["why"] = f"{len(fs)} 条{_role_zh(rmap[fs[0]['id']])}，每条一个视频"
        elif rid in ("explainer", "preproduction", "slides"):
            docs = [f for f in analysis["files"] if rmap[f["id"]] in ("doc", "slides", "notes", "script") and f["id"] not in used]
            if rid == "explainer":
                docs = [f for f in docs if rmap[f["id"]] in ("doc", "slides")] or docs
            if rid == "preproduction":
                docs = [f for f in docs if rmap[f["id"]] in ("notes", "doc")] or docs
            n = cnt
            rows = []
            if docs:
                used |= {f["id"] for f in docs}
                p["materials"] = [f["id"] for f in docs]
                heads = [(f, h) for f in docs for h in (f.get("headings") or [])]
                if rid == "preproduction" and not cnt:
                    rows = [dict(id=None, inputs=_doc_input(rid, f), params=dict(title=f.get("title") or "")) for f in docs]
                else:
                    n = n or max(1, min(10, len(heads) or len(docs)))
                    src = heads[:n] if len(heads) >= n else heads + [(docs[k % len(docs)], None) for k in range(n - len(heads))]
                    for k, (f, h) in enumerate(src[:n]):
                        topic = f"{h or f.get('title') or os.path.basename(f['path'])}（素材：{os.path.basename(f['path'])}" + \
                                (f"，第 {k + 1} 部分" if not h else "") + "）"
                        rows.append(dict(id=f"{k + 1:02d}", inputs={"topic": topic}, params=dict(title=(h or f.get("title") or "")[:30])))
            elif ctext:
                rows = [dict(id=f"{k + 1:02d}", inputs={"topic": ctext}, params={}) for k in range(n or 1)]
            p["items"] = dict(method="list", count=len(rows), rows=rows)
            if rid == "explainer":
                p["params"]["mode"] = "short" if (intent.get("orientation") == "vertical" or "短" in ctext or
                                                  set(intent.get("platforms") or []) & {"xiaohongshu", "douyin", "tiktok",
                                                                                        "youtube-shorts"}) else "long"
            p["why"] = (f"用 {len(docs)} 份文档做 {len(rows)} 条" if docs else f"{len(rows)} 条") + \
                {"explainer": "讲解视频", "preproduction": "口播稿", "slides": "幻灯片"}[rid]
        elif rid == "ai-video":
            scripts = [f for f in analysis["files"] if rmap[f["id"]] in ("script", "doc", "notes") and f["id"] not in used]
            n = intent.get("episodes") or cnt or (scripts[0].get("episodes") if scripts else None) or 1
            refs = [f for f in _by_kind(analysis, "image") if f["id"] not in used]
            if refs:
                p["inputs"]["refs"] = [f["path"] for f in refs]
            used |= {f["id"] for f in scripts + refs}
            p["materials"] = [f["id"] for f in scripts + refs]
            base = os.path.basename(scripts[0]["path"]) if scripts else None
            p["items"] = dict(method="episodes", count=n, rows=[
                dict(id=f"ep{k + 1:02d}", inputs={"premise": f"第 {k + 1} 集" + (f"（剧本：{base}）" if base else "")},
                     params=dict(title=f"第{k + 1}集")) for k in range(n)])
            p["why"] = f"{'按剧本 ' + base if base else '按你的设定'}做 {n} 集 AI 短剧，生成前先锁剧本和预算"
            risks.append(MSG.cs("intake.risk.aigc-credits", L))
        elif rid == "launch-kit":
            notes = [f for f in analysis["files"] if rmap[f["id"]] in ("doc", "notes") and f["id"] not in used][:1]
            shots = [f for f in analysis["files"] if f["id"] not in used and f not in notes and
                     (rmap[f["id"]] == "screen-recording" or f.get("kind") == "image")]
            if notes:
                p["inputs"]["notes"] = notes[0]["path"]
            if shots:
                p["inputs"]["shots"] = [f["path"] for f in shots]
            used |= {f["id"] for f in notes + shots}
            p["materials"] = [f["id"] for f in notes + shots]
            p["items"] = dict(method="single", count=1)
            p["why"] = ("用 " + os.path.basename(notes[0]["path"]) + " 起草功能列表，" if notes else "") + \
                "录制产品操作，做演示视频、README 动图、功能短片、配图和文案"
        elif rid in ("photo-story", "vlog"):
            imgs = [f for f in _by_kind(analysis, "image") if f["id"] not in used]
            clips = [f for f in _by_kind(analysis, "video") if f["id"] not in used and rmap[f["id"]] in ("footage", "talking-head")]
            music = [f for f in _by_kind(analysis, "audio") if rmap[f["id"]] == "music"]
            if rid == "vlog" and not clips:
                risks.append(MSG.cs("intake.risk.no-video", L, recipe="vlog"))
                continue
            if rid == "photo-story" and not (imgs or clips):
                risks.append(MSG.cs("intake.risk.no-photos", L, recipe="photo-story"))
                continue
            used |= {f["id"] for f in imgs + clips + music[:1]}
            p["materials"] = [f["id"] for f in imgs + clips + music[:1]]
            if rid == "photo-story":
                if imgs:
                    p["inputs"]["photos"] = [f["path"] for f in imgs]
                if clips:
                    p["inputs"]["clips"] = [f["path"] for f in clips]
                if intent.get("narration") is False or (music and intent.get("narration") is not True):
                    p["params"]["mode"] = "music"
            else:
                p["inputs"]["footage"] = [f["path"] for f in clips]
                if imgs:
                    p["inputs"]["photos"] = [f["path"] for f in imgs]
                if intent.get("style"):
                    p["params"]["style"] = intent["style"]
            if music:
                p["inputs"]["music"] = music[0]["path"]
            p["items"] = dict(method="single", count=1)
            p["why"] = f"{len(imgs)} 张照片 + {len(clips)} 段视频" + ("（带配乐）" if music else "") + \
                ("做成一条文艺片" if rid == "photo-story" else "剪成一条 vlog")
            if rid == "photo-story" and p["params"].get("mode") != "music" and not music:
                questions.append(dict(project=len(projects), text=MSG.cs("intake.question.narration", L),
                                      options=narr_opts, default=narr_opts[0]))
        else:
            continue
        projects.append(p)
    return projects, questions, risks


def _doc_input(rid, f):
    ext = os.path.splitext(f["path"])[1].lower()
    if rid == "preproduction" and ext in (".md", ".txt"):
        return {"script": f["path"]}
    return {"topic": f"{f.get('title') or os.path.basename(f['path'])}（素材：{os.path.basename(f['path'])}）"}


def _focus_text(intent):
    fs = intent.get("focus") or []
    if not fs:
        return None
    return "；".join(f"{f.get('where') or ''}{f['topic']}" for f in fs)


def _fmt_dur(s):
    if not s:
        return "?"
    s = int(round(s))
    return f"{s // 3600}小时{s % 3600 // 60}分" if s >= 3600 else f"{s // 60}分{s % 60:02d}秒" if s >= 60 else f"{s}秒"


ROLE_ZH = {"call": "多人通话/播客录屏", "lecture": "长录播/课程", "screen-recording": "录屏", "talking-head": "口播素材",
           "finished-edit": "已剪成片", "footage": "空镜/素材", "podcast-audio": "播客音频", "voice": "人声音频", "music": "音乐",
           "photo": "照片", "script": "剧本", "slides": "幻灯片", "doc": "文档", "notes": "笔记", "subtitles": "字幕", "other": "其他"}


def _role_zh(r):
    return ROLE_ZH.get(r, r)


# --------------------------------------------------------------------------- follow-up edits (no model)
def revise_rules(plan, instruction):
    """Apply a follow-up instruction to a plan's projects with rules. -> (new projects, notes [what changed])."""
    projects = copy.deepcopy(plan["projects"])
    it = parse_prompt(instruction)
    notes = []
    t = _norm(instruction)
    excl = set(it.get("exclude") or [])
    if excl:
        keep = [p for p in projects if p["recipe"] not in excl]
        if len(keep) != len(projects):
            notes.append(f"去掉了 {len(projects) - len(keep)} 个子项目（{'、'.join(sorted(excl))}）")
        projects = keep
    only = re.search(r"只(要|发|做|保留)", t)
    if it["platforms"]:
        for p in projects:
            cur = p.get("params", {}).get("platforms") or []
            base = [x.split(":")[0] for x in cur]
            if only or not cur:
                p.setdefault("params", {})["platforms"] = list(it["platforms"])
            else:
                p.setdefault("params", {})["platforms"] = cur + [x for x in it["platforms"] if x not in base]
        notes.append(("只发 " if only else "平台加上 ") + "、".join(it["platforms"]))
    if it.get("max_s") or it.get("target_s"):
        mx = it.get("max_s") or it.get("target_s")
        for p in projects:
            pr = p.setdefault("params", {})
            if p["recipe"] in ("longform-to-short", "call-clips", "batch"):
                pr["max_s"] = mx
                pr["min_s"] = min(pr.get("min_s") or 30, max(10, int(mx * 0.5)))
            for r in (p.get("items") or {}).get("rows") or []:
                rng = (r.get("params") or {}).get("range")
                if rng and rng[1] - rng[0] > mx:
                    r.setdefault("notes", []).append(f"超过 {mx}s，需要在选段时收紧")
            p.setdefault("items", {})["max_s"] = mx
        notes.append(f"每条控制在 {mx} 秒内")
    if it.get("count") and not excl:
        for p in projects:
            items = p.setdefault("items", {})
            if items.get("method") in ("planner", "focus", "list", "episodes"):
                items["count"] = it["count"]
                if items.get("rows") and len(items["rows"]) > it["count"]:
                    items["rows"] = items["rows"][: it["count"]]
                if p["recipe"] in ("longform-to-short", "call-clips", "batch"):
                    p.setdefault("params", {})["count"] = it["count"]
        notes.append(f"条数改为 {it['count']}")
    for key, param, recipes in (("speed", "speed", None), ("language", "language", None),
                                ("cleanup", "cleanup_profile", None), ("style", "style", ("vlog",))):
        if it.get(key) is not None:
            for p in projects:
                if recipes and p["recipe"] not in recipes:
                    continue
                p.setdefault("params", {})[param] = it[key]
            notes.append(f"{param} = {it[key]}")
    if it.get("subtitles"):
        for p in projects:
            if p["recipe"] in EDU_SOURCE:
                p.setdefault("params", {})["subtitles"] = it["subtitles"]
                if it.get("subtitle_lang"):
                    p["params"]["subtitle_lang"] = it["subtitle_lang"]
        notes.append(f"字幕 = {it['subtitles']}")
    if it.get("mask") is not None:
        for p in projects:
            if p["recipe"] == "call-clips":
                p.setdefault("params", {})["no_mask"] = not it["mask"]
            if p["recipe"] in EDU_SOURCE:
                p.setdefault("params", {})["mask"] = "sticker" if it["mask"] else "off"
        notes.append("遮脸" if it["mask"] else "不遮脸")
    if it.get("hook") is not None:
        for p in projects:
            if p["recipe"] == "talkinghead":
                p.setdefault("params", {})["hook_default"] = 0 if it["hook"] else -1
        notes.append("加 hook" if it["hook"] else "不加 hook")
    if it.get("orientation"):
        for p in projects:
            pr = p.setdefault("params", {})
            if p["recipe"] == "promo-recut":
                pr["orientation"] = it["orientation"]
            if p["recipe"] == "explainer":
                pr["mode"] = "short" if it["orientation"] == "vertical" else "long"
            pr["_orientation"] = it["orientation"]
        notes.append("竖屏" if it["orientation"] == "vertical" else "横屏")
    return projects, notes
