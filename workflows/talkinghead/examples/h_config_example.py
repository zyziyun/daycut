# H track config (scripts/make_assets.py, build_filter.py, make_cover.py). SYNTHETIC example.
# Copy to work/config.py in the project dir; relative paths resolve from where you run the scripts (the project dir).
# Run: python3 $VSTUDIO/workflows/talkinghead/scripts/make_assets.py work/config.py
#      python3 $VSTUDIO/workflows/talkinghead/scripts/build_filter.py work/config.py && bash work/run.sh
#      python3 $VSTUDIO/workflows/talkinghead/scripts/make_cover.py work/config.py

# ---- paths ----
SRC  = "my-talk.mp4"            # 1920x1080 剪映 export with burned subtitles
OUT  = "my-talk_final.mp4"
WORK = "work"                   # assets + filter.txt + run.sh land here
COVER_OUT = "my-talk_cover.jpg"
# PLATFORM = "youtube"          # 16:9 profile for bar/badge/callout/panel positions, loudness, cover size
#                               # (default persona platforms.default, horizontal = 小红书 16:9)

# ---- timing / speed ----
MAIN_DUR   = 300.0   # real content end (whisper hallucinates over a silent tail)
HOOK_SPEED = 1.5     # omit to use the talking-head format (vstudio.formats <- persona formats)
BODY_SPEED = 1.25    # omit to use the talking-head format
XFADE      = 0.8     # dissolve between hook clips and into main; it plays over muted pads, so each join adds ~2*XFADE
HOOK_VOL_DB = 4      # extra gain on hook audio
# HOOK_BADGE_TEXT = "高光预告 · 完整版在下面"; NOTES_TAG = "记笔记 ↓"
# GRADE = "eq=brightness=-0.06:contrast=1.08:saturation=1.05:gamma=0.96"   # brightness grade only

# ---- hooks: picked clips in picked order (source seconds). A 2-part clip = 2 entries ----
HOOKS = [
    (120.0, 123.5),   # opener
    (45.2, 51.0),
    (210.4, 216.0),   # cliffhanger
]

# ---- progress-bar chapters (source seconds, SHORT labels 2-4 chars) ----
CHAPTERS = [
    (0,     30.0,  "开场"),
    (30.0,  110.0, "第一部分"),
    (110.0, 200.0, "第二部分"),
    (200.0, MAIN_DUR, "总结"),
]

# ---- callouts: full-sentence punchline bubbles (source anchor sec, on-screen sec, text) ----
CALLOUTS = [
    (35,  4.5, "第一句金句气泡，一整句话"),
    (95,  5.0, "第二句金句气泡，放在没有面板的地方"),
    (150, 5.0, "第三句会被面板取代"),
]
REMOVE = {150}   # callout anchors now covered by a panel (avoid double-stacking)

# ---- 记笔记 panels (source anchor, on-screen sec, title, [bullets]) ----
PANELS = [
    (60,  16.0, "第一部分要点", ["要点一，不超过一行", "要点二", "要点三"]),
    (145, 18.0, "第二部分要点", ["要点一", "要点二", "要点三"]),
]

# ============ COVER (notes-board, 16:9, judged on the 4:3 crop) ============
COVER_FRAME_T = 180               # source second: face-forward, engaged
COVER_KICKER  = "封面顶部一句话标题"
COVER_PANELS = [("第一部分要点", "一行总结"), ("第二部分要点", "一行总结")]       # 2-3 mini panels
COVER_FUN = ("说句大实话", ["黄色便签", "三行文字", "最后一句标红"], "最后一句标红")   # (title, lines, red line)
COVER_HEAD_X = (700, 1300)        # from detect_head.py, so cards avoid the face
# COVER_EQ = "eq=brightness=0.04"  # lift a frame that reads dark under the near-black cards
# COVER_MUTE_BOTTOM = 150          # solid band over burned subtitles (0 = off); COVER_MUTE_TOP likewise
