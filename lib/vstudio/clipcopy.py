"""Copy drafted from one clip's own words: the post title, highlighted keywords, progress-bar chapters and
记笔记 panels (her talking-head look). The creator edits any of it in review.

    from vstudio import clipcopy
    d = clipcopy.draft(sents, platforms=["xiaohongshu:full"], glossary_terms=["亚麻", "onboarding"])
    d["title"]      # within the tightest title limit of the platforms (publish.fit_title, shortening reported)
    d["keywords"]   # terms said in the clip, shown in the accent colour in captions and panels
    d["chapters"]   # [(t0, t1, label)]: 2-6 character labels for the progress bar
    d["panels"]     # [(t0, t1, title, [(t, bullet)])]: one 记笔记 card per section, bullets as she says them
    d["source"]     # "llm:<provider>" | "transcript"; d["notes"]: what was dropped / shortened / not drafted

sents: [{t, te, text}] on any timeline (``sentences_from_subs`` for a talkinghead segs.json, ``sentences_from_cues``
for burned caption chunks, ``sentences_from_words`` for an ASR transcript); every time in the draft is on it.

Two real paths, chosen by the ``copy`` route of vstudio.llm (persona / desk llm settings):
  * a text model is routed: it writes the title, keywords and the sections (label, card title, 2-3 bullets anchored
    to sentence numbers); everything is validated here (anchors in range and in order, card text lengths, keywords
    actually said) and the title goes through ``publish.fit_title``.
  * no model (route ``none``): the title is the most title-like spoken clause (vstudio.batch.segplan rules), the
    keywords are the glossary terms said in the clip plus recurring latin terms, and no cards are drafted - spoken
    fragments make poor note cards - which ``notes`` says.
A model that fails raises (``llm.AllProvidersFailed`` / the provider's error): the caller reports it.
"""
import re

PANEL_EVERY = 40.0          # seconds of speech per 记笔记 card ("notes 多一点" / "多加 panel")
BULLET_MAX = 14             # characters per panel bullet (the compositor's card width)
CARD_TITLE_MAX = 8
LABEL_MAX = 6               # progress-bar chapter label
HOLD = 6.0                  # a card stays this long after its last bullet is said (within its section)

SCHEMA = {"type": "object", "required": ["title", "keywords", "sections"], "properties": {
    "title": {"type": "string"},
    "keywords": {"type": "array", "items": {"type": "string"}},
    "sections": {"type": "array", "items": {"type": "object", "required": ["from", "label", "title", "bullets"],
                                            "properties": {
        "from": {"type": "integer"}, "label": {"type": "string"}, "title": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "object", "required": ["at", "text"], "properties": {
            "at": {"type": "integer"}, "text": {"type": "string"}}}}}}}}}


# ------------------------------------------------------------------------------------------------ sentences
def sentences_from_words(transcript):
    """ASR transcript (whisper json / sidecar) -> sentences [{t, te, text}]."""
    from vstudio.batch.segplan import sentences_of
    from vstudio.cleanup import load_words
    W = load_words(transcript)
    return [dict(t=s["t"], te=s["te"], text=s["text"]) for s in sentences_of(W, max_len=12.0)] if W else []


def sentences_from_subs(subs):
    """talkinghead segs.json ``subs`` [{sid, text, start, end}] -> sentences [{t, te, text, sid}] (body time)."""
    return [dict(t=float(s["start"]), te=float(s["end"]), text=_clean(s.get("text")), sid=s.get("sid"))
            for s in subs or [] if _clean(s.get("text"))]


def sentences_from_cues(cues, max_gap=0.15, max_chars=36):
    """Burned caption chunks [{start, end, text}] -> sentences: chunks joined while the pause between them is
    under ``max_gap`` s and the sentence stays under ``max_chars`` (captions carry no punctuation)."""
    out = []
    for c in cues or []:
        t = _clean(c.get("text"))
        if not t:
            continue
        a, b = float(c.get("start", 0)), float(c.get("end", 0))
        if out and a - out[-1]["te"] <= max_gap and len(out[-1]["text"]) + len(t) <= max_chars \
                and not re.search(r"[。！？!?]$", out[-1]["text"]):
            sep = " " if re.search(r"[A-Za-z0-9]$", out[-1]["text"]) and re.match(r"[A-Za-z0-9]", t) else ""
            out[-1].update(te=b, text=out[-1]["text"] + sep + t)
        else:
            out.append(dict(t=a, te=b, text=t))
    return out


def _clean(t):
    return re.sub(r"\s+", " ", re.sub(r"[【】|]", "", str(t or ""))).strip()


def _norm(t):
    return re.sub(r"\s+", "", str(t or "")).lower()


def _clip(text, n):
    """``text`` cut to ``n`` characters at a clause end when there is one (never mid latin word)."""
    t = _clean(text).strip("，,。.；;：:、 ")
    if len(t) <= n:
        return t, False
    cut = t[:n]
    m = list(re.finditer(r"[，,。.；;：:、]", cut))
    if m and m[-1].start() >= n // 2:
        cut = cut[:m[-1].start()]
    elif re.match(r"[A-Za-z0-9]", t[n:n + 1]) and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip("，,。.；;：:、 "), True


# ------------------------------------------------------------------------------------------------ model path
def _prompt(sents, limit, pl, lang, n_sec):
    from vstudio import publish
    count = ("CJK characters count 1, Latin letters / digits / spaces 0.5" if pl == "xiaohongshu" else "characters")
    zh = lang != "en"
    rules = " ".join(publish._p("voice.rules", []) or [])
    system = (
        "You prepare the on-screen notes for one talking-head video the creator recorded (her own words, "
        f"{'Chinese' if zh else 'English'}). You get its sentences numbered [i] with mm:ss.\n"
        f"- title: the post title, <= {limit:g} ({count}); concrete and specific to what she says, no clickbait, "
        "no 鸡汤 / motivational slogan, no emoji, no hashtags.\n"
        "- keywords: 3-8 terms she actually says (names, domain terms, the key idea words), written exactly as in "
        "the text; they are highlighted in the captions.\n"
        f"- sections: {n_sec} sections covering the whole video in order. from = the first sentence number of the "
        f"section. label = a 2-{LABEL_MAX} character summary of the section for the progress bar (a topic, not a "
        f"fragment of a sentence). title = the note card's heading (<= {CARD_TITLE_MAX} characters). bullets = 2-3 "
        f"takeaways of that section, each <= {BULLET_MAX} characters, rewritten short and clean but faithful to "
        "what she says (no new facts), with at = the sentence number where she says it (inside the section, in "
        "order).\n" + (f"Voice rules: {rules}\n" if rules else "") + "Answer with JSON only.")
    lines = [f"[{k}] {int(s['t']) // 60:02d}:{int(s['t']) % 60:02d} {s['text']}" for k, s in enumerate(sents)]
    return system, "SENTENCES:\n" + "\n".join(lines)[:24000]


def _from_model(j, sents, notes):
    n = len(sents)
    text = _norm(" ".join(s["text"] for s in sents))
    kws = []
    for k in j.get("keywords") or []:
        k = _clean(k)
        if len(k) >= 2 and _norm(k) in text and k not in kws:
            kws.append(k)
        elif k:
            notes.append(f"keyword {k!r} dropped: not said in the clip")
    secs = []
    for s in j.get("sections") or []:
        try:
            a = int(s.get("from"))
        except (TypeError, ValueError):
            continue
        if 0 <= a < n and (not secs or a > secs[-1]["from"]):
            secs.append(dict(s, **{"from": a}))
    if not secs:
        return kws, [], []
    secs[0]["from"] = 0
    chapters, panels = [], []
    for i, s in enumerate(secs):
        a = s["from"]
        b = secs[i + 1]["from"] - 1 if i + 1 < len(secs) else n - 1
        label, cut = _clip(s.get("label"), LABEL_MAX)
        if cut:
            notes.append(f"chapter label shortened to {label!r}")
        t0 = 0.0 if i == 0 else sents[a]["t"]
        t1 = sents[secs[i + 1]["from"]]["t"] if i + 1 < len(secs) else sents[b]["te"]
        chapters.append((round(t0, 3), round(t1, 3), label or f"{i + 1:02d}"))
        rows, last = [], a - 1
        for bl in s.get("bullets") or []:
            try:
                at = int(bl.get("at"))
            except (TypeError, ValueError):
                continue
            at = min(max(at, a, last), b)
            txt, cut = _clip(bl.get("text"), BULLET_MAX)
            if cut:
                notes.append(f"bullet shortened to {txt!r}")
            if len(txt) >= 2:
                rows.append((at, txt))
                last = at
        if rows:
            title, cut = _clip(s.get("title") or label, CARD_TITLE_MAX)
            p0 = sents[rows[0][0]]["t"]
            p1 = min(sents[b]["te"], sents[rows[-1][0]]["te"] + HOLD)
            panels.append((round(p0, 3), round(max(p1, p0 + 2.0), 3), title or label,
                           [(round(sents[k]["t"], 3), x) for k, x in rows[:3]]))
    return kws, chapters, panels


# ------------------------------------------------------------------------------------------------ no-model path
def _spoken_title(sents, limit, pl, lang):
    from vstudio.batch.segplan import pick_title, shorten, term_stats
    lead = re.compile(r"^(反正|就是|然后|所以|其实|比如说?|像是?|那么?|因为|但是|而且|如果说?|我觉得|我就|对|嗯|呃|啊|好)+")
    ss = [dict(s, text=lead.sub("", s["text"]).strip() or s["text"], k=k) for k, s in enumerate(sents)]
    for k, s in enumerate(ss):
        s["gap_before"] = s["t"] - ss[k - 1]["te"] if k else 9.0
    idf, per = term_stats(ss)
    t = pick_title(ss, per, idf, list(range(len(ss))), limit, pl, lang) if idf else ""
    return t or shorten(max(ss[:6], key=lambda s: len(s["text"]))["text"], limit, pl)


def _said_terms(sents, glossary_terms):
    text = " ".join(s["text"] for s in sents)
    out = [t for t in glossary_terms or [] if len(t) >= 2 and t.upper() != "OK" and _norm(t) in _norm(text)]
    lat = {}
    for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9+#.-]{1,}\b", text):
        w = m.group(0).strip(".")
        if len(w) >= 2 and w.lower() not in ("ok", "the", "and", "a", "i"):
            lat[w] = lat.get(w, 0) + 1
    out += [w for w, c in sorted(lat.items(), key=lambda x: -x[1]) if c >= 2 or w.isupper()]
    seen, res = set(), []
    for t in out:
        if _norm(t) not in seen:
            seen.add(_norm(t))
            res.append(t)
    return res[:8]


# ------------------------------------------------------------------------------------------------ draft
def draft(sents, platforms=None, glossary_terms=(), provider="auto", complete=None, every=PANEL_EVERY, lang=None):
    """-> {title, title_note, title_platform, keywords, chapters, panels, source, notes}. See the module doc."""
    from vstudio import llm, publish
    sents = [dict(s, text=_clean(s.get("text"))) for s in sents if _clean(s.get("text"))]
    out = dict(title="", title_note=None, title_platform=None, keywords=[], chapters=[], panels=[],
               source=None, notes=[])
    if not sents:
        out["notes"].append("no speech: nothing drafted")
        return out
    lang = lang or ("en" if publish.detect_lang([s["text"] for s in sents]) == "en" else "zh")
    plats = list(platforms or ["xiaohongshu"])
    limit, pl = publish.title_limit(plats)
    prov = None if complete else llm.route("copy", None if provider in (None, "auto") else provider).provider
    if complete or prov != "none":
        total = sents[-1]["te"] - sents[0]["t"]
        n_sec = max(2, min(5, int(round(total / every)))) if total >= 1.5 * every else 1
        system, prompt = _prompt(sents, limit, pl, lang, n_sec)
        r = (complete or llm.complete)("copy", system, prompt, schema=SCHEMA,
                                       provider=None if provider in (None, "auto") else provider)
        j = (r or {}).get("json")
        if not isinstance(j, dict):
            raise ValueError("copy model returned no JSON for the clip notes")
        out["keywords"], out["chapters"], out["panels"] = _from_model(j, sents, out["notes"])
        title = _clean(j.get("title"))
        out["source"] = f"llm:{(r or {}).get('provider') or prov or 'custom'}"
        for t in _said_terms(sents, glossary_terms):          # glossary terms the model left out
            if len(out["keywords"]) < 8 and _norm(t) not in {_norm(k) for k in out["keywords"]}:
                out["keywords"].append(t)
    else:
        title = _spoken_title(sents, limit, pl, lang)
        out["keywords"] = _said_terms(sents, glossary_terms)
        out["source"] = "transcript"
        out["notes"].append("no text model routed (vstudio.llm task 'copy'): 记笔记 cards and chapters not drafted; "
                            "the title is a spoken clause")
    out["title"], out["title_note"] = publish.fit_title_all(title, plats)
    out["title_platform"] = pl
    if out["title_note"]:
        out["notes"].append(out["title_note"])
    return out
