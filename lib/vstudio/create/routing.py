"""Per-shot routing: policy + overrides -> one route per shot (SPEC §1.3), cheapest-first, character lock.

Source strings:  cloud:<provider>[/<model>]  manual:<site>  local:<runtime>|local:auto  record  card
                 reuse:<eid>/<shot>  plugin:<render provider>  agent:<runner>  (+ policy-only: cheapest, placeholder)
plugin: / agent: shots are made by ``make`` (vstudio.plugins.lanes) in parallel lanes, not by the finals run.
Policy (series spec.create.routing, defaults from the format): faces, no_faces, drafts, stills,
one_model_per_character.
"""
import re

from . import costs
from .i18n import CreateError, msg

SOURCE_RE = re.compile(r"^(cloud|manual|local):[a-z0-9-]+(/[\w.\-]+)?$|^(record|card|cheapest|placeholder)$"
                       r"|^reuse:[a-z0-9][a-z0-9-]{0,47}/\d{2,3}$|^(plugin|agent):[a-z][a-z0-9-]{1,40}$")
MADE_BY_PLUGINS = ("plugin", "agent")
DEFAULT_MODEL = {"kling-mcp": "kling-video-v3_0_omni", "minimax": "MiniMax-Hailuo-02", "veo": "veo-3.1-fast",
                 "seedance-ark": "seedance-2", "jimeng": "seedance-2"}
MANUAL_SITES = {"jimeng": "jimeng", "seedance": "jimeng", "即梦": "jimeng"}
HARD_WORDS = re.compile(r"fall|falls|falling|hang|hangs|hanging|dangl|collaps|grab|holds?\b|in (his|her) hand|"
                        r"prop|drone|aerial|low angle|extreme|splash|dive|jump|crowd|坠|掉|悬|塌|抓|手持|手里|俯拍|"
                        r"仰拍|航拍|跳|摔|人群", re.I)
POLICY_KEYS = ("faces", "no_faces", "drafts", "stills", "one_model_per_character")


def check_source(src):
    if not isinstance(src, str) or not SOURCE_RE.match(src):
        raise CreateError("bad-input", field="source", value=str(src)[:80])
    return src


def parse(src):
    """-> {source, kind cloud|mcp|manual|local|record|card|reuse|placeholder, provider, model}"""
    check_source(src)
    if src in ("record", "card", "placeholder"):
        return dict(source=src, kind=src, provider=None, model=None)
    if src.startswith("reuse:"):
        eid, no = src[6:].split("/")
        return dict(source=src, kind="reuse", provider=None, model=None, ref=dict(episode=eid, shot=no))
    if src.startswith(("plugin:", "agent:")):
        kind, pid = src.split(":", 1)
        return dict(source=src, kind=kind, provider=pid, model=None)
    kind, rest = src.split(":", 1)
    prov, _, model = rest.partition("/")
    if kind == "manual":
        prov = MANUAL_SITES.get(prov, prov)
        model = model or DEFAULT_MODEL.get(prov, "")
        return dict(source=f"manual:{prov}" + (f"/{model}" if model else ""), kind="manual", provider=prov,
                    model=model)
    if kind == "local":
        return dict(source=src, kind="local", provider=f"local-{prov}" if prov != "auto" else "local-auto",
                    model=model or None)
    model = model or DEFAULT_MODEL.get(prov, "")
    return dict(source=f"cloud:{prov}/{model}", kind="mcp" if prov == "kling-mcp" else "cloud", provider=prov,
                model=model)


def policy(series_doc, fmt):
    pol = dict(faces="cloud:kling-mcp/kling-video-v3_0_omni", no_faces="cheapest", drafts="local:auto",
               stills="local:auto", one_model_per_character=True)
    pol.update({k: v for k, v in (fmt.get("sources") or {}).items() if k in POLICY_KEYS})
    from . import store
    pol.update({k: v for k, v in (store.create_meta(series_doc).get("routing") or {}).items() if k in POLICY_KEYS})
    return pol


def hard_score(shot):
    s = 0
    if len(shot.get("faces") or []) >= 2:
        s += 2
    s += len(HARD_WORDS.findall(" ".join([str(shot.get("action") or ""), str(shot.get("camera") or "")])))
    if shot.get("hard"):
        s += 3
    return s


def cheapest(seconds, connected, kinds=("cloud", "mcp")):
    """The cheapest known-rate cloud model among ``connected`` providers (all known ones when none is
    connected) -> (source, price) or (None, None)."""
    pool = []
    rates = costs.load_rates().get("providers") or {}
    for prov, models in rates.items():
        if connected and prov not in connected:
            continue
        for model, e in models.items():
            if e.get("manual") or e.get("unit") == "image":
                continue
            p = costs.price_job(prov, model, seconds)
            if not p["unknown"]:
                pool.append((p["cny"], prov, model))
    if not pool:
        return None, None
    pool.sort()
    cny, prov, model = pool[0]
    return f"cloud:{prov}/{model}", cny


def resolve(ep, series_doc, fmt, connected=None):
    """-> (routes, warnings). routes: [{no, source, kind, provider, model, why, hard, hard_rank, cny}]"""
    pol = policy(series_doc, fmt)
    connected = list(connected or [])
    routes = []
    for shot in ep.get("shots") or []:
        no = shot["no"]
        if shot.get("source"):
            src, why = shot["source"], "create.route.override"
        elif shot.get("card"):
            src, why = "card", "create.route.card"
        elif shot.get("faces"):
            src, why = pol["faces"], "create.route.faces"
        else:
            src, why = pol["no_faces"], "create.route.no-faces"
        if src == "cheapest":
            src, _ = cheapest(shot.get("dur") or 2, connected)
            if src is None:
                src, why = "placeholder", "create.route.no-service"
        r = parse(src)
        price = None
        if r["kind"] in ("cloud", "mcp", "manual"):
            price = costs.price_job(r["provider"], r["model"], shot.get("dur") or 2)
        elif r["kind"] in MADE_BY_PLUGINS:
            price = dict(label=plugin_label(r), cny=0, native_units=None)
        routes.append(dict(r, no=no, why=why, hard=False, hard_score=hard_score(shot),
                           cny=None if price is None else price["cny"],
                           credits=None if price is None else price["native_units"],
                           connected=r["provider"] in connected if r["kind"] in ("cloud", "mcp") else True,
                           label=(price or {}).get("label")))
    ranked = sorted([r for r in routes if r["hard_score"] > 0], key=lambda r: (-r["hard_score"], r["no"]))
    for i, r in enumerate(ranked):
        r["hard"], r["hard_rank"] = True, i
    return routes, validate_routes(ep, routes, pol)


def validate_routes(ep, routes, pol):
    """Character lock: every shot with cast member X uses one provider/model (faces drift otherwise)."""
    warns = []
    if not pol.get("one_model_per_character", True):
        return warns
    by_no = {r["no"]: r for r in routes}
    cast = sorted({c for s in ep.get("shots") or [] for c in (s.get("faces") or [])})
    for c in cast:
        used = {}
        for s in ep.get("shots") or []:
            r = by_no.get(s["no"])
            if c in (s.get("faces") or []) and r and r["kind"] in ("cloud", "mcp", "manual"):
                used.setdefault(f"{r['provider']}/{r['model']}", []).append(s["no"])
        if len(used) > 1:
            main = max(used.items(), key=lambda kv: len(kv[1]))[0]
            odd = sorted(no for k, nos in used.items() if k != main for no in nos)
            warns.append(msg("route.character-split", cast=c, shots=odd, keep=main))
    return warns


def units(ep, routes, pad=0.5):
    """Shots that share ``unit:`` and the same source become one generation (ai-video compile_units semantics:
    order kept, durations summed + pad). -> [{id, kind, provider, model, source, shots[], seconds, hard}]"""
    from .providers.aivideo import plan_module
    PL = plan_module()
    by_no = {r["no"]: r for r in routes}
    groups, order = {}, []
    for s in ep.get("shots") or []:
        r = by_no[s["no"]]
        key = (r["source"], str(s.get("unit") or s["no"]))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)
    out = []
    for key in order:
        shots = groups[key]
        r = by_no[shots[0]["no"]]
        cfg = dict(model="", characters={}, unit_pad=pad if len(shots) > 1 else 0.0,
                   shots=[dict(id=s["no"], unit=key[1], dur=float(s.get("dur") or 2), chars=s.get("faces") or [],
                               scene=s.get("scene", "")) for s in shots])
        u = PL.compile_units(cfg)[0]
        out.append(dict(id=f"u{shots[0]['no']}", kind=r["kind"], provider=r["provider"], model=r["model"],
                        source=r["source"], shots=[s["no"] for s in shots], seconds=float(u.dur),
                        hard=any(by_no[s["no"]]["hard"] for s in shots),
                        hard_rank=min((by_no[s["no"]].get("hard_rank", 99) for s in shots), default=99)))
    return out


OPTION_SOURCES = ("cloud:kling-mcp/kling-video-v3_0_omni", "cloud:veo/veo-3.1-fast", "cloud:minimax/MiniMax-Hailuo-02",
                  "manual:jimeng/seedance-2", "local:rapidmlx/ltx-2-distilled", "record", "card")


def options(shot, connected=None, local=False):
    """The popover rows for one shot: [{source, kind, label, cny, credits, note code, connected}]."""
    out = []
    for src in OPTION_SOURCES:
        r = parse(src)
        if r["kind"] == "local" and not local:
            continue
        price = costs.price_job(r["provider"], r["model"], shot.get("dur") or 2) if r["kind"] in (
            "cloud", "mcp", "manual") else None
        note = {"kling-mcp": "create.option.kling", "veo": "create.option.veo", "minimax": "create.option.hailuo",
                "jimeng": "create.option.jimeng"}.get(r["provider"] or "", f"create.option.{r['kind']}")
        if r["kind"] == "local":
            note = "create.option.local"
        out.append(dict(source=r["source"], kind=r["kind"], provider=r["provider"], model=r["model"],
                        label=(price or {}).get("label"), cny=(price or {}).get("cny"),
                        credits=(price or {}).get("native_units"), note=note,
                        connected=(r["provider"] in (connected or [])) if r["kind"] in ("cloud", "mcp") else True))
    return out + plugin_options(shot)


def plugin_label(r):
    try:
        from vstudio.plugins import registry as R
        return R.display_name(R.find(r["provider"], "agent-runner" if r["kind"] == "agent" else "shot-provider"))
    except Exception:  # noqa: BLE001
        return r["provider"]


def plugin_options(shot):
    """Enabled agent runners (any shot) and render providers (the shots whose ``ref`` they can read) as options."""
    out = []
    try:
        from vstudio.plugins import registry as R
        for row in R.rows("agent-runner", enabled_only=True):
            st = R.instance(row["key"]).status()
            out.append(dict(source=f"agent:{row['id']}", kind="agent", provider=row["id"], model=None,
                            label=R.display_name(row), cny=0 if row["cost"]["kind"] != "paid" else None, credits=None,
                            note="create.option.agent", connected=bool(st.get("ready")), cost=row["cost"]["kind"]))
        ref = (shot.get("ref") or {}).get("kind")
        for row in R.rows("shot-provider", enabled_only=True):
            cls = R.instance(row["key"])
            if (getattr(cls, "info", {}) or {}).get("kind") == "render" and ref == row["id"]:
                out.append(dict(source=f"plugin:{row['id']}", kind="plugin", provider=row["id"], model=None,
                                label=R.display_name(row), cny=0, credits=None, note="create.option.plugin",
                                connected=True, cost=row["cost"]["kind"]))
    except Exception:  # noqa: BLE001  (a broken plugin never breaks the storyboard)
        pass
    return out


# --------------------------------------------------------------------------- NL route instructions (rules)
PROVIDER_WORDS = [
    (r"kling|可灵", "cloud:kling-mcp/kling-video-v3_0_omni"), (r"hailuo|海螺|minimax", "cloud:minimax/MiniMax-Hailuo-02"),
    (r"\bveo\b|google", "cloud:veo/veo-3.1-fast"), (r"即梦|jimeng|seedance", "manual:jimeng/seedance-2"),
    (r"record|录|自己拍|myself", "record"), (r"text card|字卡|card", "card"),
]


def rule_instruction(ep, routes, text, connected=None):
    """'make every shot without faces cheaper' / '07 用海螺' / 'all faces on Kling' -> [{no, from, to}]."""
    t = str(text or "").lower()
    nos = set(re.findall(r"(?<!\d)(\d{2})(?!\d)", t))
    by_no = {r["no"]: r for r in routes}
    shots = ep.get("shots") or []
    if nos:
        scope = [s for s in shots if s["no"] in nos]
    elif re.search(r"without faces|no.faces|no face|sans visage|无脸|没有脸|没脸|不露脸|空镜", t):
        scope = [s for s in shots if not s.get("faces") and not s.get("card")]
    elif re.search(r"with faces|faces|visages?|有脸|露脸|人脸", t):
        scope = [s for s in shots if s.get("faces")]
    elif re.search(r"\ball\b|every|tous|toutes|全部|所有|都", t):
        scope = [s for s in shots if not s.get("card")]
    else:
        scope = []
    target = next((src for pat, src in PROVIDER_WORDS if re.search(pat, t)), None)
    cheaper = re.search(r"cheap|moins cher|便宜|省钱|less money|lower cost", t)
    changes = []
    for s in scope:
        cur = by_no[s["no"]]["source"]
        to = target
        if to is None and cheaper:
            to, _ = cheapest(s.get("dur") or 2, connected)
        if to and to != cur:
            changes.append(dict(no=s["no"], **{"from": cur, "to": to}))
    return changes
