"""Share for review: a read-only static review page for a project, a batch, or a few clips, and the way the
reviewer's answers come back (``python -m vstudio.project share`` / ``feedback``). Guide: apps/docs guides/share-for-review.

One folder, opened from disk in any browser, nothing hosted and nothing tracked::

    <out>/index.html           player + title + platform versions + caption + Approve / Request a change per clip
    <out>/review.json          the same data for machines (schema below; no local paths, no project internals)
    <out>/media/<clip>-<n>.mp4 compressed previews (H.264 + AAC, faststart, metadata stripped)
    <out>/posters/<clip>.jpg   one poster per clip (the cover when there is one, else a frame)
    <out>/captions/<clip>.txt  the post caption, plain text
    <out>/README.txt           how to send it (zip, or upload the folder to your own Drive / Dropbox)
    <out>.zip                  the same folder, zipped (deterministic: fixed timestamps, sorted entries)

Responses come back without a server (option A, the default): the page keeps the reviewer's choices in the browser
(localStorage) and "Send my feedback" gives a short code (``RFB1.<base64url JSON>``), a mailto: draft, a Copy
button and a ``.reelfold.json`` download. ``import_feedback`` (CLI ``feedback import``; the desk: Inbox > Import
feedback) reads any of them back into feedback items: approve -> "mark ready", change -> the comment pinned on the
clip (a chat turn on the clip's output). Option B: the folder can sit on any host the creator picks (see the guide);
``HOSTS`` is the seam for a future hosted review link (studio tier): a host publishes the folder and fetches feedback,
the built-in ``folder`` host does neither.

Deterministic: the same clips + options give byte-identical files (no clock in the page, ``-bitexact`` encodes
with libx264, fixed zip timestamps); the share id is a hash of the clip ids, titles, file signatures and options.

    clips = collect_clips(project_dir)                     # or build your own list (see CLIP below)
    scan = privacy_scan(project_dir, clips)                # masked / unmasked people -> warnings before sharing
    r = share(project_dir, quality="standard", footer=True) # collect + build + zip + remember the share
    r = build_page(clips, out_dir, title="Week 12")        # just the folder (desk sidecar: its own clip list)
    doc = parse_feedback(pasted_text)                      # code / JSON / an email body that contains the code
    r = import_feedback(pasted_text)                       # -> feedback items in the owner's review store
    feedback_items(project_dir); resolve(project_dir, fid) # approve -> mark_ready(project_dir, clip)

CLIP (input of build_page): {id, title, caption?, cover?, versions [{file, platform?, label?}], ref?} - ``ref`` is
opaque (kept in the share record, never written to the page): how the owner maps feedback back to its outputs.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile

from vstudio.batch.util import read_json, sha1_json, write_json

PAGE_VERSION = 1
FEEDBACK_KIND = "reelfold-review-feedback"
CODE_PREFIX = "RFB1."
CODE_RE = re.compile(r"RFB1\.([A-Za-z0-9_-]{8,})")
CLIP_ID_RE = re.compile(r"^\w[\w .()+\-]{0,119}$")
DECISIONS = ("approve", "change")
QUALITY = {   # short side (px), x264 CRF, AAC bitrate
    "small": dict(short=540, crf=30, audio="80k", label="540p"),
    "standard": dict(short=720, crf=27, audio="96k", label="720p"),
    "high": dict(short=1080, crf=23, audio="128k", label="1080p"),
}
QUALITY_ALIASES = {"540p": "small", "720p": "standard", "1080p": "high", "sd": "small", "hd": "high"}
TEMPLATE = os.path.join(os.path.dirname(__file__), "templates", "review_page.html")
FOOTER_URL = "https://reelfold.com"
PLATFORM_NAMES = {"xiaohongshu": "Xiaohongshu", "douyin": "Douyin", "tiktok": "TikTok", "youtube": "YouTube",
                  "youtube-shorts": "Shorts", "bilibili": "Bilibili", "instagram": "Instagram", "x": "X",
                  "shipinhao": "Channels", "kuaishou": "Kuaishou", "reels": "Reels"}
MAX_FEEDBACK_BYTES = 200_000
MAX_COMMENT = 2000


class ShareError(ValueError):
    """code + English / Chinese message (the desk localises by code)."""

    def __init__(self, code, message, message_zh=None, **params):
        super().__init__(message)
        self.info = dict(code=code, message=message, message_zh=message_zh or message, params=params)


def _msg(code, en, zh, level="warn", **params):
    return dict(code=code, level=level, message=en, message_zh=zh, params=params)


# --------------------------------------------------------------------------- hosts (option B / future hosted links)
class FolderHost:
    """The default: nothing leaves the machine. The creator sends the zip or uploads the folder wherever she likes.

    A hosted review link (studio tier, not built) implements the same two methods: ``publish`` uploads the folder
    and returns {url}; ``fetch_feedback`` returns feedback documents (``parse_feedback`` shape) for a share."""
    name = "folder"
    hosted = False

    def publish(self, folder, record):
        return dict(host=self.name, url=None, path=folder)

    def fetch_feedback(self, record):
        return []


HOSTS = {"folder": FolderHost}


def register_host(name, cls):
    """Plug in a host (a hosted review-link service). ``cls()`` must provide publish(folder, record) and
    fetch_feedback(record)."""
    HOSTS[name] = cls


def get_host(name="folder"):
    if name not in HOSTS:
        raise ShareError("unknown-host", f"no review host {name!r} (available: {', '.join(sorted(HOSTS))})",
                         f"没有这个审片托管方式 {name!r}", host=name)
    return HOSTS[name]()


# --------------------------------------------------------------------------- where things live
def owner_dirs(d):
    """-> (owner dir, kind project|batch|work, review store dir)."""
    d = os.path.abspath(d)
    if os.path.exists(os.path.join(d, "project.yaml")):
        return d, "project", os.path.join(d, "state", "review")
    if os.path.exists(os.path.join(d, "batch.db")):
        return d, "batch", os.path.join(d, "review-links", ".store")
    return d, "work", os.path.join(d, ".vstudio", "review")


def _home_index():
    from vstudio.batch.clients import home
    return os.path.join(home(), "shares.json")


def default_out(d, title, share_id):
    owner = owner_dirs(d)[0]
    name = re.sub(r"[^\w\u3400-\u9fff-]+", "-", title or "review", flags=re.UNICODE).strip("-")[:40] or "review"
    return os.path.join(owner, "review-links", f"{name}-{share_id[:6]}")


# --------------------------------------------------------------------------- collect the clips of a project
def _read_text(path, limit=20000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def _caption_from(post, base=None):
    """post: a dict {title, body, tags}, a path to post copy (.md / .txt), or text."""
    if not post:
        return None
    if isinstance(post, dict):
        tags = " ".join(f"#{t}" for t in post.get("tags") or [] if t)
        parts = [post.get("title") or "", post.get("body") or "", tags]
        txt = "\n\n".join(p.strip() for p in parts if p and p.strip())
        return txt or None
    p = str(post)
    if base and not os.path.isabs(p):
        p = os.path.join(base, p)
    if os.path.isfile(p):
        txt = _read_text(p) or ""
        txt = re.sub(r"^#{1,6}\s*", "", txt, flags=re.M).strip()
        return txt or None
    if os.path.sep in p or re.search(r"\.(md|txt)$", p, re.I):
        return None
    return str(post).strip() or None


def _version_label(platform, w=None, h=None):
    asp = None
    if w and h:
        from math import gcd
        g = gcd(int(w), int(h)) or 1
        a, b = int(w) // g, int(h) // g
        known = {(3, 4): "3:4", (9, 16): "9:16", (16, 9): "16:9", (1, 1): "1:1", (4, 5): "4:5", (4, 3): "4:3"}
        asp = known.get((a, b)) or next((v for (x, y), v in known.items() if abs(x / y - w / h) < 0.02), f"{w}x{h}")
    name = None
    if platform:
        base, _, orient = str(platform).partition(":")
        name = PLATFORM_NAMES.get(base, base.replace("-", " ").title())
    return " · ".join(x for x in (asp, name) if x) or "Video"


def collect_clips(d, outputs=None, items=None):
    """A recipe project (one clip per item, its platform exports as versions) or an adopted work folder (one clip
    per video) -> CLIP dicts with ``ref`` = {item?, outputs [output ids]}."""
    from . import outputs as O
    if owner_dirs(d)[1] == "batch":
        d, kind = os.path.abspath(d), "batch"
    else:
        d, kind = O._owner(d)
    want_o = set(outputs or [])
    want_i = set(items or [])
    clips = {}
    if kind in ("project", "batch"):
        for o in (O._project_outputs(d) if kind == "project" else _batch_outputs(d)):
            if want_i and o["item"] not in want_i:
                continue
            if want_o and o["id"] not in want_o and o["item"] not in want_o:
                continue
            c = clips.setdefault(o["item"], dict(id=o["item"], title=o.get("title") or o["item"], caption=None,
                                                 cover=None, versions=[], ref=dict(item=o["item"], outputs=[])))
            base = os.path.dirname(o["file"])
            plat = f"{o['platform']}:{o['orientation']}" if o.get("platform") and o.get("orientation") else o.get("platform")
            c["versions"].append(dict(file=o["file"], platform=plat))
            c["ref"]["outputs"].append(o["id"])
            if not c["cover"] and o.get("cover"):
                cv = o["cover"] if os.path.isabs(o["cover"]) else os.path.join(base, o["cover"])
                c["cover"] = cv if os.path.isfile(cv) else None
            if not c["caption"]:
                c["caption"] = _caption_from(o.get("post"), base) or _caption_from((o.get("_params") or {}).get("post"))
    else:
        for rel in O._work_files(d):
            oid = rel
            stem = os.path.splitext(os.path.basename(rel))[0]
            cid = re.sub(r"[^\w.\-\u3400-\u9fff]+", "_", stem).strip("._")[:60] or sha1_json(rel, 8)
            if (want_o and oid not in want_o and cid not in want_o) or (want_i and cid not in want_i):
                continue
            while cid in clips:
                cid = f"{cid}_{sha1_json(rel, 4)}"
            f = os.path.join(d, rel)
            here = os.path.dirname(f)
            cover = next((os.path.join(here, n) for n in (f"{stem}_cover.jpg", f"{stem}.cover.jpg", f"{stem}_cover.png")
                          if os.path.isfile(os.path.join(here, n))), None)
            cap = next((_caption_from(os.path.join(here, n)) for n in (f"{stem}.post.md", f"{stem}_post.md",
                                                                       f"{stem}.txt") if os.path.isfile(os.path.join(here, n))), None)
            clips[cid] = dict(id=cid, title=stem.replace("_", " "), caption=cap, cover=cover,
                              versions=[dict(file=f, platform=None)], ref=dict(item=None, outputs=[oid]))
    return list(clips.values())


def _batch_outputs(bdir):
    """A plain ``vstudio.batch`` folder (batch.db): every finished job's exports, like ``_project_outputs``."""
    from vstudio.batch.store import Store
    from .outputs import VIDEO
    st = Store(bdir)
    out = []
    try:
        for j in st.jobs():
            if j["state"] in ("dropped", "failed", "planned", "running"):
                continue
            rows = st.stage_rows(j["id"])
            for e in ((rows.get("export") or {}).get("out") or {}).get("exports") or []:
                f = e.get("file")
                if not f or not os.path.isfile(f) or os.path.splitext(f)[1].lower() not in VIDEO:
                    continue
                tag = "-".join(x for x in (e.get("platform"), e.get("orientation")) if x) or os.path.basename(f)
                out.append(dict(id=f"{j['id']}/{tag}", file=os.path.abspath(f), item=j["id"], platform=e.get("platform"),
                                orientation=e.get("orientation"), title=(j["params"] or {}).get("title"),
                                cover=e.get("cover"), post=e.get("post"), _params=j["params"] or {}))
    finally:
        st.close()
    return out


# --------------------------------------------------------------------------- privacy
def privacy_scan(d, clips=None):
    """Warnings before anything leaves the machine: people masked (check the masks hold) or shown unmasked, guests
    without recorded consent, hidden screen regions. Reads the project's own mask metadata (call-clips ``guests`` /
    ``no_mask``, the coverage report, ``privacy_exclude``) and privacy stickers added in the output editor.
    -> {ok, warnings [{code, level warn|info, message, message_zh, params {clips}}], needs_ack}"""
    from . import outputs as O
    d, kind, _ = owner_dirs(d)
    warns = []
    ids = [c["id"] for c in clips] if clips else None
    params, manifest_kinds = {}, set()
    if kind == "project":
        try:
            import yaml
            with open(os.path.join(d, "project.yaml"), encoding="utf-8") as f:
                pdoc = yaml.safe_load(f) or {}
            params = pdoc.get("params") or {}
            from .core import Project
            manifest_kinds = {c.get("kind") for c in Project(d).manifest.get("checkpoints") or []}
        except Exception:  # noqa: BLE001  (a scan never blocks; it only warns)
            pass
    guests = params.get("guests") or []
    if params.get("no_mask") and (guests or "privacy-masks" in manifest_kinds):
        warns.append(_msg("unmasked-people", "Other people appear without a mask (masking was switched off).",
                          "片子里有人没有打码（遮脸被关掉了）。", clips=ids))
    elif guests or "privacy-masks" in manifest_kinds:
        warns.append(_msg("masked-people", "Some clips show masked people. Check the masks hold in every frame "
                          "before you share.", "部分片子里有打码的人。分享前确认每一帧都遮住了。", clips=ids))
    bad = _coverage_failures(d) if kind == "project" else []
    if bad:
        warns.append(_msg("mask-gaps", "A face mask does not cover the face in every frame.",
                          "有遮脸贴纸没有在每一帧都盖住脸。", clips=bad))
    if "consent" in manifest_kinds:
        warns.append(_msg("guest-consent", "This project has guests. Make sure they agreed to this review.",
                          "这个项目有嘉宾，确认他们同意给别人审片。", level="info", clips=ids))
    if params.get("privacy_exclude"):
        warns.append(_msg("hidden-regions", "Parts of the screen are hidden in every clip; previews keep them hidden.",
                          "部分屏幕区域已隐藏，预览同样隐藏。", level="info"))
    stickers = []
    try:
        rows = O.list_outputs(d)["outputs"] if kind == "project" or (kind == "work" and O.owner_kind(d) == "work") else []
        for r in rows:
            doc = read_json(os.path.join(r["edit_dir"], "edit.json"), None) or {}
            st = doc.get("state") or {}
            effs = st.get("effects") or []
            if any((e or {}).get("effect") == "privacy-sticker" for e in effs if isinstance(e, dict)):
                stickers.append(r.get("item") or os.path.splitext(os.path.basename(r["id"]))[0])
    except Exception:  # noqa: BLE001
        pass
    if stickers and not any(w["code"] == "masked-people" for w in warns):
        warns.append(_msg("masked-people", "Some clips show masked people. Check the masks hold in every frame "
                          "before you share.", "部分片子里有打码的人。分享前确认每一帧都遮住了。",
                          clips=sorted(set(stickers))))
    if ids is not None:
        for w in warns:
            if w["params"].get("clips"):
                w["params"]["clips"] = [c for c in w["params"]["clips"] if c in ids] or w["params"]["clips"]
    return dict(ok=not any(w["level"] == "warn" for w in warns), warnings=warns,
                needs_ack=any(w["level"] == "warn" for w in warns))


def _coverage_failures(pdir):
    try:
        from vstudio.batch.store import Store
        st = Store(os.path.join(pdir, "state"))
        try:
            out = []
            for j in st.jobs():
                cov = ((st.stage_rows(j["id"]).get("coverage") or {}).get("out") or {})
                if cov and (cov.get("ok") is False or any(t.get("ok") is False for t in cov.get("tracks") or [])):
                    out.append(j["id"])
            return out
        finally:
            st.close()
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- media
def _ffmpeg():
    try:
        from vstudio.h264 import ffmpeg_path
        return ffmpeg_path() or "ffmpeg"
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _probe(path):
    from vstudio import media
    i = media.probe(path)
    return dict(w=int(i.get("display_w") or i["w"]), h=int(i.get("display_h") or i["h"]),
                duration=float(i.get("duration") or 0.0), has_audio=bool(i.get("has_audio")))


def _even(x):
    x = int(round(x))
    return max(2, x - (x % 2))


def target_size(w, h, short):
    s = min(w, h)
    if s <= short:
        return _even(w), _even(h)
    k = short / s
    return _even(w * k), _even(h * k)


def _run(cmd):
    """ffmpeg as written: previews are always libx264 (plays in every browser, byte-identical re-runs), so the
    ``vstudio.h264`` encoder rewrite is bypassed."""
    from vstudio import h264
    kw = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    if getattr(h264, "_ORIG_INIT", None):
        kw["_vstudio_raw"] = True
    try:
        p = subprocess.Popen(cmd, **kw)
        _, err = p.communicate()
    except OSError as e:
        raise ShareError("no-ffmpeg", f"ffmpeg is not available: {e}", "找不到 ffmpeg") from e
    if p.returncode != 0:
        raise ShareError("encode-failed", f"ffmpeg failed: {(err or '').strip()[-400:]}",
                         "ffmpeg 转码失败", cmd=" ".join(cmd[:3]))


def encode_preview(src, dst, quality="standard"):
    q = QUALITY[quality]
    info = _probe(src)
    w, h = target_size(info["w"], info["h"], q["short"])
    cmd = [_ffmpeg(), "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
           "-map_chapters", "-1", "-vf", f"scale={w}:{h}:flags=bicubic,format=yuv420p", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", str(q["crf"]), "-profile:v", "high", "-threads", "4",
           "-c:a", "aac", "-b:a", q["audio"], "-ac", "2", "-movflags", "+faststart",
           "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", dst]
    _run(cmd)
    return dict(w=w, h=h, duration=round(info["duration"], 2))


def make_poster(src_video, cover, dst, short):
    if cover and os.path.isfile(cover):
        ci = _probe(cover)
        w, h = target_size(ci["w"], ci["h"], short)
        _run([_ffmpeg(), "-v", "error", "-y", "-i", cover, "-vf", f"scale={w}:{h}:flags=bicubic", "-frames:v", "1",
              "-q:v", "4", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", dst])
        return
    info = _probe(src_video)
    w, h = target_size(info["w"], info["h"], short)
    at = min(1.0, max(0.0, info["duration"] / 3))
    _run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", src_video, "-vf", f"scale={w}:{h}:flags=bicubic",
          "-frames:v", "1", "-q:v", "4", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", dst])


def _file_sig(path):
    st = os.stat(path)
    h = hashlib.sha1(str(st.st_size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if st.st_size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def _safe_name(cid, i=None):
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", cid).strip("-")[:40]
    s = s or "clip"
    return f"{i:02d}-{s}-{sha1_json(cid, 4)}" if i is not None else s


# --------------------------------------------------------------------------- the page
def _norm_quality(q):
    q = QUALITY_ALIASES.get(q or "standard", q or "standard")
    if q not in QUALITY:
        raise ShareError("bad-quality", f"quality: {' | '.join(QUALITY)}", "画质只能是 small / standard / high",
                         value=q)
    return q


def _check_clips(clips):
    if not clips:
        raise ShareError("no-clips", "nothing to share: no finished clips", "没有可分享的成片")
    seen = set()
    for c in clips:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not CLIP_ID_RE.match(c["id"]):
            raise ShareError("bad-clip", f"bad clip id {c.get('id') if isinstance(c, dict) else c!r}", "片子 id 不对")
        if c["id"] in seen:
            raise ShareError("bad-clip", f"duplicate clip id {c['id']}", "片子 id 重复")
        seen.add(c["id"])
        vs = [v for v in c.get("versions") or [] if isinstance(v, dict) and v.get("file") and os.path.isfile(v["file"])]
        if not vs:
            raise ShareError("no-file", f"clip {c['id']} has no video file", f"片子 {c['id']} 没有视频文件",
                             clip=c["id"])
        c["versions"] = vs


def share_id_of(clips, opts):
    basis = dict(opts=opts, clips=[dict(id=c["id"], title=c.get("title"), caption=c.get("caption"),
                                         cover=_file_sig(c["cover"]) if c.get("cover") and os.path.isfile(c["cover"]) else None,
                                         v=[[_file_sig(v["file"]), v.get("platform"), v.get("label")] for v in c["versions"]])
                                    for c in clips])
    return sha1_json(basis, 20)


def build_page(clips, out_dir, title="Review", footer=True, quality="standard", lang="auto", expiry_note=None,
               reply_to=None, owner_name=None, make_zip=True, on_progress=None, share_id=None):
    """Write the review folder (+ zip). Clips in the given order. -> {ok, share, dir, index, zip, json, clips [..],
    bytes, quality}. Nothing in the folder names a local path."""
    quality = _norm_quality(quality)
    _check_clips(clips)
    if lang not in ("auto", "en", "zh"):
        raise ShareError("bad-lang", "lang: auto | en | zh", "语言只能是 auto / en / zh")
    title = (str(title or "Review").strip() or "Review")[:120]
    opts = dict(title=title, footer=bool(footer), quality=quality, lang=lang, expiry=(expiry_note or "")[:200] or None,
                reply_to=(reply_to or "")[:200] or None, owner=(owner_name or "")[:80] or None)
    sid = share_id or share_id_of(clips, opts)
    out_dir = os.path.abspath(out_dir)
    if os.path.isdir(out_dir):
        if not os.path.exists(os.path.join(out_dir, "review.json")) and os.listdir(out_dir):
            raise ShareError("out-not-empty", f"{out_dir} exists and is not a review folder", "输出文件夹不是空的",
                             dir=out_dir)
        shutil.rmtree(out_dir)
    tmp = out_dir + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    for sub in ("media", "posters", "captions"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=True)
    q = QUALITY[quality]
    total = sum(len(c["versions"]) for c in clips) + len(clips)
    done = 0
    page_clips = []
    try:
        for i, c in enumerate(clips, 1):
            base = _safe_name(c["id"], i)
            vers = []
            for k, v in enumerate(c["versions"], 1):
                rel = f"media/{base}-{k}.mp4"
                meta = encode_preview(v["file"], os.path.join(tmp, rel), quality)
                vers.append(dict(file=rel, platform=v.get("platform"),
                                 label=v.get("label") or _version_label(v.get("platform"), meta["w"], meta["h"]),
                                 w=meta["w"], h=meta["h"], duration=meta["duration"],
                                 bytes=os.path.getsize(os.path.join(tmp, rel))))
                done += 1
                if on_progress:
                    on_progress(dict(done=done, total=total, clip=c["id"], what="video"))
            prel = f"posters/{base}.jpg"
            make_poster(c["versions"][0]["file"], c.get("cover"), os.path.join(tmp, prel), q["short"])
            done += 1
            if on_progress:
                on_progress(dict(done=done, total=total, clip=c["id"], what="poster"))
            caption = (c.get("caption") or "").strip()[:5000] or None
            crel = None
            if caption:
                crel = f"captions/{base}.txt"
                with open(os.path.join(tmp, crel), "w", encoding="utf-8", newline="\n") as f:
                    f.write(caption + "\n")
            page_clips.append(dict(id=c["id"], title=(c.get("title") or c["id"])[:160], caption=caption,
                                   caption_file=crel, poster=prel, versions=vers))
        data = dict(kind="reelfold-review", version=PAGE_VERSION, share=sid, title=title, owner=opts["owner"],
                    lang=lang, quality=dict(name=quality, label=q["label"]), footer=opts["footer"],
                    footer_url=FOOTER_URL if opts["footer"] else None, expiry_note=opts["expiry"],
                    reply_to=opts["reply_to"], feedback=dict(kind=FEEDBACK_KIND, version=1, code_prefix=CODE_PREFIX,
                                                             endpoint=None),
                    clips=page_clips)
        write_json_stable(os.path.join(tmp, "review.json"), data)
        with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(render_html(data))
        with open(os.path.join(tmp, "README.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(readme_text(data))
        os.replace(tmp, out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    zpath = None
    if make_zip:
        zpath = out_dir + ".zip"
        zip_folder(out_dir, zpath)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(out_dir) for f in fs)
    return dict(ok=True, share=sid, dir=out_dir, index=os.path.join(out_dir, "index.html"),
                json=os.path.join(out_dir, "review.json"), zip=zpath, bytes=size,
                zip_bytes=os.path.getsize(zpath) if zpath else None, quality=quality, footer=opts["footer"],
                clips=[dict(id=c["id"], title=c["title"], versions=len(c["versions"])) for c in page_clips])


def write_json_stable(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def render_html(data):
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    esc = (data["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return tpl.replace("__TITLE__", esc).replace("__REVIEW_DATA__", blob)


def readme_text(data):
    return (f"{data['title']} - review page made with Reelfold\n\n"
            "Open index.html in any browser (double-click it). Everything works offline: no account, no upload,\n"
            "no tracking. Watch each clip, press Approve or Request a change, then Send my feedback and send the\n"
            "code or the file back to whoever shared this with you.\n\n"
            "Sharing this folder: send the zip, or upload the whole folder to a shared Google Drive, Dropbox or\n"
            "OneDrive folder (keep index.html next to media/ and posters/). Delete the shared copy when the review\n"
            "is done; nothing else needs cleaning up.\n")


def zip_folder(folder, zpath):
    """Deterministic zip: sorted entries, fixed timestamps and permissions; videos stored, text deflated."""
    root = os.path.basename(folder.rstrip(os.sep))
    files = []
    for dp, dns, fns in os.walk(folder):
        dns.sort()
        for fn in sorted(fns):
            files.append(os.path.join(dp, fn))
    tmp = zpath + ".part"
    with zipfile.ZipFile(tmp, "w") as z:
        for p in sorted(files, key=lambda x: os.path.relpath(x, folder).replace(os.sep, "/")):
            arc = f"{root}/{os.path.relpath(p, folder).replace(os.sep, '/')}"
            zi = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            stored = p.lower().endswith((".mp4", ".jpg", ".png"))
            zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            with open(p, "rb") as f:
                z.writestr(zi, f.read(), compresslevel=None if stored else 9)
    os.replace(tmp, zpath)
    return zpath


# --------------------------------------------------------------------------- share = collect + build + remember
def remember(d, result, clips, host="folder", hosted=None):
    """Keep the share record (clip id -> ref) in the owner's review store and index it in $VSTUDIO_HOME so a
    pasted feedback code finds its project."""
    owner, kind, store = owner_dirs(d)
    rec = dict(share=result["share"], owner=owner, kind=kind, dir=result["dir"], zip=result["zip"],
               title=read_json(result["json"], {}).get("title"), host=host, hosted=hosted,
               created=time.strftime("%Y-%m-%dT%H:%M:%S"),
               clips=[dict(id=c["id"], title=c.get("title"), ref=c.get("ref") or {}) for c in clips])
    write_json(os.path.join(store, "shares", f"{result['share']}.json"), rec)
    idx = _home_index()
    rows = [r for r in (read_json(idx, []) or []) if isinstance(r, dict) and r.get("share") != result["share"]]
    rows.append(dict(share=result["share"], owner=owner, title=rec["title"], created=rec["created"]))
    try:
        write_json(idx, rows[-500:])
    except OSError:
        pass
    return rec


def share(d, out=None, outputs=None, items=None, quality="standard", footer=True, title=None, lang="auto",
          expiry_note=None, reply_to=None, owner_name=None, make_zip=True, host="folder", on_progress=None,
          clips=None):
    """Collect the clips of a project / work folder (or take ``clips``), build the page, remember the share.
    -> build_page result + {privacy, host}."""
    h = get_host(host)
    owner, kind, _ = owner_dirs(d)
    clips = clips if clips is not None else collect_clips(owner, outputs=outputs, items=items)
    if title is None:
        title = _owner_title(owner, kind)
    quality = _norm_quality(quality)
    _check_clips(clips)
    opts = dict(title=title, footer=bool(footer), quality=quality, lang=lang, expiry=expiry_note or None,
                reply_to=reply_to or None, owner=owner_name or None)
    sid = share_id_of(clips, opts)
    out = out or default_out(owner, title, sid)
    r = build_page(clips, out, title=title, footer=footer, quality=quality, lang=lang, expiry_note=expiry_note,
                   reply_to=reply_to, owner_name=owner_name, make_zip=make_zip, on_progress=on_progress, share_id=sid)
    hosted = h.publish(r["dir"], dict(share=sid)) if h.hosted else None
    remember(owner, r, clips, host=h.name, hosted=hosted)
    r.update(privacy=privacy_scan(owner, clips), host=h.name, url=(hosted or {}).get("url"))
    return r


def _owner_title(owner, kind):
    if kind == "project":
        try:
            import yaml
            with open(os.path.join(owner, "project.yaml"), encoding="utf-8") as f:
                y = yaml.safe_load(f) or {}
            if y.get("name"):
                return str(y["name"])
        except Exception:  # noqa: BLE001
            pass
    if kind == "work":
        rec = read_json(os.path.join(owner, ".vstudio", "work.json"), {}) or {}
        if rec.get("title"):
            return str(rec["title"])
    return os.path.basename(owner.rstrip(os.sep)) or "Review"


def find_share(share_id, owner=None):
    """-> the share record, from ``owner``'s store or the $VSTUDIO_HOME index."""
    cands = []
    if owner:
        cands.append(owner)
    for r in read_json(_home_index(), []) or []:
        if isinstance(r, dict) and r.get("share") == share_id and r.get("owner"):
            cands.append(r["owner"])
    for o in cands:
        rec = read_json(os.path.join(owner_dirs(o)[2], "shares", f"{share_id}.json"), None)
        if isinstance(rec, dict):
            return rec
    return None


# --------------------------------------------------------------------------- feedback
def _b64url_decode(s):
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def parse_feedback(text):
    """A pasted code (``RFB1.…``, alone or inside an email / chat message), the downloaded ``.reelfold.json`` or
    its JSON text -> {kind, version, share, reviewer, at, clips [{id, decision approve|change, comment}]}."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    if isinstance(text, dict):
        doc = text
    else:
        text = str(text or "")
        if len(text.encode("utf-8")) > MAX_FEEDBACK_BYTES:
            raise ShareError("feedback-too-large", "that feedback is too large", "反馈内容太大")
        short = None
        if CODE_PREFIX in re.sub(r"\s+", "", text):
            # the code alone, or inside a message (mail apps may wrap it: then try it with the breaks removed)
            cands = [m.group(1) for m in CODE_RE.finditer(text)] + \
                [m.group(1) for m in CODE_RE.finditer(re.sub(r"\s+", "", text))]
            for c in cands:
                try:
                    v = json.loads(_b64url_decode(c).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(v, dict) and v.get("k") == "rf":
                    short = v
                    break
            if short is None:
                raise ShareError("bad-feedback", "the feedback code is damaged (copy it again, all of it)",
                                 "反馈码不完整，请完整复制后再试")
        if short is not None:
            doc = dict(kind=FEEDBACK_KIND, version=short.get("v"), share=short.get("s"), reviewer=short.get("n"),
                       at=short.get("t"), clips=[dict(id=x[0], decision={"a": "approve", "c": "change"}.get(x[1]),
                                                      comment=x[2] if len(x) > 2 else "")
                                                 for x in short.get("c") or [] if isinstance(x, list) and len(x) >= 2])
        else:
            s, e = text.find("{"), text.rfind("}")
            if s < 0 or e <= s:
                raise ShareError("bad-feedback", "no feedback found: paste the code or drop the .reelfold.json file",
                                 "没有找到反馈：请粘贴反馈码，或拖入 .reelfold.json 文件")
            try:
                doc = json.loads(text[s:e + 1])
            except ValueError as ex:
                raise ShareError("bad-feedback", "the feedback file is damaged", "反馈文件已损坏") from ex
    return validate_feedback(doc)


def validate_feedback(doc):
    if not isinstance(doc, dict) or doc.get("kind") != FEEDBACK_KIND:
        raise ShareError("bad-feedback", "not Reelfold review feedback", "不是 Reelfold 的审片反馈")
    if doc.get("version") != 1:
        raise ShareError("feedback-version", f"feedback version {doc.get('version')!r} is not supported",
                         "这个版本的反馈不支持", version=doc.get("version"))
    sid = doc.get("share")
    if not isinstance(sid, str) or not re.match(r"^[0-9a-f]{8,40}$", sid):
        raise ShareError("bad-feedback", "the feedback does not say which review it answers", "反馈缺少审片编号")
    rows = []
    seen = set()
    for c in doc.get("clips") or []:
        if not isinstance(c, dict):
            continue
        cid, dec = c.get("id"), c.get("decision")
        if not isinstance(cid, str) or not CLIP_ID_RE.match(cid) or dec not in DECISIONS or cid in seen:
            continue
        seen.add(cid)
        com = c.get("comment") if isinstance(c.get("comment"), str) else ""
        rows.append(dict(id=cid, decision=dec, comment=com.strip()[:MAX_COMMENT]))
    if not rows:
        raise ShareError("empty-feedback", "the feedback has no answers", "反馈里没有任何回复")
    who = doc.get("reviewer") if isinstance(doc.get("reviewer"), str) else ""
    at = doc.get("at") if isinstance(doc.get("at"), str) and len(doc["at"]) <= 40 else None
    return dict(kind=FEEDBACK_KIND, version=1, share=sid, reviewer=who.strip()[:80], at=at, clips=rows)


def _store_path(owner):
    return os.path.join(owner_dirs(owner)[2], "feedback.json")


def feedback_id(share_id, reviewer, clip, decision, comment):
    return sha1_json([share_id, reviewer, clip, decision, comment], 16)


def import_feedback(text, owner=None, pin=True):
    """Feedback -> items in the owner's review store (re-importing the same feedback adds nothing). ``pin``: a
    change request is also added to the clip's chat (the output editor shows it on the clip).
    -> {ok, share, owner, title, items [new], duplicates, unknown [clip ids not in the share]}"""
    doc = parse_feedback(text)
    rec = find_share(doc["share"], owner)
    if not rec:
        raise ShareError("unknown-share", "this feedback answers a review that was not shared from this computer "
                         "(or its project moved)", "这份反馈对应的审片不是在这台电脑上分享的（或项目已移动）",
                         share=doc["share"])
    owner = rec["owner"]
    by_id = {c["id"]: c for c in rec.get("clips") or []}
    path = _store_path(owner)
    store = read_json(path, {}) or {}
    items = store.setdefault("items", [])
    have = {x.get("id") for x in items}
    new, dup, unknown = [], [], []
    for c in doc["clips"]:
        if c["id"] not in by_id:
            unknown.append(c["id"])
            continue
        fid = feedback_id(doc["share"], doc["reviewer"], c["id"], c["decision"], c["comment"])
        if fid in have:
            dup.append(fid)
            continue
        clip = by_id[c["id"]]
        it = dict(id=fid, share=doc["share"], clip=c["id"], title=clip.get("title"), decision=c["decision"],
                  comment=c["comment"], reviewer=doc["reviewer"], at=doc["at"], status="open",
                  imported=time.strftime("%Y-%m-%dT%H:%M:%S"), ref=clip.get("ref") or {}, pinned=None)
        if pin and c["decision"] == "change":
            it["pinned"] = pin_comment(owner, it)
        items.append(it)
        have.add(fid)
        new.append(it)
    write_json(path, store)
    return dict(ok=True, share=doc["share"], owner=owner, title=rec.get("title"), reviewer=doc["reviewer"],
                items=new, duplicates=len(dup), unknown=unknown)


def pin_comment(owner, it):
    """The reviewer's change request as a note on the clip's first output (its chat: "<reviewer>: <comment>")."""
    outs = (it.get("ref") or {}).get("outputs") or []
    if not outs or owner_dirs(owner)[1] == "batch":       # a plain batch has no output edit documents
        return None
    from . import outputs as O
    text = f"{it['reviewer'] or 'Reviewer'}: {it['comment']}" if it.get("comment") else (it["reviewer"] or "Reviewer")
    try:
        r = O.chat_add(owner, outs[0], dict(role="user", status="note", text=text))
        return dict(output=outs[0], turn=r["turn"]["id"])
    except Exception:  # noqa: BLE001  (an output that cannot be resolved still gets its inbox item)
        return None


def feedback_items(owner, status="open"):
    items = (read_json(_store_path(owner), {}) or {}).get("items") or []
    return [x for x in items if status in (None, "all") or x.get("status") == status]


def resolve(owner, fid, by="user"):
    """Act on one feedback item: approve -> mark the clip ready; change -> done (the comment stays in the chat)."""
    path = _store_path(owner)
    store = read_json(path, {}) or {}
    for it in store.get("items") or []:
        if it.get("id") == fid:
            res = mark_ready(owner, it["clip"], ref=it.get("ref"), by=it.get("reviewer") or by) \
                if it["decision"] == "approve" else dict(ok=True, how="noted")
            it.update(status="done", resolved=time.strftime("%Y-%m-%dT%H:%M:%S"), result=res)
            write_json(path, store)
            return dict(ok=True, item=it)
    raise ShareError("unknown-feedback", f"no feedback item {fid}", "没有这条反馈", id=fid)


def reopen(owner, fid):
    """Take a resolve back (the desk's Undo): the item is open again, an approval's ready mark is removed."""
    path = _store_path(owner)
    store = read_json(path, {}) or {}
    for it in store.get("items") or []:
        if it.get("id") == fid:
            if it.get("status") == "done" and it["decision"] == "approve":
                mark_ready(owner, it["clip"], undo=True)
            it.update(status="open", resolved=None, result=None)
            write_json(path, store)
            return dict(ok=True, item=it)
    raise ShareError("unknown-feedback", f"no feedback item {fid}", "没有这条反馈", id=fid)


def ready_marks(owner):
    return (read_json(os.path.join(owner_dirs(owner)[2], "ready.json"), {}) or {}).get("clips") or {}


def mark_ready(owner, clip, ref=None, by=None, undo=False):
    """A reviewer approved the clip: a recipe project / batch item is approved in its store (its publish
    checkpoint answered when one is waiting); a work folder clip gets a ready mark (``ready_marks``)."""
    owner, kind, store_dir = owner_dirs(owner)
    item = (ref or {}).get("item") or clip
    how = "marked"
    if kind in ("project", "batch") and not undo:
        how = _approve_item(owner, kind, item) or how
    path = os.path.join(store_dir, "ready.json")
    doc = read_json(path, {}) or {}
    marks = doc.setdefault("clips", {})
    if undo:
        marks.pop(clip, None)
    else:
        marks[clip] = dict(at=time.strftime("%Y-%m-%dT%H:%M:%S"), by=by, how=how)
    write_json(path, doc)
    return dict(ok=True, clip=clip, how="unmarked" if undo else how)


def _approve_item(owner, kind, item):
    if kind == "project":
        try:
            from .core import Project
            p = Project(owner)
            if any(x.get("id") == "publish" and x.get("item") == item for x in p.pending()):
                p.answer("publish", dict(approve=True), items=[item])
                return "publish-checkpoint"
        except Exception:  # noqa: BLE001
            pass
    try:
        from vstudio.batch.review import apply_decisions
        st = os.path.join(owner, "state") if kind == "project" else owner
        r = apply_decisions(st, dict(decisions={item: "approve"}))
        return "approved" if item in r.get("approved") or [] else None
    except Exception:  # noqa: BLE001
        return None
