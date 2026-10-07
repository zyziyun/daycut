"""Publish calendar (发布): scheduled posts per day + the clips not scheduled yet.

Desk store ``<DESK_DATA_DIR>/calendar.json`` [{id, item, clip, title, platform, at "YYYY-MM-DDTHH:MM", state
planned|ready|filled|posted, cover, caption?, enabled?, stats?}]. One row = one clip on one platform at one time;
the desk groups the rows of one clip on one day into a single card. ``vstudio.project calendar`` (pubcal) is the
engine's own planner; the desk keeps this store until the two are joined (the desk never posts: the assisted-fill
browser stops before 发布, ``filled`` = the form is filled and waits for her to press publish).

Every list row also carries what the board shows without asking again: ``status`` (draft | ready | filled | posted),
``caption`` (her per-platform text, else the clip's post copy), ``limit`` / ``length`` (the platform's post-text
limit, counted the platform's way: X weighs CJK as 2) and ``warnings`` [{kind caption_too_long | no_caption |
slot_clash, platform, ...}]. Unscheduling only removes rows: video files are never touched.
"""
import datetime as dt
import hashlib
import os
import re
import threading
import time

from . import schedule_text
from .common import need, read_json, write_json

AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
STATES = ("planned", "ready", "filled", "posted")
STATUS = dict(planned="draft", ready="ready", filled="filled", posted="posted")
PLATFORM_RE = re.compile(r"^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$")
ITEM_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_CAPTION = 40000
MAX_MANY = 200

# post-text limits when the engine's platform table (vstudio.platform) is not importable: chars, X weighted
FALLBACK_LIMITS = {"xiaohongshu": 1000, "douyin": 1000, "tiktok": 4000, "youtube": 5000, "youtube-shorts": 5000,
                   "bilibili": 2000, "wechat-channels": 1000, "x": 280, "instagram": 2200, "facebook": 63206,
                   "linkedin": 3000, "threads": 500, "pinterest": 500, "kuaishou": 500, "weibo": 2000, "zhihu": 300,
                   "snapchat": 160, "dailymotion": 3000, "kwai": 500, "reddit": 40000}


def _xlen(text):
    n = 0
    for ch in text or "":
        c = ord(ch)
        n += 1 if c <= 4351 or 8192 <= c <= 8205 or 8208 <= c <= 8223 or 8242 <= c <= 8247 else 2
    return n


def text_limit(platform, text):
    """(length counted the platform's way, the platform's post-text limit or None)."""
    base = (platform or "").split(":")[0]
    try:
        from vstudio import platform as PF
        p = PF.profile(base, use_persona=False)
        return PF.text_len(p, text or ""), (p.desc_max or None)
    except Exception:  # noqa: BLE001  (engine not on the path, or a platform it does not know)
        lim = FALLBACK_LIMITS.get(base)
        return (_xlen(text) if base == "x" else len(text or "")), lim


def post_text(post):
    """A clip's post copy {title, body, tags} -> the text one platform gets by default."""
    if not isinstance(post, dict):
        return ""
    parts = [str(post.get("title") or "").strip(), str(post.get("body") or "").strip()]
    tags = [str(t).lstrip("#").strip() for t in (post.get("tags") or []) if str(t).strip("# ")]
    if tags and not any("#" + t in parts[1] for t in tags):
        parts.append(" ".join("#" + t for t in tags))
    out = []
    for p in parts:
        if p and p not in out and not (out and out[-1].startswith(p)):
            out.append(p)
    return "\n\n".join(out)


def shorten_rules(platform, text, lim):
    """Fit ``text`` into ``lim`` (counted the platform's way) without a model."""
    fits = lambda t: text_limit(platform, t)[0] <= lim  # noqa: E731
    lines = [ln.rstrip() for ln in text.strip().split("\n")]
    tags = []
    while lines and (re.fullmatch(r"(#[^\s#]+\s*)+", lines[-1].strip() or "-") or not lines[-1].strip()):
        last = lines.pop().strip()
        tags = last.split() + tags if last else tags
    body = "\n".join(lines).strip()
    sents = [x for x in re.split(r"(?<=[。！？!?.；;])\s*|\n+", body) if x.strip()]
    def build(ss, tg):
        b = "".join(x if re.search(r"[\u2e80-\u9fff]", x) else x + " " for x in ss).strip()
        return (b + ("\n\n" + " ".join(tg) if tg else "")).strip()
    for keep_tags in range(len(tags), -1, -1):
        for k in range(len(sents), 0, -1):
            out = build(sents[:k], tags[:keep_tags])
            if fits(out):
                return out
    out = sents[0] if sents else text
    while out and not fits(out + "…"):
        out = out[:-1]
    return (out.rstrip() + "…") if out else ""


def _day(s):
    return dt.date.fromisoformat(s)


def _iso(d):
    return d.isoformat()


def _plus_hours(at, h):
    t = dt.datetime.strptime(at, "%Y-%m-%dT%H:%M") + dt.timedelta(hours=h)
    return t.strftime("%Y-%m-%dT%H:%M")


class Calendar:
    def __init__(self, data_dir, history, outputs, bus=None, mode="mock"):
        self.path = os.path.join(data_dir, "calendar.json")
        self.history, self.outputs, self.bus, self.mode = history, outputs, bus, mode
        self._lock = threading.Lock()

    def _rows(self):
        r = read_json(self.path, []) or []
        return [x for x in r if isinstance(x, dict) and x.get("id")]

    # ------------------------------------------------------------------ read
    def _clips(self, cache, item):
        if item not in cache:
            try:
                cache[item] = {c["id"]: c for c in self.outputs.clips(item)["clips"]}
            except Exception:  # noqa: BLE001  (project moved / hidden: the post keeps what it stored)
                cache[item] = {}
        return cache[item]

    def decorate(self, rows, cache=None, everything=None):
        """rows + status, effective caption, limit / length, project, warnings (clashes against ``everything``)."""
        cache = {} if cache is None else cache
        everything = rows if everything is None else everything
        names = {}
        try:
            for e in self.history.list()["items"]:
                names[e["id"]] = e.get("name")
        except Exception:  # noqa: BLE001
            pass
        slots = {}
        for r in everything:
            if r.get("enabled", True) is not False:
                slots.setdefault((r["platform"].split(":")[0], r["at"]), []).append(r["id"])
        out = []
        for r in rows:
            r = dict(r)
            clip = self._clips(cache, r["item"]).get(r["clip"]) or {}
            own = r.get("caption")
            text = own if isinstance(own, str) else post_text(clip.get("post"))
            n, lim = text_limit(r["platform"], text)
            pf = r["platform"].split(":")[0]
            warn = []
            if r.get("enabled", True) is not False and r.get("state") != "posted":
                if not text.strip():
                    warn.append(dict(kind="no_caption", platform=pf))
                elif lim and n > lim:
                    warn.append(dict(kind="caption_too_long", platform=pf, n=n, max=lim))
                clash = [x for x in slots.get((pf, r["at"]), []) if x != r["id"]]
                if clash:
                    warn.append(dict(kind="slot_clash", platform=pf, at=r["at"], other=clash[0]))
            r.update(status=STATUS.get(r.get("state"), "draft"), enabled=r.get("enabled", True) is not False,
                     caption=text, caption_custom=isinstance(own, str), length=n, limit=lim, warnings=warn,
                     project=names.get(r["item"]), duration=clip.get("duration"),
                     cover=r.get("cover") or clip.get("cover"), title=r.get("title") or clip.get("title") or r["clip"])
            out.append(r)
        return out

    def list(self, start=None, days=7):
        allrows = self._rows()
        rows = allrows
        if start:
            need(DAY_RE.match(start), "start: YYYY-MM-DD")
            ends = _iso(_day(start) + dt.timedelta(days=int(days)))
            rows = [r for r in rows if start <= r["at"][:10] < ends]
        cache = {}
        scheduled = {(r["item"], r["clip"]) for r in allrows}
        queue = []
        for e in self.history.list()["items"]:
            if (e.get("live") or {}).get("state") in ("running", "waiting") or e.get("status") not in (
                    "done", "delivered", "packaged"):
                continue
            try:
                cl = self.outputs.clips(e["id"])["clips"]
            except Exception:  # noqa: BLE001
                continue
            cache[e["id"]] = {c["id"]: c for c in cl}
            for c in cl:
                if c["state"] in ("done", "approved", "packaged") and not c.get("extra") and \
                        (e["id"], c["id"]) not in scheduled and c.get("files"):
                    queue.append(dict(item=e["id"], clip=c["id"], title=c["title"], project=e.get("name"),
                                      cover=c.get("cover"), aspects=[f["aspect"] for f in c["files"]],
                                      duration=c.get("duration"), has_post=bool(post_text(c.get("post")))))
                if len(queue) >= 200:
                    break
        posts = self.decorate(sorted(rows, key=lambda r: r["at"]), cache, allrows)
        return dict(posts=posts, queue=queue, at=time.time())

    # ------------------------------------------------------------------ write
    def _row(self, b, clips_cache):
        need(isinstance(b, dict), "post must be an object")
        need(isinstance(b.get("item"), str) and ITEM_RE.match(b["item"]), "item: project id")
        need(isinstance(b.get("clip"), str) and 0 < len(b["clip"]) <= 120, "clip: id")
        need(isinstance(b.get("at"), str) and AT_RE.match(b["at"]), "at: YYYY-MM-DDTHH:MM")
        pl = b.get("platform") or "xiaohongshu"
        need(isinstance(pl, str) and PLATFORM_RE.match(pl), "platform: id")
        cap = b.get("caption")
        need(cap is None or (isinstance(cap, str) and len(cap) <= MAX_CAPTION), f"caption: up to {MAX_CAPTION} chars")
        if b["item"] not in clips_cache:
            clips_cache[b["item"]] = {c["id"]: c for c in self.outputs.clips(b["item"])["clips"]}
        clip = clips_cache[b["item"]].get(b["clip"])
        need(clip is not None, "no such clip")
        row = dict(id=hashlib.sha1(f"{b['item']}{b['clip']}{pl}{b['at']}{time.time()}{os.urandom(4).hex()}".encode()).hexdigest()[:12],
                   item=b["item"], clip=b["clip"], title=clip["title"], cover=clip.get("cover"), platform=pl,
                   at=b["at"], state="planned")
        if cap is not None:
            row["caption"] = cap
        return row

    def add(self, b):
        row = self._row(b, {})
        with self._lock:
            rows = self._rows()
            rows.append(row)
            write_json(self.path, rows)
        self._pub()
        return row

    def add_many(self, posts):
        """scheduleMany: every row or none (one validation pass first) -> {posts, ids} for a single undo."""
        need(isinstance(posts, list) and 0 < len(posts) <= MAX_MANY, f"posts: 1-{MAX_MANY} rows")
        cache = {}
        new = [self._row(p, cache) for p in posts]
        with self._lock:
            rows = self._rows()
            rows += new
            write_json(self.path, rows)
        self._pub()
        return dict(ok=True, posts=new, ids=[r["id"] for r in new])

    def remove_many(self, ids):
        """Unschedule (back to the queue). Only calendar rows go; the clips' files are never touched. Returns the
        removed rows so the desk's undo can put them back as they were (``restore``)."""
        need(isinstance(ids, list) and 0 < len(ids) <= MAX_MANY and all(isinstance(i, str) and ITEM_RE.match(i) for i in ids),
             "ids: post ids")
        with self._lock:
            rows = self._rows()
            gone = [r for r in rows if r["id"] in ids]
            write_json(self.path, [r for r in rows if r["id"] not in ids])
        self._pub()
        return dict(ok=True, removed=gone)

    def restore(self, posts):
        """Undo of remove_many: the same rows back (same ids, captions, states)."""
        need(isinstance(posts, list) and 0 < len(posts) <= MAX_MANY, f"posts: 1-{MAX_MANY} rows")
        keep = ("id", "item", "clip", "title", "cover", "platform", "at", "state", "caption", "enabled", "stats")
        clean = []
        for p in posts:
            need(isinstance(p, dict) and isinstance(p.get("id"), str) and ITEM_RE.match(p["id"]), "post id")
            need(isinstance(p.get("item"), str) and ITEM_RE.match(p["item"]), "item: project id")
            need(isinstance(p.get("at"), str) and AT_RE.match(p["at"]), "at: YYYY-MM-DDTHH:MM")
            need(isinstance(p.get("platform"), str) and PLATFORM_RE.match(p["platform"]), "platform: id")
            need(p.get("state", "planned") in STATES, "state")
            row = {k: p[k] for k in keep if k in p}
            if not p.get("caption_custom", True):
                row.pop("caption", None)        # a decorated row: the clip's own copy is not her edit
            clean.append(row)
        with self._lock:
            rows = self._rows()
            have = {r["id"] for r in rows}
            rows += [r for r in clean if r["id"] not in have]
            write_json(self.path, rows)
        self._pub()
        return dict(ok=True, ids=[r["id"] for r in clean])

    def update(self, pid, b):
        need(isinstance(b, dict), "body must be an object")
        with self._lock:
            rows = self._rows()
            row = next((r for r in rows if r["id"] == pid), None)
            if row is None:
                raise KeyError(f"no post {pid}")
            before = dict(row)
            if b.get("remove"):
                rows = [r for r in rows if r["id"] != pid]
            else:
                if b.get("at") is not None:
                    need(isinstance(b["at"], str) and AT_RE.match(b["at"]), "at: YYYY-MM-DDTHH:MM")
                    row["at"] = b["at"]
                if b.get("state") is not None:
                    need(b["state"] in STATES, "state: planned | ready | filled | posted")
                    row["state"] = b["state"]
                if "caption" in b:
                    cap = b["caption"]
                    need(cap is None or (isinstance(cap, str) and len(cap) <= MAX_CAPTION), f"caption: up to {MAX_CAPTION} chars")
                    if cap is None:
                        row.pop("caption", None)          # back to the clip's own copy
                    else:
                        row["caption"] = cap
                if b.get("platform") is not None:
                    need(isinstance(b["platform"], str) and PLATFORM_RE.match(b["platform"]), "platform: id")
                    row["platform"] = b["platform"]
                if b.get("enabled") is not None:
                    need(isinstance(b["enabled"], bool), "enabled: true | false")
                    if b["enabled"]:
                        row.pop("enabled", None)
                    else:
                        row["enabled"] = False
                if b.get("stats") is not None:
                    s = b["stats"]
                    need(isinstance(s, dict) and all(k in ("views", "likes") and isinstance(v, int) and 0 <= v < 10 ** 12
                                                     for k, v in s.items()), "stats: {views?, likes?} counts")
                    row["stats"] = {**(row.get("stats") or {}), **s}
            write_json(self.path, rows)
        self._pub()
        return dict(ok=True, post=row, before=before)

    def confirm_week(self, start):
        """确认本周排期: every planned post of the week (switched on) becomes ready."""
        need(isinstance(start, str) and DAY_RE.match(start), "start: YYYY-MM-DD")
        end = _iso(_day(start) + dt.timedelta(days=7))
        n = 0
        with self._lock:
            rows = self._rows()
            for r in rows:
                if start <= r["at"][:10] < end and r["state"] == "planned" and r.get("enabled", True) is not False:
                    r["state"] = "ready"
                    n += 1
            write_json(self.path, rows)
        self._pub()
        return dict(ok=True, ready=n)

    # ------------------------------------------------------------------ fill / plan
    def _week_args(self, b):
        need(isinstance(b, dict), "body must be an object")
        start = b.get("start")
        need(isinstance(start, str) and DAY_RE.match(start), "start: YYYY-MM-DD (the Monday of the week)")
        today = b.get("today") or _iso(dt.date.today())
        need(isinstance(today, str) and DAY_RE.match(today), "today: YYYY-MM-DD")
        pfs = b.get("platforms") or []
        need(isinstance(pfs, list) and len(pfs) <= 12 and all(isinstance(p, str) and PLATFORM_RE.match(p) for p in pfs),
             "platforms: [platform id]")
        times = b.get("times") or {}
        need(isinstance(times, dict) and all(isinstance(v, str) and HM_RE.match(v) for v in times.values()),
             "times: {platform: HH:MM}")
        clips = b.get("clips")
        need(clips is None or (isinstance(clips, list) and len(clips) <= MAX_MANY and all(
            isinstance(c, dict) and isinstance(c.get("item"), str) and isinstance(c.get("clip"), str) for c in clips)),
            "clips: [{item, clip}]")
        return start, today, pfs, times, clips

    def _source(self, clips):
        """The clips to place, in order: her selection, else the queue (oldest project first, as listed)."""
        q = self.list()["queue"]
        if clips:
            byk = {(c["item"], c["clip"]): c for c in q}
            return [byk.get((c["item"], c["clip"])) or dict(item=c["item"], clip=c["clip"], title=c["clip"], cover=None)
                    for c in clips]
        return q

    def fill_week(self, b):
        """一键排满本周: each free day of the week (today on) gets the next clip, on every platform at that
        platform's default time. Written in one go -> {posts, ids} (one undo)."""
        start, today, pfs, times, clips = self._week_args(b)
        need(pfs, "platforms: connect a platform first")
        per_day = int(b.get("per_day") or 1)
        need(1 <= per_day <= 4, "per_day: 1-4")
        rows = [r for r in self._rows() if r.get("enabled", True) is not False]
        taken = {r["at"][:10] for r in rows}
        src = self._source(clips)
        d0 = max(_day(start), _day(today))
        new = []
        k = 0
        for i in range(7):
            day = _day(start) + dt.timedelta(days=i)
            if day < d0 or _iso(day) in taken:
                continue
            for j in range(per_day):
                if k >= len(src):
                    break
                c = src[k]
                k += 1
                for pf in pfs:
                    at = f"{_iso(day)}T{times.get(pf) or '19:00'}"
                    new.append(dict(item=c["item"], clip=c["clip"], platform=pf, at=_plus_hours(at, 2 * j) if j else at))
        if not new:
            return dict(ok=True, posts=[], ids=[], reason="no_clips" if not src else "no_free_days")
        return self.add_many(new)

    def plan(self, b):
        """「一句话排期」 preview: text -> proposed rows (never written). Apply = add_many(drafts)."""
        need(isinstance(b, dict), "body must be an object")
        text = b.get("text")
        need(isinstance(text, str) and 0 < len(text.strip()) <= 300, "text: 1-300 chars")
        start, today, connected, times, clips = self._week_args(b)
        rule = schedule_text.parse(text)
        base = dict(text=text.strip(), rule=rule, drafts=[], adjustments=[], start=start)
        if not rule["understood"]:
            return dict(base, ok=False, reason="not_understood")
        pfs = rule["platforms"] or connected[:1] or ["xiaohongshu"]
        days = rule["days"] if rule["days"] is not None else list(range(7))
        wk = _day(start) + dt.timedelta(days=7 if rule["next_week"] else 0)
        d0 = max(wk, _day(today) + dt.timedelta(days=0 if rule["next_week"] else 1))
        if not rule["next_week"] and not any(wk + dt.timedelta(days=i) >= d0 and i in days for i in range(7)):
            wk = wk + dt.timedelta(days=7)        # nothing left this week: the plan is for next week
        src = self._source(clips)
        if not src:
            return dict(base, ok=False, reason="no_clips", start=_iso(wk))
        busy = {(r["platform"].split(":")[0], r["at"]) for r in self._rows() if r.get("enabled", True) is not False}
        drafts, adj = [], []
        k = 0
        for i in range(7):
            day = wk + dt.timedelta(days=i)
            if i not in days or day < d0:
                continue
            for j in range(rule["per_day"]):
                if k >= len(src):
                    break
                c = src[k]
                k += 1
                for pf in pfs:
                    at = f"{_iso(day)}T{rule['time'] or times.get(pf) or '19:00'}"
                    if j:
                        at = _plus_hours(at, 2 * j)
                    first = at
                    while (pf, at) in busy and at[:10] == first[:10] and at[11:13] < "23":
                        at = _plus_hours(at, 1)
                    if at != first:
                        adj.append(dict(kind="moved", platform=pf, frm=first, to=at))
                    busy.add((pf, at))
                    drafts.append(dict(item=c["item"], clip=c["clip"], title=c.get("title"), cover=c.get("cover"),
                                       project=c.get("project"), platform=pf, at=at))
        return dict(base, ok=bool(drafts), reason=None if drafts else "no_days", drafts=drafts, adjustments=adj,
                    start=_iso(wk), platforms=pfs, time=rule["time"], days=days, per_day=rule["per_day"],
                    clips=len({(d["item"], d["clip"]) for d in drafts}), from_selection=bool(clips))

    # ------------------------------------------------------------------ 「为 X 缩短」
    def shorten(self, b):
        """A post text that fits ``platform``'s limit. Real engine: the model routed for post copy (task "copy",
        with its fallbacks); without one (or when it fails / still does not fit): rules - drop whole sentences from
        the end, keep the hashtags that fit, cut with … only as the last resort. Nothing is saved here."""
        need(isinstance(b, dict), "body must be an object")
        text = b.get("text")
        need(isinstance(text, str) and 0 < len(text) <= MAX_CAPTION, "text: the caption")
        pf = b.get("platform")
        need(isinstance(pf, str) and PLATFORM_RE.match(pf), "platform: id")
        n, lim = text_limit(pf, text)
        lim = int(b.get("max") or lim or 0)
        need(lim > 0, "this platform has no text limit")
        if n <= lim:
            return dict(text=text, provider="none", length=n, limit=lim)
        if self.mode == "real":
            try:
                from vstudio import llm
                system = ("You shorten social media post captions. Keep the language, voice and the most important "
                          "hashtags; never add facts. Reply as JSON {\"text\": \"...\"}.")
                unit = "weighted characters (CJK and emoji count 2, a URL 23)" if pf.split(":")[0] == "x" else "characters"
                r = llm.complete("copy", system, f"Platform: {pf}. Limit: {lim} {unit}. Make it fit with a little room "
                                 f"to spare.\n\nCaption:\n{text}", schema={"type": "object", "properties": {
                                     "text": {"type": "string"}}, "required": ["text"]}, max_tokens=2000, timeout=120,
                                 cli_timeout=90)
                out = (r.get("json") or {}).get("text") if isinstance(r, dict) else None
                if isinstance(out, str) and out.strip() and text_limit(pf, out)[0] <= lim:
                    return dict(text=out.strip(), provider=r.get("provider") or "ai", length=text_limit(pf, out)[0], limit=lim)
            except Exception:  # noqa: BLE001  (no model / failed: the rules below still make it fit)
                pass
        out = shorten_rules(pf, text, lim)
        return dict(text=out, provider="rules", length=text_limit(pf, out)[0], limit=lim)

    def _pub(self):
        if self.bus:
            self.bus.publish("calendar")
