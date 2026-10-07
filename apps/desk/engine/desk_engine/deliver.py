"""Client delivery package (PRODUCT_V02.md P0-4), built from a batch's publish package (manifest.json).

Layout (``<batch>/delivery/<client>-<batch>-<YYYYMMDD>/``)::

    小红书/01_<title>.mp4          one folder per platform (orientation suffix when a platform has several)
    小红书/01_<title>_封面.jpg      cover next to its video (when the package has one)
    文案.md                        title / body / tags per item + the AI-content label reminder
    排期表.csv                     date, time, platform, no., title, file
    交付说明.md                    counts, total duration, platforms, QC notes, cleanup date
    manifest.json                 every file with sha256 + bytes (and the package confirmation code)
  + <same name>.zip               when zip=True

Used when the engine has no ``deliver`` command (and by mock mode). Files are hard-linked when possible.
"""
import csv
import datetime as dt
import hashlib
import io
import os
import re
import shutil
import zipfile


def _rel(path, start):
    """A relative path with / on every OS (manifests read elsewhere; Windows accepts /)."""
    return os.path.relpath(path, start).replace(os.sep, "/")


PLATFORM_NAMES = {
    "xiaohongshu": "小红书", "douyin": "抖音", "tiktok": "TikTok", "youtube-shorts": "YouTube Shorts",
    "youtube": "YouTube", "bilibili": "B站", "kuaishou": "快手", "weixin-channels": "视频号",
}
# display order: international platforms first, then Chinese (the registry order of vstudio.platform / the desk UI)
_ORDER = ["youtube", "youtube-shorts", "tiktok", "instagram", "x", "facebook", "linkedin", "threads", "reddit",
          "pinterest", "snapchat", "xiaohongshu", "douyin", "wechat-channels", "weixin-channels", "bilibili",
          "kuaishou", "weibo", "zhihu", "dailymotion", "kwai"]


def _order(key):
    s = str(key or "").split(":")[0]
    hits = [n for n in _ORDER if s == n or s.startswith(n + "-")]
    return _ORDER.index(max(hits, key=len)) if hits else len(_ORDER)


AI_REMINDER = ("【AI 标识提醒】本批视频使用了 AI 辅助剪辑/字幕/文案。发布时请按平台要求勾选 AI 生成内容声明"
               "（小红书「笔记含 AI 合成内容」、抖音「内容由 AI 生成」、YouTube「Altered or synthetic content」），"
               "避免限流或下架。")


def platform_label(key, keys):
    """'xiaohongshu-full' -> '小红书' (or '小红书-full' when xiaohongshu has several orientations)."""
    name, _, orient = key.rpartition("-")
    if key in PLATFORM_NAMES or not name:
        name, orient = key, ""
    base = PLATFORM_NAMES.get(name, name)
    same = [k for k in keys if k.rpartition("-")[0] == name]
    return f"{base}-{orient}" if len(same) > 1 and orient else base


def safe_name(s, n=40):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", s or "").strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return s[:n] or "untitled"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _place(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def parse_post(md, fallback_title=""):
    """post.md (title line, body, #tags) -> dict(title, body, tags). Mirrors src/shared/publish/postCopy.ts."""
    lines = [ln.rstrip() for ln in (md or "").splitlines()]
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    title = (lines[first].lstrip("# ").strip() if first is not None else "") or fallback_title
    rest = lines[first + 1:] if first is not None else []
    tags = re.findall(r"#([^\s#]+)", "\n".join(rest))
    body = "\n".join(ln for ln in rest if not re.fullmatch(r"(\s*#[^\s#]+)+\s*", ln)).strip()
    return dict(title=title, body=body, tags=tags)


def build(pkg_dir, manifest, out_root, client_name, batch_name, jobs=None, make_zip=True, cleanup_days=None,
          today=None, copy_overrides=None):
    """Build the delivery folder (+ zip). ``jobs``: {job_id: {qc, duration, qc_warn}} for 交付说明;
    ``copy_overrides``: {job_id: {title, body, tags}} edited in the desk. Returns the delivery record."""
    today = today or dt.date.today()
    name = safe_name(f"{client_name}-{batch_name}-{today.strftime('%Y%m%d')}", 80)
    out = os.path.join(out_root, name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    items = list(manifest.get("items") or [])
    keys = sorted({it["platform"] for it in items})
    counters, files, posts, sched = {}, [], [], []
    total_s = 0.0
    lrank = {}
    for it in sorted(items, key=lambda x: (x.get("date") or "", x.get("time") or "", _order(x["platform"]), x["platform"],
                                           x["job"])):
        label = platform_label(it["platform"], keys)
        lrank.setdefault(label, _order(it["platform"]))
        n = counters[label] = counters.get(label, 0) + 1
        ov = (copy_overrides or {}).get(it["job"]) or {}
        post_src = os.path.join(pkg_dir, it["files"]["post"]) if (it.get("files") or {}).get("post") else None
        md = ""
        if post_src and os.path.exists(post_src):
            with open(post_src, encoding="utf-8") as f:
                md = f.read()
        post = parse_post(md, it.get("title") or "")
        post.update({k: v for k, v in ov.items() if v})
        stem = f"{n:02d}_{safe_name(post['title'])}"
        vsrc = os.path.join(pkg_dir, it["files"]["video"])
        vdst = os.path.join(out, label, stem + (os.path.splitext(vsrc)[1] or ".mp4"))
        _place(vsrc, vdst)
        files.append(vdst)
        cover_rel = None
        if (it.get("files") or {}).get("cover"):
            csrc = os.path.join(pkg_dir, it["files"]["cover"])
            if os.path.exists(csrc):
                cdst = os.path.join(out, label, f"{stem}_封面{os.path.splitext(csrc)[1] or '.jpg'}")
                _place(csrc, cdst)
                files.append(cdst)
                cover_rel = _rel(cdst, out)
        total_s += float(it.get("duration") or 0)
        rel = _rel(vdst, out)
        posts.append(dict(no=n, platform=label, job=it["job"], date=it.get("date"), time=it.get("time"),
                          file=rel, cover=cover_rel, **post))
        sched.append([it.get("date") or "", it.get("time") or "", label, n, post["title"], rel])

    # 文案.md
    md = [f"# 文案 · {client_name} · {batch_name}", "", AI_REMINDER, ""]
    for p in posts:
        md += [f"## {p['platform']} {p['no']:02d} · {p['title']}", "",
               f"- 发布时间：{p['date'] or '—'} {p['time'] or ''}", f"- 视频：`{p['file']}`"]
        if p["cover"]:
            md.append(f"- 封面：`{p['cover']}`")
        md += ["", "**标题**", "", p["title"], "", "**正文**", "", p["body"] or "（无）", "", "**标签**", "",
               " ".join(f"#{t}" for t in p["tags"]) or "（无）", "", "- [ ] 已勾选 AI 生成内容声明", ""]
    _write(os.path.join(out, "文案.md"), "\n".join(md))

    # 排期表.csv (UTF-8 with BOM so Excel opens Chinese correctly)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["日期", "时间", "平台", "序号", "标题", "文件"])
    w.writerows(sched)
    _write(os.path.join(out, "排期表.csv"), "﻿" + buf.getvalue())

    # 交付说明.md
    jobs = jobs or {}
    job_ids = sorted({p["job"] for p in posts})
    red = [j for j in job_ids if (jobs.get(j) or {}).get("qc") == "red"]
    warns = [(j, w) for j in job_ids for w in (jobs.get(j) or {}).get("qc_warn") or []]
    cleanup = (today + dt.timedelta(days=int(cleanup_days))).isoformat() if cleanup_days else None
    notes = [f"# 交付说明 · {client_name}", "",
             f"- 批次：{batch_name}", f"- 交付日期：{today.isoformat()}",
             f"- 条数：{len(job_ids)} 条内容 · {len(posts)} 个平台文件",
             f"- 平台：{'、'.join(sorted(counters, key=lambda x: (lrank.get(x, 999), x)))}",
             f"- 总时长：{int(total_s // 60)} 分 {int(total_s % 60)} 秒",
             f"- 发布包确认码：{manifest.get('confirmation_code') or '—'}", "",
             "## 质检说明", "",
             "每条视频都经过自动质检（响度、字幕安全区、标题长度、画面黑帧/静音）和人工审片。", ""]
    notes += [f"- {j}：红灯已人工确认后放行" for j in red] or ["- 全部绿灯"]
    notes += [f"- {j}：{w}" for j, w in warns[:20]]
    notes += ["", "## 使用说明", "", "1. 按 `排期表.csv` 的时间发布；文案见 `文案.md`。",
              "2. " + AI_REMINDER, "3. 发布后第 7 天，请把每条的播放 / 收藏 / 点赞 / 涨粉回传给我们。", ""]
    if cleanup:
        notes += [f"原始素材将在 {cleanup} 从我们的电脑上清理（交付后 {cleanup_days} 天）。如需保留请提前告知。", ""]
    _write(os.path.join(out, "交付说明.md"), "\n".join(notes))

    entries = []
    for f in sorted(files + [os.path.join(out, n) for n in ("文案.md", "排期表.csv", "交付说明.md")]):
        entries.append(dict(path=_rel(f, out), sha256=_sha(f), bytes=os.path.getsize(f)))
    man = dict(client=client_name, batch=batch_name, date=today.isoformat(),
               package_code=manifest.get("confirmation_code"), items=entries, posts=posts)
    import json
    _write(os.path.join(out, "manifest.json"), json.dumps(man, ensure_ascii=False, indent=1))
    zpath = None
    if make_zip:
        zpath = out + ".zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, fs in os.walk(out):
                for fn in sorted(fs):
                    p = os.path.join(root, fn)
                    z.write(p, os.path.join(name, _rel(p, out)))
    return dict(dir=out, zip=zpath, items=len(posts), jobs=len(job_ids), duration_s=round(total_s, 1),
                manifest=man, cleanup_on=cleanup)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
