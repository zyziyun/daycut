"""AI video / image generation providers behind one interface.

    from providers import get_provider, Job
    p = get_provider("kling-mcp")
    job = Job(unit="u03", kind="video", model="kling-video-v3_0_omni", prompt="...", duration=5,
              aspect="9:16", resolution="1080p", refs={"image_1": "keyframes/u03_k2.jpg"})
    p.estimate(job)          # credits (provider units) or None when unknown
    tid = p.submit(job)      # charges the account - only generate.py calls this, behind --yes + budget
    p.poll(tid)              # {"status": "pending"|"done"|"failed", "urls": [...], "raw": {...}}
    p.download(url, "takes/u03_v1.mp4")

Adapters
  kling-mcp     Kling's hosted MCP server (https://klingai.com/mcp, streamable HTTP, JSON-RPC). This is the path the
                sessions used. Bearer token from env KLING_MCP_TOKEN (an OAuth access token you obtained yourself).
                Inside Claude Code the simpler path is the MCP connector itself (mcp__kling__* tools) - see
                references/PROVIDERS.md. Never read another app's stored credentials to get a token.
  seedance-ark  Seedance through Volcengine Ark's content-generation task API. Key from env ARK_API_KEY.
                NOT exercised in the sessions (they used the 即梦 web UI) - verify endpoint/model ids first.
  minimax       MiniMax Hailuo video API. Key from env MINIMAX_API_KEY (+ MINIMAX_API_BASE for the China host).
                NOT exercised in the sessions (they used the MiniMax web app) - verify first.
  manual        Any web UI (即梦/Seedance, 可灵 web, 海螺/MiniMax, Vidu...): writes a prompt sheet per unit and imports
                the files you download. Zero automation, zero accidental spend. The default for web-only tools.

Rules every adapter follows
  - Keys only from environment variables (or a user config outside the repo); nothing is ever written to the project.
  - submit() is never retried automatically: a timeout after the request left the machine may still have been
    charged. Retries cover poll() and download() only (transport errors, HTTP 429/5xx).
  - estimate() uses the rate table below (observed in-app prices, credits) unless the project overrides `rates:`.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- capabilities and observed prices
# Tags: [S] seen in the sessions (in-app price / accepted value), [U] unverified (docs or memory, check before use).
# Durations: list = discrete values accepted; tuple = (min, max) integer seconds.
CAPS = {
    "kling-video-v3_0_omni": dict(provider="kling-mcp", kind="video", durations=(3, 10), aspects=["9:16", "16:9", "1:1"],
                                  resolutions=["720p", "1080p"], max_refs=4, native_audio=True, max_prompt_chars=2500,
                                  note="[S] 4-6 s used; 1 prompt = 1 shot; elements bound as <<<id>>>; [U] max duration"),
    "kling-image-v3_0_omni": dict(provider="kling-mcp", kind="image", aspects=["9:16", "16:9", "1:1", "3:4"],
                                  resolutions=["1k", "2k"], max_refs=4, max_prompt_chars=2500,
                                  note="[S] keyframes / look sheets, 2k, 3-4 per batch"),
    "seedance-2": dict(provider="manual", kind="video", durations=(4, 15), aspects=["9:16", "16:9", "1:1"],
                       resolutions=["480p", "720p", "1080p"], max_refs=12, native_audio=True, max_prompt_chars=2000,
                       note="[S] 即梦 web: <=15 s per generation, up to 12 refs (image/video/audio), multi-shot "
                            "with in-prompt timecodes; draft (样片) mode = 480p"),
    "seedream-image": dict(provider="manual", kind="image", aspects=["9:16", "3:4", "1:1", "16:9"], resolutions=["2k"],
                           max_refs=6, note="[S] 即梦 image generation for look sheets, 4 per batch"),
    "minimax-hailuo": dict(provider="minimax", kind="video", durations=[6, 10], aspects=["9:16", "16:9"],
                           resolutions=["768p", "1080p"], max_refs=1, native_audio=False, max_prompt_chars=2000,
                           note="[U] 6/10 s; first-frame image ref; camera moves as [Push in] style commands"),
}

# Credits per second of video (by resolution) / per image. All [S] unless marked; prices change - the
# generate.py plan always says "estimate", and the in-app number shown before submitting wins.
RATES = {
    "kling-mcp": {"video": {"1080p": 12.0, "720p": 8.0}, "image": 2.0,
                  "note": "[S] 1080p 5 s = 60 credits (observed 48-72 per clip); keyframe images ~2 credits each"},
    "seedance": {"video": {"480p": 9.0, "720p": 8.0, "1080p": 11.0, "final-upgrade": 64.0}, "image": 8.0,
                 "note": "[S] 即梦: draft 480p ~9/s (5 s = 45 discounted); upgrading a draft to 正片 ~64/s (~7x); "
                         "720p ~8/s, 1080p ~11/s; Seedream image 8 each"},
    "minimax": {"video": {}, "image": None, "note": "[U] not recorded in the sessions - unknown"},
    "manual": {"video": {}, "image": None, "note": "price shown in the web UI"},
}


class ProviderError(RuntimeError):
    pass


class TransportError(ProviderError):
    """Network / 429 / 5xx - safe to retry for poll and download only."""


@dataclass
class Job:
    unit: str
    kind: str = "video"                    # video | image
    model: str = ""
    prompt: str = ""
    duration: float | None = None
    aspect: str = "9:16"
    resolution: str = "1080p"
    refs: dict = field(default_factory=dict)       # name -> local path or URL (image_1, audio_1, first_frame...)
    count: int = 1
    audio: bool = True                    # native audio (dialogue/ambience) where the model supports it
    elements: list = field(default_factory=list)   # provider-side subjects (Kling 主体): [{"id", "bindName"}]
    extra: dict = field(default_factory=dict)
    rate_key: str | None = None            # which RATES table to use (defaults to provider name)

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def with_retries(fn, tries=4, backoff=3.0, sleep=time.sleep):
    """Call fn() and retry on TransportError only (poll/download). Never wrap submit() with this."""
    for i in range(tries):
        try:
            return fn()
        except TransportError:
            if i == tries - 1:
                raise
            sleep(backoff * (i + 1))


def estimate_cost(job: Job, provider_name: str, rates: dict | None = None):
    """Credits for one job (count included), or None when the rate is unknown."""
    table = (rates or {}).get(job.rate_key or provider_name) or RATES.get(job.rate_key or provider_name) or {}
    if job.kind == "image":
        per = table.get("image")
        return None if per is None else round(per * max(1, job.count), 2)
    per_s = (table.get("video") or {}).get(job.resolution)
    if per_s is None or not job.duration:
        return None
    return round(per_s * float(job.duration) * max(1, job.count), 2)


def _http(url, data=None, headers=None, method=None, timeout=300):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read()[:500].decode("utf-8", "replace")
        if e.code == 429 or e.code >= 500:
            raise TransportError(f"HTTP {e.code}: {body}") from e
        if e.code == 401:
            raise ProviderError("HTTP 401: token expired or missing - re-authorise and export a fresh token") from e
        raise ProviderError(f"HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise TransportError(str(e)) from e


def _env(name, hint):
    v = os.environ.get(name)
    if not v:
        raise ProviderError(f"{name} is not set ({hint}). Keys come from the environment only.")
    return v


class Provider:
    name = "base"
    rate_key = None

    def caps(self, model):
        return CAPS.get(model, {})

    def estimate(self, job, rates=None):
        return estimate_cost(job, self.rate_key or self.name, rates)

    def balance(self):
        """Remaining credits, or None when the provider cannot tell."""
        return None

    def submit(self, job: Job) -> str:
        raise NotImplementedError

    def poll(self, task_id) -> dict:
        raise NotImplementedError

    def wait(self, task_id, every=10.0, limit=1800.0, sleep=time.sleep, clock=time.time):
        t0 = clock()
        while True:
            r = with_retries(lambda: self.poll(task_id), sleep=sleep)
            if r["status"] in ("done", "failed") or clock() - t0 > limit:
                return r
            sleep(every)

    def download(self, url, path, tries=4):
        def go():
            data, _ = _http(url, timeout=120)
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            return path
        return with_retries(go, tries=tries)


# --------------------------------------------------------------------------- Kling (hosted MCP)
_DONE = {"COMPLETED", "SUCCEED", "SUCCESS", "SUCCEEDED"}
_FAIL = {"FAILED", "FAIL", "ERROR", "CANCELLED", "CANCELED"}


class KlingMCP(Provider):
    """Minimal MCP client for https://klingai.com/mcp (protocol 2025-06-18, JSON or SSE replies).
    Tools used: who_am_i (call first: it documents each model's `arguments`), query_membership_and_credits,
    file_upload, text_to_image, image_to_image, text_to_video, image_to_video, omni_ref_video, query_tasks,
    element_create/element_list (subjects = 主体)."""
    name = "kling-mcp"
    URL = "https://klingai.com/mcp"

    def __init__(self, token=None, url=None, transport=None):
        self.url = url or os.environ.get("KLING_MCP_URL", self.URL)
        self._token = token
        self.sid, self.n = None, 0
        self._transport = transport or _http          # injectable for tests
        self._started = False

    @property
    def token(self):
        if not self._token:
            self._token = _env("KLING_MCP_TOKEN", "an OAuth access token for the Kling MCP server")
        return self._token

    def rpc(self, method, params=None, notify=False):
        self.n += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            body["id"] = self.n
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "Authorization": f"Bearer {self.token}", "MCP-Protocol-Version": "2025-06-18"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        raw, headers = self._transport(self.url, json.dumps(body).encode(), h, "POST")
        self.sid = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id") or self.sid
        raw = raw.decode() if isinstance(raw, bytes) else raw
        if notify or not raw.strip():
            return None
        if raw.lstrip().startswith("{"):
            msg = json.loads(raw)
        else:                                        # SSE: last data line
            datas = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
            msg = json.loads(datas[-1])
        if "error" in msg:
            raise ProviderError(str(msg["error"]))
        return msg["result"]

    def start(self):
        if not self._started:
            self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "video-studio-ai-video", "version": "1"}})
            self.rpc("notifications/initialized", notify=True)
            self._started = True
        return self

    def call(self, tool, args):
        self.start()
        res = self.rpc("tools/call", {"name": tool, "arguments": args})
        t = "".join(c.get("text", "") for c in (res or {}).get("content", []))
        try:
            return json.loads(t)
        except Exception:
            return t

    def balance(self):
        r = self.call("query_membership_and_credits", {})
        return r.get("availableRemainCredits") if isinstance(r, dict) else None

    def upload(self, path):
        """file_upload -> ticket + upload URL -> multipart POST -> hosted URL usable as an input."""
        if path.startswith("http"):
            return path
        ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
        info = self.call("file_upload", {"filename": os.path.basename(path), "contentType": ctype,
                                         "size": os.path.getsize(path)})
        up = info.get("upload_url") or info.get("uploadUrl")
        b = uuid.uuid4().hex
        with open(path, "rb") as f:
            data = f.read()
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"ticket\"\r\n\r\n{info.get('ticket')}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(path)}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        raw, _ = self._transport(up, body, {"Content-Type": f"multipart/form-data; boundary={b}"}, "POST")
        resp = json.loads(raw)
        return (resp.get("data") or {}).get("url") or resp.get("url")

    @staticmethod
    def tool_for(job: Job):
        if job.kind == "image":
            return "image_to_image" if job.refs else "text_to_image"
        if job.extra.get("omni_ref"):
            return "omni_ref_video"
        return "image_to_video" if job.refs else "text_to_video"

    def payload(self, job: Job, urls: dict):
        if job.kind == "image":
            args = {"prompt": job.prompt, "img_resolution": job.resolution if job.resolution in ("1k", "2k") else "2k",
                    "aspect_ratio": job.aspect, "imageCount": job.count}
        else:
            args = {"prompt": job.prompt, "duration": int(round(job.duration or 5)), "aspect_ratio": job.aspect,
                    "resolution": job.resolution, "imageCount": job.count,
                    "enable_audio": str(bool(job.audio)).lower()}
        if job.elements:
            args["elements"] = json.dumps(job.elements)
        args.update(job.extra.get("arguments", {}))
        p = {"model": job.model, "arguments": [{"name": k, "value": str(v)} for k, v in args.items()],
             "rationale": job.extra.get("rationale", f"Shot unit {job.unit} of the user's own short.")}
        if urls:
            p["inputs"] = [{"name": k, "inputType": "URL", "url": u} for k, u in urls.items()]
        return p

    def submit(self, job):
        urls = {k: self.upload(v) for k, v in job.refs.items()}
        r = self.call(self.tool_for(job), self.payload(job, urls))
        if not isinstance(r, dict) or not r.get("generationId"):
            raise ProviderError(f"submit rejected: {str(r)[:300]}")
        return r["generationId"]

    def poll(self, task_id):
        r = self.call("query_tasks", {"generationId": task_id})
        st = str(r.get("status", "")).upper() if isinstance(r, dict) else ""
        urls = [w.get("urlWithoutWatermark") or w.get("url") for w in (r.get("works") or [])
                if str(w.get("status", "")).upper() in _DONE] if isinstance(r, dict) else []
        status = "done" if st in _DONE else "failed" if st in _FAIL else "pending"
        return {"status": status, "urls": urls, "raw": r}


# --------------------------------------------------------------------------- Seedance via Volcengine Ark  [U]
class SeedanceArk(Provider):
    name = "seedance-ark"
    rate_key = "seedance"
    BASE = "https://ark.cn-beijing.volces.com/api/v3"

    def __init__(self, key=None, base=None, transport=None):
        self._key, self.base = key, base or os.environ.get("ARK_API_BASE", self.BASE)
        self._transport = transport or _http

    def _h(self):
        k = self._key or _env("ARK_API_KEY", "Volcengine Ark API key")
        return {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}

    def submit(self, job):
        if not job.model:
            raise ProviderError("set `model:` to an Ark Seedance model id from your Ark console")
        text = f"{job.prompt} --ratio {job.aspect} --duration {int(round(job.duration or 5))} --resolution {job.resolution}"
        content = [{"type": "text", "text": text}]
        for k, v in job.refs.items():
            if not str(v).startswith("http"):
                raise ProviderError(f"ref {k}: Ark needs a hosted URL (or base64 data URL), got a local path")
            content.append({"type": "image_url", "image_url": {"url": v}})
        raw, _ = self._transport(f"{self.base}/contents/generations/tasks",
                                 json.dumps({"model": job.model, "content": content}).encode(), self._h(), "POST")
        r = json.loads(raw)
        if not r.get("id"):
            raise ProviderError(f"submit rejected: {str(r)[:300]}")
        return r["id"]

    def poll(self, task_id):
        raw, _ = self._transport(f"{self.base}/contents/generations/tasks/{task_id}", None, self._h(), "GET")
        r = json.loads(raw)
        st = str(r.get("status", "")).lower()
        url = (r.get("content") or {}).get("video_url")
        return {"status": "done" if st == "succeeded" else "failed" if st in ("failed", "cancelled") else "pending",
                "urls": [url] if url else [], "raw": r}


# --------------------------------------------------------------------------- MiniMax Hailuo  [U]
class MiniMax(Provider):
    name = "minimax"
    BASE = "https://api.minimax.io/v1"

    def __init__(self, key=None, base=None, transport=None):
        self._key, self.base = key, base or os.environ.get("MINIMAX_API_BASE", self.BASE)
        self._transport = transport or _http

    def _h(self):
        k = self._key or _env("MINIMAX_API_KEY", "MiniMax platform API key")
        return {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}

    def submit(self, job):
        body = {"model": job.model or "MiniMax-Hailuo-02", "prompt": job.prompt,
                "duration": int(round(job.duration or 6)), "resolution": job.resolution.upper()}
        first = job.refs.get("first_frame") or job.refs.get("image_1")
        if first:
            body["first_frame_image"] = first
        raw, _ = self._transport(f"{self.base}/video_generation", json.dumps(body).encode(), self._h(), "POST")
        r = json.loads(raw)
        if not r.get("task_id"):
            raise ProviderError(f"submit rejected: {str(r)[:300]}")
        return r["task_id"]

    def poll(self, task_id):
        raw, _ = self._transport(f"{self.base}/query/video_generation?task_id={task_id}", None, self._h(), "GET")
        r = json.loads(raw)
        st = str(r.get("status", "")).lower()
        urls = []
        if st == "success" and r.get("file_id"):
            raw2, _ = self._transport(f"{self.base}/files/retrieve?file_id={r['file_id']}", None, self._h(), "GET")
            urls = [((json.loads(raw2).get("file") or {}).get("download_url"))]
        return {"status": "done" if st == "success" else "failed" if st == "fail" else "pending",
                "urls": [u for u in urls if u], "raw": r}


# --------------------------------------------------------------------------- manual (any web UI)
class Manual(Provider):
    """Writes a prompt sheet; you generate in the web UI and drop downloads into the inbox; `generate.py import`
    picks them up by filename prefix (<unit>_*.mp4)."""
    name = "manual"

    def __init__(self, site="web UI", rate_key="manual"):
        self.site, self.rate_key = site, rate_key

    def sheet(self, job: Job, n=None) -> str:
        refs = "\n".join(f"- {k}: `{v}`" for k, v in job.refs.items()) or "- (none)"
        dur = f"{job.duration:g} s" if job.duration else "-"
        return (f"## {job.unit}  ({self.site}, {job.kind}, {job.model or 'model per UI'}, {job.aspect}, {job.resolution}, {dur})\n\n"
                f"References to attach:\n{refs}\n\nPrompt (paste as ONE line - a newline can submit the form):\n\n"
                f"```\n{job.prompt}\n```\n\nSave downloads as `{job.unit}_v1.mp4`, `{job.unit}_v2.mp4`... in the inbox.\n")

    def submit(self, job):
        raise ProviderError("manual provider: generate in the web UI, then run `generate.py import`")

    def poll(self, task_id):
        return {"status": "pending", "urls": [], "raw": {}}


def get_provider(name, **kw):
    name = (name or "manual").lower()
    if name in ("kling", "kling-mcp"):
        return KlingMCP(**kw)
    if name in ("seedance-ark", "ark"):
        return SeedanceArk(**kw)
    if name in ("minimax", "hailuo", "minimax-hailuo"):
        return MiniMax(**kw)
    if name.startswith("manual"):
        site = name.split(":", 1)[1] if ":" in name else "web UI"
        rk = "seedance" if site in ("jimeng", "seedance", "即梦") else "kling-mcp" if site.startswith("kling") else "manual"
        return Manual(site=site, rate_key=rk)
    raise ProviderError(f"unknown provider {name!r} (kling-mcp | seedance-ark | minimax | manual[:site])")
