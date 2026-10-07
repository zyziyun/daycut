"""Interview / podcast -> Q&A clips: who speaks when, question / answer pairs, answers trimmed tight.

    from vstudio import qa
    sents = qa.sentences(transcript)
    spk = qa.diarize("talk.mp4", sents)                   # {labels: [S1|S2 per sentence], method, confidence}
    plan = qa.plan_pairs(sents, spk["labels"], count=8)   # {pairs: [...], roles: {...}}
    rows = qa.to_segments(plan, question="audio")         # call-clips / podcast-clips segment rows (windows)

    python -m vstudio.qa plan --source talk.mp4 [--transcript t.json] [--speakers 2] [--tiles host=x,y,w,h ...]
        [--count 8] [--min 15 --max 75] [--names S1=Ziyun] [--out work/pairs.json] [--segments segments.yaml]

Speakers (``diarize``): ``method`` auto picks by what is available and SAYS which one ran (``method``,
``note``); nothing is guessed silently:
  pyannote   ``pyannote.audio`` installed AND a local pipeline (env VSTUDIO_DIARIZE_MODEL = a local folder /
             config.yaml): real diarization, nothing is downloaded at run time. Asked for explicitly but not
             installed -> an error.
  tiles      gallery-view calls with ``tiles`` given: ``face.talk_activity`` on the participants' tiles (mouth
             movement) -> the talker per sentence (call-clips' speaker timeline).
  voice      per-sentence voice prints (log band energies of the voiced frames) clustered into N speakers
             (k-means, farthest-pair seeds); ``confidence`` = cluster separation, below 0.3 the plan says the
             split is unsure and the review checkpoint shows it.
  none       no audio to cluster (or ``speakers: 1``): labels are None and the plan says so; pairs then come
             from the questions alone and carry no speaker labels.
``confidence`` says how clean the split is; the plan never prints a guessed name: speakers are roles ("Host" /
"Guest", 主持人 / 嘉宾) unless ``names`` maps a label to a name.

Pairs: a question = a run of the asker's sentences ending in a question (?, wh-/aux-inversion openers in English;
吗 / 呢 / 什么 / 怎么 / 为什么 ... in Chinese); its answer = the other speaker's sentences that follow, until the asker
takes the floor again, a long pause, or ``max_s``. Answers are trimmed tight: an opening acknowledgement ("great
question", "好问题") goes, then ``vstudio.cleanup`` (profile tight, word-safe) removes fillers / restarts / long
pauses inside, so ``answer.windows`` are the kept pieces. Question delivery per clip (``question`` param of the
recipe): ``card`` (a text card with the question, the asker's audio is not used), ``audio`` (the asker's own
question opens the clip), ``both``.
"""
import argparse
import json
import os
import re
import sys

import numpy as np

ROLE_LABELS = {"host": dict(en="Host", zh="主持人"), "guest": dict(en="Guest", zh="嘉宾"),
               "guest2": dict(en="Guest 2", zh="嘉宾 2"), "student": dict(en="Student", zh="学员"),
               "coach": dict(en="Coach", zh="教练")}
Q_EN = re.compile(r"^(?:(?:so|and|but|okay|ok|um|uh|now)[,.]?\s+)*(?:"
                  r"(?:what|why|how|when|where|who|which|whose)(?:'s|'re|\s+(?:do|does|did|is|are|was|were|can|could|"
                  r"would|will|should|have|has|had|made|makes|kind|about|much|many|long|often|come)\b)"
                  r"|(?:do|does|did|can|could|would|will|is|are|was|were|have|has|should|shall|may|might|isn't|aren't|"
                  r"don't|doesn't|didn't|wouldn't|couldn't)\s+(?:you|we|they|i|it|he|she|there|this|that|your|people|"
                  r"anyone|someone)\b|tell me\b)", re.I)
Q_EN_ASK = re.compile(r"\b(?:my question is|i(?:'m| am) curious|i wonder(?:ed)?|can you (?:tell|share|walk|talk)|"
                      r"could you (?:tell|share|walk|talk)|what do you think|how do you)\b", re.I)
Q_ZH = re.compile(r"(?:吗|呢|么|嘛)[？?。]?$|什么|怎么|为什么|为何|如何|哪|多少|是不是|能不能|有没有|会不会|可不可以|要不要|对不对|好不好")
Q_ZH_ASK = re.compile(r"想问|请问|我的问题是|问一下|好奇|聊聊|说说|讲讲|分享一下")
ACK = re.compile(r"^(?:(?:um+|uh+|so|well|yeah|yes|right|okay|ok|oh)[,.]?\s+)*(?:that'?s|it'?s|what)?\s*(?:a\s+)?"
                 r"(?:great|good|really good|wonderful|fantastic|interesting|tough|hard|big) question[.!,]?\s*"
                 r"|^(?:thank you for asking|thanks for asking)[.!,]?\s*"
                 r"|^(?:嗯+|呃+|啊|对|好)?[，,]?\s*(?:这(?:个)?|你这个)?(?:是)?(?:一个)?(?:好问题|问题很好|很好的问题)[。！，,]?\s*", re.I)
LEAD_EN = re.compile(r"^(?:(?:um+|uh+|so|well|yeah|okay|ok|oh|right|and|now|tell me)[,.]?\s+)+", re.I)


# --------------------------------------------------------------------------- transcript
def sentences(transcript, max_len=25.0):
    from vstudio import lesson
    return lesson.sentences(transcript, max_len)


def is_question(text, lang="en"):
    t = (text or "").strip()
    if not t:
        return False
    if t.endswith(("?", "？")):
        return True
    if lang == "zh" or re.search(r"[一-鿿]", t):
        tail = re.sub(r"[。！!，,\s]+$", "", t)[-12:]
        return bool(Q_ZH.search(tail)) or bool(Q_ZH_ASK.search(t))
    words = t.split()
    return (len(words) >= 3 and bool(Q_EN.match(t)) and not t.endswith("!")) or bool(Q_EN_ASK.search(t))


# --------------------------------------------------------------------------- diarization
def _band_features(x, sr, a, b, n_bands=24, hop=0.02):
    i0, i1 = int(a * sr), int(b * sr)
    seg = x[i0:i1]
    n = int(hop * sr * 2)
    if len(seg) < n * 3:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(seg, n)[::n // 2]
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(frames * win, axis=1)) ** 2
    energy = spec.sum(1)
    voiced = energy > np.percentile(energy, 40)
    if voiced.sum() < 3:
        return None
    spec = spec[voiced]
    freqs = np.fft.rfftfreq(n, 1 / sr)
    edges = np.geomspace(80, min(7600, sr / 2 - 1), n_bands + 1)
    bands = np.stack([spec[:, (freqs >= lo) & (freqs < hi)].sum(1) for lo, hi in zip(edges[:-1], edges[1:])], 1)
    lb = np.log(bands + 1e-9)
    lb = lb - lb.mean(1, keepdims=True)                 # spectral shape, not loudness
    return lb.mean(0)


def kmeans(X, k, iters=50):
    """Tiny deterministic k-means (farthest-point seeds) -> (labels, centres)."""
    X = np.asarray(X, float)
    c = [X[int(np.argmax(np.linalg.norm(X - X.mean(0), axis=1)))]]
    while len(c) < k:
        d = np.min([np.linalg.norm(X - ci, axis=1) for ci in c], axis=0)
        c.append(X[int(np.argmax(d))])
    C = np.array(c)
    lab = np.zeros(len(X), int)
    for _ in range(iters):
        D = np.stack([np.linalg.norm(X - ci, axis=1) for ci in C], 1)
        new = D.argmin(1)
        if (new == lab).all() and _ > 0:
            break
        lab = new
        for j in range(k):
            if (lab == j).any():
                C[j] = X[lab == j].mean(0)
    return lab, C


def _smooth(labels, sents, min_s=1.2):
    out = list(labels)
    for k, s in enumerate(sents):
        if s["te"] - s["t"] < min_s and 0 < k < len(sents) - 1 and out[k - 1] == out[k + 1] != out[k]:
            out[k] = out[k - 1]
    return out


def diarize_voice(audio, sents, n=2):
    """Per-sentence voice clustering. audio: a media path or (x, sr). -> dict(labels, method, confidence)."""
    if isinstance(audio, (tuple, list)):
        x, sr = audio
    else:
        from .audio import decode_audio
        sr = 16000
        x = decode_audio(audio, sr=sr, channels=1)[:, 0]
    x = np.asarray(x, np.float32)
    feats, idx = [], []
    for k, s in enumerate(sents):
        f = _band_features(x, sr, s["t"], s["te"])
        if f is not None:
            feats.append(f)
            idx.append(k)
    if len(feats) < max(2, n):
        return None
    F = np.array(feats)
    F = (F - F.mean(0)) / (F.std(0) + 1e-6)
    lab, C = kmeans(F, n)
    within = np.mean([np.linalg.norm(F[i] - C[lab[i]]) for i in range(len(F))])
    between = np.mean([np.linalg.norm(C[i] - C[j]) for i in range(n) for j in range(i + 1, n)]) if n > 1 else 0
    conf = float(max(0.0, min(1.0, (between / (within + 1e-9) - 0.5) / 2.0)))
    labels = [None] * len(sents)
    order = {}
    for i, k in enumerate(idx):                         # S1 = whoever speaks first
        order.setdefault(int(lab[i]), f"S{len(order) + 1}")
        labels[k] = order[int(lab[i])]
    for k in range(len(labels)):                        # unvoiced / too short: nearest labelled neighbour
        if labels[k] is None:
            j = min((j for j in range(len(labels)) if labels[j]), key=lambda j: abs(j - k), default=None)
            labels[k] = labels[j] if j is not None else "S1"
    return dict(labels=_smooth(labels, sents), method="voice", confidence=round(conf, 3))


def diarize_tiles(video, sents, tiles, every=3):
    """Gallery view: the talking tile per sentence (mouth movement). tiles = {name: (x, y, w, h)}."""
    from . import face
    act = face.talk_activity(video, tiles, every=every)
    times, labs = np.array(act["times"]), act["labels"]
    out = []
    for s in sents:
        m = (times >= s["t"]) & (times <= s["te"])
        votes = [labs[i] for i in np.where(m)[0] if labs[i] != "both"]
        out.append(max(set(votes), key=votes.count) if votes else None)
    for k in range(len(out)):
        if out[k] is None:
            out[k] = out[k - 1] if k else next((x for x in out if x), list(tiles)[0])
    return dict(labels=_smooth(out, sents), method="tiles", confidence=0.8)


def diarize_pyannote(source, sents):
    model = os.environ.get("VSTUDIO_DIARIZE_MODEL")
    if not model or not os.path.exists(model):
        return None
    try:
        from pyannote.audio import Pipeline              # optional, local only
    except ImportError:
        return None
    pipe = Pipeline.from_pretrained(model)
    dia = pipe(source)
    turns = [(t.start, t.end, spk) for t, _, spk in dia.itertracks(yield_label=True)]
    names, out = {}, []
    for s in sents:
        best, bo = None, 0.0
        for a, b, spk in turns:
            ov = min(b, s["te"]) - max(a, s["t"])
            if ov > bo:
                best, bo = spk, ov
        if best is not None:
            names.setdefault(best, f"S{len(names) + 1}")
        out.append(names.get(best))
    for k in range(len(out)):
        if out[k] is None:
            out[k] = out[k - 1] if k else "S1"
    return dict(labels=out, method="pyannote", confidence=0.9)


class DiarizeError(RuntimeError):
    pass


def diarize(source, sents, n=2, tiles=None, method="auto", lang="en"):
    """-> {labels [per sentence] | None, method, confidence, note}. auto = pyannote when installed locally, else
    tiles when given, else voice clustering; an explicitly named method that cannot run raises ``DiarizeError``."""
    if n <= 1:
        return dict(labels=None, method="none", confidence=0.0, note="one speaker: no speaker labels")
    order = [method] if method != "auto" else (["pyannote"] + (["tiles"] if tiles else []) + ["voice"])
    for m in order:
        if m == "pyannote":
            if not os.environ.get("VSTUDIO_DIARIZE_MODEL"):
                if method == "pyannote":
                    raise DiarizeError("pyannote diarization needs VSTUDIO_DIARIZE_MODEL (a local pipeline folder)")
                continue
            r = diarize_pyannote(source, sents)
            if r is None:
                raise DiarizeError("pyannote.audio is not installed or VSTUDIO_DIARIZE_MODEL does not exist")
            return dict(r, note="pyannote (local)")
        if m == "tiles":
            if not tiles:
                raise DiarizeError("tiles diarization needs --tiles name=x,y,w,h for every participant")
            return dict(diarize_tiles(source, sents, tiles), note="mouth movement per tile")
        if m == "voice":
            if source is None:
                raise DiarizeError("voice diarization needs the recording")
            r = diarize_voice(source, sents, n)
            if r is None:
                return dict(labels=None, method="none", confidence=0.0,
                            note="too little speech to tell voices apart: pairs come from the questions only")
            if r["confidence"] < 0.3:
                r["note"] = f"voice clustering is unsure (confidence {r['confidence']:.2f}): check the roles"
            else:
                r["note"] = "voice clustering"
            return r
        raise DiarizeError(f"unknown diarization method {m!r}")
    return dict(labels=None, method="none", confidence=0.0, note="no diarization method available")


# --------------------------------------------------------------------------- roles
def roles(labels, sents, lang="en", names=None, ui="zh"):
    """{speaker: {role, label}}: the speaker with the most questions is the host, the others guests. A label is a
    role ("Host" / "主持人") unless ``names`` gives a name for that speaker."""
    qn = {}
    for s, l in zip(sents, labels):
        qn.setdefault(l, 0)
        if is_question(s["text"], lang):
            qn[l] += 1
    spk = sorted(qn, key=lambda x: (-qn[x], x))
    out = {}
    for i, s in enumerate(spk):
        role = "host" if i == 0 else ("guest" if i == 1 else f"guest{i}")
        lab = (names or {}).get(s) or ROLE_LABELS.get(role, ROLE_LABELS["guest"]).get(ui) or \
            (f"嘉宾 {i}" if ui == "zh" else f"Guest {i}")
        out[s] = dict(role=role, label=lab, questions=qn[s], named=bool((names or {}).get(s)))
    return out


# --------------------------------------------------------------------------- pairs
def _trim_answer(sents, a, b, lang):
    """Drop opening acknowledgements: a whole short sentence ("Great question.") or its leading words."""
    while a < b and ACK.match(sents[a]["text"]) and \
            (len(ACK.sub("", sents[a]["text"]).strip()) < 3 or sents[a]["te"] - sents[a]["t"] < 2.5):
        a += 1
    return a


def tight_windows(words, a, b, profile="tight", audio=None):
    """Answer [a, b] (source s) -> kept pieces after ``vstudio.cleanup`` (fillers, restarts, long pauses; all
    confirm-level edits applied) and an opening acknowledgement cut at word level."""
    from vstudio import cleanup as C
    W = [w for w in words if a - 0.05 <= (w["t"] + w["te"]) / 2 <= b + 0.05]
    if not W:
        return [[a, b]]
    head = C.join_words(W[:12])
    m = ACK.match(head) or LEAD_EN.match(head)
    if m and m.end() < len(head):
        n_chars, k = 0, 0
        while k < len(W) and n_chars < m.end() - 1:
            n_chars += len(W[k]["w"]) + (1 if re.match(r"[A-Za-z]", W[k]["w"]) else 0)
            k += 1
        if 0 < k < len(W):
            a = max(a, W[k]["t"] - 0.05)
    edits = C.detect(words, audio=audio, ranges=[(a, b)], profile=profile)
    keep = C.keep_segments(edits, [(a, b)], all_confirm=True, words=W)
    keep = [[round(float(x), 3), round(float(y), 3)] for x, y in keep if y - x >= 0.25]
    return keep or [[round(float(a), 3), round(float(b), 3)]]


def _shorten(text, lang, limit=None):
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = LEAD_EN.sub("", t) if lang != "zh" else re.sub(r"^(?:嗯+|呃+|那|那么|就是|然后)[，,]?", "", t)
    if lang == "zh":
        limit = limit or 28
        return t if len(t) <= limit else t[:limit - 1] + "…"
    limit = limit or 90
    t = t[:1].upper() + t[1:]
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def plan_pairs(sents, labels=None, lang=None, count=None, min_s=15.0, max_s=75.0, max_q=25.0, long_pause=3.0,
               words=None, tighten=True, names=None, ui="zh", audio=None):
    """-> {lang, pairs [...], roles {...}}. ``labels``: per-sentence speakers (``diarize``); None = text only."""
    from vstudio import lesson
    lang = lang or lesson.lang_of(sents)
    known = bool(labels)
    labels = labels or [None] * len(sents)
    rl = roles(labels, sents, lang, names, ui) if known else {}
    host = next((s for s, r in rl.items() if r["role"] == "host"), None)
    multi = known and len(set(labels)) > 1
    n = len(sents)
    pairs, k = [], 0
    while k < n:
        s = sents[k]
        if not (is_question(s["text"], lang) and (not multi or labels[k] == host)):
            k += 1
            continue
        q1 = k                                          # the question run: the asker's following questions too
        while q1 + 1 < n and labels[q1 + 1] == labels[k] and is_question(sents[q1 + 1]["text"], lang) and \
                sents[q1 + 1]["gap_before"] < 1.5:
            q1 += 1
        q0 = k                                          # setup before the question (same speaker, close by)
        while q0 > 0 and labels[q0 - 1] == labels[k] and sents[q0 - 1]["gap_before"] < 1.5 and \
                sents[q1]["te"] - sents[q0 - 1]["t"] <= max_q and not is_question(sents[q0 - 1]["text"], lang) and \
                (not pairs or sents[q0 - 1]["t"] >= pairs[-1]["answer"]["end"]):
            q0 -= 1
        a0 = q1 + 1
        if a0 >= n:
            break
        if multi:
            while a0 < n and labels[a0] == labels[k] and not is_question(sents[a0]["text"], lang) and \
                    sents[a0]["te"] - sents[q1]["te"] < 4.0:
                a0 += 1                                 # the asker's own trailing "you know?" / "go ahead"
        a0 = _trim_answer(sents, a0, n - 1, lang) if a0 < n else a0
        a1 = a0
        while a1 + 1 < n:
            nx = sents[a1 + 1]
            if nx["gap_before"] > long_pause:
                break
            if multi and labels[a1 + 1] == host and (is_question(nx["text"], lang) or
                                                      len(re.findall(r"[A-Za-z']+|[一-鿿]", nx["text"])) >= 3):
                break                                   # the host takes the floor (a "mm-hmm" / "right" does not)
            if not multi and is_question(nx["text"], lang):
                break
            if nx["te"] - sents[a0]["t"] > max_s:
                break
            a1 += 1
        if a0 >= n or sents[a1]["te"] - sents[a0]["t"] < min_s:
            k = max(k + 1, a1 if a0 < n else n)
            continue
        q = dict(start=round(sents[q0]["t"], 2), end=round(sents[q1]["te"], 2),
                 text=" ".join(x["text"] for x in sents[q0:q1 + 1]) if lang != "zh"
                 else "".join(x["text"] for x in sents[q0:q1 + 1]),
                 ask=" ".join(x["text"] for x in sents[k:q1 + 1]) if lang != "zh" else "".join(
                     x["text"] for x in sents[k:q1 + 1]),
                 speaker=labels[k])
        ans_text = (" " if lang != "zh" else "").join(x["text"] for x in sents[a0:a1 + 1])
        a_start, a_end = round(sents[a0]["t"], 2), round(sents[a1]["te"], 2)
        wins = tight_windows(words, a_start, a_end, audio=audio) if (tighten and words) else [[a_start, a_end]]
        dur = sum(y - x for x, y in wins)
        target = (min_s + max_s) / 2
        score = round(1.0 - abs(dur - target) / max(target, 1) + 0.3 * (labels[a0] != labels[k] if multi else 0.5)
                      + 0.2 * min(1.0, len(re.findall(r"\w+", ans_text)) / max(1.0, dur * 2.5)), 3)
        pairs.append(dict(question=q, answer=dict(start=a_start, end=a_end, text=ans_text, speaker=labels[a0],
                                                  windows=wins, kept_s=round(dur, 2)),
                          title=_shorten(q["ask"], lang), score=score))
        k = a1 + 1
    if count and len(pairs) > count:
        keep = sorted(sorted(pairs, key=lambda p: -p["score"])[:count], key=lambda p: p["question"]["start"])
        pairs = keep
    for i, p in enumerate(pairs):
        p["id"] = f"q{i + 1:02d}"
        p["question"]["role"] = rl.get(p["question"]["speaker"], {}).get("label") if known else None
        p["answer"]["role"] = rl.get(p["answer"]["speaker"], {}).get("label") if known else None
    return dict(lang=lang, pairs=pairs, roles=rl, host=host, speakers_known=known)


def to_segments(plan, question="audio"):
    """Pairs -> segment rows for ``call-clips`` / the ``podcast-clips`` batch (gallery-view calls with tiles):
    ``windows`` = [question] + answer pieces (question "card" / "both": the question text goes into ``chapter`` +
    ``notes`` and, for "card", the asker's audio is left out)."""
    rows = []
    for p in plan["pairs"]:
        q = p["question"]
        wins = ([[q["start"], q["end"]]] if question in ("audio", "both") else []) + [list(w) for w in p["answer"]["windows"]]
        rows.append(dict(id=p["id"], windows=wins, title=p["title"], chapter="Q&A", notes=[p["title"]],
                         why=f"{q.get('role') or 'Q'} -> {p['answer'].get('role') or 'A'}"))
    return rows


# --------------------------------------------------------------------------- clips
QUESTION_KICKER = dict(en="Question", zh="提问")


def reading_time(text, lang="en", lo=2.5, hi=6.0):
    """Seconds to read a question card: ~3.5 English words / 6 Chinese characters per second + 1 s, in [lo, hi]."""
    n = len(re.findall(r"[一-鿿]", text or "")) / 6.0 + len(re.findall(r"[A-Za-z0-9']+", text or "")) / 3.5
    return round(max(lo, min(hi, 1.0 + n)), 2)


def clip_specs(plan, source, question="audio", mode="bilingual", mask=None, speed=1.0, subs=None, ui="zh",
               camera=None, offset=0.0, layout=None):
    """Pairs -> ``clipkit`` specs: question card and / or the asker's audio, the answer pieces, a persistent header
    with the question, role labels at each speaker's first line."""
    lang = plan.get("lang") or "en"
    bi = mode in ("bilingual", "translated")
    subs = subs or {}
    kick = f"{QUESTION_KICKER['en']} · {QUESTION_KICKER['zh']}" if bi else QUESTION_KICKER["zh" if lang == "zh" else "en"]
    specs = []
    for p in plan["pairs"]:
        q, a = p["question"], p["answer"]
        sub = subs.get(p["title"]) if bi else None
        parts, labels = [], []
        if question in ("card", "both"):
            parts.append(dict(kind="card", kicker=kick, title=p["title"], sub=sub,
                              dur=reading_time(p["title"], lang), footer=f"— {q['role']}" if q.get("role") else None))
        if question in ("audio", "both"):
            parts.append(dict(kind="src", a=q["start"], b=q["end"]))
            if q.get("role"):
                labels.append(dict(a=q["start"], b=q["end"], text=q["role"]))
        for k, (x, y) in enumerate(a["windows"]):
            parts.append(dict(kind="src", a=x, b=y))
        if a.get("role"):
            labels.append(dict(a=a["windows"][0][0], b=a["windows"][0][1], text=a["role"]))
        specs.append(dict(id=p["id"], kind="qa", title=p["title"], source=source, camera=camera,
                          offset=float(offset or 0.0), layout=layout, mask=mask or {}, speed=float(speed or 1.0),
                          parts=parts, header=dict(kicker="Q&A", title=p["title"], sub=sub), labels=labels,
                          terms=[], gloss=sub, summary=a.get("text", "")[:120]))
    return specs


def post_for(spec):
    return dict(title=spec["title"][:40], body="\n".join(x for x in [spec.get("gloss")] if x), tags=None)


def render(plan, source, out_dir, platforms, question="audio", mode="bilingual", mask=None, speed=1.0, only=None,
           tgt_lang=None, translate=None, call=None, ui="zh"):
    from . import bilingual as BL
    from . import clipkit as CK
    from vstudio.cleanup import load_words
    lang = plan.get("lang") or "en"
    tgt = tgt_lang or BL.other_lang(lang)
    cache = os.path.join(out_dir, "translate-cache.json")
    subs = {}
    if mode in ("bilingual", "translated"):
        texts = [p["title"] for p in plan["pairs"]]
        subs = dict(zip(texts, CK.translate_lines(texts, lang, tgt, cache=cache, call=call)))
    specs = clip_specs(plan, source, question, mode, mask, speed, subs, ui)
    words = load_words(plan["transcript"]) if plan.get("transcript") else None
    cap = CK.caption_config(mode, lang, tgt, cache=cache)
    return CK.render_all(specs, words, platforms, out_dir, cap, "interview-qa", only=only, post_of=post_for,
                         translate=translate)


# --------------------------------------------------------------------------- CLI
def _tiles(vals):
    out = {}
    for v in vals or []:
        name, _, r = v.partition("=")
        out[name] = tuple(int(x) for x in r.split(","))
    return out


def _cli(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.qa", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--source", default=None)
    p.add_argument("--transcript", default=None)
    p.add_argument("--language", default=None)
    p.add_argument("--speakers", type=int, default=2)
    p.add_argument("--diarize", default="auto", choices=["auto", "pyannote", "tiles", "voice"])
    p.add_argument("--tiles", nargs="*", default=None, help="name=x,y,w,h per participant tile (gallery view)")
    p.add_argument("--names", nargs="*", default=None, help="S1=Name: show a name instead of the role")
    p.add_argument("--names-csv", default=None, help="S1=Name,S2=Name (one argument)")
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--min", dest="min_s", type=float, default=15.0)
    p.add_argument("--max", dest="max_s", type=float, default=75.0)
    p.add_argument("--no-tighten", action="store_true")
    p.add_argument("--ui", default="zh", choices=["zh", "en"])
    p.add_argument("--out", default="work/pairs.json")
    p.add_argument("--segments", default=None, help="also write call-clips segment rows (yaml)")
    p.add_argument("--question", default="audio", choices=["card", "audio", "both"])
    p.add_argument("--keep-edited", action="store_true")
    r = sub.add_parser("render")
    r.add_argument("plan")
    r.add_argument("--source", default=None)
    r.add_argument("--platforms", default="douyin")
    r.add_argument("--question", default="audio", choices=["card", "audio", "both"])
    r.add_argument("--subtitles", default="bilingual", choices=["mono", "bilingual", "translated"])
    r.add_argument("--to", dest="tgt", default=None)
    r.add_argument("--mask", default="off", choices=["off", "sticker", "blur"])
    r.add_argument("--mask-regions", nargs="*", default=None, help="x,y,w,h per face to hide (source px); "
                   "default: the main face of the picture")
    r.add_argument("--mask-regions-csv", default=None, help="'x,y,w,h x,y,w,h' (one argument)")
    r.add_argument("--speed", type=float, default=1.0)
    r.add_argument("--only", nargs="*", default=None)
    r.add_argument("--ui", default="zh", choices=["zh", "en"])
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "render":
        with open(a.plan, encoding="utf-8") as f:
            plan = json.load(f)
        mask = {}
        if a.mask != "off":
            regs = [[int(float(v)) for v in x.split(",")] for x in (a.mask_regions or []) +
                    (a.mask_regions_csv or "").split() if x.count(",") == 3]
            mask = dict(mode=a.mask, target="regions" if regs else "all", regions=regs)
        res = render(plan, a.source or plan.get("source"), a.out, [x for x in a.platforms.split(",") if x],
                     a.question, a.subtitles, mask, a.speed, a.only, None if a.tgt in (None, "auto") else a.tgt,
                     ui=a.ui)
        print(json.dumps(dict(out=a.out, clips=len(res["clips"]), ok=res["ok"]), ensure_ascii=False))
        return 0 if res["ok"] else 1
    if a.keep_edited and os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                if json.load(f).get("edited"):
                    print(json.dumps(dict(out=a.out, kept=True)))
                    return 0
        except (OSError, ValueError):
            pass
    from vstudio.batch.segplan import get_transcript
    from vstudio.cleanup import load_words
    lang0 = None if a.language in (None, "", "auto") else a.language
    tr, tpath, _ = get_transcript(a.source, a.transcript, language=lang0)
    W = load_words(tr)
    from vstudio.batch.segplan import sentences_of
    sents = sentences_of(W)
    from vstudio import lesson
    lang = lang0 or lesson.lang_of(sents)
    spk = diarize(a.source, sents, a.speakers, _tiles(a.tiles), a.diarize, lang)
    print(f"[qa] speakers: {spk['method']} - {spk.get('note')}", file=sys.stderr, flush=True)
    names = dict(x.strip().split("=", 1) for x in (a.names or []) + (a.names_csv or "").split(",") if "=" in x)
    plan = plan_pairs(sents, spk["labels"], lang, a.count, a.min_s, a.max_s, words=W, tighten=not a.no_tighten,
                      names=names, ui=a.ui, audio=a.source)
    plan.update(source=os.path.abspath(a.source) if a.source else None, transcript=tpath,
                diarization={k: v for k, v in spk.items() if k != "labels"}, speakers=spk["labels"])
    if spk.get("labels") is None:
        plan["warnings"] = [spk.get("note")]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    if a.segments:
        import yaml
        with open(a.segments, "w", encoding="utf-8") as f:
            yaml.safe_dump(dict(source=plan["source"], segments=to_segments(plan, a.question)), f, allow_unicode=True,
                           sort_keys=False)
    print(json.dumps(dict(out=a.out, pairs=len(plan["pairs"]), diarization=plan["diarization"], lang=lang),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
