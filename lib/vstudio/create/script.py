"""Episode scripts: idea -> beats with lines + the shot list (one model call), lint, revise. Rule fallback from
the format's beat template when no model is set up.

    add_episodes(sid, idea_ids, on_event=None) -> [episode]      write(ep) / revise(eid, instruction) -> ep
"""
import re
import statistics

from . import ai, formats as F, store, storyboard
from .i18n import CreateError

SCHEMA = {
    "type": "object",
    "properties": {
        "beats": {"type": "array", "items": {"type": "object", "properties": {
            "beat": {"type": "string"},
            "lines": {"type": "array", "items": {"type": "object", "properties": {
                "who": {"type": "string"}, "text": {"type": "string"}}, "required": ["who", "text"]}},
            "shots": {"type": "array", "items": {"type": "object", "properties": {
                "camera": {"type": "string"}, "action": {"type": "string"},
                "faces": {"type": "array", "items": {"type": "string"}},
                "dur": {"type": "number"}, "card": {"type": ["string", "null"]},
                "line": {"type": ["string", "null"]}}, "required": ["camera", "action", "faces", "dur"]}}},
            "required": ["beat", "lines", "shots"]}},
    },
    "required": ["beats"],
}

SYSTEM = ("You write vertical short-video episodes as shot lists for AI video models and the creator's own camera. "
          "Rules: one action per shot, 1-4 s per shot, camera language (wide / close / low angle / over-the-shoulder), "
          "restrained acting, no text inside shots (put on-screen words in `card`), no real brands. "
          "`faces` lists the cast ids visible in the shot (empty for no people). `line` is the spoken line in that "
          "shot, if any. Write lines in {lang}.")


def _target(bible, fmt):
    return float(bible.get("length_s") or statistics.mean(fmt["length_s"]))


def rule_episode(fmt, bible, idea, lang):
    """Two shots per beat (a wide set-up + a closer reaction / line); repeated beats get a text card."""
    zh = str(lang).startswith("zh")
    cast = [c["id"] for c in bible.get("cast") or []] or ["A"]
    beats = []
    title = idea.get("title") or ""
    for i, b in enumerate(F.expand_beats(fmt, lang)):
        a = cast[i % len(cast)]
        other = cast[(i + 1) % len(cast)]
        line = (f"{b['label']}：{title}" if zh else f"{b['label']}: {title}")
        shots = [dict(camera="wide" if not zh else "全景", faces=[] if i % 3 == 0 else [a, other][:1 + (i % 2)],
                      action=(f"{b['label']} — {idea.get('logline') or title}"), dur=2.0, card=None, line=None)]
        if b.get("n"):
            shots.append(dict(camera="insert", faces=[], action=b["label"], dur=1.5, card=f"*{title}", line=None))
        else:
            shots.append(dict(camera="close" if not zh else "近景", faces=[a], action=line, dur=2.0, card=None,
                              line=line))
        beats.append(dict(beat=b["label"], lines=[dict(who=a, text=line)], shots=shots))
    return dict(beats=beats)


def lint(ep, bible, fmt):
    """Plain checks -> [code]: runtime vs the target, long lines, text asked inside generated shots."""
    out = []
    total = sum(float(s.get("dur") or 0) for s in ep.get("shots") or [])
    tgt = _target(bible, fmt)
    if total and abs(total - tgt) > tgt * 0.25:
        out.append(dict(code="create.lint.length", params=dict(total=round(total), target=round(tgt))))
    for s in ep.get("shots") or []:
        for ln in s.get("lines") or []:
            limit = 36 if re.search(r"[一-鿿]", ln.get("text", "")) else 90
            if len(ln.get("text", "")) > limit:
                out.append(dict(code="create.lint.long-line", params=dict(shot=s["no"])))
        if not s.get("card") and re.search(r"\b(text|sign|caption|subtitle|logo)\b|字幕|文字|招牌|标语",
                                           str(s.get("action") or ""), re.I):
            out.append(dict(code="create.lint.text-in-shot", params=dict(shot=s["no"])))
    return out


def write(ep, sid=None):
    sid = sid or ep["series"]
    s = store.load_series_file(sid)
    meta = store.create_meta(s)
    fmt = F.get(meta["format"])
    bible = store.load_bible(sid)
    lang = meta.get("lang", "en")
    idea = ep.get("idea") or {}
    got = ai.ask(SYSTEM.format(lang=ai.lang_name(lang)),
                 f"Series: {s.get('name')}\nEngine: {bible.get('engine')}\nCast: {bible.get('cast')}\n"
                 f"Always: {(bible.get('rules') or {}).get('always')}\nNever: {(bible.get('rules') or {}).get('never')}\n"
                 f"Beats: {[b['label'] for b in bible.get('beats') or F.expand_beats(fmt, lang)]}\n"
                 f"Episode: {idea.get('title')} - {idea.get('logline')}\nTarget length: {_target(bible, fmt):.0f} s, "
                 f"aspect {bible.get('aspect', '9:16')}.", SCHEMA, max_tokens=8000)
    doc = got if got and got.get("beats") else rule_episode(fmt, bible, idea, lang)
    ep["script"] = dict(beats=[dict(beat=b["beat"], lines=b.get("lines") or []) for b in doc["beats"]],
                        source="ai" if got else "rules")
    ep["shots"] = storyboard.from_beats(doc["beats"], target=_target(bible, fmt), cast=bible.get("cast") or [])
    ep["lint"] = lint(ep, bible, fmt)
    ep["state"] = "boarded"
    ep.setdefault("ladder", dict(stills="todo", animatic="todo", drafts="todo", finals="todo", assemble="todo"))
    return ep


def add_episodes(sid, idea_ids, on_event=None):
    store.need_sid(sid)
    ideas = store.load_ideas(sid)
    pick = [i for i in ideas if i["id"] in set(idea_ids or [])]
    if not pick:
        raise CreateError("bad-input", field="idea_ids")
    have = store.list_episodes(sid)
    no = max([e.get("no") or 0 for e in have] + [0])
    out = []
    for k, idea in enumerate(pick):
        no += 1
        eid = store.new_eid(sid, no)
        ep = dict(id=eid, series=sid, no=no, title=idea["title"], logline=idea.get("logline", ""), idea=idea,
                  state="writing", shots=[], estimates={}, takes={}, created=store.stamp())
        ep["_dir"] = store.episode_dir(eid, sid)
        if on_event:
            on_event(dict(event="create.stage", stage="script", episode=eid, done=k, total=len(pick)))
        write(ep, sid)
        storyboard.write_aivideo(ep, store.load_bible(sid))
        store.save_episode(ep)
        idea["picked"] = True
        idea["episode"] = eid
        out.append(ep)
    store.save_ideas(sid, ideas)
    if on_event:
        on_event(dict(event="create.done", stage="script", episodes=[e["id"] for e in out]))
    return out


def revise(eid, instruction):
    ep = store.load_episode(eid)
    text = str(instruction or "").strip()
    if not text:
        raise CreateError("bad-input", field="instruction")
    ep.setdefault("idea", {})["notes"] = (ep["idea"].get("notes", "") + "\n" + text).strip()
    write(ep)
    storyboard.write_aivideo(ep, store.load_bible(ep["series"]))
    return store.save_episode(ep)
