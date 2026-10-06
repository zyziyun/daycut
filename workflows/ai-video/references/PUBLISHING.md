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

## X, Instagram, 视频号, B站: what the APIs really require (checked 2026-10)
Default for all four = **assisted publishing**: the desk app opens the platform's own web page in its built-in
browser (one persistent, separate login per platform/account), sets the video file and types the caption; the
creator checks everything, picks what only she should pick, and presses Post / Share / 发表 / 投稿 herself. Then she
marks it posted with the post URL. Nothing here ever presses the final button. Without the desk: `uploader: manual`
prints the page + steps (`caption.txt`, `cover.jpg`, `CHECKLIST.md` are in the package).

| platform | official API for posting video | what it takes | here |
|---|---|---|---|
| X | X API v2: chunked `POST /2/media/upload/{initialize,append,finalize}` + `GET ?command=STATUS`, then `POST /2/tweets` with `media.media_ids` | **paid**: pay-per-use credits since 2026-02 (≈ $0.015 per post, more with a link; no free posting tier for new apps); **OAuth 2.0 user context** token with `tweet.write media.write` (+ `offline.access`); app-only tokens are refused | optional `uploader: x-api` (token JSON in `$VSTUDIO_SECRETS/x_oauth2_token.json`) |
| Instagram | Content Publishing API: `POST /{ig-user-id}/media` (`media_type=REELS`, `video_url`), poll `status_code` → `FINISHED`, `POST /{ig-user-id}/media_publish` | an **Instagram Professional** (Business/Creator) account, a **Meta app** whose `instagram_business_content_publish` (or `instagram_content_publish`) permission passed **App Review**, and the video at a **public https URL** (Meta downloads it; there is no direct file upload); 100 API posts / 24 h | optional `uploader: instagram-api` (`$VSTUDIO_SECRETS/instagram_token.json` = {access_token, ig_user_id}; `public_video_url` in the series) |
| 视频号 | **none for publishing**: WeChat's Channels APIs cover the shop / showcase / live data, not video upload (official community replies, 2021-2025) | — (third-party "protocol" APIs imitate the WeChat client: account-ban risk, not used) | assisted fill on 视频号助手 (channels.weixin.qq.com, WeChat QR login) or `uploader: manual` |
| B站 | 开放平台 (openhome.bilibili.com) 视频稿件投递: OAuth for the UP主's account, chunked upload, signed requests | developer **application + review** (identity / business documents), per-scope permission (`ARC_BASE` …) whitelisting, the UP主 authorises the app | assisted fill on 创作中心 (member.bilibili.com), `sau` (browser cookies) or `manual`; no open-platform adapter yet |

API uploaders are opt-in per platform in the series file and still go through the confirm step:
```yaml
platforms:
  x:         {lang: en, variant: en, cover: "16x9", uploader: x-api}           # default: manual
  instagram: {lang: en, variant: en, cover: "9x16", uploader: instagram-api,
              public_video_url: "https://cdn.example.com/{slug}/instagram.mp4", share_to_feed: true}
```
- The plan prints the API requirements; the confirm code covers the text, the video bytes and (Instagram) the public
  URL. `instagram-api` refuses when that URL does not serve exactly the package's byte size.
- Neither API uploader schedules (`publish_at` → refused: schedule in the app). Neither sets an AI label: tick
  "AI info" / the disclosure by hand when it applies (the CHECKLIST says so).
- Credentials only in `$VSTUDIO_SECRETS` (default `~/.config/video-studio/secrets`, refused if it points inside the
  repo). The endpoint shapes follow the 2025-2026 developer docs; **neither uploader has been run against the live
  API from this repo** - make the first post with an account you can clean up.
- Copy: X = one post ≤ 280 weighted characters (CJK and emoji count 2, a URL 23), 1-2 hashtags; Instagram caption
  ≤ 2,200, **≤ 5 hashtags** (hard cap since Dec 2025). English content → English copy (`vstudio.publish.platform_post`).

Sources: https://developers.facebook.com/docs/instagram-platform/content-publishing/ ,
https://postproxy.dev/blog/x-api-pricing-2026/ , https://www.postzen.dev/blog/twitter-api-pricing ,
https://devcommunity.x.com/t/how-to-upload-media-to-twitter-api-v2-using-oauth-2-0/238518 ,
https://developers.weixin.qq.com/community/minihome/doc/0000e2bec7ce686b8dcc360e35b800 ,
https://openhome.bilibili.com/doc/4 , https://openhome.bilibili.com/agreement/developer-service

## Upload adapters
| uploader | how | AI label | notes |
|---|---|---|---|
| `manual` (default) | prints page + steps; you upload | tick by hand (reminder printed) | always works |
| `youtube` | YouTube Data API v3, OAuth desktop client in `$VSTUDIO_SECRETS` | `status.containsSyntheticMedia` | custom thumbnail needs a verified channel |
| `sau` | external [social-auto-upload](https://github.com/dreammis/social-auto-upload) CLI (MIT, browser automation with saved logins) in `$SAU_DIR` | 抖音 only (`--declaration 内容由AI生成`); others by hand | install and log in there; we do not vendor it. Collection: douyin/kuaishou/channels/weibo; schedule: douyin/kuaishou/xiaohongshu/channels/bilibili |
| TikTok | manual (the sessions never wired the API) | tick by hand | an API adapter would be SELF_ONLY until audited - see below |
| `x-api` | X API v2 (paid credits, OAuth 2.0 user token) | tick by hand | opt-in; see the table above |
| `instagram-api` | Instagram Content Publishing API (Professional account, reviewed Meta app, public video URL) | tick by hand | opt-in; see the table above |

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
