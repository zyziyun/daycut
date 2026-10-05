# Platform profiles

`lib/vstudio/platform.py` holds the defaults. Override any field in `persona.local.yaml` under
`platforms.<name>` (or `platforms.<name>.orientations.<o>`). `python -m vstudio.platform` prints every
profile. `python -m vstudio.export` uses them to produce per-platform files (see the bottom of this page).

Researched October 2026. Platforms change their UI and limits often, and **none of the Chinese platforms
publish safe-zone pixels or loudness targets**. Each value below is tagged:
**[S]** sourced (official doc, or several independent guides that agree), **[3P]** one or two third-party
guides, **[C]** convention (our own working default, measured in-app or chosen to be conservative).
When a platform's UI changes, preview on a phone and update the persona, not the code.

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

## Covers

| profile | size | title-safe / feed crop | tag |
|---|---|---|---|
| xiaohongshu vertical/full | 1080x1440 3:4 | – | [S] |
| xiaohongshu horizontal | 1920x1080 | **feed shows centre 4:3** → `.feed.jpg` preview | [3P + workflows/cover] |
| douyin / tiktok vertical | 1080x1920 | profile grid shows centre 3:4 | [3P] |
| youtube | 1280x720, ≤ 2 MB (desktop now allows larger) | bottom-right timestamp: title-safe ends at x 1100 | [S] |
| youtube-shorts | 1080x1920 | – | [C] |
| bilibili horizontal | 1146x717 (16:10), min 960x600, ≤ 5 MB | – | [3P, several agree] |

## Title / description / tags / chapters

| platform | title | description | tags | chapters |
|---|---|---|---|---|
| 小红书 | 20 (CJK 1, latin 0.5; `config.xhs_len`) [S] | 1000 [S] | #话题 in body [C: ≤10] | none native; 时间线 text, labels ≤ 14 [C] |
| 抖音 | 55 [3P, practical app limit] | 1000 incl. #话题/@ (open-platform API) [S] | inline | no |
| TikTok | 55 [C, same as `publish`] | 4000 (2200 via API) [S] | inline, ≤ 30 [3P] | no |
| YouTube / Shorts | 100 [S] | 5000 [S] | first 3 shown above title, > 60 → all ignored [S] | ≥ 3, first 00:00, each ≥ 10 s [S] |
| B站 | 80 [3P] | 2000 (250 in some 分区) [3P] | ≤ 10 tags, ≤ 20 chars each [3P] | 分段章节 in the uploader [C] |

`title_max` agrees with `vstudio.publish.TITLE_MAX_DEFAULT`, and both read the same persona key
(`platforms.<name>.title_max`).

## Multi-platform export

```bash
python3 -m vstudio.export work/master.mp4 --platforms xiaohongshu:vertical,douyin,youtube \
    --out exports/ --cues work/cues.json --cover work/cover-3x4.png --cover work/cover-16x9.png --post work/post.json
```
Keep the **master caption-free** and the cues separate (`subs.Cue.to_dict` JSON or SRT). Each export then gets
captions placed and sized for that platform's UI. Text burned into a 16:9 master gets cropped off on 3:4 / 9:16.
Reframe: `face` mode follows the main face inside the safe box. If no face is found, or the aspect is the same, it uses a blurred fill (`pad-blur`) or a plain scale.
Outputs: `<platform>-<orientation>.mp4`, `.cover.jpg` (+ `.cover.feed.jpg`), `.crop.json`, `.post.md`, and `manifest.json`
(sizes, durations, measured loudness, reframe hit rate, pan stats, warnings).

## Sources
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
