"""Subtitle helpers: ASR term fixes, CJK-aware wrap, SRT/ASS timestamps, ASS header.

Term fixes are applied in this order:
  1. config.subtitles.term_fixes   [[regex, replacement], ...]   per-video mis-hearings
  2. persona subtitles.term_fixes  {"heard": "meant"}            creator-wide (literal, case-insensitive)
  3. GENERIC_TERM_FIXES            below: common tech-talk ASR misses, safe for anyone
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import re

from vstudio.config import persona

GENERIC_TERM_FIXES = [
    (r"[Ll]it ?code|[Ll]eet ?code|[Ll]ead ?code", "LeetCode"),
    (r"\bGithub\b|\bgit hub\b", "GitHub"),
    (r"\bopen ?AI\b|\bopenai\b", "OpenAI"),
    (r"[Cc]hat ?GPT|[Cc]hallet ?GPT", "ChatGPT"),
    (r"[Ll]ong ?chain|[Ll]ung ?chain", "LangChain"),
    (r"[Ll]ong ?graph|[Ll]ung ?graph", "LangGraph"),
    (r"\bpg ?vector\b|\bpd vector\b", "pgvector"),
    (r"system problem", "system prompt"),
    (r"field shot|feel shot", "few-shot"),
    (r"半tune", "fine-tune"),
    (r"[Ff]acefulness", "faithfulness"),
    (r"[Bb]anjmark", "benchmark"),
    (r"(?<![A-Za-z])REG(?![A-Za-z])", "RAG"),
]

FILLER_ONLY = re.compile(r"[嗯啊哦呃哈OK好的。，\s]*")


def term_fixes(cfg):
    fixes = [(p, r) for p, r in (cfg.get("subtitles.term_fixes") or [])]
    for heard, meant in ((persona().get("subtitles") or {}).get("term_fixes") or {}).items():
        fixes.append((r"(?i)" + re.escape(heard), meant))
    return fixes + GENERIC_TERM_FIXES


def make_clean(cfg):
    fixes = [(re.compile(p), r) for p, r in term_fixes(cfg)]

    def clean(t):
        t = t.strip()
        for pat, rep in fixes:
            t = pat.sub(rep, t)
        t = re.sub(r"嗯{2,}", "", t)
        t = re.sub(r"(.)\1{4,}", r"\1", t)  # collapse stutter / hallucination runs
        return t.strip()
    return clean


def wrap(t, max_line):
    """Two-line wrap at the punctuation / non-latin boundary nearest the middle (ASS \\N)."""
    if len(t) <= max_line:
        return t
    mid = len(t) // 2
    cand = [m.start() + 1 for m in re.finditer(r"[，。、？！,.?! ]", t)]
    if not cand:
        cand = [i for i in range(1, len(t))
                if not (re.match(r"[A-Za-z0-9-]", t[i - 1]) and re.match(r"[A-Za-z0-9-]", t[i]))]
    pos = min(cand, key=lambda p: abs(p - mid)) if cand else mid
    return t[:pos] + r"\N" + t[pos:]


def srt_ts(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


def ass_ts(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_header(font_name, w=1920, h=1080):
    k = h / 1080.0
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font_name},{int(52 * k)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H88000000,1,0,0,0,100,100,0,0,1,2.4,1,2,80,80,{int(42 * k)},1
Style: Note,{font_name},{int(38 * k)},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB0000000,0,0,0,0,100,100,0,0,3,2,0,8,60,60,{int(36 * k)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
