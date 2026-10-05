"""Subtitles: cue model, CJK-aware balanced wrapping, highlight markup, SRT/ASS writers,
bilingual pairing and retiming through a cut.

    from vstudio import subs
    cues = subs.cues_from_words(tr["words"])                 # draft lines from ASR words
    cues = subs.retime(cues, timemap)                         # source -> final seconds
    subs.wrap_cjk("我们用Claude Code做了一个HyperFrames视频", 12)
    subs.srt_write(cues, "out/zh.srt"); subs.ass_write(cues, "work/subs.ass", w=1080, h=1920)

Width rule (same as ``vstudio.config.xhs_len``): CJK/full-width = 1, latin/digit/space = 0.5.
Highlight markup: ``【term】`` (persona subtitles.highlight_markup) or ``**term**``.
Unified from longform ``subs_lib.wrap/srt_ts/ass_ts/ass_header``, call-clips ``export_srt.ts/write``
(integer-ms rounding: never ",1000"), ``render_vertical._toks/_wrap/wrap_sub`` (latin runs whole,
balanced two lines), photo-story ``subtitles.wrap/bwrap`` (balanced, markers kept per line) and
``export.ts``, call-clips ``build_clips.load_subs`` / ``build_subs`` (retime, merge, linger).
"""
import math
import re
from dataclasses import dataclass, field

# ------------------------------------------------------------------ model


@dataclass
class Cue:
    """One subtitle: start/end seconds, text (may carry 【】/** markup), alt = second language."""
    start: float
    end: float
    text: str
    alt: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        d = dict(start=round(self.start, 3), end=round(self.end, 3), text=self.text)
        if self.alt:
            d["alt"] = self.alt
        if self.meta:
            d["meta"] = self.meta
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(float(d["start"]), float(d["end"]), d.get("text") or d.get("zh") or "",
                   d.get("alt") or d.get("en") or "", d.get("meta") or {})


def _persona_subs():
    try:
        from .config import persona
        return persona().get("subtitles", {}) or {}
    except Exception:
        return {}


# ------------------------------------------------------------------ markup
_HI = re.compile(r"【([^】]*)】|\*\*(.+?)\*\*")


def parse_highlight(text):
    """Split ``text`` into [(segment, highlighted)] for 【x】 and **x** markup."""
    out, i = [], 0
    for m in _HI.finditer(text):
        if m.start() > i:
            out.append((text[i:m.start()], False))
        out.append((m.group(1) if m.group(1) is not None else m.group(2), True))
        i = m.end()
    if i < len(text):
        out.append((text[i:], False))
    return [(s, h) for s, h in out if s]


def strip_markup(text):
    """Text with 【】 / ** markers removed."""
    return "".join(s for s, _ in parse_highlight(text))


# ------------------------------------------------------------------ wrapping
_LATIN = re.compile(r"[A-Za-z0-9%/+.\-'’&@#_$€£]+")
_CLOSE = set("，。、！？；：”’）》」』】,.!?;:)]…%")
_OPEN = set("“‘（《「『【([")


def char_width(c):
    """CJK/full-width = 1.0, everything else 0.5 (xhs_len rule)."""
    return 0.5 if ord(c) < 0x2E80 else 1.0


def text_width(s):
    return sum(char_width(c) for c in s)


def _tokens(text):
    """[(token, highlighted)] with latin/number runs whole, CJK per char, closing punctuation glued to
    the token before it and opening punctuation to the token after it (no line starts with ，)."""
    raw = []
    for seg, hi in parse_highlight(text):
        i = 0
        while i < len(seg):
            m = _LATIN.match(seg, i)
            if m:
                raw.append([m.group(), hi]); i = m.end()
            else:
                raw.append([seg[i], hi]); i += 1
    out = []
    for tok in raw:
        if out and tok[0] and tok[0][0] in _CLOSE and not out[-1][0].isspace():
            out[-1][0] += tok[0]
        elif out and out[-1][0] and out[-1][0][-1] in _OPEN and not tok[0].isspace():
            out[-1][0] += tok[0]; out[-1][1] = out[-1][1] or tok[1]
        else:
            out.append(tok)
    return [tuple(t) for t in out]


def _render(toks, style):
    s, open_ = "", False
    for t, hi in toks:
        if hi and not open_:
            s += "【" if style == "【】" else "**"; open_ = True
        elif not hi and open_:
            s += "】" if style == "【】" else "**"; open_ = False
        s += t
    if open_:
        s += "】" if style == "【】" else "**"
    return s


def _trim(toks):
    a, b = 0, len(toks)
    while a < b and toks[a][0].isspace():
        a += 1
    while b > a and toks[b - 1][0].isspace():
        b -= 1
    return toks[a:b]


def balanced_wrap(text, max_width, measure=None, max_lines=None):
    """Wrap into the FEWEST lines that fit ``max_width``, then balance them (similar lengths, breaks
    preferred after punctuation, never a one-character orphan line, latin words never split).

    Args: measure(str) -> width (default ``text_width``: CJK 1, latin 0.5; pass a PIL textlength for
    pixel wrapping); max_lines caps the line count (lines may then overflow). Markup is preserved on
    every line (a highlight spanning a break is closed and reopened).
    Returns [line, ...]. From photo-story ``subtitles.bwrap`` + call-clips ``wrap_sub`` (balanced, no orphan).
    """
    measure = measure or text_width
    style = "**" if "**" in text and "【" not in text else "【】"
    toks = _tokens(text)
    if not toks:
        return []
    widths = [measure(t) for t, _ in toks]
    total = measure(strip_markup(text).strip())
    if total <= max_width:
        return [text.strip()]
    m = len(toks)

    def lw(i, j):
        tt = _trim(toks[i:j])
        return sum(measure(t) for t, _ in tt) if tt else 0.0

    def is_orphan(i, j):
        tt = _trim(toks[i:j])
        return len(tt) == 1 and len(tt[0][0]) == 1 and not _LATIN.fullmatch(tt[0][0])

    n0 = max(2, math.ceil(total / max_width))
    best = None
    for n in range(n0, min(m, max_lines or m) + 1):
        target = total / n
        INF = float("inf")
        dp = [[INF] * (m + 1) for _ in range(n + 1)]
        bk = [[-1] * (m + 1) for _ in range(n + 1)]
        dp[0][0] = 0.0
        for L in range(1, n + 1):
            for j in range(1, m + 1):
                for i in range(L - 1, j):
                    if dp[L - 1][i] == INF:
                        continue
                    w = lw(i, j)
                    if w == 0:
                        continue
                    c = (w - target) ** 2
                    if w > max_width:
                        c += 1e6 * (w - max_width + 1)
                    if is_orphan(i, j):
                        c += 1e5
                    last = toks[j - 1][0]
                    if j < m and last and last[-1] in _CLOSE:
                        c -= 0.5 * target                   # break after punctuation
                    if dp[L - 1][i] + c < dp[L][j]:
                        dp[L][j], bk[L][j] = dp[L - 1][i] + c, i
        if dp[n][m] < float("inf"):
            cuts, j = [], m
            for L in range(n, 0, -1):
                i = bk[L][j]; cuts.append((i, j)); j = i
            lines = [_render(_trim(toks[i:j]), style) for i, j in reversed(cuts)]
            fits = all(lw(i, j) <= max_width for i, j in cuts)
            if best is None or fits:
                best = lines
            if fits:
                break
    return best or [text.strip()]


def wrap_cjk(text, max_chars=None, max_lines=None):
    """CJK-aware subtitle wrap (width: CJK 1, latin 0.5; default persona subtitles.max_cjk_chars, 18).
    Latin runs stay whole ("Claude Code" never splits), no line starts with closing punctuation,
    no single-character last line. Returns [line, ...]. See ``balanced_wrap``.
    From longform ``subs_lib.wrap``, call-clips ``render_vertical._wrap/_toks/wrap_sub``."""
    max_chars = max_chars or _persona_subs().get("max_cjk_chars", 18)
    return balanced_wrap(text, max_chars, max_lines=max_lines)


# ------------------------------------------------------------------ timestamps
def _ms(t):
    return max(0, int(round(float(t) * 1000)))


def srt_ts(t):
    """SRT time 'HH:MM:SS,mmm' from seconds; rounds once in integer ms (59.9996 -> 00:01:00,000,
    never ',1000'). From call-clips ``export_srt.ts``."""
    ms = _ms(t)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_ts(t):
    """ASS time 'H:MM:SS.cc' from seconds, integer centiseconds (never '60.00')."""
    cs = max(0, int(round(float(t) * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean_times(cues, no_overlap=True, min_ms=40):
    out = []
    cs = sorted(cues, key=lambda c: c.start)
    for i, c in enumerate(cs):
        a, b = _ms(c.start), _ms(c.end)
        if no_overlap and i + 1 < len(cs):
            b = min(b, _ms(cs[i + 1].start))
        if b - a < min_ms:
            b = a + min_ms
        out.append((a / 1000, b / 1000, c))
    return out


# ------------------------------------------------------------------ writers
def srt_write(cues, path, which="text", wrap=None, no_overlap=True):
    """Write an .srt. which: "text" | "alt" | "both" (text line(s) then alt). wrap: max chars per
    line (CJK-aware) or None. Markup stripped; empty cues skipped; times clamped >= 0, end > start,
    no overlap. Returns the number of cues written. From call-clips ``export_srt.write``."""
    n, lines = 0, []
    for a, b, c in _clean_times(cues, no_overlap):
        parts = []
        if which in ("text", "both") and c.text.strip():
            t = strip_markup(c.text).strip()
            parts += wrap_cjk(t, wrap) if wrap else [t]
        if which in ("alt", "both") and c.alt.strip():
            parts += [strip_markup(c.alt).strip()]
        if not parts:
            continue
        n += 1
        lines.append(f"{n}\n{srt_ts(a)} --> {srt_ts(b)}\n" + "\n".join(parts) + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return n


_SRT_T = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def srt_read(path):
    """Parse an .srt into [Cue] (multi-line text joined with a newline)."""
    with open(path, encoding="utf-8-sig") as f:
        blocks = re.split(r"\n\s*\n", f.read().strip())
    out = []
    for b in blocks:
        ls = b.strip().splitlines()
        for k, line in enumerate(ls):
            m = _SRT_T.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                out.append(Cue(a, e, "\n".join(ls[k + 1:])))
                break
    return out


def _ass_colour(hexstr):
    h = hexstr.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_text(text, hi_colour):
    out = ""
    for seg, hi in parse_highlight(text):
        seg = seg.replace("{", "(").replace("}", ")").replace("\n", r"\N")
        out += f"{{\\c{hi_colour}&}}{seg}{{\\r}}" if hi else seg
    return out


def font_family(role="cjk-bold"):
    """Family name of a vstudio font for ASS styles (fallback "Noto Sans SC")."""
    try:
        from PIL import ImageFont
        from .config import font
        return ImageFont.truetype(font(role), 10).getname()[0]
    except Exception:
        return "Noto Sans SC"


def ass_write(cues, path, w=1920, h=1080, font_name=None, size=None, wrap=None, highlight=None,
              alt_scale=0.72, margin_v=None, outline=2.4, no_overlap=True):
    """Write an .ass for burning with ffmpeg's ``ass`` filter (needs libass: ``media.ffmpeg_bin(need=["ass"])``).

    Style "Sub": bold white, black outline, bottom-centre; size defaults to 52 px at 1080 lines
    (scaled to ``h``). Highlights render in ``highlight`` (persona brand.highlight); ``alt`` goes on
    a smaller second line (alt_scale). wrap: max chars per line (CJK-aware) for the main text.
    Times clamped like ``srt_write``. Returns the number of events.
    From longform ``subs_lib.ass_header/ass_ts`` + ``build_subs``.
    """
    k = min(w, h) / 1080.0
    size = size or int(52 * k)
    mv = margin_v if margin_v is not None else int(42 * k)
    font_name = font_name or font_family()
    if highlight is None:
        try:
            from .config import persona
            highlight = (persona().get("brand") or {}).get("highlight", "#FFD60A")
        except Exception:
            highlight = "#FFD60A"
    hc = _ass_colour(highlight)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font_name},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H88000000,1,0,0,0,100,100,0,0,1,{outline},1,2,{int(60 * k)},{int(60 * k)},{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for a, b, c in _clean_times(cues, no_overlap):
        main = wrap_cjk(c.text, wrap) if wrap else [c.text]
        txt = r"\N".join(_ass_text(t, hc) for t in main if t.strip())
        if c.alt.strip():
            alt = _ass_text(c.alt.strip(), hc)
            txt = (txt + r"\N" if txt else "") + f"{{\\fs{int(size * alt_scale)}}}{alt}"
        if not txt:
            continue
        ev.append(f"Dialogue: 0,{ass_ts(a)},{ass_ts(b)},Sub,,0,0,0,,{txt}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    return len(ev)


# ------------------------------------------------------------------ building / timing
def cues_from_words(words, max_chars=None, max_gap=0.45, linger=0.3, fixes=None):
    """Draft cues from ASR words: a new cue at a gap > max_gap or when the line would exceed
    max_chars (CJK width); latin words keep a space between them; each cue lingers up to ``linger``
    s into the following pause. fixes: passed to ``asr.apply_term_fixes`` (None = persona+generic,
    False = none). Words: {"w","t","te"} or whisper {"word","start","end"}.
    From promo ``tight_cut.draft_subs``, call-clips ``build_subs`` / ``build_clips.load_subs``."""
    max_chars = max_chars or _persona_subs().get("max_cjk_chars", 18)
    ws = []
    for w in words:
        if isinstance(w, dict) and "t" in w:
            ws.append((w["w"], w["t"], w["te"]))
        elif isinstance(w, dict):
            ws.append((w["word"].strip(), w["start"], w["end"]))
        else:
            ws.append(tuple(w))
    cues, cur = [], []

    def join(items):
        s = ""
        for t, _, _ in items:
            t = t.strip()
            if s and re.match(r"[A-Za-z0-9%]", s[-1]) and re.match(r"[A-Za-z0-9]", t[:1]):
                s += " "
            s += t
        return s

    for w in ws:
        if not w[0].strip():
            continue
        if cur and (w[1] - cur[-1][2] > max_gap or text_width(join(cur + [w])) > max_chars):
            cues.append(Cue(cur[0][1], cur[-1][2], join(cur))); cur = []
        cur.append(w)
    if cur:
        cues.append(Cue(cur[0][1], cur[-1][2], join(cur)))
    if fixes is not False:
        from .asr import apply_term_fixes
        for c in cues:
            c.text = apply_term_fixes(c.text, fixes or None)
    for i, c in enumerate(cues[:-1]):
        c.end = min(cues[i + 1].start, c.end + linger)
    return [c for c in cues if c.text]


def retime(cues, timemap, min_dur=0.28, tag=None):
    """Map cues from source to final time through a ``cut.TimeMap``: the start snaps forward and the
    end back past removed material; cues with nothing left (or shorter than min_dur) are dropped.
    From call-clips ``build_clips.load_subs`` (+ ``src_to_final``), longform ``build_subs`` (``map_src``),
    promo ``common.raw2cut``."""
    out = []
    for c in cues:
        span = timemap.map_span(c.start, c.end, tag=tag, min_dur=min_dur)
        if span:
            out.append(Cue(span[0], span[1], c.text, c.alt, dict(c.meta)))
    return out


def pair_bilingual(primary, secondary, min_overlap=0.1):
    """Attach ``secondary`` cues (other language) to ``primary`` as ``alt`` by largest time overlap;
    several secondaries landing on one primary are joined with a space. Returns new cues."""
    out = [Cue(c.start, c.end, c.text, "", dict(c.meta)) for c in primary]
    for s in secondary:
        best, bo = None, min_overlap
        for c in out:
            ov = min(c.end, s.end) - max(c.start, s.start)
            if ov > bo:
                best, bo = c, ov
        if best is not None:
            best.alt = (best.alt + " " + s.text).strip() if best.alt else s.text
    return out


def apply_translations(cues, mapping):
    """Set ``alt`` from {primary text: translation} (call-clips keys English by the final Chinese
    text so re-cutting never misaligns it). Returns (cues, n_missing)."""
    miss = 0
    for c in cues:
        c.alt = mapping.get(c.text, mapping.get(strip_markup(c.text), ""))
        miss += not c.alt
    return cues, miss
