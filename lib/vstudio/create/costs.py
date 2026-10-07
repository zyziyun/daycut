"""Rates, estimates, the spend gate and the ledger - the core safety contract (SPEC §1.5).

    price_job(provider, model, seconds, resolution) -> {seconds_billed, native_units, cny, unknown, manual}
    estimate(eid, stage)            -> Estimate {id, stage, lines[], free{}, subtotal_cny, retry_cny, max_cny,
                                       unknown[], confirm_code, expires_at, budget{...}, month{...}}
    check(est, sid, allow_unknown)  -> {ok, codes[]}  (series budget, monthly cap, unknown rates, credits, ready)
    verify(ep, estimate_id, code, max_cny) -> the stored estimate, or CreateError (mismatch / expired / changed)
    ledger_append(sid, row)         append-only spend.jsonl + the month counter
"""
import hashlib
import json
import math
import os
import threading
import time

from . import store
from .i18n import CreateError, msg

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIRM_TTL_S = 15 * 60
DEFAULT_RETRY = 0.30
DEFAULT_CAP = 300.0
COUNTED = ("submitted", "unknown-charge")
_rates = {}
_month_lock = threading.Lock()


# --------------------------------------------------------------------------- rates
def load_rates():
    path = os.environ.get("VSTUDIO_CREATE_RATES") or os.path.join(HERE, "rates.json")
    if _rates.get("path") != path:
        with open(path, encoding="utf-8") as f:
            _rates.update(path=path, doc=json.load(f))
    return _rates["doc"]


def entry(provider, model):
    return ((load_rates().get("providers") or {}).get(provider) or {}).get(model)


def models_for(provider):
    return list(((load_rates().get("providers") or {}).get(provider) or {}).keys())


def snap(e, seconds, resolution=None):
    """Seconds the service bills for a clip of ``seconds`` (discrete clip lengths, or min / step / max).
    ``clips_s_by_res`` narrows the lengths per resolution (Veo 3.1: 1080p is 8 s only)."""
    seconds = max(0.1, float(seconds or 0))
    clips = (e.get("clips_s_by_res") or {}).get(resolution or e.get("resolution")) or e.get("clips_s")
    if clips:
        ok = sorted(clips)
        return float(next((v for v in ok if v >= seconds - 1e-6), ok[-1]))
    lo, hi, step = e.get("min_clip_s") or 1, e.get("max_clip_s") or 60, e.get("step_s") or 1
    v = max(lo, math.ceil((seconds - 1e-6) / step) * step)
    return float(min(v, hi))


def price_job(provider, model, seconds, resolution=None, kind="video"):
    e = entry(provider, model)
    if not e:
        return dict(seconds_billed=None, native_units=None, cny=None, unknown=True, manual=False, verified=False)
    fx = (load_rates().get("fx") or {}).get("USD", 7.1)
    res = resolution or e.get("resolution")
    out = dict(unknown=False, manual=bool(e.get("manual")), verified=bool(e.get("verified")), label=e.get("label"))
    if e.get("unit") == "image":
        n = max(1, int(seconds or 1))
        credits = (e.get("credits_per_image") or 0) * n
        out.update(seconds_billed=None, native_units=credits,
                   cny=round(credits * e["cny_per_credit"], 2) if e.get("cny_per_credit") else None)
        return out
    billed = snap(e, seconds, res)
    out["seconds_billed"] = billed
    cps = (e.get("credits_per_s") or {}).get(res)
    out["native_units"] = round(cps * billed) if cps else None
    if e.get("manual"):
        out["cny"] = 0.0                          # spent in the user's own web membership, not by Reelfold
    elif e.get("usd_per_clip"):
        tbl = (e["usd_per_clip"].get(res) or {})
        usd = tbl.get(str(int(billed)))
        out["cny"] = None if usd is None else round(usd * fx, 2)
    elif e.get("usd_per_s") is not None:
        usd = e["usd_per_s"].get(res) if isinstance(e["usd_per_s"], dict) else e["usd_per_s"]
        out["cny"] = None if usd is None else round(usd * billed * fx, 2)
    elif e.get("cny_per_s") is not None:
        out["cny"] = round(e["cny_per_s"] * billed, 2)
    elif cps and e.get("cny_per_credit"):
        out["cny"] = round(cps * billed * e["cny_per_credit"], 2)
    else:
        out["cny"] = None
    out["unknown"] = out["cny"] is None
    return out


# --------------------------------------------------------------------------- month + ledger
def _this_month():
    return time.strftime("%Y-%m")


def month():
    d = store.read_json(store.month_path(), {}) or {}
    cur = _this_month()
    if d.get("month") != cur:
        d = dict(month=cur, cap_cny=d.get("cap_cny", DEFAULT_CAP), used_cny=0.0)
    d.setdefault("cap_cny", DEFAULT_CAP)
    d.setdefault("used_cny", 0.0)
    return d


def set_cap(cap):
    if cap is not None and not (isinstance(cap, (int, float)) and not isinstance(cap, bool) and 0 <= cap <= 100000):
        raise CreateError("bad-input", field="cap_cny")
    with _month_lock:
        d = month()
        d["cap_cny"] = None if cap is None else float(cap)
        store.write_json(store.month_path(), d)
    return d


def check_money(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CreateError("bad-input", field="cny") from None
    if not (0 <= f <= 100000):
        raise CreateError("bad-input", field="cny")
    return f


def ledger_append(sid, row):
    row = dict(row, ts=row.get("ts") or store.stamp())
    store.append_jsonl(store.ledger_path(sid), row)
    if row.get("status") in COUNTED:
        with _month_lock:
            d = month()
            d["used_cny"] = round(float(d.get("used_cny") or 0) + float(row.get("charged_cny") or row.get("est_cny") or 0),
                                  2)
            store.write_json(store.month_path(), d)
    return row


def ledger(sid):
    return store.read_jsonl(store.ledger_path(sid))


def spent(sid):
    return round(sum(float(r.get("charged_cny") or r.get("est_cny") or 0) for r in ledger(sid)
                     if r.get("status") in COUNTED), 2)


def series_budget(series_doc):
    b = store.create_meta(series_doc).get("budget_cny")
    return None if b is None else float(b)


def summary(sid=None):
    m = month()
    out = dict(month=m["month"], cap=m.get("cap_cny"), used=round(float(m.get("used_cny") or 0), 2))
    if sid:
        s = store.load_series_file(sid)
        out["series"] = dict(budget=series_budget(s), spent=spent(sid))
        out["lines"] = ledger(sid)[-200:]
    return out


# --------------------------------------------------------------------------- estimates
def confirm_code(lines, version, eid, stage):
    blob = json.dumps(lines, sort_keys=True, ensure_ascii=False) + str(version) + eid + stage
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


def retry_pct(series_doc):
    v = store.create_meta(series_doc).get("retry_pct")
    return DEFAULT_RETRY if v is None else float(v)


def build(ep, series_doc, stage, routes, units):
    """Pure: the estimate for ``stage`` from resolved routes + units (no IO except rates)."""
    lines, free, unknown = {}, {}, []
    by_no = {r["no"]: r for r in routes}
    if stage == "finals":
        for u in units:
            kind = u["kind"]
            if kind in ("cloud", "mcp", "manual"):
                p = price_job(u["provider"], u["model"], u["seconds"], u.get("resolution"))
                key = f"{u['provider']}/{u['model']}"
                ln = lines.setdefault(key, dict(provider=u["provider"], model=u["model"], label=p.get("label") or u["model"],
                                                kind=kind, shots=[], units=0, seconds_video=0.0, seconds_billed=0.0,
                                                native_units=0, cny=0.0, manual=kind == "manual",
                                                verified=p.get("verified", False)))
                ln["shots"] += u["shots"]
                ln["units"] += 1
                ln["seconds_video"] = round(ln["seconds_video"] + u["seconds"], 2)
                if p["unknown"]:
                    unknown += u["shots"]
                    continue
                ln["seconds_billed"] = round(ln["seconds_billed"] + (p["seconds_billed"] or 0), 2)
                ln["native_units"] = (ln["native_units"] or 0) + (p["native_units"] or 0)
                ln["cny"] = round(ln["cny"] + (p["cny"] or 0), 2)
            else:
                free[kind] = free.get(kind, 0) + len(u["shots"])
    else:
        for r in routes:
            free[r["kind"]] = free.get(r["kind"], 0) + 1
    lines = sorted(lines.values(), key=lambda ln: (-ln["cny"], ln["provider"]))
    for ln in lines:
        ln["shots"] = sorted(ln["shots"])
        ln["cny"] = round(ln["cny"], 1)
    sub = round(sum(ln["cny"] for ln in lines if not ln["manual"]), 1)
    pct = retry_pct(series_doc) if sub else 0.0
    retry = round(sub * pct, 1)
    ver = load_rates().get("version")
    eid = ep["id"]
    code = confirm_code(lines, ver, eid, stage) if stage == "finals" else None
    now = time.time()
    return dict(id=f"est-{hashlib.sha1(f'{code}{now}'.encode()).hexdigest()[:10]}", stage=stage, episode=eid,
                lines=lines, free=free, subtotal_cny=sub, retry_pct=pct, retry_cny=retry,
                max_cny=round(sub + retry, 1), unknown=sorted(set(unknown)), confirm_code=code,
                rates_version=ver, created=now, expires_at=now + CONFIRM_TTL_S,
                hard_first=[r["no"] for r in sorted(routes, key=lambda r: r.get("hard_rank", 99)) if r.get("hard")
                            and r["kind"] in ("cloud", "mcp")][:3],
                n_paid=sum(len(ln["shots"]) for ln in lines if not ln["manual"]),
                n_manual=sum(len(ln["shots"]) for ln in lines if ln["manual"]),
                shots={no: dict(kind=r["kind"], source=r["source"]) for no, r in by_no.items()})


def context(est, series_doc, sid):
    """Budget / cap numbers the sheet shows: series spent + left after, month used + cap."""
    m = month()
    b = series_budget(series_doc)
    sp = spent(sid)
    return dict(budget=dict(budget=b, spent=sp, left_after=None if b is None else round(b - sp - est["max_cny"], 1)),
                month=dict(cap=m.get("cap_cny"), used=round(float(m.get("used_cny") or 0), 2),
                           left_after=None if m.get("cap_cny") is None else
                           round(m["cap_cny"] - float(m.get("used_cny") or 0) - est["max_cny"], 1)))


def check(est, series_doc, sid, allow_unknown=False, balances=None, ready=None):
    """Every refusal reason (empty = ok). ``balances`` {provider: credits}; ``ready`` {provider: bool}."""
    codes = []
    ctx = context(est, series_doc, sid)
    b = ctx["budget"]
    if b["budget"] is not None and b["spent"] + est["max_cny"] > b["budget"] + 1e-6:
        codes.append(msg("over-budget", spent=b["spent"], budget=b["budget"], need=est["max_cny"]))
    m = ctx["month"]
    if m["cap"] is not None and m["used"] + est["max_cny"] > m["cap"] + 1e-6:
        codes.append(msg("over-cap", used=m["used"], cap=m["cap"], need=est["max_cny"]))
    if est.get("unknown") and not allow_unknown:
        codes.append(msg("unknown-rate", shots=est["unknown"]))
    for ln in est["lines"]:
        if ln["manual"]:
            continue
        if ready is not None and not ready.get(ln["provider"], False):
            codes.append(msg("provider-not-ready", provider=ln["provider"]))
        bal = (balances or {}).get(ln["provider"])
        if bal is not None and ln.get("native_units") and bal < ln["native_units"]:
            codes.append(msg("low-credits", provider=ln["provider"], balance=bal, need=ln["native_units"]))
    return dict(ok=not codes, codes=codes, **ctx)


def verify(ep, estimate_id, code, max_cny, fresh):
    """The stored estimate if (1) it exists, (2) the code matches and was never used for a run (one OK = one
    submission), (3) not expired, (4) the plan did not change
    since (``fresh`` = a new build of the same stage has the same code), (5) ``max_cny`` covers it."""
    if not estimate_id or not code:
        raise CreateError("confirm-required", status=409)
    est = (ep.get("estimates") or {}).get(estimate_id)
    if not est:
        raise CreateError("confirm-required", status=409, estimate=estimate_id)
    if est.get("confirm_code") != code:
        raise CreateError("confirm-mismatch", status=409)
    if est.get("used"):
        raise CreateError("confirm-used", status=409)
    if time.time() > float(est.get("expires_at") or 0):
        raise CreateError("confirm-expired", status=409)
    if fresh["confirm_code"] != code:
        raise CreateError("plan-changed", status=409)
    if max_cny is None or float(max_cny) + 1e-6 < float(est["max_cny"]):
        raise CreateError("max-too-low", status=409, max_cny=max_cny, need=est["max_cny"])
    return est
