"""Provider registry: ids, ``get(id)``, ``list_info()``, ``detect()`` (status per provider, no paid calls).

Fake mode (``set_fake(True)`` - the desk's mock mode and tests, or env VSTUDIO_CREATE_FAKE=1): every provider is a
FakeProvider with the real one's metadata; nothing leaves this machine.
"""
import os

from ..i18n import CreateError
from .aivideo import Jimeng, KlingMCP, MiniMax, SeedanceArk
from .base import Provider, SubmitTimeout  # noqa: F401
from .fake import FakeProvider
from .local_comfyui import ComfyUI
from .local_rapidmlx import RapidMLX
from .veo import Veo

CLASSES = {c.info["id"]: c for c in (KlingMCP, MiniMax, Veo, Jimeng, SeedanceArk, RapidMLX, ComfyUI)}
ORDER = ("kling-mcp", "minimax", "jimeng", "veo", "seedance-ark", "local-rapidmlx", "local-comfyui")

_fake = {"on": None, "overrides": {}}
_instances = {}


def fake_mode():
    return _fake["on"] if _fake["on"] is not None else os.environ.get("VSTUDIO_CREATE_FAKE") == "1"


def set_fake(on=True, **overrides):
    """Fake mode on/off; ``overrides`` = {provider_id: FakeProvider kwargs} (tests: fail / timeout / balance)."""
    _fake["on"] = on
    _fake["overrides"] = overrides
    _instances.clear()


def install(pid, provider):
    """Tests: use this instance for ``pid``."""
    _instances[pid] = provider


def get(pid):
    if pid in _instances:
        return _instances[pid]
    cls = CLASSES.get(pid)
    if cls is None:
        raise CreateError("not-found", status=404, what="service", id=pid)
    if fake_mode():
        kw = dict(_fake["overrides"].get(pid) or {})
        if pid == "kling-mcp":
            kw.setdefault("balance", 1240)
        inst = FakeProvider(cls.info, **kw)
    else:
        inst = cls()
    _instances[pid] = inst
    return inst


def info(pid):
    return dict(CLASSES[pid].info)


def list_info():
    return [dict(CLASSES[p].info) for p in ORDER]


def detect(include_local=False):
    """[{id, label, kind, ready, code, params, ...}] - env presence only (no network) for cloud; local probes run
    only when the second flag is on and ``include_local``."""
    out = []
    for pid in ORDER:
        meta = dict(CLASSES[pid].info)
        if meta["kind"] == "local" and not include_local:
            st = dict(ready=False, code="create.local-off", params={})
        else:
            st = get(pid).status()
        out.append(dict(meta, **st))
    return out


def connected():
    """Ids of cloud / mcp providers ready to take a paid job right now."""
    return [d["id"] for d in detect() if d["ready"] and d["kind"] in ("cloud", "mcp")]
