"""Caption proofreading: term fixes + a per-source glossary + minimal LLM corrections + low-confidence words, all
logged, every change checked against the audio.

    from vstudio import proofread
    g = proofread.build_glossary(whole_transcript_text, context=dict(topic="RAG lecture", glossary=["RAG", "LLM"]),
                                 provider="openai", model="gpt-4.1")          # ONCE per source recording
    res = proofread.proofread(cues, term_fixes=[["[Tt]runking", "chunking"]], provider="auto", glossary=g,
                              context=dict(topic="RAG lecture", glossary=["RAG", "LLM"]), heard=reasr_words)
    res["cues"]        # corrected cues (same timing, same count)
    res["changes"]     # [{i, start, end, before, after, source: term_fix | glossary | llm | llm-propagated, why,
                       #   guess, support}]  guess: an LLM fix neither in the glossary nor a strong sound-alike
    cues, log = proofread.fix_filler_edges(res["cues"])   # no caption ends on 就是 / starts on 的话

Captions must match the audio, so nothing here rewrites what was said: term fixes are the creator's own regex /
literal list (spec ``subtitles.term_fixes``, persona ``subtitles.term_fixes``, ``asr.GENERIC_TERM_FIXES``); the
glossary (``build_glossary``: the whole transcript -> domain terms + the recurring ASR confusions, a focused pass
over the latin tokens, a second look, confidence >= 0.97) is applied the same way to every job of the source; the
LLM pass may only swap a short mis-heard span for what the speaker actually said (homophones such as 称爆 -> 撑爆,
mangled English terms such as RM -> LLM). Every proposal goes through ``faithful``: on the spoken units (one per
CJK character / latin word) nothing may be deleted or added, each replaced run must sound alike (syllables within
1, same language), the cue stays >= 60 % similar; rejected ones are logged with the reason. An accepted term fix
is propagated to the job's other cues; spans the term fixes / glossary fixed are never re-edited. Fillers are never
removed here - that is cleanup's job (the audio would still say them).

Providers (``provider``; every call goes through ``vstudio.llm.complete``, tasks ``proofread`` / ``glossary``):
  auto     the configured route (persona / client ``llm.tasks.proofread`` / ``llm.default``, env
           VSTUDIO_LLM_PROOFREAD_PROVIDER ...), else claude when ANTHROPIC_API_KEY is set, else none (OpenAI, local
           servers and subscription CLIs are never picked implicitly)
  claude   anthropic SDK (``pip install anthropic``, imported lazily), default model claude-opus-5-5
  openai   only when configured explicitly; OPENAI_API_KEY; ``openai`` SDK, default model gpt-4.1-mini
  any other ``vstudio.llm`` provider: openai-compatible presets (deepseek, qwen, kimi, glm, openrouter, ollama,
           lmstudio, vllm, llamacpp), gemini, claude-code / codex (your own CLI login) - see references/PROVIDERS.md
  none     term fixes + glossary fixes + low-confidence flags only
A test / plugin can pass ``call=fn(system, prompt, model) -> (text, usage dict)`` instead of a provider.

Low-confidence words: words of a transcript with a probability (``p`` / ``probability``, as ``asr.transcribe``
returns) under ``low_conf`` (default 0.5), attached to the cue they fall in - shown on the batch review page.
``heard`` (a fresh ASR of the finished cut, e.g. the verify re-ASR) also goes to the LLM as a second hearing.
"""
import difflib
import json
import os
import re

from . import asr
from . import llm

DEFAULT_MODELS = {"claude": "claude-opus-5-5", "openai": "gpt-4.1-mini"}
# USD per million tokens (input, output); spec prices.proofread_in / proofread_out override
PRICES = llm.PRICES
FILLER_STACK = re.compile(r"(?:然后|就是|那个|这个|因为|所以|而且|的话|但是|嗯|呃|额)(?:然后|就是|那个|这个|因为|所以|而且|的话|"
                          r"但是|嗯|呃|额)+")
HESITATION_RE = re.compile(r"[嗯呃额]")
# function characters a homophone / term fix never needs to DELETE ("整个的RM" -> "整个LLM" drops a spoken 的;
# swapping one in place, 比的 -> 比例, is fine)
SPOKEN_ZH = set("的了是在也和就都把被个们你我他它这那")

SYSTEM = """You proofread burned-in captions of a recorded talk. The captions come from speech recognition (ASR) \
and must keep matching what the speaker SAID, word for word. Fix every clear recognition error: homophones / \
near-homophones that make no sense in context while a sound-alike word fits the topic (e.g. 准缺率 -> 准确率, \
模形 -> 模型, 称爆 -> 撑爆), and mangled technical or English terms (e.g. RM -> LLM in a talk about LLMs, \
Rewanking -> reranking). Be consistent: the same mis-heard term gets the same fix in every caption, and the \
known confusions listed below are already applied - use them as a guide for similar mistakes. Do NOT rephrase, \
shorten, reorder, translate, polish grammar, remove fillers or repetitions, delete or add words: a fix swaps a \
mis-heard span for a sound-alike span (about the same number of syllables). Leave anything you are not sure about.

Input lines look like `i: CAPTION [heard: ...] [unsure: ...]`. Captions are consecutive: read them in context. \
`heard` is a second ASR pass over the same audio and `unsure` lists low-confidence words: hints. A phrase that \
reads wrong or makes no sense right where an `unsure` word sits is almost always a mis-heard sound-alike: fix it \
when a sound-alike word fits the sentence and the topic (e.g. 模型的准缺率很高 [unsure: 缺] -> 准确率). \
Each fix replaces one short span of ONE caption; "from" must be copied exactly from that CAPTION (not from \
`heard`) and be as short as possible (just the mis-heard word, not the whole caption).

Reply with JSON only: {"fixes": [{"i": <caption index>, "from": "<exact substring of caption i>", \
"to": "<replacement>", "why": "<few words>"}]} - an empty list when nothing is clearly wrong."""

VOCAB_SYSTEM = """You check the English / latin words of ONE speech-recognition (ASR) transcript of a talk (mostly \
Chinese with English terms). You get the topic, the terms the speaker uses, and every latin token of the \
transcript with its count and one context. List the tokens that are mis-hearings of a term or English word the \
speaker said (e.g. RM -> LLM and IRM -> LLM in a talk about LLMs, Rewanking -> reranking, Sematic -> Semantic). \
"to" must sound like "from"; never translate, never change case only, never split / merge words only. \
"confidence": 0-1, how sure you are that EVERY occurrence of "from" was "to" (look at all its contexts: a \
token that may mean two different terms is not a fix). "why" in at most 8 words.
Reply with JSON only: {"fixes": [{"from": "<token exactly as listed>", "to": "...", "why": "...", "confidence": 0.9}]}"""

CHECK_SYSTEM = """You double-check proposed caption fixes for ONE speech-recognition (ASR) transcript of a talk. Each \
proposal says that the transcript text "from" is a mis-hearing of "to", and shows every context where "from" \
appears (up to 5). Accept a proposal only if, in EVERY context, the speaker clearly said "to" (it sounds like \
"from" and fits the topic). Reject it when "from" is itself a real word, name or product that fits (e.g. Skill \
for Claude Skills, Java), when a context could mean something else, when "to" is a guess, a translation or a \
rewording, or when it changes only case or spacing.
List only the proposals you reject. Reply with JSON only: {"reject": [{"n": <proposal number>, "why": "<at most 8 \
words>"}]} (an empty list when all are right)."""

GLOSSARY_SYSTEM = """You prepare the proofreading glossary for the captions of ONE recorded talk. You get its whole \
speech-recognition (ASR) transcript (and the topic). Return:
1. "terms": the domain terms, product names and English words the speaker uses, spelled correctly.
2. "fixes": recognition errors in this transcript, especially RECURRING ones: {"from": "<exact text as it \
appears in the transcript>", "to": "<what the speaker actually said>", "why": "<few words>"}. Only clear \
cases: homophones / near-homophones that make no sense in context while a sound-alike word fits the topic \
(e.g. 称爆 -> 撑爆, 准缺率 -> 准确率) and mangled English / technical terms (e.g. RM -> LLM in a talk about LLMs, \
Rewanking -> reranking).
Rules: "from" must be copied exactly from the transcript and be short (the mis-heard word, 2+ characters, not a \
whole sentence); "to" must sound like "from" (about the same number of syllables) in the SAME language - never \
translate (precision -> 精度 is wrong: the speaker said "precision"); never delete or add words, never rephrase, \
never fix grammar, case, fillers or repetitions; leave out anything you are not sure of. "confidence": 0-1, how \
sure you are that the speaker said "to" every time "from" appears.
3. "entities": the proper nouns of the transcript (countries, regions, cities, organisations, companies, products, people): {"text": "<exactly as in the transcript>", "standard": "<its standard spelling in the transcript's language and script>", "kind": "place|org|product|person", "certain": true|false} - "certain" only when you know the standard spelling for sure; a sound-alike spelling fix only, never a translation.
At most 60 terms, 40 fixes and 40 entities (the most frequent first), each listed once; "why" in at most 8 words.
Reply with JSON only: {"terms": ["..."], "fixes": [{"from": "...", "to": "...", "why": "...", "confidence": 0.9}],
"entities": [{"text": "...", "standard": "...", "kind": "org", "certain": true}]}"""


def resolve_provider(provider=None, task="proofread", config=None):
    """"auto" | None -> the configured ``vstudio.llm`` route for ``task``, else "claude" when ANTHROPIC_API_KEY is
    set, else "none"; anything else is validated and returned as is (the Anthropic API keeps the name "claude")."""
    p = (provider or "auto").lower()
    if p == "auto":
        p = llm.route(task, config=config).provider
    if p in ("claude", "openai", "none"):
        return p
    try:
        c = llm.canonical(p)
    except ValueError:
        raise ValueError(f"proofread provider {provider!r}: auto | claude | openai | none | "
                         + " | ".join(n for n in llm.names() if n not in ("anthropic", "openai", "none"))) from None
    return "claude" if c == "anthropic" else c


def default_model(prov, task="proofread", config=None):
    """The model for a resolved provider: the route's model when that provider is configured, else the defaults."""
    if prov in ("none", "custom"):
        return DEFAULT_MODELS.get(prov)
    r = llm.route(task, "anthropic" if prov == "claude" else prov, config=config)
    return r.model or DEFAULT_MODELS.get(prov) or llm.default_model(r.provider, r.opts)


def _cue_dict(c):
    if isinstance(c, dict):
        return dict(c)
    return c.to_dict() if hasattr(c, "to_dict") else dict(start=c[0], end=c[1], text=c[2])


# ------------------------------------------------------------------ providers
def _call_claude(system, prompt, model, task="proofread"):
    """Anthropic API through ``vstudio.llm`` (effort low, JSON parsed / retried by the caller). The route's
    fallback chain applies when the task is routed to anthropic (``llm.complete``: same provider = not pinned)."""
    r = llm.complete(task, system, prompt, schema=True, provider="anthropic", model=model, max_tokens=16000,
                     effort="low", repair=False)
    return r["text"], dict(r["usage"])


def _call_openai(system, prompt, model, task="proofread"):
    """OpenAI Chat Completions (JSON mode, temperature 0) through ``vstudio.llm``."""
    r = llm.complete(task, system, prompt, schema=True, provider="openai", model=model, max_tokens=8000,
                     temperature=0, repair=False)
    return r["text"], dict(r["usage"])


def _call_llm(prov, task="proofread"):
    """``fn(system, prompt, model) -> (text, usage)`` for any ``vstudio.llm`` provider. A provider that is the
    task's own route keeps the route's fallback chain (``llm.complete``: the routed provider is never pinned), so
    "auto" -> claude-code still falls back to codex; ``fn.results``: who really answered."""
    if prov in CALLS:
        f = CALLS[prov]
        return f if task == "proofread" or f not in (_call_claude, _call_openai) else \
            (lambda s, p, m: f(s, p, m, task=task))
    return llm.call_fn(task, provider=prov, schema=True, temperature=0, repair=False)


CALLS = {"claude": _call_claude, "openai": _call_openai}


def _parse(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    try:
        if not m:
            raise ValueError("no object")
        d = json.loads(m.group(0))
        fixes = d.get("fixes") if isinstance(d, dict) else d
        return [f for f in fixes or [] if isinstance(f, dict)]
    except ValueError:
        pass
    out = []                                      # truncated / wrapped reply: salvage every complete fix object
    for frag in re.findall(r"\{[^{}]*\}", t):
        try:
            d = json.loads(frag)
        except ValueError:
            continue
        if isinstance(d, dict) and "i" in d:
            out.append(d)
    if not out and not re.search(r'"fixes"\s*:\s*\[\s*\]', t):
        raise ValueError(f"proofread: no JSON in the reply: {t[:200]!r}")
    return out


# ------------------------------------------------------------------ helpers
def low_confidence(words, cues, thr=0.5):
    """Words with a probability < thr -> [{i (cue), word, p, t}] (words without a probability are skipped)."""
    out = []
    for w in words or ():
        p = w.get("p", w.get("probability"))
        if p is None or float(p) >= thr:
            continue
        t = float(w.get("start", w.get("t", 0.0)))
        te = float(w.get("end", w.get("te", t)))
        m = (t + te) / 2
        i = next((k for k, c in enumerate(cues) if c["start"] - 0.05 <= m <= c["end"] + 0.05), None)
        if i is not None:
            out.append(dict(i=i, word=str(w.get("word", w.get("w", ""))).strip(), p=round(float(p), 3),
                            t=round(t, 2)))
    return out


def words_of(transcript):
    """Flat words [{word, start, end, p}] of any asr.transcribe-shaped dict / list (probabilities kept)."""
    if isinstance(transcript, dict):
        segs = transcript.get("segments") or []
        if segs:
            return [w for s in segs for w in s.get("words") or []]
        return list(transcript.get("words") or [])
    return list(transcript or [])


def caption_fillers(cues):
    """Filler stacks / hesitations still in the captions (they are in the audio too: cut them in cleanup)."""
    out = []
    for i, c in enumerate(cues):
        hits = [m.group(0) for m in FILLER_STACK.finditer(c["text"])]
        hits += [m.group(0) for m in HESITATION_RE.finditer(c["text"]) if not any(m.group(0) in h for h in hits)]
        if hits:
            out.append(dict(i=i, start=round(c["start"], 2), text=c["text"], fillers=hits))
    return out


def _heard_in(heard, c):
    ws = [w for w in heard or () if c["start"] - 0.1 <= (float(w.get("start", w.get("t", 0))) +
                                                         float(w.get("end", w.get("te", 0)))) / 2 <= c["end"] + 0.1]
    return asr_join(ws)


def asr_join(ws):
    from .cleanup import join_words
    return join_words([dict(w=str(w.get("word", w.get("w", "")))) for w in ws])


def _prompt(cues, context, heard, low):
    lines = []
    ctx = context or {}
    if ctx.get("topic"):
        lines.append(f"Topic: {ctx['topic']}")
    if ctx.get("glossary"):
        lines.append("Terms the speaker uses: " + ", ".join(dict.fromkeys(str(g) for g in ctx["glossary"] if g)))
    if ctx.get("notes"):
        lines.append("Key points: " + " / ".join(ctx["notes"]))
    if ctx.get("confusions"):
        lines.append("Known ASR confusions in this recording (already fixed): " + ", ".join(
            f"{a} -> {b}" for a, b in ctx["confusions"][:60]))
    lines.append("")
    lines.append("Captions:")
    by = {}
    for x in low or ():
        by.setdefault(x["i"], []).append(x["word"])
    for i, c in enumerate(cues):
        s = f"{i}: {c['text']}"
        h = _heard_in(heard, c) if heard else ""
        if h and h != c["text"]:
            s += f" [heard: {h}]"
        if by.get(i):
            s += " [unsure: " + ", ".join(by[i]) + "]"
        lines.append(s)
    return "\n".join(lines)


def _span_len(s):
    """CJK characters count 1, latin letters / digits 1/2 (an English word is one mis-heard unit, not ten)."""
    return sum(0.5 if re.match(r"[A-Za-z0-9]", ch) else (0.0 if ch.isspace() else 1.0) for ch in s)


def _locate(text, a):
    """``a`` in ``text`` exactly, else with spaces ignored (the model copied 'cont ext' for 'context')."""
    if a in text:
        return a
    squeezed = a.replace(" ", "")
    if squeezed and squeezed in text:
        return squeezed
    return None


# ------------------------------------------------------------------ captions match the audio
_TOK = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-\.]*|[\u3400-\u9fff\uf900-\ufaff]|[^\sA-Za-z0-9\u3400-\u9fff\uf900-\ufaff]")
_PUNCT = re.compile(r"^[^A-Za-z0-9\u3400-\u9fff\uf900-\ufaff]+$")


def tokens(text):
    """Spoken units of a caption: one per CJK character, one per latin / digit word; punctuation dropped."""
    return [t for t in _TOK.findall(text or "") if not _PUNCT.match(t)]


def _en_syl(w):
    """English syllables of one latin word: vowel groups, a silent final e dropped (pipeline 2-3, rewrite 2)."""
    n = 0
    for part in re.findall(r"[a-z]+", w.lower()):
        if len(part) > 2 and part.endswith("e") and not re.search(r"[^aeiouy]le$", part):
            part = part[:-1]
        n += max(1, len(re.findall(r"[aeiouy]+", part)))
    return max(1, n)


def _syl(toks):
    """Spoken syllables: CJK 1 per character, digits 1 each, an acronym (RM, RRF, BM) 1 per letter, other latin
    words by vowel groups (``_en_syl``)."""
    n = 0
    for t in toks:
        if re.fullmatch(r"[A-Za-z]{1,5}", t) and (t.isupper() or not re.search(r"[aeiouyAEIOUY]", t)):
            n += len(t)
        elif re.search(r"[A-Za-z]", t):
            n += _en_syl(t) + len(re.findall(r"[0-9]", t))
        else:
            n += max(1, len(t)) if re.match(r"[0-9]", t) else 1
    return n


def _cjk(toks):
    return [t for t in toks if re.match(r"[\u3400-\u9fff\uf900-\ufaff]", t)]


def faithful(before, after):
    """None when ``after`` still says what ``before`` says (only mis-heard spans swapped for sound-alikes), else
    the reason. Rules on the spoken units (``tokens``; case, spaces and punctuation are free):
    no unit may disappear (a deleted spoken word: 整个的RM -> 整个LLM drops 的), none may appear from nowhere (an
    added word), and every replaced run must sound alike: syllable counts within 1 (or a third for long runs), and
    a function character (的 了 是 ...) is never replaced by fewer characters."""
    return _faithful_toks(tokens(before), tokens(after))


def faithful_swap(text, a, b, at=None):
    """``faithful`` for one substitution of span ``a`` (at index ``at``, default its first occurrence) by ``b``;
    the parts left and right of the span are tokenised on their own, so latin words never merge across it."""
    k = text.find(a) if at is None else at
    if k < 0:
        return "'from' is not in the caption"
    pre, post = tokens(text[:k]), tokens(text[k + len(a):])
    return _faithful_toks(pre + tokens(a) + post, pre + tokens(b) + post)


def _faithful_toks(ta, tb):
    a = [t.lower() for t in ta]
    b = [t.lower() for t in tb]
    if a == b:
        return None
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        old, new = ta[i1:i2], tb[j1:j2]
        if op == "equal" or "".join(old).lower() == "".join(new).lower():     # spacing / case only
            continue
        if op == "delete":
            return f"drops spoken word(s) {''.join(old)} (captions must match the audio)"
        if op == "insert":
            return f"adds word(s) {''.join(new)} that were not said"
        so, sn = _syl(old), _syl(new)
        if abs(so - sn) > max(1, round(so / 3)):
            return f"'{''.join(old)}' -> '{''.join(new)}' does not sound alike ({so} vs {sn} syllables)"
        ol, nl = "".join(old).lower(), "".join(new).lower()
        if re.fullmatch(r"[a-z]+", ol) and re.fullmatch(r"[a-z]+", nl) and len(nl) < len(ol) and ol.startswith(nl):
            return f"'{''.join(old)}' -> '{''.join(new)}' only drops an ending (grammar, not a mis-hearing)"
        co, cn = _cjk(old), _cjk(new)
        if cn and not co and len(cn) == len(new):     # latin -> Chinese is a translation (precision -> 精度);
            return f"'{''.join(old)}' -> '{''.join(new)}' switches language (a translation, not a mis-hearing)"
        # Chinese -> latin stays allowed: ASR writes English words with sound-alike characters (派篮 -> pipeline)
        lost = [ch for ch in set(co) if ch in SPOKEN_ZH and co.count(ch) > cn.count(ch)]
        if lost and len(cn) < len(co):
            return f"drops spoken word(s) {''.join(sorted(lost))} (captions must match the audio)"
    return None


def diff_spans(before, after):
    """Minimal [(from, to)] spans turning ``before`` into ``after`` (whole spoken units; used to shrink a fix the
    model wrote as a whole caption down to the words that really changed)."""
    ta, tb = tokens(before), tokens(after)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [t.lower() for t in ta], [t.lower() for t in tb],
                                                       autojunk=False).get_opcodes():
        if op != "equal":
            out.append(("".join(ta[i1:i2]) if all(_cjk([t]) for t in ta[i1:i2]) else " ".join(ta[i1:i2]),
                        "".join(tb[j1:j2]) if all(_cjk([t]) for t in tb[j1:j2]) else " ".join(tb[j1:j2])))
    return out


def _valid(text, fx, max_span=12):
    a, b = str(fx.get("from") or ""), str(fx.get("to") or "")
    if not a or a == b:
        return "empty / no-op fix"
    if _locate(text, a) is None:
        return "'from' is not in the caption"
    a = _locate(text, a)
    new = text.replace(a, b, 1)
    if new.replace(" ", "") == text.replace(" ", ""):
        return "empty / no-op fix"
    if difflib.SequenceMatcher(None, text, new).ratio() < 0.6:
        return "changes too much of the caption"
    bad = faithful_swap(text, a, b)
    if bad:
        return bad
    for o, n in diff_spans(text, new):                 # the words that really change must each be short
        if _span_len(o) > max_span or _span_len(n) > _span_len(o) + 6:
            return "span too long (only short mis-heard spans may change)"
    return None


_ASCII_B = r"(?:(?<![A-Za-z0-9])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?![A-Za-z0-9]))"


def ascii_boundaries(fixes):
    """Term fixes with every regex ``\\b`` turned into an ASCII word boundary: next to CJK (a \\w character in
    Python) ``\\bprom\\b`` never matches 这个prom, which is what the creator meant."""
    out = []
    for f in fixes or ():
        if isinstance(f, (list, tuple)) and len(f) >= 2 and isinstance(f[0], str) and "\\b" in f[0]:
            out.append([f[0].replace("\\b", _ASCII_B), *f[1:]])
        else:
            out.append(f)
    return out if not isinstance(fixes, dict) else fixes


def cost_usd(model, usage, prices=None, provider=None):
    """USD of ``usage``: spec prices.proofread_in / proofread_out override the table; local servers and
    subscription CLIs (``provider``) cost 0."""
    pin, pout = (prices or {}).get("proofread_in"), (prices or {}).get("proofread_out")
    if provider and provider not in ("claude", "custom") and pin is None and pout is None:
        try:
            if llm.canonical(provider) in llm.LOCAL:
                return 0.0
        except ValueError:
            pass
    d = llm.price_of(model, {k: v for k, v in (prices or {}).items() if isinstance(v, (list, tuple))})[0]
    pin = d[0] if pin is None else float(pin)
    pout = d[1] if pout is None else float(pout)
    return round((usage.get("input", 0) * pin + usage.get("output", 0) * pout) / 1e6, 5)


# ------------------------------------------------------------------ per-source glossary
def _term_like(a):
    """A span worth fixing everywhere: latin / digits, or >= 2 CJK characters."""
    return bool(re.search(r"[A-Za-z0-9]", a)) or len(_cjk(tokens(a))) >= 2


def _pattern(a):
    """Regex for span ``a`` that never matches inside a longer latin word (RM must not hit ARM / RMS)."""
    p = re.escape(a)
    if re.match(r"[A-Za-z0-9]", a):
        p = r"(?<![A-Za-z0-9])" + p
    if re.search(r"[A-Za-z0-9]$", a):
        p += r"(?![A-Za-z0-9])"
    return re.compile(p)


def check_glossary_fix(fx, text=None):
    """None when a glossary fix is usable on every caption of the source, else why not."""
    a, b = str(fx.get("from") or "").strip(), str(fx.get("to") or "").strip()
    if not a or not b or a == b:
        return "empty / no-op fix"
    if not _term_like(a):
        return "too generic ('from' must be a term: latin, or 2+ characters)"
    if text is not None and not _pattern(a).search(text):
        return "'from' is not in the transcript"
    if _span_len(a) > 12 or _span_len(b) > _span_len(a) + 6:
        return "span too long (only short mis-heard spans may change)"
    bad = faithful(a, b)
    if bad:
        return bad
    return None


def build_glossary(text, context=None, provider="auto", model=None, call=None, prices=None, max_chars=120000,
                   min_conf=0.97, term_conf=0.9, check=True):
    """ONE glossary per source recording, from its whole transcript ``text``: domain terms + the recurring ASR
    confusions (``from`` exactly as in the transcript -> what was said), each fix validated
    (``check_glossary_fix``: a term, found in the transcript, sound-alike, no deleted / added words).
    Returns dict(terms, fixes [{from, to, why, count}], rejected, provider, model, usage, cost_usd)."""
    prov = "custom" if call else resolve_provider(provider, task="glossary")
    mdl = model or default_model(prov, "glossary")
    out = dict(terms=[], fixes=[], rejected=[], provider=prov, model=mdl if prov != "none" else None,
               usage=dict(input=0, output=0), cost_usd=0.0)
    if prov == "none" or not text:
        return out
    ctx = context or {}
    lines = []
    if ctx.get("topic"):
        lines.append(f"Topic: {ctx['topic']}")
    if ctx.get("glossary"):
        lines.append("Terms the creator listed: " + ", ".join(dict.fromkeys(str(g) for g in ctx["glossary"] if g)))
    lines += ["", "Transcript:", text[:max_chars]]
    fn = call or _call_llm(prov, "glossary")

    def ask(system, prompt):
        reply, u = fn(system, prompt, mdl)
        out.setdefault("raw", []).append((reply or "")[:20000])
        out["usage"]["input"] += int(u.get("input", 0))
        out["usage"]["output"] += int(u.get("output", 0))
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (reply or "").strip())
        m = re.search(r"\{.*\}", t, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except ValueError:
            return {}
    d = ask(GLOSSARY_SYSTEM, "\n".join(lines))
    out["terms"] = [str(x).strip() for x in d.get("terms") or [] if str(x).strip()][:200]
    llm_entities = [e for e in d.get("entities") or [] if isinstance(e, dict)][:80]
    vocab = latin_vocab(text)
    proposals = list(d.get("fixes") or [])
    if vocab:                                    # second, focused pass over the English tokens (RM -> LLM ...)
        vl = [f"Topic: {ctx.get('topic') or ''}",
              "Terms: " + ", ".join(dict.fromkeys(list(ctx.get("glossary") or []) + out["terms"])), "",
              "Latin tokens (token x count: context):"]
        for order in (vocab, sorted(vocab, key=lambda v: v["token"].lower())):   # two looks: recall
            proposals += list(ask(VOCAB_SYSTEM, "\n".join(vl + [f"{v['token']} x{v['count']}: {v['context']}"
                                                                 for v in order])).get("fixes") or [])
    cand, seen = [], set()
    for fx in proposals:
        if not isinstance(fx, dict):
            continue
        try:
            conf = float(fx.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 0.0
        fx = {k: str(fx.get(k) or "").strip() for k in ("from", "to", "why")}
        fx["confidence"] = conf
        bad = check_glossary_fix(fx, text)
        listed_ = {str(g).strip().lower() for g in ctx.get("glossary") or [] if str(g).strip()}
        need = min_conf
        if not bad and conf < need:
            bad = f"confidence {conf:.2f} < {need}"
        if not bad and fx["from"].lower() == fx["to"].lower():
            bad = "case only (not a mis-hearing)"
        if not bad and fx["from"] in seen:
            continue                                  # the same proposal from another pass
        if bad:
            out["rejected"].append(dict(fx, reason=bad))
            continue
        seen.add(fx["from"])
        cand.append(dict(fx, count=len(_pattern(fx["from"]).findall(text))))
    listed = {str(g).strip().lower() for g in ctx.get("glossary") or [] if str(g).strip()}
    sure = [fx for fx in cand if fx["to"].lower() in listed and re.fullmatch(r"[A-Za-z0-9]+", fx["from"])]
    out["fixes"] += [dict(fx, checked="creator term") for fx in sure]     # RM -> LLM when the creator listed LLM
    cand = [fx for fx in cand if fx not in sure]
    if cand and check:                            # a second look at every proposal, with all its contexts
        cl = [f"Topic: {ctx.get('topic') or ''}", ""]
        for n, fx in enumerate(cand):
            ctxs = [text[max(0, m.start() - 14):m.end() + 14].replace("\n", " ")
                    for m in list(_pattern(fx["from"]).finditer(text))[:5]]
            cl.append(f"{n}. {fx['from']} -> {fx['to']}  (x{fx['count']}): " + " | ".join(ctxs))
        rej = {}
        for v in ask(CHECK_SYSTEM, "\n".join(cl)).get("reject") or []:
            try:
                rej[int(v.get("n"))] = v
            except (TypeError, ValueError, AttributeError):
                continue
        for n, fx in enumerate(cand):
            if n in rej:
                out["rejected"].append(dict(fx, reason="second look: " + str(rej[n].get("why") or "rejected")))
            else:
                out["fixes"].append(dict(fx, checked="second look"))
    else:
        out["fixes"] += cand
    # named-entity verification (vstudio.entities): CLDR place names / cities, glossary spellings and the model's
    # "standard spelling" answers; certain ones join the source's fixes (one truth for captions, cards and copy)
    from . import entities as ENT
    ev = ENT.verify(text, locale=entity_locale(text), glossary=list(ctx.get("glossary") or []) + out["terms"],
                    llm_entities=llm_entities)
    have = {f["from"] for f in out["fixes"]}
    for f in ev["fixes"]:
        if f["from"] not in have and not check_glossary_fix(dict(f), text):
            out["fixes"].append(dict(**{"from": f["from"], "to": f["to"]}, why=f["why"], confidence=1.0,
                                     count=f.get("count", 1), checked=f"entity:{f['source']}"))
    out["entities"] = dict(locale=ev["locale"], found=ev["entities"], flagged=ev["flagged"])
    out["cost_usd"] = cost_usd(mdl, out["usage"], prices, prov)
    out["fixes"].sort(key=lambda f: -len(f["from"]))
    return out


def entity_locale(text=""):
    """The content locale for entity spelling: persona ``creator.locale`` (zh-TW, zh-HK ...), else from the text."""
    from . import entities as ENT
    try:
        from .config import persona
        loc = (persona().get("creator") or {}).get("locale")
    except Exception:  # noqa: BLE001
        loc = None
    return ENT.norm_locale(loc, text)


def latin_vocab(text, limit=400):
    """Distinct latin / digit tokens of ``text`` with their count and one short context, most frequent first."""
    seen = {}
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9\-]*", text or ""):
        w = m.group(0)
        v = seen.setdefault(w, dict(token=w, count=0, contexts=[]))
        v["count"] += 1
        if len(v["contexts"]) < 3:
            v["contexts"].append(text[max(0, m.start() - 10):m.end() + 10].replace("\n", " "))
    out = sorted(seen.values(), key=lambda v: (-v["count"], v["token"]))[:limit]
    for v in out:
        v["context"] = " | ".join(v.pop("contexts"))
    return out


def _swap(text, k, a, b):
    """``text`` with ``a`` at index ``k`` replaced by ``b``; a latin replacement glued to a latin neighbour gets a
    space (query派篮 -> query pipeline, not querypipeline)."""
    pre, post = text[:k], text[k + len(a):]
    if b and re.match(r"[A-Za-z0-9]", b) and re.search(r"[A-Za-z0-9]$", pre) and not re.search(r"[A-Za-z0-9]$", a[:1]):
        b = " " + b
    if b and re.search(r"[A-Za-z0-9]$", b) and re.match(r"[A-Za-z0-9]", post) and not re.match(r"[A-Za-z0-9]", a[-1:]):
        b = b + " "
    return pre + b + post


def _overlaps(text, span, kept):
    """True when the first occurrence of ``span`` in ``text`` overlaps an occurrence of ``kept``."""
    a = text.find(span)
    if a < 0 or not kept:
        return False
    b = a + len(span)
    for m in re.finditer(re.escape(kept), text):
        if m.start() < b and a < m.end():
            return True
    return False


def apply_glossary(text, fixes):
    """Every glossary fix on ``text`` (longest ``from`` first, latin spans only at word boundaries)."""
    for fx in fixes or ():
        text = _pattern(fx["from"]).sub(lambda m: fx["to"], text)
    return text


# ------------------------------------------------------------------ caption filler edges
LEAD_FILLERS = ("然后的话", "就是说", "然后呢", "然后", "就是", "那个", "那么", "嗯", "呃", "额")
TRAIL_FILLERS = ("的话", "对吧", "是吧", "嘛", "呢", "吧", "啊", "呀")


def _edge(text, side):
    t = text.strip()
    for f in sorted(LEAD_FILLERS + TRAIL_FILLERS, key=len, reverse=True):
        if (t.startswith(f) if side == "start" else t.endswith(f)) and len(t) > len(f):
            return f
    return None


def _cue_time(c, k):
    """Time inside cue ``c`` after its first ``k`` characters (shared in proportion to the text)."""
    n = max(1, len(c["text"]))
    return c["start"] + (c["end"] - c["start"]) * min(1.0, k / n)


def fix_filler_edges(cues, fits=None, max_chars=24, max_gap=0.35, max_dur=7.0, locked=None):
    """No caption ends on a filler that leads into the next words (就是 / 然后 / 那个 / 嗯 ...) and none starts
    on a particle that closes the words before (的话 / 嘛 / 吧 ...) - both read as a broken line. At every such
    boundary between two cues that follow each other (gap <= max_gap) the cues merge when the result fits
    (``fits(text)``, default <= max_chars characters and <= max_dur s), else the filler moves across the
    boundary to the cue it belongs to (when that cue still fits). The words and their order never change; a
    filler opening a cue (然后我们...) or a particle closing one (...的话) is where it belongs. ``locked``: indices
    of cues the creator fixed by hand - never merged or changed. Returns (cues, log)."""
    fits = fits or (lambda t: len(t.replace(" ", "")) <= max_chars)
    C = [dict(c) for c in cues]
    lk = [k in set(locked or ()) for k in range(len(C))]
    log = []
    k = 0
    while k < len(C) - 1:
        a, b = C[k], C[k + 1]
        if b["start"] - a["end"] > max_gap or (a.get("meta") or {}).get("kind") != (b.get("meta") or {}).get("kind") \
                or lk[k] or lk[k + 1]:
            k += 1
            continue
        ea, sb = _edge(a["text"], "end"), _edge(b["text"], "start")
        ea = ea if ea in LEAD_FILLERS else None             # 就是 at the end of a line leads into the next
        sb = sb if sb in TRAIL_FILLERS else None            # 的话 at the start of a line closes the one before
        if not ea and not sb:
            k += 1
            continue
        sep = " " if re.search(r"[A-Za-z0-9]$", a["text"]) and re.match(r"[A-Za-z0-9]", b["text"]) else ""
        merged = a["text"] + sep + b["text"]
        if fits(merged) and b["end"] - a["start"] <= max_dur:
            C[k] = dict(a, text=merged, end=b["end"])
            del C[k + 1]
            del lk[k + 1]
            log.append(dict(action="merge", at=round(a["end"], 2), text=merged, filler=ea or sb))
            continue
        if sb and fits(a["text"] + sb):
            t = _cue_time(b, len(sb))
            C[k] = dict(a, text=a["text"] + sb, end=t)
            C[k + 1] = dict(b, text=b["text"][len(sb):].lstrip(), start=t)
            log.append(dict(action="move-back", at=round(t, 2), filler=sb))
        elif ea and fits(ea + b["text"]):
            t = _cue_time(a, len(a["text"]) - len(ea))
            C[k] = dict(a, text=a["text"][:-len(ea)].rstrip(), end=t)
            C[k + 1] = dict(b, text=ea + b["text"], start=t)
            log.append(dict(action="move-forward", at=round(t, 2), filler=ea))
        else:
            log.append(dict(action="left", at=round(a["end"], 2), filler=ea or sb, text=a["text"] + " | " + b["text"]))
        k += 1
    return C, log


# ------------------------------------------------------------------ main
# ------------------------------------------------------------------ guess flags (a human must look)
GUESS_MIN = 0.8          # sound-alike score a caption fix needs (without glossary support) not to be a guess
_PINYIN_FN = None


def _pinyin_backend():
    """text -> [toneless pinyin syllable per CJK character] or None: pypinyin when installed, else the macOS
    Foundation Mandarin->Latin transform (pyobjc), else None (no sound-alike check: CJK swaps count as guesses)."""
    global _PINYIN_FN
    if _PINYIN_FN is not None:
        return _PINYIN_FN or None
    fn = False
    try:
        from pypinyin import lazy_pinyin  # type: ignore

        def fn(s):
            return [x.lower() for x in lazy_pinyin(s)]
    except Exception:  # noqa: BLE001
        try:
            from Foundation import NSString  # type: ignore  (macOS)

            def fn(s):
                t = NSString.stringWithString_(s)
                t = t.stringByApplyingTransform_reverse_("Any-Latin; Latin-ASCII", False) or ""
                return [x.lower() for x in str(t).split()]
            if fn("上下文") != ["shang", "xia", "wen"]:
                fn = False
        except Exception:  # noqa: BLE001
            fn = False
    _PINYIN_FN = fn
    return fn or None


def pinyin_of(text):
    """Toneless pinyin of the CJK characters of ``text`` (one syllable each), None when no backend."""
    fn = _pinyin_backend()
    chars = "".join(re.findall(r"[㐀-鿿豈-﫿]", text or ""))
    if not chars:
        return []
    if not fn:
        return None
    out = fn(chars)
    return out if len(out) == len(chars) else None


def _phon(s):
    """Crude latin phonetic key: lowercase letters, c/q/ck -> k, ph/v/w -> f, th/z -> s, every vowel run -> a,
    a silent final e dropped (peer ~ pair, vibe ~ web, rewanking ~ reranking)."""
    s = re.sub(r"[^a-z]", "", (s or "").lower())
    s = re.sub(r"(?<=[^aeiou])e$", "", s)
    for a, b in (("ph", "f"), ("th", "s"), ("ck", "k"), ("q", "k"), ("c", "k"), ("v", "f"), ("w", "f"), ("z", "s"),
                 ("x", "ks")):
        s = s.replace(a, b)
    return re.sub(r"[aeiouy]+", "a", s)


def sound_alike(a, b):
    """0..1 how alike two spoken spans sound, None when it cannot be told (CJK without a pinyin backend).
    CJK vs CJK: per-character pinyin similarity; latin vs latin: spelling or phonetic-key similarity;
    mixed: the pinyin / phonetic keys of both sides compared as one string."""
    a, b = a or "", b or ""
    ca, cb = bool(re.search(r"[㐀-鿿]", a)), bool(re.search(r"[㐀-鿿]", b))
    la, lb = re.sub(r"[^a-z0-9]", "", a.lower()), re.sub(r"[^a-z0-9]", "", b.lower())
    if not ca and not cb:
        if not la or not lb:
            return 0.0
        r = difflib.SequenceMatcher(None, la, lb).ratio()
        return round(max(r, difflib.SequenceMatcher(None, _phon(la), _phon(lb)).ratio()), 3)
    pa, pb = pinyin_of(a), pinyin_of(b)
    if pa is None or pb is None:
        return None
    if ca and cb and not la and not lb and len(pa) == len(pb):
        return round(sum(difflib.SequenceMatcher(None, x, y).ratio() for x, y in zip(pa, pb)) / len(pa), 3)
    ka = _phon("".join(pa) + la)
    kb = _phon("".join(pb) + lb)
    return round(difflib.SequenceMatcher(None, ka, kb).ratio(), 3) if ka and kb else 0.0


def _gloss_terms(glossary=None, context=None):
    terms = [str(t) for t in (glossary or {}).get("terms") or []]
    terms += [str(f.get("to", "")) for f in (glossary or {}).get("fixes") or []]
    terms += [str(t) for t in (context or {}).get("glossary") or []]
    pairs = {(str(f.get("from", "")).lower(), str(f.get("to", "")).lower()) for f in (glossary or {}).get("fixes") or []}
    return {t.strip().lower() for t in terms if t and t.strip()}, pairs


def guess_check(change, glossary=None, context=None, min_score=GUESS_MIN):
    """(guess: bool, support: str) for one caption change. term_fix / glossary changes are the creator's or the
    validated source glossary: never guesses. An LLM change is supported when every swapped span is a glossary
    confusion / lands on a glossary term, or sounds alike with score >= min_score; else it is a guess."""
    src = change.get("source")
    if src in ("term_fix", "glossary", "entity"):
        return False, src
    spans = change.get("diff") or [list(x) for x in diff_spans(change.get("before", ""), change.get("after", ""))]
    spans = [(o or "", n or "") for o, n in spans if (o or n)]
    if not spans:
        return False, "no change"
    terms, pairs = _gloss_terms(glossary, context)
    notes, guess = [], False
    for o, n in spans:
        ol, nl = o.strip().lower(), n.strip().lower()
        if (ol, nl) in pairs:
            notes.append(f"{o}->{n}: glossary confusion")
            continue
        sc = sound_alike(o, n)
        if nl in terms and (sc is None or sc >= 0.5):
            notes.append(f"{o}->{n}: glossary term" + (f", sounds {sc:.2f}" if sc is not None else ""))
            continue
        if sc is not None and sc >= min_score:
            notes.append(f"{o}->{n}: sound-alike {sc:.2f}")
            continue
        guess = True
        notes.append(f"{o}->{n}: " + ("cannot check the sound (no pinyin)" if sc is None else
                                       f"weak sound match {sc:.2f}, not in the glossary"))
    return guess, "; ".join(notes)


def flag_guesses(changes, glossary=None, context=None, min_score=GUESS_MIN):
    """Mark every change in place with ``guess`` (bool) + ``support`` (why it is / is not trusted). An
    ``llm-propagated`` change inherits the verdict of the fix it copies. Returns the number of guesses."""
    n = 0
    pairs = set()
    for c in changes or []:
        for o, nw in (c.get("diff") or diff_spans(c.get("before", ""), c.get("after", ""))):
            if o and nw:
                pairs.add((o.strip().lower(), nw.strip().lower()))
    for c in changes or []:
        g, why = guess_check(c, glossary, context, min_score)
        if c.get("source") not in ("term_fix", "glossary"):
            flip = [f"{o}<->{nw}" for o, nw in (c.get("diff") or diff_spans(c.get("before", ""), c.get("after", "")))
                    if o and nw and (nw.strip().lower(), o.strip().lower()) in pairs]
            if flip:
                g, why = True, why + "; contradicts another fix in this job (" + ", ".join(flip) + ")"
        c["guess"], c["support"] = g, why
        n += g
    return n


def proofread(cues, term_fixes=None, provider="auto", model=None, context=None, heard=None, words=None,
              low_conf=0.5, call=None, prices=None, chunk=120, glossary=None, propagate=True, passes=2, cache=None,
              locked=None, entities=True):
    """cues: [{start, end, text}] (or ``subs.Cue``). Returns dict(cues, changes, rejected, low_confidence,
    fillers_left, provider, model, usage, cost_usd, cache). Never changes timing or the number of cues.

    Order: (1) ``term_fixes`` (the creator's list; a fix that deletes spoken words is applied but logged in
    ``warnings``), (2) ``glossary`` fixes (``build_glossary``: one per source, the same on every job), (3) the
    named-entity check (``vstudio.entities``: CLDR place names / cities / glossary spellings, ``entities``: False
    off, or a locale such as "zh_Hant"), (4) the LLM per-cue pass with the glossary in its context, every fix
    through ``_valid`` (``faithful``), (5) an accepted LLM fix of a term is applied to the job's other cues holding the same span (``llm-propagated``).

    ``cache`` (a ``CueCache`` or a directory): the LLM result of every cue is stored under its normalized ASR text
    + ``context_hash`` (prompt, provider / model, glossary, term fixes, topic); a cue seen before is NOT sent again
    - only new / changed cue texts go to the LLM, so a re-cut never re-rolls the corrections of unchanged cues.
    ``locked``: cue indices the creator fixed by hand (``job edit --op caption``): never touched here."""
    C = [_cue_dict(c) for c in cues]
    locked = {int(i) for i in locked or ()}
    raw = [c["text"] for c in C]
    changes, rejected, warnings = [], [], []
    term_fixes = ascii_boundaries(term_fixes)
    for i, c in enumerate(C):
        if i in locked:
            continue
        new = asr.apply_term_fixes(c["text"], term_fixes or None)
        if new != c["text"]:
            bad = faithful(c["text"], new)
            changes.append(dict(i=i, start=c["start"], end=c["end"], before=c["text"], after=new, source="term_fix",
                                why="term fix"))
            if bad:
                warnings.append(dict(i=i, before=c["text"], after=new, source="term_fix",
                                     reason=f"{bad} - kept: the creator's own term fix"))
            c["text"] = new
    gfix = list((glossary or {}).get("fixes") or [])
    protected = {i: [] for i in range(len(C))}
    for ch in changes:
        protected[ch["i"]] += [n for _, n in diff_spans(ch["before"], ch["after"]) if n]
    # what the creator says they say is never re-"fixed": the term-fix targets (also when the captions arrive with
    # them already applied upstream), the creator's glossary and the glossary's targets
    keep_terms = [str(f[1]) for f in term_fixes or [] if isinstance(f, (list, tuple)) and len(f) > 1
                  and str(f[1]).strip() and not re.search(r"\\\d|\\g<", str(f[1]))]
    keep_terms += [str(g) for g in (context or {}).get("glossary") or [] if str(g).strip()]
    keep_terms += [f["to"] for f in (glossary or {}).get("fixes") or []]
    keep_terms = sorted({t.strip() for t in keep_terms if len(t.strip()) >= 2}, key=len, reverse=True)
    for i, c in enumerate(C):
        if i in locked:
            continue
        new = apply_glossary(c["text"], gfix)
        if new != c["text"]:
            bad = faithful(c["text"], new)
            if bad:                                    # a glossary fix colliding with a term fix: skip it here
                rejected.append(dict(i=i, text=c["text"], to=new, source="glossary", reason=bad))
                continue
            used = [f"{f['from']} -> {f['to']}" for f in gfix if _pattern(f["from"]).search(c["text"])]
            changes.append(dict(i=i, start=c["start"], end=c["end"], before=c["text"], after=new, source="glossary",
                                why="glossary: " + "; ".join(used)))
            protected[i] += [n for _, n in diff_spans(c["text"], new) if n]
            c["text"] = new
    # named entities (vstudio.entities): place names that sound like the CLDR / city standard but are spelled
    # otherwise (宏都拉斯 -> 洪都拉斯), glossary spellings; the same fixes every job of the source gets
    ents = None
    if entities is not False:
        from . import entities as ENT
        alltext = "\n".join(c["text"] for c in C)
        ents = ENT.verify(alltext, locale=entities if isinstance(entities, str) else entity_locale(alltext),
                          glossary=[t for t in keep_terms if re.search(r"[A-Za-z]", t)])
        efix = [f for f in ents["fixes"] if not any(f["from"] in t and f["from"] != t for t in keep_terms)]
        for i, c in enumerate(C):
            if i in locked or not efix:
                continue
            new = ENT.fix_text(c["text"], efix)
            if new != c["text"]:
                bad = faithful(c["text"], new)
                if bad:
                    rejected.append(dict(i=i, text=c["text"], to=new, source="entity", reason=bad))
                    continue
                used = [f"{f['from']} -> {f['to']}" for f in efix if f["from"] in c["text"]]
                changes.append(dict(i=i, start=c["start"], end=c["end"], before=c["text"], after=new, source="entity",
                                    why="entity: " + "; ".join(used)))
                protected[i] += [n for _, n in diff_spans(c["text"], new) if n]
                c["text"] = new
    prov = "custom" if call else resolve_provider(provider)
    mdl = model or default_model(prov)
    low = low_confidence(list(words or ()) + list(heard or ()), C, low_conf)
    usage = dict(input=0, output=0)
    ctx = dict(context or {})
    if gfix:
        ctx["confusions"] = [(f["from"], f["to"]) for f in gfix]
        ctx["glossary"] = list(ctx.get("glossary") or []) + list((glossary or {}).get("terms") or [])
    accepted = []
    cstat = dict(hits=0, sent=0, stored=0)
    if prov != "none" and C:
        fn = call or _call_llm(prov)
        cc = CueCache(cache) if isinstance(cache, str) else cache
        ch = context_hash(prov, mdl, glossary, term_fixes, context, passes) if cc is not None else None
        pre = {i: c["text"] for i, c in enumerate(C)}
        todo = []
        for i, c in enumerate(C):
            if i in locked:
                continue
            hit = cc.get(cue_key(raw[i], ch)) if cc is not None else None
            if hit and hit.get("pre") == c["text"]:
                c["text"] = hit["text"]
                for x in hit.get("changes") or []:
                    x = dict(x, i=i, start=c["start"], end=c["end"], cached=True)
                    changes.append(x)
                    accepted += [(o, n) for o, n in (x.get("diff") or []) if o and n]
                cstat["hits"] += 1
            else:
                todo.append(i)
        cstat["sent"] = len(todo)
        failed = set()
        for rnd, k0 in [(r, k) for r in range(max(1, int(passes))) for k in range(0, len(todo), chunk)]:   # recall
            idx = todo[k0:k0 + chunk]
            part = [C[i] for i in idx]
            plow = [dict(x, i=idx.index(x["i"])) for x in low if x["i"] in idx]
            parsed = None
            for attempt in range(2):                      # one retry on a broken reply, then glossary-only
                try:
                    text, u = fn(SYSTEM, _prompt(part, ctx, heard, plow), mdl)
                    usage["input"] += int(u.get("input", 0))
                    usage["output"] += int(u.get("output", 0))
                    parsed = _parse(text)
                    break
                except Exception as e:  # noqa: BLE001  (timeouts / rate limits / broken JSON: retry once, then degrade)
                    warnings.append(dict(source="provider",
                                         message=f"chunk {k0}: {type(e).__name__}: {str(e)[:160]} (attempt {attempt + 1})"))
            if parsed is None:
                warnings.append(dict(source="provider", message=f"chunk {k0}: gave up, glossary/term fixes only"))
                failed |= set(idx)
                continue
            for fx in parsed:
                try:
                    j = int(fx.get("i"))
                except (TypeError, ValueError):
                    rejected.append(dict(fx, reason="no caption index"))
                    continue
                if not (0 <= j < len(idx)):
                    rejected.append(dict(fx, reason="caption index out of range"))
                    continue
                i = idx[j]
                c = C[i]
                if rnd and str(fx.get("to") or "") and str(fx.get("to")) in c["text"] and \
                        _locate(c["text"], str(fx.get("from") or "")) is None:
                    continue                          # the first look already made this fix
                bad = _valid(c["text"], fx)
                loc = _locate(c["text"], str(fx.get("from") or "")) if not bad else None
                if not bad and loc and any(_overlaps(c["text"], loc, p) for p in protected.get(i, [])):
                    bad = "already fixed by the term fixes / glossary"
                if not bad and loc and any(_overlaps(c["text"], loc, t) and t not in str(fx.get("to") or "")
                                           for t in keep_terms):
                    bad = "touches a term the creator listed (term fixes / glossary)"
                if bad:
                    rejected.append(dict(i=i, text=c["text"], **{k: fx.get(k) for k in ("from", "to", "why")},
                                         reason=bad))
                    continue
                before = c["text"]
                fx = dict(fx, **{"from": _locate(before, str(fx["from"]))})
                c["text"] = _swap(before, before.find(fx["from"]), fx["from"], fx["to"])
                spans = diff_spans(before, c["text"])
                accepted += [(o, n) for o, n in spans if o and n]
                changes.append(dict(i=i, start=c["start"], end=c["end"], before=before, after=c["text"], source="llm",
                                    why=str(fx.get("why") or ""), span=[fx["from"], fx["to"]], diff=spans))
        if cc is not None:
            for i in todo:
                if i in failed:
                    continue                          # a failed call is never remembered as "no change"
                mine = [{k: v for k, v in x.items() if k not in ("i", "start", "end")} for x in changes
                        if x["i"] == i and x["source"] == "llm"]
                cc.put(cue_key(raw[i], ch), dict(pre=pre[i], text=C[i]["text"], changes=mine))
                cstat["stored"] += 1
    if propagate:
        for o, n in dict.fromkeys(accepted):
            if not _term_like(o):
                continue
            pat = _pattern(o)
            for i, c in enumerate(C):
                m = pat.search(c["text"]) if i not in locked else None
                if not m:
                    continue
                bad = _valid(c["text"], {"from": o, "to": n})
                if bad:
                    rejected.append(dict(i=i, text=c["text"], **{"from": o, "to": n}, source="llm-propagated",
                                         reason=bad))
                    continue
                before = c["text"]
                c["text"] = _swap(before, m.start(), o, n)
                changes.append(dict(i=i, start=c["start"], end=c["end"], before=before, after=c["text"],
                                    source="llm-propagated", why=f"same fix as elsewhere: {o} -> {n}"))
    flag_guesses(changes, glossary, context)
    fb = next((x.get("fallback") for x in getattr(fn, "results", None) or [] if x and x.get("fallback")), None) \
        if prov != "none" and C else None
    return dict(cues=C, changes=changes, rejected=rejected, warnings=warnings, low_confidence=low, fallback=fb,
                entities=None if ents is None else dict(locale=ents["locale"], fixes=ents["fixes"],
                                                        flagged=ents["flagged"], found=ents["entities"]),
                fillers_left=caption_fillers(C), provider=prov, model=mdl if prov != "none" else None, usage=usage,
                cost_usd=cost_usd(mdl, usage, prices, prov) if prov not in ("none",) else 0.0,
                glossary=dict(fixes=len(gfix), terms=len((glossary or {}).get("terms") or [])), cache=cstat,
                locked=sorted(locked))


# ------------------------------------------------------------------ per-cue cache (no re-roll on a re-cut)
def norm_cue(text):
    """The cache form of a cue text: whitespace collapsed, case kept (RAG vs rag is a real difference)."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def context_hash(provider, model, glossary=None, term_fixes=None, context=None, passes=2):
    """Everything besides the cue text that shapes the LLM's answer for a cue: the prompt, provider / model, the
    source glossary, the term fixes, the topic and the creator's term list (not the notes / re-hearing hints)."""
    import hashlib
    ctx = context or {}
    d = [SYSTEM, provider, model, sorted((f.get("from"), f.get("to")) for f in (glossary or {}).get("fixes") or []),
         sorted(str(t) for t in (glossary or {}).get("terms") or []), [list(f) if isinstance(f, (list, tuple)) else f
                                                                        for f in term_fixes or []],
         ctx.get("topic"), [str(g) for g in ctx.get("glossary") or []], int(passes), 1]
    return hashlib.sha1(json.dumps(d, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def cue_key(text, ctx_hash):
    import hashlib
    return hashlib.sha1(f"{norm_cue(text)}\0{ctx_hash}".encode()).hexdigest()


class CueCache:
    """Proofread results per cue on disk: ``<root>/<key[:2]>/<key>.json`` = {pre, text, changes}. One small file
    per cue (atomic writes): jobs proofreading in parallel never clobber each other."""

    def __init__(self, root):
        self.root = root

    def _path(self, key):
        return os.path.join(self.root, key[:2], key + ".json")

    def get(self, key):
        try:
            with open(self._path(key), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def put(self, key, value):
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, p)


__all__ = ["proofread", "resolve_provider", "low_confidence", "caption_fillers", "words_of", "SYSTEM",
           "GLOSSARY_SYSTEM", "build_glossary", "apply_glossary", "check_glossary_fix", "faithful", "faithful_swap",
           "diff_spans", "tokens", "fix_filler_edges", "flag_guesses", "guess_check", "sound_alike", "pinyin_of",
           "CueCache", "cue_key", "context_hash", "norm_cue"]
