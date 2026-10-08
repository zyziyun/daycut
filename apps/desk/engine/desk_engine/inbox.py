"""Inbox (需要你): every decision waiting for the creator, across all projects, as codes + params the desk renders
in the UI language. Sources:

  * the engine's checkpoints (``python -m vstudio.project inbox list --json``) when the command exists;
  * plain work folders: the "creator should confirm" bullets of PICKS.md / NOTES.md (kind ``confirm``);
  * batches and project batches: finished clips not reviewed yet + red QC checks (kind ``review``);
  * live runs parked at a checkpoint (``.vstudio/status.json`` waiting + needs_you, kind ``checkpoint``).

Answers for desk-side items are kept in ``<DESK_DATA_DIR>/inbox.json`` (never written into the creator's folder);
an answer can be taken back (undo toast). Item: {key, kind, group choose|review|spend|other, project {id, name,
kind, thumb}, code, params, text, options [{id, code?, text, clip, checked}], minutes, source, at}.
"""
import hashlib
import json
import os
import re
import sys
import sqlite3
import threading
import time

from . import inbox_labels as L
from . import works as WK
from .common import need, read_json, write_json

GROUP = {"confirm": "choose", "filler-confirm": "choose", "hook-pick": "choose", "segment-approval": "choose",
         "cover-pick": "choose", "take-selection": "choose", "media-selection": "choose", "script-lock": "choose",
         "review": "review", "publish": "review", "budget-approval": "spend", "voice-pick": "spend",
         "checkpoint": "other", "consent": "other", "privacy-masks": "other"}


_PLATFORM_NAMES = {"tiktok": "TikTok", "youtube-shorts": "YouTube Shorts", "youtube": "YouTube",
                   "xiaohongshu": "Xiaohongshu", "douyin": "Douyin", "bilibili": "Bilibili", "instagram": "Instagram",
                   "x": "X", "wechat-channels": "WeChat Channels"}


def _export_label(path):
    """exports/tiktok-vertical.mp4 -> "TikTok · vertical" (a publish checkpoint lists the files it would publish)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for orient in ("vertical", "horizontal", "square", "full"):
        if stem.endswith("-" + orient):
            name = stem[: -len(orient) - 1]
            return f"{_PLATFORM_NAMES.get(name, name)} · {orient}"
    return _PLATFORM_NAMES.get(stem, stem)


def _with_clip(opt, raw, item):
    """An engine option that points at a video plays in the inbox and links to its clip in the editor."""
    if item and not opt.get("clip_id"):
        opt["clip_id"] = item
    if raw.get("file") and str(raw["file"]).endswith((".mp4", ".mov")):
        opt["file"] = raw["file"]
    return opt


PREVIEW_LINES = 40


def _head(path, n=PREVIEW_LINES, max_bytes=64000):
    """The first ``n`` lines of a text file + whether there is more (None when it cannot be read as text)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(max_bytes)
    except (OSError, UnicodeDecodeError, ValueError):
        return None, False
    lines = text.splitlines()
    return "\n".join(lines[:n]), len(lines) > n or len(text) >= max_bytes


def author_block(p, pd):
    """An ``author`` checkpoint (she writes / approves a file: promo-recut "Keep spans", "Cards, highlights, montage")
    -> what the Inbox shows instead of options: {labels, help {zh, en}, file, exists, template, doc, format, preview,
    more, preview_of file|template}. The payload file (state/checkpoints/<item>/<id>.json) fills what the engine's
    inbox entry leaves out (template, doc)."""
    pay = {}
    if p.get("item") and p.get("id") and pd:
        pay = read_json(os.path.join(pd, "state", "checkpoints", str(p["item"]), f"{p['id']}.json"), None) or {}
    get = lambda k: p.get(k) if p.get(k) is not None else pay.get(k)  # noqa: E731
    f = get("file")
    exists = bool(get("exists")) and bool(f) and os.path.exists(f)
    tpl = get("template")
    src = f if exists else (tpl if tpl and os.path.isfile(tpl) else None)
    preview, more = (None, False)
    if src and os.path.isfile(src):
        preview, more = _head(src)
    help_ = get("help") if isinstance(get("help"), dict) else {}
    return dict(labels=get("labels") if isinstance(get("labels"), dict) else {}, help=help_, file=f, exists=exists,
                is_dir=bool(get("is_dir")), template=tpl, doc=get("doc"), format=get("format"), preview=preview,
                more=more, preview_of=("file" if src == f else "template") if src else None)


def open_path(path):
    """Open a file in the default app for its type (a text file: the text editor on macOS)."""
    import subprocess
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-t", path] if os.path.isfile(path) else ["open", path])
    elif os.name == "nt":
        os.startfile(path)  # noqa: S606  (a path the inbox listed, not user input)
    else:
        subprocess.Popen(["xdg-open", path])


def engine_answer(kind, answer):
    """The desk's generic answer (``{approve: [option ids], keep: [...]}`` from her ticks) in the shape the engine
    checkpoint's schema wants; None = use the checkpoint's default."""
    if kind == "author":
        # she wrote / approved the file: {done: true} (+ content when the desk sends the text itself); the generic
        # ticks of an older desk ({approve: ["0"]}) mean the same
        v = answer if isinstance(answer, dict) else {}
        return dict(done=True, **({"content": v["content"]} if isinstance(v.get("content"), str) else {}))
    if not isinstance(answer, dict) or "approve" not in answer or not isinstance(answer.get("approve"), list):
        return answer or None
    ids = [int(x) for x in answer["approve"] if str(x).lstrip("-").isdigit()]
    if kind in ("hook-pick", "cover-pick"):
        return dict(pick=ids[0]) if len(ids) == 1 else None      # one tick = her pick; all / none = the default
    if kind == "publish":
        return dict(approve=bool(answer["approve"]) or not answer.get("keep"))
    if kind == "filler-confirm":
        keep = [int(x) for x in answer.get("keep") or [] if str(x).lstrip("-").isdigit()]
        return dict(approve=ids, keep=keep)
    return answer


def _key(*parts):
    return hashlib.sha1("\0".join(str(p) for p in parts).encode()).hexdigest()[:16]


def qc_issues(jobdir):
    """jobs/<id>/qc/qc.json -> [{code, at, value, text}] for the failed checks (codes = the engine's check names)."""
    doc = read_json(os.path.join(jobdir, "qc", "qc.json"), None) or {}
    out = []
    for c in doc.get("checks") or []:
        if isinstance(c, dict) and c.get("ok") is False:
            reason = c.get("reason") or ""
            at = re.search(r"@\s*([0-9.]+)\s*s", reason)
            dur = re.search(r"for\s*([0-9.]+)\s*s", reason)
            quote = re.search(r"'([^']{1,80})'", reason)
            out.append(dict(code=c.get("name") or "qc", severity=c.get("severity"), at=float(at.group(1)) if at else None,
                            value=c.get("value"), seconds=float(dur.group(1)) if dur else None,
                            quote=quote.group(1) if quote else None, text=reason))
    return out


def _batch_review(entry):
    store = os.path.join(entry["dir"], "state") if entry["kind"] == "project" else entry["dir"]
    db = os.path.join(store, "batch.db")
    if not os.path.exists(db):
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            rows = con.execute("SELECT id, state, qc, review FROM jobs ORDER BY ord, id").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    todo = [r for r in rows if r[1] in ("done", "pilot-review") and not r[3]]
    if not todo:
        return None
    issues = {}
    for jid, _st, qc, _rv in todo:
        if qc == "red":
            issues[jid] = qc_issues(os.path.join(store, "jobs", jid))
    passed = len([r for r in rows if r[2] == "green"])
    return dict(todo=[r[0] for r in todo], red=[j for j in issues], issues=issues, passed=passed, total=len(rows))


def confirm_options(d, conf):
    """PICKS.md bullets -> plain-language options (inbox_labels.humanize) + the media files they preview."""
    text = ""
    for n in ("PICKS.md", "NOTES.md"):
        p = os.path.join(d, n)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    text += f.read(200000) + "\n"
            except OSError:
                pass
    spans = L.picks_spans(text)
    try:
        clips = [c for c in WK.clips(d) if c.get("files")]
    except Exception:  # noqa: BLE001
        clips = []
    by_letter = {}
    for c in clips:
        if c.get("letter") and not c.get("extra") and c["letter"] not in by_letter:
            by_letter[c["letter"]] = c
    words = {}

    def words_for(letter):
        if letter not in words:
            from .outputs import _asr_for
            c = by_letter.get(letter)
            words[letter] = _asr_for(c["files"][0]["path"]) if c else []
        return words[letter]
    source = L.find_source(d, L.source_name(text))
    opts = [L.humanize(c, spans, by_letter.get, words_for, source, i) for i, c in enumerate(conf)]
    media = [source] if source else []
    for o in opts:
        c = by_letter.get(o["clip"])
        if c:
            o["file"] = c["files"][0]["path"]
            o["cover"] = c.get("cover")
            media += [o["file"]] + ([o["cover"]] if o["cover"] else [])
    return opts, media


class Inbox:
    def __init__(self, data_dir, history, runner=None, mode=None, bus=None):
        self.path = os.path.join(data_dir, "inbox.json")
        self.history, self.runner, self.mode, self.bus = history, runner, mode, bus
        self._lock = threading.Lock()
        self._real = None
        self._engine_doc = (0.0, None)
        self._engine_lock = threading.Lock()
        self.extra = []          # more sources: callables -> [item] (Create: takes to pick, paused runs ...)
        self.handlers = {}       # source -> fn(item, answer): desk-side items that act when answered (feedback)
        self.undo_hooks = []     # fn(keys): an answer taken back

    def real(self):
        """The engine has project checkpoints (``vstudio.project.inbox``): checked in this process, no CLI start."""
        if self._real is None:
            ok = False
            if self.mode == "real" and self.runner is not None:
                try:
                    from vstudio.project import inbox as PI
                    ok = callable(getattr(PI, "inbox", None)) and callable(getattr(PI, "answer", None))
                except Exception as e:  # noqa: BLE001
                    print(f"[inbox] the engine's project inbox does not load: {e}", file=sys.stderr, flush=True)
            self._real = ok
        return self._real

    ENGINE_TTL = 5.0

    def _engine_inbox(self):
        """``vstudio.project inbox`` (every project's pending checkpoints), read in this process and kept for a few
        seconds: the Inbox, Home and the sidebar badge poll it, and a CLI start per poll cost 1.5-4.5 s of CPU while
        the app sat idle. An answer / undo drops the copy."""
        with self._engine_lock:
            at, doc = self._engine_doc
            if doc is not None and time.time() - at < self.ENGINE_TTL:
                return doc
            from vstudio.project import inbox as PI
            doc = json.loads(json.dumps(PI.inbox(), ensure_ascii=False, default=str))   # the CLI's JSON, same shape
            self._engine_doc = (time.time(), doc)
            return doc

    def _forget_engine(self):
        with self._engine_lock:
            self._engine_doc = (0.0, None)

    def _answers(self):
        a = read_json(self.path, {}) or {}
        return a if isinstance(a, dict) else {}

    # ---------------------------------------------------------- listing
    def list(self):
        answers = self._answers()
        items, allow = [], []
        hist = self.history.list()["items"]
        for e in hist:
            proj = dict(id=e["id"], name=e.get("name"), kind=e["kind"], thumb=e.get("thumb"), type=e.get("type"))
            if e["kind"] == "work":
                conf = WK.confirmations(e["dir"])
                if conf:
                    k = _key(e["dir"], "confirm", json.dumps(conf, ensure_ascii=False))
                    if k not in answers:
                        opts, media = confirm_options(e["dir"], conf)
                        allow += media
                        items.append(dict(key=k, kind="confirm", group="choose", project=proj, code="inbox.confirmEdits",
                                          params=dict(n=len(conf)), text=None, minutes=max(1, len(conf) // 2),
                                          options=opts, source="picks", at=e.get("updated")))
            else:
                rv = _batch_review(e)
                if rv:
                    k = _key(e["dir"], "review", ",".join(rv["todo"]))
                    if k not in answers:
                        codes = {}
                        for lst in rv["issues"].values():
                            for i in lst:
                                if i.get("severity") in (None, "red"):
                                    codes[i["code"]] = codes.get(i["code"], 0) + 1
                        items.append(dict(key=k, kind="review", group="review", project=proj,
                                          code="inbox.reviewClips" if rv["red"] else "inbox.reviewAll",
                                          params=dict(n=len(rv["red"]) or len(rv["todo"]), passed=rv["passed"],
                                                      total=rv["total"]),
                                          reasons=[dict(code=c, n=n) for c, n in codes.items()], text=None,
                                          minutes=max(1, round((len(rv["red"]) or len(rv["todo"])) * 1.2)),
                                          jobs=rv["red"] or rv["todo"], source="batch", at=e.get("updated")))
            fail = e.get("failure")
            if fail:
                k = _key(e["dir"], "failed", str(fail.get("at")))
                if k not in answers:
                    items.append(dict(key=k, kind="failed", group="failed", project=proj,
                                      code=f"inbox.failed.{fail.get('code') or 'unknown'}",
                                      params=dict(provider=fail.get("provider")), text=None, minutes=1,
                                      failure=fail, source="pilot", at=fail.get("at")))
                continue
            live = e.get("live") or {}
            if live.get("needs_you") and not any(i["project"]["id"] == e["id"] for i in items):
                k = _key(e["dir"], "live", live.get("heartbeat"))
                if k not in answers:
                    items.append(dict(key=k, kind="checkpoint", group="other", project=proj, code=None, params={},
                                      text=live.get("message"), minutes=1, source="live", at=live.get("heartbeat")))
        engine_read = False
        if self.real():
            try:
                doc = self._engine_inbox()
                engine_read = True
                by_dir = {os.path.realpath(e["dir"]): e for e in hist}
                for p in (doc.get("entries") or doc.get("items") or doc.get("pending") or []) if isinstance(doc, dict) else []:
                    if not isinstance(p, dict):
                        continue
                    pd = os.path.realpath(p.get("project") or p.get("dir") or "")
                    e = by_dir.get(pd) or {}
                    kind = p.get("kind") or p.get("checkpoint_kind") or "checkpoint"
                    spend = kind == "budget-approval"
                    params = dict(n=p.get("n_options") or 0)
                    if spend:
                        params.update(L.spend_params(p))
                    raw = [o for o in p.get("options") or [] if isinstance(o, dict)]
                    if kind == "publish":                 # the exported videos (not their covers), by platform
                        raw = [dict(o, labels=dict(en=_export_label(o["file"]), zh=_export_label(o["file"])))
                               for o in raw if str(o.get("file") or "").endswith((".mp4", ".mov"))
                               and os.sep + "exports" + os.sep in str(o.get("file"))]
                        allow += [o["file"] for o in raw]
                    author = author_block(p, pd) if kind == "author" else None
                    if author:
                        raw = []                          # the file is the decision, never a "☑ 1 0" option row
                        allow += [x for x in (author["file"], author["template"], author["doc"]) if x]
                    items.append(dict(key=_key(pd, p.get("id"), p.get("item"), p.get("digest")), kind=kind,
                                      group=GROUP.get(kind, "other"),
                                      project=dict(id=e.get("id"), name=e.get("name") or os.path.basename(pd),
                                                   kind=e.get("kind"), thumb=e.get("thumb"), type=e.get("type")),
                                      code=("inbox.spend" if spend and params.get("amount") is not None
                                            else f"checkpoint.{kind}"), params=params,
                                      text=(p.get("labels") or {}).get("zh") or p.get("label"),
                                      label=p.get("label_info"),
                                      options=[_with_clip(L.engine_option(o, p.get("default"), i), o, p.get("item"))
                                               for i, o in enumerate(raw)],
                                      previews=p.get("previews") or [],
                                      default=p.get("default"), minutes=1 if not author else 5, source="engine",
                                      engine=dict(dir=pd, id=p.get("id"), item=p.get("item")),
                                      **({"author": author, "labels": author["labels"]} if author else {})))
            except Exception:  # noqa: BLE001
                pass
        # a run parked at a checkpoint shows up twice (its live status + the engine's own entry): keep the engine's,
        # which has the options. For a project the engine's inbox is the whole truth: its last run's "needs you"
        # outlives the answers until the next run writes its status, and would read "A decision is waiting" for
        # nothing
        asked = {i["project"]["id"] for i in items if i["source"] == "engine"}
        items = [i for i in items if not (i["source"] == "live" and (i["project"]["id"] in asked or (
            engine_read and i["project"].get("kind") == "project")))]
        for src in self.extra:
            try:
                items += [i for i in src() if i["key"] not in answers]
            except Exception:  # noqa: BLE001  (an optional source never breaks the inbox)
                pass
        thumbs = [i["project"]["thumb"] for i in items if i["project"].get("thumb")]
        self.history.allow_media(thumbs + allow)
        # quickest first (the inbox reads top-down: what takes a minute goes before what takes ten); failures lead
        items.sort(key=lambda i: (0 if i["group"] == "failed" else 1, i.get("minutes") or 1,
                                  {"choose": 0, "spend": 1, "review": 2}.get(i["group"], 3), -(i.get("at") or 0)))
        day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        done = [a for a in answers.values() if isinstance(a, dict) and (a.get("at") or 0) >= day0]
        return dict(items=items, at=time.time(), done_today=len(done))

    # ---------------------------------------------------------- answering
    def answer(self, keys, answer=None):
        need(isinstance(keys, list) and 0 < len(keys) <= 200 and all(isinstance(k, str) and re.match(r"^[0-9a-f]{16}$", k)
                                                                       for k in keys), "keys: 1-200 inbox keys")
        need(answer is None or (isinstance(answer, dict) and len(json.dumps(answer)) < 20000), "answer: object")
        cur = {i["key"]: i for i in self.list()["items"]}
        done, dirs = [], []
        for k in keys:
            it = cur.get(k)
            need(it is not None, f"no inbox item {k}")
            if it["source"] == "engine":
                eng = it["engine"]
                args = ["inbox", "answer", "--project", eng["dir"], "--id", str(eng["id"])]
                if eng.get("item"):
                    args += ["--item", str(eng["item"])]
                value = engine_answer(it.get("kind"), answer)
                args += ["--answer", json.dumps(value, ensure_ascii=False)] if value is not None else ["--default"]
                try:
                    self.runner.sibling("vstudio.project").json(args + ["--json"], timeout=300)
                finally:
                    self._forget_engine()
                if eng.get("dir") and eng["dir"] not in dirs:
                    dirs.append(eng["dir"])
            elif it["source"] in self.handlers:
                self.handlers[it["source"]](it, answer)
            done.append(k)
        with self._lock:
            a = self._answers()
            for k in done:
                if cur[k]["source"] != "engine":
                    a[k] = dict(answer=answer or "default", at=time.time(), kind=cur[k]["kind"],
                                project=cur[k]["project"]["id"])
            write_json(self.path, a)
        if self.bus:
            self.bus.publish("inbox")
        self.resume(dirs)
        return dict(ok=True, answered=done)

    def resume(self, dirs):
        """Answers recorded for these projects: continue their runs in the background (nothing when nothing waits)."""
        self._forget_engine()
        if dirs:
            threading.Thread(target=self._resume, args=(list(dirs),), daemon=True).start()

    def _resume(self, dirs):
        """The last open question of a project answered: its run goes on (pilot.resume_after_answer)."""
        from . import pilot
        for d in dirs:
            try:
                if pilot.resume_after_answer(self.runner, d, bus=self.bus) and self.bus:
                    self.bus.publish("batches")
            except Exception as e:  # noqa: BLE001  (the answer itself is saved; say why nothing ran)
                print(f"[inbox] resume after answer failed for {d}: {e}", file=sys.stderr, flush=True)

    opener = staticmethod(open_path)

    def open_file(self, key, which="file"):
        """「在编辑器中打开」 on an author item: its file (or the template / the guide) in the default app. Only paths
        the inbox itself lists can be opened."""
        need(isinstance(key, str) and re.match(r"^[0-9a-f]{16}$", key), "key: an inbox key")
        need(which in ("file", "template", "doc"), "which: file | template | doc")
        it = next((i for i in self.list()["items"] if i["key"] == key), None)
        need(it is not None and it.get("author"), f"no author item {key}")
        path = it["author"].get(which)
        need(bool(path) and os.path.exists(path), f"the {which} does not exist yet")
        self.opener(path)
        return dict(ok=True, path=path)

    def undo(self, keys):
        need(isinstance(keys, list) and 0 < len(keys) <= 200, "keys: list")
        with self._lock:
            a = self._answers()
            back = [k for k in keys if a.pop(k, None) is not None]
            write_json(self.path, a)
        self._forget_engine()
        for f in self.undo_hooks:
            f(back)
        if self.bus:
            self.bus.publish("inbox")
        return dict(ok=True, restored=back)
