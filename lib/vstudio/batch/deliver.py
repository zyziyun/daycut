"""``deliver``: the client delivery package built from a batch's approved jobs, + source cleanup after N days.

    python -m vstudio.batch deliver --batch B [--client acme] [--zip] [--cleanup-days 30] [--out DIR] [--json]
    python -m vstudio.batch cleanup-sources [--batch B | --client acme | --all]           # always a dry run first
    python -m vstudio.batch cleanup-sources ... --confirm-delete CODE   # deletes exactly the files the dry run listed

Layout (``<batch>/delivery/<client>-<batch>-<YYYYMMDD>/``)::

    小红书/01_<title>.mp4            one folder per platform (+ orientation when a platform has several)
    小红书/01_<title>_封面.jpg        the cover next to its video
    文案.md                          title / body / tags per post + the AI-content label reminder
    排期表.csv                       date, time, platform, no., title, file (UTF-8 BOM: opens in Excel)
    交付说明.md                      counts, total duration, platforms, QC notes, source cleanup date
    manifest.json                   every file with sha256 + bytes, the package confirmation code, the delivery code
  + <same name>.zip                 with --zip

It packages first when needed (``package``: approved jobs not yet in the publish folders, or a stale manifest).
Files are hard links where possible (no extra space). The delivery is recorded in the batch store (``metrics``
counts it) with the cleanup due date: ``--cleanup-days`` (default the client's ``delivery.cleanup_days``, else
0 = never). The creator's own workspace (client ``self``, or no client) never schedules a cleanup, whatever is passed.

Source cleanup never happens on its own: ``cleanup-sources`` lists the source files of deliveries past due with a
confirmation code (a hash of the exact file list); only ``--confirm-delete <code>`` deletes, and only those files.
Never deleted: a file another registered batch still needs (not delivered / not due), and any source outside the
batch / project folder (the creator's own recordings) - those are only reported (``outside``).
"""
import csv
import datetime as dt
import io
import os
import re
import shutil
import time
import zipfile

from .store import Store
from .util import read_json, sha1_json, sha256_file, write_json
from ..oscompat import relpath as _relpath

PLATFORM_NAMES = {"xiaohongshu": "小红书", "douyin": "抖音", "tiktok": "TikTok", "youtube-shorts": "YouTube Shorts",
                  "youtube": "YouTube", "bilibili": "B站", "kuaishou": "快手", "weixin-channels": "视频号",
                  "instagram": "Instagram", "wechat-channels": "视频号", "x": "X"}
AI_REMINDER = ("【AI 标识提醒】这批视频用了 AI 辅助剪辑 / 字幕 / 文案。发布时请按平台要求声明 AI 生成内容"
               "（小红书「笔记含 AI 合成内容」、抖音「内容由 AI 生成」、YouTube「Altered or synthetic content」），"
               "避免限流或下架。")
DEFAULT_CLEANUP_DAYS = 0          # never, unless the client config sets delivery.cleanup_days
SELF_CLIENTS = {"self", "me", "own", "自己", "自己的账号"}


def is_self_client(cdir, ccfg=None):
    """The creator's own workspace: no client, client folder ``self`` (or a config with ``own: true``)."""
    if not cdir:
        return True
    return os.path.basename(os.path.normpath(cdir)).lower() in SELF_CLIENTS or bool((ccfg or {}).get("own"))


def platform_label(key, keys):
    """'xiaohongshu-full' -> '小红书' ('小红书-full' when the delivery has several 小红书 orientations)."""
    name, _, orient = key.rpartition("-")
    if key in PLATFORM_NAMES or not name:
        name, orient = key, ""
    base = PLATFORM_NAMES.get(name, name)
    same = [k for k in keys if (k.rpartition("-")[0] or k) == name]
    return f"{base}-{orient}" if len(same) > 1 and orient else base


def safe_name(s, n=40):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", s or "").strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return s[:n] or "untitled"


def _place(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _post_text(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_title(text, title):
    lines = (text or "").strip("\n").split("\n")
    if lines and title and lines[0].strip() == title.strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def _needs_package(store):
    pk = store.meta("package") or {}
    if not pk.get("dir") or not os.path.exists(os.path.join(pk["dir"], "manifest.json")):
        return True
    if store.jobs(("approved",)):                    # approved after the last package
        return True
    from .api import verify_manifest
    return not verify_manifest(os.path.join(pk["dir"], "manifest.json"))["ok"]


def deliver(batch_dir, client=None, make_zip=False, cleanup_days=None, out=None, today=None):
    from . import clients as CL
    from .package import package
    store = Store(batch_dir)
    try:
        if _needs_package(store):
            store.close()
            package(batch_dir)
            store = Store(batch_dir)
        spec = store.spec
        cdir = CL.resolve(client, spec.get("_dir")) if client else CL.batch_client_dir(spec)
        ccfg = CL.load(cdir) if cdir and os.path.exists(CL.yaml_path(cdir)) else {}
        cname = ccfg.get("name") or (os.path.basename(cdir) if cdir else "客户")
        cleanup_note = None
        if is_self_client(cdir, ccfg):
            if cleanup_days:
                cleanup_note = "own workspace: source cleanup is never scheduled"
            cleanup_days = 0
        elif cleanup_days is None:
            cleanup_days = int(((CL.effective(ccfg) if ccfg else {}).get("delivery") or {}).get("cleanup_days")
                               or DEFAULT_CLEANUP_DAYS)
        pk = store.meta("package") or {}
        pdir = pk["dir"]
        man = read_json(os.path.join(pdir, "manifest.json"), {}) or {}
        jobs = {j["id"]: j for j in store.jobs()}
        bname = spec.get("name") or os.path.basename(store.dir)
        today = today or dt.date.today()
        name = safe_name(f"{cname}-{bname}-{today.strftime('%Y%m%d')}", 80)
        root = os.path.abspath(out or os.path.join(store.dir, "delivery"))
        ddir = os.path.join(root, name)
        shutil.rmtree(ddir, ignore_errors=True)
        os.makedirs(ddir)
        items = list(man.get("items") or [])
        keys = sorted({it["platform"] for it in items})
        counters, files, posts, sched, total_s = {}, [], [], [], 0.0
        lrank = {}                                         # label -> display order
        from vstudio.platform import order_key           # international platforms first, then Chinese, then other
        for it in sorted(items, key=lambda x: (x.get("date") or "", x.get("time") or "", order_key(x["platform"]),
                                               x["platform"], x["job"])):
            label = platform_label(it["platform"], keys)
            lrank.setdefault(label, order_key(it["platform"]))
            n = counters[label] = counters.get(label, 0) + 1
            p = (jobs.get(it["job"]) or {}).get("params") or {}
            title = p.get("title") or it.get("title") or it["job"]
            stem = f"{n:02d}_{safe_name(title)}"
            vsrc = os.path.join(pdir, it["files"]["video"])
            vdst = _place(vsrc, os.path.join(ddir, label, stem + (os.path.splitext(vsrc)[1] or ".mp4")))
            files.append(vdst)
            cover_rel = None
            if it["files"].get("cover") and os.path.exists(os.path.join(pdir, it["files"]["cover"])):
                csrc = os.path.join(pdir, it["files"]["cover"])
                cdst = _place(csrc, os.path.join(ddir, label, f"{stem}_封面{os.path.splitext(csrc)[1] or '.jpg'}"))
                files.append(cdst)
                cover_rel = _relpath(cdst, ddir)
            post = _post_text(os.path.join(pdir, it["files"]["post"])) if it["files"].get("post") else ""
            total_s += float(it.get("duration") or 0)
            rel = _relpath(vdst, ddir)
            posts.append(dict(no=n, platform=label, job=it["job"], date=it.get("date"), time=it.get("time"), file=rel,
                              cover=cover_rel, title=title, body=_strip_title(post, title) or (p.get("body") or ""),
                              tags=list(p.get("tags") or []), sha256=it.get("sha256")))
            sched.append([it.get("date") or "", it.get("time") or "", label, n, title, rel])
        if not posts:
            raise ValueError("nothing to deliver: approve jobs (review) first")
        md = [f"# 文案 · {cname} · {bname}", "", AI_REMINDER, ""]
        for p in posts:
            md += [f"## {p['platform']} {p['no']:02d} · {p['title']}", "",
                   f"- 发布时间：{p['date'] or '—'} {p['time'] or ''}", f"- 视频：`{p['file']}`"]
            if p["cover"]:
                md.append(f"- 封面：`{p['cover']}`")
            md += ["", "**标题**", "", p["title"], "", "**正文**", "", p["body"] or "（无）", "", "**标签**", "",
                   " ".join(f"#{t}" for t in p["tags"]) or "（无）", "", "- [ ] 已声明 AI 生成内容", ""]
        files.append(_write(os.path.join(ddir, "文案.md"), "\n".join(md)))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["日期", "时间", "平台", "序号", "标题", "文件"])
        w.writerows(sched)
        files.append(_write(os.path.join(ddir, "排期表.csv"), "﻿" + buf.getvalue()))
        job_ids = sorted({p["job"] for p in posts})
        red = [j for j in job_ids if (jobs.get(j) or {}).get("qc") == "red"]
        warns = []
        for j in job_ids:
            qr = (jobs.get(j) or {}).get("qc_reasons")
            if isinstance(qr, dict):
                warns += [(j, w_) for w_ in qr.get("warn") or []]
        due = today + dt.timedelta(days=int(cleanup_days)) if cleanup_days else None
        notes = [f"# 交付说明 · {cname}", "", f"- 批次：{bname}", f"- 交付日期：{today.isoformat()}",
                 f"- 条数：{len(job_ids)} 条内容 · {len(posts)} 个平台文件", f"- 平台：{'、'.join(sorted(counters, key=lambda x: (lrank.get(x, 999), x)))}",
                 f"- 总时长：{int(total_s // 60)} 分 {int(total_s % 60)} 秒",
                 f"- 发布包确认码：{man.get('confirmation_code') or '—'}", "", "## 质检说明", "",
                 "每条视频都过了自动质检（响度、字幕与音频一致、字幕安全区、标题长度、黑帧 / 定格、音画同步）和人工审片。", ""]
        notes += [f"- {j}：自动质检红灯，人工确认后放行" for j in red] or ["- 自动质检全部绿灯"]
        notes += [f"- {j}：{w_}" for j, w_ in warns[:20]]
        notes += ["", "## 使用说明", "", "1. 按 `排期表.csv` 的时间发布，文案见 `文案.md`。", "2. " + AI_REMINDER,
                  "3. 发布 7 天后，请把每条的播放 / 收藏 / 点赞 / 涨粉发给我们。", ""]
        if due:
            notes += [f"原始素材将于 {due.isoformat()} 从制作电脑上删除（交付后 {cleanup_days} 天）。需要保留请提前告知。", ""]
        files.append(_write(os.path.join(ddir, "交付说明.md"), "\n".join(notes)))
        entries = [dict(path=_relpath(f, ddir), sha256=sha256_file(f), bytes=os.path.getsize(f))
                   for f in sorted(files)]
        code = sha1_json(dict(batch=bname, client=cname, items=entries))[:12]
        dman = dict(client=cname, batch=bname, date=today.isoformat(), package_code=man.get("confirmation_code"),
                    delivery_code=code, items=entries, posts=posts, cleanup_on=due.isoformat() if due else None)
        mpath = write_json(os.path.join(ddir, "manifest.json"), dman)
        zpath = None
        if make_zip:
            zpath = ddir + ".zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                for r_, _d, fs in os.walk(ddir):
                    for fn in sorted(fs):
                        fp = os.path.join(r_, fn)
                        z.write(fp, os.path.join(name, _relpath(fp, ddir)))
        srcs = sorted({x for x in _sources(spec, jobs.values()) if x})
        now = time.time()
        n = store.add_delivery(client=cname, dir=ddir, zip=zpath, code=code, items=len(posts), jobs=len(job_ids),
                               duration=round(total_s, 1), cleanup_due=(now + int(cleanup_days) * 86400)
                               if cleanup_days else None, sources=dict(sources=srcs, jobs=job_ids), ts=now)
        store.log("deliver", f"{len(posts)} files, {len(job_ids)} jobs -> {ddir} (code {code})")
    finally:
        store.close()
    if cdir:
        CL.register_batch(batch_dir, bname, cdir)
    return dict(ok=True, delivery=n, dir=ddir, zip=zpath, items=len(posts), jobs=len(job_ids),
                duration_s=round(total_s, 1), code=code, package_code=man.get("confirmation_code"),
                manifest=mpath, manifest_data=dman, cleanup_days=int(cleanup_days or 0),
                cleanup_on=due.isoformat() if due else None, cleanup_note=cleanup_note, client=cname)


def _sources(spec, jobs):
    inp = spec.get("inputs") or {}
    out = [inp.get("source")] + list(inp.get("clips") or [])
    for j in jobs:
        out.append((j.get("params") or {}).get("source"))
    return out


def verify_delivery(manifest):
    """Recompute a delivery manifest's code and every file hash -> dict(ok, code, stored, bad)."""
    path = manifest if isinstance(manifest, str) else None
    man = read_json(path) if path else manifest
    if not isinstance(man, dict) or "items" not in man:
        return dict(ok=False, reason="no delivery manifest")
    code = sha1_json(dict(batch=man.get("batch"), client=man.get("client"), items=man.get("items")))[:12]
    bad = []
    if path:
        root = os.path.dirname(os.path.abspath(path))
        for e in man["items"]:
            f = os.path.join(root, e["path"])
            if not os.path.exists(f) or sha256_file(f) != e["sha256"]:
                bad.append(e["path"])
    ok = code == man.get("delivery_code") and not bad
    return dict(ok=ok, code=code, stored=man.get("delivery_code"), bad=bad)


# --------------------------------------------------------------------------- source cleanup
def _inside(path, folders):
    rp = os.path.realpath(path)
    return any(rp == f or rp.startswith(f.rstrip(os.sep) + os.sep) for f in folders)


def _owner_folders(batch_dir):
    """The batch folder, and the project folder when the batch is a project's ``state/``."""
    b = os.path.realpath(batch_dir)
    out = [b]
    if os.path.basename(b) == "state" and os.path.exists(os.path.join(os.path.dirname(b), "project.yaml")):
        out.append(os.path.dirname(b))
    return out


def cleanup_code(files):
    """Confirmation code of an exact deletion list ([{path, bytes}])."""
    return sha1_json(sorted((f["path"], int(f.get("bytes") or 0)) for f in files))[:12]


def cleanup_sources(batch_dirs, confirm=None, now=None, yes=None):
    """List (default) or delete (``confirm`` = the code of the dry run's list) the source files of deliveries
    past their cleanup date. Kept: files another registered batch still uses; reported, never deleted: sources
    outside the batch / project folder. -> dict(dry_run, would_delete | deleted, outside, kept, freed,
    confirm_code)."""
    if yes is not None:
        raise ValueError("deleting sources needs the confirmation code of the dry run: cleanup-sources "
                         "--confirm-delete <code> (``yes`` is no longer accepted)")
    from . import clients as CL
    now = now or time.time()
    due, busy, owners_dirs = {}, set(), {}
    every = {os.path.abspath(b["dir"]) for b in CL.batches()} | {os.path.abspath(d) for d in batch_dirs}
    asked = {os.path.abspath(x) for x in batch_dirs}
    for b in every:
        try:
            st = Store(b)
        except (FileNotFoundError, OSError):
            continue
        try:
            dels = st.deliveries()
            srcs = {x for x in _sources(st.spec, st.jobs()) if x}
            ripe = [d for d in dels if d["cleanup_due"] and d["cleanup_due"] <= now and not d["cleaned"]]
            done_before = [d for d in dels if d["cleaned"]]
            if b in asked and ripe:
                owners_dirs[b] = _owner_folders(b)
                for s in srcs:
                    due.setdefault(s, []).append((b, [d["n"] for d in ripe]))
            elif not ripe and not done_before:
                busy |= srcs                            # still in production / not due: keep its sources
        finally:
            st.close()
    act, kept, outside, pending = [], [], [], set()
    for s, owners in sorted(due.items()):
        if s in busy:
            kept.append(dict(path=s, why="another batch still uses it"))
            pending |= {b for b, _ in owners}
            continue
        if not any(_inside(s, owners_dirs[b]) for b, _ in owners):
            outside.append(dict(path=s, exists=os.path.exists(s),
                                why="outside the batch / project folder: never deleted (yours to keep or remove)"))
            pending |= {b for b, _ in owners}
            continue
        if not os.path.exists(s):
            act.append(dict(path=s, bytes=0, missing=True))
            continue
        act.append(dict(path=s, bytes=os.path.getsize(s)))
    code = cleanup_code(act)
    freed = sum(x["bytes"] for x in act)
    base = dict(ok=True, outside=outside, kept=kept, confirm_code=code if act else None)
    if confirm is None:
        return dict(base, dry_run=True, would_delete=act, freed=freed)
    if confirm != code:
        raise ValueError(f"confirmation code {confirm!r} does not match the current list ({code}): run the dry run "
                         "again and check the files")
    for x in act:
        if not x.get("missing"):
            os.remove(x["path"])
    marked = {(b, n) for owners in due.values() for b, ns in owners for n in ns if b not in pending}
    for b in {b for b, _ in marked}:                  # a delivery is cleaned once none of its sources is left
        st = Store(b)
        try:
            for (bb, n) in marked:
                if bb == b:
                    st.set_delivery(n, cleaned=now)
            st.log("cleanup", f"source cleanup (confirmed {code}): {len(act)} file(s), {freed} bytes")
        finally:
            st.close()
    return dict(base, dry_run=False, deleted=act, freed=freed)
