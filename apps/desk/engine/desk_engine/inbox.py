"""Inbox (需要你): every decision waiting for the creator, across all projects, as codes + params the desk renders
in the UI language. Sources:

  * the engine's checkpoints (``python -m vstudio.project inbox list --json``) when the command exists;
  * plain work folders: the "creator should confirm" bullets of PICKS.md / NOTES.md (kind ``confirm``);
  * batches and project batches: finished clips not reviewed yet + red QC checks (kind ``review``);
  * live runs parked at a checkpoint (``.vstudio/status.json`` waiting + needs_you, kind ``checkpoint``).

Answers for desk-side items are kept in ``<DESK_DATA_DIR>/inbox.json`` (never written into the creator's folder);
an answer can be taken back (undo toast). Item: {key, kind, group choose|review|spend|other, project {id, name,
kind, thumb}, code, params, text, options [{id, code?, text, clip, checked}], minutes, source, at, archived?}.
``archived: true`` marks an item of an archived project (history ``hidden``): only that project's page lists it.
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

# checkpoints whose answer is a file the engine drafts (vstudio.project.drafts): shown as the draft, in plain words
AUTHOR_KINDS = ("author", "script-lock", "storyboard-approval", "media-selection")
GROUP = {"confirm": "choose", "filler-confirm": "choose", "hook-pick": "choose", "segment-approval": "choose",
         "keywords": "choose", "cover-pick": "choose", "take-selection": "choose", "media-selection": "choose",
         "script-lock": "choose",
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


def author_block(p, pd):
    """An ``author`` checkpoint (promo-recut "Check what's kept", an explainer's script, a launch kit's details ...)
    -> what the Inbox shows: never the file. {labels, recipe, checkpoint, state missing | template | drafted | hers,
    review (the engine's plain-language view: a summary, lines, the transcript with kept / cut parts, a script's
    text), can_draft (the engine can draft it: "Draft it for me" / "ask in plain words"), draft_error, exists, file
    (only for "Advanced: open the file")}. An older payload (no ``draft_state``) is read again here: a file that is
    still the seeded template / SYNTHETIC example is "template" - never shown as hers, never her answer."""
    pay = {}
    if p.get("item") and p.get("id") and pd:
        pay = read_json(os.path.join(pd, "state", "checkpoints", str(p["item"]), f"{p['id']}.json"), None) or {}
    get = lambda k: p.get(k) if p.get(k) is not None else pay.get(k)  # noqa: E731
    f = get("file")
    if not f:
        return None                           # a script lock / storyboard with no file of its own: options as usual
    recipe, cid = get("recipe"), p.get("id") or pay.get("id")
    st, review = pay.get("draft_state"), pay.get("review")
    can = False
    try:
        from vstudio.project import drafts as DR
        if not st:
            st = DR.state(f, get("template"), cid, recipe)
        if review is None and st in ("drafted", "hers") and f:
            review = DR.outline_review(f, DR.read_side(f, cid))
        can = bool(DR._drafter(recipe, cid)) or bool(f and not os.path.isdir(f) and f.lower().endswith(DR.TEXT_EXT))
    except Exception:  # noqa: BLE001  (an engine without drafts: the file decides)
        st = st or ("hers" if f and os.path.exists(f) else "missing")
    return dict(labels=get("labels") if isinstance(get("labels"), dict) else {}, recipe=recipe, checkpoint=cid,
                state=st, review=review, can_draft=can, draft_error=pay.get("draft_error"),
                exists=st in ("drafted", "hers"), is_dir=bool(get("is_dir")), file=f, doc=get("doc"))


def _project_name(pd):
    """A project the history does not list: its own name (project.yaml), not its folder ("01-AIGC")."""
    try:
        import yaml
        with open(os.path.join(pd, "project.yaml"), encoding="utf-8") as f:
            n = (yaml.safe_load(f) or {}).get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
    except Exception:  # noqa: BLE001
        pass
    return os.path.basename(pd)


def _item_video(pd, item):
    """The item's own recording (its first video input): the Inbox row's picture when the project has no cover yet."""
    try:
        import yaml
        with open(os.path.join(pd, "project.yaml"), encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return None
    its = [i for i in d.get("items") or [] if isinstance(i, dict)]
    it = next((i for i in its if i.get("id") == item), its[0] if its else {})
    ins = dict(d.get("inputs") or {}, **(it.get("inputs") or {}))
    for v in ins.values():
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str) and x.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv")) and os.path.isfile(x):
                return x
    return None


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
        # she approved the draft: {done: true}; + spans (keep spans: what she selected to keep in the transcript) or
        # content (the file's text); the generic ticks of an older desk ({approve: ["0"]}) mean the same
        v = answer if isinstance(answer, dict) else {}
        out = dict(done=True)
        if isinstance(v.get("content"), str):
            out["content"] = v["content"]
        if isinstance(v.get("spans"), list) and all(isinstance(x, list) and len(x) == 2 for x in v["spans"]):
            out["spans"] = [[float(a), float(b)] for a, b in v["spans"]]
        return out
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
        self._drafting = {}      # inbox key -> started (a draft being written: "Drafting ..." on the item)

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

    def _archived_dirs(self):
        try:
            return set(self.history.archived_dirs())
        except Exception:  # noqa: BLE001  (a history without archives: nothing is archived)
            return set()

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
                hidden = self._archived_dirs()
                arch_dir = None                   # archived rows, read only when an entry belongs to one
                for p in (doc.get("entries") or doc.get("items") or doc.get("pending") or []) if isinstance(doc, dict) else []:
                    if not isinstance(p, dict):
                        continue
                    pd = os.path.realpath(p.get("project") or p.get("dir") or "")
                    archived = pd in hidden
                    if archived and arch_dir is None:
                        arch_dir = {os.path.realpath(r["dir"]): r for r in self.history.list(archived=True)["items"]}
                    e = (arch_dir or {}).get(pd) or {} if archived else by_dir.get(pd) or {}
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
                    author = author_block(p, pd) if kind in AUTHOR_KINDS else None
                    if author:
                        raw = []                          # the draft is the decision, never a "☑ 1 0" option row
                        allow += [x for x in (author["file"], author["doc"]) if x]
                        author["drafting"] = self._drafting.get(_key(pd, p.get("id"), p.get("item"))) is not None
                    video = None if e.get("thumb") else _item_video(pd, p.get("item"))
                    if video:
                        allow.append(video)
                    items.append(dict(key=_key(pd, p.get("id"), p.get("item"), p.get("digest")), kind=kind,
                                      group=GROUP.get(kind, "other"),
                                      project=dict(id=e.get("id"), name=e.get("name") or _project_name(pd),
                                                   kind=e.get("kind"), thumb=e.get("thumb"), type=e.get("type"),
                                                   video=video),
                                      code=("inbox.spend" if spend and params.get("amount") is not None
                                            else f"checkpoint.{kind}"), params=params,
                                      text=(p.get("labels") or {}).get("zh") or p.get("label"),
                                      label=p.get("label_info"),
                                      options=[_with_clip(L.engine_option(o, p.get("default"), i), o, p.get("item"))
                                               for i, o in enumerate(raw)],
                                      previews=[] if author else p.get("previews") or [],
                                      default=p.get("default"), minutes=1 if not author else 2, source="engine",
                                      engine=dict(dir=pd, id=p.get("id"), item=p.get("item")),
                                      **({"archived": True} if archived else {}),
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
        # an archived project's checkpoints stay listed but marked ``archived``: the Inbox, Home, the badge and the
        # triage queue leave them out; the project's own page still shows them (restore -> they are plain again)
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

    def redraft(self, key, instruction=None):
        """「Draft it for me」/「Ask in plain words」 on an author item: the engine drafts the file again (following
        ``instruction``), in the background (a model call takes a minute or two); the item says "Drafting ..." and
        the Inbox reloads when the new draft is in (``vstudio.project.drafts.redraft``)."""
        need(isinstance(key, str) and re.match(r"^[0-9a-f]{16}$", key), "key: an inbox key")
        need(instruction is None or (isinstance(instruction, str) and len(instruction) <= 1000), "instruction: text")
        it = next((i for i in self.list()["items"] if i["key"] == key), None)
        need(it is not None and it.get("author"), f"no draft to change for {key}")
        need(it["author"].get("can_draft"), "this step can't be drafted by the AI")
        eng = it["engine"]
        dk = _key(eng["dir"], eng["id"], eng.get("item"))
        need(dk not in self._drafting, "already drafting")
        self._drafting[dk] = time.time()
        if self.bus:
            self.bus.publish("inbox")

        def go():
            try:
                from vstudio.project import drafts as DR
                from vstudio.project.core import Project
                DR.redraft(Project(eng["dir"]), eng["id"], eng.get("item"), (instruction or "").strip() or None,
                           request=self._request_of(eng["dir"]))
            except Exception as e:  # noqa: BLE001  (the item stays as it was; the reason is logged)
                print(f"[inbox] redraft failed for {eng['dir']} {eng['id']}: {e}", file=sys.stderr, flush=True)
            finally:
                self._drafting.pop(dk, None)
                self._forget_engine()
                if self.bus:
                    self.bus.publish("inbox")
        threading.Thread(target=go, daemon=True).start()
        return dict(ok=True, drafting=True)

    def _request_of(self, pdir):
        """Her request for a project an older app made from Home without keeping it (project.yaml has no
        ``prompt``): the plan it was applied from, ``<data>/intake/<request id>.json`` (the project's parent folder is
        named after the request)."""
        rid = os.path.basename(os.path.dirname(os.path.abspath(pdir)))
        if not re.match(r"^[0-9a-f]{12}$", rid):
            return None
        plan = read_json(os.path.join(os.path.dirname(self.path), "intake", f"{rid}.json"), None) or {}
        texts = [plan.get("prompt") or ""] + [r.get("prompt") or "" for r in plan.get("revisions") or []
                                              if isinstance(r, dict)]
        return "\n".join(t for t in texts if t).strip() or None

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
