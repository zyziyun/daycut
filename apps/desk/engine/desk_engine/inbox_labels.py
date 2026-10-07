"""Plain-language inbox options: the "creator should confirm" bullets of PICKS.md / NOTES.md are notes an agent wrote
for itself ("change the D start to 316.72 in `work/make_src.py`"). The inbox never shows those: every option gets a
human label (code + params + English / Chinese text), the quoted line it is about, how many seconds it saves, where
to watch it (seconds in the finished clip, and in the source recording when it is in the folder) and, for real
choices, a choice set with the recommended one first.

    picks_spans(text)                       -> {letter: [[a, b], ...]} source spans of the pick table (seconds)
    humanize(conf, spans, clip_for, words_for, source) -> option dict (see ``humanize``)
    engine_option(o, default)               -> the same shape for an engine checkpoint option
    spend_params(entry)                     -> {amount, currency, what} of a budget approval
"""
import os
import re

CLOCK = r"(\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?\s*s)"
QUOTE = re.compile(r"[「“\"]([^」”\"]{1,200})[」”\"]")
CJK = re.compile(r"[㐀-鿿]")


def clock(s):
    """'5:05.6' / '10:53' / '12.5 s' -> seconds (None when not a time)."""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2}(?:\.\d+)?)$", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"^(\d+(?:\.\d+)?)\s*s$", s)
    return float(m.group(1)) if m else None


def picks_spans(text):
    """The pick table's 'Source span' column -> {letter: [[a, b], ...]} (several spans joined with '+')."""
    out = {}
    for ln in (text or "").splitlines():
        m = re.match(r"^\|\s*([A-Z0-9]{1,3})\b[^|]*\|([^|]*)\|", ln)
        if not m:
            continue
        segs = []
        for part in m.group(2).split("+"):
            r = re.match(r"^\s*(\d{1,2}:\d{2}(?:\.\d+)?)\s*[–—-]\s*(\d{1,2}:\d{2}(?:\.\d+)?)\s*$", part)
            if r:
                a, b = clock(r.group(1)), clock(r.group(2))
                if a is not None and b is not None and b > a:
                    segs.append([round(a, 3), round(b, 3)])
        if segs:
            out[m.group(1)] = segs
    return out


def source_name(text):
    """'# PICKS: 多元副业复盘_final.mp4 → 4 条小红书切片' -> '多元副业复盘_final.mp4'."""
    m = re.search(r"^#\s*PICKS:?\s*(\S+\.(?:mp4|mov|m4v|mkv|webm))", text or "", re.M | re.I)
    return m.group(1) if m else None


def find_source(d, name, depth=2):
    """The source recording named in PICKS.md, inside the work folder or next to it (None when it is not there)."""
    if not name:
        return None
    roots = [d, os.path.dirname(d)]
    for root in roots:
        base = root.rstrip(os.sep).count(os.sep)
        for dp, dns, fns in os.walk(root):
            if dp.count(os.sep) - base >= depth:
                dns[:] = []
            dns[:] = [x for x in dns if not x.startswith(".") and x not in ("node_modules", "renders")]
            if name in fns:
                return os.path.join(dp, name)
    return None


def to_clip_time(spans, t, tol=0.6):
    """Source seconds -> seconds in the finished clip, through the clip's source spans (None: not in the clip)."""
    if t is None or not spans:
        return None
    off = 0.0
    for a, b in spans:
        if a - tol <= t <= b + tol:
            return round(off + min(max(t, a), b) - a, 2)
        off += b - a
    return None


def _norm(s):
    return re.sub(r"[\s，。、！？,.!?;；:：「」“”\"'（）()\-—…]+", "", s or "")


def find_words(words, needle):
    """Start time of ``needle`` in the clip's words (punctuation / spaces ignored), or None."""
    n = _norm(needle)
    if not n or not words:
        return None
    text, starts = "", []
    for w in words:
        piece = _norm(w.get("w") or "")
        starts += [w["t"]] * len(piece)
        text += piece
    i = text.find(n)
    if i < 0 and len(n) > 4:
        i = text.find(n[:4])
    return round(starts[i], 2) if 0 <= i < len(starts) else None


def speech_secs(quote):
    """How long saying ``quote`` takes, roughly (Chinese ~4.5 characters / s, other words ~2.6 / s)."""
    cjk = len(CJK.findall(quote or ""))
    latin = len(re.findall(r"[A-Za-z]+", quote or ""))
    return round(cjk / 4.5 + latin / 2.6, 1)


def _m(code, en, zh, **params):
    return dict(code=code, params=params, message=en, message_zh=zh)


def clean_text(s):
    """An agent note without file paths, code spans and raw timestamps (the fallback label)."""
    s = re.sub(r"`[^`]*`", "", s or "")
    s = re.sub(r"\b[\w./-]+\.(?:py|json|md|yaml|mp4|mov|txt)\b", "", s)
    s = re.sub(r"\(\s*\d{1,2}:\d{2}(?:\.\d+)?\s*[–—-]\s*\d{1,2}:\d{2}(?:\.\d+)?\s*\)", "", s)
    s = re.sub(r"\b\d+\.\d{2,}\b", "", s)
    s = re.sub(r"\b(in|to|at)\s*(?=[.,;]|$)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,;.")
    return s


def humanize(conf, spans, clip_for=None, words_for=None, source=None, idx=0):
    """One confirm bullet {clip, text} -> {id, clip, text, checked, kind, label, detail, quote, secs, approx, at, before,
    choices, choice}. ``clip_for(letter)`` -> the desk clip (id, title, files...) or None, ``words_for(letter)`` -> the
    clip's word timings, ``source`` = the source recording path (before / after preview) or None."""
    text = conf.get("text") or ""
    letter = conf.get("clip")
    sp = spans.get(letter) or []
    quotes = QUOTE.findall(text)
    quote = quotes[0] if quotes else None
    words = (words_for(letter) if words_for and letter else None) or []
    stamps = [(clock(a), clock(b)) for a, b in re.findall(
        r"\(\s*(\d{1,2}:\d{2}(?:\.\d+)?)\s*[–—-]\s*(\d{1,2}:\d{2}(?:\.\d+)?)\s*\)", text)]
    stamped = sum(b - a for a, b in stamps if a is not None and b is not None and b > a)
    # quotes with a timestamp right after them are measured, the others estimated
    est = 0.0
    for q in quotes:
        after = text[text.find(q) + len(q):][:24]
        if not re.match(r"^[」”\"]?\s*\(\s*\d{1,2}:\d{2}", after):
            est += speech_secs(q)
    secs = round(stamped + est, 1) if (stamped or est) else None
    approx = bool(est)
    kind, label, detail, choices, choice = "check", None, None, None, None
    at, src_at = None, None
    low = text.lower()
    if re.search(r"starts at .+ instead of", low) or re.search(r"开头(改|从).+(而不是|代替)", text):
        kind = "opener"
        label = _m("inbox.opt.opener", "Which opening?", "用哪个开头？")
        m = re.search(r"clip is\s*(\d+(?:\.\d+)?)\s*s", low)
        strong = float(m.group(1)) if m else None
        m = re.search(r"(\d+(?:\.\d+)?)\s*s\s*floor|under the\s*(\d+(?:\.\d+)?)\s*s", low)
        floor = float(m.group(1) or m.group(2)) if m else None
        m = re.search(r"start to\s*(\d+(?:\.\d+)?)", low)
        new_start = float(m.group(1)) if m else None
        cur = sp[0][0] if sp else None
        soft = round(strong + (cur - new_start), 1) if strong and cur is not None and new_start is not None and \
            0 < cur - new_start < 60 else None
        under = bool(strong and floor and strong < floor)
        if under:
            detail = _m("inbox.opt.openerWhy", f"The stronger opener makes the clip {strong:g} s — under the "
                        f"{floor:g} s minimum.", f"更强的开头让片子只有 {strong:g} 秒，低于 {floor:g} 秒的下限。",
                        secs=strong, floor=floor)
        choices = [dict(id="softer", label=_m("inbox.choice.softer", "Keep softer opener", "保留柔和开头"),
                        secs=soft, recommended=under),
                   dict(id="stronger", label=_m("inbox.choice.stronger", "Use stronger opener", "用更强的开头"),
                        secs=strong, recommended=not under)]
        choice = "softer" if under else "stronger"
        secs = None
        at = 0.0
        src_at = new_start
    elif "hedge" in low or "保险" in text or "铺垫" in text:
        kind = "hedge"
        label = _m("inbox.opt.dropHedge", "Drops a hedge", "删掉一句铺垫")
    elif "skipping" in low or "跳过" in text:
        kind = "aside"
        label = _m("inbox.opt.skipAside", "Skips an aside", "跳过一段题外话")
    elif re.search(r"\bdrops?\b|删掉|去掉", text, re.I):
        kind = "filler"
        label = _m("inbox.opt.dropLine", "Drops a filler line", "删掉一句口头禅")
    else:
        detail = _m("inbox.opt.note", clean_text(text), clean_text(text), text=clean_text(text))
        label = _m("inbox.opt.check", "Check this edit", "看一下这处剪辑")
    if at is None:
        m = re.search(r"\bbefore\s+(\d{1,2}:\d{2}(?:\.\d+)?)", text)
        before_t = clock(m.group(1)) if m else None
        m = re.search(r"\bbefore\s+([^\s,.;，。「」(]{2,30})", text)
        anchor = m.group(1) if m and not re.match(r"^\d", m.group(1)) else None
        m = re.search(r"starts at\s+([^\s,.;，。「」(]{2,30})", text)
        if m and not anchor:
            at = 0.0
        if anchor:
            at = find_words(words, anchor)
        if at is None and stamps and stamps[0][1] is not None:
            at = to_clip_time(sp, stamps[0][1])
            src_at = stamps[0][0]
        if at is None and before_t is not None:
            at = to_clip_time(sp, before_t)
            src_at = before_t
        if at is None and quote:
            at = find_words(words, quote)
    clip = clip_for(letter) if clip_for and letter else None
    out = dict(id=f"o{idx}", clip=letter, clip_id=(clip or {}).get("id"), clip_title=(clip or {}).get("title"),
               text=text, checked=True, kind=kind, label=label, detail=detail, quote=quote,
               secs=(-secs if secs else None), approx=approx, at=at, before=None, choices=choices, choice=choice)
    if source and src_at is not None:
        out["before"] = dict(file=source, at=round(max(0.0, src_at), 2))
    return out


def _around(before, word, after, n=24):
    """"…the words before ⟨word⟩ the words after…": the sentence a cut sits in (CJK runs together, Latin gets spaces)."""
    b, w, a = clean_text(str(before or "")).strip()[-n:], clean_text(str(word or "")).strip(), clean_text(str(after or "")).strip()[:n]
    sp = lambda x, y: " " if x and y and re.match(r"[A-Za-z0-9,.!?]", x[-1]) and re.match(r"[A-Za-z0-9]", y[0]) else ""  # noqa: E731
    return f"{'…' if b else ''}{b}{sp(b, w)}⟨{w}⟩{sp(w, a)}{a}{'…' if a else ''}"


def engine_option(o, default=None, idx=0):
    """An engine checkpoint option -> the inbox option shape (label from its labels / label / text). A cut the engine
    asks about (filler / repeat / pause with ``t0``-``t1`` and its ``before`` / ``after`` words) reads "Cut “So”" with
    the sentence around it, never a bare checkbox labelled with the filler word itself."""
    labels = o.get("labels") if isinstance(o.get("labels"), dict) else {}
    if not labels and not o.get("label") and o.get("t0") is not None and o.get("t1") is not None:
        word = clean_text(str(o.get("text") or "")).strip()
        secs = round(max(0.0, float(o["t1"]) - float(o["t0"])), 1)
        label = (_m("inbox.opt.cutWord", f"Cut “{word}”", f"删掉「{word}」", word=word) if word else
                 _m("inbox.opt.cutPause", f"Cut a {secs:g} s pause", f"删掉 {secs:g} 秒停顿", secs=secs))
        has_ctx = bool(str(o.get("before") or "").strip() or str(o.get("after") or "").strip())
        return dict(id=str(o.get("id") if o.get("id") is not None else idx), clip=o.get("item"), clip_id=None,
                    text=word, checked=o.get("checked", True) is not False, kind="filler", label=label,
                    detail=None, quote=_around(o.get("before"), word, o.get("after")) if has_ctx else None,
                    secs=-secs if secs else None, approx=False, at=None, before=None, choices=None, choice=None,
                    recommended=default is not None and str(o.get("id")) == str(default))
    en = labels.get("en") or o.get("label") or o.get("text") or str(o.get("id") or idx)
    zh = labels.get("zh") or en
    return dict(id=str(o.get("id") if o.get("id") is not None else idx), clip=o.get("item"), clip_id=None,
                text=en, checked=o.get("checked", True) is not False, kind="choice",
                label=_m("inbox.opt.engine", clean_text(str(en)), clean_text(str(zh)), text=clean_text(str(en))),
                detail=None, quote=o.get("quote"), secs=None, approx=False, at=o.get("at"), before=None, choices=None,
                choice=None, recommended=default is not None and str(o.get("id")) == str(default))


def spend_params(e):
    """A budget approval entry -> {amount, currency, what} for 'OK to spend ¥18 on AI shots?'."""
    agg = e.get("aggregate") or {}
    est = e.get("estimate") or {}
    amount, cur = None, None
    for src in (agg, est, e):
        if not isinstance(src, dict):
            continue
        for k, c in (("cost_cny", "CNY"), ("cny", "CNY"), ("cost_usd", "USD"), ("usd", "USD"), ("cost", None),
                     ("total", None), ("amount", None)):
            v = src.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                amount, cur = v, c or src.get("currency") or "USD"
                break
        if amount is not None:
            break
    n = est.get("n") or est.get("shots") or e.get("n_options") or len(e.get("items") or []) or None
    return dict(amount=round(float(amount), 2) if amount is not None else None, currency=cur or "USD", n=n or 0)
