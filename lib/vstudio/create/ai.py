"""LLM glue: ``ask(system, prompt, schema)`` -> JSON dict or None (no model set up, fake mode, or a failure;
callers then use their rule-based fallback). Routed as the ``script`` task (SPEC: the ``create`` task's default
route is the same as ``script``; a separate task id is a later, shared-file change)."""
import os

TASK = "script"


def enabled():
    from .providers import fake_mode
    return not fake_mode() and os.environ.get("VSTUDIO_CREATE_NO_LLM") != "1"


def ask(system, prompt, schema, max_tokens=6000, timeout=240):
    if not enabled():
        return None
    try:
        from vstudio import llm
        out = llm.complete(TASK, system, prompt, schema=schema, max_tokens=max_tokens, timeout=timeout)
    except Exception:  # noqa: BLE001  (no provider / expired login / outage: the rules take over)
        return None
    j = (out or {}).get("json")
    return j if isinstance(j, dict) else None


def lang_name(lang):
    return {"zh": "Simplified Chinese", "en": "English", "fr": "French"}.get(str(lang)[:2], "English")
