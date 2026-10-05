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
| TikTok | manual (the sessions never wired the API) | tick by hand | - |

## The confirm step
`package.py plan series.yaml 3 douyin` prints exactly what goes where (file + size, cover, title, first line,
tags, schedule or IMMEDIATELY, AI label method, warnings) and a code. `upload ... --confirm <code>` publishes
only if the package is byte-for-byte what was reviewed. One platform per call; already-published episodes are
skipped; the log records the code that was approved.
