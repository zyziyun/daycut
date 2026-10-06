# 投稿: publishing an AI series to several platforms

`scripts/package.py` turns one series file (`templates/series.yaml`) into upload-ready packages per platform and
publishes **one post at a time** after a confirm step. Default = packages only.

## What the sessions settled on
- **Language split**: Chinese platforms (抖音, 小红书, 快手, B站) get the bilingual-caption cut; English platforms
  (TikTok, YouTube Shorts, Reddit communities) get the English-caption cut. Captions are burned per variant,
  each re-placed for the platform UI (`python -m vstudio.export`).
- **Series**: every post says "Series · Ep. N" (中文「【系列名·第N集】」), adds a call to comment, and links the
  previous episode once its URL is in the log. Episodes are numbered in **publish order**, not production order.
- **Covers per ratio**: 9:16 (抖音/TikTok/Shorts), 3:4 (小红书), 16:9 or 16:10 (B站). A cover of the wrong ratio
  is fitted on a blurred fill - never cropped (heads and headline survive).
- **YouTube = Shorts only**: vertical and <= 180 s, enforced before upload; `#Shorts` added if missing;
  scheduled posts upload as private with `publishAt`.
- **Scheduling**: `publish_at` per language with an IANA time zone ("2030-01-01 20:00 Asia/Shanghai").
- **Status gate**: `draft` / `needs-fix` / `ready`; a known caption error kept an episode at `needs-fix`.
- **Communities** (r/aivideo, r/aifilm were chosen): upload the video file itself (no channel links), no
  hashtags, title says what it is, and post the making-of as the first comment; read each community's rules
  and flair first. Several niche communities were listed from memory and **not verified**.
- 快手「小剧场」 / 微短剧 channels need an enterprise account and 备案; a personal account posts into a 合集 instead.
  B站 was given the 小剧场 category id via the uploader's `--tid` [S: as configured; check the current id].

## Upload adapters
| uploader | how | AI label | notes |
|---|---|---|---|
| `manual` (default) | prints page + steps; you upload | tick by hand (reminder printed) | always works |
| `youtube` | YouTube Data API v3, OAuth desktop client in `$VSTUDIO_SECRETS` | `status.containsSyntheticMedia` | custom thumbnail needs a verified channel |
| `sau` | external [social-auto-upload](https://github.com/dreammis/social-auto-upload) CLI (MIT, browser automation with saved logins) in `$SAU_DIR` | 抖音 only (`--declaration 内容由AI生成`); others by hand | install and log in there; we do not vendor it. Collection: douyin/kuaishou/channels/weibo; schedule: douyin/kuaishou/xiaohongshu/channels/bilibili |
| TikTok | manual (the sessions never wired the API) | tick by hand | an API adapter would be SELF_ONLY until audited - see below |

## Official upload APIs: the audit requirement
Both official APIs restrict clients that have not passed the platform's API audit, and YouTube does it
**silently** (no error, the upload just is not public). [S: YouTube Data API / TikTok Content Posting API docs;
re-check the current terms before relying on the numbers]

| platform | unaudited client | quota / limits |
|---|---|---|
| YouTube Data API v3 | API projects created after 2020-07-28 that have not passed the YouTube API Services audit (compliance review): every `videos.insert` is **locked to private**, whatever `privacyStatus` was sent | new projects: default quota, ~100 uploads/day |
| TikTok Content Posting API | Direct Post only as `SELF_ONLY`; the posting account must be **private** | max 5 users posting per 24 h |

`package.py` handles this with a per-platform **`api_audited`** setting (default **false**):
- set it in the series file (`youtube: {..., uploader: youtube, api_audited: true}`) or with env
  `VSTUDIO_<PLATFORM>_API_AUDITED=1` (env wins). Optional `privacy: public | unlisted | private`.
- **not audited** (default): the post is built as `private` (TikTok: `SELF_ONLY`) instead of being silently
  downgraded; the plan shows `api : NOT AUDITED ...` plus a warning, `upload` prints a warning before the upload,
  and a `publish_at` schedule is flagged as unlikely to go public (schedule it in the app instead). The log
  status is `private`.
- **after every upload** the privacy YouTube reports back (insert response, then `videos.list`) is compared with
  what was asked for. A mismatch (e.g. `api_audited: true` but the project is not) is logged as **`locked`** and
  reported. `private` / `locked` episodes count as uploaded and are never re-uploaded.
- `api_audited` and `privacy` are part of the confirm code: flipping either needs a new `plan`.

**Fallback (the normal path until audited): upload package + share to the official app.** `build` already makes
`video.mp4`, `cover.jpg`, `caption.txt` and `CHECKLIST.md` per platform. Either keep `uploader: manual` and
publish from the creator page / mobile app (AirDrop or sync the package folder to the phone, paste
`caption.txt`, set cover and AI label there), or let the API upload privately and flip it to public in YouTube
Studio / the app. Both keep the AI label and the schedule under your eyes.

TikTok adapter notes (none is wired today; `uploader: manual`): a Content Posting API adapter must be added to
`API_UPLOADERS`, read `api_audited`, send `privacy_level: SELF_ONLY` while unaudited (`api_privacy("tiktok", ...)`
already returns it), require a private posting account, and verify the post status after publishing the same way.
Until the audit passes, the share-to-app fallback is the only way to post publicly.

## The confirm step
`package.py plan series.yaml 3 douyin` prints exactly what goes where (file + size, cover, title, first line,
tags, schedule or IMMEDIATELY plus the privacy, API audit state, AI label method, warnings) and a code. `upload ... --confirm <code>` publishes
only if the package is byte-for-byte what was reviewed. One platform per call; already-published episodes are
skipped; the log records the code that was approved.
