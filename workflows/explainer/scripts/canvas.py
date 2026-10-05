"""Canvas of an explainer project: the legacy 16:9 layout, or a vstudio.platform profile (vertical shorts).

Resolution order: ``--platform`` CLI flag > ``"platform"`` in ``<project>/scenes.config.json`` > legacy 16:9.
A horizontal profile (youtube, bilibili, xiaohongshu:horizontal) keeps the legacy 1920x1080 layout
(captions own y > 840, math in y 80-800), so 16:9 projects build exactly as before.

    from canvas import resolve, add_platform_arg
    cv = resolve(root, a.platform)     # dict: W, H, legacy, key, safe, caption, keepouts, math, ...

Vertical keys (all px on the canvas):
  safe      (x0, y0, x1, y1)   platform.safe_box: free of the app's top bar / bottom description / side buttons
  caption   (x0, y0, x1, y1)   platform.caption_box: where the bilingual captions sit (bottom-anchored)
  keepouts  [(x0, y0, x1, y1)] lower-right button column(s)
  math      (x0, y0, x1, y1)   the scene's drawing area: safe box below a title strip, above the caption band
  math_narrow_from_y, math_narrow_x1   below this y keep content left of x1 (button column)
  en_fs / zh_fs                caption sizes, from the caption band height (2 lines each fit the band)
  max_en / max_zh              soft per-cue char limits (2 lines each at those sizes)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import json

LEGACY = dict(W=1920, H=1080, legacy=True, key="legacy:16:9", orientation="horizontal",
              caption=(120, 840, 1800, 1036), math=(80, 80, 1840, 800), safe=(0, 0, 1920, 1080), keepouts=[],
              en_fs=38, zh_fs=34, max_en=100, max_zh=40)


def add_platform_arg(ap):
    ap.add_argument("--platform", default=None,
                    help="vstudio.platform profile for the canvas, e.g. xiaohongshu:full, douyin, youtube-shorts, "
                         "xiaohongshu:vertical (3:4). Default: scenes.config.json \"platform\", else 16:9 (legacy)")


def project_platform(root):
    p = pathlib.Path(root) / "scenes.config.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("platform")
        except (ValueError, AttributeError):
            return None
    return None


def resolve(root=".", platform=None):
    spec = platform or project_platform(root)
    if not spec:
        return dict(LEGACY)
    from vstudio import platform as PF
    prof = PF.profile(spec)
    if prof.w >= prof.h:
        return dict(LEGACY, key=prof.key, profile=prof)
    W, H = prof.w, prof.h
    safe = PF.safe_box(prof)
    cap = PF.caption_box(prof)
    kos = PF.keepouts(prof)
    bh = cap[3] - cap[1]
    zh_fs = int(round(min(48, bh * 0.22)))
    en_fs = int(round(zh_fs * 0.8))
    cw = cap[2] - cap[0]
    max_zh = 2 * int(cw / zh_fs)                 # 2 lines of CJK
    max_en = 2 * int(cw / (en_fs * 0.5))         # 2 lines of latin (~0.5 em per char)
    title_strip = 110                            # scene title (eyebrow) under the app's top bar
    m = max(safe[0], W - safe[2], 60)
    math = (m + 30, safe[1] + title_strip, W - m - 30, cap[1] - 50)
    narrow_y = min((k[1] for k in kos), default=None)
    narrow_x1 = min((k[0] for k in kos), default=None)
    return dict(W=W, H=H, legacy=False, key=prof.key, orientation="vertical", profile=prof,
                safe=safe, caption=cap, keepouts=kos, math=math,
                math_narrow_from_y=narrow_y, math_narrow_x1=(narrow_x1 - 20) if narrow_x1 else None,
                title_xy=(math[0], safe[1] + 70), en_fs=en_fs, zh_fs=zh_fs, max_en=max_en, max_zh=max_zh)


def describe(cv):
    """One-paragraph canvas description for frame packets / dispatch."""
    if cv["legacy"]:
        return "canvas: 1920×1080 · Captions: enabled (root track owns y > 840; keep all content y ≤ 800)"
    x0, y0, x1, y1 = cv["math"]
    s = (f"canvas: {cv['W']}×{cv['H']} ({cv['key']}) · safe box {tuple(cv['safe'])} (platform UI outside it) · "
         f"captions own the band {tuple(cv['caption'])} — keep every element above y {cv['caption'][1] - 30} · "
         f"math area x {x0}–{x1}, y {y0}–{y1}; scene title at {tuple(cv['title_xy'])}")
    if cv.get("math_narrow_from_y"):
        s += (f" · lower-right button column: below y {cv['math_narrow_from_y']} keep content left of "
              f"x {cv['math_narrow_x1']}")
    return s
