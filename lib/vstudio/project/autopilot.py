"""Autopilot: a project runs to finished exports without asking. Every checkpoint a run stops at is answered by the
engine's own judgement - an AI judge for the taste calls (which of the unsure filler cuts to make), the checkpoint's
rules otherwise (its default, the QC verdict, the spend cap; hooks are never picked by a model: no cold open unless
her format asks for one) - and every answer is recorded with who decided and why, so
it can be looked at and changed afterwards. Only real blockers stay for the creator:

    consent          a consent checkpoint (someone else's face / voice): never answered for her
    spend-cap        a budget approval above the cap (``spend_cap`` credits, default 0 = every budget asks)
    qc-red           the review before publishing on a clip whose QC is red (nothing to approve)
    needs-input      an ``author`` checkpoint nothing could be drafted for (no model, a reply that did not parse;
                     the engine drafts these files itself: ``drafts``) or a checkpoint with no default and no AI
                     answer. A seeded template / SYNTHETIC example is never taken for a draft
    asked            she took a decision back ("change it"): the checkpoint waits for her answer

project.yaml::

    autopilot: {on: true, spend_cap: 0, judge: true, lang: en, ask: ["filler:c1"]}

``on`` (``run --autopilot`` writes it, so a resume keeps going the same way), ``judge`` (false: rules only, no model
call), ``lang`` (en | zh | fr: the language the judge writes its reasons in), ``ask`` (``<checkpoint>:<item>``
taken back by her: autopilot leaves them to her).

Each auto-answer is the normal answer record (``answers.<cp>.<item>``) plus ``auto: true, by: ai | rules, reason,
reason_code, provider`` and one line in ``state/autopilot.jsonl`` (the full history, also of answers she later
changed). The checkpoint payloads stay in ``state/checkpoints/<item>/<cp>.json`` (what was shown to the judge).
``decisions(project)`` lists the current ones; ``reopen(project, cp, item)`` takes one back into her Inbox.
"""
import json
import os
import time

NEVER = ("consent",)
APPROVE_KINDS = ("publish", "review")
AUTHOR_KINDS = ("author", "script-lock", "storyboard-approval", "media-selection")
AI_KINDS = ("filler-confirm",)
LOG = "autopilot.jsonl"
LANGS = {"en": "English", "zh": "Simplified Chinese", "fr": "French"}
# a filler cut the rules make without a model: the cleanup's own confidence (her style cuts strictly)
FILLER_MIN_CONFIDENCE = 0.6


def settings(project):
    """The project's autopilot settings (``autopilot: true`` is short for ``{on: true}``)."""
    raw = project.data.get("autopilot")
    d = dict(on=bool(raw)) if not isinstance(raw, dict) else dict(raw)
    d["on"] = bool(d.get("on"))
    d["spend_cap"] = float(d.get("spend_cap") or 0)
    d["judge"] = d.get("judge", True) is not False
    d["ask"] = [str(x) for x in d.get("ask") or []]
    if d.get("lang") not in LANGS:
        d.pop("lang", None)
    return d


def refresh(project):
    """The settings as saved now: the app may switch autopilot while a run goes (read before each round)."""
    import yaml
    try:
        with open(project.yaml_path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
    except (OSError, ValueError):
        return settings(project)
    if "autopilot" in d:
        project.data["autopilot"] = d.get("autopilot")
    return settings(project)


def configure(project, on=None, spend_cap=None, judge=None, lang=None, save=True):
    """Turn autopilot on / off for a project (and its cap / judge / language) in project.yaml -> the settings."""
    d = settings(project)
    if on is not None:
        d["on"] = bool(on)
    if spend_cap is not None:
        d["spend_cap"] = max(0.0, float(spend_cap))
    if judge is not None:
        d["judge"] = bool(judge)
    if lang in LANGS:
        d["lang"] = lang
    project.data["autopilot"] = d
    if save:
        project.save()
    return d


def key(cp_id, item):
    return f"{cp_id}:{item}"


# --------------------------------------------------------------------------- deciding
def _rule(code, reason, value, **params):
    return dict(value=value, by="rules", reason=reason, reason_code=code, params=params)


def _block(code, reason, **params):
    return dict(blocker=code, reason=reason, params=params)


def rules(cp, pay, spend_cap=0.0):
    """The checkpoint's rules: -> a decision {value, by: rules, reason, reason_code} or a blocker {blocker, reason}."""
    kind = cp["kind"]
    default = pay.get("default")
    if kind in NEVER:
        return _block("consent", "consent is the creator's own call")
    if kind == "budget-approval":
        total = float(pay.get("total_credits") or 0)
        unknown = pay.get("unknown_items") or []
        if unknown:
            return _block("spend-cap", f"the cost of {len(unknown)} item(s) is unknown", total=total, cap=spend_cap)
        if total > spend_cap + 1e-9:
            return _block("spend-cap", f"{total:g} credits is over the {spend_cap:g} cap", total=total, cap=spend_cap)
        return _rule("within-cap", f"{total:g} credits, within the {spend_cap:g} cap", dict(approve=True, budget=total),
                     total=total, cap=spend_cap)
    if kind in APPROVE_KINDS:
        qc = pay.get("qc") or {}
        if default is None:
            return _block("qc-red", "; ".join(str(r) for r in qc.get("reasons") or []) or "the checks did not pass",
                          reasons=[str(r) for r in qc.get("reasons") or []][:5])
        return _rule("qc-passed" if qc.get("status") else "approve", f"checks {qc.get('status') or 'passed'}", default,
                     qc=qc.get("status"))
    if kind == "filler-confirm":
        opts = pay.get("options") or []
        cut = [int(o["id"]) for o in opts if float(o.get("confidence") or 0) >= FILLER_MIN_CONFIDENCE]
        keep = [int(o["id"]) for o in opts if int(o["id"]) not in cut]
        return _rule("filler-confidence", f"cut {len(cut)} of {len(opts)} (the sure ones), kept {len(keep)}",
                     dict(approve=cut, keep=keep), cut=len(cut), kept=len(keep), n=len(opts))
    if default is None:
        if kind in AUTHOR_KINDS:
            # nothing drafted (no model, a reply that did not parse) - never the seeded template / example
            return _block("needs-input", "nothing could be drafted for this step" + (
                f" ({pay['draft_error']})" if pay.get("draft_error") else ""), file=os.path.basename(
                str(pay.get("file") or "")), state=pay.get("draft_state"))
        return _block("needs-input", "nothing to go on (no default)")
    if kind in AUTHOR_KINDS:
        rv = pay.get("review") or {}
        summ = rv.get("summary") or {}
        by = pay.get("draft_by")
        params = dict(summ.get("params") or {}, summary=summ.get("code"), state=pay.get("draft_state"))
        if by == "ai":
            return dict(value=default, by="ai", provider=rv.get("provider"), reason=rv.get("ai_summary") or
                        "the AI's draft", reason_code="drafted", params=params)
        return _rule("drafted" if pay.get("draft_state") == "drafted" else "hers",
                     "the drafted file" if pay.get("draft_state") == "drafted" else "your own file", default, **params)
    if kind == "hook-pick":
        pick = int((default or {}).get("pick", -1))
        return _rule("hook-default", "no cold open (your style)" if pick < 0 else f"opening {pick + 1}", default,
                     pick=pick)
    if kind == "cover-pick":
        return _rule("cover-best", "the best-scored frame", default, pick=int((default or {}).get("pick", 0)))
    return _rule("default", "the suggested answer", default)


SYSTEM = ("You are the editor of a short-video studio running on autopilot: you take the small taste decisions a "
          "human editor would, quickly and consistently, so the video can be finished without asking the creator. "
          "Prefer tight, premium edits: cut filler words, false starts and repeats; keep words that carry meaning or "
          "emphasis.")


def _ai_prompt(cp, pay, context, lang):
    kind = cp["kind"]
    opts = pay.get("options") or []
    rows = [dict(id=o.get("id"), kind=o.get("kind"), text=o.get("text"), before=str(o.get("before") or "")[-60:],
                 after=str(o.get("after") or "")[:60], reason=o.get("reason"), confidence=o.get("confidence"))
            for o in opts[:80]]
    ask = ('Decide each proposed cut. Reply {"approve": [ids to cut], "keep": [ids to keep], "reason": "one short '
           'sentence"}. Every id goes in exactly one list.')
    return (f"Request: {context or '(none)'}\nDecision: {cp['labels'].get('en') or cp['id']} ({kind})\n"
            f"Options:\n{json.dumps(rows, ensure_ascii=False)}\n\n{ask} Write the reason in "
            f"{LANGS.get(lang or 'en', 'English')}.")


def _ai_value(cp, pay, doc):
    """The model's reply -> a valid answer value, or None."""
    if not isinstance(doc, dict):
        return None
    ids = {int(o["id"]) for o in pay.get("options") or []}
    if "approve" not in doc and "keep" not in doc:
        return None                                        # neither list: not an answer
    try:
        cut = sorted({int(x) for x in doc.get("approve") or []} & ids)
    except (TypeError, ValueError):
        return None
    return dict(approve=cut, keep=sorted(ids - set(cut)))


def judge(cp, pay, context="", lang=None, complete=None, timeout=90):
    """The AI judge for a taste call -> {value, by: ai, reason, provider} or None (no model, a bad reply, an error:
    the rules decide). ``complete``: vstudio.llm.complete (tests pass a fake)."""
    if cp["kind"] not in AI_KINDS or not (pay.get("options") or []):
        return None
    if complete is None:
        from vstudio import llm
        complete = llm.complete
    try:
        r = complete("planner", SYSTEM, _ai_prompt(cp, pay, context, lang), schema=True, max_tokens=2000,
                     timeout=timeout, cli_timeout=timeout, retries=1)
    except Exception as e:  # noqa: BLE001  (no provider, auth, timeout: the rules decide, said in the record)
        return dict(error=str(e)[:200])
    if not isinstance(r, dict) or r.get("provider") == "none":
        return None
    v = _ai_value(cp, pay, r.get("json"))
    if v is None:
        return dict(error="the model's answer did not fit the options")
    reason = str((r.get("json") or {}).get("reason") or "").strip()[:300]
    return dict(value=v, by="ai", reason=reason or "the AI's pick", reason_code="ai", provider=r.get("provider"),
                model=r.get("model"), params=_summary_params(cp["kind"], v, pay))


def _summary_params(kind, value, pay):
    v = value or {}
    if kind == "filler-confirm":
        return dict(cut=len(v.get("approve") or []), kept=len(v.get("keep") or []), n=len(pay.get("options") or []))
    if kind == "hook-pick":
        k = int(v.get("pick", -1))
        opts = pay.get("options") or []
        return dict(pick=k, text=(opts[k].get("text") if 0 <= k < len(opts) else None))
    return {}


def decide(project, pay, complete=None):
    """One pending checkpoint payload -> a decision (``value`` set) or a blocker (``blocker`` set)."""
    s = settings(project)
    cp = project.checkpoint(pay["id"])
    if key(pay["id"], "*" if cp["scope"] == "project" else pay.get("item")) in s["ask"]:
        return _block("asked", "you asked to decide this one")
    base = rules(cp, pay, s["spend_cap"])
    if base.get("blocker") or not s["judge"] or cp["kind"] not in AI_KINDS:
        return base
    ctx = project.data.get("prompt") or project.data.get("name") or ""
    ai = judge(cp, pay, ctx, s.get("lang"), complete=complete)
    if ai and ai.get("value") is not None:
        return ai
    if ai and ai.get("error"):
        base = dict(base, ai_error=ai["error"])
    return base


# --------------------------------------------------------------------------- the record
def log_path(project):
    return os.path.join(project.state_dir, LOG)


def log(project, entry):
    os.makedirs(project.state_dir, exist_ok=True)
    with open(log_path(project), "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(entry, at=entry.get("at") or time.strftime("%Y-%m-%dT%H:%M:%S")),
                           ensure_ascii=False, default=str) + "\n")


def history(project):
    out = []
    try:
        with open(log_path(project), encoding="utf-8") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def answer_meta(d):
    """The fields an auto-answer adds to the answer record."""
    return {k: d[k] for k in ("by", "reason", "reason_code", "provider", "params") if d.get(k) not in (None, {}, "")}


def decisions(project):
    """The auto-decisions in force (newest first): {checkpoint, kind, item, labels, value, by, reason, reason_code,
    params, provider, at, payload}. A decision she changed is hers (not listed); one she took back is ``asked``."""
    out = []
    s = settings(project)
    for cid, per in (project.data.get("answers") or {}).items():
        try:
            cp = project.checkpoint(cid)
        except Exception:  # noqa: BLE001  (a checkpoint the recipe no longer has)
            continue
        for item, rec in (per or {}).items():
            if not isinstance(rec, dict) or not rec.get("auto"):
                continue
            pay = os.path.join(project.state_dir, "checkpoints", item, f"{cid}.json") if item != "*" else None
            out.append(dict(checkpoint=cid, kind=cp["kind"], item=item, labels=cp.get("labels") or {},
                            value=rec.get("value"), by=rec.get("by") or "rules", reason=rec.get("reason"),
                            reason_code=rec.get("reason_code"), params=rec.get("params") or {},
                            provider=rec.get("provider"), at=rec.get("at"),
                            payload=pay if pay and os.path.exists(pay) else None))
    for k in s["ask"]:
        cid, _, item = k.partition(":")
        out.append(dict(checkpoint=cid, item=item, asked=True))
    out.sort(key=lambda d: str(d.get("at") or ""), reverse=True)
    return out


def reopen(project, cp_id, item):
    """She wants to decide this one herself: the auto-answer goes (kept in the log), the checkpoint is left to her
    (``ask``) and re-planned, so the next run stops there and the Inbox asks her. -> {ok, rerun}."""
    cp = project.checkpoint(cp_id)
    target = "*" if cp["scope"] == "project" else item
    rec = ((project.data.get("answers") or {}).get(cp_id) or {}).get(target)
    if not isinstance(rec, dict):
        from .core import ProjectError
        raise ProjectError(f"{cp_id} has no answer for {target}")
    del project.data["answers"][cp_id][target]
    if not project.data["answers"][cp_id]:
        del project.data["answers"][cp_id]
    s = settings(project)
    if key(cp_id, target) not in s["ask"]:
        s["ask"].append(key(cp_id, target))
    project.data["autopilot"] = s
    project.save()
    log(project, dict(event="reopened", checkpoint=cp_id, item=target, was=rec.get("value"), by=rec.get("by")))
    project.plan()
    stale = project.stale()
    return dict(ok=True, checkpoint=cp_id, item=target,
                rerun={j: st for j, st in stale.items() if st and (target == "*" or j == item)})
