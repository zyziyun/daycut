#!/usr/bin/env python3
"""投稿 / multi-platform publishing for a series: upload-ready packages by default, uploads only per post
after an explicit confirm step.

    python3 package.py status  series.yaml
    python3 package.py build   series.yaml 3                    # out/ep03/<platform>/{video.mp4,cover.jpg,post.json,caption.txt,CHECKLIST.md}
    python3 package.py plan    series.yaml 3 douyin             # exactly what would go where + a confirm code
    python3 package.py upload  series.yaml 3 douyin --confirm 1a2b3c4d     # the ONLY command that publishes

Rules
  - One platform per upload call; the confirm code is a hash of the package (video bytes, cover, title, body,
    tags, schedule, AI label). Change anything and the old code stops working - re-run `plan`.
  - Episodes publish only with `status: ready`; an episode already logged as published/scheduled is skipped.
  - Credentials never live in the repo or the project: YouTube OAuth files in $VSTUDIO_SECRETS
    (default ~/.config/video-studio/secrets); browser-cookie uploaders (social-auto-upload) keep their own
    login state in their own folder ($SAU_DIR). Neither is vendored here.
  - Official upload APIs lock unaudited API clients to private (YouTube Data API projects created after
    2020-07-28; TikTok Content Posting API: SELF_ONLY). Per platform `api_audited` (series.yaml, or env
    VSTUDIO_<PLATFORM>_API_AUDITED=1) defaults to false: the post then defaults to private, the plan and the
    upload warn, and the returned status is checked afterwards (a silent lock is reported as `locked`).
  - Every post carries the AI-generated disclosure. Where the uploader cannot set the platform's AI label,
    the CHECKLIST says so and the plan prints a reminder to tick it by hand.
Sources (video per language variant, covers per ratio) should already be exported with `python -m vstudio.export`.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

# Title / body limits for platforms vstudio.platform does not profile (kuaishou, channels, reddit...). [C]
LIMITS = {"kuaishou": (30, 500), "channels": (16, 1000), "weibo": (30, 2000), "reddit": (300, 10000),
          "instagram": (0, 2200), "linkedin": (0, 3000)}
VSTUDIO_PLATFORMS = {"xiaohongshu", "douyin", "tiktok", "youtube", "bilibili"}
UPLOAD_PAGES = {
    "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
    "douyin": "https://creator.douyin.com/creator-micro/content/upload",
    "kuaishou": "https://cp.kuaishou.com/article/publish/video",
    "bilibili": "https://member.bilibili.com/platform/upload/video/frame",
    "channels": "https://channels.weixin.qq.com/platform/post/create",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    "youtube": "https://studio.youtube.com",
    "reddit": "https://www.reddit.com/submit",
}
# How the AI-generated label gets set, per uploader+platform (recorded in the sessions; "manual" = tick it in the UI).
AI_LABEL = {
    ("youtube", "youtube"): ("auto", "status.containsSyntheticMedia = true"),
    ("sau", "douyin"): ("auto", "--declaration 内容由AI生成"),
}
# Upload APIs that silently restrict clients which have not passed the platform's API audit. [S: platform API docs]
API_AUDIT = {
    "youtube": "YouTube Data API: uploads from API projects created after 2020-07-28 that have not passed the "
               "YouTube API Services audit are locked to private (no error); new projects get ~100 uploads/day",
    "tiktok": "TikTok Content Posting API: unaudited clients can only post SELF_ONLY, the posting account must be "
              "private, max 5 users per 24 h",
}
# (uploader, platform) pairs that publish through an official API and are therefore subject to API_AUDIT.
API_UPLOADERS = {("youtube", "youtube")}
PRIVACY = {"youtube": ("public", "unlisted", "private"),
           "tiktok": ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")}
PRIVATE = {"youtube": "private", "tiktok": "SELF_ONLY"}
UPLOADED = ("published", "scheduled", "private", "locked")    # anything that already put the video on the platform


def base_platform(name):
    return name.split("_")[0] if name.startswith("reddit") else name


# ------------------------------------------------------------------------------------------- config
def load(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_dir"] = os.path.dirname(os.path.abspath(path))
    cfg.setdefault("out", "out")
    cfg.setdefault("log", "publish_log.json")
    return cfg


def _p(cfg, rel):
    return rel if os.path.isabs(rel) else os.path.join(cfg["_dir"], rel)


def episode(cfg, n):
    for e in cfg.get("episodes", []):
        if int(e["ep"]) == int(n):
            return e
    raise SystemExit(f"episode {n} not in the series file")


def ep_dir(cfg, n):
    return os.path.join(_p(cfg, cfg["out"]), f"ep{int(n):02d}")


def load_log(cfg):
    p = _p(cfg, cfg["log"])
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_log(cfg, log):
    with open(_p(cfg, cfg["log"]), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


def api_audited(pc, platform):
    """Has this platform's API client passed the platform audit? env VSTUDIO_<PLATFORM>_API_AUDITED wins, then
    `api_audited` in the series platform entry; default False (assume the restricted, unaudited mode)."""
    env = os.environ.get(f"VSTUDIO_{base_platform(platform).upper()}_API_AUDITED", "").strip().lower()
    if env:
        return env in ("1", "true", "yes", "on")
    return bool((pc or {}).get("api_audited", False))


def api_privacy(platform, audited, requested=None):
    """-> (privacy to request, warning or None). Unaudited clients get the platform's private level up front,
    so the upload does what the plan says instead of being silently downgraded."""
    b = base_platform(platform)
    levels = PRIVACY.get(b)
    if not levels:
        return requested, None
    want = requested or levels[0]
    if want not in levels:
        raise SystemExit(f"{platform}: privacy {want!r} not one of {', '.join(levels)}")
    if audited or want == PRIVATE[b]:
        return want, None
    return PRIVATE[b], (f"{b} API not audited (api_audited: false): uploading as {PRIVATE[b]}, not {want}. "
                        f"{API_AUDIT[b]}. Publish it from the official app/Studio, or set api_audited: true "
                        f"once the audit has passed.")


# ------------------------------------------------------------------------------------------- copy
def _limits(platform):
    b = base_platform(platform)
    if b in VSTUDIO_PLATFORMS:
        from vstudio import platform as P
        p = P.profile(b)
        return p.title_max, p.desc_max
    return LIMITS.get(b, (100, 2000))


def build_post(cfg, n, platform, log=None):
    s, pc, e = cfg["series"], cfg["platforms"][platform], episode(cfg, n)
    lang = pc["lang"]
    c = e[lang]
    name = (s.get("name") or {}).get(lang, "")
    prev = ((log or {}).get(str(int(n) - 1), {}).get(platform) or {}).get("url")
    tags = list((s.get("tags") or {}).get(lang, []))
    stag = (s.get("series_tag") or {}).get(lang)
    b = base_platform(platform)
    if b == "youtube":
        tags = ["shorts"] + tags[:4]
    tags = ([stag] if stag else []) + tags
    series_line = (f"【{name}·第{n}集】" if lang == "zh" else f"{name} · Ep. {n}") if name else ""
    prev_line = (f"上一集：{prev}" if lang == "zh" else f"Previous episode: {prev}") if prev else ""
    cta = (s.get("cta") or {}).get(lang, "")
    title = c["title"]
    tmax, bmax = _limits(platform)
    if b == "reddit":
        # communities: no hashtags; the body is the first comment (how it was made), upload the video file itself
        title = f"{c['title']} ({pc.get('title_suffix', 'Ep. ' + str(n))})"
        body = "\n\n".join(x for x in [c.get("hook"), (c.get("body") or "").strip(),
                                        (s.get("making_of") or {}).get(lang, "").strip(), prev_line] if x)
        tags = []
    else:
        if b == "bilibili" and series_line:
            title = f"{series_line}{title}"
        elif b == "youtube" and name:
            title = f"{title} | {name} Ep.{n}"
        parts = [series_line, c.get("hook"), (c.get("body") or "").strip(), cta, prev_line,
                 " ".join("#" + t for t in tags)]
        body = "\n\n".join(x for x in parts if x)
    warnings = []
    if b in VSTUDIO_PLATFORMS:          # platform-aware length rules (小红书 counts latin as 0.5): warn, never cut
        from vstudio import platform as P
        warnings += P.check_text(P.profile(b), title=title if tmax else None, body=body, tags=tags)
    else:
        if tmax and len(title) > tmax:
            warnings.append(f"title {len(title)} > {tmax}; trimmed")
            title = title[:tmax - 1] + "…"
        if bmax and len(body) > bmax:
            warnings.append(f"body {len(body)} > {bmax}; trimmed")
            body = body[:bmax]
    up = pc.get("uploader", "manual")
    how, note = AI_LABEL.get((up, b), ("manual", "tick the platform's AI-generated / 内容由AI生成 label by hand"))
    ai = bool(s.get("ai_generated", True))
    api = {}
    if (up, b) in API_UPLOADERS:
        audited = api_audited(pc, platform)
        privacy, warn = api_privacy(platform, audited, pc.get("privacy"))
        if warn:
            warnings.append(warn)
            if (e.get("publish_at") or {}).get(lang):
                warnings.append(f"{b}: scheduled release of an unaudited upload is not expected to go public "
                                f"either; schedule it in the platform UI")
        api = {"api_audited": audited, "privacy": privacy,
               "privacy_requested": pc.get("privacy") or PRIVACY[b][0]}
    return {"platform": platform, "episode": int(n), "slug": e.get("slug", f"ep{n}"), "lang": lang,
            "title": title if tmax else "", "body": body, "tags": tags,
            "publish_at": (e.get("publish_at") or {}).get(lang), "collection": name,
            "ai_generated": ai, "ai_label": {"how": how if ai else "n/a", "note": note if ai else ""},
            "uploader": up, "warnings": warnings, **api, **({k: pc[k] for k in ("tid", "account") if k in pc})}


def fit_cover(src, dst, ratio):
    """Cover at the platform ratio: blurred fill + whole image centred (never crop heads or the headline)."""
    from vstudio import media
    w, h = {"9x16": (1080, 1920), "3x4": (1080, 1440), "16x9": (1920, 1080), "16x10": (1146, 717)}[ratio]
    vf = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:3,"
          f"eq=brightness=-0.08[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    media.run(["ffmpeg", "-y", "-i", src, "-filter_complex", vf, "-frames:v", "1", "-q:v", "2", dst])
    return dst


def _link(src, dst):
    if os.path.lexists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def checklist(post, video, cover):
    lines = [f"# {post['platform']} - ep {post['episode']} ({post['slug']})", "",
             f"- video: `{os.path.basename(video)}`", f"- cover: `{os.path.basename(cover) if cover else '(none)'}`",
             f"- title: {post['title'] or '(platform has no title)'}",
             f"- schedule: {post['publish_at'] or 'immediately'}"
             + (f" ({post['privacy']}; api_audited: {post['api_audited']})" if "privacy" in post else ""),
             f"- collection / 合集: {post['collection'] or '-'}",
             f"- AI label: {post['ai_label']['how']} - {post['ai_label']['note']}",
             f"- upload page: {UPLOAD_PAGES.get(base_platform(post['platform']), '-')}"]
    if post["warnings"]:
        lines += ["", "Warnings:"] + [f"- {w}" for w in post["warnings"]]
    if base_platform(post["platform"]) == "reddit":
        lines += ["", "- Read the community rules / flair first; upload the video file (no channel links); "
                      "post the body as the first comment."]
    return "\n".join(lines) + "\n"


def build(cfg, n, out=print):
    e = episode(cfg, n)
    d = ep_dir(cfg, n)
    log = load_log(cfg)
    made = []
    for platform, pc in cfg["platforms"].items():
        src_rel = (e.get("source") or {}).get(pc["variant"])
        if not src_rel:
            out(f"- {platform}: episode has no '{pc['variant']}' video; skipped")
            continue
        video = _p(cfg, src_rel)
        if not os.path.exists(video):
            out(f"- {platform}: missing {src_rel}; skipped")
            continue
        pd = os.path.join(d, platform)
        os.makedirs(pd, exist_ok=True)
        _link(video, os.path.join(pd, "video.mp4"))
        covers = e.get("covers") or {}
        csrc = covers.get(f"{pc['cover']}-{pc['lang']}") or covers.get(pc["cover"]) or next(iter(covers.values()), None)
        cover = None
        if csrc:
            cover = os.path.join(pd, "cover.jpg")
            exact = covers.get(f"{pc['cover']}-{pc['lang']}") or covers.get(pc["cover"])
            if exact and exact.lower().endswith((".jpg", ".jpeg")):
                _link(_p(cfg, exact), cover)
            else:
                fit_cover(_p(cfg, csrc), cover, pc["cover"])
        post = build_post(cfg, n, platform, log)
        with open(os.path.join(pd, "post.json"), "w", encoding="utf-8") as f:
            json.dump(post, f, ensure_ascii=False, indent=1)
        with open(os.path.join(pd, "caption.txt"), "w", encoding="utf-8") as f:
            f.write((post["title"] + "\n\n" if post["title"] else "") + post["body"] + "\n")
        with open(os.path.join(pd, "CHECKLIST.md"), "w", encoding="utf-8") as f:
            f.write(checklist(post, video, cover))
        made.append(platform)
    out(f"ep {n}: packages for {', '.join(made) or 'nothing'} -> {d}")
    return made


# ------------------------------------------------------------------------------------------- confirm gate
def _sha1_file(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load_package(cfg, n, platform):
    pd = os.path.join(ep_dir(cfg, n), platform)
    pj = os.path.join(pd, "post.json")
    if not os.path.exists(pj):
        raise SystemExit(f"no package for ep {n} / {platform}: run `build` first")
    with open(pj, encoding="utf-8") as f:
        post = json.load(f)
    video = os.path.join(pd, "video.mp4")
    cover = os.path.join(pd, "cover.jpg")
    return pd, post, video, cover if os.path.exists(cover) else None


def confirm_code(post, video, cover):
    keys = ("platform", "episode", "title", "body", "tags", "publish_at", "ai_generated", "ai_label", "uploader",
            "collection", "account", "tid", "api_audited", "privacy")
    blob = json.dumps({k: post.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    blob += _sha1_file(video) + (_sha1_file(cover) if cover else "")
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


def plan_text(post, video, cover, code):
    mb = os.path.getsize(video) / 1e6
    body = post["body"].splitlines()
    lines = [f"PLAN  ep {post['episode']} -> {post['platform']}  via {post['uploader']}"
             + (f" (account {post['account']})" if post.get("account") else ""),
             f"  video : {video}  ({mb:.1f} MB)", f"  cover : {cover or '(none)'}",
             f"  title : {post['title'] or '(none)'}",
             f"  body  : {body[0] if body else ''}" + (f"  (+{len(body) - 1} lines)" if len(body) > 1 else ""),
             f"  tags  : {' '.join(post['tags']) or '-'}",
             f"  when  : {post['publish_at'] or 'IMMEDIATELY'} ({post.get('privacy') or 'public'})",
             f"  AI    : {post['ai_label']['how']} - {post['ai_label']['note']}"]
    if post.get("api_audited") is False:
        lines += [f"  api   : NOT AUDITED - {API_AUDIT[base_platform(post['platform'])]}"]
    lines += [f"  warn  : {w}" for w in post.get("warnings", [])]
    lines += [f"To publish exactly this, run with:  --confirm {code}"]
    return "\n".join(lines)


class UploadRefused(RuntimeError):
    pass


def upload(cfg, n, platform, confirm=None, uploaders=None, out=print):
    """No confirm -> print the plan and return it (no side effects). Matching confirm -> publish + log."""
    e = episode(cfg, n)
    pd, post, video, cover = load_package(cfg, n, platform)
    code = confirm_code(post, video, cover)
    text = plan_text(post, video, cover, code)
    if confirm is None:
        out(text)
        return {"status": "planned", "code": code, "plan": text}
    if e.get("status") != "ready":
        raise UploadRefused(f"episode {n} status={e.get('status')!r}; set it to ready after fixing")
    log = load_log(cfg)
    prev = (log.get(str(n)) or {}).get(platform) or {}
    if prev.get("status") in UPLOADED:
        out(f"{platform}: ep {n} already {prev['status']}; skipped")
        return prev
    if confirm != code:
        raise UploadRefused("confirm code does not match the current package (it changed, or the code is for "
                            "another post). Re-run `plan` and review it again.")
    ups = uploaders or UPLOADERS
    fn = ups.get(post["uploader"]) or ups["manual"]
    if post.get("api_audited") is False:
        out(f"WARNING {platform}: API client not audited - this upload will be {post['privacy']} "
            f"(not {post['privacy_requested']}). {API_AUDIT[base_platform(platform)]}.")
    res = fn(post, video, cover, out=out)
    if res.get("locked"):
        out(f"WARNING {platform}: the platform returned privacy {res.get('privacy')!r} - the upload was locked "
            f"(API audit; set api_audited: false until it passes). Publish it from the official app/Studio; "
            f"logged as 'locked'.")
    log.setdefault(str(n), {})[platform] = {**res, "at": datetime.datetime.now().isoformat(timespec="seconds"),
                                            "code": code}
    save_log(cfg, log)
    if post["ai_generated"] and post["ai_label"]["how"] == "manual":
        out(f"{platform}: REMINDER - tick the AI-generated label in the platform UI now.")
    return res


# ------------------------------------------------------------------------------------------- uploaders
def manual_uploader(post, video, cover, out=print):
    out(f"{post['platform']}: manual upload - open {UPLOAD_PAGES.get(base_platform(post['platform']), 'the creator page')}, "
        f"upload {video}, paste caption.txt, set cover, collection '{post['collection']}', AI label, schedule "
        f"{post['publish_at'] or 'now'}.")
    return {"status": "manual"}


def secrets_dir():
    d = os.path.expanduser(os.environ.get("VSTUDIO_SECRETS", "~/.config/video-studio/secrets"))
    repo = str(pathlib.Path(__file__).resolve().parents[3])
    if os.path.abspath(d).startswith(repo):
        raise UploadRefused("VSTUDIO_SECRETS points inside the repository; keep credentials outside it")
    return d


def youtube_shorts_guard(video):
    from vstudio import media
    i = media.probe(video)
    w, h = i["display_w"], i["display_h"]
    if h <= w or i["duration"] > 180:
        raise UploadRefused(f"not a Short ({w}x{h}, {i['duration']:.0f}s): vertical and <= 180 s required")


def youtube_uploader(post, video, cover, out=print):
    youtube_shorts_guard(video)
    return youtube_publish(_youtube_client(), post, video, cover, out=out)


def _youtube_client():
    d = secrets_dir()
    client = os.path.join(d, "youtube_client_secret.json")
    if not os.path.exists(client):
        raise UploadRefused(f"missing {client} (OAuth desktop client from Google Cloud Console)")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as gbuild
    scopes = ["https://www.googleapis.com/auth/youtube"]
    tok = os.path.join(d, "youtube_token.json")
    creds = Credentials.from_authorized_user_file(tok, scopes) if os.path.exists(tok) else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(client, scopes).run_local_server(port=0)
        with open(tok, "w") as f:
            f.write(creds.to_json())
    return gbuild("youtube", "v3", credentials=creds)


def youtube_publish(yt, post, video, cover, out=print, media=None):
    """Insert + verify. Unaudited projects are locked to private without an error, so the privacy the API
    reports back (insert response, then videos.list) is compared with what was asked for."""
    if media is None:
        from googleapiclient.http import MediaFileUpload as media
    body = post["body"] if "#shorts" in post["body"].lower() else post["body"] + " #Shorts"
    audited = post["api_audited"] if "api_audited" in post else api_audited({}, post["platform"])  # old packages
    privacy = post.get("privacy") or api_privacy(post["platform"], audited)[0]
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(post.get("ai_generated"))}
    when = _schedule(post.get("publish_at"))
    if when:
        status.update(privacyStatus="private", publishAt=when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    res = yt.videos().insert(part="snippet,status", body={"snippet": {
        "title": post["title"], "description": body, "tags": post["tags"], "categoryId": post.get("category", "23")},
        "status": status}, media_body=media(video, chunksize=-1, resumable=True)).execute()
    vid = res["id"]
    if cover:
        try:
            yt.thumbnails().set(videoId=vid, media_body=media(cover)).execute()
        except Exception as ex:          # custom thumbnails need a verified channel
            out(f"youtube: thumbnail not set ({ex.__class__.__name__})")
    got = (res.get("status") or {}).get("privacyStatus")
    try:
        items = yt.videos().list(part="status", id=vid).execute().get("items") or []
        if items:
            got = (items[0].get("status") or {}).get("privacyStatus") or got
    except Exception as ex:              # verification is best effort; the insert already succeeded
        out(f"youtube: could not re-read the status ({ex.__class__.__name__}); using the insert response")
    url = f"https://youtube.com/shorts/{vid}"
    if when:
        st, want = "scheduled", "private"
    elif privacy == "public":
        st, want = "published", "public"
    else:
        st, want = "private", privacy
    locked = got is not None and got != want
    if locked:                           # upload() prints the warning and logs it as locked
        st = "locked"
    elif not audited:
        out(f"youtube: uploaded as {got or privacy} (unaudited API). Make it public in YouTube Studio / the app: {url}")
    return {"status": st, "url": url, "privacy": got or privacy, "locked": locked}


def _schedule(publish_at):
    """'YYYY-MM-DD HH:MM Area/City' -> aware datetime if in the future, else None."""
    if not publish_at:
        return None
    from zoneinfo import ZoneInfo
    when, tz = publish_at.rsplit(" ", 1)
    at = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))
    return at if at > datetime.datetime.now(datetime.timezone.utc) else None


SAU_SUB = {"douyin": "douyin", "kuaishou": "kuaishou", "xiaohongshu": "xiaohongshu", "channels": "tencent",
           "bilibili": "bilibili", "weibo": "weibo"}
SAU_COLLECTION = {"douyin", "kuaishou", "tencent", "weibo"}
SAU_SCHEDULE = {"douyin", "kuaishou", "xiaohongshu", "tencent", "bilibili"}


def sau_command(post, video, cover):
    """Command line for the external social-auto-upload CLI (MIT, not vendored; install it yourself)."""
    sub = SAU_SUB[base_platform(post["platform"])]
    desc = "\n".join(ln for ln in post["body"].splitlines() if not ln.startswith("#")).strip()
    cmd = ["uv", "run", "sau", sub, "upload-video", "--account", post.get("account", "main"), "--file", video,
           "--title", post["title"] or desc.splitlines()[0], "--desc", desc, "--tags", ",".join(post["tags"])]
    if cover:
        cmd += ["--thumbnail", cover]
    if sub == "douyin" and post.get("ai_generated"):
        cmd += ["--declaration", "内容由AI生成"]
    if sub == "bilibili" and post.get("tid"):
        cmd += ["--tid", str(post["tid"])]
    if sub in SAU_COLLECTION and post.get("collection"):
        cmd += ["--collection", post["collection"]]
    when = _schedule(post.get("publish_at"))
    if when and sub in SAU_SCHEDULE:
        cmd += ["--schedule", when.astimezone().strftime("%Y-%m-%d %H:%M")]
    return cmd, bool(when and sub in SAU_SCHEDULE)


def sau_uploader(post, video, cover, out=print):
    d = os.environ.get("SAU_DIR")
    if not d or not os.path.isdir(d):
        raise UploadRefused("set SAU_DIR to your social-auto-upload checkout (log in there first: "
                            "`uv run sau <platform> login --account main`)")
    cmd, scheduled = sau_command(post, video, cover)
    r = subprocess.run(cmd, cwd=d)
    if r.returncode != 0:
        raise UploadRefused(f"{post['platform']} upload failed (exit {r.returncode}); add --headed in sau to watch")
    return {"status": "scheduled" if scheduled else "published"}


UPLOADERS = {"manual": manual_uploader, "youtube": youtube_uploader, "sau": sau_uploader}


def status(cfg, out=print):
    log = load_log(cfg)
    pfs = list(cfg["platforms"])
    out("ep  status       " + " ".join(f"{p[:8]:>9}" for p in pfs))
    for e in cfg.get("episodes", []):
        n = int(e["ep"])
        cells = []
        for p in pfs:
            st = ((log.get(str(n)) or {}).get(p) or {}).get("status")
            pkg = os.path.exists(os.path.join(ep_dir(cfg, n), p, "post.json"))
            cells.append(st or ("packaged" if pkg else "."))
        out(f"{n:<3} {e.get('status', '?'):<12} " + " ".join(f"{c:>9}" for c in cells))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("series")
    for name in ("build", "plan", "upload"):
        s = sub.add_parser(name)
        s.add_argument("series")
        s.add_argument("ep", type=int)
        if name != "build":
            s.add_argument("platform")
        if name == "upload":
            s.add_argument("--confirm", help="code printed by `plan` for exactly this package")
    a = ap.parse_args(argv)
    cfg = load(a.series)
    if a.cmd == "status":
        status(cfg)
    elif a.cmd == "build":
        build(cfg, a.ep)
    elif a.cmd == "plan":
        upload(cfg, a.ep, a.platform, confirm=None)
    else:
        if not a.confirm:
            upload(cfg, a.ep, a.platform, confirm=None)
            print("\nNothing uploaded: review the plan, then re-run with --confirm <code>.")
            return 2
        try:
            res = upload(cfg, a.ep, a.platform, confirm=a.confirm)
        except UploadRefused as e:
            print(f"REFUSED: {e}")
            return 2
        print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
