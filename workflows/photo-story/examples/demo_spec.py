"""SYNTHETIC demo spec: a made-up painter and made-up towns, placeholder images from
make_demo_assets.py. Exercises every shot type, most overlays and every transition.

    python3 make_demo_assets.py                                   # -> my_photos/, my_clips/
    python3 ../scripts/photostory/render.py demo_spec.py --stills 1,9,20,33,45
    python3 ../scripts/photostory/tts.py demo_spec.py             # needs OPENAI_API_KEY (optional)

All relative paths below are relative to THIS file's folder.
Coordinates in options (c, hl, tri, loupe) are 0-1 fractions of the picture box / photo.
"""

# ---------------------------------------------------------------- canvas
CANVAS = "3:4"            # "3:4" 1080x1440 | "3:4-hd" 1620x2160 | "9:16" 1080x1920 | "16:9" 1920x1080 | "WxH"
# LAYOUT = dict(header=0.139, sub=0.167, overlay_subs=False)   # fractions of H or px; defaults by orientation
# PALETTE = dict(accent="#DEB870", mark="#E85638")            # see ctx.DEFAULT_PALETTE for all keys
# FPS = 30

# ---------------------------------------------------------------- titles / sections
TITLE_ZH = "灯塔画家｜一个虚构的故事"
TITLE_EN = "The Lighthouse Painter · a synthetic demo"
SECTIONS = ["开场", "路线", "草稿"]
SECTIONS_EN = ["Prologue", "The Road", "Drafts"]
FILM_SECTIONS = {0}        # these sections get the heavier "memory film" look
CHAPTER_CARD = 2.2         # seconds; 0 disables chapter cards
FILM_CAPTION = "{n:02d}  ▸  LIGHTHOUSE · DEMO"

# ---------------------------------------------------------------- media
MEDIA = dict(images="my_photos", videos="my_clips")
FOCUS = {"photo03": ((0.4, 0.45), 1.3)}            # framing (centre, zoom) used inside collage/grid/split/film
VCROP = {"clip1": (0.5, 0.5, 0.9)}                 # video crop: centre x, centre y, width fraction
VEQ = {"clip1"}                                    # clips that get VEQ_FILTER (lift dull phone video)
# VEQ_FILTER = "eq=contrast=1.22:brightness=-0.07:saturation=1.3"

# ---------------------------------------------------------------- route map + timeline bar
ROUTE = dict(
    title="The painter's coast · 画家的海岸",
    note="示意图，非精确比例 · schematic, not to scale",
    cities={   # name: lon, lat, 中文, year label, label side
        "Northport": dict(lon=10.9, lat=44.1, zh="北港", year="1890", side="right"),
        "Millbrook": dict(lon=12.2, lat=43.4, zh="磨坊溪", year="1896", side="left"),
        "Easton": dict(lon=12.9, lat=42.2, zh="东镇", year="1903", side="right"),
    },
    legs={"home": [("Northport", "Northport")], "south": [("Northport", "Millbrook"), ("Millbrook", "Easton")]},
)
TIMELINE = dict(start=1885, end=1910, ticks=[1885, 1890, 1896, 1903, 1910], labels=[1885, 1910])

# ---------------------------------------------------------------- audio
TTS = dict(dir="tts", voice="marin", model="gpt-4o-mini-tts",
           instructions="Voice: a warm, curious narrator showing a friend around a small gallery. "
                        "Pacing: calm and clear, slightly slower than conversation.")
SAY = {"1890": "eighteen ninety"}   # spoken forms used for alignment (and for TTS when TTS['use_say'])
BGM = None                          # e.g. "music/bed.mp3" (your own licensed track)
BGM_LUFS = -30                      # music bed loudness before the mix (default persona audio.music_lufs)
BGM_DUCK = 0                        # extra dB on the bed while the voice speaks (e.g. -6); 0 = static bed
OUT = "out/lighthouse_demo.mp4"

# ---------------------------------------------------------------- script
# (section, [(EN cue, 中文 cue), ...], [(source, weight, motion, options), ...])
#   **word** = highlighted in the accent colour.  One item = one TTS clip.
SCRIPT = [
    (0, [("This is a story told with **twelve** photos.", "这是一个用**十二张**照片讲的故事。"),
         ("None of them are real.", "它们都不是真的。")], [
        ("photo01", 0.9, "in", dict(fx=("develop",))),
        ("film:photo02,photo03,photo04,photo05,photo06", 1.4, "still", dict(tr="leak", count=(12, "PHOTOS", "张照片"))),
    ]),
    (0, [("A short clip, a deck of cards, and some dust.", "一段短视频，一叠卡片，还有些浮尘。")], [
        ("vclip1", 1, "still", dict(off=0.5, tr="flash", label="Clip · 视频")),
        ("deck:photo07,photo08,photo09,photo10", 1, "still", dict(tr="tear", fx=("dust",))),
    ]),
    (1, [("He was born in **Northport** in 1890.", "他 1890 年生于**北港**。")], [
        ("route:home", 1, "still", dict(tr="leak")),
        ("tilt:photo02", 1, "still", dict(tr="blinds", tl=1890, fx=("dust",))),
    ]),
    (1, [("Then he walked south, town by town.", "后来他一路向南，一个镇一个镇地走。")], [
        ("route:south", 1.2, "still", dict(tr="ink")),
        ("photo05", 1, "panR", dict(tr="whip", label="Millbrook · 磨坊溪")),
    ]),
    (1, [("He painted what he saw, again and again.", "他一遍遍画眼前所见。")], [
        ("collage:photo01,photo04,photo06,photo09,photo11", 1, "still", dict(tr="slideup")),
        ("medal:photo04", 1, "still", dict(tr="iris", c=(0.5, 0.4), ring="THE LIGHTHOUSE PAINTER · 1890 – 1910 · ")),
    ]),
    (2, [("Every painting started as a **draft**.", "每一幅画，都从一张**草稿**开始。")], [
        ("split:sketch1|final1", 1.2, "still", dict(tr="push")),
        ("final1", 1, "still", dict(tr="zoom", tri=((0.5, 0.2), (0.82, 0.82), (0.2, 0.82)))),
    ]),
    (2, [("He traced the outlines with tiny holes,", "他沿着轮廓扎出细小的孔，"),
         ("then looked closer, and closer.", "然后凑近，再凑近。")], [
        ("final1", 1, "still", dict(tr="fade", fx=("prick",), label="illustration · 示意")),
        ("photo03", 1, "in", dict(tr="push", loupe=[(0.3, 0.4), (0.6, 0.5), (0.45, 0.7)])),
        ("photo06", 1, "still", dict(tr="whip", hl=(0.45, 0.55, 0.22, 0.16))),
    ]),
    (2, [("Some drafts became paintings. Most did not.", "有的草稿成了画，大多数没有。")], [
        ("grid:photo07,photo08,photo10,photo12", 1, "still", dict(tr="flash")),
        ("rows:photo05,photo08,photo11", 1, "still", dict(tr="blinds", tl=(1896, 1910))),
        ("photo12", 1, "flip", dict(tr="fade", fx=("sketch",))),
    ]),
    (2, [("Make the difficult look effortless.", "把难事做得毫不费力。")], [
        ("quote:photo09", 1, "still", dict(tr="ink", fx=("dust",), q=(
            "Make the difficult look effortless.", "把难事做得毫不费力。", "— a made-up proverb"))),
        ("photo11", 1, "out", dict(tr="leak", fx=("shimmer",))),
    ]),
]

# ---------------------------------------------------------------- cover + post copy (cover.py / export.py)
COVER = dict(
    kicker="纪 念",
    title="灯塔画家",
    subtitle="The Lighthouse Painter · a synthetic demo",
    tagline=("他的", "草稿", "，比成品还好看"),      # middle part gets the accent colour + red-pen circle
    hero=dict(a="sketch1", b="final1", labels=("草稿 Draft", "成品 Final")),
    polaroids=[
        dict(src="photo04", caption="北港 1890", rot=-8),
        dict(src="photo05", caption="磨坊溪", rot=5),
        dict(src="photo06", caption="圈出来的细节", rot=-4, circle=(0.45, 0.55, 0.3, 0.22)),
        dict(src="photo09", caption="DEMO", rot=8),
    ],
    out="out/cover.png",
)
POST = dict(
    title="灯塔画家：一个虚构的故事",
    intro="用十二张占位图演示 photo-story 工作流。",
    tags=["#photo-story", "#demo"],
)
VOCAB = [("draft", "草稿", "Every painting started as a draft.")]   # optional study sheet (export.py)
