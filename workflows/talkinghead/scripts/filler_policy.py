"""Conservative filler policy + post-cut content check (talkinghead strict_pass, promo-recut tight_cut).

Why: `vstudio.cut.suggest_fillers` is a recall-oriented review aid. On real footage, applying every
candidate deleted real words (semantic "fillers" such as 就是 / 那个 / 然后 that were part of the
sentence, a "hidden onset" PATCH that clipped the word itself), and the subtitles no longer matched the
audio. So candidates are scored here, only the high-confidence ones are pre-filled, and everything
else needs the creator's explicit confirmation. After the cut, `content_check` re-reads the kept
audio and flags content words that went missing.

  score(sug, words)              -> [{..., "conf": 0..1, "tier": "auto"|"confirm"|"info", "why"}]
  split_tiers(scored)            -> (auto, confirm, info)
  content_check(expected, got)   -> [{"kind": "missing"|"changed", "text", "got", "t"}]
"""
import difflib
import re

AUTO_MIN = 0.8                    # conf >= AUTO_MIN may be pre-filled into DEL / cut.drop
# Pure hesitation sounds: never carry meaning when transcribed as a standalone word.
HESITATION = {"嗯", "呃", "额", "um", "uh", "erm", "uhm", "hmm"}
# Interjections / particles that are often real (好啊, 哦 原来, 哎 你看): confirm.
SOFT = {"啊", "哦", "哎", "诶"}
# Doubles that are often grammatical in English ("that that", "had had").
LEGIT_DOUBLE = {"that", "had", "is", "do", "very", "really", "so", "no", "bye", "well"}
_P = re.compile(r"[\s，。,.!?！？、：:；;“”\"'…\-]+")


def _norm(s):
    return _P.sub("", str(s)).lower()


def _w(w):
    """(text, start, end) from any word shape (vstudio {w,t,te}, whisper {word,start,end}, bw {w,b0,b1})."""
    if isinstance(w, dict):
        t = w.get("w", w.get("word", ""))
        a = w.get("t", w.get("start", w.get("b0")))
        b = w.get("te", w.get("end", w.get("b1")))
        return str(t), float(a), float(b)
    return str(w[0]), float(w[1]), float(w[2])


def score(sug, words=None):
    """Attach a confidence + tier to each `cut.suggest_fillers` row.

    auto (conf >= 0.8): a standalone hesitation sound (嗯 呃 um uh) shorter than 0.6 s; an immediate
    single-word repeat (我我, the the) that is not a known grammatical double.
    confirm: semantic fillers (就是 那个 然后 这个 对吧 like "you know"), soft interjections (啊 哦),
    two-word repeats (could be 一点一点), filler-glued words, long-word / hidden-onset PATCHes.
    info: long words with no clear dip, or with speech before the dip (listen, do not cut).
    """
    out = []
    for r in sug:
        r = dict(r)
        kind, txt, dur = r["kind"], _norm(r["text"]), r["end"] - r["start"]
        if kind == "filler":
            if txt in HESITATION and dur <= 0.6:
                conf, why = 0.95, "hesitation sound"
            elif txt in HESITATION:
                conf, why = 0.5, f"hesitation but {dur:.2f}s long: whisper may have merged a real word"
            elif txt in SOFT:
                conf, why = 0.45, "interjection / particle, often part of the sentence"
            else:
                conf, why = 0.35, "semantic filler: often a real word here, confirm by ear"
        elif kind == "repeat":
            unit = txt[: max(1, len(txt) // 2)]
            if unit in LEGIT_DOUBLE:
                conf, why = 0.4, "can be grammatical"
            elif dur > 1.2:
                conf, why = 0.5, "copies far apart: may be a deliberate restatement"
            else:
                conf, why = 0.85, "immediate stutter repeat (drop the first copy)"
        elif kind == "repeat2":
            conf, why = 0.5, "two-word repeat: can be reduplication (一点一点) or emphasis"
        elif kind == "filler-glued":
            conf, why = 0.3, "filler glued to a real word: needs a PATCH, never a whole-word DEL"
        elif kind == "long-word" and r.get("patch"):
            conf, why = 0.3, "hidden onset (merged filler/restart?): PATCH only after listening"
        else:
            conf, why = 0.1, "listen; no cut suggested"
        if r.get("dropped"):
            why += " (already dropped)"
        r.update(conf=conf, why=why, tier="auto" if conf >= AUTO_MIN else ("confirm" if conf >= 0.25 else "info"))
        out.append(r)
    return out


def split_tiers(scored):
    auto = [r for r in scored if r["tier"] == "auto" and not r.get("dropped")]
    conf = [r for r in scored if r["tier"] == "confirm" and not r.get("dropped")]
    info = [r for r in scored if r["tier"] == "info"]
    return auto, conf, info


def units(words):
    """Comparable units: each CJK character, each latin/digit run; with the source word's start time."""
    out = []
    for w in words:
        txt, a, _ = _w(w)
        for m in re.finditer(r"[a-z0-9']+|[^\sa-z0-9']", _norm(txt)):
            out.append((m.group(0), a))
    return out


def _is_filler(u, fillers):
    return u in fillers


def content_check(expected, got, fillers=(), min_chars=2):
    """Compare the transcript that SHOULD remain (original minus confirmed deletions) with a fresh ASR
    of the cut. Flags runs of content that are missing (or replaced) in the cut.

    expected, got: word lists (any shape). fillers: tokens ignored on both sides.
    A missing run is flagged when it has >= min_chars CJK characters or any latin/digit word; single
    characters are usually ASR noise. Returns [{"kind", "text", "got", "t"}] (t = original seconds).
    """
    fl = {_norm(f) for f in fillers} | HESITATION
    fl_chars = {f for f in fl if len(f) == 1}
    e = [(u, t) for u, t in units(expected) if u not in fl_chars and u not in fl]
    g = [u for u, _ in units(got) if u not in fl_chars and u not in fl]
    sm = difflib.SequenceMatcher(None, [u for u, _ in e], g, autojunk=False)
    flags = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op not in ("delete", "replace"):
            continue
        miss = [u for u, _ in e[i1:i2]]
        heavy = sum(len(u) if re.match(r"[a-z0-9]", u) is None else 2 for u in miss)
        if heavy < min_chars:
            continue
        if op == "replace" and abs((i2 - i1) - (j2 - j1)) <= 1 and (i2 - i1) <= 2:
            continue    # same-length swap of 1-2 units = homophone / ASR spelling noise
        flags.append(dict(kind="missing" if op == "delete" else "changed",
                          text="".join(m if not re.match(r"[a-z0-9]", m) else f" {m} " for m in miss).strip(),
                          got="".join(g[j1:j2]), t=round(e[i1][1], 2)))
    return flags


def print_flags(flags, label=""):
    if not flags:
        print(f"content check{label}: OK - every kept content word is still in the cut")
        return
    print(f"content check{label}: {len(flags)} span(s) to listen to (missing words = a cut ate speech):")
    for f in flags:
        extra = f"  (cut ASR heard '{f['got']}')" if f["got"] else ""
        print(f"  ! {f['kind']:<8} @{f['t']:7.2f}s  '{f['text']}'{extra}")
