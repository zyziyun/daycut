"""Bilingual captions (中英): source-language cues + a translated second line, per-language SRT / VTT tracks.

    from vstudio import bilingual as BL
    cues = BL.translate_cues(cues, "en", "zh")                    # alt = the Chinese line (LLM, cached)
    cues = BL.apply_mode(cues, "bilingual")                       # mono | bilingual | translated
    cues = BL.highlight(cues, ["break the ice"])                  # language-learning mode: the target phrase
    BL.write_tracks(cues, "out/clip01", "en", "zh")               # clip01.en.srt/.vtt, clip01.zh.srt/.vtt, .bi.srt

    python -m vstudio.bilingual translate cues.json --from en --to zh [--mode bilingual] [--out cues.bi.json]
    python -m vstudio.bilingual tracks cues.bi.json --from en --to zh --stem out/clip01

Translation goes through ``vstudio.llm`` task ``translate`` (persona / client ``llm.tasks.translate`` or
``llm.default``, its ``fallback`` chain: claude-code -> codex -> ...). Lines go in numbered batches and come back
one translation per line, so a cue never borrows its neighbour's words. Before translating, the source text gets
the persona ``subtitles.term_fixes`` (ASR mis-hearings); the glossary (persona ``subtitles.glossary``
{source term: target term} + the job's own terms) is given to the model and then enforced: a glossary term that
came back untranslated is swapped for its target, one that is missing is reported in ``info["glossary_misses"]``.
Results are cached (``cache=`` path, keyed by text + languages + glossary), so a re-render never pays twice. When
every provider fails (or none is configured) ``info["error"]`` says why and the cues keep an empty ``alt``; callers
that were asked for bilingual captions stop with that error (``clipkit.TranslationError``) - never a silent mono.

Display (``vstudio.export`` burns cues per platform): ``text`` is the main line, ``alt`` the smaller second line in
the theme's secondary ink over video (``theme.over_ink2``). Modes: ``mono`` (source only), ``bilingual`` (source +
translation), ``translated`` (translation only, as the main line).
"""
import argparse
import hashlib
import json
import os
import re
import sys

from . import subs as S

MODES = ("mono", "bilingual", "translated")
LANG_NAMES = {"zh": "Simplified Chinese (简体中文)", "en": "English", "ja": "Japanese", "ko": "Korean",
              "fr": "French", "es": "Spanish", "de": "German"}
BATCH = 40
_CJK = re.compile(r"[㐀-鿿豈-﫿]")

SYSTEM = """You translate video captions from {src} to {tgt} for a short-video audience (subtitles under a \
speaker). Rules:
- Translate EVERY numbered line on its own, in order: exactly one translation per input line, same numbering. A \
line may be a sentence fragment that continues on the next line - translate the fragment, do not move words between \
lines, never merge or split lines.
- Natural spoken {tgt}, short enough to read in the time of the line; keep the speaker's register (a teacher, a \
guest on a podcast). No explanations, no quotes around lines, no notes.
- Keep proper nouns, product names, code and numbers as they are unless the glossary says otherwise.
- Glossary (always use these renderings): {glossary}
{context}Return JSON: {{"lines": [{{"n": <line number>, "t": "<translation>"}}, ...]}}"""

SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {
    "type": "object", "properties": {"n": {"type": "integer"}, "t": {"type": "string"}}, "required": ["n", "t"]}}},
    "required": ["lines"]}


# --------------------------------------------------------------------------- glossary
def _persona_subs():
    try:
        from .config import persona
        return (persona() or {}).get("subtitles") or {}
    except Exception:                                   # noqa: BLE001 - no persona = no glossary
        return {}


def glossary(extra=None, src=None, tgt=None):
    """{source term: target term}: persona ``subtitles.glossary`` (flat, or nested per pair ``{"en-zh": {...}}``)
    + ``extra`` (the job's own terms; extra wins)."""
    g = {}
    pg = _persona_subs().get("glossary") or {}
    pair = f"{src}-{tgt}" if src and tgt else None
    for k, v in pg.items():
        if isinstance(v, dict):
            if pair and k == pair:
                g.update({str(a): str(b) for a, b in v.items() if a and b})
        elif k and v:
            g[str(k)] = str(v)
    for k, v in (extra or {}).items():
        if k and v:
            g[str(k)] = str(v)
    return g


def _in(term, text):
    if re.match(r"[A-Za-z]", term or ""):
        return re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", text or "", re.I) is not None
    return bool(term) and term in (text or "")


def enforce_glossary(src_text, translation, gl):
    """-> (translation, misses). A glossary source term that appears in the source line must appear as its target in
    the translation: left untranslated -> swapped; absent -> reported (never guessed)."""
    misses = []
    out = translation or ""
    for a, b in (gl or {}).items():
        if not _in(a, src_text) or _in(b, out):
            continue
        if _in(a, out):
            out = re.sub(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", b, out, flags=re.I) \
                if re.match(r"[A-Za-z]", a) else out.replace(a, b)
        else:
            misses.append(dict(term=a, want=b, line=src_text))
    return out, misses


# --------------------------------------------------------------------------- cache
def _key(text, src, tgt, gl):
    h = hashlib.sha1(json.dumps([text, src, tgt, sorted((gl or {}).items())], ensure_ascii=False).encode())
    return h.hexdigest()[:20]


def _load_cache(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def _save_cache(path, data):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)


# --------------------------------------------------------------------------- translation
def _llm_call(provider=None, config=None):
    """-> fn(system, prompt) -> (parsed json or None, info) through vstudio.llm (route + fallback chain)."""
    from . import llm as LLM

    def fn(system, prompt):
        r = LLM.complete("translate", system, prompt, schema=SCHEMA, provider=provider, config=config,
                         temperature=0.2, max_tokens=8000, cli_timeout=180)
        return r.get("json"), {k: r.get(k) for k in ("provider", "model", "fallback", "cost_usd")}
    return fn


def _parse_lines(js, n):
    out = [None] * n
    rows = (js or {}).get("lines") if isinstance(js, dict) else js
    for r in rows or []:
        if isinstance(r, dict):
            try:
                k = int(r.get("n")) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= k < n and isinstance(r.get("t"), str):
                out[k] = r["t"].strip()
    return out


def translate_texts(texts, src, tgt, gl=None, provider=None, config=None, context="", cache=None, call=None,
                    batch=BATCH):
    """-> (translations [str, "" when missing], info {provider, translated, cached, missing, glossary_misses,
    error}). ``call``: fn(system, prompt) -> (json, info) (tests / a fixed provider); default ``vstudio.llm``."""
    gl = glossary(gl, src, tgt) if gl is None or isinstance(gl, dict) else gl
    store = _load_cache(cache)
    out = [""] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        t = (t or "").strip()
        if not t:
            continue
        k = _key(t, src, tgt, gl)
        if k in store:
            out[i] = store[k]
        else:
            todo.append(i)
    info = dict(provider=None, translated=0, cached=len([x for x in out if x]), missing=0, glossary_misses=[],
                error=None, calls=[])
    if todo:
        fn = call or _llm_call(provider, config)
        gtxt = "; ".join(f"{a} -> {b}" for a, b in gl.items()) or "(none)"
        system = SYSTEM.format(src=LANG_NAMES.get(src, src), tgt=LANG_NAMES.get(tgt, tgt), glossary=gtxt,
                               context=(f"Context: {context.strip()}\n" if context and context.strip() else ""))
        for b0 in range(0, len(todo), batch):
            idx = todo[b0:b0 + batch]
            prompt = "\n".join(f"{k + 1}. {texts[i].strip()}" for k, i in enumerate(idx))
            try:
                js, ci = fn(system, prompt)
            except Exception as e:  # noqa: BLE001 - every provider failed: mono captions, said out loud
                info["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                break
            info["calls"].append(ci)
            info["provider"] = info["provider"] or (ci or {}).get("provider")
            got = _parse_lines(js, len(idx))
            if (ci or {}).get("provider") == "none" and not any(got):
                info["error"] = "no translation provider configured (llm.tasks.translate / llm.default)"
                break
            for k, i in enumerate(idx):
                t = got[k]
                if not t:
                    continue
                t, miss = enforce_glossary(texts[i], t, gl)
                info["glossary_misses"] += miss
                out[i] = t
                store[_key(texts[i].strip(), src, tgt, gl)] = t
                info["translated"] += 1
        _save_cache(cache, store)
    info["missing"] = sum(1 for t, o in zip(texts, out) if (t or "").strip() and not o)
    return out, info


def translate_cues(cues, src, tgt, gl=None, fix_terms=True, **kw):
    """Cues (``subs.Cue`` or dicts) -> new cues whose ``alt`` is the translation (source text term-fixed first).
    Returns (cues, info)."""
    cs = [c if isinstance(c, S.Cue) else S.Cue.from_dict(c) for c in cues]
    texts = []
    for c in cs:
        t = S.strip_markup(c.text)
        if fix_terms:
            try:
                from .asr import apply_term_fixes
                t = apply_term_fixes(t, clean=False)
            except Exception:                           # noqa: BLE001
                pass
        texts.append(t)
    tr, info = translate_texts(texts, src, tgt, gl, **kw)
    out = [S.Cue(c.start, c.end, c.text, t or "", dict(c.meta, lang=src, alt_lang=tgt)) for c, t in zip(cs, tr)]
    return out, info


def apply_mode(cues, mode="bilingual"):
    """mono: drop ``alt``; bilingual: keep it; translated: the translation becomes the main line (cues without one
    keep their source text, so nothing goes silent)."""
    if mode not in MODES:
        raise ValueError(f"caption mode {mode!r}: {' | '.join(MODES)}")
    out = []
    for c in cues:
        if mode == "mono":
            out.append(S.Cue(c.start, c.end, c.text, "", dict(c.meta)))
        elif mode == "translated":
            out.append(S.Cue(c.start, c.end, c.alt or c.text, "", dict(c.meta)))
        else:
            out.append(S.Cue(c.start, c.end, c.text, c.alt, dict(c.meta)))
    return out


# --------------------------------------------------------------------------- language learning
def highlight(cues, phrases, field="text"):
    """Wrap every occurrence of the target ``phrases`` in 【】 (case-insensitive, whole words for latin), so the
    burned caption shows the phrase the way the theme emphasises keywords. Cues that already carry markup keep it."""
    phrases = sorted({p.strip() for p in phrases or [] if p and p.strip()}, key=len, reverse=True)
    if not phrases:
        return list(cues)
    rx = re.compile("|".join((r"(?<![A-Za-z])" + re.escape(p) + r"(?![A-Za-z])") if re.match(r"[A-Za-z]", p)
                             else re.escape(p) for p in phrases), re.I)
    out = []
    for c in cues:
        c = S.Cue(c.start, c.end, c.text, c.alt, dict(c.meta))
        v = getattr(c, field)
        if v and "【" not in v and "**" not in v:
            setattr(c, field, rx.sub(lambda m: f"【{m.group(0)}】", v))
        out.append(c)
    return out


# --------------------------------------------------------------------------- files
def write_tracks(cues, stem, src, tgt=None, wrap=None):
    """Per-language sidecar tracks: ``<stem>.<src>.srt/.vtt`` (the source line), ``<stem>.<tgt>.srt/.vtt`` (the
    translation) and ``<stem>.bi.srt`` (both lines) when there is a translation. Returns {lang: {srt, vtt}}."""
    os.makedirs(os.path.dirname(os.path.abspath(stem)) or ".", exist_ok=True)
    cs = [c if isinstance(c, S.Cue) else S.Cue.from_dict(c) for c in cues]
    out = {}
    out[src] = dict(srt=f"{stem}.{src}.srt", vtt=f"{stem}.{src}.vtt")
    S.srt_write(cs, out[src]["srt"], which="text", wrap=wrap, trailing_newline=True)
    S.vtt_write(cs, out[src]["vtt"], which="text", wrap=wrap)
    if tgt and any(c.alt.strip() for c in cs):
        out[tgt] = dict(srt=f"{stem}.{tgt}.srt", vtt=f"{stem}.{tgt}.vtt")
        S.srt_write(cs, out[tgt]["srt"], which="alt", trailing_newline=True)
        S.vtt_write(cs, out[tgt]["vtt"], which="alt")
        out["bi"] = dict(srt=f"{stem}.bi.srt")
        S.srt_write(cs, out["bi"]["srt"], which="both", wrap=wrap, trailing_newline=True)
    return out


def other_lang(lang):
    return "en" if (lang or "zh").startswith("zh") else "zh"


def detect_lang(texts):
    s = "".join(texts or [])
    return "zh" if len(_CJK.findall(s)) > 0.2 * max(1, len(re.sub(r"\s", "", s))) else "en"


# --------------------------------------------------------------------------- CLI
def _cli(argv=None):
    from .export import load_cues
    ap = argparse.ArgumentParser(prog="python -m vstudio.bilingual", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("translate", help="cues.json / .srt -> cues with a translated alt line")
    t.add_argument("cues")
    t.add_argument("--from", dest="src", default=None)
    t.add_argument("--to", dest="tgt", default=None)
    t.add_argument("--mode", default="bilingual", choices=MODES)
    t.add_argument("--term", action="append", default=[], help="glossary entry 'source=target' (repeatable)")
    t.add_argument("--highlight", action="append", default=[], help="target phrase to emphasise (repeatable)")
    t.add_argument("--provider", default=None)
    t.add_argument("--cache", default=None)
    t.add_argument("--out", default=None)
    t.add_argument("--stem", default=None, help="also write <stem>.<lang>.srt/.vtt tracks")
    k = sub.add_parser("tracks", help="cues (with alt) -> per-language SRT / VTT")
    k.add_argument("cues")
    k.add_argument("--from", dest="src", required=True)
    k.add_argument("--to", dest="tgt", default=None)
    k.add_argument("--stem", required=True)
    a = ap.parse_args(argv)
    cues = load_cues(a.cues)
    if a.cmd == "tracks":
        print(json.dumps(write_tracks(cues, a.stem, a.src, a.tgt), ensure_ascii=False, indent=1))
        return 0
    src = a.src or detect_lang([c.text for c in cues])
    tgt = a.tgt or other_lang(src)
    gl = dict(x.split("=", 1) for x in a.term if "=" in x)
    cache = a.cache or (os.path.splitext(a.out or a.cues)[0] + ".translate-cache.json")
    cs, info = translate_cues(cues, src, tgt, gl, provider=a.provider, cache=cache)
    shown = highlight(apply_mode(cs, a.mode), a.highlight)
    out = a.out or os.path.splitext(a.cues)[0] + f".{a.mode}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(dict(cues=[c.to_dict() for c in shown], lang=src, alt_lang=tgt, mode=a.mode), f, ensure_ascii=False,
                  indent=1)
    res = dict(out=out, src=src, tgt=tgt, **{k2: v for k2, v in info.items() if k2 != "calls"})
    if a.stem:
        res["tracks"] = write_tracks(cs, a.stem, src, tgt)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if not info.get("error") else 3


if __name__ == "__main__":
    sys.exit(_cli())
