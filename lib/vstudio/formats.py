"""Recurring formats: the defaults a creator would otherwise re-type at the start of every job.

A *format* is a kind of post the creator makes again and again (口播, a podcast / call cut into clips, a promo of
something she built, lecture slices, a voice-over vlog, an explainer, a photo story, an AI skit). Each one carries
the first-pass defaults learned from real jobs: speeds, whether hooks are offered or skipped, cleanup strength,
notes / progress bar, cover rules, series labels, captions, which tag set the post copy may use, guest privacy.

    from vstudio import formats
    f = formats.get("talking-head")            # defaults <- persona formats.talking-head
    formats.detect("这条口播帮我剪一下发小红书")  # -> "talking-head"
    formats.summary(f)                          # one line to state to the creator BEFORE the first render

    python -m vstudio.formats list | show talking-head | detect "播客切几条" [--json]

Precedence: these defaults < persona ``formats.<id>`` (persona.local.yaml) < what the creator says for this job.
State the summary line before starting so she never has to ask "加速了么" (it also names what is NOT done:
no hook montage, no series labels). ``vstudio.firstpass`` checks the render against the same format.
Not the same thing as ``vstudio.create.formats`` (series presets that seed AI-generated content on the Create page):
these are editing defaults for footage the creator hands over.
"""
import argparse
import copy
import json
import sys

# Field meanings (every format has every key; persona overrides deep-merge):
#   workflow      workflows/<name>/WORKFLOW.md to follow
#   speed         body / hook / inserts (inserted highlight footage, labelled 精选) playback rates, pitch kept
#   hooks         "menu" = show a numbered list of `hook_menu` candidates and let the creator pick + order
#                 (never auto-pick); "none" = no hook montage, open on her own first line
#   cleanup       vstudio.cleanup profile for her own speech (gentle | standard | tight | off)
#   theme         design theme (vstudio.theme); never the red "classic" look unless she asks
#   notes         记笔记 / note cards on the key points;  progress: progress bar style (None = none)
#   engine        talkinghead recipe pipeline: "vtrack" = her styled V track (face track, the edit style below),
#                 "fast" = clean + plain captions; None = the format has no engine choice
#   style         vtrack edit style: "notes" (chapter bar with labels + 记笔记 panels + keyword-coloured captions),
#                 "refined" (精剪: punch-ins, pops, stamps), "mixed"; None = none
#   cover         aspect "video" = same canvas as the video; style; retouch (slim + light makeup on her face);
#                 min_luma = mean brightness floor (0..1); text = "designed" (typographic, theme fonts) | "none"
#   series_labels False = never add 01/04, PART n, 第n集 corner labels or series lines; "ask" = only when told
#   captions      "zh" | "en" | "bilingual"
#   tag_set       persona publish.tag_sets entry for post copy; None = the persona's default tags;
#                 "" = only the post's own tags (persona tags would be off-topic)
#   guests        None | "ask-mask" (offer a sticker over each other participant's head only, never the frame)
#   rules         short extra rules learned from her corrections (shown in `show`, not in the summary line)
#   audio         "required" = the render must have sound (her voice); "optional" = silent is fine (a product demo
#                 with kinetic captions and no music bed)
_COMMON = dict(theme="editorial", series_labels=False, captions="zh", tag_set=None, guests=None, notes=False,
               progress=None, engine=None, style=None, hook_menu=12, rules=[], audio="required")

FORMATS = {
    "talking-head": dict(
        labels=dict(zh="口播", en="Talking head"), workflow="talkinghead",
        speed=dict(body=1.25, hook=1.5, inserts=1.1), hooks="menu", cleanup="tight", notes=True,
        progress="classic", engine="vtrack", style="notes",
        cover=dict(aspect="video", style="frames-with-notes", retouch=True, min_luma=0.42, text="designed"),
        rules=["hooks 只给候选清单让她挑和排序，不自动选", "hook 不超过 1.6x（再快就假了）",
               "保留原始画幅比例，不做大头特写裁切", "标题别太鸡汤，<= 平台标题上限"]),
    "promo": dict(
        labels=dict(zh="作品宣传 / 精选插片", en="Promo of your work"), workflow="promo-recut",
        speed=dict(body=1.2, hook=1.5, inserts=1.1), hooks="none", cleanup="tight", notes=True, progress=None,
        cover=dict(aspect="video", style="retouched-portrait", retouch=True, min_luma=0.42, text="designed"),
        rules=["插入的成片片段标注「精选」，1.1x 就够", "不加 hook 蒙太奇：她的开场句 + 封面就够",
               "高端感：3D 截图卡片滚动高亮、分屏、定格放大，而不是静态贴图"]),
    "call-clips": dict(
        labels=dict(zh="播客 / 通话切片", en="Podcast / call clips"), workflow="call-clips",
        speed=dict(body=1.2, hook=1.35, inserts=1.1), hooks="menu", cleanup="standard", notes=True,
        progress="refined", guests="ask-mask", captions="zh",
        cover=dict(aspect="video", style="frames-with-notes", retouch=False, min_luma=0.42, text="designed"),
        rules=["每条 3-8 分钟，几条合起来覆盖全部内容", "遮挡只盖住对方头部（小猫/小狗贴纸），不整块关掉画面",
               "删掉自我介绍、点名同事 / 老板 / 公司的句子前先列出来给她确认", "字幕和内容留在平台安全区内"]),
    "lecture-slices": dict(
        labels=dict(zh="课程 / 讲座切片", en="Lecture slices"), workflow="longform-to-short",
        speed=dict(body=1.2, hook=1.35, inserts=1.1), hooks="none", cleanup="standard", notes=True,
        progress="refined", series_labels="ask",
        cover=dict(aspect="video", style="title-card", retouch=False, min_luma=0.42, text="designed"),
        rules=["去掉学员信息 / 头像 / 浏览器书签栏", "每条只讲一个有长期价值的点"]),
    "lesson-points": dict(
        labels=dict(zh="课堂知识点切片", en="Lesson knowledge points"), workflow="lesson-clips",
        speed=dict(body=1.0, hook=1.0, inserts=1.0), hooks="none", cleanup="gentle", notes=True, progress=None,
        captions="bilingual", tag_set="",
        cover=dict(aspect="video", style="title-card", retouch=False, min_luma=0.42, text="designed"),
        rules=["一条只讲一个知识点（短语 / 词 / 规则 / 易错点），开头是「今日短语」标题卡", "语言课不加速：学生要听清老师的原速",
               "目标短语在字幕里高亮，关键词卡片在第一次出现时弹出", "学生的名字 / 脸不进成片；每节课附学习笔记"]),
    "interview-qa": dict(
        labels=dict(zh="访谈 / 播客问答切片", en="Interview Q&A clips"), workflow="interview-qa",
        speed=dict(body=1.1, hook=1.0, inserts=1.0), hooks="none", cleanup="tight", notes=False, progress=None,
        guests="ask-mask", captions="bilingual", tag_set="",
        cover=dict(aspect="video", style="title-card", retouch=False, min_luma=0.42, text="designed"),
        rules=["每条以问题开头（问题卡或提问者原声），回答剪紧：去掉「好问题」、口癖和长停顿",
               "说话人标签用角色（主持人 / 嘉宾），没给名字就不写名字", "嘉宾露脸先问，遮脸只盖头"]),
    "vlog": dict(
        labels=dict(zh="vlog（自己的旁白）", en="Voice-over vlog"), workflow="vlog",
        speed=dict(body=1.3, hook=1.3, inserts=1.0), hooks="none", cleanup="gentle", tag_set="",
        cover=dict(aspect="video", style="collage", retouch=False, min_luma=0.45, text="none"),
        rules=["用她自己录的声音，不用 TTS", "人要完整入镜，不重复用素材", "不加暗角，防抖，空镜可 1.3x",
               "配乐轻，不要太欢快"]),
    "explainer": dict(
        labels=dict(zh="讲解视频（3b1b）", en="Explainer"), workflow="explainer",
        speed=dict(body=1.0, hook=1.0, inserts=1.0), hooks="none", cleanup="off", captions="bilingual",
        tag_set="tech",
        cover=dict(aspect="video", style="title-card", retouch=False, min_luma=0.30, text="designed"),
        rules=["转场和动画要多样", "旁白长句口语化，不做总结腔", "轻背景音乐"]),
    "photo-story": dict(
        labels=dict(zh="文艺片 / 照片故事", en="Photo story"), workflow="photo-story",
        speed=dict(body=1.0, hook=1.0, inserts=1.0), hooks="none", cleanup="gentle", captions="bilingual",
        tag_set="art",
        cover=dict(aspect="video", style="hero-photo", retouch=False, min_luma=0.35, text="designed"),
        rules=["不要底部标签条", "特效要够丰富，图片和旁白内容对得上"]),
    "ai-skit": dict(
        labels=dict(zh="AI 短剧 / 系列", en="AI skit"), workflow="ai-video",
        speed=dict(body=1.0, hook=1.0, inserts=1.0), hooks="none", cleanup="off", captions="bilingual",
        series_labels="ask", tag_set="",
        cover=dict(aspect="video", style="frames", retouch=False, min_luma=0.42, text="designed"),
        rules=["先估积分；放大、字幕、配乐在本地做，不花积分", "台词像真人说话，不要 AI 腔",
               "发布时打开平台自己的 AI 生成内容声明"]),
    "launch": dict(
        labels=dict(zh="产品发布 / 更新视频", en="Product launch video"), workflow="launch-kit",
        speed=dict(body=1.0, hook=1.0, inserts=1.0), hooks="none", cleanup="off", captions="en", tag_set="",
        audio="optional",
        cover=dict(aspect="video", style="title-card", retouch=False, min_luma=0.40, text="designed"),
        rules=["真实的产品操作录屏，不放假数据当真实数字", "动态字幕 + 推近到操作处，默认无旁白，配内置曲库的轻背景音",
               "配乐只用有授权的曲库（内置生成曲或写明授权的自有曲）；AI 配音要标注", "平台顺序：国际平台在前，中文平台在后"]),
}
# recipe / workflow id -> format (intake.rules recipe ids and workflow folder names)
BY_RECIPE = {"talkinghead": "talking-head", "promo-recut": "promo", "call-clips": "call-clips",
             "longform-to-short": "lecture-slices", "longform-course": "lecture-slices", "batch": "lecture-slices",
             "vlog": "vlog", "explainer": "explainer", "photo-story": "photo-story", "ai-video": "ai-skit",
             "lesson-clips": "lesson-points", "interview-qa": "interview-qa", "launch-kit": "launch"}
ALIASES = {"口播": "talking-head", "talkinghead": "talking-head", "promo-recut": "promo", "宣传": "promo",
           "播客": "call-clips", "podcast": "call-clips", "call": "call-clips", "访谈": "call-clips",
           "lecture": "lecture-slices", "课程": "lecture-slices", "切片": "lecture-slices", "讲解": "explainer",
           "3b1b": "explainer", "文艺片": "photo-story", "photo": "photo-story", "ai-video": "ai-skit",
           "ai": "ai-skit", "短剧": "ai-skit", "知识点": "lesson-points", "lesson": "lesson-points",
           "问答": "interview-qa", "q&a": "interview-qa", "qa": "interview-qa", "launch-kit": "launch",
           "发布视频": "launch", "product launch": "launch"}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def names():
    return list(FORMATS)


def canonical(name):
    """A format id from an id, alias, recipe or workflow name; None when unknown."""
    n = (name or "").strip().lower()
    if n in FORMATS:
        return n
    return ALIASES.get(n) or BY_RECIPE.get(n)


def _persona_formats():
    try:
        from vstudio.config import persona
        return (persona() or {}).get("formats") or {}
    except Exception:                                   # noqa: BLE001 - no persona = repo defaults
        return {}


def get(name, persona_formats=None):
    """The format's defaults merged with persona ``formats.<id>``. Raises KeyError for an unknown name."""
    fid = canonical(name)
    if not fid:
        raise KeyError(f"unknown format {name!r}; known: {', '.join(FORMATS)}")
    pf = _persona_formats() if persona_formats is None else (persona_formats or {})
    f = _merge(copy.deepcopy(_COMMON), copy.deepcopy(FORMATS[fid]))
    f = _merge(f, pf.get(fid) or {})
    f["id"] = fid
    return f


def detect(text, materials=None):
    """Best format for a request (the intake phrase table + a few format-only words), or None.

    materials: optional {"photos": n, "videos": n, "screenshots": n} hints (screenshots / links next to a 口播
    clip make it a promo)."""
    t = (text or "").lower()
    if not t.strip():
        return None
    try:
        from vstudio.intake.rules import recipe_scores
        scores = recipe_scores(t)
    except Exception:                                   # noqa: BLE001 - the phrase table is optional here
        scores = {}
    fs = {}
    for rid, s in scores.items():
        fid = BY_RECIPE.get(rid)
        if fid:
            fs[fid] = max(fs.get(fid, 0), s)
    if any(w in t for w in ("精选", "宣传", "我做的", "截图放", "分屏", "左右分栏")) and "talking-head" in fs:
        fs["promo"] = max(fs.get("promo", 0), fs["talking-head"] + 0.5)
    if materials and (materials.get("screenshots") or materials.get("links")) and "talking-head" in fs:
        fs["promo"] = max(fs.get("promo", 0), fs["talking-head"] + 0.5)
    if "interview-qa" in fs and "call-clips" in fs:
        fs["interview-qa"] = max(fs["interview-qa"], fs["call-clips"] + 0.5)   # 问答 / Q&A named: the Q&A cut
    if "call-clips" in fs and "lecture-slices" in fs and not any(w in t for w in ("课", "讲座", "lecture", "webinar")):
        fs["call-clips"] = fs["lecture-slices"] + 0.5     # 播客 / 访谈切片 = a conversation cut into clips
    if not fs:
        return None
    return max(fs, key=lambda k: fs[k])


def _x(v):
    return f"{float(v):g}x"


_LOOKS = {   # (engine, style) -> what the render shows: (zh, en)
    ("vtrack", "notes"): (["章节进度条带章节名、当前章节高亮", "记笔记面板", "关键词变色字幕、关键词可改"],
                          ["chapter bar with labels, current chapter highlighted", "note panels",
                           "keyword-coloured captions, keywords editable"]),
    ("vtrack", "refined"): (["精剪风推镜、弹字、印章", "进度条", "关键词变色字幕"],
                            ["refined look with punch-ins, pop words, stamps", "progress bar", "keyword-coloured captions"]),
    ("vtrack", "mixed"): (["推镜加记笔记面板", "进度条", "关键词变色字幕"],
                          ["punch-ins plus note panels", "progress bar", "keyword-coloured captions"]),
    ("fast", None): (["只有字幕，没有面板和进度条的快速精剪"], ["plain captions only, no panels or bar, the fast pass"]),
}


def look(engine, style=None, lang="zh"):
    """What a talkinghead engine + edit style draw, as summary parts (the format summary, the intake plan line)."""
    zh, en = _LOOKS.get((engine, style if engine != "fast" else None), ([], []))
    return list(zh if lang == "zh" else en)


def _look(f, lang):
    """The look parts of the summary: what the engine + style draw, else the notes / progress flags."""
    if f.get("engine"):
        return look(f["engine"], f.get("style"), lang)
    if lang != "zh":
        return ["note cards"] if f["notes"] else []
    return (["记笔记卡片"] if f["notes"] else []) + (["进度条"] if f["progress"] else [])


def summary(f, lang="zh"):
    """One line stating what the first pass will do (and not do). Say it before the first render."""
    if isinstance(f, str):
        f = get(f)
    sp, cv = f["speed"], f["cover"]
    if lang != "zh":
        parts = [f"{f['labels']['en']} defaults: body {_x(sp['body'])}"]
        parts.append(f"hooks: menu of {f['hook_menu']} at {_x(sp['hook'])}, you pick" if f["hooks"] == "menu"
                     else "no hook montage")
        if sp.get("inserts") and sp["inserts"] != 1.0 and f["workflow"] == "promo-recut":
            parts.append(f"inserted footage {_x(sp['inserts'])}, labelled")
        parts.append(f"cleanup {f['cleanup']}")
        parts.append(f"theme {f['theme']}")
        parts += _look(f, "en")
        parts.append("cover same size as the video" + (", retouched" if cv.get("retouch") else ""))
        if f["series_labels"] is False:
            parts.append("no series labels")
        if f["guests"]:
            parts.append("guest faces: ask, sticker on the head only")
        return "; ".join(parts)
    parts = [f"按「{f['labels']['zh']}」默认：正文 {_x(sp['body'])}"]
    parts.append(f"hook 给 {f['hook_menu']} 条候选你挑（{_x(sp['hook'])}）" if f["hooks"] == "menu" else "不加 hook 蒙太奇")
    if sp.get("inserts") and sp["inserts"] != 1.0 and f["workflow"] == "promo-recut":
        parts.append(f"插入成片 {_x(sp['inserts'])} 标「精选」")
    if f["cleanup"] != "off":
        parts.append({"tight": "严格去 filler / 重复 / 气口", "standard": "标准去 filler / 气口",
                      "gentle": "轻度去气口"}.get(f["cleanup"], f"cleanup {f['cleanup']}"))
    parts.append(f"{f['theme']} 主题")
    parts += _look(f, "zh")
    parts.append("封面与正片同尺寸" + ("、修图" if cv.get("retouch") else "") + "、够亮")
    if f["series_labels"] is False:
        parts.append("不加系列角标")
    if f["captions"] == "bilingual":
        parts.append("双语字幕")
    if f["guests"]:
        parts.append("对方的脸：先问，只遮头")
    return "，".join(parts)


def _cli(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.formats", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    s = sub.add_parser("show")
    s.add_argument("name")
    d = sub.add_parser("detect")
    d.add_argument("text")
    for p in sub.choices.values():
        p.add_argument("--json", action="store_true")
        p.add_argument("--lang", default="zh", choices=["zh", "en"])
    a = ap.parse_args(argv)
    if a.cmd in (None, "list"):
        rows = [dict(id=k, label=get(k)["labels"][getattr(a, "lang", "zh")], summary=summary(k, getattr(a, "lang", "zh")))
                for k in FORMATS]
        if getattr(a, "json", False):
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                print(f"{r['id']:<15} {r['summary']}")
        return 0
    if a.cmd == "detect":
        fid = detect(a.text)
        out = dict(format=fid, summary=summary(fid, a.lang) if fid else None)
        print(json.dumps(out, ensure_ascii=False) if a.json else (f"{fid}: {out['summary']}" if fid else "no match"))
        return 0 if fid else 1
    try:
        f = get(a.name)
    except KeyError as e:
        print(e, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(f, ensure_ascii=False, indent=1))
    else:
        print(summary(f, a.lang))
        for r in f["rules"]:
            print(f"  - {r}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
