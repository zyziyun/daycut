# Platform profiles

`lib/vstudio/platform.py` holds the defaults. Override any field in `persona.local.yaml` under
`platforms.<name>` (or `platforms.<name>.orientations.<o>`). `python -m vstudio.platform` prints every
profile. `python -m vstudio.export` uses them to produce per-platform files (see the bottom of this page).

Researched October 2026 (X / Instagram / 视频号 added and B站 re-checked 2026-10-06; Facebook, LinkedIn, Threads,
Reddit, Pinterest, Snapchat, 快手, 微博, 知乎, Dailymotion, Kwai added 2026-10-06 - see "Platforms added 2026-10" below).
Publishing (how a post gets there, APIs): `references/PUBLISHING.md`. Platforms change their UI
and limits often, and **no platform here publishes safe-zone pixels or a loudness target** (YouTube's −14 LUFS
is the one well-documented normalisation). Each value below is tagged:
**[S]** sourced (official doc, or several independent guides that agree), **[3P]** one or two third-party
guides, **[C]** convention (our own working default, measured in-app or chosen to be conservative).
When a platform's UI changes, preview on a phone and update the persona, not the code.

## Order and groups

Every list a person sees (platform pickers, the desk's publish page, accounts list, calendar chips, the website)
uses `platform.ORDER`: **English / global** (YouTube, Shorts, TikTok, Instagram, X, Facebook, LinkedIn, Threads,
Reddit, Pinterest, Snapchat), then **Chinese** (小红书, 抖音, 视频号, B站, 快手, 微博, 知乎), then **other languages**
(Dailymotion, Kwai). `platform.ordered(names, connected=[...])` puts platforms with a connected account first
*within* their group. `PLATFORMS` (the dict) keeps its old insertion order so lookups that scan it are unchanged.

**YouTube = one channel, two formats.** `youtube` (long-form, 16:9) and `youtube-shorts` (vertical or square,
≤ 3 min [S: https://support.google.com/youtube/answer/15424877]) stay two export targets but share one account:
`channel_of("youtube-shorts") == "youtube"`, `FORMATS["youtube"]`. `youtube_format(aspect, seconds)` says which one
a file is; `check_format` (also run by `vstudio.export`) warns when long-form only has a vertical master (re-laid out
on 16:9 with a blurred fill - render a real 16:9 cut, or post it as Shorts) and when a Shorts target is horizontal
or over 180 s. Shorts description links are not clickable since 2023-08 [S: https://support.google.com/youtube/answer/13748639 ,
https://9to5google.com/2023/08/10/youtube-shorts-links-spam/].

## Canvases

| profile | canvas | notes |
|---|---|---|
| `xiaohongshu:vertical` | 1080x1440 (3:4) | feed-native vertical; cover 3:4 1080x1440 [S: multiple 3P guides agree] |
| `xiaohongshu:full` | 1080x1920 (9:16) | full-screen vertical; feed tile shows a 3:4 cover [S] |
| `xiaohongshu:horizontal` | 1920x1080 (16:9) | **feed shows a centre 4:3 crop** of horizontal posts and covers [3P + in-app; repo cover workflow] |
| `douyin:vertical` / `:horizontal` | 1080x1920 / 1920x1080 | 9:16 recommended [S]; profile grid shows a 3:4 crop of covers [3P] |
| `tiktok:vertical` | 1080x1920 | [S] |
| `youtube:horizontal` | 1920x1080 | [S] |
| `youtube-shorts:vertical` | 1080x1920 | Shorts = square or vertical, up to 3 min (since 2024-10-15) [S] |
| `bilibili:horizontal` / `:vertical` | 1920x1080 / 1080x1920 | [S] |
| `wechat-channels:vertical` / `:horizontal` | 1080x1920 / 1920x1080 | 视频号: aspect 0.33-3.0 accepted, 16:9 or 9:16 recommended, ≤ 2 GB, no HDR [S: 视频号 help centre]; the old 6:7 (1080x1260) size now only matters for share cards [3P] |
| `x:horizontal` / `:square` / `:vertical` | 1920x1080 / 1080x1080 / 1080x1920 | 16:9 recommended, 1:1 and 9:16 supported, max 1920x1200 / 1200x1920 [3P, several agree]. A bare `x` target picks the orientation closest to the master (`auto_orientation`) - no letterbox |
| `instagram:reels` | 1080x1920 (9:16) | [S: all guides agree]; **the feed shows a centre 4:5 crop** (y 285-1635) [3P] |
| `instagram:feed` | 1080x1350 (4:5) | tallest feed post [3P, several agree]; videos posted to feed are Reels since 2023 [S: Meta API docs] |

## Safe zones (px on the profile canvas: top / bottom / left / right, + lower-right button column)

| profile | top | bottom | left | right | right_lower keep-out | tag |
|---|---|---|---|---|---|---|
| xiaohongshu:full | 240 | 260 (y 1660) | 60 | 60 | 160 w from y 960 | [C] measured by the talkinghead workflow (`safe_zone` persona key) |
| xiaohongshu:vertical | 60 | 150 | 48 | 48 | 120 w from y 900 | [C] the full-screen numbers mapped onto a 3:4 frame, then padded |
| xiaohongshu:horizontal | 60 | 60 | 280 | 280 | – | [C] left/right = outside the 4:3 feed crop (240) + 40 |
| douyin:vertical | 160 | 440 | 60 | 150 | 180 w from y 900 | [C] from the TikTok numbers (same UI family); 3P says "centre 1080x1350" |
| tiktok:vertical | 130 | 484 | 60 | 140 | – | [3P] most-cited set: 130/484/44/140 (bottom grows with long captions) |
| youtube-shorts:vertical | 180 | 390 | 60 | 120 | – | [3P] AdConvert set; others range 120-380 top, 300-390 bottom |
| youtube / bilibili horizontal | 54 | 54-80 | 96 | 96 | – | [C] 5 % title-safe; bilibili bottom +danmaku/progress bar |
| bilibili:vertical | 200 | 420 | 60 | 150 | – | [C] |
| wechat-channels:vertical | 200 | 460 | 60 | 60 | – | [C] no published numbers; bottom = author / description / like row |
| wechat-channels:horizontal | 54 | 80 | 96 | 96 | – | [C] |
| x:horizontal / square | 54 | 90 | 96 / 60 | 96 / 60 | – | [C] player controls at the bottom; timeline video has almost no overlay |
| x:vertical | 160 | 380 | 60 | 120 | – | [C] immersive player: post text + action row at the bottom |
| instagram:reels | 285 | 450 | 60 | 130 | 170 w from y 1000 | top = 4:5 feed crop (285) ≥ UI 200-220 [3P]; bottom 400-450 [3P: CampaignSwift 400, Somake 450, Xyla 430]; right rail [3P] |
| instagram:feed | 60 | 120 | 60 | 60 | – | [C] mute / tag icons only |

## Captions

`caption.band` [y0, y1], `size` [min, max] px, `max_chars_zh` / `max_chars_en` per line, `max_lines` 2. All **[C]**:
vertical 52-72 px, 14 CJK / 32 latin per line (the repo's `subtitles.max_cjk_chars` 18 is for 16:9 / wide boxes);
horizontal 44-60 px, 22 CJK / 48 latin. 小红书 9:16 band centred on y ≈ 1525 (talkinghead workflow).
`platform.fit_text_size()` picks the largest size that wraps into `max_lines` inside `caption_box()`.

## Length (seconds: sweet spot / hard max)

| profile | sweet | max | tag |
|---|---|---|---|
| xiaohongshu | 30-180 | 900 (15 min) | max [3P, several agree; some accounts higher]; sweet [C] |
| douyin | 15-60 | 900 | max [C] (in-app 15 min common; longer for some accounts) |
| tiktok | 21-60 | 600 | 10 min in-app / Content Posting API [S]; 60 min web upload for some accounts [3P] |
| youtube | 420-1200 | 43200 (12 h) | max [S]; sweet [C] |
| youtube-shorts | 20-60 | 180 | [S] |
| bilibili | 180-900 | 36000 | [C] |
| wechat-channels | 15-120 | 28800 | phone 3 s-60 min, computer (视频号助手) up to 8 h [S: 视频号 help centre via search, page ~2 y old]; sweet [C] |
| x | 15-90 | 140 (standard) | 140 s / 512 MB [3P, all agree]; **Premium**: sources disagree (2 h vs 4 h, 8 vs 16 GB; Android 10 min) → profile tiers `premium` 7200 s / 8 GB, `premium_plus` 14400 s / 16 GB [3P, unverified: help.x.com blocked automated reads] |
| instagram | 15-90 | 1200 | 20 min Reels since 2025 [3P, several]; **> 3 min is not recommended to non-followers** (`reach_max` 180, warned) [3P citing the IG Help Center]; min 3 s; 4 GB [3P] |

## Loudness, fps, encode

- **YouTube −14 LUFS** is well established [S: many guides; YouTube turns louder uploads down]. TikTok/Douyin/小红书/B站
  publish no target: −14 LUFS integrated, **−1.5 dBTP** everywhere [C] (repo default `audio.loudness_lufs`;
  guides agree on ≤ −1 dBTP because platform transcodes overshoot). B站 reportedly does not normalise [3P, Zhihu].
  Override per platform in the persona (e.g. a hotter −12 LUFS short-form master).
- fps: deliver at the source rate, 30 default; capped at 60 (120 on B站) [S YouTube: "same frame rate as recorded"].
- Encode: H.264 High, yuv420p, BT.709, AAC 48 kHz, +faststart [S YouTube recommended upload settings].
  YouTube 1080p30 SDR ≈ 8 Mbps (12 at 60 fps), "no bitrate limit" [S] → CRF 18 with a 16 M cap [C].
  B站 1080p re-encodes above ~6 Mbps average / 24 Mbps peak [3P] → CRF 18, maxrate 24 M [C].
  小红书 8-12 Mbps advised [3P] → CRF 18, 16 M cap. TikTok/Douyin CRF 20, 12 M cap [C].
  X: H.264 High, AAC-LC, 30/60 fps, ≤ ~25 Mbps [3P] → CRF 20, 12 M cap; Instagram / 视频号 CRF 20, 12 M cap [C].
- Upload caps live in `limits.max_bytes` (X 512 MB standard, Instagram 4 GB, 视频号 2 GB); `vstudio.export` warns
  when a file is over the cap for the account tier.
- **X autoplays muted** in the timeline: the profile says `captions.burn: recommended`, and an X export without
  `--cues` warns. Loudness for X / Instagram / 视频号: −14 LUFS / −1.5 dBTP [C; 3P guides cite −14 for Reels].

## Covers

| profile | size | title-safe / feed crop | tag |
|---|---|---|---|
| xiaohongshu vertical/full | 1080x1440 3:4 | – | [S] |
| xiaohongshu horizontal | 1920x1080 | **feed shows centre 4:3** → `.feed.jpg` preview | [3P + workflows/cover] |
| douyin / tiktok vertical | 1080x1920 | profile grid shows centre 3:4 | [3P] |
| youtube | 1280x720, ≤ 2 MB (desktop now allows larger) | bottom-right timestamp: title-safe ends at x 1100 | [S] |
| youtube-shorts | 1080x1920 | – | [C] |
| bilibili horizontal | 1146x717 (16:10), min 960x600, ≤ 5 MB | **also cropped to 4:3 (phone home feed) and 16:9** → `crops: [4:3, 16:9]`, title-safe = the intersection | size [3P, several agree]; crops [3P: B站 creator post, updated 2023-11; it says 4:3 1200x900 is now asked for - the uploader crops one image per ratio] |
| wechat-channels vertical | 1080x1440 (3:4) | share card 6:7 (1080x1260) → `crops: [6:7]` | [3P] |
| x | = the video canvas (thumbnail is a frame you pick) | – | [C] |
| instagram:reels | 1080x1920 | **4:5 feed, 3:4 profile grid (since 2025), 1:1** (older grid / some surfaces) → title-safe = centre 1080x1080 (y 420-1500) | 9:16 + 4:5 [3P, several]; grid 3:4 vs 1:1 vs 4:5 [3P disagree → check all three] |
| instagram:feed | 1080x1350 | 3:4 grid, 1:1 | [3P] |

**Crop check.** For every crop in `platform.cover_crops(p)` the export writes `<target>.cover.crop-4x5.jpg` etc. and
`<target>.cover.crops.jpg` (all crops + the title-safe box outlined), and `export.cover_crop_check` measures the
share of busy 48 px tiles (text / faces / detail) in each strip a crop removes: over 15 % → a warning that the
headline is probably cut in that view.

## Title / description / tags / chapters

| platform | title | description | tags | chapters |
|---|---|---|---|---|
| 小红书 | 20 (CJK 1, latin 0.5; `config.xhs_len`) [S] | 1000 [S] | #话题 in body [C: ≤10] | none native; 时间线 text, labels ≤ 14 [C] |
| 抖音 | 55 [3P, practical app limit] | 1000 incl. #话题/@ (open-platform API) [S] | inline | no |
| TikTok | 55 [C, same as `publish`] | 4000 (2200 via API) [S] | inline, ≤ 30 [3P] | no |
| YouTube / Shorts | 100 [S] | 5000 [S] | first 3 shown above title, > 60 → all ignored [S] | ≥ 3, first 00:00, each ≥ 10 s [S] |
| B站 | 80 [3P] | 2000 (250 in some 分区) [3P] | ≤ 10 tags, ≤ 20 chars each [3P] | 分段章节 in the uploader [C] |
| 视频号 | 短标题 16 [3P, unverified: the uploader shows the limit] | 1000 incl. #话题 / @ [3P] | inline #话题 [C ≤ 10] | no |
| X | none (the post text is everything) | **280 weighted** (standard) / 25,000 (Premium) [3P]: twitter-text v3 - Latin/punctuation 1, **CJK and emoji 2**, any URL 23 [S: twitter-text config/v3.json] | 1-2 [C, common guidance] - `publish` keeps the first 2 | no |
| Instagram | none (first caption line = hook) | 2,200 [S: Meta Content Publishing API docs] | **max 5 per post/reel since Dec 2025** (was 30) [S: Instagram @creators announcement, reported widely]; 3-5 recommended | no |

Fields: B站 needs a **分区** (`category.required`; `tid` through the open platform) and the creator's own **自制 / 转载**
choice - never pre-filled by the desk. `platform.check_text` counts X weighted (`desc_count: x`), and hashtags
across the tag list AND the #tags already in the body.

**Post language.** `vstudio.publish.platform_post` (used by `vstudio.export --post`) picks the copy per platform:
post.json may hold `en` / `zh` blocks; English content (detected from the cues, or `--lang en`) gets English copy
on X / Instagram / TikTok / YouTube; `--bilingual` = English then Chinese. English copy never inherits the persona's
Chinese tags (`publish.tag_sets.en` is used if present). X copy is shortened by whole sentences to 280 weighted.
`publish.generate_copy(platform, source)` asks the routed LLM (task `copy`) for copy within these limits.

`title_max` agrees with `vstudio.publish.TITLE_MAX_DEFAULT`, and both read the same persona key
(`platforms.<name>.title_max`).

## Multi-platform export

```bash
python3 -m vstudio.export work/master.mp4 --platforms xiaohongshu:vertical,douyin,youtube \
    --out exports/ --cues work/cues.json --cover work/cover-3x4.png --cover work/cover-16x9.png --post work/post.json
# international: x picks 16:9 / 1:1 / 9:16 from the master; Reels + a 4:5 feed cut; English copy + 2 / 5 tags
python3 -m vstudio.export work/master.mp4 --platforms x,instagram,instagram:feed --cues work/cues.json \
    --cover instagram=work/cover-9x16.png --post work/post.json [--lang en | --bilingual] [--account premium]
```
Keep the **master caption-free** and the cues separate (`subs.Cue.to_dict` JSON or SRT). Each export then gets
captions placed and sized for that platform's UI. Text burned into a 16:9 master gets cropped off on 3:4 / 9:16.
Reframe: `face` mode follows the main face inside the safe box. If no face is found it uses a blurred fill
(`pad-blur`). A master of the same aspect is a plain ffmpeg scale (no face tracking; manifest says `scale`).

- **Masters with burned overlays** (记笔记 panels, stamps, hook titles): put `keepouts` in cues.json -
  `{"cues": [...], "keepouts": [{"t0", "t1", "box": [x, y, w, h], "kind"}], "size": [W, H]}`, boxes in master
  px (or 0..1 fractions), final seconds. Each box is mapped through the reframe and the caption moves above /
  below it while it is on screen (`captions_moved_frames` in the manifest; a warning if there is no free spot).
  `--no-captions` skips burning when the master already has its captions.
- **Keyword colour** survives re-burning: 【kw】 markup in cue text, or per cue `"hl": ["kw", ...]` / `[[i, j]]`
  char spans, and `"style": {"fill": "#fff", "highlight": "#FFD60A"}`.
- **Covers**: `--cover xiaohongshu=cover_3x4.png --cover douyin=cover_9x16.png` gives each target its own cover.
  A generic `--cover` of another aspect is fitted on a blurred pad (a centre crop cuts the headline) with a
  warning - render a real cover per aspect for anything you publish.
Outputs: `<platform>-<orientation>.mp4`, `.cover.jpg` (+ `.cover.feed.jpg`), `.crop.json`, `.post.md`, and `manifest.json`
(sizes, durations, measured loudness, reframe hit rate, pan stats, warnings).

## Platforms added 2026-10

Tags as above ([S] / [3P] / [C]). Meta, Pinterest, Reddit and Dailymotion help pages mostly refused automated reads,
so several of their numbers are [3P]; **no platform below publishes a loudness target** → −14 LUFS / −1.5 dBTP [C].

| platform (profiles) | canvas | safe zone (top/bottom/left/right) | length | size | title | text | hashtags | links |
|---|---|---|---|---|---|---|---|---|
| Facebook (`facebook:reels` default, `:feed` 4:5, `:horizontal`) | 1080x1920 / 1080x1350 / 1920x1080 [3P] | Reels 269/672/65/65 = Meta's 14 % / 35 % / 6 % [3P citing Meta Business Help]; feed / 16:9 [C] | Reels: no cap since 2025-06, 240 min upload cap [3P]; **Reels API 3-90 s** [S] → max 14400, sweet 15-90 [C] | 4 GB [3P] | none | 2,200 [C: Reels caption limit unsourced; posts 63,206 3P] | 3-5 [3P] | feed clickable, Reels not reliably [C] |
| LinkedIn (`linkedin:horizontal` default, `:square`, `:feed` 4:5; auto-orientation) | 16:9 / 1:1 / 4:5, any 1:2.4-2.4:1 [3P] | [C] | 3 s-15 min organic [3P] (API / ads 30 min [S]) | 5 GB [3P] (API 500 MB-5 GB [S]) | none for organic posts [3P] | **3,000** [S] | 1-3, keyword signal only [3P] | clickable; reach penalty disputed [3P] |
| Threads (`threads:vertical` default, `:horizontal`) | 9:16 rec., ratios 0.01-10, width ≤ 1920 [S] | [C] = X vertical | ≤ 5 min [S] | 1 GB [S] | none | **500** [S] | **one topic tag** [3P] (hard) | clickable; ≤ 5 links via API [S] |
| Reddit (`reddit:horizontal` default, `:square`, `:vertical`) | 16:9 / 1:1 work best in the feed [3P] | [C] | 15 min [3P] | 1 GB [3P] | **300, required**, not editable [3P] | 40,000 (self-post) [3P] | **none** | clickable (markdown) |
| Pinterest (`pinterest:vertical` default, `:feed` 2:3, `:square`) | 9:16, 2:3, 1:1; ratio 1:2-1.91:1 [3P] | 270 / **790** / 65 / 195 [3P, citing Pinterest] | 4 s-15 min, 5 min organic per one 3P (sources disagree) | 2 GB [3P] | 100 [3P] | 500 [3P] | none: up to 10 topics picked on the page [S] | **separate destination-link field** [S] |
| Snapchat Spotlight (`snapchat:vertical`) | 9:16, ≥ 540x960 [S] | [C] | **5-60 s** web [S] | 1 GB [3P] | none | ~160 [3P] | #Topics, 1-3 [C]; irrelevant ones raise rejection [3P] | none |
| 快手 (`kuaishou:vertical` default, `:horizontal`) | 9:16 main, 16:9 / 1:1 [3P] | [C], bottom ≈ 20 % UI | **15 min / 4 GB web** [S: help centre] (others 10-30 min [3P]) | 4 GB [S] | none (one 文字描述 = caption; API `caption` required) | 500 [3P] | #话题 (one #), 1-3 niche [3P] | not clickable, 站外导流 penalised [3P] |
| 微博 (`weibo:horizontal` default, `:vertical`; auto-orientation) | 16:9 / 9:16 [3P] | [C] | 15 min ordinary accounts [3P] | **PC 15 GB** [S: kefu FAQ] | 投稿 title **≥ 6 chars** [S]; max 30 [C] | 2,000 [3P] | **#话题#** (two hashes) [S: help.sina] ≤ 3 [C] | 网页链接 short links; non-whitelisted domains get a risk prompt [S: m.weibo.cn/outlink_rules.html] |
| 知乎 (`zhihu:horizontal` default, `:vertical`) | 16:9 safest [C] | [C] | PC 1 h / 2 GB [3P] | 2 GB [3P] | **30, required** [3P] | 简介 300 [3P] | no inline tags: 话题 field (≤ 5 [C]) | not clickable (unverified), 导流 loses 优质 [3P] |
| Dailymotion (`dailymotion:horizontal` default, `:vertical`) | 16:9 and 9:16 [S snippet] | [C] | **2 h / 4 GB** standard accounts, 15 uploads / 24 h [S snippet] | 4 GB | **1-255, required** [S: API docs] | 3,000 [S snippet] | ≤ 15 #hashtags in the description, 2-25 chars [S] | clickable |
| Kwai (`kwai:vertical`) | 9:16 native | [C] = 抖音 | no public spec; 57 s camera / ~5 min editor / 10-12 min gallery claims disagree → max 300 [C] | – | none | 500 [C] | ≤ 5 [C] | not clickable [C] |

Required choices the desk never makes for the creator: Reddit subreddit (typed by her), flair, NSFW / spoiler;
Pinterest board + topics; 微博 投稿 频道 / 标签 / 原创; 知乎 领域 / 话题 / 原创; Dailymotion category / language /
made-for-kids; every Chinese platform's **AI 生成内容声明** (《人工智能生成合成内容标识办法》, in force 2025-09-01
[S: https://www.news.cn/legal/20250901/a12108b0b10249e5bae4435269e40c91/c.html]).

**Reddit norms.** No sitewide 9:1 rule any more: Reddit says some communities use a 10 % self-promotion rule and some
ban promotion outright [S: https://support.reddithelp.com/hc/en-us/articles/28012014962580]; spam is never allowed
and posts should be in communities you take part in [S: https://support.reddithelp.com/hc/en-us/articles/360043504051-Spam];
don't flood several communities at once [S: Reddiquette https://support.reddithelp.com/hc/en-us/articles/205926439-Reddiquette];
NSFW must be tagged [S: https://support.reddithelp.com/hc/en-us/articles/15484642147988]. Flair, account age and
karma minimums are per subreddit: read the sidebar rules, disclose that it is your own video, upload the file
itself (no channel link), and expect some communities to remove it.

Re-checked 2026-10-06: TikTok uploads up to **60 min** (in-app recording 10 min; some accounts still 10 min)
[S: https://support.tiktok.com/en/using-tiktok/creating-videos/camera-tools] → `length.max` 3600; 抖音 web 15 min /
4 GB (open-platform spec agrees) → `limits.max_bytes`. YouTube thumbnails: guides now cite up to 3840x2160 / 50 MB
on desktop; 1280x720 ≤ 2 MB stays the safe default [3P]. Link handling is per profile (`links`, `platform.link_policy`):
`check_text` warns when a URL is in the text where it is not clickable (Instagram, TikTok, Shorts, 小红书, 抖音 ...)
or belongs in a link field (Pinterest).

### French- and Spanish-speaking markets: why only Dailymotion and Kwai
These markets run on the **global platforms** already in the list. France: YouTube 51.5 M, Facebook 31.5 M, **Snapchat
29.8 M**, Instagram 28.2 M, TikTok 23.4 M ad reach [S: https://datareportal.com/reports/digital-2026-france];
Snapchat is #1 with 11-14 year-olds (Médiamétrie 2025, via press). Quebec: Facebook 74 %, YouTube, Instagram, TikTok
[S: https://transformation-numerique.ulaval.ca/enquetes-et-mesures/netendances/reseaux-sociaux-et-divertissement-en-ligne-2025/].
Francophone Africa: Facebook ≈ 80 %+ of social web visits, TikTok growing [S: https://gs.statcounter.com/social-media-stats/all/cameroon].
Spain: WhatsApp, Instagram 57.9 %, TikTok 31 % [S: https://www.cnmc.es/prensa/panel-hogares-ott-internet-20260522].
Mexico: TikTok 99 M, Facebook 93.5 M, YouTube 85 M [S: https://datareportal.com/reports/digital-2026-mexico].
- **Dailymotion** - the only French platform at scale (Médiamétrie "Dailymotion Network" 50.5 M visitors / month, mostly
  embeds on partner sites [S: Médiamétrie 2025-11 press release]); full desktop web upload + official upload API → added.
- **Kwai** - Brazil ≈ 60 M MAU (company claim [3P: https://www.caixinglobal.com/2025-12-11/kuaishous-kwai-conquers-brazil-by-ditching-the-time-machine-strategy-102392161.html]),
  smaller in Colombia / Argentina; **no desktop web upload** (kwai.com is viewing / marketing; Kwai Studio is for live
  streaming [S: https://www.kwai.com/pt-BR/support/live-streaming/como-fazer-transmissao-ao-vivo-em-computador-pc]) →
  profile added for packaging, publishing is a phone step.
- **Snapchat Spotlight** - strong in France, official web uploader (profile.snapchat.com) → in the global group.
- Skipped: Twitch (live, no VOD upload target), Telegram / WhatsApp (messaging, not a feed), Vimeo (hosting, low
  discovery), VK, Taringa (closed), Rumble / Odysee / PeerTube / Likee / Triller (no significant share, mostly app-only).

Sources (added 2026-10): Facebook https://developers.facebook.com/docs/video-api/guides/reels-publishing ,
https://postfa.st/sizes/facebook/reels , https://posteverywhere.ai/blog/facebook-aspect-ratios , https://www.biddyco.com/blog-posts/meta-ad-specs ,
https://postiz.com/blog/facebook-reel-size ; LinkedIn https://www.linkedin.com/help/linkedin/answer/a528176 ,
https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api , https://www.brandwatch.com/blog/linkedin-video-specs/ ,
https://postfa.st/sizes/linkedin/video , https://authoredup.com/blog/linkedin-character-limit ; Threads https://developers.facebook.com/docs/threads/overview ,
https://developers.facebook.com/docs/threads/posts/ , https://searchengineland.com/threads-hashtags-topic-tags-435595 ; Reddit
https://www.tella.com/blog/how-to-post-videos-on-reddit , https://typecount.com/blog/reddit-post-character-limit ; Pinterest
https://help.pinterest.com/en/article/create-a-pin-from-an-image-or-video , https://linkgrab.io/pinterest-video-size-and-format ,
https://84pins.com/pinterest-video-pin-specs/ , https://moda.app/resources/sizes/pinterest ; Snapchat
https://help.snapchat.com/hc/en-us/articles/7012293789972-How-do-I-submit-a-Snap-to-Spotlight-from-the-web ,
https://help.snapchat.com/hc/en-us/articles/7012310003348-How-to-Post-a-Snap-to-My-Story-from-the-Web ; 快手
https://www.kuaishou.com/help/feedback/4000?categoryId=hot , https://open.kuaishou.com/platformDocs/openAbility/contentManagement/createAVideo.html ,
https://a.newrank.cn/trade/news/5958 ; 微博 https://kefu.weibo.com/faqdetail?id=21503 , http://help.sina.com.cn/comquestiondetail/view/422/ ,
https://m.weibo.cn/outlink_rules.html , https://xueyuan.yixiaoer.cn/article/6317 ; 知乎 https://zhuanlan.zhihu.com/p/420973568 ,
https://zhuanlan.zhihu.com/p/372236311 ; Dailymotion https://faq.dailymotion.com/hc/en-us/articles/115009030568-Upload-policies-technical-specifications ,
https://faq.dailymotion.com/hc/en-us/articles/10316200097298-Create-and-manage-hashtags-on-videos , https://developers.dailymotion.com/docs/upload-videos ;
TikTok https://support.tiktok.com/en/using-tiktok/creating-videos/camera-tools .

## Sources
- X video specs / length / Premium tiers (conflicting): https://www.nemovideo.com/blog/twitter-video-specs-guide-2026 ,
  https://xroadstudio.com/platform-specs/x , https://www.sendcove.app/integrations/twitter/video-specs , https://www.bulkpublish.com/blog/x-twitter-limits/
- X weighted counting: https://raw.githubusercontent.com/twitter/twitter-text/master/config/v3.json ,
  https://redmooncalculators.com/blog/twitter-character-counting-explained/ , https://textlimits.com/blog/x-twitter-character-limit/
- Instagram Reels size / feed 4:5 crop / grid crops / safe zone: https://www.krumzi.com/size-guide/instagram-reel-size ,
  https://stan.store/blog/instagram-post-size-guide-2026/ , https://campaignswift.com/blog/instagram-safe-zone-sizes ,
  https://www.somake.ai/blog/instagram-reel-size-guide , https://www.xyla.ai/tools/social-media-sizes/ , https://www.jwtoolbox.com/blog/instagram-reel-cover-size-cheat-sheet-2026
- Instagram length 20 min / >3 min reach / 4 GB: https://zeely.ai/blog/how-long-can-instagram-reels-be/ , https://www.socialcal.app/blog/instagram-video-length-limits-2026
- Instagram 5-hashtag cap: https://www.socialmediatoday.com/news/instagram-implements-new-limits-on-hashtag-use/808309/ ,
  https://later.com/blog/ultimate-guide-to-using-instagram-hashtags/
- Instagram caption 2,200 / publishing API: https://developers.facebook.com/docs/instagram-platform/content-publishing/
- 视频号 formats (help centre) and sizes: https://findeross.weixin.qq.com/cgi-bin/mmfindernodelivecrmwebbroker-bin/helper-center/pages/Yhdpjlq2RIkcmnQu ,
  https://www.zhihu.com/question/424117543 , https://zhuanlan.zhihu.com/p/459415659 , https://cloud.tencent.com/developer/news/1874769
- B站 cover crops 4:3 / 16:10 / 16:9: https://www.bilibili.com/opus/517638323328040669
- YouTube recommended upload encoding settings: https://support.google.com/youtube/answer/1722171
- YouTube Shorts 3-minute limit, title 100 / description 5000, chapter rules: https://www.descript.com/blog/article/how-long-can-youtube-shorts-be ,
  https://hashtagtools.io/blog/youtube-shorts-character-limits-title-description-hashtags-2026 , https://timeskip.io/blog/youtube-video-chapters
- YouTube thumbnail 1280x720 / 2 MB: https://thumbnailtest.com/guides/youtube-thumbnail-size/ , https://havecamerawilltravel.com/youtube-thumbnail-size/
- YouTube Shorts safe zones: https://adconvert.org/tools/youtube-shorts-safe-zone-checker , https://reformat.video/tools/youtube-shorts-safe-zone ,
  https://postplanify.com/tools/youtube-shorts-safe-zone-checker
- TikTok safe zone: https://cadenus.io/resources/blog/tiktok-safe-zone/ , https://www.xyla.ai/tools/social-media-sizes/ , https://postplanify.com/tools/tiktok-safe-zone-checker
- TikTok caption / length: https://lettercounter.org/blog/tiktok-character-limit-guide/ , https://sociality.io/blog/tiktok-video-length/
- Loudness (YouTube −14; no official TikTok/Douyin figure; true-peak headroom): https://apu.software/tiktok-instagram-reels-loudness/ ,
  https://www.sweetwater.com/insync/loudness-standards-lufs-peaks-and-streaming-limits/ , https://zhuanlan.zhihu.com/p/649576826
- 小红书 sizes / title / body: https://www.autoxhs.cn/blog/xiaohongshu-fengmian-chicun , https://resouci.com/xiaohongshu-image-size-guide-2026/ ,
  https://xueyuan.yixiaoer.cn/article/36494 , https://www.opp2.com/198169.html
- 小红书 duration / bitrate: https://insight.xiaoduoai.com/commerce-knowledge/xiaohongshu-information/ , https://ixiaguo.com/h-nd-490730.html
- 抖音 title limit (open platform create-video API, 1000 chars incl. topics): https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create
- 抖音 sizes / cover crops: https://www.secaiyun.com/docs/douyin-kuaishou-video-size-specification-guide-2026-06-02.html , https://zhuanlan.zhihu.com/p/507190726
- B站 cover 1146x717, title 80, tags, bitrate: https://image.mid-life.vip/help/bzhan-fengmian-chicun , https://www.cnblogs.com/suyj/p/20384825 ,
  https://www.zhihu.com/question/452825495 , https://www.zhihu.com/question/397360058 , https://deervideo.net/guide/bilibili-video-upload-format
