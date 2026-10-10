"""explainer: the voice checkpoint (paid TTS: voice / speed confirmed first, with a cost estimate)."""
import os
import re

from ..build import file_sha

VOICES = ["cedar", "marin", "alloy", "ash", "coral", "sage", "verse", "ballad"]
USD_PER_MIN = 0.015           # gpt-4o-mini-tts, workflows/explainer/WORKFLOW.md


def spoken_words(script_path):
    try:
        with open(script_path, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return 0
    spoken = [ln.strip() for ln in txt.splitlines() if ln.startswith("    ") and ln.strip()]
    return sum(len(re.findall(r"[A-Za-z0-9']+", s)) for s in spoken)


def voice_payload(env, cp):
    script = os.path.join(env.item_dir, "SCRIPT.md")
    words = spoken_words(script)
    speed = float(env.params.get("speed") or 1.0)
    minutes = words / (165.0 * speed) if words else 0.0
    cur = env.params.get("voice") or "cedar"
    return dict(options=[dict(voice=v, current=v == cur) for v in VOICES], words=words,
                minutes=round(minutes, 2), estimate_usd=round(minutes * USD_PER_MIN * 1.5, 3),
                digest=file_sha(script) or "none",
                default=dict(voice=cur, speed=speed, approve=True),
                previews=[dict(kind="markdown", path=script)])


def voice_apply(a):
    v = a.value or {}
    if not v.get("approve"):
        return dict(params={}, digest="not-approved")
    p = {}
    if v.get("voice"):
        p["voice"] = v["voice"]
    if v.get("speed"):
        p["speed"] = float(v["speed"])
    return dict(params={}, project_params=p) if p else dict(params={})


def draft_cues(ctx, cp, path, template=None, instruction=None, complete=None):
    """The subtitle pairing (``subtitles/cues.txt``) drafted by the engine: the workflow's own pairing
    (``pair_cues.py`` -> ``cues.draft.txt``, EN || ZH per cue) taken as it is - she checks it, she never retypes it.
    With an instruction ("make the Chinese shorter") the AI rewrites it from that draft (``drafts.generic``)."""
    draft = os.path.join(os.path.dirname(path), "cues.draft.txt")
    if not os.path.isfile(draft):
        return None
    if instruction:
        from .. import drafts as DR
        with open(draft, encoding="utf-8") as f:
            text = f.read()
        return DR.generic(ctx, cp, path, instruction=instruction, complete=complete, template_text=text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(draft, encoding="utf-8") as f, open(path, "w", encoding="utf-8") as g:
        g.write(f.read())
    cues = 0
    with open(path, encoding="utf-8") as f:
        cues = sum(1 for ln in f if "||" in ln)
    return dict(by="rules", instruction=None, review=dict(kind="outline", lines=[], summary=dict(
        code="draft.items", params=dict(n=cues))))
