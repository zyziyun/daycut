"""Episode done -> assembled master -> a normal work folder (registered like every other job) so the existing
editor, captions, languages and calendar take it from here (SPEC §1 handoff).

    assemble(eid)                     -> work/ai/master.mp4 via ai-video assemble.py (picks, text cards in post)
    handoff(eid, languages, schedule) -> {dir, file, clip, languages[], posts[]}   (the desk adds the posts to its
                                         calendar; publishing itself is always pressed by the creator)
"""
import datetime as DT
import hashlib
import os
import shutil

from . import ai, formats as F, jobs, store, stills
from .i18n import CreateError

LANG_PLATFORMS = {"zh": ["xiaohongshu", "douyin"], "en": ["youtube-shorts", "tiktok"], "fr": ["instagram"]}   # registry order
SLOTS = [(3, "20:00"), (4, "09:00"), (5, "12:00"), (6, "20:00")]       # Thu 20:00, Fri 09:00, Sat 12:00 ...
AI_LABEL = {"zh": "AI 生成 · 仅供娱乐", "en": "AI-generated · for fun", "fr": "Généré par IA · pour rire"}


# the master's canvas / frame rate / film grain (tests/create_fake.py makes them small and fast)
CANVAS, FPS, GRAIN = (1080, 1920), 30, 3


def _timeline(ep):
    d = store.work_dir(ep)
    picks = ep.get("picks") or {}
    takes = ep.get("takes") or {}
    edl = []
    size = CANVAS
    for sh in ep.get("shots") or []:
        dur = float(sh.get("dur") or 2)
        f = picks.get(sh["no"]) or ((takes.get(sh["no"]) or [{}])[0].get("file"))
        src = sh.get("source") or ""
        if src.startswith("reuse:"):
            other, no = src[6:].split("/")
            try:
                f = (store.load_episode(other).get("picks") or {}).get(no) or f
            except CreateError:
                pass
        if sh.get("card"):
            png = stills.card_png(sh["card"], os.path.join(d, "cards", f"{sh['no']}.png"), size=size)
            edl.append({"still": png, "dur": dur})
        elif f and os.path.exists(f):
            from .record import duration
            length = duration(f) or dur
            edl.append({"take": f, "in": 0.0, "out": round(min(dur, length), 3)})
        else:
            still = sh.get("still") or stills.placeholder(sh, os.path.join(d, "stills", f"{sh['no']}.jpg"))
            edl.append({"still": still, "dur": dur})
    return dict(canvas=list(size), fps=FPS, takes_dir="takes", out="master.mp4",
                grade=dict(saturation=0.92, grain=GRAIN), edl=edl, music=dict(path=None),
                captions=dict(language="zh", max_chars=32, out="cues.json"))


def assemble(eid, on_event=None):
    from .providers.aivideo import _import
    ep = store.load_episode(eid)
    if not ep.get("shots"):
        raise CreateError("nothing-to-make", status=409)
    path = os.path.join(store.work_dir(ep), "timeline.yaml")
    store.write_yaml(path, _timeline(ep))
    A = _import("assemble")
    t = A.load(path)
    res = A.assemble(t, asr=False, out=lambda m: on_event and on_event(dict(event="create.progress",
                                                                             stage="assemble", message=str(m)[:200])))
    with jobs.lock(eid):
        ep = store.load_episode(eid)
        ep.setdefault("ladder", {})["assemble"] = "done"
        ep["master"] = res["master"]
        store.save_episode(ep)
    return res["master"]


def _srt(cues):
    def ts(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i + 1}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(cues))


def script_cues(ep):
    t, out = 0.0, []
    for sh in ep.get("shots") or []:
        dur = float(sh.get("dur") or 2)
        for ln in sh.get("lines") or []:
            if ln.get("text"):
                out.append((t, t + dur, ln["text"]))
        t += dur
    return out


def translate(lines, lang, src_lang):
    if lang == src_lang or not lines:
        return lines, 0
    got = ai.ask("You translate short-video dialogue for subtitles: natural, short, same meaning, no notes.",
                 f"Translate each line into {ai.lang_name(lang)}. Lines: {lines}",
                 {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
                  "required": ["lines"]})
    tr = (got or {}).get("lines")
    if isinstance(tr, list) and len(tr) == len(lines):
        return tr, 0
    return lines, len(lines)                     # untranslated: the creator checks these lines in the editor


def next_slots(n, now=None):
    now = now or DT.datetime.now()
    out, day = [], now.date()
    while len(out) < n:
        for wd, hm in SLOTS:
            if day.weekday() == wd:
                hh, mm = (int(x) for x in hm.split(":"))
                at = DT.datetime(day.year, day.month, day.day, hh, mm)
                if at > now:
                    out.append(at.strftime("%Y-%m-%dT%H:%M"))
        day += DT.timedelta(days=1)
    return out[:n]


def handoff(eid, languages=None, schedule=True, register=True, on_event=None):
    ep = store.load_episode(eid)
    sid = ep["series"]
    s = store.load_series_file(sid)
    meta = store.create_meta(s)
    bible = store.load_bible(sid)
    fmt = F.get(meta["format"])
    master = ep.get("master") if ep.get("master") and os.path.exists(ep["master"]) else assemble(eid, on_event)
    langs = [x for x in (languages or bible.get("languages") or ["zh"]) if x in ("zh", "en", "fr")] or ["zh"]
    src_lang = (bible.get("languages") or langs)[0]
    slug = store.slugify(ep.get("title") or eid, 30) or eid
    d = os.path.join(store.series_dir(sid), "delivered", eid)
    fin = os.path.join(d, "final")
    os.makedirs(fin, exist_ok=True)
    clip = f"{ep.get('no', 0):02d}_{slug}"
    dst = os.path.join(fin, f"{clip}.mp4")
    shutil.copy2(master, dst)
    first = next((sh.get("still") for sh in ep.get("shots") or [] if sh.get("still")), None)
    if first and os.path.exists(first):
        shutil.copy2(first, os.path.join(fin, f"{clip}_cover.jpg"))
    cues = script_cues(ep)
    rows, post = [], [f"# {s.get('name')} · {ep.get('title')}\n"]
    for lang in langs:
        texts, n_check = translate([c[2] for c in cues], lang, src_lang)
        if cues:
            with open(os.path.join(fin, f"{clip}.{lang}.srt"), "w", encoding="utf-8") as f:
                f.write(_srt([(a, b, tx) for (a, b, _), tx in zip(cues, texts)]))
        kind = "original" if lang == src_lang else ("bilingual" if lang == "en" else "translated")
        rows.append(dict(lang=lang, kind=kind, state="check" if n_check else "ready", n_check=n_check,
                         platforms=LANG_PLATFORMS.get(lang, ["tiktok"])))
        label = AI_LABEL[lang] if bible.get("ai_generated", fmt["recipe"] == "ai-video") else ""
        post.append(f"## {clip}.mp4 · {lang}\n\n{ep.get('title')}\n\n{ep.get('logline') or ''}\n\n{label}\n")
    with open(os.path.join(d, "post.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(post))
    from vstudio.project import works
    works.touch(d, recipe="ai-video", title=f"{s.get('name')} · {ep.get('title')}", outputs=[dst],
                register=register)
    posts = []
    if schedule:
        slots = next_slots(len(rows))
        for r, at in zip(rows, slots):
            posts.append(dict(lang=r["lang"], platforms=r["platforms"], at=at, clip=clip))
    spent = sum(float(x.get("est_cny") or 0) for x in store.read_jsonl(store.ledger_path(sid))
                if x.get("episode") == eid and x.get("status") in ("submitted", "unknown-charge"))
    approved = max([float(a.get("max_cny") or 0) for a in ep.get("approved") or []] + [0.0])
    est = next((e for e in (ep.get("estimates") or {}).values() if e.get("id") == (ep.get("run") or {}).get("estimate")),
               None)
    with jobs.lock(eid):
        ep = store.load_episode(eid)
        item_id = hashlib.sha1(os.path.realpath(d).encode()).hexdigest()[:12]      # the desk's history id (real folder)
        ep["handoff"] = dict(dir=d, file=dst, clip=clip, item_id=item_id, languages=rows, posts=posts, at=store.stamp(),
                             spent=round(spent, 1), approved=approved,
                             under=None if not est else round(float(est.get("subtotal_cny") or 0) - spent, 1),
                             ai_label=bool(bible.get("ai_generated", True)))
        ep["state"] = "ready"
        store.save_episode(ep)
    return dict(ok=True, episode=eid, **ep["handoff"])
