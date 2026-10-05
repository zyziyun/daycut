"""Per-video config for workflows/longform-to-short (SYNTHETIC example values).

Copy to <project>/work/config.py and fill it in as you go through WORKFLOW.md.
A JSON file with the same keys (config.json) works too. Paths are relative to work/.
Every key is optional unless marked REQUIRED; defaults are shown.
"""

CONFIG = {
    # ── paths ────────────────────────────────────────────────────────────
    "src": "../raw/my-talk.mp4",          # REQUIRED: the long recording
    "out": "../out",                      # deliverables
    "duration": None,                     # auto (ffprobe) when None
    "language": "zh",                     # whisper language; default persona creator.language
    "asr_prompt": None,                   # whisper initial prompt with domain terms, e.g. "LangChain, RAG"
    "source_size": [1280, 720],           # recording frame size (meeting recorders often 720p)

    # ── platforms (vstudio.platform profiles; see WORKFLOW.md "Platforms") ──
    # Horizontal targets drive the 16:9 course (canvas, caption margin / chars, panel safe box, loudness);
    # vertical targets get vertical slices from make_vertical.py. Unset = ["youtube", "<persona
    # platforms.default>:horizontal"] with the pre-platform look. Also: "platform": "xiaohongshu:vertical".
    "targets": ["youtube", "xiaohongshu:vertical", "xiaohongshu:full"],

    # ── analysis ─────────────────────────────────────────────────────────
    "silence": {"noise_db": -35, "min_dur": 1.2, "pad": 0.30, "min_sound": 0.40},
    "geometry": {                         # screen-share detection (light page on dark meeting canvas)
        "step": 10, "bright": 160, "share_frac_x": 0.80,
        "doc_header_px": 45,              # thin docs-app header at ~1500px share width
        "browser_header_px": 115,         # tab strip + address bar + bookmark bar
        "bottom_trim": 14,                # hide the "<host>'s screen" label at the bottom edge
        "min_span": 30,
    },
    "share": [0, 148, 958, 584],          # main share region x0,y0,x1,y1 (zoom clamp, transient scan, fallback crop)
    "speakers": {
        "srt": "rec_subs.srt",
        "label_regex": r"\(([^)]+)\)",    # how the platform marks the speaker in its caption track
        "aliases": {                      # meeting display name -> role label; never commit real names
            "Presenter Name": "Host",
            "Participant Name": "Guest",
        },
    },
    "blocks": {"gap": 2.5, "max_len": 45},

    # ── review decisions (from blocks.txt) ──────────────────────────────
    "keep": {
        "ranges": [[12, 40], [44, 95], [110, 118]],     # inclusive block ids to keep
        "chapters": {                                   # block id -> chapter card title
            "12": "Demo：成品长什么样",
            "20": "概念1：先把输入输出想清楚",
            "44": "概念2：一个循环解决多步问题",
            "110": "什么时候不需要它",
        },
        "merge_gap": 1.5, "pad_in": 0.15, "pad_out": 0.25,
    },

    # ── edit ─────────────────────────────────────────────────────────────
    "speeds": {"lecture": 1.2, "demo": 1.3, "hook": 1.1},   # default: persona longform.speed.*
    "hook": {
        "src": [602.4, 615.0],                          # cold-open clip (source s)
        "lines": ["一句话说清你会得到什么？", "N 个概念 + 一个能跑的例子，一次讲透"],
    },
    "cuts": [                                           # word-level deletions (source s) + why
        [431.2, 434.0, "stumble / restart"],
        [512.8, 518.1, "off-topic aside"],
    ],
    "freezes": [[777.5, 780.9]],                        # accidental tab flash: hold previous frame
    "pitches": {"windows": [[905.1, 909.6]], "semitones": -3},   # anonymise a participant's voice
    "zoom": {
        "windows": [[640, 684], [1020, 1062]],          # code-block zoom cut-ins (source s)
        "box": [736, 336],                              # source window -> ~1.3x push-in
        "code_rgb": [247, 246, 243], "tol": [9, 9, 11], "min_px": 4000,
        "centers": {},                                  # {"640": [480, 360]} manual override
    },
    "transients": {"white_thresh": 0.55, "luma": 200},
    "demo": {                                           # optional live re-record of a web demo
        "enabled": False,
        "url": "http://localhost:3000",
        "prompt": "Summarise the three slowest queries and suggest one fix each.",
        "input_selector": "textarea", "submit_text": "Ask",
        "done_markers": ["summary", "tokens"],
        "viewport": [1856, 1016], "target_seconds": 100,
        "rec": "demo_video/recording.webm",             # set after record_demo.py
        "keep_idx": [0, 1],                             # keep-list segments whose video is replaced
        "rec_in": 0.0, "align_last_to_end": True,
    },
    "cards": {"dur": 1.6, "titles": None},              # titles: optional on-card wording override

    # ── overlays ─────────────────────────────────────────────────────────
    "panel_tag": "记笔记",
    "panel_pos": [1422, 240],
    "panels": [
        {"title": "输入输出", "lines": ["一次调用 = 无状态函数", "上下文靠每次重发"], "src": [700, 718]},
        {"title": "循环", "lines": ["决定 → 执行 → 看结果", "拿到答案才退出"], "src": [1100, 1150]},
    ],
    "style": {"accent": "#2DD4BF", "bg": "#0A0A0C"},    # default: persona longform.accent / ground

    # ── vertical slices (make_vertical.py; see WORKFLOW.md "Vertical slices") ──
    "vertical": {
        "mode": "split",                  # split | screen | speaker | pad-blur (per item; default split)
        "speaker": {                      # the HOST's camera tile; omit for a camera-less share (title band)
            "region": [990, 200, 1250, 350],  # x0,y0,x1,y1 in source px; the crop never leaves it
            "min_hit": 0.3,               # face hit rate below this -> title band instead of the tile
            "zoom": 1.0, "detector": "mediapipe",
        },
        "exclude": [[960, 0, 1280, 720]], # privacy: painted out before any crop (participant tiles, name tags)
        "screen": {"min_scale": 1.6, "max_scale": 2.4, "follow": "content"},   # zoom range; content | center
        "split": {"speaker_frac": 0.40, "band_frac": 0.24},
        "segments": [{"src": [1020, 1062], "mode": "screen"}],   # per source window override
        "series": None,                   # title-band eyebrow (default episodes.series / publish.title)
    },

    # ── render / subtitles ───────────────────────────────────────────────
    "render": {"size": [1920, 1080], "fit": [1856, 1016], "pad_color": "0x141414", "fps": 24, "crf": 19},
    "burn": {"encoder": "auto"},                        # auto | videotoolbox | x264
    "subtitles": {
        "max_line": 22,
        "term_fixes": [[r"[Ll]ama ?index", "LlamaIndex"]],   # per-video ASR fixes (regex, replacement)
        "errata": [{"src": [1500.0, 1530.0], "text": "勘误：这里说的限制在新版本里已经取消"}],
    },

    # ── packaging ────────────────────────────────────────────────────────
    "cover": {
        "shot_src": 1040,                               # screenshot source second (mapped into the cut)
        "wide": {"eyebrow": "系列名 / 受众", "big1": "一句大字", "big2": "重点词",
                 "sub_lines": ["N 个概念 + 一个例子", "一次讲完"], "chips": ["概念A", "概念B", "概念C"]},
        "tall": {"eyebrow": "系列名 / 受众", "hook": ["问题的前半句", "后半句？"],
                 "big1": "一句大字", "big2": "重点词", "sub": "N 个核心概念 · 一次讲透",
                 "chips": ["概念A", "概念B", "概念C"]},
    },
    "episodes": {
        "series": "系列名",
        "max_minutes": 15,
        "targets": None,                                # default: the short-form targets (sweet spot <= 5 min)
        "count": 3,                                     # auto split, or give explicit items:
        "items": [
            {"chapters": [1, 2], "title": "重点词｜入门1/3", "big1": "一句大字", "big2": "重点词",
             "sub": "Demo · 概念1", "shot_src": 700, "vertical": "screen"},   # vertical: per-episode layout
            {"chapters": [3, 3], "title": "循环｜入门2/3", "big1": "本质是", "big2": "一个循环",
             "sub": "概念2", "shot_src": 1100},
            {"chapters": [4, 4], "title": "什么时候不需要｜入门3/3", "big1": "什么时候", "big2": "不需要",
             "sub": "取舍", "shot_src": 1700},
        ],
    },
    "publish": {
        "title": "完整版标题",
        "body": "两三句正文：这期讲什么、适合谁。",
        "tags": ["教程"],
        "errata_line": "勘误：视频里提到的限制在新版本已取消，以官方文档为准。",
        "short_labels": {},                             # chapter title -> ≤14-char 小红书 label
    },
}
