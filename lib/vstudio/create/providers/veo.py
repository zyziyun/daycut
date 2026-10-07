"""Google Veo 3.1 through the Gemini API (long-running operation). Key: env GEMINI_API_KEY.

    POST {BASE}/models/{model}:predictLongRunning   {instances: [{prompt, image?}], parameters: {aspectRatio,
                                                     durationSeconds, resolution, negativePrompt}}
    -> {name: "models/.../operations/..."};  GET {BASE}/{name} -> {done, response.generateVideoResponse
    .generatedSamples[].video.uri};  the uri downloads with the same key header.
[unverified against a live key in this build: unit-tested with a fake transport only; the first paid run is the
user's own.]
"""
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request

from .base import Provider, SubmitTimeout

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = {"veo-3.1-fast": "veo-3.1-fast-generate-preview", "veo-3.1": "veo-3.1-generate-preview",
          "veo-3.1-lite": "veo-3.1-lite-generate-preview"}


class TransportError(RuntimeError):
    pass


def _http(url, data=None, headers=None, method=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf-8", "replace")
        if e.code == 429 or e.code >= 500:
            raise TransportError(f"HTTP {e.code}: {body}") from e
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise TransportError(str(e)) from e


class Veo(Provider):
    info = dict(id="veo", label={"en": "Google Veo", "zh": "Google Veo", "fr": "Google Veo"}, kind="cloud",
                needs=["GEMINI_API_KEY"], tos="official Gemini API, pay as you go", license=None,
                models=list(MODELS), concurrency=2)

    def __init__(self, key=None, base=None, transport=None):
        self._key, self.base = key, base or os.environ.get("GEMINI_API_BASE", BASE)
        self._transport = transport or _http

    def _h(self):
        k = self._key or os.environ.get("GEMINI_API_KEY")
        if not k:
            raise RuntimeError("GEMINI_API_KEY is not set (Settings > Video generation)")
        return {"x-goog-api-key": k, "Content-Type": "application/json"}

    @staticmethod
    def body(job):
        inst = {"prompt": job.prompt}
        first = (job.refs or {}).get("first_frame") or (job.refs or {}).get("image_1")
        if first and os.path.exists(str(first)):
            with open(first, "rb") as f:
                inst["image"] = {"bytesBase64Encoded": base64.b64encode(f.read()).decode(),
                                 "mimeType": mimetypes.guess_type(first)[0] or "image/jpeg"}
        params = {"aspectRatio": job.aspect if job.aspect in ("9:16", "16:9") else "9:16",
                  "durationSeconds": int(round(job.duration or 8)),
                  "resolution": job.resolution if job.resolution in ("720p", "1080p") else "1080p"}
        neg = (job.extra or {}).get("negative")
        if neg:
            params["negativePrompt"] = neg
        return {"instances": [inst], "parameters": params}

    def submit(self, job):
        model = MODELS.get(job.model, job.model)
        try:
            raw, _ = self._transport(f"{self.base}/models/{model}:predictLongRunning",
                                     json.dumps(self.body(job)).encode(), self._h(), "POST")
        except TransportError as e:
            raise SubmitTimeout(str(e)) from e
        r = json.loads(raw)
        if not r.get("name"):
            raise RuntimeError(f"submit rejected: {str(r)[:300]}")
        return r["name"]

    def poll(self, task_id):
        last = None
        for _ in range(4):
            try:
                raw, _ = self._transport(f"{self.base}/{task_id}", None, self._h(), "GET")
                break
            except TransportError as e:
                last = e
        else:
            raise last
        r = json.loads(raw)
        if not r.get("done"):
            return {"status": "pending", "urls": [], "raw": r}
        if r.get("error"):
            return {"status": "failed", "urls": [], "raw": r}
        samples = (((r.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [])
        urls = [((s.get("video") or {}).get("uri")) for s in samples]
        urls = [u for u in urls if u]
        return {"status": "done" if urls else "failed", "urls": urls, "raw": r}

    def download(self, url, path):
        raw, _ = self._transport(url, None, {"x-goog-api-key": self._h()["x-goog-api-key"]}, "GET")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        return path
