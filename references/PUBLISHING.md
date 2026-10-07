# Publishing: how a post reaches each platform

`vstudio.platform.publishing(name)` holds the same data as this page. The rules apply to every platform:

1. **Assisted publishing is the default.** The Reelfold desktop app (`apps/desk`) opens the platform's own upload page in its built-in browser,
   with one persistent login per account (the app never stores passwords or cookies itself). It sets the video file
   and types the title, text and tags where the page allows it. The creator checks everything, makes the choices only
   she should make (category, audience, AI label, subreddit, board ...), and **presses publish herself**. She then
   marks the post as posted, with its URL. The app outlines the publish button at most; it never clicks it.
   Login pages are detected (URL rules + a password / QR form on the page) and the fill stops there.
2. **An official API is optional and opt-in per platform.** It is used only when the creator turns it on in config
   (`uploader: <name>` in the series / project file, with credentials in `$VSTUDIO_SECRETS`, never in the repo), and
   each upload needs the **confirm code** of the exact package that was reviewed (`plan` → code → `upload --confirm`).
3. **Nothing auto-posts.** Neither path schedules or posts without that review step. `publishing(n)["auto_post"]` is
   always `False`.
4. Without the desk, `uploader: manual` prints the page, the steps, `caption.txt`, the cover and a `CHECKLIST.md`.

The selectors of every assisted-fill page are marked **unverified** until someone checks them against the live page
with a logged-in account. The desk keeps the adapter files.

| platform | assisted fill (web upload page) | official posting API, and what it takes | wired here |
|---|---|---|---|
| YouTube (long-form + Shorts, one channel) | https://www.youtube.com/upload | Data API v3 `videos.insert`, OAuth. Projects that have not passed the API audit are **locked to private** [S] | `uploader: youtube` (ai-video workflow) |
| TikTok | https://www.tiktok.com/tiktokstudio/upload | Content Posting API. Unaudited clients can only post as `SELF_ONLY` from a private account [S] | no (manual / assisted) |
| Instagram | https://www.instagram.com/ (Create → Post) | Content Publishing API: a Professional account, a Meta app that passed App Review, and the video at a public URL [S] | `uploader: instagram-api` |
| X | https://x.com/compose/post | API v2 media upload + `POST /2/tweets`. Paid credits, OAuth 2.0 user token [3P] | `uploader: x-api` |
| Facebook | https://www.facebook.com/ (Reel / Photo-video). Pages: Meta Business Suite | Graph API Reels publishing, **Pages only** (`pages_manage_posts`), 30 API Reels per 24 h. No API for personal profiles [S: https://developers.facebook.com/docs/video-api/guides/reels-publishing] | no |
| LinkedIn | https://www.linkedin.com/feed/ (Start a post → Video) | Posts + Videos API. Members: "Share on LinkedIn" (`w_member_social`). Company Pages: Community Management API approval [S: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview] | no |
| Threads | https://www.threads.com/ (composer → media) | Threads API `threads_content_publish`. App review is needed to post for other accounts. The video must be at a public URL. 250 posts per 24 h [S: https://developers.facebook.com/docs/threads/posts/] | no |
| Reddit | https://www.reddit.com/r/<subreddit>/submit (the creator types the subreddit) | Data API: OAuth, plus app pre-approval [3P]. The video upload flow is **undocumented** (media asset lease + websocket) [3P: PRAW] | no (not planned: undocumented) |
| Pinterest | https://www.pinterest.com/pin-creation-tool/ | API v5 `media` + `pins`. Standard access tier; pins made on the Trial tier are private [S: https://developers.pinterest.com/docs/key-concepts/access-tiers/] | no |
| Snapchat Spotlight | https://profile.snapchat.com/ (tick "Spotlight", accept the Creator Terms) | Public Profile API, **allowlisted partners only** [S: https://developers.snap.com/marketing-api/Public-Profile-API/Introduction] | no |
| 小红书 | https://creator.xiaohongshu.com/publish/publish | no public posting API | no |
| 抖音 | https://creator.douyin.com/creator-micro/content/upload | Open platform: posting on the user's behalf is limited to government / media tools; SDK share needs an enterprise app [S: developer.open-douyin.com] | `sau` (external browser tool, see ai-video) |
| 视频号 | https://channels.weixin.qq.com/platform/post/create | none for publishing [S: WeChat community replies] | no |
| B站 | https://member.bilibili.com/platform/upload/video/frame | 开放平台 视频稿件投递: developer application + review [S: https://openhome.bilibili.com/doc/4] | no |
| 快手 | https://cp.kuaishou.com/article/publish/video | 快手开放平台 `photo/start_upload` → `photo/publish`: approved app, `user_video_publish` scope [S: https://open.kuaishou.com/platformDocs/openAbility/contentManagement/createAVideo.html] | no |
| 微博 | https://weibo.com/upload/channel (投稿), or the home composer | Video upload API only for government / media / institution accounts. `statuses/upload` takes images only [S: https://open.weibo.com/wiki/Video/api] | no |
| 知乎 | https://www.zhihu.com/zvideo/upload-video (or 创作中心 → 上传视频) | none (the 2026 open platform is read-only) [S: https://developer.zhihu.com/] | no |
| Dailymotion | Studio → Media → Upload video (https://www.dailymotion.com/partner/; the exact Studio host is unverified) | Data API v2 upload sessions, OAuth `video.manage`, API key from Studio [S: https://developers.dailymotion.com/docs/upload-videos] | no |
| Kwai | **none**: no desktop web upload (Kwai Studio is for live streaming) | none for third parties | phone app (package + manual) |

URLs not confirmed by a source are written as the convention and are checked by the desk's login / upload-page
detection on first use. Platform-specific notes:

- **Reddit**: a title is required (300 characters, cannot be edited after posting) and Reddit has no hashtags. The
  creator types the subreddit, and flair / NSFW / spoiler are left to her. Read the community's rules before posting:
  many limit or ban self-promotion. See the norms in `references/PLATFORMS.md`.
- **Pinterest**: the link goes into the destination-link field, never into the description. The creator picks the
  board and the topics.
- **Snapchat**: 5-60 s, 9:16, no watermarks. Story and Spotlight cannot be posted together from the web.
- **YouTube**: one channel, two formats. A Shorts upload must be vertical or square and ≤ 3 min. Long-form from a
  vertical-only clip is flagged at packaging time.
- **AI label**: every Chinese platform has a 内容由 AI 生成 / 作者声明 toggle (labeling rules in force since
  2025-09-01). YouTube has "Altered or synthetic content", TikTok "AI-generated content", Meta "AI info". The creator
  ticks it herself; the checklist reminds her.

The ai-video workflow's own notes (series packages, the API audit rules, the confirm step) are in
`workflows/ai-video/references/PUBLISHING.md`.
