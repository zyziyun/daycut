"""LLM glue for Create: ``ask(system, prompt, schema)`` -> JSON dict or None (no model set up, or a failure), and
``ask_or_fail`` -> the dict or ``CreateError("ai-failed", reason=...)``: the series bible, more ideas, bible changes
and episode scripts never swap a failed answer for rules (only "Start from the template" is template text, and it
says so). Routed as the ``script`` task (SPEC: the ``create`` task's
default route is the same as ``script``; a separate task id is a later, shared-file change).

Every call is bounded: each CLI attempt (Claude Code / Codex subscriptions) gets ``VSTUDIO_CREATE_AI_TIMEOUT``
seconds (default 90; an expired ``claude -p`` otherwise drags on for ~4 minutes before the fallback even starts)
and the whole call, fallbacks included, ``VSTUDIO_CREATE_AI_DEADLINE`` seconds (default 200). ``strict=True``
raises ``AIFailed`` (code timeout | auth-expired | not-installed | failed | bad-answer) instead of returning None,
so a screen that waits on the answer (Plan) can say what happened and offer Retry / "Use simple rules".
``on_event`` gets ``{"event": "create.step", "step": "fallback", "from", "to", "code"}`` before each fallback.
"""
import os
import threading
import time

TASK = "script"


class AIFailed(RuntimeError):
    def __init__(self, code, provider=None, error="", seconds=0.0, tried=()):
        super().__init__(f"{code}: {error}"[:300])
        self.code, self.provider, self.error, self.seconds, self.tried = code, provider, error, seconds, list(tried)


def _num(env, default):
    try:
        v = float(os.environ.get(env) or default)
        return v if v > 0 else default
    except ValueError:
        return default


def attempt_timeout():
    return _num("VSTUDIO_CREATE_AI_TIMEOUT", 90.0)


def deadline():
    return _num("VSTUDIO_CREATE_AI_DEADLINE", 200.0)


def provider():
    """The provider the ``script`` task routes to ("none" when nothing is set up), never raises."""
    try:
        from vstudio import llm
        return llm.route(TASK).provider or "none"
    except Exception:  # noqa: BLE001
        return "none"


def configured():
    return provider() != "none"


def ask(system, prompt, schema, max_tokens=6000, timeout=None, on_event=None, strict=False):
    who = provider()
    if who == "none":
        if strict:
            raise AIFailed("not-set-up", "none", "no AI is set up for scripts")
        return None
    per = float(timeout or attempt_timeout())
    limit = max(per, deadline())
    box = {}

    def fallback(info):
        if on_event:
            try:
                on_event({"event": "create.step", "step": "fallback", "from": info.get("from"), "to": info.get("to"),
                          "code": info.get("code")})
            except Exception:  # noqa: BLE001
                pass

    def go():
        try:
            from vstudio import llm
            box["out"] = llm.complete(TASK, system, prompt, schema=schema, max_tokens=max_tokens, timeout=per,
                                      cli_timeout=per, retries=1, on_fallback=fallback)
        except Exception as e:  # noqa: BLE001  (no provider / expired login / outage)
            box["err"] = e

    t0 = time.time()
    th = threading.Thread(target=go, daemon=True, name="create-ai")
    th.start()
    th.join(limit)
    secs = round(time.time() - t0, 1)
    fail = None
    if th.is_alive():
        fail = AIFailed("timeout", who, f"no answer in {int(limit)} s", secs)
    elif "err" in box:
        e = box["err"]
        try:
            from vstudio import llm
            a = getattr(e, "attempts", None) or []
            code = (a[0].get("code") if a else None) or llm.failure_code(e)
            tried = [a.get("provider") for a in getattr(e, "attempts", None) or []]
        except Exception:  # noqa: BLE001
            code, tried = "failed", []
        fail = AIFailed(code or "failed", who, str(e)[:300], secs, tried)
    else:
        j = (box.get("out") or {}).get("json")
        if isinstance(j, dict):
            return j
        fail = AIFailed("bad-answer", (box.get("out") or {}).get("provider") or who, "no JSON in the answer", secs)
    if on_event:
        try:
            on_event({"event": "create.step", "step": "ai-failed", "code": fail.code, "provider": fail.provider,
                      "seconds": fail.seconds})
        except Exception:  # noqa: BLE001
            pass
    if strict:
        raise fail
    return None


def ask_or_fail(system, prompt, schema, **kw):
    """``ask`` that never comes back empty: no AI set up, a timeout, an expired login or an answer without JSON ->
    ``CreateError("ai-failed", reason, provider, seconds, tried)`` (the desk shows the reason and Retry)."""
    from .i18n import CreateError
    try:
        got = ask(system, prompt, schema, strict=True, **kw)
    except AIFailed as e:
        raise CreateError("ai-failed", status=503, reason=e.code, provider=e.provider or "", seconds=e.seconds,
                          tried=e.tried) from e
    if not isinstance(got, dict):
        raise CreateError("ai-failed", status=503, reason="bad-answer", provider=provider(), seconds=0)
    return got


def lang_name(lang):
    return {"zh": "Simplified Chinese", "en": "English", "fr": "French"}.get(str(lang)[:2], "English")
