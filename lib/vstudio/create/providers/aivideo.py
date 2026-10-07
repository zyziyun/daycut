"""The ai-video workflow's provider adapters (workflows/ai-video/scripts/providers.py: KlingMCP, MiniMax,
SeedanceArk, Manual) behind the Create protocol - loaded with importlib, never copied."""
import importlib
import os
import socket
import sys

from .base import Provider, SubmitTimeout

def scripts_dir():
    from vstudio.project import manifests as M
    return os.path.join(M.ROOT, "workflows", "ai-video", "scripts")


def _import(name):
    d = scripts_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module(name)


def ai():
    """workflows/ai-video/scripts/providers.py (the same module generate.py / plan.py import)."""
    m = _import("providers")
    if not hasattr(m, "Job"):
        raise ImportError(f"an unrelated 'providers' module shadows the ai-video one: {m!r}")
    return m


def plan_module():
    return _import("plan")


def make_job(**kw):
    return ai().Job(**kw)


class _Wrapped(Provider):
    """Submit once; a transport error after the request left the machine = SubmitTimeout (maybe charged)."""
    impl_name = None

    def __init__(self, impl=None):
        self._impl = impl

    @property
    def impl(self):
        if self._impl is None:
            self._impl = ai().get_provider(self.impl_name)
        return self._impl

    def balance(self):
        try:
            return self.impl.balance()
        except Exception:  # noqa: BLE001  (balance is a nicety; the gate still has the estimate)
            return None

    def submit(self, job):
        m = ai()
        try:
            return self.impl.submit(job)
        except m.TransportError as e:
            raise SubmitTimeout(str(e)) from e
        except (socket.timeout, TimeoutError) as e:
            raise SubmitTimeout(str(e)) from e

    def poll(self, task_id):
        return ai().with_retries(lambda: self.impl.poll(task_id))

    def download(self, url, path):
        return self.impl.download(url, path)


class KlingMCP(_Wrapped):
    impl_name = "kling-mcp"
    info = dict(id="kling-mcp", label={"en": "Kling", "zh": "可灵", "fr": "Kling"}, kind="mcp",
                needs=["KLING_MCP_TOKEN"], tos="official MCP server; spends your Kling membership credits",
                license=None, models=["kling-video-v3_0_omni", "kling-image-v3_0_omni"], concurrency=5)


class MiniMax(_Wrapped):
    impl_name = "minimax"
    info = dict(id="minimax", label={"en": "MiniMax · Hailuo", "zh": "MiniMax · 海螺", "fr": "MiniMax · Hailuo"},
                kind="cloud", needs=["MINIMAX_API_KEY"], tos="official open-platform API, pay as you go",
                license=None, models=["MiniMax-Hailuo-02"], concurrency=4)


class SeedanceArk(_Wrapped):
    impl_name = "seedance-ark"
    info = dict(id="seedance-ark", label={"en": "Seedance (Ark API)", "zh": "Seedance（火山方舟 API）",
                                          "fr": "Seedance (API Ark)"},
                kind="cloud", needs=["ARK_API_KEY"], tos="official Volcengine Ark API", license=None,
                models=["seedance-2"], concurrency=4)


class Jimeng(Provider):
    """即梦 web: assisted only. Reelfold writes the prompt sheet; YOU press Generate on jimeng.com (its terms forbid
    automation); downloads named <unit>_*.mp4 are imported. ``submit`` always refuses."""
    info = dict(id="jimeng", label={"en": "即梦 · Seedance", "zh": "即梦 · Seedance", "fr": "即梦 · Seedance"},
                kind="manual", needs=[], tos="you press Generate on jimeng.com; Reelfold never clicks it",
                license=None, models=["seedance-2"], concurrency=1, site="https://jimeng.jianying.com/")

    def status(self):
        return dict(ready=True, code="create.provider.browser", params={})

    def sheet(self, job):
        return ai().Manual(site="即梦 jimeng.com", rate_key="seedance").sheet(job)
