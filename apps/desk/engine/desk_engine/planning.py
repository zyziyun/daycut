"""Segment planning helpers.

* ``rule_plan(words, ...)``: the ``none`` provider - rule-based selection by chapter + pauses + keyword density,
  the same contract ``plan-segments`` returns (id, start, end, title, chapter, hook{start,end,text}, notes, tags,
  why, risk, score).
* ``snap(t, words, edge)``: snap a time to the nearest word edge (start -> word start, end -> word end).
* ``faithful(old, new, heard)``: is a caption edit consistent with what is said in the audio?
"""
import difflib
import re
import shutil
import subprocess

KEYWORDS = {"RAG", "切块", "召回", "重排", "评估", "面试", "向量", "模型", "数据", "指标"}
HOOK_LINES = {
    "RAG 全景": "RAG 不是把文档塞进向量库这么简单",
    "切块策略": "切块切错了，后面全白做",
    "召回与重排": "只用向量召回？效果至少差一截",
    "评估": "没有评估集，你改了半天也不知道变好变坏",
    "总结": "三点讲清楚，RAG 面试基本稳了",
}


def probe_duration(path, default=600.0):
    if shutil.which("ffprobe"):
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=20).stdout
            d = float(out.strip())
            if d > 1:
                return d
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
    return default


def sentences(words, gap=0.5):
    """Split words into sentences at pauses >= gap: [(i0, i1)] inclusive indices."""
    out, i0 = [], 0
    for i in range(1, len(words) + 1):
        if i == len(words) or words[i]["t"] - words[i - 1]["te"] >= gap:
            out.append((i0, i - 1))
            i0 = i
    return out


def _text(ws):
    s = ""
    for w in ws:
        if s and re.match(r"[A-Za-z0-9]", w["w"][:1]) and re.match(r"[A-Za-z0-9]", s[-1:]):
            s += " "
        s += w["w"]
    return s


def rule_plan(words, count=6, min_s=30.0, max_s=90.0, title_max=20):
    """Greedy windows of whole sentences in [min_s, max_s], scored by keyword density; best ``count`` kept in
    time order. Returns plan-segments rows."""
    sents = sentences(words)
    cands = []
    for a in range(len(sents)):
        i0 = sents[a][0]
        for b in range(a, len(sents)):
            i1 = sents[b][1]
            dur = words[i1]["te"] - words[i0]["t"]
            if dur > max_s:
                break
            if dur < min_s:
                continue
            ws = words[i0:i1 + 1]
            kw = sum(w["w"] in KEYWORDS for w in ws)
            chapters = {w.get("chapter") for w in ws}
            score = kw / max(1.0, dur / 10) - 0.4 * (len(chapters) - 1)
            cands.append((score, i0, i1, a, b))
    cands.sort(key=lambda c: -c[0])
    chosen = []
    for c in cands:
        if all(c[2] < x[1] or c[1] > x[2] for x in chosen):
            chosen.append(c)
        if len(chosen) >= count:
            break
    chosen.sort(key=lambda c: c[1])
    rows, used = [], set()
    for n, (score, i0, i1, a, _b) in enumerate(chosen):
        ws = words[i0:i1 + 1]
        chapter = ws[0].get("chapter") or ""
        h0, h1 = sents[a]
        hook_ws = words[h0:min(h1, h0 + 14) + 1]
        title = HOOK_LINES.get(chapter) if chapter not in used else None
        used.add(chapter)
        title = (title or f"{chapter}：{_text(hook_ws)}")[:title_max]
        kws = [w["w"] for w in ws if w["w"] in KEYWORDS]
        tags = list(dict.fromkeys(kws))[:5]
        hooks = _hook_candidates(words, sents, i0, i1, chapter)
        rows.append(dict(
            id=f"s{n + 1:03d}", start=ws[0]["t"], end=ws[-1]["te"], title=title, chapter=chapter,
            hook=hooks[0] if hooks else dict(start=hook_ws[0]["t"], end=hook_ws[-1]["te"], text=_text(hook_ws)),
            hook_candidates=hooks,
            notes=[_text(words[s0:s1 + 1])[:24] for s0, s1 in sents[a:a + 3]],
            tags=tags, why=f"关键词密度高（{', '.join(tags[:3]) or '—'}），句子完整",
            risk="" if score > 0.5 else "信息密度一般，可能需要更强的 hook",
            score=round(max(0.0, min(1.0, score / 2)), 2)))
    return rows


def _hook_candidates(words, sents, i0, i1, chapter):
    """Up to 3 sentences inside [i0, i1] with the most keywords, as {start, end, text} (2-8 s)."""
    inside = [(s0, s1) for s0, s1 in sents if s0 >= i0 and s1 <= i1]
    scored = []
    for s0, s1 in inside:
        ws = words[s0:min(s1, s0 + 16) + 1]
        while len(ws) > 2 and ws[-1]["te"] - ws[0]["t"] > 8:
            ws = ws[:-1]
        if ws[-1]["te"] - ws[0]["t"] < 1.5:
            continue
        scored.append((sum(w["w"] in KEYWORDS for w in ws), ws))
    scored.sort(key=lambda x: -x[0])
    out = [dict(start=ws[0]["t"], end=ws[-1]["te"], text=_text(ws)) for _, ws in scored[:3]]
    if chapter in HOOK_LINES and out:
        out[0]["text"] = HOOK_LINES[chapter]
    return out


def snap(t, words, edge="start"):
    """Nearest word start (edge=start) or word end (edge=end) to t; t unchanged without words."""
    if not words:
        return t
    key = "t" if edge == "start" else "te"
    return min((w[key] for w in words), key=lambda x: abs(x - t))


_PUNCT = re.compile(r"[\s　-〿＀-／：-＠［-｀｛-･!-/:-@\[-`{-~]+")


def norm(s):
    return _PUNCT.sub("", s or "").lower()


def faithful(old, new, heard=None):
    """A caption edit may fix ASR errors / punctuation / terms, not add content. Returns
    dict(faithful, reason, ratio). ``heard`` = the words under the cue (defaults to ``old``)."""
    ref = norm(heard if heard is not None else old)
    n = norm(new)
    if not n:
        return dict(faithful=False, reason="empty", ratio=0.0)
    if n == norm(old) or n == ref:
        return dict(faithful=True, reason="punctuation" if n == norm(old) else "matches-audio", ratio=1.0)
    ratio = difflib.SequenceMatcher(None, ref, n).ratio()
    if len(n) > len(ref) + max(4, len(ref) // 4):
        return dict(faithful=False, reason="adds-words", ratio=round(ratio, 2))
    if ratio < 0.6:
        return dict(faithful=False, reason="differs-from-audio", ratio=round(ratio, 2))
    return dict(faithful=True, reason="term-fix", ratio=round(ratio, 2))


def _tokens(s):
    """Latin/digit runs as one token, every other non-punctuation char as its own token."""
    return re.findall(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]", _PUNCT.sub(" ", s or ""))


def term_fix(old, new):
    """The replaced span of a caption edit as a glossary entry {wrong, right}, or None (pure punctuation /
    several changes / large rewrites)."""
    a, b = _tokens(old), _tokens(new)
    if a == b:
        return None
    ops = [o for o in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    if len(ops) != 1 or ops[0][0] != "replace":
        return None
    _, i0, i1, j0, j1 = ops[0]
    latin = any(t.isascii() for t in a[i0:i1] + b[j0:j1])
    if not latin and (i1 - i0 < 2 or j1 - j0 < 2):
        # a one-character CJK fix ("形" -> "型") is only a term with its neighbours ("模形" -> "模型")
        lo = 1 if i0 > 0 and j0 > 0 else 0
        hi = 1 if i1 < len(a) and j1 < len(b) else 0
        if not lo and not hi:
            return None
        i0, j0, i1, j1 = i0 - lo, j0 - lo, i1 + hi, j1 + hi
    wrong, right = _join(a[i0:i1]), _join(b[j0:j1])
    if not (1 <= len(wrong) <= 12 and 1 <= len(right) <= 12):
        return None
    return dict(wrong=wrong, right=right)


def _join(toks):
    out = ""
    for t in toks:
        if out and out[-1].isascii() and out[-1].isalnum() and t[:1].isascii() and t[:1].isalnum():
            out += " "
        out += t
    return out
