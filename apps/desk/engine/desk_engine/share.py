"""Share for review (the desk side of ``vstudio.project.share``): the share dialog's options (clips, versions,
privacy warnings from mask metadata), building the static review folder off the request thread, and importing a
reviewer's feedback into Inbox items (approve -> mark ready; change -> the comment pinned in the clip's chat).

Routes (app.py):
  GET  /api/share/<item>             {item, title, clips [{id, title, cover, versions [label]}], privacy, out_root}
  POST /api/share/<item>             {clips?[], quality?, footer?, title?, expiry_note?, owner_name?, reply_to?,
                                      zip?, ack?} -> {job}; events ``share`` {job, state, done, total}
  GET  /api/share-jobs/<job>         {state running|done|failed, done, total, result?, error?}
  POST /api/feedback/import          {text} -> {share, title, project, items, duplicates, unknown}

The engine library does the work in-process (the desk puts lib/ on PYTHONPATH in both modes); its review store
lives in the project (``state/review``) or work folder (``.vstudio/review``). The desk keeps only the list of
folders that have feedback (``<DESK_DATA_DIR>/feedback_owners.json``) so the Inbox can find them.
"""
import os
import re
import threading
import time
import uuid

from .common import need, read_json, write_json
from .outputs import EngineMessage, list_clips

JOB_RE = re.compile(r"^[0-9a-f]{12}$")
QUALITIES = ("small", "standard", "high")


def _sh():
    from vstudio.project import share as SH
    return SH


def _engine_msg(e):
    info = getattr(e, "info", None) or {}
    return EngineMessage(dict(code=info.get("code") or "share-error", params=info.get("params") or {},
                              message=info.get("message") or str(e), message_zh=info.get("message_zh")))


def _label(f):
    plat = (f.get("platform") or "").split(":")[0]
    names = {"xiaohongshu": "Xiaohongshu", "douyin": "Douyin", "tiktok": "TikTok", "youtube": "YouTube",
             "youtube-shorts": "Shorts", "bilibili": "Bilibili", "instagram": "Instagram"}
    asp = f.get("aspect") if f.get("aspect") and f.get("aspect") != "原尺寸" else None
    return " · ".join(x for x in (asp, names.get(plat) or (plat.title() if plat and plat != "None" else None)) if x) or "Video"


def _caption(post):
    if not post:
        return None
    tags = " ".join(f"#{t}" for t in post.get("tags") or [] if t)
    txt = "\n\n".join(x.strip() for x in (post.get("title") or "", post.get("body") or "", tags) if x and x.strip())
    return txt or None


class Share:
    def __init__(self, data_dir, history, outputs, inbox, bus=None):
        self.history, self.outputs, self.inbox, self.bus = history, outputs, inbox, bus
        self.owners_path = os.path.join(data_dir, "feedback_owners.json")
        self.jobs = {}
        self._lock = threading.Lock()
        inbox.extra.append(self.inbox_items)
        inbox.handlers["feedback"] = self._answered
        inbox.undo_hooks.append(self._undone)

    # ---------------------------------------------------------- the dialog
    def _done_clips(self, e):
        return [c for c in list_clips(e) if c.get("files") and c.get("state") not in ("queued", "running", "failed")
                and not c.get("extra")]

    def options(self, item_id):
        e = self.history.find(item_id)
        clips = self._done_clips(e)
        SH = _sh()
        scan = SH.privacy_scan(e["dir"], [dict(id=c["id"]) for c in clips])
        self.history.allow_media([c["cover"] for c in clips if c.get("cover")])
        return dict(item=item_id, title=e.get("name") or os.path.basename(e["dir"]), privacy=scan,
                    out_root=os.path.join(e["dir"], "review-links"),
                    clips=[dict(id=c["id"], title=c["title"], cover=c.get("cover"), duration=c.get("duration"),
                                versions=[_label(f) for f in c["files"]], caption=bool(c.get("post"))) for c in clips])

    def start(self, item_id, b):
        need(isinstance(b, dict), "body must be an object")
        e = self.history.find(item_id)
        clips = self._done_clips(e)
        want = b.get("clips")
        if want is not None:
            need(isinstance(want, list) and 0 < len(want) <= 500 and all(isinstance(x, str) for x in want),
                 "clips: a list of clip ids")
            clips = [c for c in clips if c["id"] in want]
        need(clips, "nothing to share: no finished clips")
        q = b.get("quality") or "standard"
        need(q in QUALITIES, f"quality: {' | '.join(QUALITIES)}")
        for k in ("title", "expiry_note", "owner_name", "reply_to"):
            need(b.get(k) is None or (isinstance(b[k], str) and len(b[k]) <= 200), f"{k}: text up to 200 characters")
        need(b.get("footer") in (None, True, False) and b.get("zip") in (None, True, False), "footer / zip: booleans")
        scan = self.options(item_id)["privacy"]
        need(not scan["needs_ack"] or b.get("ack") is True, "check the privacy warnings first (ack)")
        SH = _sh()
        sc = [dict(id=c["id"], title=c["title"], caption=_caption(c.get("post")), cover=c.get("cover"),
                   versions=[dict(file=f["path"], platform=f.get("platform") if f.get("platform") and
                                  not str(f.get("platform")).startswith("None") else None, label=_label(f))
                             for f in c["files"]],
                   ref=dict(item=c["id"], desk_item=item_id, desk_clip=c["id"], outputs=[])) for c in clips]
        title = (b.get("title") or "").strip() or e.get("name") or os.path.basename(e["dir"])
        opts = dict(title=title, footer=b.get("footer", True) is not False, quality=q, lang="auto",
                    expiry_note=(b.get("expiry_note") or "").strip() or None, reply_to=(b.get("reply_to") or "").strip() or None,
                    owner_name=(b.get("owner_name") or "").strip() or None)
        try:
            sid = SH.share_id_of(sc, dict(title=title, footer=opts["footer"], quality=q, lang="auto",
                                          expiry=opts["expiry_note"], reply_to=opts["reply_to"], owner=opts["owner_name"]))
        except SH.ShareError as ex:
            raise _engine_msg(ex) from ex
        job = uuid.uuid4().hex[:12]
        st = dict(id=job, item=item_id, state="running", done=0, total=sum(len(c["versions"]) + 1 for c in sc),
                  started=time.time(), result=None, error=None)
        with self._lock:
            self.jobs[job] = st

        def work():
            try:
                def prog(p):
                    st.update(done=p["done"], total=p["total"])
                    self._emit(st)
                r = SH.build_page(sc, SH.default_out(e["dir"], title, sid), title=title, footer=opts["footer"],
                                  quality=q, expiry_note=opts["expiry_note"], reply_to=opts["reply_to"],
                                  owner_name=opts["owner_name"], make_zip=b.get("zip", True) is not False,
                                  on_progress=prog, share_id=sid)
                SH.remember(e["dir"], r, sc)
                r["privacy"] = scan
                st.update(state="done", result=r, done=st["total"])
            except Exception as ex:  # noqa: BLE001
                info = getattr(ex, "info", None)
                st.update(state="failed", error=dict(info) if info else dict(code="share-error", message=str(ex),
                                                                            message_zh=str(ex), params={}))
            self._emit(st)
        threading.Thread(target=work, daemon=True).start()
        return dict(ok=True, job=job, total=st["total"])

    def job(self, job):
        need(JOB_RE.match(job or ""), "bad job id")
        st = self.jobs.get(job)
        need(st is not None, f"no share job {job}")
        return {k: v for k, v in st.items()}

    def _emit(self, st):
        if self.bus:
            self.bus.publish("share", job=st["id"], state=st["state"], done=st["done"], total=st["total"])

    # ---------------------------------------------------------- feedback
    def _owners(self):
        v = read_json(self.owners_path, [])
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def import_feedback(self, b):
        need(isinstance(b, dict) and isinstance(b.get("text"), str) and 0 < len(b["text"]) <= 200_000,
             "text: the feedback code or file contents")
        SH = _sh()
        try:
            r = SH.import_feedback(b["text"], pin=False)
        except SH.ShareError as ex:
            raise _engine_msg(ex) from ex
        owners = self._owners()
        if r["owner"] not in owners:
            write_json(self.owners_path, owners + [r["owner"]])
        entry = self._entry_of(r["owner"])
        for it in r["items"]:
            if it["decision"] != "change":
                continue
            ref = it.get("ref") or {}
            pid = ref.get("desk_item") or (entry or {}).get("id")
            if not pid:
                continue
            try:
                self.outputs.chat_add(pid, ref.get("desk_clip") or it["clip"], dict(
                    role="user", status="note",
                    text=f"{it['reviewer'] or 'Reviewer'}: {it['comment']}" if it["comment"] else it["reviewer"] or "Reviewer"))
            except Exception:  # noqa: BLE001  (the inbox item still carries the comment)
                pass
        if self.bus:
            self.bus.publish("inbox")
        return dict(ok=True, share=r["share"], title=r["title"], reviewer=r["reviewer"],
                    project=(entry or {}).get("id"), items=len(r["items"]), duplicates=r["duplicates"],
                    unknown=r["unknown"])

    def _entry_of(self, owner):
        real = os.path.realpath(owner)
        for e in self.history.list()["items"]:
            if os.path.realpath(e["dir"]) == real:
                return e
        return None

    def inbox_items(self):
        SH = _sh()
        out = []
        for owner in self._owners():
            if not os.path.isdir(owner):
                continue
            items = SH.feedback_items(owner)
            if not items:
                continue
            e = self._entry_of(owner) or {}
            proj = dict(id=e.get("id"), name=e.get("name") or os.path.basename(owner), kind=e.get("kind"),
                        thumb=e.get("thumb"), type=e.get("type"))
            covers = {}
            if e.get("id"):
                try:
                    covers = {c["id"]: c.get("cover") for c in list_clips(e)}
                except Exception:  # noqa: BLE001
                    covers = {}
            for it in items:
                ref = it.get("ref") or {}
                cid = ref.get("desk_clip") or it["clip"]
                appr = it["decision"] == "approve"
                out.append(dict(
                    key=it["id"], kind="feedback-approve" if appr else "feedback-change", group="review" if appr else "choose",
                    project=proj, code="inbox.feedbackApproved" if appr else "inbox.feedbackChange",
                    params=dict(who=it.get("reviewer") or "", clip=it.get("title") or cid), text=it.get("comment") or None,
                    options=[dict(id=it["clip"], clip_id=cid if e.get("id") else None, clip_title=it.get("title"),
                                  text=it.get("comment") or it.get("title") or cid, quote=None, cover=covers.get(cid),
                                  kind="feedback", checked=True)],
                    minutes=1 if appr else 3, source="feedback", feedback=dict(owner=owner, id=it["id"]),
                    at=_ts(it.get("imported"))))
        self.history.allow_media([o["cover"] for i in out for o in i["options"] if o.get("cover")])
        return out

    def _answered(self, item, answer):
        f = item.get("feedback") or {}
        _sh().resolve(f["owner"], f["id"])

    def _undone(self, keys):
        SH = _sh()
        for owner in self._owners():
            if not os.path.isdir(owner):
                continue
            for it in SH.feedback_items(owner, status="all"):
                if it["id"] in keys and it.get("status") == "done":
                    SH.reopen(owner, it["id"])


def _ts(iso):
    try:
        return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None
