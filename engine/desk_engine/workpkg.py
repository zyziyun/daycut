"""Multi-platform publish package of a project that is not a batch (a work folder like fuye/, or a project).

The batch flow has ``vstudio.batch.package``; a work folder has finished clips (versions per aspect, a cover, the
post copy) but no batch store. This builds the same kind of package, so the desk's publish page (confirmation code,
assisted fill, mark posted) works unchanged:

  <DESK_DATA_DIR>/packages/<item>/
    <platform>-<orientation>/<NNN>_<clip>/video.<ext> cover.jpg post.md   (APFS clones / copies: originals untouched)
    manifest.json   {batch: <item>, schedule, items [{job, platform, title, date, time, files, sha256, bytes,
                     duration, checks [...]}], confirmation_code}

Per platform: the clip version whose aspect matches the platform's orientation (default orientation first), else
the closest one with an ``aspect`` check; the copy adapted to the platform (hashtag cap, X / Instagram have no
title: it becomes the first line); structured checks (title / text length, hashtags, duration, aspect, AI label
reminder) for the UI's own words. Nothing is uploaded.
"""
import datetime as dt
import hashlib
import os
import re
import shutil
import subprocess
import sys

from .common import need, read_json, sha1_json, write_json

PLATFORMS = ("xiaohongshu", "douyin", "wechat-channels", "bilibili", "youtube", "youtube-shorts", "tiktok", "x",
             "instagram")
DEFAULT_TIMES = ["19:00"]
CLIP_RE = re.compile(r"^[^/\\\0]{1,120}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Used when the engine (vstudio.platform) is not importable (mock mode). Values mirror vstudio.platform.PLATFORMS.
_FALLBACK = {
    "xiaohongshu": dict(default="vertical", o={"vertical": "3:4", "full": "9:16", "horizontal": "16:9"},
                        title_max=20, desc_max=1000, tags=10, hard=False, length=(5, 900)),
    "douyin": dict(default="vertical", o={"vertical": "9:16", "horizontal": "16:9"}, title_max=55, desc_max=1000,
                   tags=10, hard=False, length=(5, 900)),
    "wechat-channels": dict(default="vertical", o={"vertical": "9:16", "horizontal": "16:9"}, title_max=16,
                            desc_max=1000, tags=10, hard=False, length=(3, 3600)),
    "bilibili": dict(default="horizontal", o={"horizontal": "16:9", "vertical": "9:16"}, title_max=80,
                     desc_max=2000, tags=10, hard=False, length=(5, 36000)),
    "youtube": dict(default="horizontal", o={"horizontal": "16:9"}, title_max=100, desc_max=5000, tags=15,
                    hard=False, length=(5, 43200)),
    "youtube-shorts": dict(default="vertical", o={"vertical": "9:16"}, title_max=100, desc_max=5000, tags=3,
                           hard=False, length=(1, 180)),
    "tiktok": dict(default="vertical", o={"vertical": "9:16"}, title_max=55, desc_max=4000, tags=30, hard=False,
                   length=(3, 600)),
    "x": dict(default="horizontal", o={"horizontal": "16:9", "square": "1:1", "vertical": "9:16"}, title_max=0,
              desc_max=280, tags=2, hard=False, length=(1, 140)),
    "instagram": dict(default="reels", o={"reels": "9:16", "feed": "4:5"}, title_max=0, desc_max=2200, tags=5,
                      hard=True, length=(3, 900)),
}
NO_TITLE = {"x", "instagram"}


def _ratio(a):
    try:
        w, h = (float(x) for x in str(a).split(":"))
        return w / h
    except (ValueError, ZeroDivisionError):
        return None


def _file_ratio(f):
    if f.get("w") and f.get("h"):
        return f["w"] / f["h"]
    return _ratio(f.get("aspect"))


def _aspect_label(r):
    best = min(("9:16", "3:4", "4:5", "1:1", "16:9"), key=lambda a: abs(_ratio(a) - r))
    return best if abs(_ratio(best) - r) < 0.04 else f"{r:.2f}"


class _Prof:
    """A platform's numbers: vstudio.platform when importable, else the fallback table."""

    def __init__(self, name):
        self.name = name
        self.P = None
        try:
            from vstudio import platform as P
            self.P = P
            base = P.PLATFORMS[name]
            self.default = base.get("default")
            self.orient = {k: v.get("aspect") for k, v in base["orientations"].items()}
            self.title_max = base.get("title_max") or 0
            self.desc_max = base.get("desc_max") or 0
            self.tags = (base.get("hashtags") or {}).get("max")
            self.hard = bool((base.get("hashtags") or {}).get("hard"))
            L = base.get("length") or {}
            self.length = (L.get("min"), L.get("max"))
        except Exception:  # noqa: BLE001  (mock mode / older engine)
            fb = _FALLBACK[name]
            self.default, self.orient = fb["default"], fb["o"]
            self.title_max, self.desc_max, self.tags, self.hard = fb["title_max"], fb["desc_max"], fb["tags"], fb["hard"]
            self.length = fb["length"]

    def title_len(self, title):
        if self.P:
            try:
                return float(self.P.title_len(self.P.profile(self.name, use_persona=False), title))
            except Exception:  # noqa: BLE001
                pass
        if self.name == "xiaohongshu":     # CJK / full-width = 1, latin / digit / space = 0.5
            return sum(1 if ord(c) > 0x2E7F else 0.5 for c in title)
        return float(len(title))

    def text_len(self, text):
        if self.P:
            try:
                return int(self.P.text_len(self.P.profile(self.name, use_persona=False), text))
            except Exception:  # noqa: BLE001
                pass
        if self.name == "x":
            return sum(1 if ord(c) < 4352 else 2 for c in text)
        return len(text)


def _hashtags_in(text):
    out = []
    for m in re.finditer(r"(?<![\w&/#])#([^\s#.,!?;:，。！？；：、()（）\[\]{}\"'<>]+)", text or ""):
        t = m.group(1).lower()
        if t not in out:
            out.append(t)
    return out


def _clone(src, dst):
    """APFS clone (copy-on-write, instant, the original is never shared for writing), else a plain copy."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.remove(dst)
    if sys.platform == "darwin":
        try:
            subprocess.run(["/bin/cp", "-c", src, dst], check=True, capture_output=True, timeout=120)
            return dst
        except Exception:  # noqa: BLE001
            pass
    shutil.copy2(src, dst)
    return dst


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pick_version(files, prof):
    """The clip file for this platform -> (orientation, file, check or None)."""
    order = [prof.default] + [o for o in prof.orient if o != prof.default]
    for o in order:
        want = _ratio(prof.orient[o])
        for f in files:
            r = _file_ratio(f)
            if r and want and abs(r - want) < 0.04:
                return o, f, None
    unknown = [f for f in files if _file_ratio(f) is None]
    if unknown:                                     # a master whose size is unknown: take it as the default version
        return prof.default, unknown[0], None
    # nothing matches: the version closest to the default orientation, with a check
    want = _ratio(prof.orient[prof.default]) or 1
    f = min(files, key=lambda x: abs((_file_ratio(x) or want) - want))
    r = _file_ratio(f)
    if r is None:                                   # size unknown (not probed): take it as the default version
        return prof.default, f, None
    o = min(prof.orient, key=lambda k: abs((_ratio(prof.orient[k]) or 1) - r))
    return o, f, dict(code="aspect", want=prof.orient[prof.default], got=_aspect_label(r))


def adapt_copy(name, prof, post, fallback_title):
    """The clip's post copy for one platform -> (title, body, tags, checks)."""
    post = post or {}
    title = (post.get("title") or fallback_title or "").strip()
    body = (post.get("body") or "").strip()
    tags = [str(t).lstrip("#").strip() for t in post.get("tags") or [] if str(t).strip("# ")]
    checks = []
    if not post.get("body") and not post.get("tags"):
        checks.append(dict(code="no-copy"))
    in_body = _hashtags_in(body)
    allt = list(dict.fromkeys([t.lower() for t in tags] + in_body))
    if prof.tags and len(allt) > prof.tags:
        checks.append(dict(code="hashtags-over", n=len(allt), max=prof.tags, hard=prof.hard))
        tags = tags[:max(0, prof.tags - len(in_body))]
    if name in NO_TITLE:
        checks.append(dict(code="no-title"))
        text = "\n\n".join(x for x in (title, body) if x)
    else:
        text = body
        if title and prof.title_max:
            n = prof.title_len(title)
            if n > prof.title_max:
                checks.append(dict(code="title-over", n=round(n, 1), max=prof.title_max))
    full = text + ("\n\n" + " ".join(f"#{t}" for t in tags) if tags else "")
    if prof.desc_max and full:
        n = prof.text_len(full)
        if n > prof.desc_max:
            checks.append(dict(code="desc-over", n=n, max=prof.desc_max))
    return title, body, tags, checks


def post_md(name, title, body, tags):
    lines = [title, ""] if title else []
    if body:
        lines += [body, ""]
    if tags:
        lines.append("标签：" + ", ".join(tags) if name == "bilibili" else " ".join(f"#{t}" for t in tags))
    return "\n".join(lines).strip() + "\n"


class WorkPackages:
    def __init__(self, data_dir, history, outputs):
        self.dir = os.path.join(data_dir, "packages")
        self.history, self.outputs = history, outputs

    def owns(self, item_id):
        """A history entry that is not a batch the engine can package itself."""
        try:
            e = self.history.find(item_id)
        except KeyError:
            return False
        return e.get("kind") in ("work", "project") and not e.get("openable")

    def _pdir(self, item_id):
        return os.path.join(self.dir, item_id)

    def manifest(self, item_id):
        from .real import verify_manifest
        d = self._pdir(item_id)
        man = read_json(os.path.join(d, "manifest.json"), None)
        if not man:
            return dict(manifest=None, dir=None, verify=dict(ok=False, reason="not packaged yet"))
        self.history.allow_media([os.path.join(d, "manifest.json")])
        return dict(manifest=man, dir=d, verify=verify_manifest(man))

    def package(self, item_id, b):
        need(isinstance(b, dict), "body must be an object")
        clips = b.get("clips")
        plats = b.get("platforms")
        need(isinstance(clips, list) and 0 < len(clips) <= 50 and all(isinstance(c, str) and CLIP_RE.match(c)
                                                                      for c in clips), "clips: 1-50 clip ids")
        need(isinstance(plats, list) and 0 < len(plats) <= len(PLATFORMS) and all(p in PLATFORMS for p in plats),
             f"platforms: some of {', '.join(PLATFORMS)}")
        per_day = int(b.get("per_day") or 1)
        need(1 <= per_day <= 20, "per_day: 1-20")
        start = b.get("start") or (dt.date.today() + dt.timedelta(days=1)).isoformat()
        need(isinstance(start, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", start), "start: YYYY-MM-DD")
        times = b.get("times") or DEFAULT_TIMES
        need(isinstance(times, list) and all(isinstance(t, str) and TIME_RE.match(t) for t in times), "times: [HH:MM]")
        by_pf = b.get("times_by_platform") or {}
        need(isinstance(by_pf, dict) and all(k in PLATFORMS and isinstance(v, list) and all(
            isinstance(t, str) and TIME_RE.match(t) for t in v) for k, v in by_pf.items()), "times_by_platform")

        listing = {c["id"]: c for c in self.outputs.clips(item_id)["clips"]}
        e = self.history.find(item_id)
        from .outputs import list_clips
        full = {c["id"]: c for c in list_clips(e)}         # with absolute paths
        chosen = []
        for cid in clips:
            c = full.get(cid)
            need(c is not None and cid in listing, f"no such clip {cid}")
            need(c.get("files"), f"{cid}: no video file yet")
            chosen.append(c)

        final = self._pdir(item_id)
        tmp = final + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        d0 = dt.date.fromisoformat(start)
        items = []
        for pf in plats:
            prof = _Prof(pf)
            ts = list(by_pf.get(pf) or times)
            while len(ts) < per_day:
                ts.append(ts[-1])
            for k, c in enumerate(chosen):
                orient, f, aspect_check = pick_version(c["files"], prof)
                key = f"{pf}-{orient}"
                folder = os.path.join(tmp, key, f"{k + 1:03d}_{c['id']}")
                ext = os.path.splitext(f["path"])[1].lower() or ".mp4"
                vid = _clone(f["path"], os.path.join(folder, "video" + ext))
                files = dict(video=os.path.relpath(vid, tmp))
                if c.get("cover") and os.path.exists(c["cover"]):
                    cov = _clone(c["cover"], os.path.join(folder, "cover" + (os.path.splitext(c["cover"])[1].lower() or ".jpg")))
                    files["cover"] = os.path.relpath(cov, tmp)
                title, body, tags, checks = adapt_copy(pf, prof, c.get("post"), c.get("title"))
                with open(os.path.join(folder, "post.md"), "w", encoding="utf-8") as fh:
                    fh.write(post_md(pf, title, body, tags))
                files["post"] = os.path.relpath(os.path.join(folder, "post.md"), tmp)
                if aspect_check:
                    checks.insert(0, aspect_check)
                dur = f.get("duration") or c.get("duration")
                lo, hi = prof.length
                if dur and ((hi and dur > hi) or (lo and dur < lo)):
                    checks.append(dict(code="length", n=round(dur, 1), min=lo, max=hi))
                checks.append(dict(code="ai-label"))
                day, slot = divmod(k, per_day)
                items.append(dict(job=c["id"], platform=key, title=title, date=(d0 + dt.timedelta(days=day)).isoformat(),
                                  time=ts[slot], files=files, sha256=_sha256(vid), bytes=os.path.getsize(vid),
                                  duration=dur, checks=checks))
        schedule = dict(per_day=per_day, start=start, times=times, times_by_platform=by_pf or None)
        man = dict(batch=item_id, schedule=schedule, items=items)
        man["confirmation_code"] = sha1_json(dict(batch=item_id, schedule=schedule, items=items))[:12]
        write_json(os.path.join(tmp, "manifest.json"), man)
        with open(os.path.join(tmp, "CONFIRM.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"{man['confirmation_code']}  ({len(items)} posts)\n")
        shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)
        self.history.allow_media([os.path.join(final, "manifest.json")])
        return dict(dir=final, items=len(items), confirmation_code=man["confirmation_code"],
                    checks=sum(1 for i in items for x in i["checks"] if x["code"] != "ai-label"))


__all__ = ["WorkPackages", "PLATFORMS", "pick_version", "adapt_copy", "post_md"]
