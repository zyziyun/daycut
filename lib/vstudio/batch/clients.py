"""Client workspaces: one folder per client with a ``client.yaml`` layered over the global persona.

    python -m vstudio.batch client init   --client acme --set '{"name": "Acme", "platforms": ["douyin"]}'
    python -m vstudio.batch client show   --client acme            # {config, effective, dir, batches}
    python -m vstudio.batch client update --client acme --set '{"glossary_add": [{"wrong": "rag", "right": "RAG"}]}'

``--client`` is a folder (absolute / relative path, as the desk sends it) or a slug resolved under the clients
root (``$VSTUDIO_CLIENTS``, else ``$VSTUDIO_HOME/clients``, else ``~/.config/vstudio/clients``).

client.yaml keys (all optional except ``name``):
  name, style (free text: tone for planners / copy), platforms ["xiaohongshu:full", "douyin"], tags [..] (the
  client's tag set), glossary [{wrong, right, source?, batch?, job?}] (ASR term fixes; accepted caption fixes
  append here), fillers {extra: [..], keep: [..]} (extra 口头禅 to cut / words never cut), brand {accent,
  highlight, ink, ground} (#RRGGBB), cover_style frame | collage | face | text, cleanup_profile gentle |
  standard | tight, confirm_policy true | false (answer low-risk cleanup questions automatically), language,
  asr_prompt, delivery {cleanup_days (30), per_day, times}, notes, crm {history: [{stage, at}], revenue:
  [{at, amount}]} (optional funnel data for ``metrics --csv``).

``effective(cfg)``: persona-derived defaults <- client.yaml. A batch whose spec names a client
(``client: acme`` / ``plan --client``) gets, at plan time: default platforms / cleanup profile / confirm policy /
asr prompt (spec values win), the glossary appended to ``subtitles.term_fixes`` (so it is part of the stage keys:
the batch never changes under a running review), and ``client.persona.yaml`` in the batch folder - the persona
with the client's brand, fillers, tags, term fixes on top - which every ``run`` activates
(``VSTUDIO_PERSONA``) for in-process stages and workflow subprocesses alike.
"""
import json
import os
import re
import time

from .util import read_json, write_json

CLEANUP_PROFILES = ("gentle", "standard", "tight", "strict", "off")
COVER_STYLES = ("frame", "collage", "face", "text")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
PLAT = re.compile(r"^[a-z][a-z-]{1,30}(:[a-z]{3,12})?$")
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
KNOWN = {"name", "slug", "style", "platforms", "tags", "glossary", "fillers", "brand", "cover_style", "cleanup_profile",
         "confirm_policy", "language", "asr_prompt", "delivery", "notes", "crm", "created"}
DEFAULT_CLEANUP_DAYS = 30


class ClientError(ValueError):
    pass


# --------------------------------------------------------------------------- paths
def home():
    return os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"))


def clients_root():
    return os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_CLIENTS") or os.path.join(home(), "clients")))


def resolve(ref, base=None):
    """client ref (folder path, client.yaml path or slug) -> absolute client folder."""
    if not ref:
        raise ClientError("no client given")
    ref = os.path.expanduser(str(ref))
    if ref.endswith((".yaml", ".yml")):
        return os.path.dirname(os.path.abspath(ref if os.path.isabs(ref) or not base else os.path.join(base, ref)))
    if os.path.isabs(ref) or os.sep in ref or ref.startswith("."):
        return os.path.abspath(ref if os.path.isabs(ref) or not base else os.path.join(base, ref))
    if base and os.path.isdir(os.path.join(base, ref)) and os.path.exists(os.path.join(base, ref, "client.yaml")):
        return os.path.join(base, ref)
    if not SLUG.match(ref):
        raise ClientError(f"client {ref!r}: a folder path or a slug (letters, digits, _ . -)")
    return os.path.join(clients_root(), ref)


def yaml_path(cdir):
    return os.path.join(cdir, "client.yaml")


# --------------------------------------------------------------------------- yaml io
def _load_yaml(path):
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    try:
        import yaml
        return yaml.safe_load(txt) or {}
    except ImportError:
        return json.loads(txt)


def _dump_yaml(obj):
    try:
        import yaml
        return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except ImportError:
        return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def load(cdir):
    p = yaml_path(cdir)
    if not os.path.exists(p):
        raise ClientError(f"no client.yaml in {cdir} (client init first)")
    cfg = _load_yaml(p)
    if not isinstance(cfg, dict):
        raise ClientError(f"{p}: not a mapping")
    return cfg


def save(cdir, cfg):
    os.makedirs(cdir, exist_ok=True)
    p = yaml_path(cdir)
    tmp = f"{p}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# client.yaml - this client's settings, layered over the global persona (vstudio.batch clients)\n")
        f.write(_dump_yaml(cfg))
    os.replace(tmp, p)
    return p


# --------------------------------------------------------------------------- validation
def _strs(v, name, n=200, ln=60):
    if isinstance(v, str):
        v = [x.strip() for x in re.split(r"[,|]", v) if x.strip()]
    if not (isinstance(v, list) and len(v) <= n and all(isinstance(x, str) and 0 < len(x.strip()) <= ln for x in v)):
        raise ClientError(f"{name}: a list of up to {n} strings (max {ln} chars)")
    return [x.strip() for x in v]


def _gloss(v, name):
    if not isinstance(v, list) or len(v) > 2000:
        raise ClientError(f"{name}: a list of {{wrong, right}} (max 2000)")
    out = []
    for x in v:
        if isinstance(x, (list, tuple)) and len(x) == 2:
            x = dict(wrong=x[0], right=x[1])
        if not (isinstance(x, dict) and isinstance(x.get("wrong"), str) and isinstance(x.get("right"), str)
                and 0 < len(x["wrong"]) <= 60 and 0 < len(x["right"]) <= 60):
            raise ClientError(f"{name}: entries are {{wrong, right}} strings (1-60 chars)")
        row = dict(wrong=x["wrong"], right=x["right"])
        for k in ("source", "batch", "job", "at"):
            if isinstance(x.get(k), (str, int, float)) and len(str(x[k])) <= 200:
                row[k] = x[k]
        out.append(row)
    return out


def validate(patch, partial=True):
    """client.yaml fields -> checked copy. ``partial``: an update (``glossary_add`` / ``glossary_remove`` /
    ``tags_add`` allowed). Unknown keys are kept (forward compatible) but listed in ``_unknown``."""
    if not isinstance(patch, dict):
        raise ClientError("client settings must be a mapping")
    out, unknown = {}, []
    for k, v in patch.items():
        if k in ("glossary_add", "glossary_remove", "tags_add") and partial:
            out[k] = _gloss(v, k) if k != "tags_add" else _strs(v, k)
            continue
        if k not in KNOWN:
            unknown.append(k)
            out[k] = v
            continue
        if k == "name":
            if not (isinstance(v, str) and 0 < len(v.strip()) <= 80):
                raise ClientError("name: 1-80 chars")
            out[k] = v.strip()
        elif k in ("style", "notes", "asr_prompt", "language", "slug"):
            if not isinstance(v, str) or len(v) > 4000:
                raise ClientError(f"{k}: text (max 4000 chars)")
            out[k] = v
        elif k == "platforms":
            v = _strs(v, k, 12, 40)
            if not all(PLAT.match(p) for p in v):
                raise ClientError("platforms: like xiaohongshu:full, douyin, youtube-shorts")
            out[k] = v
        elif k == "tags":
            out[k] = [t.lstrip("#") for t in _strs(v, k, 100, 40)]
        elif k == "glossary":
            out[k] = _gloss(v, k)
        elif k == "fillers":
            if not (isinstance(v, dict) and set(v) <= {"extra", "keep"}):
                raise ClientError("fillers: {extra: [..], keep: [..]}")
            out[k] = dict(extra=_strs(v.get("extra") or [], "fillers.extra", 200, 16),
                          keep=_strs(v.get("keep") or [], "fillers.keep", 200, 16))
        elif k == "brand":
            if not (isinstance(v, dict) and all(isinstance(x, str) and HEX.match(x) for x in v.values())):
                raise ClientError("brand: {accent, highlight, ink, ground} as #RRGGBB")
            out[k] = dict(v)
        elif k == "cover_style":
            if v not in COVER_STYLES:
                raise ClientError(f"cover_style: {' | '.join(COVER_STYLES)}")
            out[k] = v
        elif k == "cleanup_profile":
            if v not in CLEANUP_PROFILES:
                raise ClientError(f"cleanup_profile: {' | '.join(CLEANUP_PROFILES)}")
            out[k] = v
        elif k == "confirm_policy":
            if not isinstance(v, bool):
                raise ClientError("confirm_policy: true | false")
            out[k] = v
        elif k == "delivery":
            if not isinstance(v, dict):
                raise ClientError("delivery: {cleanup_days, per_day, times}")
            d = dict(v)
            if d.get("cleanup_days") is not None and (not isinstance(d["cleanup_days"], int) or d["cleanup_days"] < 0):
                raise ClientError("delivery.cleanup_days: a whole number of days (0 = never)")
            out[k] = d
        else:
            out[k] = v
    if unknown:
        out["_unknown"] = unknown
    return out


# --------------------------------------------------------------------------- effective config
def persona_defaults():
    """The client fields as the global persona sets them (what a client without overrides gets)."""
    try:
        from vstudio.config import persona
        p = persona() or {}
    except Exception:  # noqa: BLE001
        p = {}
    pf = p.get("platforms") or {}
    cl = p.get("cleanup") or {}
    tf = (p.get("subtitles") or {}).get("term_fixes") or {}
    gl = [dict(wrong=str(k), right=str(v), source="persona") for k, v in tf.items()] if isinstance(tf, dict) else []
    br = {k: v for k, v in (p.get("brand") or {}).items() if isinstance(v, str) and HEX.match(v)}
    return dict(name="", style=(p.get("voice") or {}).get("persona") or "",
                platforms=[f"{pf.get('default') or 'xiaohongshu'}:full"],
                tags=list((p.get("publish") or {}).get("tags") or []), glossary=gl,
                fillers=dict(extra=list(cl.get("fillers_extra") or []), keep=list(cl.get("never_cut") or [])),
                brand=br, cover_style="frame", cleanup_profile=cl.get("profile") or "standard",
                confirm_policy=bool(cl.get("policy", True)), language=(p.get("creator") or {}).get("language") or "zh",
                asr_prompt="", delivery=dict(cleanup_days=DEFAULT_CLEANUP_DAYS), notes="")


def merge_glossary(base, extra):
    """Glossary lists merged by ``wrong`` (later wins)."""
    out, idx = [], {}
    for g in list(base or []) + list(extra or []):
        k = g["wrong"]
        if k in idx:
            out[idx[k]] = g
        else:
            idx[k] = len(out)
            out.append(g)
    return out


def effective(cfg):
    base = persona_defaults()
    eff = dict(base)
    for k, v in (cfg or {}).items():
        if k.startswith("_"):
            continue
        if k == "glossary":
            eff[k] = merge_glossary(base["glossary"], v)
        elif k in ("brand", "delivery", "fillers") and isinstance(v, dict):
            eff[k] = dict(base.get(k) or {}, **v)
        else:
            eff[k] = v
    return eff


def persona_overlay(eff):
    """A persona-shaped dict with the client's settings (merged over the global persona by ``activate``)."""
    plats = eff.get("platforms") or []
    ov = dict(
        subtitles=dict(term_fixes={g["wrong"]: g["right"] for g in eff.get("glossary") or []}),
        cleanup=dict(profile=eff.get("cleanup_profile") if eff.get("cleanup_profile") in
                     ("gentle", "standard", "tight") else "standard",
                     fillers_extra=list((eff.get("fillers") or {}).get("extra") or []),
                     never_cut=list((eff.get("fillers") or {}).get("keep") or []),
                     policy=bool(eff.get("confirm_policy", True))),
        publish=dict(tags=list(eff.get("tags") or [])),
        creator=dict(language=eff.get("language") or "zh"),
        client=dict(name=eff.get("name") or "", cover_style=eff.get("cover_style") or "frame",
                    style=eff.get("style") or ""))
    if eff.get("brand"):
        ov["brand"] = dict(eff["brand"])
    if plats:
        ov["platforms"] = dict(default=plats[0].split(":")[0])
    return ov


# --------------------------------------------------------------------------- operations
def view(cdir):
    cfg = load(cdir)
    return dict(ok=True, dir=cdir, path=yaml_path(cdir), slug=os.path.basename(cdir), config=cfg,
                effective=effective(cfg), batches=batches(cdir))


def init(cdir, fields=None, exist_ok=False):
    if os.path.exists(yaml_path(cdir)):
        if not exist_ok:
            raise ClientError(f"client exists: {yaml_path(cdir)} (use client update)")
        return update(cdir, fields or {})
    f = validate(dict(fields or {}), partial=False)
    f.pop("_unknown", None)
    for k in ("glossary_add", "tags_add", "glossary_remove"):
        f.pop(k, None)
    f.setdefault("name", os.path.basename(cdir))
    f["created"] = time.strftime("%Y-%m-%d")
    save(cdir, f)
    return view(cdir)


def update(cdir, patch):
    cfg = load(cdir)
    p = validate(dict(patch or {}), partial=True)
    unknown = p.pop("_unknown", None)
    add, rem, tags_add = p.pop("glossary_add", None), p.pop("glossary_remove", None), p.pop("tags_add", None)
    cfg.update(p)
    if add:
        cfg["glossary"] = merge_glossary(cfg.get("glossary") or [], add)
    if rem:
        drop = {(g["wrong"], g["right"]) for g in rem}
        cfg["glossary"] = [g for g in cfg.get("glossary") or [] if (g["wrong"], g["right"]) not in drop]
    if tags_add:
        cfg["tags"] = list(dict.fromkeys(list(cfg.get("tags") or []) + tags_add))
    save(cdir, cfg)
    v = view(cdir)
    if unknown:
        v["warnings"] = [f"unknown client key(s) kept: {', '.join(unknown)}"]
    return v


def add_glossary(cdir, entries):
    """Append accepted caption fixes ({wrong, right, ...}) to the client glossary; -> the entries added."""
    if not entries or not os.path.exists(yaml_path(cdir)):
        return []
    cfg = load(cdir)
    have = {(g.get("wrong"), g.get("right")) for g in cfg.get("glossary") or []}
    new = [e for e in _gloss(entries, "glossary_add") if (e["wrong"], e["right"]) not in have]
    if new:
        cfg["glossary"] = merge_glossary(cfg.get("glossary") or [], new)
        save(cdir, cfg)
    return new


def list_clients(root=None):
    root = root or clients_root()
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.exists(yaml_path(d)):
                try:
                    cfg = load(d)
                except (ClientError, ValueError):
                    continue
                out.append(dict(slug=name, dir=d, name=cfg.get("name") or name, platforms=cfg.get("platforms") or [],
                                glossary=len(cfg.get("glossary") or []), batches=len(batches(d))))
    return out


# --------------------------------------------------------------------------- batch registry
def _reg_path(cdir=None):
    return os.path.join(cdir, "batches.json") if cdir else os.path.join(home(), "batches.json")


def register_batch(batch_dir, name=None, cdir=None):
    """Remember a batch folder for the client (and in the global list ``metrics --all`` reads)."""
    batch_dir = os.path.abspath(batch_dir)
    for path in ([_reg_path(cdir)] if cdir else []) + [_reg_path()]:
        try:
            reg = [r for r in read_json(path, []) or [] if os.path.isdir(r.get("dir") or "")]   # prune deleted ones
            if not any(r.get("dir") == batch_dir for r in reg):
                reg.append(dict(dir=batch_dir, name=name, client=cdir, at=time.time()))
            else:
                for r in reg:
                    if r.get("dir") == batch_dir:
                        r.update(name=name or r.get("name"), client=cdir or r.get("client"))
            write_json(path, reg)
        except OSError:
            pass


def batches(cdir=None):
    """Registered batch folders that still exist: [{dir, name, client, at}]."""
    reg = read_json(_reg_path(cdir), []) or []
    return [r for r in reg if os.path.exists(os.path.join(r.get("dir") or "", "batch.db"))]


# --------------------------------------------------------------------------- spec integration
def apply_to_spec(spec, client_ref):
    """Plan time: resolve the client, snapshot its effective config into ``spec['_client']`` and fill spec
    defaults the spec itself leaves open. Returns the client folder."""
    cdir = resolve(client_ref, spec.get("_dir"))
    cfg = load(cdir)
    eff = effective(cfg)
    spec["client"] = cdir
    spec["_client"] = dict(dir=cdir, slug=os.path.basename(cdir), name=eff.get("name") or os.path.basename(cdir),
                           effective=eff)
    ud = spec.get("_user_defaults") or {}
    d = spec.setdefault("defaults", {})
    if "platforms" not in ud and eff.get("platforms"):
        d["platforms"] = list(eff["platforms"])
    if "cleanup_profile" not in ud and eff.get("cleanup_profile") in ("gentle", "standard", "tight", "off"):
        d["cleanup_profile"] = eff["cleanup_profile"]
    if "cleanup_policy" not in ud and eff.get("confirm_policy") is False:
        d["cleanup_policy"] = False
    asr = spec.setdefault("asr", {})
    if not asr.get("prompt") and eff.get("asr_prompt"):
        asr["prompt"] = eff["asr_prompt"]
    if not asr.get("language") and eff.get("language"):
        asr["language"] = eff["language"]
    gl = [g for g in eff.get("glossary") or [] if g.get("source") != "persona"]
    if gl:
        sub = spec.setdefault("subtitles", {})
        tf = list(sub.get("term_fixes") or [])
        have = {tuple(x)[0] if isinstance(x, (list, tuple)) else None for x in tf}
        for g in gl:
            pat = re.escape(g["wrong"])
            if pat not in have:
                tf.append([pat, g["right"]])
        sub["term_fixes"] = tf
    if not spec.get("schedule") and (eff.get("delivery") or {}).get("per_day"):
        dl = eff["delivery"]
        spec["schedule"] = {k: dl[k] for k in ("per_day", "times") if dl.get(k)}
    return cdir


def write_persona(batch_dir, spec):
    """``<batch>/client.persona.yaml``: the global persona + the client overlay (None without a client)."""
    c = spec.get("_client")
    if not c:
        return None
    from vstudio.config import _merge, persona
    merged = _merge(persona() or {}, persona_overlay(c["effective"]))
    path = os.path.join(batch_dir, "client.persona.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_dump_yaml(merged))
    return path


class activate:
    """Context manager: make ``<batch>/client.persona.yaml`` THE persona (``VSTUDIO_PERSONA``) while a run lasts."""

    def __init__(self, batch_dir):
        self.path = os.path.join(batch_dir, "client.persona.yaml")
        self.prev = None
        self.on = os.path.exists(self.path)

    def __enter__(self):
        if self.on:
            self.prev = os.environ.get("VSTUDIO_PERSONA")
            os.environ["VSTUDIO_PERSONA"] = self.path
            _clear_persona()
        return self

    def __exit__(self, *exc):
        if self.on:
            if self.prev is None:
                os.environ.pop("VSTUDIO_PERSONA", None)
            else:
                os.environ["VSTUDIO_PERSONA"] = self.prev
            _clear_persona()
        return False


def _clear_persona():
    try:
        from vstudio.config import persona
        persona.cache_clear()
    except Exception:  # noqa: BLE001
        pass


def batch_client_dir(spec):
    c = spec.get("_client") or {}
    return c.get("dir") or (spec.get("client") if isinstance(spec.get("client"), str) else None)
