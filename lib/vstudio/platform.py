"""Platform profiles: canvas, UI safe zones, caption style, length / loudness / encode guidance, cover
and post-copy limits (title / text / hashtags / link handling) for
  English / global: YouTube (long-form + Shorts), TikTok, Instagram (Reels / feed), X, Facebook (Reels / feed),
                    LinkedIn, Threads, Reddit, Pinterest, Snapchat (Spotlight)
  Chinese:          小红书, 抖音, 视频号 (WeChat Channels), B站, 快手, 微博, 知乎
  other languages:  Dailymotion (France), Kwai (Latin America / Brazil)

    from vstudio import platform as P
    p = P.profile("xiaohongshu", "vertical")      # Profile(w=1080, h=1440, ...); persona overrides merged
    P.safe_box(p)        -> (x0, y0, x1, y1)        UI-free area (top bar / bottom description / side buttons)
    P.caption_box(p)     -> (x0, y0, x1, y1)        where burned captions go
    P.cover_size(p)      -> (w, h)
    P.fit_text_size(p, "一行字幕")  -> {"size": 64, "lines": [...]}
    P.list_profiles()    -> ["xiaohongshu:vertical", "xiaohongshu:full", ...]
    P.best_orientation("x", 9 / 16) -> "vertical"   (the orientation closest to a master's aspect)
    P.cover_crops(p)     -> ["4:5", "3:4", "1:1"]   every crop a surface shows of the cover (feed / grid)
    P.text_len(p, body)  -> X: weighted length (CJK / emoji = 2, URL = 23); else characters
    P.ordered(["douyin", "x", "kwai"], connected=["douyin"]) -> ["x", "douyin", "kwai"]   (display order, below)
    P.youtube_format(9 / 16, 75) -> "shorts";  P.check_format(p, aspect, seconds) -> warnings
    P.link_policy(p)     -> {"clickable": False, ...}   (check_text warns about links that won't work)
    P.publishing(name)   -> {"mode": "assisted", "upload_url": ..., "api": {...}}   (see references/PUBLISHING.md)

Order: every list of platforms shown to a person (pickers, publish page, accounts, calendar, website) uses
``ORDER``: English / global first, then Chinese, then other-language platforms; ``ordered`` floats the platforms
with a connected account to the top WITHIN their group.

YouTube is ONE channel with two formats: ``youtube`` (long-form, 16:9) and ``youtube-shorts`` (vertical / square,
<= 3 min). ``channel_of("youtube-shorts") == "youtube"``; ``FORMATS["youtube"]`` maps format -> profile name.

Account tiers: a profile may carry ``tiers`` (X: premium / premium_plus); ``account: premium`` (persona
``platforms.x.account`` or ``overrides``) merges that tier's limits (longer videos, longer posts).

Every number is either sourced or marked "convention" in references/PLATFORMS.md. Platforms change their
UI often: treat safe zones as conservative defaults and override them in persona.local.yaml
(``platforms.<name>.<field>`` or ``platforms.<name>.orientations.<orientation>.<field>``, deep-merged).

Back-compat with older persona keys: ``platforms.<name>.title_max`` (also read by vstudio.publish),
``cover_aspect`` and ``safe_zone: {top, bottom, right_lower_keepout}`` (y coordinates on a 1080x1920
canvas; applied to the 1920-tall orientation).
"""
import copy
from dataclasses import asdict, dataclass, field

ALIASES = {"fb": "facebook", "facebook-reels": "facebook", "meta": "facebook", "脸书": "facebook",
           "li": "linkedin", "领英": "linkedin", "threads.net": "threads", "threads.com": "threads",
           "pin": "pinterest", "snap": "snapchat", "spotlight": "snapchat", "snapchat-spotlight": "snapchat",
           "ks": "kuaishou", "快手": "kuaishou", "微博": "weibo", "sina-weibo": "weibo", "知乎": "zhihu",
           "dm": "dailymotion", "kwai-app": "kwai", "youtube-long": "youtube", "long": "youtube",
           "xhs": "xiaohongshu", "rednote": "xiaohongshu", "小红书": "xiaohongshu", "dy": "douyin", "抖音": "douyin",
           "yt": "youtube", "shorts": "youtube-shorts", "yt-shorts": "youtube-shorts", "youtube_shorts": "youtube-shorts",
           "b站": "bilibili", "bili": "bilibili", "tt": "tiktok",
           "twitter": "x", "x.com": "x", "推特": "x", "ig": "instagram", "ins": "instagram", "insta": "instagram",
           "reels": "instagram", "instagram-reels": "instagram",
           "视频号": "wechat-channels", "channels": "wechat-channels", "weixin-channels": "wechat-channels",
           "wechat_channels": "wechat-channels", "wxchannels": "wechat-channels", "wechat": "wechat-channels"}
ORIENT_ALIASES = {"v": "vertical", "portrait": "vertical", "3:4": "vertical", "feed": "vertical",
                  "9:16": "full", "fullscreen": "full", "h": "horizontal", "landscape": "horizontal", "16:9": "horizontal",
                  "1:1": "square", "sq": "square"}

# ----------------------------------------------------------------------------------- shared blocks
_VERT_CAPTION = dict(size=[52, 72], max_chars_zh=14, max_chars_en=32, max_lines=2, stroke=0.09)
_HORZ_CAPTION = dict(size=[44, 60], max_chars_zh=22, max_chars_en=48, max_lines=2, stroke=0.08)
_LOUD = dict(lufs=-14.0, tp=-1.5)        # repo default (persona audio.loudness_lufs); see PLATFORMS.md

# name -> common fields + per-orientation fields. Coordinates are px on that orientation's canvas.
# safe: margins {top, bottom, left, right} + optional right_lower {w, from_y} keep-out (button column).
# caption.band: [y0, y1] of the caption block. length: seconds. encode: media.delivery_args kwargs.
PLATFORMS = {
    "xiaohongshu": dict(
        label="小红书 RedNote", default="vertical",
        group="zh", links=dict(clickable=False, avoid=True, note="off-site links count as 导流 and are removed"),
        title_max=20, title_count="xhs", desc_max=1000,
        hashtags=dict(style="inline", max=10, note="#话题 at the end of the body; counts toward 1000"),
        chapters=dict(supported=False, note="no native chapters; a 时间线 list in the body is the convention",
                      label_max=14),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[30, 180], max=900, min=5),
        orientations=dict(
            vertical=dict(w=1080, h=1440, aspect="3:4",
                          safe=dict(top=60, bottom=150, left=48, right=48, right_lower=dict(w=120, from_y=900)),
                          caption=dict(_VERT_CAPTION, band=[1080, 1270]),
                          cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1240], feed_crop=None),
                          cover_aspect="3:4"),
            full=dict(w=1080, h=1920, aspect="9:16",
                      safe=dict(top=240, bottom=260, left=60, right=60, right_lower=dict(w=160, from_y=960)),
                      caption=dict(_VERT_CAPTION, band=[1420, 1640]),
                      cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1240], feed_crop=None),
                      cover_aspect="3:4"),
            horizontal=dict(w=1920, h=1080, aspect="16:9", feed_crop="4:3",
                            safe=dict(top=60, bottom=60, left=280, right=280),
                            caption=dict(_HORZ_CAPTION, band=[880, 1030], max_chars_zh=18),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[300, 80, 1620, 1000], feed_crop="4:3"),
                            cover_aspect="16:9"),
        )),
    "douyin": dict(
        label="抖音 Douyin", default="vertical",
        group="zh", links=dict(clickable=False, avoid=True, note="no clickable links in captions; 导流 is penalised"),
        title_max=55, title_count="chars", desc_max=1000,
        hashtags=dict(style="inline", max=10, note="#话题 / @ inside the caption text; counts toward the 1000 limit"),
        chapters=dict(supported=False, note="auto 章节 on some long videos only; not author-controlled"),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 60], max=900, min=3, note="web 15 min / 4 GB (open-platform spec agrees)"),
        limits=dict(max_bytes=4_000_000_000),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=440, left=60, right=150, right_lower=dict(w=180, from_y=900)),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680],
                                     feed_crop="3:4"),
                          cover_aspect="9:16"),
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=60, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[240, 60, 1680, 1020], feed_crop="4:3"),
                            cover_aspect="16:9"),
        )),
    "tiktok": dict(
        label="TikTok", default="vertical",
        group="global", links=dict(clickable=False, note="links only in the bio (business / 1k+ followers)"),
        title_max=55, title_count="chars", desc_max=4000,
        hashtags=dict(style="inline", max=30, note="in the caption; counts toward 4000 (2200 via API)"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[21, 60], max=3600, min=3, note="uploads up to 60 min (some accounts still 10 min); "
                    "in-app recording 10 min"),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=130, bottom=484, left=60, right=140),
                          caption=dict(_VERT_CAPTION, band=[1200, 1420]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680],
                                     feed_crop="3:4"),
                          cover_aspect="9:16"),
        )),
    "youtube": dict(
        label="YouTube (long-form)", default="horizontal",
        group="global", formats=dict(long="youtube", shorts="youtube-shorts"), links=dict(clickable=True),
        title_max=100, title_count="chars", title_required=True, desc_max=5000,
        hashtags=dict(style="description", max=15, note="first 3 show above the title; >60 = all ignored"),
        chapters=dict(supported=True, min_count=3, min_len=10, first_zero=True),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[420, 1200], max=43200, min=1),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=54, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[880, 1020]),
                            cover=dict(w=1280, h=720, aspect="16:9", title_safe=[40, 40, 1100, 620], feed_crop=None,
                                       max_bytes=2_000_000),
                            cover_aspect="16:9"),
        )),
    "youtube-shorts": dict(
        label="YouTube Shorts", default="vertical",
        group="global", channel="youtube", format="shorts", links=dict(clickable=False, note="links in Shorts descriptions / comments are not clickable since 2023-08; use the Related video link"),
        title_max=100, title_count="chars", desc_max=5000,
        hashtags=dict(style="description", max=3),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[20, 60], max=180, min=3),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=180, bottom=390, left=60, right=120),
                          caption=dict(_VERT_CAPTION, band=[1260, 1480]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 960, 1530], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "bilibili": dict(
        label="B站 Bilibili", default="horizontal",
        group="zh", links=dict(clickable=False, avoid=True, note="站外 links in 简介 are not linked; 导流 is limited"),
        title_max=80, title_count="chars", title_required=True, desc_max=2000,
        hashtags=dict(style="tags_line", max=10, tag_max=20, note="separate tag field, <=10 tags, <=20 chars each"),
        category=dict(required=True, field="分区 (tid)", note="pick the 分区 in the uploader (or `tid` via the open "
                      "platform); 自制 / 转载 (creation type) is the creator's own choice - never pre-filled"),
        chapters=dict(supported=True, min_count=2, min_len=5, first_zero=True,
                      note="分段章节 set in the uploader; timestamps in the description also link"),
        loudness=dict(_LOUD), fps=dict(default=30, max=120),
        encode=dict(crf=18, maxrate="24M", bufsize="24M"),
        length=dict(sweet=[180, 900], max=36000, min=10),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=80, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1146, h=717, aspect="16:10", title_safe=[100, 40, 1046, 640], feed_crop=None,
                                       crops=["4:3", "16:9"], max_bytes=5_000_000),
                            cover_aspect="16:10"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=200, bottom=420, left=60, right=150),
                          caption=dict(_VERT_CAPTION, band=[1260, 1480]),
                          cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1240], feed_crop=None),
                          cover_aspect="3:4"),
        )),
    "wechat-channels": dict(
        label="视频号 WeChat Channels", default="vertical",
        group="zh", links=dict(clickable=False, avoid=True, note="only a 公众号 article via the 扩展链接 field"),
        title_max=16, title_count="chars", desc_max=1000,
        hashtags=dict(style="inline", max=10, note="#话题 / @ inside the description; counts toward 1000"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 120], max=28800, min=3, note="phone app 60 min; web 视频号助手 up to 8 h"),
        limits=dict(max_bytes=2_000_000_000, aspect_range=[0.33, 3.0], hdr=False),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=200, bottom=460, left=60, right=60),
                          caption=dict(_VERT_CAPTION, band=[1200, 1420]),
                          cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1320], feed_crop=None,
                                     crops=["6:7"]),
                          cover_aspect="3:4"),
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=80, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[240, 60, 1680, 1020], feed_crop=None),
                            cover_aspect="16:9"),
        )),
    "x": dict(
        label="X (Twitter)", default="horizontal", auto_orientation=True,
        group="global", links=dict(clickable=True, note="every URL counts 23"),
        title_max=0, title_count="chars", desc_max=280, desc_count="x",
        copy_lang="intl",
        hashtags=dict(style="inline", max=2, recommend=[1, 2], note="1-2 tags in the post text; more reads as spam"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 90], max=140, min=0.5),
        limits=dict(max_bytes=512_000_000, max_bitrate="25M", max_w=1920, max_h=1200),
        captions=dict(burn="recommended", reason="X autoplays video muted in the timeline: burn the captions"),
        account="standard",
        tiers=dict(premium=dict(desc_max=25000, length=dict(max=7200), limits=dict(max_bytes=8_000_000_000)),
                   premium_plus=dict(desc_max=25000, length=dict(max=14400), limits=dict(max_bytes=16_000_000_000))),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 990]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 80, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
            square=dict(w=1080, h=1080, aspect="1:1",
                        safe=dict(top=54, bottom=90, left=60, right=60),
                        caption=dict(size=[46, 64], max_chars_zh=16, max_chars_en=36, max_lines=2, stroke=0.09,
                                     band=[800, 980]),
                        cover=dict(w=1080, h=1080, aspect="1:1", title_safe=[60, 60, 1020, 1020], feed_crop=None),
                        cover_aspect="1:1"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=380, left=60, right=120),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop=None,
                                     crops=["4:5"]),
                          cover_aspect="9:16"),
        )),
    "instagram": dict(
        label="Instagram", default="reels",
        group="global", links=dict(clickable=False, note="caption links are not clickable: link in bio / sticker"),
        title_max=0, title_count="chars", desc_max=2200,
        copy_lang="intl",
        hashtags=dict(style="inline", max=5, recommend=[3, 5], hard=True,
                      note="max 5 hashtags per post/reel (since Dec 2025, caption + comments)"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 90], max=1200, min=3, reach_max=180,
                    note="Reels over 3 min are not recommended to non-followers"),
        limits=dict(max_bytes=4_000_000_000),
        orient_aliases={"vertical": "reels", "full": "reels", "9:16": "reels", "reel": "reels", "4:5": "feed",
                        "portrait": "feed", "post": "feed"},
        orientations=dict(
            reels=dict(w=1080, h=1920, aspect="9:16", feed_crop="4:5",
                       safe=dict(top=285, bottom=450, left=60, right=130, right_lower=dict(w=170, from_y=1000)),
                       caption=dict(_VERT_CAPTION, band=[1200, 1440]),
                       cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 300, 1020, 1620], feed_crop=None,
                                  crops=["4:5", "3:4", "1:1"]),
                       cover_aspect="9:16"),
            feed=dict(w=1080, h=1350, aspect="4:5",
                      safe=dict(top=60, bottom=120, left=60, right=60),
                      caption=dict(_VERT_CAPTION, band=[1010, 1200]),
                      cover=dict(w=1080, h=1350, aspect="4:5", title_safe=[60, 60, 1020, 1290], feed_crop=None,
                                 crops=["3:4", "1:1"]),
                      cover_aspect="4:5"),
        )),

    # ------------------------------------------------------------------ added 2026-10 (see PLATFORMS.md)
    "facebook": dict(
        label="Facebook", default="reels", group="global",
        title_max=0, title_count="chars", desc_max=2200,
        copy_lang="intl",
        hashtags=dict(style="inline", max=5, recommend=[3, 5], note="up to ~30 work; 3-5 recommended; low impact"),
        links=dict(clickable=True, note="feed posts: URLs are clickable; Reels captions: not reliably"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 90], max=14400, min=3,
                    note="since 2025-06 most uploads publish as Reels, no Reel length cap; 240 min / 4 GB upload cap; "
                         "the Reels API still says 3-90 s"),
        limits=dict(max_bytes=4_000_000_000),
        orient_aliases={"vertical": "reels", "full": "reels", "9:16": "reels", "reel": "reels", "4:5": "feed",
                        "portrait": "feed", "post": "feed", "16:9": "horizontal"},
        orientations=dict(
            reels=dict(w=1080, h=1920, aspect="9:16",
                       safe=dict(top=269, bottom=672, left=65, right=65),
                       caption=dict(_VERT_CAPTION, band=[1040, 1240]),
                       cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[65, 269, 1015, 1248], feed_crop=None,
                                  crops=["4:5"]),
                       cover_aspect="9:16"),
            feed=dict(w=1080, h=1350, aspect="4:5",
                      safe=dict(top=60, bottom=120, left=60, right=60),
                      caption=dict(_VERT_CAPTION, band=[1010, 1200]),
                      cover=dict(w=1080, h=1350, aspect="4:5", title_safe=[60, 60, 1020, 1290], feed_crop=None),
                      cover_aspect="4:5"),
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 990]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 80, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
        )),
    "linkedin": dict(
        label="LinkedIn", default="horizontal", group="global", auto_orientation=True,
        title_max=0, title_count="chars", desc_max=3000,
        copy_lang="intl",
        hashtags=dict(style="inline", max=3, recommend=[1, 3], note="keyword signal only since hashtag following "
                      "was removed; stuffing hurts"),
        links=dict(clickable=True, note="URLs in the post are clickable; a reach penalty for links is disputed"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[30, 120], max=900, min=3, note="15 min organic (API / ads 30 min)"),
        limits=dict(max_bytes=5_000_000_000, aspect_range=[1 / 2.4, 2.4]),
        captions=dict(burn="recommended", reason="LinkedIn autoplays muted in the feed: burn the captions (or add one "
                      "SRT on upload)"),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 990]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 80, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
            square=dict(w=1080, h=1080, aspect="1:1",
                        safe=dict(top=54, bottom=90, left=60, right=60),
                        caption=dict(size=[46, 64], max_chars_zh=16, max_chars_en=36, max_lines=2, stroke=0.09,
                                     band=[800, 980]),
                        cover=dict(w=1080, h=1080, aspect="1:1", title_safe=[60, 60, 1020, 1020], feed_crop=None),
                        cover_aspect="1:1"),
            feed=dict(w=1080, h=1350, aspect="4:5",
                      safe=dict(top=60, bottom=120, left=60, right=60),
                      caption=dict(_VERT_CAPTION, band=[1010, 1200]),
                      cover=dict(w=1080, h=1350, aspect="4:5", title_safe=[60, 60, 1020, 1290], feed_crop=None),
                      cover_aspect="4:5"),
        )),
    "threads": dict(
        label="Threads", default="vertical", group="global", auto_orientation=True,
        title_max=0, title_count="chars", desc_max=500,
        copy_lang="intl",
        hashtags=dict(style="topic", max=1, hard=True, note="one topic tag per post (shown without #)"),
        links=dict(clickable=True, max=5, note="links are clickable; no preview card on video posts"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 90], max=300, min=1),
        limits=dict(max_bytes=1_000_000_000, max_w=1920),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=380, left=60, right=120),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop=None,
                                     crops=["4:5"]),
                          cover_aspect="9:16"),
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 990]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 80, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
        )),
    "reddit": dict(
        label="Reddit", default="horizontal", group="global", auto_orientation=True,
        title_max=300, title_count="chars", title_required=True, desc_max=40000,
        copy_lang="intl",
        hashtags=dict(style="none", max=0, note="Reddit does not use hashtags; tags are left out"),
        links=dict(clickable=True, note="markdown links in the body are clickable; a video post is not a link post"),
        community=dict(required=True, field="subreddit", note="the creator types the subreddit; read its rules "
                       "(self-promotion share, flair, account age / karma, NSFW) before posting"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=30),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 120], max=900, min=1),
        limits=dict(max_bytes=1_000_000_000),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 990]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 80, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
            square=dict(w=1080, h=1080, aspect="1:1",
                        safe=dict(top=54, bottom=90, left=60, right=60),
                        caption=dict(size=[46, 64], max_chars_zh=16, max_chars_en=36, max_lines=2, stroke=0.09,
                                     band=[800, 980]),
                        cover=dict(w=1080, h=1080, aspect="1:1", title_safe=[60, 60, 1020, 1020], feed_crop=None),
                        cover_aspect="1:1"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=300, left=60, right=60),
                          caption=dict(_VERT_CAPTION, band=[1300, 1520]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1620], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "pinterest": dict(
        label="Pinterest", default="vertical", group="global",
        title_max=100, title_count="chars", desc_max=500,
        copy_lang="intl",
        hashtags=dict(style="none", max=0, note="hashtags were replaced by topics (up to 10, picked on the page) "
                      "and keywords in the title / description"),
        links=dict(clickable=False, field="link", note="a separate destination-link field; not in the text"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[6, 60], max=900, min=4, note="sources disagree: 15 min vs 5 min for organic pins"),
        limits=dict(max_bytes=2_000_000_000, aspect_range=[0.5, 1.91]),
        orient_aliases={"2:3": "feed", "pin": "feed"},
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=270, bottom=790, left=65, right=195),
                          caption=dict(_VERT_CAPTION, band=[920, 1120]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[65, 270, 885, 1130], feed_crop="2:3"),
                          cover_aspect="9:16"),
            feed=dict(w=1000, h=1500, aspect="2:3",
                      safe=dict(top=60, bottom=160, left=60, right=60),
                      caption=dict(_VERT_CAPTION, band=[1120, 1330]),
                      cover=dict(w=1000, h=1500, aspect="2:3", title_safe=[60, 60, 940, 1340], feed_crop=None),
                      cover_aspect="2:3"),
            square=dict(w=1080, h=1080, aspect="1:1",
                        safe=dict(top=60, bottom=120, left=60, right=60),
                        caption=dict(size=[46, 64], max_chars_zh=16, max_chars_en=36, max_lines=2, stroke=0.09,
                                     band=[780, 950]),
                        cover=dict(w=1080, h=1080, aspect="1:1", title_safe=[60, 60, 1020, 1020], feed_crop=None),
                        cover_aspect="1:1"),
        )),
    "snapchat": dict(
        label="Snapchat Spotlight", default="vertical", group="global",
        title_max=0, title_count="chars", desc_max=160,
        copy_lang="intl",
        hashtags=dict(style="inline", max=3, recommend=[1, 3], note="#Topics; irrelevant topics raise the rejection "
                      "risk; the 160-char description caps them"),
        links=dict(clickable=False, note="no links on Spotlight"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[10, 60], max=60, min=5),
        limits=dict(max_bytes=1_000_000_000, watermark=False),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=200, bottom=400, left=60, right=140),
                          caption=dict(_VERT_CAPTION, band=[1220, 1440]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "kuaishou": dict(
        label="快手 Kuaishou", default="vertical", group="zh",
        title_max=0, title_count="chars", desc_max=500,
        hashtags=dict(style="inline", max=4, recommend=[1, 3], note="#话题 (one #) picked in the 话题 menu; 1-3 niche topics"),
        links=dict(clickable=False, avoid=True, note="no clickable links; 站外导流 is penalised"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 90], max=900, min=3, note="web 15 min / 4 GB (help centre); longer needs a permission"),
        limits=dict(max_bytes=4_000_000_000),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=400, left=60, right=150, right_lower=dict(w=180, from_y=900)),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop="3:4"),
                          cover_aspect="9:16"),
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=60, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[240, 60, 1680, 1020], feed_crop="4:3"),
                            cover_aspect="16:9"),
        )),
    "weibo": dict(
        label="微博 Weibo", default="horizontal", group="zh", auto_orientation=True,
        title_max=30, title_min=6, title_count="chars", desc_max=2000,
        hashtags=dict(style="inline", max=3, format="#{tag}#", note="#话题# with two hashes, 4-32 chars, no spaces"),
        links=dict(clickable=True, note="URLs become 网页链接 short links; non-whitelisted personal domains often get "
                   "a risk prompt or are blocked"),
        category=dict(required=False, field="投稿: 频道分类 + 标签 + 原创/转载", note="only when 投稿 to a channel"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[30, 300], max=900, min=3, note="15 min ordinary accounts (members / V longer) [3P]; PC 15 GB"),
        limits=dict(max_bytes=15_000_000_000),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=80, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 60, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=180, bottom=400, left=60, right=120),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "zhihu": dict(
        label="知乎 Zhihu", default="horizontal", group="zh",
        title_max=30, title_count="chars", title_required=True, desc_max=300,
        hashtags=dict(style="topics", max=5, note="no inline hashtags: topics go in the separate 话题 field"),
        links=dict(clickable=False, avoid=True, note="video 简介 links not clickable (unverified); 站外导流 loses 优质 status"),
        category=dict(required=True, field="领域 + 话题 + 原创/转载", note="picked on the upload page by the creator"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[60, 600], max=3600, min=1, note="PC 1 h / 2 GB; < 1 min earns no 创作分 and cannot be "
                                                          "投稿到问题"),
        limits=dict(max_bytes=2_000_000_000),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=80, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[160, 60, 1760, 1000], feed_crop=None),
                            cover_aspect="16:9"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=360, left=60, right=120),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "dailymotion": dict(
        label="Dailymotion", default="horizontal", group="intl",
        title_max=255, title_count="chars", title_required=True, desc_max=3000,
        copy_lang="intl",
        hashtags=dict(style="inline", max=15, note="#hashtags in the description: <= 15, 2-25 chars, letters / digits / _"),
        links=dict(clickable=True, note="URLs in the description are links"),
        category=dict(required=True, field="category + language + made for kids", note="picked in Studio by the creator"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[60, 900], max=7200, min=1, note="standard accounts 2 h / 4 GB, 15 uploads per 24 h"),
        limits=dict(max_bytes=4_000_000_000),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=80, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1280, h=720, aspect="16:9", title_safe=[40, 40, 1100, 640], feed_crop=None,
                                       max_bytes=5_000_000),
                            cover_aspect="16:9"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=300, left=60, right=60),
                          caption=dict(_VERT_CAPTION, band=[1300, 1520]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1620], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "kwai": dict(
        label="Kwai", default="vertical", group="intl",
        title_max=0, title_count="chars", desc_max=500,
        copy_lang="intl",
        hashtags=dict(style="inline", max=5, note="convention: no published cap"),
        links=dict(clickable=False, note="links in captions are not clickable"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 60], max=300, min=3, note="no public spec page; sources disagree (57 s camera, ~5 min "
                                                         "editor, 10-12 min gallery claims)"),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=440, left=60, right=150),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680], feed_crop=None),
                          cover_aspect="9:16"),
        )),
}

# Display order everywhere a person picks or sees platforms: English / global, then Chinese, then other languages.
GROUPS = {
    "global": ["youtube", "youtube-shorts", "tiktok", "instagram", "x", "facebook", "linkedin", "threads", "reddit",
               "pinterest", "snapchat"],
    "zh": ["xiaohongshu", "douyin", "wechat-channels", "bilibili", "kuaishou", "weibo", "zhihu"],
    "intl": ["dailymotion", "kwai"],
}
ORDER = [n for g in GROUPS.values() for n in g]
GROUP_LABELS = {"global": dict(en="English / global", zh="英文 / 全球", fr="Anglais / international"),
                "zh": dict(en="Chinese", zh="中文平台", fr="Chinois"),
                "intl": dict(en="Other languages", zh="其他语言", fr="Autres langues")}

# One account / channel, several formats: YouTube long-form and Shorts post through the same channel.
FORMATS = {"youtube": {"long": "youtube", "shorts": "youtube-shorts"}}
CHANNEL_OF = {"youtube-shorts": "youtube"}
SHORTS_MAX_S = 180

# Platforms whose post copy defaults to English when the content is English (vstudio.publish.localize_post).
INTL_PLATFORMS = set(GROUPS["global"]) | set(GROUPS["intl"])

# How a post reaches each platform. Default everywhere: ASSISTED publishing - the desk opens the platform's own
# upload page in its built-in browser (one persistent login per account), sets the file and types the copy; the
# creator presses publish. ``api`` = the official posting API and what it takes; an API uploader is only ever used
# behind explicit config (``uploader:`` in the series / project) AND a confirm code, and never posts on its own.
# Details + sources: references/PUBLISHING.md.
PUBLISHING = {
    "youtube": dict(upload_url="https://www.youtube.com/upload", api="YouTube Data API v3 videos.insert (OAuth; "
                    "unaudited projects are locked to private)"),
    "youtube-shorts": dict(upload_url="https://www.youtube.com/upload", api="same as youtube (vertical, <= 3 min)"),
    "tiktok": dict(upload_url="https://www.tiktok.com/tiktokstudio/upload", api="Content Posting API (unaudited: "
                   "SELF_ONLY, private account)"),
    "instagram": dict(upload_url="https://www.instagram.com/", api="Content Publishing API (Professional account, "
                      "reviewed Meta app, public video URL)"),
    "x": dict(upload_url="https://x.com/compose/post", api="X API v2 media upload + POST /2/tweets (paid credits, "
              "OAuth 2.0 user token)"),
    "facebook": dict(upload_url="https://www.facebook.com/", api="Graph API Reels publishing - Pages only "
                     "(pages_manage_posts), 30 API Reels / 24 h; no API for personal profiles"),
    "linkedin": dict(upload_url="https://www.linkedin.com/feed/", api="Posts + Videos API: member posts via "
                     "Share on LinkedIn (w_member_social); Pages need Community Management API approval"),
    "threads": dict(upload_url="https://www.threads.com/", api="Threads API threads_content_publish (app review for "
                    "other accounts; video at a public URL; 250 posts / 24 h)"),
    "reddit": dict(upload_url="https://www.reddit.com/submit", api="Data API (OAuth, app pre-approval); video upload is "
                   "the undocumented media-asset flow - not used"),
    "pinterest": dict(upload_url="https://www.pinterest.com/pin-creation-tool/", api="API v5 media + pins (Standard "
                      "access tier; trial pins are private)"),
    "snapchat": dict(upload_url="https://profile.snapchat.com/", api="Public Profile API (allowlisted partners only)"),
    "xiaohongshu": dict(upload_url="https://creator.xiaohongshu.com/publish/publish", api=None),
    "douyin": dict(upload_url="https://creator.douyin.com/creator-micro/content/upload", api="open platform: "
                   "server-side posting only for government / media tools; SDK share needs an enterprise app"),
    "wechat-channels": dict(upload_url="https://channels.weixin.qq.com/platform/post/create", api=None),
    "bilibili": dict(upload_url="https://member.bilibili.com/platform/upload/video/frame", api="开放平台 视频稿件投递 "
                     "(developer application + review)"),
    "kuaishou": dict(upload_url="https://cp.kuaishou.com/article/publish/video", api="快手开放平台 photo/publish "
                     "(approved app, user_video_publish scope)"),
    "weibo": dict(upload_url="https://weibo.com/upload/channel", api="video upload API only for government / media / "
                  "institution accounts"),
    "zhihu": dict(upload_url="https://www.zhihu.com/zvideo/upload-video", api=None),
    "dailymotion": dict(upload_url="https://www.dailymotion.com/partner/", api="Data API v2 upload sessions (OAuth "
                        "video.manage, API key from Studio)"),
    "kwai": dict(upload_url=None, api=None, note="no desktop web upload: post from the phone app"),
}


@dataclass
class Profile:
    name: str
    orientation: str
    label: str
    w: int
    h: int
    aspect: str
    safe: dict
    caption: dict
    cover: dict
    cover_aspect: str
    title_max: float
    title_count: str
    desc_max: int
    hashtags: dict
    chapters: dict
    loudness: dict
    fps: dict
    encode: dict
    length: dict
    feed_crop: str = None
    desc_count: str = "chars"
    extra: dict = field(default_factory=dict)

    @property
    def key(self):
        return f"{self.name}:{self.orientation}"

    @property
    def size(self):
        return self.w, self.h

    def to_dict(self):
        return asdict(self)


_FIELDS = set(Profile.__dataclass_fields__) - {"name", "orientation", "extra"}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def canonical(name):
    n = str(name).strip().lower()
    return ALIASES.get(n, n)


def _persona_platform(name):
    try:
        from .config import persona
        p = (persona().get("platforms") or {}).get(name) or {}
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def _legacy_safe_zone(sz, w, h):
    """persona safe_zone {top, bottom, right_lower_keepout} (y coordinates, 1080x1920) -> safe dict."""
    out = {}
    if "top" in sz:
        out["top"] = int(sz["top"])
    if "bottom" in sz:
        b = int(sz["bottom"])
        out["bottom"] = h - b if b > h / 2 else b          # coordinate (1660) or margin (260)
    for k in ("left", "right"):
        if k in sz:
            out[k] = int(sz[k])
    if sz.get("right_lower_keepout"):
        out["right_lower"] = dict(w=int(sz["right_lower_keepout"]), from_y=h // 2)
    return out


def profile(name, orientation=None, overrides=None, use_persona=True) -> Profile:
    """Profile for ``name`` ("xiaohongshu", "douyin", "tiktok", "youtube", "youtube-shorts", "bilibili"
    or an alias) and ``orientation`` ("vertical", "full", "horizontal"; default per platform).
    Merge order: built-in common <- built-in orientation <- persona platforms.<name> <- persona
    platforms.<name>.orientations.<o> <- ``overrides``."""
    if ":" in str(name) and orientation is None:
        name, orientation = str(name).split(":", 1)
    name = canonical(name)
    if name not in PLATFORMS:
        raise KeyError(f"unknown platform {name!r}; one of {sorted(PLATFORMS)}")
    base = PLATFORMS[name]
    o = _resolve_orientation(base, orientation)
    if o not in base["orientations"]:
        if o == "full" and "vertical" in base["orientations"] and base["orientations"]["vertical"]["h"] == 1920:
            o = "vertical"
        elif o == "vertical" and "full" in base["orientations"]:
            o = "full"
        else:
            raise KeyError(f"{name} has no {o!r} orientation; one of {sorted(base['orientations'])}")
    d = {k: v for k, v in base.items() if k not in ("orientations", "default")}
    d = _merge(d, base["orientations"][o])
    if use_persona:
        pp = dict(_persona_platform(name))
        per_o = (pp.pop("orientations", None) or {}).get(o) or {}
        legacy = pp.pop("safe_zone", None)
        if legacy and d["h"] == 1920:
            d["safe"] = _merge(d["safe"], _legacy_safe_zone(legacy, d["w"], d["h"]))
        if "cover_aspect" in pp and pp["cover_aspect"] != d.get("cover_aspect"):
            pp.pop("cover_aspect")      # a single legacy aspect can't describe every orientation; keep built-in
        d = _merge(d, pp)
        d = _merge(d, per_o)
    d = _merge(d, overrides or {})
    tier = (d.get("tiers") or {}).get(str(d.get("account") or "").lower().replace("-", "_"))
    if tier:
        d = _merge(d, tier)
    extra = {k: d.pop(k) for k in list(d) if k not in _FIELDS}
    return Profile(name=name, orientation=o, extra=extra, **d)


def _resolve_orientation(base, orientation):
    if not orientation:
        return base["default"]
    o = str(orientation).strip().lower()
    if o in base["orientations"]:
        return o
    pa = base.get("orient_aliases") or {}
    if o in pa:
        return pa[o]
    o = ORIENT_ALIASES.get(o, o)
    return pa.get(o, o)


def _ratio(a):
    if isinstance(a, (int, float)):
        return float(a)
    w, h = (float(v) for v in str(a).split(":"))
    return w / h


def best_orientation(name, aspect):
    """The orientation of ``name`` whose canvas aspect is closest (log distance) to ``aspect`` (w/h float or
    "9:16") - so a master is re-laid out with the least crop and no letterbox where the platform allows it."""
    import math
    base = PLATFORMS[canonical(name)]
    a = _ratio(aspect)
    return min(base["orientations"], key=lambda o: abs(math.log((base["orientations"][o]["w"] /
                                                                base["orientations"][o]["h"]) / a)))


def list_profiles():
    """["xiaohongshu:vertical", ...] - every platform:orientation pair."""
    return [f"{n}:{o}" for n, p in PLATFORMS.items() for o in p["orientations"]]


def parse_targets(spec, master_aspect=None, overrides=None):
    """"xiaohongshu:vertical,douyin,youtube" -> [Profile, ...]. With ``master_aspect`` (w/h), a bare name of a
    platform that accepts several shapes equally (``auto_orientation``: X) gets the orientation closest to the
    master, e.g. "x" + a 9:16 master -> x:vertical (no letterbox / heavy crop)."""
    out = []
    for item in (spec if isinstance(spec, (list, tuple)) else str(spec).split(",")):
        item = item.strip() if isinstance(item, str) else item
        if isinstance(item, Profile):
            out.append(item)
        elif item:
            n, _, o = item.partition(":")
            if not o and master_aspect and PLATFORMS.get(canonical(n), {}).get("auto_orientation"):
                o = best_orientation(n, master_aspect)
            out.append(profile(n, o or None, overrides=overrides))
    return out


# ----------------------------------------------------------------------------------- order / formats / links
def group_of(name):
    n = canonical(str(name).split(":")[0])
    return next((g for g, names in GROUPS.items() if n in names), None)


def channel_of(name):
    """The account / channel a platform posts through: youtube-shorts -> youtube; else itself."""
    n = canonical(str(name).split(":")[0])
    return CHANNEL_OF.get(n, n)


def ordered(names, connected=()):
    """Sort platform names (or "name:orientation" keys) for display: group order (English / global, Chinese,
    other languages); inside a group the ones with a connected account first (a Shorts target counts through its
    YouTube channel), then ``ORDER``. Unknown names last, in input order."""
    conn = {channel_of(c) for c in connected or ()}
    gidx = {g: i for i, g in enumerate(GROUPS)}

    def key(item):
        i, n = item
        base = canonical(str(n).split(":")[0])
        g = group_of(base)
        return (gidx.get(g, len(GROUPS)), 0 if channel_of(base) in conn else 1,
                ORDER.index(base) if base in ORDER else len(ORDER), i)
    return [n for _, n in sorted(enumerate(names), key=key)]


def order_key(name):
    """Position of a platform in the display order for any spelling the engine uses: "douyin", "douyin:vertical",
    a package key "xiaohongshu-full" / "youtube-shorts-vertical", an alias ("视频号"). Unknown -> after all."""
    s = str(name or "").strip().lower()
    base = canonical(s.split(":")[0])
    if base not in ORDER:
        hits = [n for n in ORDER if s.startswith(n + "-")]
        base = canonical(max(hits, key=len)) if hits else canonical(s.rpartition("-")[0] or s)
    return ORDER.index(base) if base in ORDER else len(ORDER)


def youtube_format(aspect, seconds=None):
    """"shorts" for a vertical / square video of <= 3 min, else "long" (YouTube decides the same way)."""
    a = _ratio(aspect)
    return "shorts" if a <= 1.0 + 1e-6 and (seconds is None or seconds <= SHORTS_MAX_S) else "long"


def check_format(p: "Profile", aspect, seconds=None):
    """Warnings when a master does not fit the format: YouTube long-form from a vertical-only master (re-laid out on
    16:9 with a blurred fill - render a real 16:9 cut, or post it as Shorts), Shorts from a horizontal master or over
    3 min (YouTube would publish it as a long-form video)."""
    a, w = _ratio(aspect), []
    if p.name == "youtube" and a < 1.0:
        w.append("only a vertical version: YouTube long-form is 16:9 - this export re-lays it out on 16:9 (blurred "
                 "fill); render a 16:9 cut, or post it as Shorts")
    if p.name == "youtube-shorts":
        if a > 1.0 + 1e-6:
            w.append("Shorts must be vertical or square: a horizontal master is cropped to 9:16 - check the framing, "
                     "or post it as long-form")
        if seconds and seconds > SHORTS_MAX_S:
            w.append(f"{seconds:.0f}s is over the {SHORTS_MAX_S}s Shorts limit: YouTube publishes it as long-form")
    return w


def link_policy(p: "Profile"):
    """{"clickable": bool, "field": "link"|None, "avoid": bool, "note": str} - how a URL in the post text behaves."""
    lp = dict(clickable=True, field=None, avoid=False, note="")
    lp.update(p.extra.get("links") or {})
    return lp


def publishing(name):
    """{"mode": "assisted", "upload_url", "api", "auto_post": False}: assisted fill is the default; ``api`` names the
    official API (opt-in per platform, behind a confirm code); nothing ever auto-posts."""
    n = canonical(str(name).split(":")[0])
    d = dict(PUBLISHING.get(n) or {})
    return dict(mode="assisted" if d.get("upload_url") else "manual", upload_url=d.get("upload_url"),
                api=d.get("api"), auto_post=False, note=d.get("note"))


# ----------------------------------------------------------------------------------- geometry
def safe_box(p: Profile):
    """(x0, y0, x1, y1): the area free of the platform's UI margins (top bar, bottom description,
    side buttons). The lower-right button keep-out is returned separately by ``keepouts``."""
    s = p.safe
    return (int(s.get("left", 0)), int(s.get("top", 0)), int(p.w - s.get("right", 0)), int(p.h - s.get("bottom", 0)))


def keepouts(p: Profile):
    """Extra keep-out rects [(x0, y0, x1, y1)] (e.g. the like/comment column on the lower right)."""
    rl = p.safe.get("right_lower")
    return [(p.w - int(rl["w"]), int(rl.get("from_y", p.h // 2)), p.w, p.h)] if rl else []


def caption_box(p: Profile):
    """(x0, y0, x1, y1) for burned captions: the caption band, inside the safe box, symmetric around
    the canvas centre and clear of any lower-right button column."""
    x0, y0, x1, y1 = safe_box(p)
    b0, b1 = p.caption["band"]
    b0, b1 = max(b0, y0), min(b1, y1)
    for kx0, ky0, kx1, ky1 in keepouts(p):
        if ky0 < b1 and ky1 > b0:
            x1 = min(x1, kx0)
    m = max(x0, p.w - x1)                    # keep it centred: same margin both sides
    return (int(m), int(b0), int(p.w - m), int(b1))


def cover_size(p: Profile):
    return int(p.cover["w"]), int(p.cover["h"])


def cover_crops(p: Profile):
    """Every crop (aspect strings) a surface shows of the cover: the feed tile (``feed_crop``) plus
    ``cover.crops`` (e.g. Instagram Reels: 4:5 feed, 3:4 profile grid, 1:1 legacy grid / share)."""
    out = []
    for a in [p.cover.get("feed_crop")] + list(p.cover.get("crops") or []):
        if a and a not in out and abs(_ratio(a) - p.cover["w"] / p.cover["h"]) > 1e-3:
            out.append(a)
    return out


def crop_box(W, H, aspect):
    """(x0, y0, x1, y1) of the centre crop of aspect ``aspect`` ("4:5") inside a W x H frame."""
    r = _ratio(aspect)
    if W / H > r:
        cw = H * r
        return (int(round((W - cw) / 2)), 0, int(round((W + cw) / 2)), H)
    ch = W / r
    return (0, int(round((H - ch) / 2)), W, int(round((H + ch) / 2)))


def cover_title_safe(p: Profile):
    """Title-safe rect on the cover, intersected with every centre crop a surface shows (``cover_crops``):
    what is inside survives the feed tile, the profile grid and share cards alike."""
    x0, y0, x1, y1 = p.cover.get("title_safe") or (0, 0, *cover_size(p))
    W, H = cover_size(p)
    for a in cover_crops(p):
        c0, d0, c1, d1 = crop_box(W, H, a)
        x0, y0, x1, y1 = max(x0, c0), max(y0, d0), min(x1, c1), min(y1, d1)
    return (int(x0), int(y0), int(x1), int(y1))


def feed_crop_box(p: Profile):
    """(x0, y0, x1, y1) of the part of the VIDEO frame the feed shows (e.g. 小红书 horizontal -> centre
    4:3), or the full canvas."""
    if not p.feed_crop:
        return (0, 0, p.w, p.h)
    aw, ah = (float(v) for v in p.feed_crop.split(":"))
    if p.w / p.h > aw / ah:
        cw = p.h * aw / ah
        return (int((p.w - cw) / 2), 0, int((p.w + cw) / 2), p.h)
    ch = p.w * ah / aw
    return (0, int((p.h - ch) / 2), p.w, int((p.h + ch) / 2))


# ----------------------------------------------------------------------------------- text
def _has_cjk(text):
    return any(ord(c) >= 0x2E80 for c in text)


def title_len(p: Profile, title: str) -> float:
    if p.title_count == "xhs":
        from .config import xhs_len
        return xhs_len(title)
    return float(len(title))


# twitter-text v3 config (github.com/twitter/twitter-text config/v3.json): weight 100 (= 1 char) for these code
# point ranges, 200 (= 2) for everything else (CJK, most symbols); URLs count 23; an emoji sequence counts 2.
_X_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_URL_RE = None
_EMOJI_RE = None


def _x_res():
    global _URL_RE, _EMOJI_RE
    if _URL_RE is None:
        import re
        _URL_RE = re.compile(r"(?:https?://|www\.)[^\s]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ai|co|dev|app|me|"
                             r"tv|ly|gg|cn|xyz)(?:/[^\s]*)?", re.I)
        _EMOJI_RE = re.compile("(?:[\U0001F1E6-\U0001F1FF]{2}|[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF]"
                               "[\uFE0F\U0001F3FB-\U0001F3FF]*(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF][\uFE0F"
                               "\U0001F3FB-\U0001F3FF]*)*)\uFE0F?")
    return _URL_RE, _EMOJI_RE


def x_weighted_len(text: str) -> int:
    """X post length as the composer counts it (twitter-text v3 weighting): Latin / Cyrillic / Greek / most
    punctuation = 1, CJK and other characters = 2, an emoji sequence = 2, any URL = 23. Standard accounts: <= 280."""
    import unicodedata
    url_re, emoji_re = _x_res()
    t = unicodedata.normalize("NFC", text or "")
    n = 0
    t, k = url_re.subn(" ", t)
    n += 23 * k - k                          # each URL -> one placeholder char counted below as 1
    t, k = emoji_re.subn("\x00", t)
    n += 2 * k - k
    for ch in t:
        c = ord(ch)
        n += 1 if any(a <= c <= b for a, b in _X_LIGHT) else 2
    return n


def text_len(p: Profile, text: str) -> int:
    """Post-text length by the profile's counting rule (``desc_count``: "x" weighted, else characters)."""
    return x_weighted_len(text) if p.desc_count == "x" else len(text or "")


def hashtags_in(text: str):
    """Distinct #hashtags in a post text (case-insensitive), in order."""
    import re
    out = []
    for m in re.finditer(r"(?<![\w&/#])#([^\s#.,!?;:，。！？；：、()（）\[\]{}\"'<>]+)", text or ""):
        t = m.group(1).lower()
        if t not in out:
            out.append(t)
    return out


def check_text(p: Profile, title=None, body=None, tags=None):
    """Warnings for title / description / tag limits of this profile. X counts the post text weighted
    (CJK = 2); hashtags are counted across ``tags`` and the #tags already in ``body`` (Instagram: hard max 5).
    Also: a missing title where one is required (Reddit, B站, 知乎, Dailymotion), a too-short 微博 title, a URL
    in the text where links are not clickable or belong in a link field (Pinterest), hashtags where none are used."""
    w = []
    if not (title or "").strip() and p.extra.get("title_required"):
        w.append(f"{p.name} needs a title")
    if title and p.title_max:
        n = title_len(p, title)
        if n > p.title_max:
            w.append(f"title {n:g}/{p.title_max:g} ({p.name})")
        tmin = p.extra.get("title_min")
        if tmin and n < tmin:
            w.append(f"title {n:g} chars: {p.name} wants at least {tmin}")
    if body:
        lp = link_policy(p)
        url_re, _ = _x_res()
        if url_re.search(body):
            if lp.get("field"):
                w.append(f"{p.name}: put the link in the {lp['field']} field, not in the text")
            elif not lp.get("clickable"):
                w.append(f"{p.name}: links in the text are not clickable" + (" and may cut reach" if lp.get("avoid") else "")
                         + " - use the profile / bio link")
    if body and p.desc_max:
        n = text_len(p, body)
        if n > p.desc_max:
            unit = "weighted chars (CJK/emoji = 2, URL = 23)" if p.desc_count == "x" else "chars"
            w.append(f"description {n}/{p.desc_max} {unit} ({p.name})")
    allt = list(dict.fromkeys([str(t).lstrip("#").lower() for t in (tags or []) if str(t).strip("# ")]
                              + hashtags_in(body)))
    if allt:
        mx = p.hashtags.get("max")
        if mx == 0:
            w.append(f"{p.name} does not use hashtags ({len(allt)} given)")
        elif mx and len(allt) > mx:
            kind = "hard limit" if p.hashtags.get("hard") else "guidance"
            w.append(f"{len(allt)} hashtags > {mx} ({p.name}, {kind})")
        tm = p.hashtags.get("tag_max")
        if tm:
            w += [f"tag '{t}' > {tm} chars" for t in (tags or []) if len(t) > tm]
    return w


def check_length(p: Profile, seconds: float):
    """Warnings when a duration is over the hard max (for this account tier) or outside the sweet spot.
    ``length.reach_max`` (Instagram 180 s) warns that longer posts are not recommended to non-followers."""
    L, w = p.length, []
    if L.get("reach_max") and seconds > L["reach_max"] and not (L.get("max") and seconds > L["max"]):
        w.append(f"duration {seconds:.1f}s over {L['reach_max']}s: {p.name} does not recommend it to non-followers")
    if L.get("max") and seconds > L["max"]:
        acct = p.extra.get("account")
        w.append(f"duration {seconds:.1f}s over the {p.name} max {L['max']}s" + (f" ({acct} account)" if acct else ""))
    elif L.get("min") and seconds < L["min"]:
        w.append(f"duration {seconds:.1f}s under the {p.name} minimum {L['min']}s")
    lo, hi = L.get("sweet") or (0, 1e9)
    if not any("over the" in x or "under the" in x for x in w) and not lo <= seconds <= hi:
        w.append(f"duration {seconds:.1f}s outside the {p.name} sweet spot {lo}-{hi}s (guidance)")
    return w


def fit_text_size(p: Profile, text: str, role="cjk-bold", fit_height=True):
    """Largest caption font size in the profile's range at which ``text`` wraps into at most
    ``max_lines`` lines that fit ``caption_box`` width, the per-line char limit (zh or en by
    content) and (fit_height, default) the caption band HEIGHT as ``export.caption_overlay`` stacks the
    rows. Lines are wrapped by whichever of pixel width / char limit binds first, so a long CJK line
    is split instead of failing the char check.
    Returns dict(size, lines, fits, height). Falls back to the min size (fits=False) when it can't fit."""
    from . import draw
    from .subs import text_width as cjk_w, balanced_wrap, caption_block_height
    x0, y0, x1, y1 = caption_box(p)
    cap = p.caption
    lo, hi = (int(v) for v in cap["size"])
    max_lines = int(cap.get("max_lines", 2))
    cjk = _has_cjk(text)
    max_chars = cap["max_chars_zh"] if cjk else cap["max_chars_en"]
    stroke_frac = float(cap.get("stroke", 0.08))
    chars = (lambda s: cjk_w(draw.plain(s))) if cjk else (lambda s: len(draw.plain(s)))  # noqa: E731

    def attempt(size, cap_lines=None):
        f = draw.load_font(role, size)
        avail = (x1 - x0) - 2 * int(size * stroke_frac) - 8
        meas = lambda s: max(draw.text_width(s, f) / max(1.0, avail), chars(s) / max(1, max_chars))  # noqa: E731
        lines = balanced_wrap(text.strip(), 1.0, measure=meas, max_lines=cap_lines)
        if cap_lines and len(lines) > cap_lines:
            lines = lines[:cap_lines]
        width_ok = all(draw.text_width(ln, f) <= avail for ln in lines)
        chars_ok = all(chars(ln) <= max_chars for ln in lines)
        h = caption_block_height(len(lines), f, max(2, int(size * stroke_frac)))
        ok = len(lines) <= max_lines and width_ok and chars_ok and (not fit_height or h <= y1 - y0)
        return dict(size=size, lines=lines, fits=bool(ok), height=h)

    for size in range(hi, lo - 1, -2):
        r = attempt(size)
        if r["fits"]:
            return r
    r = attempt(lo, max_lines)
    r["fits"] = False
    return r


def _wrap(text, f, avail, max_lines=None):
    """Pixel-measured balanced wrap (breaks after punctuation, latin words whole, no orphans); markup kept."""
    from . import draw
    from .subs import balanced_wrap
    lines = balanced_wrap(text.strip(), avail, measure=lambda s: draw.text_width(s, f), max_lines=max_lines)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


def summary(p: Profile) -> str:
    sb, cb = safe_box(p), caption_box(p)
    return (f"{p.key:28s} {p.w}x{p.h} safe={sb} caption={cb} cover={cover_size(p)} "
            f"title<={p.title_max:g} len {p.length.get('sweet')}/{p.length.get('max')}s "
            f"{p.loudness['lufs']} LUFS/{p.loudness['tp']} dBTP")


if __name__ == "__main__":
    for k in [f"{n}:{o}" for n in ORDER for o in PLATFORMS[n]["orientations"]]:
        print(summary(profile(k)))
