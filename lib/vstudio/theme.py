"""Design themes: one named set of tokens (paper, ink, ONE accent, emphasis treatment, fonts, radius, shadow,
card / quote / stamp / pop / progress styles, motion) that every themed overlay reads.

    from vstudio import theme as TH
    T = TH.current()                      # the resolved theme dict (see resolve() for the order)
    TH.names()                            # ['editorial', 'mono', 'soft', 'night', 'xhs-pop', 'classic']
    with TH.use("night"):                 # an explicit theme for a block of drawing (output edit `theme` op)
        ...
    TH.resolve("editorial", recipe={"theme": "mono"})   # explicit beats recipe

Resolution order (first that is set wins); every layer is a preset name or a dict
``{"theme": name, <token>: value, ...}`` (tokens override the preset's, e.g. ``{"theme": "editorial",
"accent": "#3E5C76"}``):

  1. explicit       ``resolve(x)`` / ``with use(x)`` (the output-edit ``theme`` op renders inside ``use``)
  2. env            ``$VSTUDIO_THEME`` (a project / recipe run hands its theme to workflow subprocesses)
  3. recipe         ``resolve(recipe=...)``: project params ``{"theme": ..}`` or a recipe id whose manifest has a
                    ``theme`` param default
  4. client         persona ``client.theme`` (client.yaml ``theme``, merged into the client persona)
  5. persona        persona ``style.theme`` (+ ``style.<token>`` overrides)
  6. legacy         persona ``brand.accent`` set explicitly and no theme anywhere -> ``classic`` (the old look,
                    with the persona's own brand colours), so existing setups do not change under them
  7. default        ``editorial``

Explicit per-element colours (an effect's ``color``, caption_style ``color`` / ``highlight``, a title's
``color`` / ``band_color``) always win over the theme. Rules: references/STYLE_RULES.md.
"""
import contextlib
import contextvars
import copy
import json
import os

DEFAULT = "editorial"

# Fonts: roles of vstudio.config.FONTS (OFL only: Noto Sans SC / Noto Serif SC).
_BASE = dict(
    label="", label_zh="", desc_zh="",
    # colour
    paper="#F5F1EA", ink="#1D1B18", ink2="#6A635A", rule="#DCD3C5", accent="#A84F2D", accent_ink="#FFFFFF",
    marker="#EBCDB9", marker_alpha=1.0,            # keyword highlight band (on paper; over video it is drawn at 0.85)
    emphasis="marker",                             # marker | color | underline : how a 【keyword】 is emphasised
    emph_per_line=1,                               # at most this many emphasised runs per line (0 = unlimited)
    card="#FFFDF8", card_alpha=0.96, card_ink="#1D1B18",
    over_ink="#FFFFFF", over_emph="#F3D3AE", over_stroke="#141414", over_stroke_w=0.05, over_shadow=110,
    over_ink2="#E4DED4",                           # secondary line over video (bilingual captions: the translation)
    # type
    font_title="cjk-serif-bold", font_strong="cjk-bold", font_body="cjk", font_quote="cjk-serif-bold",
    font_caption="cjk-bold", font_label="cjk-bold", label_track=0.12,
    # shape
    radius=14, shadow=(18, 6, 38), rule_w=2,
    # furniture styles
    notes="paper",          # paper (light card, small label + thin rule) | header (legacy coloured header)
    quote="type",           # type (weight contrast, hanging quote, thin rule) | glyph (legacy big coloured mark)
    stamp=dict(style="label", color="accent", angle=0.0, anim="rise", border=2, fill_alpha=0.95),
    pop=dict(style="underline", anim="rise", angle=0.0),
    progress=dict(style="line", height=4, fill="accent", track="rule", label=False),
    band="paper",           # band layouts: paper (flat theme paper) | blur (legacy blurred, darkened video)
    title_align="center",
    # motion
    motion=dict(in_s=0.28, out_s=0.2, rise=0.012, ease="cubic-out", overshoot=False),
)


def _p(**kw):
    d = copy.deepcopy(_BASE)
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = dict(d[k], **v)
        else:
            d[k] = v
    return d


PRESETS = {
    "editorial": _p(
        label="Editorial", label_zh="编辑感",
        desc_zh="暖白纸 + 深墨色 + 一点赤陶色；关键词用柔和的马克笔底色，标题用宋体（思源宋体）"),
    "mono": _p(
        label="Mono", label_zh="黑白灰",
        desc_zh="黑白灰 + 一支荧光黄马克笔；最克制，适合干货 / 观点",
        paper="#F3F3F1", ink="#111111", ink2="#646464", rule="#D4D4D0", accent="#111111", accent_ink="#FFFFFF",
        marker="#EFE59A", card="#FFFFFF", card_alpha=0.97, card_ink="#111111", over_emph="#F3E7A0",
        font_title="cjk-bold", font_quote="cjk-bold", radius=6, shadow=(12, 4, 30),
        stamp=dict(color="ink"), progress=dict(fill="ink"), over_ink2="#DCDCDA"),
    "soft": _p(
        label="Soft", label_zh="低饱和柔和",
        desc_zh="石灰白 + 鼠尾草绿，圆角更大、阴影更轻；适合生活方式 / 温和的分享",
        paper="#F1F0EA", ink="#2A2B2E", ink2="#64666B", rule="#DAD8CF", accent="#56766A", accent_ink="#FFFFFF",
        marker="#C8DCCB", card="#FCFCF9", card_alpha=0.95, card_ink="#2A2B2E", over_emph="#CFE4D3",
        font_title="cjk-bold", font_quote="cjk-bold", radius=26, shadow=(26, 8, 28),
        stamp=dict(color="accent"), over_ink2="#DCE6DE"),
    "night": _p(
        label="Night", label_zh="夜间",
        desc_zh="深炭色底 + 暖琥珀色；关键词直接用琥珀色字，适合夜聊 / 情绪向",
        paper="#141518", ink="#F2EDE4", ink2="#A29D94", rule="#30323A", accent="#E0A458", accent_ink="#141518",
        marker="#E0A458", marker_alpha=0.32, emphasis="color", card="#1E2025", card_alpha=0.94, card_ink="#F2EDE4",
        over_emph="#E8B86D", font_title="cjk-serif-bold", font_quote="cjk-serif-bold", shadow=(22, 8, 90),
        stamp=dict(color="accent"), over_ink2="#E9D9BF"),
    "xhs-pop": _p(
        label="XHS pop", label_zh="小红书红（克制版）",
        desc_zh="保留小红书红，但只给一个关键词用；白卡片、细线、无黑框",
        paper="#FBF8F3", ink="#1A1A1E", ink2="#6F6A64", rule="#E6DFD5", accent="#D42A43", accent_ink="#FFFFFF",
        marker="#FFDCE1", emphasis="color", card="#FFFFFF", card_alpha=0.97, card_ink="#1A1A1E",
        over_emph="#FFD3D9", font_title="cjk-bold", font_quote="cjk-bold", radius=16,
        stamp=dict(style="outline", color="accent", angle=-3.0, anim="pop", border=3), pop=dict(anim="pop"),
        motion=dict(overshoot=True)),
    # the pre-theme look (red header notes, red glyph quote, slamming stamps): kept for existing setups
    "classic": _p(
        label="Classic", label_zh="旧版（红色）", desc_zh="改版前的样子：红色标题 / 黑底红头笔记卡 / 砸入印章",
        paper="#FAF7F2", ink="#1A1A1E", ink2="#6E6A66", rule="#D8DEE2", accent="#FF2442", accent_ink="#FFFFFF",
        marker="#FFD60A", emphasis="color", emph_per_line=0, card="#16181E", card_alpha=0.97, card_ink="#FFFFFF",
        over_emph="#FFD60A", over_stroke_w=0.08, over_shadow=150, font_title="cjk-bold", font_quote="cjk-bold",
        radius=18, shadow=(16, 10, 55), notes="header", quote="glyph",
        stamp=dict(style="plate", color="accent", angle=8.0, anim="slam", border=7, fill_alpha=0.84),
        pop=dict(style="stroke", anim="pop", angle=-4.0), progress=dict(style="refined", height=7),
        band="blur", motion=dict(in_s=0.22, out_s=0.18, rise=0.0, overshoot=True)),
}
CHOICES = ("editorial", "mono", "soft", "night", "xhs-pop")       # what the creator is offered
ALIASES = {"default": "editorial", "高级": "editorial", "编辑": "editorial", "编辑感": "editorial", "杂志": "editorial",
           "黑白": "mono", "黑白灰": "mono", "极简": "mono", "柔和": "soft", "低饱和": "soft", "温柔": "soft",
           "夜间": "night", "深色": "night", "暗色": "night", "小红书": "xhs-pop", "小红书红": "xhs-pop",
           "xhs": "xhs-pop", "旧版": "classic", "legacy": "classic"}
COLOR_TOKENS = ("paper", "ink", "ink2", "rule", "accent", "accent_ink", "marker", "card", "card_ink", "over_ink", "over_ink2",
                "over_emph", "over_stroke")

_EXPLICIT = contextvars.ContextVar("vstudio_theme", default=None)


def names(all_=False):
    return list(PRESETS) if all_ else list(CHOICES)


def canonical(name):
    """A preset name / alias / zh label -> the preset id, or None."""
    if not name:
        return None
    n = str(name).strip()
    if n in PRESETS:
        return n
    low = n.lower()
    if low in PRESETS:
        return low
    if n in ALIASES or low in ALIASES:
        return ALIASES.get(n) or ALIASES[low]
    for k, p in PRESETS.items():
        if n in (p["label"], p["label_zh"]):
            return k
    return None


def _layer(v):
    """A layer value -> (preset id or None, token overrides) ; None when the layer is unset / unknown."""
    if v is None or v == "":
        return None
    if isinstance(v, str):
        if v.strip().startswith("{"):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        else:
            c = canonical(v)
            return (c, {}) if c else None
    if isinstance(v, dict):
        name = v.get("theme") or v.get("name")
        c = canonical(name) if name else None
        ov = {k: x for k, x in v.items() if k in _BASE and x is not None}
        if not c and not ov:
            return None
        return c, ov
    return None


def _persona():
    try:
        from .config import persona
        return persona() or {}
    except Exception:  # noqa: BLE001
        return {}


def _recipe_layer(recipe):
    if recipe is None:
        return None
    if isinstance(recipe, dict):
        return _layer(recipe.get("theme") if "theme" in recipe else recipe.get("style"))
    try:                                            # a recipe id: the manifest's `theme` param default
        from .project import manifests as M
        m = M.get(str(recipe))
        return _layer(((m.get("params") or {}).get("properties") or {}).get("theme", {}).get("default"))
    except Exception:  # noqa: BLE001
        return None


def layers(explicit=None, recipe=None, persona=None):
    """[(source, layer)] in priority order (only the set ones)."""
    p = _persona() if persona is None else persona
    style = p.get("style") if isinstance(p.get("style"), dict) else {}
    out = []
    for src, v in (("explicit", _layer(explicit) if explicit is not None else _layer(_EXPLICIT.get())),
                   ("env", _layer(os.environ.get("VSTUDIO_THEME"))),
                   ("recipe", _recipe_layer(recipe)),
                   ("client", _layer((p.get("client") or {}).get("theme") if isinstance(p.get("client"), dict) else None)),
                   ("persona", _layer(dict(style, theme=style.get("theme")) if style else None))):
        if v:
            out.append((src, v))
    return out


def resolve(explicit=None, recipe=None, persona=None):
    """The theme dict (a copy): preset of the highest set layer, token overrides of every layer applied lowest
    first (so a persona accent tint survives a recipe that only names a preset; a higher layer's tokens win)."""
    p = _persona() if persona is None else persona
    ls = layers(explicit, recipe, p)
    name = next((c for _, (c, _o) in ls if c), None)
    source = next((s for s, (c, _o) in ls if c), None)
    brand = p.get("brand") or {}
    legacy = False
    if name is None:
        if isinstance(brand.get("accent"), str) or brand.get("panel_theme"):
            name, source, legacy = "classic", "legacy", True
        else:
            name, source = DEFAULT, "default"
    T = copy.deepcopy(PRESETS[name])
    if legacy:                                       # the persona's own brand colours keep the old look exact
        if isinstance(brand.get("accent"), str):
            T["accent"] = brand["accent"]
        if isinstance(brand.get("highlight"), str):
            T["marker"] = T["over_emph"] = brand["highlight"]
    for _src, (_c, ov) in reversed(ls):
        for k, v in ov.items():
            T[k] = dict(T[k], **v) if isinstance(T.get(k), dict) and isinstance(v, dict) else v
    T["name"], T["source"] = name, source
    return T


def current():
    """The active theme (explicit ``use`` block / env / client / persona / legacy / default)."""
    return resolve()


@contextlib.contextmanager
def use(theme):
    """Draw a block with an explicit theme (name, alias or ``{"theme": .., <token>: ..}``); None = no change."""
    if theme is None:
        yield current()
        return
    tok = _EXPLICIT.set(theme)
    try:
        yield current()
    finally:
        _EXPLICIT.reset(tok)


def is_classic(T=None):
    return (T or current())["name"] == "classic"


# ---------------------------------------------------------------- colour helpers
def rgb(T, key):
    """Token -> (r, g, b). ``key`` may be a token name or a colour; 'accent' / 'ink' etc. resolve via T."""
    from .draw import rgb as _rgb
    v = T.get(key, key) if isinstance(key, str) else key
    return _rgb(v)


def rgba(T, key, alpha=1.0):
    a = alpha if alpha > 1 else int(round(255 * alpha))
    return rgb(T, key) + (int(a),)


def luminance(c):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    """WCAG contrast ratio of two RGB colours."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(T=None):
    return luminance(rgb(T or current(), "paper")) < 0.2


def ease(T, u):
    """Theme easing of u in [0, 1] (cubic ease-out; with ``overshoot`` a gentle back-out)."""
    u = min(1.0, max(0.0, u))
    if (T or {}).get("motion", {}).get("overshoot"):
        s = 1.2
        v = u - 1.0
        return 1.0 + (s + 1) * v ** 3 + s * v ** 2
    return 1.0 - (1.0 - u) ** 3


def css_vars(T=None):
    """':root{--paper:..;--ink:..;--accent:..;...}' for HyperFrames / HTML templates."""
    T = T or current()
    from .draw import rgb as _rgb
    out = []
    for k in COLOR_TOKENS:
        try:
            r, g, b = _rgb(T[k])
        except (KeyError, ValueError, TypeError):
            continue
        out.append(f"--{k.replace('_', '-')}:#{r:02X}{g:02X}{b:02X};")
    out.append(f"--radius:{int(T['radius'])}px;")
    out.append(f"--ease:cubic-bezier(.22,.61,.36,1);--dur-in:{int(T['motion']['in_s'] * 1000)}ms;")
    return ":root{" + "".join(out) + "}"


def describe(T=None):
    T = T or current()
    return dict(name=T["name"], label=T["label"], label_zh=T["label_zh"], desc_zh=T["desc_zh"], source=T.get("source"),
                paper=T["paper"], ink=T["ink"], accent=T["accent"], emphasis=T["emphasis"])


def catalogue():
    return [dict(id=k, label=PRESETS[k]["label"], label_zh=PRESETS[k]["label_zh"], desc_zh=PRESETS[k]["desc_zh"],
                 paper=PRESETS[k]["paper"], ink=PRESETS[k]["ink"], accent=PRESETS[k]["accent"])
            for k in names(all_=True)]
