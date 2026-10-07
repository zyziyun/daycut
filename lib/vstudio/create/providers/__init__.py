"""Provider registry: ids, ``get(id)``, ``list_info()``, ``detect()`` (status per provider, no paid calls).

Tests stand a fake in for every provider with ``set_fake(FakeClass)`` (tests/create_fake.py); nothing in the engine
turns that on (no environment variable, no command-line flag), so the product always talks to the real services.
"""
from ..i18n import CreateError
from .base import Provider, SubmitTimeout  # noqa: F401

# Every provider registers through the plugin registry (vstudio.plugins: built-in manifests in
# plugins/builtin/manifests, plus the user's own folder / package plugins once turned on). This order is only the
# display order of the built-ins; any other enabled shot provider follows them.
ORDER = ("kling-mcp", "minimax", "jimeng", "veo", "seedance-ark", "local-rapidmlx", "local-comfyui")


def classes():
    """{id: Provider class} of the enabled shot providers that take jobs (cloud / mcp / manual / local); ``render``
    providers (HyperFrames ...) are made by ``make`` in lanes instead."""
    from vstudio.plugins import registry as R
    out = {}
    for row in R.rows("shot-provider", enabled_only=True):
        if row["error"]:
            continue
        try:
            cls = R.instance(row["key"])
        except Exception:  # noqa: BLE001  (a broken third-party plugin never takes the built-ins down)
            continue
        if (getattr(cls, "info", None) or {}).get("kind") in ("cloud", "mcp", "manual", "local"):
            out[cls.info["id"]] = cls
    return out


def order():
    c = classes()
    return [p for p in ORDER if p in c] + sorted(p for p in c if p not in ORDER)


_fake = {"cls": None, "overrides": {}}
_instances = {}


def fake_mode():
    """A test installed a fake provider class (``set_fake``)."""
    return bool(_fake["cls"])


def set_fake(cls=None, **overrides):
    """Tests only: ``cls`` (``cls(info, **kwargs)``) stands in for every provider, None = the real ones;
    ``overrides`` = {provider_id: kwargs} (fail / timeout / balance ...)."""
    _fake["cls"] = cls
    _fake["overrides"] = overrides
    _instances.clear()


def install(pid, provider):
    """Tests: use this instance for ``pid``."""
    _instances[pid] = provider


def get(pid):
    if pid in _instances:
        return _instances[pid]
    cls = classes().get(pid)
    if cls is None:
        raise CreateError("not-found", status=404, what="service", id=pid)
    if fake_mode():
        inst = _fake["cls"](cls.info, **dict(_fake["overrides"].get(pid) or {}))
    else:
        inst = cls()
    _instances[pid] = inst
    return inst


def info(pid):
    c = classes()
    if pid not in c:
        raise CreateError("not-found", status=404, what="service", id=pid)
    return dict(c[pid].info)


def list_info():
    c = classes()
    return [dict(c[p].info) for p in order()]


def detect(include_local=False):
    """[{id, label, kind, ready, code, params, ...}] - env presence only (no network) for cloud; local probes run
    only when the second flag is on and ``include_local``."""
    out = []
    c = classes()
    for pid in order():
        meta = dict(c[pid].info)
        if meta["kind"] == "local" and not include_local:
            st = dict(ready=False, code="create.local-off", params={})
        else:
            st = get(pid).status()
        out.append(dict(meta, **st))
    return out


def connected():
    """Ids of cloud / mcp providers ready to take a paid job right now."""
    return [d["id"] for d in detect() if d["ready"] and d["kind"] in ("cloud", "mcp")]
