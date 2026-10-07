"""``plan-segments``: a long recording's transcript -> candidate short-video segments (``segments.draft.yaml``).

    python -m vstudio.batch plan-segments --source lecture.mp4 [--transcript work/audio16k.json] [--client acme]
        [--count 12] [--min 40 --max 150] [--platforms xiaohongshu:full,douyin] [--provider auto|claude|openai|none]

Each candidate: ``{id, start, end, title, chapter, hook {start, end, text}, hook_candidates [...], notes [...],
tags [...], why, risk, score}`` - times in source seconds on word edges (a start at a word onset, an end over the
last word's end, never inside a word: sentences come from ``vstudio.cleanup.load_words``, edges from
``cleanup.snap_range``). The draft is a segments.yaml (``source:`` header + ``segments:``) that ``plan`` /
``longform-split`` / ``longform-slices`` read as is; ``hook_candidates`` feed ``job edit --op hook``.

Transcript: ``--transcript`` (whisper JSON, a ``vstudio.asr`` cache file, ...) or ``vstudio.asr.transcribe`` of the
source, stored in the shared per-source cache (``transcripts.py``) the batch ``asr`` stage reads, so a batch
planned from the draft does not transcribe again.

Providers:
  none    rule based, offline: sentences from pauses + punctuation; topic shifts by lexical cohesion between
          neighbouring sentence blocks (TextTiling) + long pauses -> chapters; every window of whole sentences
          within [min, max] is scored on keyword density (tf-idf of recurring terms), self-containedness (no
          opening connective / back-reference, ends on a complete sentence with a pause after, no topic shift
          inside, not followed by its own conclusion), filler ratio and speech share; the best non-overlapping
          windows win (spread over chapters). Titles / hooks / notes are extractive (the most informative
          sentence / clause, cut to the title limit).
  auto    the configured ``vstudio.llm`` route for task ``segment_plan`` (client / persona ``llm.tasks.segment_plan``
          or ``llm.default``, env VSTUDIO_LLM_SEGMENT_PLAN_PROVIDER ...), else claude with ANTHROPIC_API_KEY, else none.
  claude  anthropic SDK (imported lazily), ``claude-opus-5-5``; only with ANTHROPIC_API_KEY (``auto`` picks it).
  openai  only when named; OPENAI_API_KEY; ``gpt-4.1`` (``--model``).
  any other ``vstudio.llm`` provider (deepseek, qwen, kimi, glm, openrouter, ollama, lmstudio, vllm, llamacpp,
          gemini, claude-code, codex, openai-compatible): see references/PROVIDERS.md.
  The LLM sees numbered sentences with times and returns sentence-index ranges (so edges are always sentence /
  word edges), titles within the platform limit, hook alternatives, notes, tags, why / risk. Too few or
  invalid picks are filled from the rule-based ranking; hook text is always the transcript of the hook range
  (captions must match the audio).

Title rules: ``vstudio.publish.title_max`` of every target platform (小红书 counts CJK = 1, latin = 0.5).
Length window: ``--min/--max``, else the platforms' sweet spots (``vstudio.platform``), clamped to 20-150 s.
Client (``--client``): platforms, tag set (preferred tags), glossary (term fixes applied to the planning text),
style (LLM prompt).
"""
import math
import os
import re
import time

from .util import write_json

from vstudio import llm as LLM
from vstudio import messages as MSG

MODELS = {"claude": "claude-opus-5-5", "openai": "gpt-4.1"}
DEFAULT_CLI_TIMEOUT = 120        # s per CLI provider attempt (claude-code / codex): a long transcript needs > 60 s
PRICES = LLM.PRICES
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_LAT = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|[A-Za-z]{2,}")
STOP_CH = set("的了是在我你他她它这那就都也还要会有个们吧啊呢嘛吗呀哦嗯呃额对和与或但而所以因为然后一不没很太更最被把给让从到上下来去说讲看想做能可以得地着过么什怎哪些里中之其")
STOP_LAT = {"the", "and", "but", "this", "that", "what", "just", "they", "there", "then", "when", "with", "have",
            "you", "your", "for", "are", "was", "were", "not", "can", "will", "would", "like", "know", "yeah", "okay",
            "ok", "so", "it", "is", "of", "to", "in", "on", "a", "an", "we", "i", "do", "be", "if", "or", "as",
            "at", "by", "from", "all", "one", "get", "got", "it's", "i'm", "um", "uh", "right", "also", "very",
            "really", "think", "about", "because", "some", "more", "how", "why", "which", "who", "our", "us"}
CONNECT_ZH = ("然后", "所以", "但是", "而且", "因为", "那么", "那", "就是", "就", "对", "嗯", "呃", "另外", "还有", "包括",
              "并且", "或者", "其次", "接着", "同时", "比如说", "也就是说", "这个", "这些", "它", "他们")
CONNECT_EN = ("and", "so", "but", "because", "then", "also", "or", "which", "it", "that", "this", "they")
BACKREF = ("刚才", "刚刚", "上面", "前面", "之前说", "之前讲", "上节课", "上一节", "上次", "刚说", "前边", "如前所述",
           "as i said", "as we said", "earlier", "last time", "previous")
CONCLUDE = ("所以", "因此", "总结", "总之", "也就是说", "换句话说", "结论", "so ", "therefore", "in short")
HOOKY = ("为什么", "怎么", "其实", "一定", "千万", "最", "关键", "核心", "不是", "没有", "坑", "错", "问题", "面试",
         "真正", "本质", "到底", "秘诀", "？", "?", "why", "how", "never", "always", "mistake", "secret", "actually")
GENERIC_ZH = ("东西", "时候", "比如", "问题", "比较", "可能", "应该", "一般", "基本", "其实", "非常", "一些", "这种", "那种",
              "这样", "那样", "玩意", "方式", "情况", "部分", "地方", "时间", "事情", "感觉", "觉得", "知道", "需要",
              "进行", "大家", "我们", "你们", "一个", "一下", "这里", "那里", "现在", "已经", "如果", "的话", "自己",
              "意思", "肯定", "可能", "相关", "里面", "之后", "之前", "怎么", "什么", "为什么", "一样", "所有", "很多",
              "多少", "特别", "主要", "不同", "直接", "然后", "或者", "因为", "所以", "但是", "而且", "还是", "就是",
              "这个", "那个", "那些", "这些", "同学", "老师", "好的", "对吧", "可以", "没有", "不是", "一直", "开始",
              "整个", "具体", "简单", "重要", "一点", "有点", "东东", "感兴趣", "听到", "看到", "讲一下", "说一下",
              "如说", "发现", "希望", "喜欢", "支持", "处理", "常好", "较低", "较高", "大量", "版本", "屏幕")
WEIGHTS = dict(density=0.6, start=0.75, end=0.75, inner=0.15, filler=2.5, share=0.6, length=0.25, tags=0.3, hook=1.0)
FILLERS = {"嗯", "呃", "额", "啊", "哦", "那个", "就是", "然后", "这个", "对", "um", "uh", "like", "you know"}


class PlanError(RuntimeError):
    """Planner not available (missing key / package) or failed."""


# --------------------------------------------------------------------------- transcript
def _term_fix(text, glossary):
    for g in glossary or []:
        w, r = g.get("wrong"), g.get("right")
        if w and r and w != r:
            text = re.sub(re.escape(w), r, text, flags=re.I) if re.match(r"[A-Za-z]", w) else text.replace(w, r)
    return text


def get_transcript(source, transcript=None, language=None, prompt=None, echo=True):
    """-> (transcript dict, path or None, shared-cache sha1 or None)."""
    from . import transcripts as TS
    if transcript:
        return TS.load_any(transcript), os.path.abspath(transcript), None
    from vstudio import asr
    if not source or not os.path.exists(source):
        raise FileNotFoundError(source or "--source")
    sha = asr.file_hash(source)
    path, tr = TS.lookup(sha, language, prompt, "auto")
    if tr is not None:
        return tr, path, sha
    if echo:
        print(f"[plan-segments] transcribing {os.path.basename(source)} (once per recording) ...", flush=True)
    tr = asr.transcribe(source, language=language, prompt=prompt)
    path = TS.save(sha, tr, language, prompt, "auto")
    return tr, path, sha


def sentences_of(W, max_len=25.0):
    """Words (``cleanup.load_words``) -> sentences [{i0, i1, t, te, text, gap_before, gap_after}]; a sentence
    longer than ``max_len`` s is split at its widest internal pause."""
    from vstudio.cleanup import join_words
    out, i0 = [], 0
    spans = []
    for k, w in enumerate(W):
        if w["end"] or k == len(W) - 1:
            spans.append((i0, k))
            i0 = k + 1

    def split(a, b):
        if W[b]["te"] - W[a]["t"] <= max_len or b - a < 4:
            return [(a, b)]
        k = max(range(a, b), key=lambda j: W[j + 1]["t"] - W[j]["te"])
        return split(a, k) + split(k + 1, b)
    for a, b in spans:
        for x, y in split(a, b):
            out.append(dict(i0=x, i1=y, t=W[x]["t"], te=W[y]["te"], text=join_words(W[x:y + 1])))
    for k, s in enumerate(out):
        s["k"] = k
        s["gap_before"] = s["t"] - out[k - 1]["te"] if k else 9.0
        s["gap_after"] = out[k + 1]["t"] - s["te"] if k + 1 < len(out) else 9.0
    return out


# --------------------------------------------------------------------------- terms
def _grams(text):
    t = text.lower()
    out = [w for w in _LAT.findall(t) if w not in STOP_LAT and len(w) >= 2]
    for run in re.findall(r"[㐀-鿿豈-﫿]+", text):
        for n in (2, 3, 4):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if g[0] in STOP_CH or g[-1] in STOP_CH or any(x in g for x in GENERIC_ZH):
                    continue
                out.append(g)
    return out


def term_stats(sents):
    """Recurring terms -> {term: idf}; a CJK n-gram survives only when it is not just a piece of a longer one
    that is almost as frequent (rough unsupervised term extraction)."""
    from collections import Counter
    tf, df = Counter(), Counter()
    per = []
    for s in sents:
        g = _grams(s["text"])
        per.append(Counter(g))
        tf.update(g)
        df.update(set(g))
    keep = {}
    for g, c in tf.items():
        if c < 3 and not (_LAT.fullmatch(g) and c >= 2):
            continue
        if _CJK.match(g):
            longer = [tf[h] for h in tf if len(h) == len(g) + 1 and g in h and tf[h] >= 0.7 * c]
            if longer:
                continue
        keep[g] = math.log((1 + len(sents)) / (1 + df[g])) + 1.0
    return keep, per


def _display(term, text):
    m = re.search(re.escape(term), text, re.I)
    return text[m.start():m.end()] if m else term


# --------------------------------------------------------------------------- topic structure
def topic_boundaries(sents, per, idf, block=6):
    """TextTiling: cosine similarity of the term vectors of the ``block`` sentences before / after each gap;
    depth score + long pauses -> {k: strength 0..1} (a boundary before sentence k)."""
    def vec(a, b):
        v = {}
        for c in per[a:b]:
            for g, n in c.items():
                if g in idf:
                    v[g] = v.get(g, 0.0) + n * idf[g]
        return v

    def cos(u, v):
        if not u or not v:
            return 0.0
        d = sum(x * v.get(g, 0.0) for g, x in u.items())
        return d / (math.sqrt(sum(x * x for x in u.values())) * math.sqrt(sum(x * x for x in v.values())) or 1)
    n = len(sents)
    sim = [1.0] * n
    for k in range(1, n):
        sim[k] = cos(vec(max(0, k - block), k), vec(k, min(n, k + block)))
    depth = [0.0] * n
    for k in range(1, n - 1):
        lp = max(sim[max(1, k - block):k + 1])
        rp = max(sim[k:min(n, k + block + 1)])
        depth[k] = (lp - sim[k]) + (rp - sim[k])
    ds = [d for d in depth if d > 0]
    mu = sum(ds) / len(ds) if ds else 0.0
    sd = math.sqrt(sum((d - mu) ** 2 for d in ds) / len(ds)) if ds else 0.0
    out = {}
    for k in range(1, n):
        s = 0.0
        if depth[k] > mu + 0.5 * sd and depth[k] == max(depth[max(1, k - 2):min(n, k + 3)]):
            s = min(1.0, (depth[k] - mu) / (2 * sd + 1e-6) + 0.4)
        g = sents[k]["gap_before"]
        if g >= 1.5:
            s = max(s, min(1.0, 0.3 + (g - 1.5) * 0.15))
        if s > 0:
            out[k] = round(s, 3)
    return out


def chapters_of(sents, per, idf, bounds, target=None, min_s=120.0):
    """The strongest boundaries, at least ``min_s`` apart (about ``target`` chapters, default one per 4 min)
    -> chapters [{k0, k1, name}] (name: the top terms of the chapter)."""
    total = sents[-1]["te"] - sents[0]["t"] if sents else 0.0
    target = target or max(1, int(total // 240))
    cuts = []
    for k, sc in sorted(bounds.items(), key=lambda x: -x[1]):
        if len(cuts) >= target - 1:
            break
        if all(abs(sents[k]["t"] - sents[c]["t"]) >= min_s for c in cuts) and sents[k]["t"] - sents[0]["t"] >= min_s \
                and total - (sents[k]["t"] - sents[0]["t"]) >= min_s:
            cuts.append(k)
    cuts.sort()
    ch, a = [], 0
    for k in cuts + [len(sents)]:
        ch.append((a, k - 1))
        a = k
    min_sents = 1
    if len(ch) > 1 and ch[-1][1] - ch[-1][0] + 1 < min_sents // 2:
        last = ch.pop()
        ch[-1] = (ch[-1][0], last[1])
    out = []
    for a, b in ch:
        score = {}
        for c in per[a:b + 1]:
            for g, n in c.items():
                if g in idf:
                    score[g] = score.get(g, 0.0) + n * idf[g]
        top = [g for g, _ in sorted(score.items(), key=lambda x: -x[1])]
        text = " ".join(s["text"] for s in sents[a:b + 1])
        names = []
        for g in top:
            if any(g in x or x in g for x in names):
                continue
            names.append(g)
            if len(names) == 2:
                break
        out.append(dict(k0=a, k1=b, name=" · ".join(_display(g, text) for g in names) or f"Part {len(out) + 1}"))
    return out


# --------------------------------------------------------------------------- rule-based ranking
def _starts(text, words):
    t = text.strip().lower()
    return next((w for w in words if t.startswith(w)), None)


def _filler_ratio(W, i0, i1):
    n = i1 - i0 + 1
    f = sum(1 for w in W[i0:i1 + 1] if w["n"] in FILLERS)
    return f / max(1, n)


def rank_windows(W, sents, per, idf, bounds, chapters, min_s, max_s, lang="zh", prefer_tags=()):
    """Every window of whole sentences within [min_s, max_s] -> [(score, k0, k1, parts)] best first."""
    n = len(sents)
    sw = []
    for k, c in enumerate(per):
        sw.append(sum(cnt * idf[g] for g, cnt in c.items() if g in idf))
    pre = [0.0]
    for x in sw:
        pre.append(pre[-1] + x)
    speech = [0.0]
    for s in sents:
        speech.append(speech[-1] + (s["te"] - s["t"]))
    total_dur = max(1.0, sents[-1]["te"] - sents[0]["t"]) if sents else 1.0
    mean_density = pre[-1] / total_dur
    chap_of = {}
    for ci, c in enumerate(chapters):
        for k in range(c["k0"], c["k1"] + 1):
            chap_of[k] = ci
    bpre = [0.0]
    for k in range(n):
        bpre.append(bpre[-1] + (bounds.get(k, 0.0) if bounds.get(k, 0.0) >= 0.5 else 0.0))
    conn = CONNECT_ZH if lang == "zh" else CONNECT_EN
    tagset = [t.lower() for t in prefer_tags or []]
    out = []
    for a in range(n):
        sa = sents[a]
        st_conn = _starts(sa["text"], conn)
        st_back = next((b for b in BACKREF if b in sa["text"].lower()), None)
        start_q = 0.0
        start_q += 0.35 if sa["gap_before"] >= 0.6 else 0.0
        start_q += 0.35 * bounds.get(a, 0.0)
        start_q -= 0.45 if st_conn else 0.0
        start_q -= 0.4 if st_back else 0.0
        for b in range(a, n):
            dur = sents[b]["te"] - sa["t"]
            if dur > max_s:
                break
            if dur < min_s:
                continue
            sb = sents[b]
            density = (pre[b + 1] - pre[a]) / dur / (mean_density or 1.0)
            end_q = 0.3 if sb["gap_after"] >= 0.5 else -0.2
            end_q += 0.3 * bounds.get(b + 1, 0.0)
            nxt = sents[b + 1]["text"] if b + 1 < n else ""
            concl_next = bool(nxt) and any(nxt.strip().lower().startswith(c) for c in CONCLUDE)
            end_q -= 0.3 if concl_next else 0.0
            if re.search(r"[，,、]$", sb["text"].strip()):
                end_q -= 0.2
            inner = bpre[b + 1] - bpre[a + 1]
            fill = _filler_ratio(W, sa["i0"], sb["i1"])
            share = (speech[b + 1] - speech[a]) / dur
            mid = 0.5 * (min_s + max_s)
            lenq = 1.0 - abs(dur - mid) / (max_s - min_s + 1e-6)
            txt = " ".join(s["text"] for s in sents[a:b + 1]).lower()
            tagq = min(1.0, sum(1 for t in tagset if t in txt) / 3.0) if tagset else 0.0
            hook = 0.15 if any(h in txt[:120] for h in HOOKY) else 0.0
            K = WEIGHTS
            score = (K["density"] * min(2.5, density) + K["start"] * start_q + K["end"] * end_q
                     - K["inner"] * min(1.5, inner) - K["filler"] * fill + K["share"] * (share - 0.8)
                     + K["length"] * lenq + K["tags"] * tagq + K["hook"] * hook)
            out.append((score, a, b, dict(density=round(density, 2), start=round(start_q, 2), end=round(end_q, 2),
                                          inner_shift=round(inner, 2), filler=round(fill, 3), share=round(share, 2),
                                          conn=st_conn, backref=st_back, concl_next=concl_next,
                                          chapter=chap_of.get(a))))
    out.sort(key=lambda x: -x[0])
    return out


def select(ranked, count, n_chapters, overlap=0.0):
    """Greedy best-first non-overlapping picks, at most ceil(count / chapters) + 1 per chapter on the first pass."""
    per_ch = max(1, math.ceil(count / max(1, n_chapters)) + 1)
    chosen, used = [], {}
    for relax in (False, True):
        for c in ranked:
            if len(chosen) >= count:
                break
            _, a, b, parts = c
            if any(not (b < x[1] or a > x[2]) for x in chosen):
                continue
            ch = parts.get("chapter")
            if not relax and used.get(ch, 0) >= per_ch:
                continue
            chosen.append(c)
            used[ch] = used.get(ch, 0) + 1
    return sorted(chosen, key=lambda x: x[1])


# --------------------------------------------------------------------------- copy (extractive)
def title_limit(platforms):
    from vstudio import publish
    from vstudio import platform as PF
    lims = []
    for t in platforms or []:
        try:
            name = PF.parse_targets([t])[0].name
        except Exception:  # noqa: BLE001
            name = t.split(":")[0]
        lims.append((publish.title_max(name), name))
    return min(lims) if lims else (20, "xiaohongshu")


def title_len(t, platform):
    from vstudio import publish
    return publish.title_len(t, platform)


def _strip_fillers(t):
    t = t.strip()
    for _ in range(4):
        t2 = re.sub(r"^(嗯|呃|额|啊|哦|对|那个|就是|然后|这个|所以|那|其实|好|OK|ok|那么|就)[，,、\s]*", "", t)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"[，,、。.\s]*(啊|吧|呢|哈|嘛|对吧|是吧|对不对)?[，,、。.\s]*$", "", t)
    return t.strip()


def shorten(t, limit, platform):
    """Fit a title to the platform limit: the most informative clause(s), else a hard cut."""
    t = _strip_fillers(t)
    if title_len(t, platform) <= limit:
        return t
    parts = [p.strip() for p in re.split(r"[，,；;。.！!？?]", t) if p.strip()]
    best = max(parts, key=lambda p: (title_len(p, platform) <= limit, len(_grams(p)), -abs(len(p) - 12))) \
        if parts else t
    if title_len(best, platform) <= limit:
        return _strip_fillers(best)
    out = ""
    for ch in best:
        if title_len(out + ch, platform) > limit:
            break
        out += ch
    return out.strip()


def _sent_weight(s, c, idf):
    return sum(n * idf.get(g, 0.0) for g, n in c.items())


def pick_title(sents, per, idf, idx, limit, platform, lang="zh"):
    """The most title-like clause of the window: dense in recurring terms (technical latin terms count more), a
    statement or a question, not a conditional / connective opening, no first / second person chatter, about
    6-18 characters; prefixed with the window's top term when it is missing and fits."""
    conn = CONNECT_ZH if lang == "zh" else CONNECT_EN
    cands = []
    top = {}
    for k in idx:
        for g, n in per[k].items():
            if g in idf:
                top[g] = top.get(g, 0.0) + n * idf[g]
    for k in idx:
        for cl in re.split(r"[，,；;。.！!？?]", sents[k]["text"]):
            c = _strip_fillers(cl)
            if len(c) < 4:
                continue
            g = [x for x in _grams(c) if x in idf]
            if not g:
                continue
            w = sum(idf[x] * (1.6 if _LAT.fullmatch(x) else 1.0) for x in set(g))
            L = title_len(c, platform)
            w *= 1.0 if 6 <= L <= limit else (0.6 if L < 6 else max(0.35, limit / L))
            if _starts(c, conn) or re.match(r"^(如果|比如|假如|例如|像|当|if|for example|like)", c, re.I):
                w *= 0.55
            if re.search(r"[你我咱]", c[:4]) or re.match(r"^(you|i|we)\b", c, re.I):
                w *= 0.7
            if any(h in c for h in HOOKY):
                w *= 1.15
            cands.append((w, k, c))
    if not cands:
        return ""
    _, _, best = max(cands, key=lambda x: (x[0], -x[1]))
    t = shorten(best, limit, platform)
    tops = [g for g, _ in sorted(top.items(), key=lambda x: -x[1])[:2]]
    text = " ".join(sents[k]["text"] for k in idx)
    for g in tops:
        d = _display(g, text)
        if d.lower() not in t.lower() and title_len(f"{d}：{t}", platform) <= limit:
            t = f"{d}：{t}"
            break
    return t


def extract_copy(W, sents, per, idf, a, b, limit, platform, chapter, prefer_tags=(), lang="zh"):
    """Rule-based title / hook candidates / notes / tags for the window of sentences a..b."""
    idx = list(range(a, b + 1))
    ws = {k: _sent_weight(sents[k], per[k], idf) / max(1.0, sents[k]["te"] - sents[k]["t"]) ** 0.5 for k in idx}
    q = {k: ws[k] * (1.3 if any(h in sents[k]["text"] for h in HOOKY) else 1.0) for k in idx}
    title = pick_title(sents, per, idf, idx, limit, platform, lang) or shorten(chapter or "", limit, platform)
    hooks = []
    for k in sorted(idx, key=lambda k: -q[k]):
        s = sents[k]
        d = s["te"] - s["t"]
        if 1.5 <= d <= 9.0 and k != a:
            hooks.append(dict(start=round(s["t"], 3), end=round(s["te"], 3), text=_strip_fillers(s["text"]) or s["text"]))
        if len(hooks) == 3:
            break
    if not hooks:
        s = sents[a]
        hooks = [dict(start=round(s["t"], 3), end=round(min(s["te"], s["t"] + 8), 3), text=s["text"])]
    notes = []
    for k in sorted(sorted(idx, key=lambda k: -ws[k])[:3]):
        nt = shorten(sents[k]["text"], 24, "douyin")
        if nt and nt not in notes:
            notes.append(nt)
    text = " ".join(sents[k]["text"] for k in idx)
    score = {}
    for k in idx:
        for g, n in per[k].items():
            if g in idf:
                score[g] = score.get(g, 0.0) + n * idf[g]
    tags = [t for t in prefer_tags or [] if t.lower() in text.lower()]
    for g, _ in sorted(score.items(), key=lambda x: -x[1]):
        if len(tags) >= 6:
            break
        d = _display(g, text)
        if any(d.lower() in x.lower() or x.lower() in d.lower() for x in tags):
            continue
        tags.append(d)
    return title, hooks, notes, tags[:6]


# --------------------------------------------------------------------------- LLM providers
SYSTEM = """You plan short vertical videos cut from one long recording (a lecture, talk or podcast).
You get the transcript as numbered sentences "[index] mm:ss text". Pick {count} segments that each work ON THEIR OWN
for a viewer who has not seen the rest: one clear point, a start that needs no earlier context (no "so / and then /
as I said" opening, no reference back), an end after the point is made. Each segment is a contiguous range of whole
sentences, {min_s:.0f}-{max_s:.0f} seconds long; segments must not overlap; prefer the most useful, concrete,
surprising parts and spread them over the recording.
For each segment write, in the transcript's language ({lang}):
- "title": a post title, at most {limit} {unit} ({rule}); concrete, no clickbait, no emoji, no quotes;
- "chapter": 2-6 word topic label; "notes": 2-3 short takeaway lines (max 24 characters each);
- "hook": the most striking 2-8 second sentence range INSIDE the segment for a cold open (from/to sentence index),
  plus up to 2 "hook_alternatives" in the same shape;
- "tags": 3-6 hashtags without '#'{tags_hint}; "why": one sentence why it works alone; "risk": what may need care
  (context needed, mis-heard terms, weak ending, privacy) or ""; "score": 0-1 how strong it is.
{style}Reply with JSON only: {{"segments": [{{"from": 12, "to": 30, "title": "...", "chapter": "...",
"hook": {{"from": 15, "to": 15}}, "hook_alternatives": [{{"from": 20, "to": 21}}], "notes": ["..."],
"tags": ["..."], "why": "...", "risk": "...", "score": 0.8}}]}}"""


def _fmt_t(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def _call_openai(system, prompt, model):
    if not os.environ.get("OPENAI_API_KEY"):
        raise PlanError("provider openai needs OPENAI_API_KEY")
    try:
        r = LLM.complete("segment_plan", system, prompt, schema=True, provider="openai", model=model,
                         max_tokens=16000, temperature=0.2, repair=False, fallback=False)
    except LLM.LLMError as e:
        raise PlanError(str(e)) from e
    return r["text"], dict(r["usage"])


def _call_claude(system, prompt, model):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise PlanError("provider claude needs ANTHROPIC_API_KEY")
    try:
        from vstudio.proofread import _call_claude as call
        return call(system, prompt, model)
    except RuntimeError as e:
        raise PlanError(str(e)) from e


def _call_llm(provider, config=None, routed=False, timeout=None):
    """Any other ``vstudio.llm`` provider as ``fn(system, prompt, model) -> (text, usage)``. ``routed``: the
    provider came from the route ("auto"): call with provider=None so the route's fallback chain applies (never
    pinned); ``timeout``: seconds per CLI provider. ``fn.results``: who really answered each call."""
    if provider in CALLS and not routed:
        return CALLS[provider]
    inner = LLM.call_fn("segment_plan", provider=None if routed else provider, schema=True, config=config,
                        temperature=0.2, repair=False, max_tokens=16000, cli_timeout=timeout)

    def fn(system, prompt, model):
        try:
            return inner(system, prompt, model)
        except LLM.LLMError as e:
            raise PlanError(str(e)) from e
    fn.results = inner.results
    return fn


CALLS = {"claude": _call_claude, "openai": _call_openai}


def _parse(text):
    import json
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise PlanError(f"planner reply has no JSON: {t[:200]!r}")
    try:
        d = json.loads(m.group(0))
    except ValueError as e:
        raise PlanError(f"planner reply is not valid JSON: {e}") from e
    segs = d.get("segments") if isinstance(d, dict) else d
    return [s for s in segs or [] if isinstance(s, dict)]


def llm_plan(provider, model, sents, count, min_s, max_s, limit, platform, lang, style="", tags=(), call=None,
             chunk_chars=150000, config=None, routed=False, timeout=None, meta=None):
    """-> ([(k0, k1, fields)], usage, raw replies)."""
    unit = "characters" if lang == "zh" else "characters"
    rule = "CJK and full-width count 1, latin letters / digits / spaces 0.5" if platform in ("xiaohongshu", "xhs") \
        else "every character counts 1"
    lines = [f"[{k}] {_fmt_t(s['t'])} {s['text']}" for k, s in enumerate(sents)]
    chunks, cur, size = [], [], 0
    for k, ln in enumerate(lines):
        if size + len(ln) > chunk_chars and cur:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(k)
        size += len(ln) + 1
    if cur:
        chunks.append(cur)
    total = sum(sents[c[-1]]["te"] - sents[c[0]]["t"] for c in chunks) or 1.0
    fn = call or _call_llm(provider, config, routed=routed, timeout=timeout)
    if meta is not None:
        meta["results"] = getattr(fn, "results", None)
    picks, usage, raws = [], dict(input=0, output=0), []
    for c in chunks:
        share = (sents[c[-1]]["te"] - sents[c[0]]["t"]) / total
        n = max(1, round(count * share)) if len(chunks) > 1 else count
        system = SYSTEM.format(count=n, min_s=min_s, max_s=max_s, lang="Chinese" if lang == "zh" else "English",
                               limit=limit, unit=unit, rule=rule,
                               tags_hint=(f"; prefer these when they fit: {', '.join(tags[:30])}" if tags else ""),
                               style=(f"Channel style: {style.strip()}\n" if style and style.strip() else ""))
        prompt = "\n".join(lines[k] for k in c)
        text, u = fn(system, prompt, model)
        raws.append(text)
        usage["input"] += u.get("input", 0)
        usage["output"] += u.get("output", 0)
        for s in _parse(text):
            try:
                a, b = int(s["from"]), int(s["to"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= a <= b < len(sents)):
                continue
            picks.append((a, b, s))
    return picks, usage, raws


def _fit_range(sents, a, b, min_s, max_s):
    """Grow / shrink a sentence range to [0.85 min, 1.15 max] seconds."""
    dur = lambda x, y: sents[y]["te"] - sents[x]["t"]  # noqa: E731
    while dur(a, b) > max_s * 1.15 and b > a:
        b -= 1
    while dur(a, b) < min_s * 0.85 and b + 1 < len(sents) and dur(a, b + 1) <= max_s * 1.15:
        b += 1
    return a, b


# --------------------------------------------------------------------------- main
def length_window(platforms, min_s=None, max_s=None):
    from vstudio import platform as PF
    lo, hi = [], []
    for t in platforms or []:
        try:
            sw = (PF.parse_targets([t])[0].length or {}).get("sweet")
        except Exception:  # noqa: BLE001
            sw = None
        if sw:
            lo.append(sw[0])
            hi.append(sw[1])
    mn = float(min_s) if min_s else max(20.0, float(max(lo)) if lo else 30.0)
    mx = float(max_s) if max_s else min(150.0, float(min(hi)) if hi else 90.0)
    if mx < mn + 10:
        mx = mn + 30.0 if not max_s else mx
    if mx <= mn:
        raise ValueError(f"--max {mx:g} must be larger than --min {mn:g}")
    return mn, mx


def plan_segments(source, transcript=None, client=None, count=None, min_s=None, max_s=None, platforms=None,
                  provider="auto", model=None, out=None, language=None, echo=True, call=None, write=True,
                  timeout=None):
    """``provider`` "auto": the segment_plan route WITH its fallback chain (claude-code -> codex ...); the doc says
    who answered (``provider``), what was routed (``routed``) and any ``fallback``. ``timeout``: seconds per CLI
    provider attempt (default ``DEFAULT_CLI_TIMEOUT``)."""
    t_start = time.time()
    eff = {}
    cdir = None
    if client:
        from . import clients as CL
        cdir = CL.resolve(client)
        eff = CL.effective(CL.load(cdir))
    platforms = list(platforms or eff.get("platforms") or ["xiaohongshu:full"])
    prov = (provider or "auto").lower()
    llm_cfg = {"llm": eff.get("llm")} if eff.get("llm") else None
    routed = prov == "auto" and call is None
    chain = []
    if prov == "auto":
        rt = LLM.route("segment_plan", config=llm_cfg)
        chain = list(rt.opts.get("fallback") or [])
        prov = "claude" if rt.provider == "anthropic" else rt.provider
    if routed and chain and prov != "none":
        pass                         # a fallback chain: the first provider may be down, the chain decides at call time
    elif prov == "claude" and not os.environ.get("ANTHROPIC_API_KEY") and call is None:
        raise PlanError("provider claude needs ANTHROPIC_API_KEY (or use --provider none)")
    if prov == "openai" and not os.environ.get("OPENAI_API_KEY") and call is None:
        raise PlanError("provider openai needs OPENAI_API_KEY (or use --provider none)")
    if prov not in ("claude", "openai", "none"):
        try:
            prov = LLM.canonical(prov)
        except ValueError:
            raise PlanError(f"provider {provider!r}: auto | claude | openai | none | "
                            + " | ".join(n for n in LLM.names() if n not in ("anthropic", "openai", "none"))) from None
        prov = "claude" if prov == "anthropic" else prov
        if prov not in ("claude", "openai", "none") and call is None and not (routed and chain):
            chk = LLM.check(prov, LLM.route("segment_plan", prov, config=llm_cfg).opts)
            if not chk["ready"]:
                raise PlanError(f"provider {prov}: {chk['detail']} (or use --provider none)")
    explicit_model = bool(model)
    if not model and prov != "none":
        r = LLM.route("segment_plan", "anthropic" if prov == "claude" else prov, config=llm_cfg)
        model = r.model or MODELS.get(prov) or LLM.default_model(r.provider, r.opts)
    tr, tr_path, sha = get_transcript(source, transcript, language or eff.get("language"),
                                      eff.get("asr_prompt") or None, echo=echo)
    from vstudio import cleanup as C
    W = C.load_words(tr)
    if not W:
        raise ValueError("the transcript has no words")
    gl = eff.get("glossary") or []
    if gl:
        for w in W:
            w["w"] = _term_fix(w["w"], gl)
    lang = language or C.detect_language(W)
    sents = sentences_of(W)
    mn, mx = length_window(platforms, min_s, max_s)
    dur_total = W[-1]["te"]
    speech = sum(s["te"] - s["t"] for s in sents)
    if not count:
        count = max(1, min(40, round(speech / max(60.0, 2.5 * (mn + mx)))))
    idf, per = term_stats(sents)
    bounds = topic_boundaries(sents, per, idf)
    chapters = chapters_of(sents, per, idf, bounds)
    limit, lim_pf = title_limit(platforms)
    prefer = list(eff.get("tags") or [])
    ranked = rank_windows(W, sents, per, idf, bounds, chapters, mn, mx, lang, prefer)
    chap_of = {k: c for c in chapters for k in range(c["k0"], c["k1"] + 1)}
    usage, raws, warnings = dict(input=0, output=0), [], []
    fallback_info, api_cost, notices = None, None, []

    def warn(code, **params):
        m = MSG.msg(code, **params)
        notices.append(m)
        warnings.append(m["message"])
    rows = []
    if prov == "none":
        picks = [(a, b, None, sc, parts) for sc, a, b, parts in select(ranked, count, len(chapters))]
    else:
        meta = {}
        lp, usage, raws = llm_plan(prov, model if (explicit_model or not routed) else None, sents, count, mn, mx,
                                   limit, lim_pf, lang, eff.get("style") or "", prefer, call=call, config=llm_cfg,
                                   routed=routed, timeout=timeout if timeout is not None else (
                                       None if os.environ.get("VSTUDIO_LLM_CLI_TIMEOUT") else DEFAULT_CLI_TIMEOUT),
                                   meta=meta)
        res = [x for x in meta.get("results") or [] if x]
        if res:
            used = res[-1]
            routed_prov, prov = prov, ("claude" if used.get("provider") == "anthropic" else used.get("provider")
                                       or prov)
            model = used.get("model") or model
            fb = next((x.get("fallback") for x in res if x.get("fallback")), None)
            if fb:
                fallback_info = dict(fb, routed=routed_prov)
                warn("plan-fallback", frm=fb.get("from"), to=fb.get("to"), why=fb.get("code"))
            api_cost = sum(float(x.get("cost_usd") or 0) for x in res)
        picks, taken = [], []
        sc_of = {(a, b): (sc, parts) for sc, a, b, parts in ranked}
        for a, b, f in sorted(lp, key=lambda x: -float((x[2] or {}).get("score") or 0)):
            a, b = _fit_range(sents, a, b, mn, mx)
            if any(not (b < x[0] or a > x[1]) for x in taken):
                continue
            taken.append((a, b))
            sc, parts = sc_of.get((a, b), (None, {}))
            picks.append((a, b, f, sc, parts))
        if len(picks) < count:
            warn("plan-short-filled", provider=prov, n=len(picks), missing=count - len(picks))
            for sc, a, b, parts in ranked:
                if len(picks) >= count:
                    break
                if any(not (b < x[0] or a > x[1]) for x in [(p[0], p[1]) for p in picks]):
                    continue
                picks.append((a, b, None, sc, parts))
        picks = sorted(picks[:count] if len(picks) > count else picks, key=lambda p: p[0])
    scores = [p[3] for p in picks if p[3] is not None]
    lo_s, hi_s = (min(scores), max(scores)) if scores else (0.0, 1.0)
    for n, (a, b, f, sc, parts) in enumerate(picks):
        s0, s1 = sents[a], sents[b]
        start, end = C.snap_range(W, s0["t"], s1["te"])
        chapter = chap_of.get(a, {}).get("name", "")
        title, hooks, notes, tags = extract_copy(W, sents, per, idf, a, b, limit, lim_pf, chapter, prefer, lang)
        why = _why(parts, chapter, tags, lang)
        risk = _risk(parts, lang)
        score = round((sc - lo_s) / (hi_s - lo_s + 1e-9), 2) if sc is not None else 0.5
        if f:
            if f.get("title"):
                t = str(f["title"]).strip().strip("\"“”「」")
                if title_len(t, lim_pf) > limit:
                    warn("plan-title-too-long", id=f"s{n + 1:03d}", provider=prov, limit=limit, title=t)
                    t = shorten(t, limit, lim_pf)
                title = t or title
            chapter = str(f.get("chapter") or chapter)
            if f.get("notes"):
                notes = [str(x)[:40] for x in f["notes"]][:4]
            if f.get("tags"):
                tags = [str(x).lstrip("#").strip() for x in f["tags"] if str(x).strip()][:6]
            why = str(f.get("why") or why)
            risk = str(f.get("risk") if f.get("risk") is not None else risk)
            try:
                score = round(max(0.0, min(1.0, float(f.get("score")))), 2)
            except (TypeError, ValueError):
                pass
            llm_hooks = []
            for h in [f.get("hook")] + list(f.get("hook_alternatives") or []):
                try:
                    ha, hb = int(h["from"]), int(h["to"])
                except (TypeError, KeyError, ValueError):
                    continue
                if a <= ha <= hb <= b and sents[hb]["te"] - sents[ha]["t"] <= 12:
                    llm_hooks.append(dict(start=round(sents[ha]["t"], 3), end=round(sents[hb]["te"], 3),
                                          text=" ".join(sents[k]["text"] for k in range(ha, hb + 1)) if lang != "zh"
                                          else "".join(sents[k]["text"] for k in range(ha, hb + 1))))
            if llm_hooks:
                seen = {(h["start"], h["end"]) for h in llm_hooks}
                hooks = llm_hooks + [h for h in hooks if (h["start"], h["end"]) not in seen]
                hooks = hooks[:3]
        hk = []
        for h in hooks:
            ha, hb = C.snap_range(W, h["start"], h["end"])
            hk.append(dict(start=round(ha, 3), end=round(hb, 3), text=h["text"]))
        rows.append(dict(id=f"s{n + 1:03d}", start=round(start, 3), end=round(end, 3), title=title, chapter=chapter,
                         hook=hk[0] if hk else None, hook_candidates=hk, notes=notes, tags=tags, why=why, risk=risk,
                         score=score))
    # named entities (vstudio.entities): titles / notes cards / hooks / tags spell names like the captions will
    from vstudio import entities as ENT
    ev = ENT.verify("\n".join(s_["text"] for s_ in sents), locale=ENT.norm_locale(None, "".join(
        s_["text"] for s_ in sents[:50])), glossary=[g.get("right") for g in gl if isinstance(g, dict) and g.get("right")])
    if ev["fixes"]:
        for r in rows:
            for k in ("title", "chapter", "why", "risk"):
                r[k] = ENT.fix_text(r[k], ev["fixes"])
            r["notes"] = [ENT.fix_text(x, ev["fixes"]) for x in r["notes"]]
            r["tags"] = [ENT.fix_text(x, ev["fixes"]) for x in r["tags"]]
            for h in [r["hook"]] + list(r["hook_candidates"]):
                if h:
                    h["text"] = ENT.fix_text(h["text"], ev["fixes"])
    cost = 0.0
    if api_cost is not None:
        cost = round(api_cost, 4)
    elif prov != "none" and (call is not None or LLM.canonical("anthropic" if prov == "claude" else prov)
                             not in LLM.LOCAL):
        pin, pout = LLM.price_of(model)[0]
        cost = round((usage["input"] * pin + usage["output"] * pout) / 1e6, 4)
    doc = dict(ok=True, provider=prov, model=model if prov != "none" else None, source=os.path.abspath(source)
               if source else None, transcript=tr_path, transcript_sha1=sha, duration=round(dur_total, 2),
               language=lang, count=count, min=mn, max=mx, platforms=platforms, title_max=limit,
               chapters=[dict(start=round(sents[c["k0"]]["t"], 2), end=round(sents[c["k1"]]["te"], 2), name=c["name"])
                         for c in chapters], segments=rows, cost_usd=cost, usage=usage, warnings=warnings,
               notices=notices, entities=dict(fixes=ev["fixes"], flagged=ev["flagged"]), client=cdir, seconds=round(time.time() - t_start, 2), fallback=fallback_info)
    if write:
        od = os.path.abspath(out or os.path.join(os.path.dirname(os.path.abspath(source or tr_path or ".")),
                                                 "plan-" + os.path.splitext(os.path.basename(source or "source"))[0]))
        os.makedirs(od, exist_ok=True)
        draft = os.path.join(od, "segments.draft.yaml")
        write_draft(draft, doc, transcript=tr_path)
        doc["draft"] = draft
        doc["plan_json"] = write_json(os.path.join(od, "plan.json"), dict(doc, raw=raws))
    doc["words"] = [dict(w=w["w"], t=w["t"], te=w["te"]) for w in W]
    return doc


def write_draft(path, doc, transcript=None):
    """segments.draft.yaml: the ``source:`` header (+ ``transcript:``) and the rows - a segments.yaml."""
    import yaml
    head = [f"# plan-segments draft ({doc['provider']}{' ' + doc['model'] if doc.get('model') else ''}): "
            f"{len(doc['segments'])} segment(s), {doc['min']:.0f}-{doc['max']:.0f} s, titles <= {doc['title_max']}",
            "# accept / drop / move rows, then: python -m vstudio.batch plan <spec> --segments <this file>"]
    body = dict(source=doc.get("source"))
    if transcript:
        body["transcript"] = transcript
    body["segments"] = doc["segments"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n")
        f.write(yaml.safe_dump(body, allow_unicode=True, sort_keys=False, default_flow_style=None, width=120))
    return path


def _why(parts, chapter, tags, lang):
    if not parts:
        return ""
    bits = []
    if lang == "zh":
        if chapter:
            bits.append(f"「{chapter}」")
        if tags:
            bits.append(f"关键词 {', '.join(tags[:3])}")
        if parts.get("density", 0) >= 1.2:
            bits.append(f"信息密度高（{parts['density']:.1f}× 平均）")
        if parts.get("start", 0) > 0.3:
            bits.append("开头在停顿 / 话题切换处")
        if parts.get("end", 0) > 0.2:
            bits.append("结尾完整")
        return "，".join(bits)
    if chapter:
        bits.append(f'"{chapter}"')
    if tags:
        bits.append("keywords " + ", ".join(tags[:3]))
    if parts.get("density", 0) >= 1.2:
        bits.append(f"dense ({parts['density']:.1f}x average)")
    if parts.get("start", 0) > 0.3:
        bits.append("starts at a pause / topic shift")
    return "; ".join(bits)


def _risk(parts, lang):
    if not parts:
        return ""
    zh = lang == "zh"
    r = []
    if parts.get("conn"):
        r.append(f"开头接上文（“{parts['conn']}”）" if zh else f"opens with '{parts['conn']}'")
    if parts.get("backref"):
        r.append(f"提到前文（“{parts['backref']}”）" if zh else f"refers back ('{parts['backref']}')")
    if parts.get("inner_shift", 0) >= 0.5:
        r.append("中间换了话题" if zh else "topic shift inside")
    if parts.get("concl_next"):
        r.append("后面紧跟结论，可能结束得早" if zh else "its conclusion follows right after")
    if parts.get("filler", 0) >= 0.08:
        r.append(f"口头禅多（{parts['filler']:.0%}）" if zh else f"many fillers ({parts['filler']:.0%})")
    if parts.get("density", 1) < 0.8:
        r.append("信息密度偏低，需要更强的 hook" if zh else "low density: needs a strong hook")
    if parts.get("share", 1) < 0.75:
        r.append("停顿多" if zh else "long pauses")
    return "；".join(r) if zh else "; ".join(r)
