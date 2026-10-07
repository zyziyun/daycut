"""ComfyUI on this Mac or a faster PC on the local network (an NVIDIA card: about 1-2 min per draft shot).
Behind the second flag; the URL is typed by the user and must be http(s) to localhost or a private range.
Phase 2: POST /prompt + /history + /view. The MVP detects (GET /system_stats) and refuses to submit."""
import ipaddress
import json
import os
import urllib.parse
import urllib.request

from ..i18n import CreateError
from .base import Provider
from .local_rapidmlx import enabled


def private_url(url):
    try:
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        if u.hostname in ("localhost",):
            return True
        ip = ipaddress.ip_address(u.hostname)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def detect(url, timeout=0.6):
    if not private_url(url):
        return None
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/system_stats", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


class ComfyUI(Provider):
    info = dict(id="local-comfyui", label={"en": "A faster PC on your network", "zh": "局域网里更快的电脑",
                                           "fr": "Un PC plus rapide sur le réseau"},
                kind="local", needs=["local:comfyui"], tos="runs on your own machine",
                models=["wan2.2-ti2v-5b"], license="Wan 2.2: Apache-2.0", concurrency=1)

    def status(self):
        if not enabled():
            return dict(ready=False, code="create.local-off", params={})
        url = os.environ.get("VSTUDIO_COMFYUI_URL") or ""
        if not url:
            return dict(ready=False, code="create.provider.local-not-set", params={})
        if detect(url) is None:
            return dict(ready=False, code="create.provider.local-not-running", params=dict(url=url))
        return dict(ready=True, code="create.provider.ready", params={})

    def submit(self, job):
        raise CreateError("local-off", phase=2)
