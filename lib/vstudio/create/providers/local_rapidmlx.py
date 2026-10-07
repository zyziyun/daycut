"""Local draft video on this Mac through a Rapid-MLX style OpenAI-compatible server (LTX-2 distilled).
Behind the second flag (Settings.createLocalGen -> env VSTUDIO_CREATE_LOCAL=1); nothing is probed at start-up.
Honest UX: slow (about 6 min per 5 s shot at 576p on a 32 GB Mac), drafts for timing only, never finals.
License: LTX-2 Community license - free below $10M annual revenue (the desk asks for that tick first).

Phase 2: actual generation (POST /v1/videos). The MVP only detects the server; ``submit`` refuses."""
import json
import os
import urllib.request

from ..i18n import CreateError
from .base import Provider

PORT = int(os.environ.get("VSTUDIO_RAPIDMLX_PORT", "8000"))


def enabled():
    return os.environ.get("VSTUDIO_CREATE_LOCAL") == "1"


def detect(timeout=0.4):
    """GET /v1/models on localhost -> list of model ids, or None (not running). Read-only, local only."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=timeout) as r:
            d = json.loads(r.read())
        return [m.get("id") for m in d.get("data") or [] if isinstance(m, dict)]
    except Exception:  # noqa: BLE001
        return None


class RapidMLX(Provider):
    info = dict(id="local-rapidmlx", label={"en": "This Mac · LTX-2 draft", "zh": "本机 · LTX-2 草稿",
                                            "fr": "Ce Mac · brouillon LTX-2"},
                kind="local", needs=["local:rapidmlx"], tos="runs on this Mac", models=["ltx-2-distilled"],
                license="LTX-2 Community (free below $10M revenue)", concurrency=1,
                speed={"en": "about 6 min per 5 s shot at 576p, for timing only",
                       "zh": "约 6 分钟一个 5 秒镜头（576p），只看节奏", "fr": "environ 6 min par plan de 5 s en 576p"})

    def status(self):
        if not enabled():
            return dict(ready=False, code="create.local-off", params={})
        models = detect()
        if models is None:
            return dict(ready=False, code="create.provider.local-not-running", params=dict(port=PORT))
        return dict(ready=True, code="create.provider.ready", params=dict(models=models))

    def submit(self, job):
        raise CreateError("local-off", phase=2)
