"""First-pass check: run this on every render BEFORE showing it to the creator.

Each item is something a real job came back for: no sound, resolution lower than the source, the speed-up never
applied ("加速了么"), first frame black, loudness, ASR typos and wrong place names in the captions (宏都拉斯),
filler words still in the captions, series labels nobody asked for (01/04, PART 2), a cover that is missing, a
different size from the video or too dark, a red "classic" look, a title over the platform limit, a hook montage on
a format that does not get one.

    python -m vstudio.firstpass final.mp4 --format talking-head --source raw1.mp4 --source raw2.mp4 \\
        --cues final.cues.json --cover cover.jpg --post post.md [--platform xiaohongshu:full] [--json]
    -> a checklist (中文 by default, --lang en); exit 1 when a red item fails. Fix the reds, re-run, then show her.

    from vstudio import firstpass
    res = firstpass.run("final.mp4", fmt="talking-head", sources=["raw.mp4"], cues="cues.json", cover="cover.jpg")
    print(firstpass.report(res))

Media checks reuse the batch QC gates (``vstudio.batch.qc``: loudness, true peak, A/V sync, black frames); text
checks reuse ``asr.apply_term_fixes`` (persona ``subtitles.term_fixes`` + generic fixes), ``entities.verify``,
``proofread.caption_fillers`` and ``publish.check_title``. The format (``vstudio.formats``) sets the expected speed,
hooks, series-label and cover rules.
"""
import argparse
import json
import os
import re
import sys

SERIES_RE = re.compile(r"(?<![\d.:])0\d\s*/\s*0?\d{1,2}(?![\d.:])|^\s*\d{1,2}\s*/\s*\d{1,2}\s*$"
                       r"|[\u4e00-\u9fff]\s*0\d(?!\d)|第\s*[0-9一二三四五六七八九十]+\s*[集期篇话]"
                       r"|\bPART\s*\d+\b|\bEP\s*\.?\s*\d+\b|\bEpisode\s*\d+\b", re.I | re.M)


def _item(id_, ok, zh, en, severity="red", value=None, fix_zh="", fix_en=""):
    return dict(id=id_, ok=ok, severity=severity, value=value, zh=zh, en=en, fix_zh=fix_zh, fix_en=fix_en)


def _from_qc(c, zh, fix_zh=""):
    return _item(c["name"], c["ok"], zh, c.get("reason") or c["name"], c.get("severity", "red"), c.get("value"),
                 fix_zh)


# ------------------------------------------------------------------------------------------------ inputs
def load_cues(path_or_cues):
    """cues.json ({cues: [...]} or a list), an .srt file, or a list of {start, end, text}."""
    if not path_or_cues:
        return []
    if isinstance(path_or_cues, (list, tuple)):
        return [dict(start=float(c.get("start", 0)), end=float(c.get("end", 0)), text=str(c.get("text", "")))
                for c in path_or_cues]
    p = os.fspath(path_or_cues)
    if p.lower().endswith(".srt"):
        from vstudio import subs
        return load_cues([dict(start=c["start"], end=c["end"], text=c["text"]) if isinstance(c, dict) else
                          dict(start=c.start, end=c.end, text=c.text) for c in subs.srt_read(p)])
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return load_cues(d.get("cues", []) if isinstance(d, dict) else d)


def _strip_markup(t):
    return re.sub(r"[【】]", "", t or "")


def load_post(path):
    """-> (title, text). post.json {title, body/text/...} or a markdown / text file (title = first non-empty
    line, without a leading '#' or '标题：')."""
    if not path:
        return "", ""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if path.lower().endswith(".json"):
        d = json.loads(raw)
        if isinstance(d, dict):
            body = "\n".join(str(d.get(k) or "") for k in ("body", "text", "description", "caption"))
            return str(d.get("title") or ""), (str(d.get("title") or "") + "\n" + body).strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    title = re.sub(r"^(#+\s*|标题[:：]\s*|title:\s*)", "", lines[0], flags=re.I) if lines else ""
    return title, raw


# ------------------------------------------------------------------------------------------------ checks
def check_video(info, prof, sources_info, fmt=None):
    out = []
    if (fmt or {}).get("audio") == "optional" and not info.get("has_audio"):
        out.append(_item("audio", None, "无声成片（这个格式默认无配乐 / 旁白）", "silent render (this format has no "
                         "music or voice by default)", severity="info"))
    else:
        out.append(_item("audio", bool(info.get("has_audio")), "成片有声音", "the render has an audio track",
                         fix_zh="音轨丢了：检查最后一步合成 / 导出是否带了 -map 0:a"))
    short = min(info["display_w"], info["display_h"])
    floor = min(prof.w, prof.h)
    if sources_info:
        floor = min(floor, min(min(s["display_w"], s["display_h"]) for s in sources_info))
    out.append(_item("resolution", short >= floor * 0.98, f"分辨率不低于源 / 平台（短边 {short}，至少 {floor}）",
                     f"resolution not below source / platform (short side {short}, floor {floor})", value=short,
                     fix_zh="用 delivery 编码按平台画布导出，不要在中间步骤缩小"))
    a_out = info["display_w"] / max(1, info["display_h"])
    a_pl = prof.w / prof.h
    out.append(_item("aspect", abs(a_out / a_pl - 1) <= 0.02, f"画幅与 {prof.key} 一致（{info['display_w']}x{info['display_h']}）",
                     f"aspect matches {prof.key}", severity="warn", value=round(a_out, 3)))
    return out


def check_media(path, prof, media_checks=True):
    if not media_checks:
        return []
    from vstudio.batch import qc
    out = []
    zh = {"loudness": f"响度 {prof.loudness['lufs']} LUFS（±1）", "true-peak": f"峰值不超过 {prof.loudness['tp']} dBTP"}
    for c in qc.check_loudness(path, prof.loudness):
        out.append(_from_qc(c, zh.get(c["name"], c["name"]), "two-pass loudnorm：vstudio.audio.loudnorm_2pass"))
    out.append(_from_qc(qc.check_av_sync(path), "音画时长对齐", "按较短的流裁齐后重新封装"))
    black, _fr = qc.detect_black_frozen(path, black_min=0.1, freeze_min=1e9)
    first = [b for b in black if b[0] <= 0.05]
    out.append(_item("first-frame", not first, "第一帧不是黑帧（封面要能当第一帧）", "first frame is not black",
                     value=first[0] if first else None, fix_zh="把封面烧进第一帧：workflows/polish"))
    mid = [b for b in black if b[0] > 0.05 and b[1] - b[0] >= 0.5]
    out.append(_item("black", not mid, "中间没有黑场", "no black gaps", severity="warn", value=mid[:3] or None))
    return out


def check_speed(out_dur, src_durs, speed, hook_seconds=0.0):
    """Cleanup and cuts only shorten, so a sped-up body can never be longer than sources / speed (+ hooks)."""
    if not src_durs or not speed or speed <= 1.0:
        return [_item("speed", None, f"正文语速 {speed or 1:g}x", f"body speed {speed or 1:g}x", severity="info")]
    limit = sum(src_durs) / speed * 1.03 + float(hook_seconds or 0) + 1.0
    ok = out_dur <= limit
    return [_item("speed", ok, f"正文已加速到 {speed:g}x（成片 {out_dur:.1f}s，按源时长应 <= {limit:.1f}s）",
                  f"body sped up to {speed:g}x (render {out_dur:.1f}s, expected <= {limit:.1f}s)", value=round(out_dur, 2),
                  fix_zh="加速没生效：检查 atempo / setpts 是否在最终导出链里")]


def check_captions(cues, fmt=None, locale=None):
    from vstudio import asr, entities, proofread
    out = []
    if not cues:
        if fmt and fmt.get("captions"):
            out.append(_item("captions", None, "没给字幕文件，错字 / 地名没有检查", "no cues given: captions not checked",
                             severity="warn"))
        return out
    texts = [_strip_markup(c["text"]) for c in cues]
    terms = []
    for i, t in enumerate(texts):
        fixed = asr.apply_term_fixes(t, clean=False)
        if fixed != t:
            terms.append(f"#{i + 1} {t} -> {fixed}")
    out.append(_item("terms", not terms, "字幕没有已知的 ASR 错词（人设 term_fixes + 常见术语）",
                     "no known ASR mis-hearings left in the captions", value=terms[:5] or None,
                     fix_zh="跑 proofread / asr.apply_term_fixes，新错词加进 persona subtitles.term_fixes"))
    ver = entities.verify("\n".join(texts), locale)
    fixes = [f"{f['from']} -> {f['to']}" for f in ver.get("fixes", [])]
    out.append(_item("entities", not fixes, "地名 / 专有名词写法正确（如 宏都拉斯 -> 洪都拉斯）",
                     "place names / entities spelled right", value=fixes[:5] or None,
                     fix_zh="用 vstudio.proofread（带实体校验）修正，并同步到卡片和文案"))
    fl = proofread.caption_fillers([dict(c, text=t) for c, t in zip(cues, texts)])
    out.append(_item("fillers", not fl, "字幕里没有残留的嗯 / 呃 / 那个那个", "no fillers left in the captions",
                     severity="warn", value=[f["text"] for f in fl[:3]] or None,
                     fix_zh="音频里也还在：回到 vstudio.cleanup 再确认一轮"))
    from vstudio.batch import qc
    out.append(_from_qc(qc.check_hallucinations([dict(c, text=t) for c, t in zip(cues, texts)]),
                        "字幕没有 whisper 编出来的句子（字幕志愿者 / 点赞订阅）"))
    if fmt is not None and fmt.get("series_labels") is False:
        hits = [t for t in texts if SERIES_RE.search(t)]
        out.append(_item("series-captions", not hits, "字幕里没有 01/04、PART n 这类系列角标",
                         "no series labels in the captions", value=hits[:3] or None))
    return out


def _luma(path):
    from PIL import Image, ImageStat
    with Image.open(path) as im:
        return ImageStat.Stat(im.convert("L")).mean[0] / 255.0, im.size


def check_cover(cover, info, fmt=None):
    want = fmt is None or bool(fmt.get("cover"))
    if not cover:
        return [_item("cover", False if want else None, "有封面", "a cover exists", severity="red" if want else "info",
                      fix_zh="workflows/cover：从成片挑帧 / 拼帧，与正片同尺寸")]
    if not os.path.exists(cover):
        return [_item("cover", False, f"封面文件存在（{os.path.basename(cover)}）", "cover file exists")]
    luma, (w, h) = _luma(cover)
    rules = (fmt or {}).get("cover") or {}
    out = [_item("cover", True, "有封面", "a cover exists")]
    if rules.get("aspect", "video") == "video":
        a_c, a_v = w / h, info["display_w"] / max(1, info["display_h"])
        out.append(_item("cover-aspect", abs(a_c / a_v - 1) <= 0.02, f"封面与正片同尺寸比例（封面 {w}x{h}，正片 "
                         f"{info['display_w']}x{info['display_h']}）", "cover has the video's aspect", value=f"{w}x{h}",
                         fix_zh="按正片画布重出封面（cover.framed_cover / cover.split_cover 传正片尺寸）"))
    floor = float(rules.get("min_luma", 0.40))
    out.append(_item("cover-bright", luma >= floor, f"封面够亮（平均亮度 {luma:.2f}，至少 {floor:.2f}）",
                     f"cover bright enough (mean luma {luma:.2f} >= {floor:.2f})", severity="warn", value=round(luma, 3),
                     fix_zh="换一帧更亮的，或提亮 / 去掉暗色渐变"))
    out.append(_item("cover-size", min(w, h) >= 1080, f"封面清晰（短边 {min(w, h)} >= 1080）", "cover short side >= 1080",
                     severity="warn", value=min(w, h)))
    return out


def check_post(title, text, prof, fmt=None):
    out = []
    if title:
        from vstudio import publish
        ok, n, hints = publish.check_title(title, "youtube" if prof.name == "youtube-shorts" else prof.name)
        out.append(_item("title", ok, f"标题长度在 {prof.name} 上限内（{n:g}）", f"title within the {prof.name} limit ({n:g})",
                         value=n, fix_zh="; ".join(hints[:2])))
    if text and fmt is not None and fmt.get("series_labels") is False:
        hits = [ln.strip() for ln in text.splitlines() if SERIES_RE.search(ln)]
        out.append(_item("series-post", not hits, "文案里没有系列编号（她没说是系列）", "no series numbering in the post",
                         value=hits[:3] or None, fix_zh="去掉编号；真要做系列时 formats series_labels 设 ask 并先问"))
    return out


def check_style(fmt=None, hook_seconds=0.0):
    out = []
    try:
        from vstudio import theme
        T = theme.resolve()
        name = T["name"]
    except Exception:                                   # noqa: BLE001 - themes are optional for this check
        name = None
    if name:
        want = (fmt or {}).get("theme") or "editorial"
        out.append(_item("theme", name not in ("classic",) or want == "classic",
                         f"配色主题 {name}（不是旧的大红字 classic）", f"theme {name} (not the old red classic look)",
                         severity="warn", value=name, fix_zh="persona style.theme: editorial，或输出编辑 {op: theme}"))
    if fmt is not None and fmt.get("hooks") == "none" and float(hook_seconds or 0) > 0:
        out.append(_item("hooks", False, f"「{fmt['labels']['zh']}」默认不加 hook 蒙太奇，这版加了 {float(hook_seconds):g}s",
                         "this format gets no hook montage", severity="warn", value=hook_seconds,
                         fix_zh="先问她要不要；默认用她自己的开场句"))
    return out


# ------------------------------------------------------------------------------------------------ run
def _profile(platform, info):
    from vstudio import platform as PL
    from vstudio.config import persona
    name = platform or ((persona().get("platforms") or {}).get("default") or "xiaohongshu")
    n, _, o = name.partition(":")
    if not o:
        o = PL.best_orientation(n, info["display_w"] / max(1, info["display_h"]))
    return PL.profile(n, o)


def run(video, fmt=None, platform=None, sources=(), speed=None, cues=None, cover=None, post=None, title=None,
        hook_seconds=0.0, media_checks=True, locale=None):
    """-> {ok, video, format, summary, platform, items: [{id, ok, severity, value, zh, en, fix_zh}]}.
    ok is False when any red item failed (ok None = skipped / info)."""
    from vstudio import formats as F
    from vstudio import media
    f = F.get(fmt) if isinstance(fmt, str) and fmt else (fmt or None)
    info = media.probe(video)
    srcs = [media.probe(s) for s in (sources or [])]
    prof = _profile(platform, info)
    sp = speed if speed is not None else ((f or {}).get("speed") or {}).get("body")
    items = []
    items += check_video(info, prof, srcs, f)
    items += check_media(video, prof, media_checks and info.get("has_audio"))
    items += check_speed(info["duration"], [s["duration"] for s in srcs], sp, hook_seconds)
    items += check_captions(load_cues(cues), f, locale)
    items += check_cover(cover, info, f)
    t, txt = load_post(post)
    items += check_post(title or t, txt, prof, f)
    items += check_style(f, hook_seconds)
    ok = not any(i["ok"] is False and i["severity"] == "red" for i in items)
    return dict(ok=ok, video=os.fspath(video), format=(f or {}).get("id"), summary=F.summary(f) if f else None,
                summary_en=F.summary(f, "en") if f else None, platform=prof.key, items=items)


def report(res, lang="zh"):
    zh = lang == "zh"
    head = ("首轮自检" if zh else "First-pass check") + f": {os.path.basename(res['video'])} ({res['platform']})"
    lines = [f"# {head}", ""]
    if res.get("summary"):
        lines += [res["summary"] if zh else res.get("summary_en") or res["summary"], ""]
    mark = {True: "[x]", False: "[ ]", None: "[-]"}
    for sev in ("red", "warn", "info"):
        for i in res["items"]:
            if i["severity"] != sev:
                continue
            tag = "" if i["ok"] is not False else (" **必须修**" if zh else " **must fix**") if sev == "red" else \
                (" 注意" if zh else " check")
            line = f"- {mark[i['ok']]} {i['zh'] if zh else i['en']}{tag}"
            if i["ok"] is False and i.get("value") not in (None, [], ""):
                line += f" — {i['value']}"
            if i["ok"] is False and zh and i.get("fix_zh"):
                line += f"（{i['fix_zh']}）"
            lines.append(line)
    lines += ["", ("可以给她看了。" if zh else "Ready to show.") if res["ok"] else
              ("先修掉 必须修 的项，再给她看。" if zh else "Fix the must-fix items before showing it.")]
    return "\n".join(lines)


def _cli(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.firstpass", description=__doc__.split("\n\n")[0])
    ap.add_argument("video")
    ap.add_argument("--format", dest="fmt", help="vstudio.formats id (talking-head, promo, call-clips, ...)")
    ap.add_argument("--platform", help="platform[:orientation]; default persona platforms.default, closest shape")
    ap.add_argument("--source", action="append", default=[], help="raw source clip (repeatable): resolution + speed")
    ap.add_argument("--speed", type=float, help="expected body speed (default: the format's)")
    ap.add_argument("--hook-seconds", type=float, default=0.0, help="length of the hook montage in the render")
    ap.add_argument("--cues", help="cues.json or .srt of the burned captions")
    ap.add_argument("--cover")
    ap.add_argument("--post", help="post.md / post.json")
    ap.add_argument("--title")
    ap.add_argument("--locale")
    ap.add_argument("--no-media", action="store_true", help="skip loudness / sync / black-frame measurements")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.video, a.fmt, a.platform, a.source, a.speed, a.cues, a.cover, a.post, a.title, a.hook_seconds,
              not a.no_media, a.locale)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if a.json else report(res, a.lang))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
