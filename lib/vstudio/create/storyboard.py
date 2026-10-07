"""Script beats -> numbered shots (durations fitted to the target length), plus the ai-video project file
(work/ai/project.yaml: characters, shots) so generate.py / plan.py / assemble.py work on an episode unchanged."""
import os

from . import store

MIN_DUR, MAX_DUR = 1.0, 4.0


def from_beats(beats, target=None, cast=()):
    ids = {c["id"] for c in cast}
    shots = []
    for b in beats:
        for s in b.get("shots") or []:
            n = len(shots) + 1
            faces = [f for f in (s.get("faces") or []) if not ids or f in ids]
            line = s.get("line")
            who = next((ln["who"] for ln in b.get("lines") or [] if ln.get("text") == line), faces[0] if faces else "")
            shots.append(dict(no=f"{n:02d}", beat=b["beat"], dur=float(s.get("dur") or 2), faces=faces,
                              camera=s.get("camera", ""), action=s.get("action", ""),
                              lines=[dict(who=who, text=line)] if line else [], card=s.get("card") or None))
    if target and shots:
        total = sum(s["dur"] for s in shots)
        k = target / total if total else 1
        for s in shots:
            s["dur"] = round(min(MAX_DUR, max(MIN_DUR, s["dur"] * k)), 1)
    return shots


def write_aivideo(ep, bible, provider="kling-mcp", model="kling-video-v3_0_omni"):
    """work/ai/project.yaml in the ai-video format (characters from the cast, one shot per board shot)."""
    chars = {}
    for c in bible.get("cast") or []:
        ch = dict(look=c.get("look") or c.get("essence") or "")
        if c.get("look_refs"):
            ch["ref"] = c["look_refs"][0]
        if c.get("kling_element_id"):
            ch["element"] = c["kling_element_id"]
        chars[c["id"]] = ch
    shots = []
    for s in ep.get("shots") or []:
        if s.get("card"):
            continue
        shots.append(dict(id=s["no"], chars=s.get("faces") or [], dur=s.get("dur"), camera=s.get("camera", ""),
                          action=s.get("action", ""), lines=s.get("lines") or [],
                          audio="native" if s.get("lines") else "post", **({"unit": s["unit"]} if s.get("unit") else {})))
    lang = (bible.get("languages") or ["en"])[0]
    proj = dict(title=ep.get("title"), aspect=bible.get("aspect", "9:16"), language=lang, provider=provider,
                model=model, resolution="1080p", characters=chars, scenes={}, shots=shots,
                style="Real-photo look, natural light, handheld documentary framing.")
    path = os.path.join(store.work_dir(ep), "project.yaml")
    store.write_yaml(path, proj)
    return path
