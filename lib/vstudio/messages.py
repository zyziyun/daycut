"""Engine-originated user text with a stable ``code`` + ``params``, so the desk can localise it (en / zh / fr ...)
without parsing English. Every message dict is ``{code, params, message, message_zh}``; the English ``message``
and Chinese ``message_zh`` stay for the CLI and older desks. The code list is documented in
``references/MESSAGES.md`` (keep the two in sync: ``tests/test_messages.py`` checks it).

    from vstudio import messages as M
    M.msg("plan-fallback", frm="claude-code", to="codex", why="auth-expired")
    M.coded("qc-loudness-off", "Loudness -9.1 LUFS (target -14)")   # a code for a text built elsewhere
"""
from __future__ import annotations

CATALOG = {
    # ---- AI providers (vstudio.llm)
    "llm-all-failed": ("Every AI provider failed ({providers})", "所有 AI 模型都失败了（{providers}）"),
    "llm-fallback": ("{frm} failed ({why}); {to} answered instead", "{frm} 没成功（{why}），改用了 {to}"),
    # ---- plan-segments (vstudio.batch.segplan)
    "plan-fallback": ("{frm} failed ({why}); the segments were planned by {to}",
                      "{frm} 没成功（{why}），这次由 {to} 规划切片"),
    "plan-segments-failed": ("Planning the segments failed ({providers}): {error}",
                             "切片规划失败（{providers}）：{error}"),
    "plan-short-filled": ("{provider} returned {n} usable segment(s); {missing} filled by the rule-based ranking",
                          "{provider} 只给出 {n} 条可用切片，另外 {missing} 条由规则补上"),
    "plan-title-too-long": ("{id}: {provider} title over {limit}: {title}", "{id}：{provider} 给的标题超过 {limit} 字：{title}"),
    # ---- intake plan (vstudio.intake.plan): needs you / questions / risks / warnings
    "intake-needs": ("{text}", "{text}"),
    "intake-question": ("{text}", "{text}"),
    "intake-risk": ("{text}", "{text}"),
    "intake-warning": ("{text}", "{text}"),
    "intake-burned-subs": ("The video already has captions burned in: the old captions are cropped off and new ones "
                           "go in a band (layout {layout})",
                           "视频里已经有烧录字幕：裁掉旧字幕，新字幕放在字幕条里（版式 {layout}）"),
    "intake-aspect-persona": ("{platform}: {aspect} (your persona default)", "{platform}：{aspect}（你的默认设置）"),
    "intake-model-fallback": ("The AI planner was not available ({reason}): the rule planner made this plan",
                              "AI 规划没成功（{reason}），这份计划由规则生成"),
    # ---- project / inbox / status
    "inbox-reason": ("{text}", "{text}"),
    "status-stage": ("{stage}", "{stage}"),
    "status-message": ("{text}", "{text}"),
    "package-state": ("{state}", "{state}"),
    "qc-reason": ("{text}", "{text}"),
    "recipe-description": ("{text}", "{text}"),
    "ai-summary": ("{text}", "{text}"),
    "ai-why": ("{text}", "{text}"),
}


def _fmt(t, params):
    try:
        return t.format(**{k: ("" if v is None else v) for k, v in params.items()})
    except (KeyError, IndexError, ValueError):
        return t


def msg(code, message=None, message_zh=None, **params):
    """{code, params, message, message_zh}: the catalog texts (``message`` / ``message_zh`` override them)."""
    en, zh = CATALOG.get(code, (message or code, message_zh or message or code))
    return dict(code=code, params=params, message=message if message is not None else _fmt(en, params),
                message_zh=message_zh if message_zh is not None else _fmt(zh, params))


def coded(code, text, text_zh=None, **params):
    """A message for a text that is already built (e.g. a QC reason): the text rides in ``params.text``."""
    return msg(code, text, text_zh if text_zh is not None else text, text=text, **params)


def text(code, **params):
    return msg(code, **params)["message"]


__all__ = ["CATALOG", "msg", "coded", "text"]
