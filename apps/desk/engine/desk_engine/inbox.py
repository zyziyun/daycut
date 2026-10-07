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
import sqlite3
import threading
import time

from . import works as WK
from .common import need, read_json, write_json

GROUP = {"confirm": "choose", "filler-confirm": "choose", "hook-pick": "choose", "segment-approval": "choose",
         "cover-pick": "choose", "take-selection": "choose", "media-selection": "choose", "script-lock": "choose",
         "review": "review", "publish": "review", "budget-approval": "spend", "voice-pick": "spend",
         "checkpoint": "other", "consent": "other", "privacy-masks": "other"}


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


class Inbox:
    def __init__(self, data_dir, history, runner=None, mode="mock", bus=None):
        self.path = os.path.join(data_dir, "inbox.json")
        self.history, self.runner, self.mode, self.bus = history, runner, mode, bus
        self._lock = threading.Lock()
        self._real = None

    def real(self):
        if self._real is None:
            ok = False
            if self.mode == "real" and self.runner is not None:
                try:
                    txt = self.runner.sibling("vstudio.project").text(["inbox", "--help"])
                    ok = "answer" in txt and "invalid choice" not in txt
                except Exception:  # noqa: BLE001
                    ok = False
            self._real = ok
        return self._real

    def _answers(self):
        a = read_json(self.path, {}) or {}
        return a if isinstance(a, dict) else {}

    # ---------------------------------------------------------- listing
    def list(self):
        answers = self._answers()
        items = []
        hist = self.history.list()["items"]
        for e in hist:
            proj = dict(id=e["id"], name=e.get("name"), kind=e["kind"], thumb=e.get("thumb"), type=e.get("type"))
            if e["kind"] == "work":
                conf = WK.confirmations(e["dir"])
                if conf:
                    k = _key(e["dir"], "confirm", json.dumps(conf, ensure_ascii=False))
                    if k not in answers:
                        items.append(dict(key=k, kind="confirm", group="choose", project=proj, code="inbox.confirmEdits",
                                          params=dict(n=len(conf)), text=None, minutes=max(1, len(conf) // 2),
                                          options=[dict(id=f"o{i}", clip=c.get("clip"), text=c["text"], checked=True)
                                                   for i, c in enumerate(conf)], source="picks",
                                          at=e.get("updated")))
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
        if self.real():
            try:
                doc = self.runner.sibling("vstudio.project").json(["inbox", "list", "--json"], timeout=120)
                by_dir = {os.path.realpath(e["dir"]): e for e in hist}
                for p in (doc.get("items") or doc.get("pending") or []) if isinstance(doc, dict) else []:
                    if not isinstance(p, dict):
                        continue
                    pd = os.path.realpath(p.get("project") or p.get("dir") or "")
                    e = by_dir.get(pd) or {}
                    kind = p.get("kind") or p.get("checkpoint_kind") or "checkpoint"
                    items.append(dict(key=_key(pd, p.get("id"), p.get("item"), p.get("digest")), kind=kind,
                                      group=GROUP.get(kind, "other"),
                                      project=dict(id=e.get("id"), name=e.get("name") or os.path.basename(pd),
                                                   kind=e.get("kind"), thumb=e.get("thumb"), type=e.get("type")),
                                      code=f"checkpoint.{kind}", params=dict(n=p.get("n_options") or 0),
                                      text=(p.get("labels") or {}).get("zh") or p.get("label"),
                                      options=p.get("options") or [], previews=p.get("previews") or [],
                                      default=p.get("default"), minutes=1, source="engine",
                                      engine=dict(dir=pd, id=p.get("id"), item=p.get("item"))))
            except Exception:  # noqa: BLE001
                pass
        thumbs = [i["project"]["thumb"] for i in items if i["project"].get("thumb")]
        self.history.allow_media(thumbs)
        items.sort(key=lambda i: ({"failed": -1, "choose": 0, "spend": 1, "review": 2}.get(i["group"], 3),
                                  -(i.get("at") or 0)))
        return dict(items=items, at=time.time())

    # ---------------------------------------------------------- answering
    def answer(self, keys, answer=None):
        need(isinstance(keys, list) and 0 < len(keys) <= 200 and all(isinstance(k, str) and re.match(r"^[0-9a-f]{16}$", k)
                                                                       for k in keys), "keys: 1-200 inbox keys")
        need(answer is None or (isinstance(answer, dict) and len(json.dumps(answer)) < 20000), "answer: object")
        cur = {i["key"]: i for i in self.list()["items"]}
        done = []
        for k in keys:
            it = cur.get(k)
            need(it is not None, f"no inbox item {k}")
            if it["source"] == "engine":
                eng = it["engine"]
                args = ["inbox", "answer", "--project", eng["dir"], "--id", str(eng["id"])]
                if eng.get("item"):
                    args += ["--item", str(eng["item"])]
                args += ["--answer", json.dumps(answer, ensure_ascii=False)] if answer else ["--default"]
                self.runner.sibling("vstudio.project").json(args + ["--json"], timeout=300)
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
        return dict(ok=True, answered=done)

    def undo(self, keys):
        need(isinstance(keys, list) and 0 < len(keys) <= 200, "keys: list")
        with self._lock:
            a = self._answers()
            back = [k for k in keys if a.pop(k, None) is not None]
            write_json(self.path, a)
        if self.bus:
            self.bus.publish("inbox")
        return dict(ok=True, restored=back)
