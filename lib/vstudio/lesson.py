"""Lesson -> knowledge-point clips: segment a class recording by teaching point, plus a recap and study notes.

    from vstudio import lesson as L
    sents = L.sentences(transcript)                                  # whole sentences with times
    plan = L.plan_points(sents, lang="en", count=6)                  # {points: [...], recap: {...}, lang}
    L.write_notes(plan, "out/notes.md", title="Small talk")         # + notes.pdf (L.notes_pdf)

    python -m vstudio.lesson plan  --source lesson.mp4 [--transcript t.json] [--count 6] [--provider none|auto]
                                   [--min 20 --max 90] [--out work/points.json]
    python -m vstudio.lesson notes work/points.json --out out/notes.md [--pdf out/notes.pdf] [--title ...]
    python -m vstudio.lesson render work/points.json --out out [--platforms ...] (see ``vstudio.clipkit``)

A *point* is one self-contained teaching moment, typed by what the teacher is doing:

  phrase      "today's phrase / expression / idiom / you can say ..."          card: Today's phrase / 今日短语
  vocab       "the word X / X means ... / pronounced"                          card: Word of the day / 今日词汇
  concept     a rule / grammar point / difference / "remember that"            card: Key point / 知识点
  correction  "a common mistake / don't say X, say Y / not X but Y"            card: Common mistake / 易错点
  example     example sentences (attached to the point they illustrate; a point of its own only when nothing
              else is around)                                                   card: Example / 例句

Each point: ``{id, kind, start, end, title, phrase, gloss, terms [{term, gloss, t}], summary, examples [text],
anchor [start, end], score}`` in source seconds on sentence edges. The recap is ``{points: [ids], parts: [{id,
title, kind, range}]}``: per point its anchor sentence (the line that names the phrase / rule), 2-7 s each, played
after a mini card.

Planner: ``provider none`` = the rules (markers per kind in English and Chinese, quoted / named phrases, a window
grown from each anchor over its explanation and examples until the next point or a long pause, inside
[min, max]); ``auto`` = the model routed for task ``lesson_plan`` (the rules when no model is configured - the
plan's ``planner`` says which ran); the model gets numbered sentences and returns sentence ranges + kinds +
titles + glosses (edges always sentence edges). A model that fails is an error, not a silent switch to rules.
"""
import argparse
import json
import os
import re
import sys

KINDS = ("phrase", "vocab", "concept", "correction", "example")
LABELS = {
    "phrase": dict(en="Today's phrase", zh="今日短语"),
    "vocab": dict(en="Word of the day", zh="今日词汇"),
    "concept": dict(en="Key point", zh="知识点"),
    "correction": dict(en="Common mistake", zh="易错点"),
    "example": dict(en="Example", zh="例句"),
    "recap": dict(en="Lesson recap", zh="本课回顾"),
    "term": dict(en="Key term", zh="关键词"),
}

_EN = {
    "phrase": r"\b(?:phrase|expression|idiom|phrasal verb|collocation|you can say|you could say|we say|people say|"
              r"native speakers say|a natural way to say|another way to say)\b",
    "vocab": r"\b(?:the word|this word|vocabulary|means|meaning|definition|is pronounced|pronounce|spell(?:ed|ing)?|"
             r"synonym|opposite)\b",
    "concept": r"\b(?:rule|grammar|tense|the difference between|remember(?: that)?|key point|important(?:ly)?|"
               r"we use|you use|is used (?:to|for|when)|structure|pattern|the reason)\b",
    "correction": r"\b(?:mistake|wrong|incorrect|not correct|don'?t say|do not say|instead of|should be|common error|"
                  r"actually it'?s|we don'?t say|avoid)\b",
    "example": r"\b(?:for example|for instance|e\.g\.|example|let'?s say|such as|imagine|like this)\b",
}
_ZH = {
    "phrase": r"短语|表达|说法|句型|习语|俗语|固定搭配|地道的说法|可以说|会说",
    "vocab": r"单词|这个词|生词|词汇|意思是|的意思|词义|发音|读作|拼写|同义词|反义词",
    "concept": r"语法|规则|时态|区别|重点|记住|概念|核心|原理|用法|结构|要点",
    "correction": r"错误|错了|不对|不要说|别说|应该说|易错|常见错误|而不是|纠正",
    "example": r"比如|例如|举个例子|例句|打个比方|像这样",
}
BACKREF_EN = re.compile(r"^(?:and|so|but|also|then|because|which|that|it|this|they|as i said)\b", re.I)
BACKREF_ZH = re.compile(r"^(?:然后|所以|但是|而且|因为|那么|就是|这个|那个|它|刚才|刚刚|另外)")
QUOTE = re.compile(r"[\"“”‘’'「『]([^\"“”‘’'「」『』]{2,48})[\"“”’'」』]")
NAMED_EN = re.compile(r"\b(?:the (?:phrase|expression|idiom|word|phrasal verb)|you can say|you could say|we say|"
                      r"people say|say)\s+[\"“']?([A-Za-z][A-Za-z'’ -]{1,40}?)[\"”']?"
                      r"(?=\s*(?:[,.!?;:]|$)|\s+(?:which|that|means|is|to|when|instead|in|and|for|if)\b)", re.I)
MEANS_EN = re.compile(r"\b([A-Za-z][A-Za-z'’ -]{1,32}?)\s+means\s+([^.!?]{3,60})", re.I)
DONT_SAY = re.compile(r"\b(?:don'?t|do not|never) say\s+[\"“']?([A-Za-z][A-Za-z'’ -]{1,30}?)[\"”']?[,.;]?\s+"
                      r"(?:say|it'?s|use)\s+[\"“']?([A-Za-z][A-Za-z'’ -]{1,30}?)[\"”']?(?=[,.!?;]|$|\s)", re.I)
NAMED_ZH = re.compile(r"(?:这个词|这个短语|这个表达|这个说法|短语|单词|表达)(?:是|叫|就是)?[：:]?\s*([A-Za-z][A-Za-z'’ -]{1,40}|[一-鿿]{2,10})")
MEANS_ZH = re.compile(r"([A-Za-z][A-Za-z'’ -]{1,32}|[一-鿿]{2,8})\s*的?意思是\s*([^，。！？]{2,30})")
PRONOUNS = {"it", "this", "that", "which", "what", "he", "she", "they", "i", "you", "we", "there", "here", "so",
            "and", "but", "which one", "this one", "that one"}
GLOSS_HINT = re.compile(r"[（(]([^()（）]{1,30})[)）]")


# --------------------------------------------------------------------------- transcript
def sentences(transcript, max_len=25.0):
    """Any transcript (``vstudio.asr`` dict, whisper JSON, a path) -> whole sentences [{k, t, te, text, i0, i1,
    gap_before, gap_after}] (``batch.segplan.sentences_of`` on ``cleanup.load_words``)."""
    from vstudio.batch.segplan import sentences_of
    from vstudio.cleanup import load_words
    return sentences_of(load_words(transcript), max_len=max_len)


def lang_of(sents):
    s = "".join(x["text"] for x in sents[:200])
    cjk = len(re.findall(r"[一-鿿]", s))
    return "zh" if cjk > 0.25 * max(1, len(re.sub(r"[\s\W]", "", s))) else "en"


# --------------------------------------------------------------------------- terms
def _clean_term(t):
    t = re.sub(r"\s+", " ", (t or "").strip(" \"'“”‘’「」,.;:!?"))
    if not t or t.lower() in PRONOUNS or len(t) > 48:
        return None
    if re.match(r"[A-Za-z]", t) and len(t.split()) > 7:
        return None
    return t


def extract_terms(text, lang="en"):
    """Named phrases / words in one sentence -> [{term, gloss, kind}] (quoted, "the phrase X", "X means Y",
    "don't say X, say Y")."""
    out = []
    seen = set()

    def add(term, gloss=None, kind=None):
        term = _clean_term(term)
        if not term or term.lower() in seen:
            return
        seen.add(term.lower())
        out.append(dict(term=term, gloss=(gloss or "").strip(" ,.;") or None, kind=kind))
    for m in DONT_SAY.finditer(text):
        add(m.group(2), None, "correction")
        seen.add(m.group(1).strip().lower())
    for m in QUOTE.finditer(text):
        add(m.group(1))
    if lang == "zh":
        for m in MEANS_ZH.finditer(text):
            add(m.group(1), m.group(2), "vocab")
        for m in NAMED_ZH.finditer(text):
            add(m.group(1))
    else:
        for m in MEANS_EN.finditer(text):
            if m.group(1).strip().lower() not in PRONOUNS and len(m.group(1).split()) <= 5:
                add(m.group(1), m.group(2), "vocab")
        for m in NAMED_EN.finditer(text):
            add(m.group(1))
    g = GLOSS_HINT.search(text)
    if g and out and not out[0]["gloss"]:
        out[0]["gloss"] = g.group(1)
    return out


def kind_scores(text, lang="en"):
    """{kind: score} from the marker table of the language (plus English markers in a Chinese lesson about
    English: teachers mix)."""
    tables = [_ZH, _EN] if lang == "zh" else [_EN]
    sc = {}
    for tb in tables:
        for k, rx in tb.items():
            n = len(re.findall(rx, text, re.I))
            if n:
                sc[k] = sc.get(k, 0.0) + min(2, n)
    return sc


def annotate(sents, lang="en"):
    """Adds ``kinds`` {kind: score}, ``terms`` and ``anchor`` (strength as a point start) to every sentence."""
    for s in sents:
        s["kinds"] = kind_scores(s["text"], lang)
        s["terms"] = extract_terms(s["text"], lang)
        strong = {k: v for k, v in s["kinds"].items() if k != "example"}
        a = 1.2 * sum(strong.values()) + 1.5 * len(s["terms"])
        if any(t.get("kind") == "correction" for t in s["terms"]):
            a += 1.0
        if s["terms"] and strong:
            a += 1.0
        s["anchor"] = round(a, 2)
    return sents


def _kind_of(sc, terms):
    if any(t.get("kind") == "correction" for t in terms) or sc.get("correction", 0) >= 1:
        return "correction"
    strong = {k: v for k, v in sc.items() if k in ("phrase", "vocab", "concept")}
    if terms and not strong:
        return "phrase"
    if strong:
        best = max(strong, key=lambda k: (strong[k], ("vocab", "phrase", "concept").index(k)))
        if best == "concept" and terms and strong.get("phrase"):
            return "phrase"
        return best
    return "example" if sc.get("example") else "concept"


# --------------------------------------------------------------------------- planning (rules)
def _short(text, lang, limit=None):
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^(?:so|and|okay|ok|well|now|alright|right|嗯|好|那么|所以|然后)[,，]?\s*", "", t, flags=re.I)
    if lang == "zh":
        limit = limit or 18
        t = re.split(r"[，。！？；]", t)[0] if len(t) > limit else t
        return t[:limit]
    limit = limit or 9
    words = re.sub(r"[.!?]+$", "", t).split()
    return " ".join(words[:limit]) + ("…" if len(words) > limit else "")


def _title(kind, terms, anchor_text, lang):
    corr = next((t for t in terms if t.get("kind") == "correction"), None)
    if corr:
        m = DONT_SAY.search(anchor_text or "")
        if m:
            return f"{m.group(1).strip()} → {m.group(2).strip()}"
    if terms and kind in ("phrase", "vocab", "correction"):
        return terms[0]["term"]
    return _short(anchor_text, lang)


def _grow(sents, k, used, min_s, max_s, target, long_pause=2.5):
    """Window [a, b] of sentence indexes around anchor k: back over one connective opener, forward over the
    explanation / examples until the next strong anchor (a different term), a long pause, or max_s."""
    a = b = k
    n = len(sents)
    if a > 0 and (a - 1) not in used and sents[a]["gap_before"] < 1.0 and \
            (BACKREF_EN.match(sents[a]["text"]) or BACKREF_ZH.match(sents[a]["text"])):
        a -= 1
    own = {t["term"].lower() for t in sents[k]["terms"]}
    dur = lambda x, y: sents[y]["te"] - sents[x]["t"]  # noqa: E731
    while b + 1 < n and (b + 1) not in used:
        nx = sents[b + 1]
        if nx["gap_before"] > long_pause and dur(a, b) >= min_s * 0.6:
            break
        if dur(a, b + 1) > max_s:
            break
        other = {t["term"].lower() for t in nx["terms"]} - own
        if nx["anchor"] >= 2.4 and other and dur(a, b) >= min_s * 0.6:
            break
        b += 1
        if dur(a, b) >= target and (nx["gap_after"] >= 0.6 or re.search(r"[.!?。！？]$", nx["text"])):
            break
    while dur(a, b) < min_s and a > 0 and (a - 1) not in used and sents[a]["gap_before"] < long_pause and \
            dur(a - 1, b) <= max_s:
        a -= 1
    return a, b


def _point(sents, a, b, k, lang, kind=None, title=None, gloss=None, extra=None):
    win = sents[a:b + 1]
    terms, seen = [], {}
    for s in win:
        for t in s["terms"]:
            key = t["term"].lower()
            if key not in seen:
                seen[key] = dict(term=t["term"], gloss=t.get("gloss"), t=round(s["t"], 2))
                terms.append(seen[key])
            elif t.get("gloss") and not seen[key].get("gloss"):
                seen[key]["gloss"] = t["gloss"]
    anc = sents[k]
    sc = {}
    for s in win:
        for kk, v in s["kinds"].items():
            sc[kk] = sc.get(kk, 0) + v
    kind = kind or _kind_of(anc["kinds"] or sc, anc["terms"] or [dict(term=x["term"]) for x in terms[:1]])
    phrase = (anc["terms"][0]["term"] if anc["terms"] else (terms[0]["term"] if terms else None))
    if kind == "correction":
        corr = next((t for t in anc["terms"] if t.get("kind") == "correction"), None)
        phrase = corr["term"] if corr else phrase
    if kind in ("phrase", "vocab") and not phrase:
        kind = "concept"                                # a phrase card needs a phrase
    exs = [s["text"] for s in win if s["kinds"].get("example") or QUOTE.search(s["text"])][:2]
    p = dict(kind=kind, start=round(win[0]["t"], 2), end=round(win[-1]["te"], 2),
             title=title or _title(kind, anc["terms"] or terms, anc["text"], lang), phrase=phrase,
             gloss=gloss or next((t.get("gloss") for t in terms if phrase and t["term"].lower() == phrase.lower()
                                  and t.get("gloss")), None),
             terms=terms[:3], summary=anc["text"], examples=exs, anchor=[round(anc["t"], 2), round(anc["te"], 2)],
             sent=[a, b], score=round(sum(s["anchor"] for s in win) / max(1.0, (win[-1]["te"] - win[0]["t"]) / 30), 2))
    if extra:
        p.update({k2: v for k2, v in extra.items() if v is not None})
    return p


def rule_points(sents, lang="en", count=None, min_s=20.0, max_s=90.0, target=None):
    annotate(sents, lang)
    target = target or (min_s + max_s) / 2 * 0.8
    order = sorted((k for k, s in enumerate(sents) if s["anchor"] >= 1.2), key=lambda k: (-sents[k]["anchor"], k))
    used, pts = set(), []
    for k in order:
        if k in used:
            continue
        a, b = _grow(sents, k, used, min_s, max_s, target)
        if sents[b]["te"] - sents[a]["t"] < min_s * 0.6:
            continue
        used |= set(range(a, b + 1))
        pts.append(_point(sents, a, b, k, lang))
        if count and len(pts) >= count * 2:
            break
    pts.sort(key=lambda p: -p["score"])
    if count:
        pts = pts[:count]
    pts.sort(key=lambda p: p["start"])
    return pts


# --------------------------------------------------------------------------- planning (LLM)
SYSTEM = """You plan short teaching clips from a recorded lesson (a teacher / tutor / coach). The lesson is \
given as numbered sentences "[n] mm:ss text". Find up to {count} self-contained TEACHING POINTS, each one moment a \
learner can watch on its own: a phrase / expression (kind "phrase"), a word (kind "vocab"), a rule or concept \
(kind "concept"), a common mistake and its fix (kind "correction"). A point starts where the teacher introduces it \
(never mid-explanation, never on "and" / "so" / a back-reference) and ends after its explanation and examples. \
Each point lasts {min_s:.0f}-{max_s:.0f} seconds. Points never overlap. Skip roll call, small talk about \
logistics, and anything naming students.
For each point: "from" / "to" = sentence numbers (inclusive), "kind", "title" = the phrase / word itself or a \
short headline (<= 8 words, in the lesson's language), "phrase" = the exact target phrase as spoken (or null), \
"gloss" = its meaning in {gloss_lang} (<= 12 words / 16 characters), "terms" = up to 3 key terms \
[{{"term", "gloss"}}] (gloss in {gloss_lang}), "summary" = one sentence in the lesson's language.
Return JSON: {{"points": [{{"from": 0, "to": 5, "kind": "phrase", "title": "...", "phrase": "...", "gloss": "...", \
"terms": [], "summary": "..."}}]}}"""


def _fmt_t(t):
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def llm_points(sents, lang, count, min_s, max_s, gloss_lang="zh", provider=None, call=None, config=None):
    """-> (points, info). ``call``: fn(system, prompt) -> parsed JSON (tests)."""
    from vstudio.batch.segplan import _fit_range
    lines = "\n".join(f"[{k}] {_fmt_t(s['t'])} {s['text']}" for k, s in enumerate(sents))
    system = SYSTEM.format(count=count or 8, min_s=min_s, max_s=max_s,
                           gloss_lang="Chinese" if gloss_lang == "zh" else "English")
    info = dict(provider=None, error=None)
    if call is None:
        from vstudio import llm as LLM
        r = LLM.complete("lesson_plan", system, lines, schema=True, provider=provider, config=config,
                         temperature=0.2, max_tokens=12000, cli_timeout=240)
        js = r.get("json")
        info["provider"] = r.get("provider")
        if r.get("fallback"):
            info["fallback"] = r["fallback"]
    else:
        js = call(system, lines)
        info["provider"] = "call"
    rows = (js or {}).get("points") if isinstance(js, dict) else js
    annotate(sents, lang)
    pts, used = [], set()
    for r in rows or []:
        try:
            a, b = int(r["from"]), int(r["to"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= a <= b < len(sents)):
            continue
        a, b = _fit_range(sents, a, b, min_s, max_s)
        if used & set(range(a, b + 1)):
            continue
        used |= set(range(a, b + 1))
        kind = r.get("kind") if r.get("kind") in KINDS else None
        k = max(range(a, b + 1), key=lambda j: sents[j]["anchor"])
        if r.get("phrase"):
            ph = str(r["phrase"]).strip().lower()
            k = next((j for j in range(a, b + 1) if ph and ph in sents[j]["text"].lower()), k)
        p = _point(sents, a, b, k, lang, kind=kind, title=(r.get("title") or "").strip() or None,
                   gloss=(r.get("gloss") or "").strip() or None,
                   extra=dict(phrase=(r.get("phrase") or None), summary=(r.get("summary") or None)))
        terms = [dict(term=str(t.get("term")).strip(), gloss=(t.get("gloss") or None)) for t in r.get("terms") or []
                 if isinstance(t, dict) and t.get("term")]
        if terms:
            for t in terms:
                j = next((x for x in range(a, b + 1) if t["term"].lower() in sents[x]["text"].lower()), a)
                t["t"] = round(sents[j]["t"], 2)
            p["terms"] = terms[:3]
        pts.append(p)
    return sorted(pts, key=lambda p: p["start"]), info


# --------------------------------------------------------------------------- plan
def recap(points, sents=None, max_part=7.0):
    """The recap clip: per point (in lesson order) its anchor line, 2-``max_part`` s."""
    parts = []
    for p in sorted(points, key=lambda x: x["start"]):
        a, b = p["anchor"]
        if b - a > max_part:
            b = a + max_part
        if b - a < 1.0:
            continue
        parts.append(dict(id=p["id"], kind=p["kind"], title=p["title"], gloss=p.get("gloss"), range=[a, round(b, 2)]))
    return dict(points=[x["id"] for x in parts], parts=parts)


def planner_of(provider="auto", config=None):
    """Which planner a run uses: "rules" (provider none, or auto with no model routed for ``lesson_plan``) or the
    model provider. Said in the plan (``planner``) - a failing model is an error, never a silent switch."""
    if not provider or provider == "none":
        return "rules"
    from vstudio import llm as LLM
    if provider == "auto":
        return "rules" if LLM.route("lesson_plan", config=config).provider == "none" else "llm"
    return "llm"


def plan_points(sents, lang=None, count=None, min_s=20.0, max_s=90.0, provider="none", gloss_lang=None, call=None,
                config=None):
    """-> {lang, points [...], recap {...}, planner, info}. Point ids p01, p02 ... in lesson order. ``provider``
    none = the rules; auto / a provider = the model (``call`` for tests); a model error propagates."""
    lang = lang or lang_of(sents)
    gloss_lang = gloss_lang or ("zh" if lang == "en" else "en")
    planner = "llm" if call is not None else planner_of(provider, config)
    info = dict(planner=planner)
    if planner == "llm" and sents:
        pts, li = llm_points(sents, lang, count, min_s, max_s, gloss_lang, provider=None if provider == "auto"
                             else provider, call=call, config=config)
        info.update(li)
        if not pts:
            raise RuntimeError(f"the lesson planner ({li.get('provider')}) returned no usable points; "
                               f"re-run, or plan with --provider none (rules)")
    else:
        pts = rule_points(sents, lang, count, min_s, max_s) if sents else []
    for i, p in enumerate(pts):
        p["id"] = f"p{i + 1:02d}"
        p["label"] = LABELS[p["kind"]]
    return dict(lang=lang, gloss_lang=gloss_lang, points=pts, recap=recap(pts, sents), planner=planner, info=info)


# --------------------------------------------------------------------------- study notes
def _fmt_range(a, b):
    return f"{_fmt_t(a)}-{_fmt_t(b)}"


def notes_markdown(plan, title=None, ui="zh"):
    """Study notes for one lesson: per point (kind, title, phrase + meaning, key terms, the teacher's line,
    examples, time), then a recap list. ``ui``: the language of the headings (zh | en)."""
    L = (lambda k: LABELS[k][ui])
    lang = plan.get("lang") or "en"
    head = title or ("Lesson notes" if ui == "en" else "课堂笔记")
    out = [f"# {head}", ""]
    n = len(plan["points"])
    out.append((f"{n} points from this lesson." if ui == "en" else f"本节课 {n} 个知识点。") + "")
    out.append("")
    for i, p in enumerate(plan["points"], 1):
        out.append(f"## {i}. {L(p['kind'])}: {p['title']}")
        out.append("")
        if p.get("phrase") and p["phrase"] != p["title"]:
            out.append(f"- **{'Phrase' if ui == 'en' else '表达'}**: {p['phrase']}")
        if p.get("gloss"):
            out.append(f"- **{'Meaning' if ui == 'en' else '意思'}**: {p['gloss']}")
        for t in p.get("terms") or []:
            if t["term"] in (p.get("phrase"), p["title"]):
                continue
            out.append(f"- **{L('term')}**: {t['term']}" + (f" ({t['gloss']})" if t.get("gloss") else ""))
        if p.get("summary"):
            out.append(f"- **{'In class' if ui == 'en' else '课上原话'}**: {p['summary']}")
        for e in p.get("examples") or []:
            if e != p.get("summary"):
                out.append(f"- **{L('example')}**: {e}")
        if p.get("translation"):
            out.append(f"- **{'Translation' if ui == 'en' else '翻译'}**: {p['translation']}")
        out.append(f"- *{_fmt_range(p['start'], p['end'])}*")
        out.append("")
    if plan["points"]:
        out.append(f"## {L('recap')}")
        out.append("")
        for p in plan["points"]:
            out.append(f"- {p['title']}" + (f" — {p['gloss']}" if p.get("gloss") else ""))
        out.append("")
    if lang != ui:
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_notes(plan, path, title=None, ui="zh", pdf=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    md = notes_markdown(plan, title, ui)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    if pdf:
        notes_pdf(md, pdf)
    return path


def notes_pdf(md, path, page=(1240, 1754), margin=110):
    """Markdown study notes -> a themed A4 PDF (paper, ink, accent headings), drawn with PIL (no extra deps)."""
    from PIL import Image, ImageDraw
    from . import draw as D
    from . import theme as TH
    T = TH.current()
    W, H = page
    paper, ink, ink2, acc = TH.rgb(T, "paper"), TH.rgba(T, "ink"), TH.rgba(T, "ink2"), TH.rgba(T, "accent")
    fonts = dict(h1=D.load_font("cjk-bold", 54), h2=D.load_font("cjk-bold", 36), body=D.load_font("cjk", 28),
                 bold=D.load_font("cjk-bold", 28), small=D.load_font("cjk", 22))
    pages, cur = [], None
    y = 0

    def new_page():
        nonlocal cur, y
        cur = Image.new("RGB", (W, H), paper)
        pages.append(cur)
        y = margin

    def need(h):
        if cur is None or y + h > H - margin:
            new_page()

    new_page()
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            y += 14
            continue
        if line.startswith("# "):
            f, fill, text, gap = fonts["h1"], ink, line[2:], 26
        elif line.startswith("## "):
            f, fill, text, gap = fonts["h2"], acc, line[3:], 14
            y += 18
        elif line.startswith("- "):
            f, fill, text, gap = fonts["body"], ink, "• " + line[2:], 8
        else:
            f, fill, text, gap = fonts["body"], ink2, line, 8
        text = text.replace("**", "").replace("*", "")
        lh = int(sum(f.getmetrics()) * 1.3)
        lines = D.wrap(text, f, W - 2 * margin)
        need(lh * len(lines) + gap)
        d = ImageDraw.Draw(cur)
        for ln in lines:
            d.text((margin, y), ln, font=f, fill=fill)
            y += lh
        if line.startswith("# "):
            d.rectangle([margin, y + 6, margin + 120, y + 12], fill=acc)
            y += 24
        y += gap
    for i, pg in enumerate(pages):
        ImageDraw.Draw(pg).text((W - margin, H - margin / 2), f"{i + 1}/{len(pages)}", font=fonts["small"],
                                fill=ink2, anchor="rm")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    pages[0].save(path, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return path


# --------------------------------------------------------------------------- clips
def kicker(kind, src_lang="en", bilingual=True):
    """Card / header label: "Today's phrase · 今日短语" in bilingual mode, else the lesson's language."""
    lab = LABELS[kind]
    if bilingual:
        return f"{lab['en']} · {lab['zh']}"
    return lab["zh" if src_lang == "zh" else "en"]


def clip_specs(plan, source, camera=None, offset=0.0, layout=None, mode="bilingual", mask=None, speed=1.0,
               recap_clip=True, subs=None, card_s=2.2, lesson_title=None):
    """Plan -> ``clipkit`` specs: one per point (title card, persistent header, key-term cards at their first
    mention) + the recap (a mini card per point before its anchor line). ``subs``: {title: translation} for card
    sublines (the planner's gloss wins)."""
    src_lang = plan.get("lang") or "en"
    bi = mode in ("bilingual", "translated")
    subs = subs or {}
    specs = []
    base = dict(source=source, camera=camera, offset=float(offset or 0.0), layout=layout, mask=mask or {},
                speed=float(speed or 1.0))
    for p in plan["points"]:
        k = kicker(p["kind"], src_lang, bi)
        sub = p.get("gloss") or (subs.get(p["title"]) if bi else None)
        terms = [dict(t=t["t"], term=t["term"], gloss=t.get("gloss") or (subs.get(t["term"]) if bi else None),
                      label=LABELS["term"]["en"] if src_lang == "en" else LABELS["term"]["zh"])
                 for t in (p.get("terms") or []) if t.get("t") is not None][:3]
        specs.append(dict(base, id=p["id"], kind=p["kind"], title=p["title"],
                          parts=[dict(kind="card", kicker=k, title=p["title"], sub=sub, dur=card_s),
                                 dict(kind="src", a=p["start"], b=p["end"])],
                          header=dict(kicker=k, title=p["title"], sub=sub), terms=terms,
                          highlight=[x for x in [p.get("phrase")] + [t["term"] for t in p.get("terms") or []] if x],
                          summary=p.get("summary"), gloss=sub))
    rc = plan.get("recap") or {}
    if recap_clip and len(rc.get("parts") or []) >= 2:
        parts = [dict(kind="card", kicker=kicker("recap", src_lang, bi),
                      title=lesson_title or (f"{len(rc['parts'])} points" if src_lang == "en" else
                                             f"{len(rc['parts'])} 个知识点"),
                      sub=None, dur=card_s)]
        for r in rc["parts"]:
            parts.append(dict(kind="card", kicker=kicker(r["kind"], src_lang, bi), title=r["title"],
                              sub=r.get("gloss") or (subs.get(r["title"]) if bi else None), dur=1.6))
            parts.append(dict(kind="src", a=r["range"][0], b=r["range"][1]))
        specs.append(dict(base, id="recap", kind="recap", title=LABELS["recap"]["en" if src_lang == "en" else "zh"],
                          parts=parts, header=None, terms=[],
                          highlight=[p.get("phrase") for p in plan["points"] if p.get("phrase")]))
    return specs


def post_for(spec, src_lang="en"):
    lab = LABELS.get(spec.get("kind"), LABELS["concept"])
    title = f"{lab['zh']}｜{spec['title']}" if src_lang == "en" else f"{lab['zh']}｜{spec['title']}"
    body = "\n".join(x for x in [spec.get("gloss"), spec.get("summary")] if x)
    return dict(title=title[:40], body=body, tags=None)


def render(plan, source, out_dir, platforms, camera=None, offset=None, layout=None, mode="bilingual", mask=None,
           speed=1.0, only=None, tgt_lang=None, sync_file=None, lesson_title=None, translate=None, call=None,
           recap_clip=True):
    """Plan -> every clip (and the recap) rendered + exported, report in ``out_dir/report.json``."""
    from . import clipkit as CK
    from . import bilingual as BL
    from vstudio.cleanup import load_words
    src_lang = plan.get("lang") or "en"
    tgt = tgt_lang or plan.get("gloss_lang") or BL.other_lang(src_lang)
    if camera and offset is None:
        if sync_file and os.path.exists(sync_file):
            with open(sync_file, encoding="utf-8") as f:
                offset = json.load(f).get("offset") or 0.0
        else:
            from . import avsync
            offset = avsync.sync(source, camera)["offset"]
    cache = os.path.join(out_dir, "translate-cache.json")
    subs = {}
    if mode in ("bilingual", "translated"):
        texts = list(dict.fromkeys([p["title"] for p in plan["points"]] +
                                   [t["term"] for p in plan["points"] for t in p.get("terms") or []]))
        subs = dict(zip(texts, CK.translate_lines(texts, src_lang, tgt, cache=cache, call=call)))
    specs = clip_specs(plan, source, camera, offset or 0.0, layout, mode, mask, speed, recap_clip=recap_clip,
                       subs=subs, lesson_title=lesson_title)
    if only:
        specs = [sp for sp in specs if sp["id"] in only]
    CK.auto_layouts(specs)
    words = load_words(plan["transcript"]) if plan.get("transcript") else None
    cap = CK.caption_config(mode, src_lang, tgt, cache=cache)
    return CK.render_all(specs, words, platforms, out_dir, cap, "lesson-points", only=only,
                         post_of=lambda s: post_for(s, src_lang), translate=translate)


# --------------------------------------------------------------------------- CLI
def load_plan(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _cli(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.lesson", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--source", default=None)
    p.add_argument("--transcript", default=None)
    p.add_argument("--language", default=None, help="en | zh | auto (detected)")
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--min", dest="min_s", type=float, default=20.0)
    p.add_argument("--max", dest="max_s", type=float, default=90.0)
    p.add_argument("--provider", default="auto")
    p.add_argument("--gloss-lang", default=None)
    p.add_argument("--out", default="work/points.json")
    p.add_argument("--keep-edited", action="store_true",
                   help="do not overwrite an --out the creator / agent edited (\"edited\": true)")
    n = sub.add_parser("notes")
    n.add_argument("plan")
    n.add_argument("--out", required=True)
    n.add_argument("--pdf", default=None)
    n.add_argument("--title", default=None)
    n.add_argument("--ui", default="zh", choices=["zh", "en"])
    sy = sub.add_parser("sync", help="offset of the camera file against the main recording (audio / timestamps)")
    sy.add_argument("--source", required=True)
    sy.add_argument("--camera", default=None)
    sy.add_argument("--offset", type=float, default=None, help="known offset (camera = source + offset)")
    sy.add_argument("--method", default="auto", choices=["auto", "audio", "timestamps"])
    sy.add_argument("--out", required=True)
    r = sub.add_parser("render")
    r.add_argument("plan")
    r.add_argument("--source", default=None)
    r.add_argument("--camera", default=None)
    r.add_argument("--sync", default=None, help="sync.json from `lesson sync`")
    r.add_argument("--offset", type=float, default=None)
    r.add_argument("--layout", default="auto", choices=["auto", "screen", "camera", "pip", "band"])
    r.add_argument("--platforms", default="douyin")
    r.add_argument("--subtitles", default="bilingual", choices=["mono", "bilingual", "translated"])
    r.add_argument("--to", dest="tgt", default=None, help="translation language (default: zh for an English lesson)")
    r.add_argument("--mask", default="off", choices=["off", "sticker", "blur"])
    r.add_argument("--mask-target", default="all", choices=["all", "camera", "screen"])
    r.add_argument("--speed", type=float, default=1.0)
    r.add_argument("--only", nargs="*", default=None)
    r.add_argument("--title", default=None)
    r.add_argument("--recap", action="store_true", help="also render the recap clip")
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "sync":
        from . import avsync
        if a.camera:
            try:
                res = avsync.sync(a.source, a.camera, offset=a.offset, method=a.method)
            except avsync.SyncError as e:
                print(f"[lesson sync] {e}", file=sys.stderr)
                return 2
        else:
            res = dict(offset=0.0, method="single-file", confidence=1.0)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        print(json.dumps(res))
        return 0
    if a.cmd == "render":
        plan = load_plan(a.plan)
        src = a.source or plan.get("source")
        mask = dict(mode=a.mask, target=a.mask_target) if a.mask != "off" else {}
        res = render(plan, src, a.out, [x for x in a.platforms.split(",") if x], camera=a.camera or None,
                     offset=a.offset, layout=None if a.layout == "auto" else a.layout, mode=a.subtitles, mask=mask,
                     speed=a.speed, only=a.only, tgt_lang=None if a.tgt in (None, "auto") else a.tgt,
                     sync_file=a.sync, lesson_title=a.title or plan.get("title"), recap_clip=a.recap)
        print(json.dumps(dict(out=a.out, clips=len(res["clips"]), ok=res["ok"]), ensure_ascii=False))
        return 0 if res["ok"] else 1
    if a.cmd == "notes":
        plan = load_plan(a.plan)
        write_notes(plan, a.out, a.title or plan.get("title"), a.ui, a.pdf)
        print(json.dumps(dict(notes=a.out, pdf=a.pdf, points=len(plan["points"])), ensure_ascii=False))
        return 0
    if a.keep_edited and os.path.exists(a.out):
        try:
            if load_plan(a.out).get("edited"):
                print(json.dumps(dict(out=a.out, kept=True), ensure_ascii=False))
                return 0
        except (OSError, ValueError):
            pass
    from vstudio.batch.segplan import get_transcript
    lang = None if a.language in (None, "", "auto") else a.language
    tr, tpath, _ = get_transcript(a.source, a.transcript, language=lang)
    sents = sentences(tr)
    plan = plan_points(sents, lang, a.count, a.min_s, a.max_s, a.provider, a.gloss_lang)
    plan.update(source=os.path.abspath(a.source) if a.source else None, transcript=tpath)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    print(json.dumps(dict(out=a.out, points=len(plan["points"]), planner=plan["planner"], lang=plan["lang"]),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
