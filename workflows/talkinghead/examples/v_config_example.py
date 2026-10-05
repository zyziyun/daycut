# V track compose config (scripts/vertical/compose.py). SYNTHETIC example matching v_edit_list_example.py.
# Lives in the WORK dir next to segs.json. Paths are relative to this file's folder.
# Every effect time is a sentence anchor, so later re-cuts (strict_pass / drop_pass) never break timing:
#   S(sid, frac) = start (+fraction) of sentence sid, E(sid) = its end, SPAN(a, b) = (S(a), E(b)),
#   W(sid, "word") = start of a word (needs strict_pass words). Raw body seconds only for half-sentence hooks.
from anchors import S, E, SPAN, W  # noqa: F401

BODY = "body3_rt.mp4"; AUDIO = "body3_a.wav"; FACE = "face3.npy"   # final body after steps 4-7
OUT = "../my-talk_xhs.mp4"
# PLATFORM = "xiaohongshu:vertical"   # canvas + safe zones + caption band + loudness (vstudio.platform). Default:
#   persona platforms.default in 9:16 (小红书 9:16 1080x1920 = "xiaohongshu:full"). A bare "xiaohongshu" is the
#   profile default, i.e. "xiaohongshu:vertical" = 3:4 1080x1440. "douyin",
#   "youtube-shorts", "youtube" / "bilibili" = 16:9 1920x1080. CLI --platform overrides it per render.
# SRC_UPSCALE = 1.8                   # picture enlargement of the source (prep.json has it); caps the punch-in
# SEGS = "segs.json"                                   # default
GRADE = "hqdn3d=1.2:1.2:3:3,eq=contrast=1.06:brightness=0.015:saturation=1.07:gamma=1.02,colorbalance=rs=-0.02:bs=0.015:rm=-0.01,cas=0.45"
HOOK_SPEED = 1.3; BODY_SPEED = 1.1                    # omit to use persona speed.hook / speed.body; 加速 -> 1.5-1.65 / 1.25-1.35
XF = 0.3; HOOK_VOL_DB = 2                             # hook dissolve length, extra hook gain
KEYWORDS = ["关键词", "Keyword", "API"]                # coloured yellow in subtitles / titles / panels
# HOOK_BADGE_TEXT = "精彩预告"; NOTES_TAG = "记笔记 ↓"  # copy on the hook badge and panel tag

# Preset 精剪风. 记笔记风: zoom/pops/stamps/circles/cards/sfx False, progress='classic', callouts/panels/hook_badge True.
STYLE = dict(zoom=True, emph_zoom=1.32, alt_zoom=1.16,
             pops=True, stamps=True, circles=True, cards=True, sfx=True, progress='refined',
             callouts=False, panels=False, hook_badge=False, fx_in_hooks=True,   # callout_theme='notes-yellow' (white bubble)
             sub_size=54, sub_stroke=5)            # sub_y: default = centre of the platform caption band (1525 on 9:16)

HOOK_TITLE = ["第一行白字标题", "第二行带关键词的标题"]
HOOKS = [                     # picked by the creator from the hook menu, in her order; each hook = list of ranges
    [SPAN(7)],                # the core point
    [SPAN(4), SPAN(6)],       # two sentences spliced into one hook
    [(1.20, 2.35)],           # half a sentence: raw body seconds (or (W(9, "结论"), E(9)))
]
CHAPTERS = [(0, S(3), "开场"), (S(3), S(7), "三个点"), (S(7), E(9), "结论")]   # 2-4 char labels
EMPH = {7, 9}                 # sentences that get the tight punch-in

# big pop words: (t, text, 'Y'|'O', x_center, y_center, size, hold_body_seconds). Keep y 1260-1370 (on the torso).
POPS = [(S(4, .6), "第一点", "Y", 540, 1320, 170, 1.4), (S(7, .7), "核心", "O", 540, 1320, 220, 1.6)]
# red stamps: (t0, t1, text, x_left, y_top, angle). Same t1 = they stack. x_left <= 480, bottom row <= y 1340.
STAMPS = [(S(4, .4), E(6), "第一点", 380, 1050, -6), (S(5, .4), E(6), "第二点", 450, 1146, 5),
          (S(6, .4), E(6), "第三点", 400, 1242, -4)]
# circle-inset list scene: (t0, t1, title, [(t, token)], grid_2col)
CIRCLES = [(S(4), E(6), "列举的三个点", [(S(4, .55), "第一点"), (S(5, .55), "第二点"), (S(6, .55), "第三点")], False)]
# shrink-to-card scene for the core thesis: (t0, t1, title, [(t, line)])
CARDS = [(S(7), E(7), "核心观点", [(S(7, .1), "第一行要点"), (S(7, .5), "第二行要点")])]

# notes-board strategies (switch on in STYLE): callouts (t, on_screen_sec, text), panels (t0, t1, title, [(t, bullet)])
CALLOUTS = [(S(1), 6.0, "一句完整的金句气泡")]
PANELS = [(S(4), E(6), "三个要点", [(S(4), "第一点 不超过14字"), (S(5), "第二点"), (S(6), "第三点")])]

# B-roll for plain 口播 (scripts/vertical/broll.py): voice continues under the insert. mode "cut" = full cut-away,
# "pip" = picture-in-picture card placed off the face, "split" = split screen (top/bottom vertical, left/right 16:9).
# Images taller than their box become a scrolling screenshot card; highlight=[(t, y0, y1)] wipes a marker over a row
# (y fractions of the image). Paths are relative to this file. Other keys: ss, loop, fit, label, side, pos, w.
BROLL = [
    # dict(t0=S(2), t1=E(2), src="broll/demo.mp4", mode="cut", label="演示"),
    # dict(t0=S(5), t1=E(6), src="broll/page.png", mode="pip", highlight=[(S(5, .4), .42, .47)]),
    # dict(t0=S(8), t1=E(8), src="broll/chart.png", mode="split", side="top"),
]

# 3:4 cover (scripts/vertical/cover.py; --platform douyin / youtube for other sizes -> <OUT stem>.douyin-vertical.jpg, OUT kept). T from pick_cover_frame.py, on the FINAL body timeline.
COVER = dict(SRC="body3_rt.mp4", T=12.3, OUT="../my-talk_cover.jpg",
             TITLE=["第一行白字", "第二行带关键词"],
             STICKY=("记笔记", [("要点一", "ink"), ("要点二", "red")]),
             TAG="系列标签")
