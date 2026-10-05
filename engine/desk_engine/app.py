"""Local HTTP API for the desk (stdlib only).

Security model
  * binds 127.0.0.1 on a random port (port 0), printed once on stdout as a JSON ``ready`` line;
  * every /api request needs ``Authorization: Bearer <DESK_TOKEN>`` (per-launch token from the Electron main
    process, compared in constant time);
  * the Host header must be 127.0.0.1:<port> (DNS-rebinding guard); a present Origin must be in
    DESK_ALLOWED_ORIGINS (the desk UI's own origin) - CORS headers are only sent to those origins;
  * JSON bodies are capped at 1 MB and validated per route.

Routes (JSON unless noted)
  GET  /api/health                         mode real|mock, engine path
  GET  /api/recipes
  GET  /api/roots                          folders the desk may show media from (Electron media protocol)
  GET  /api/batches                        registry + state + counts
  POST /api/batches                        {name, recipe, source|folder, segments?, platforms[], budget?, out_dir?}
  POST /api/batches/import                 {dir}
  GET  /api/batches/<id>                   status (meta + job rows)
  GET  /api/batches/<id>/estimate
  POST /api/batches/<id>/run               {pilot?, confirm_pilot?, resume?, retry_failed?, jobs?[]}
  POST /api/batches/<id>/cancel
  GET  /api/batches/<id>/review            review items (contact sheet, snippet, QC, cleanup edits to confirm)
  POST /api/batches/<id>/review/apply      {decisions: {job: {decision, reason}}, cleanup: {job: reply}}
  POST /api/batches/<id>/package           {per_day?, start?, times?[]}
  GET  /api/batches/<id>/package           manifest + verify (recomputed confirmation code)
  GET  /api/batches/<id>/events?n=50&job=
  GET  /api/batches/<id>/jobs/<job>        job detail (stages, QC, cleanup words + edits, media paths)
  GET  /api/stream                         text/event-stream: status | log | run-start | run-exit | batches
"""
import hmac
import json
import os
import queue
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .common import JOB_RE, NAME_RE, BadRequest, need

MAX_BODY = 1 << 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
PLATFORM_RE = re.compile(r"^[a-z][a-z-]{1,30}(:[a-z]{3,12})?$")
ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _num(v, lo, hi, name):
    need(isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi, f"{name} must be {lo}..{hi}")
    return v


def _abs_path(v, name, must_exist=True, kind=None):
    need(isinstance(v, str) and 0 < len(v) < 4096 and os.path.isabs(v) and "\0" not in v,
         f"{name} must be an absolute path")
    if must_exist:
        need(os.path.exists(v), f"{name} does not exist")
        if kind == "file":
            need(os.path.isfile(v), f"{name} must be a file")
        if kind == "dir":
            need(os.path.isdir(v), f"{name} must be a folder")
    return os.path.normpath(v)


def validate_create(b):
    need(isinstance(b, dict), "body must be an object")
    need(isinstance(b.get("name"), str) and NAME_RE.match(b["name"]), "name: letters, digits, . _ - (max 64)")
    need(b.get("recipe") in ("longform-slices", "talkinghead-clips") or
         (isinstance(b.get("recipe"), str) and NAME_RE.match(b["recipe"])), "recipe required")
    out = dict(name=b["name"], recipe=b["recipe"])
    if b.get("source"):
        out["source"] = _abs_path(b["source"], "source", kind="file")
    if b.get("folder"):
        out["folder"] = _abs_path(b["folder"], "folder", kind="dir")
    need(bool(out.get("source")) != bool(out.get("folder")), "give exactly one of source (file) or folder")
    if b.get("segments"):
        out["segments"] = _abs_path(b["segments"], "segments", kind="file")
        need(out["segments"].lower().endswith((".yaml", ".yml", ".csv", ".json")), "segments: .yaml/.csv/.json")
    if out["recipe"].startswith("longform"):
        need(out.get("source"), f"{out['recipe']} needs a source file (one long recording)")
    if out["recipe"] == "longform-slices":
        need(out.get("segments"), "longform-slices needs segments.yaml (the job list)")
    pl = b.get("platforms") or []
    need(isinstance(pl, list) and 0 < len(pl) <= 8 and all(isinstance(p, str) and PLATFORM_RE.match(p) for p in pl),
         "platforms: 1-8 entries like tiktok or xiaohongshu:full")
    out["platforms"] = pl
    if b.get("budget") is not None:
        bud = b["budget"]
        need(isinstance(bud, dict), "budget must be an object")
        out["budget"] = {}
        for k, hi in (("max_usd", 100000), ("max_hours", 1000), ("max_storage_gb", 100000)):
            if bud.get(k) is not None:
                out["budget"][k] = _num(bud[k], 0, hi, f"budget.{k}")
    if b.get("out_dir"):
        out["out_dir"] = _abs_path(b["out_dir"], "out_dir", must_exist=False)
    if b.get("planner"):
        need(b["planner"] in ("file", "claude"), "planner: file | claude")
        out["planner"] = b["planner"]
    return out


def validate_run(b):
    need(isinstance(b, dict), "body must be an object")
    out = {}
    if b.get("pilot") is not None:
        out["pilot"] = int(_num(b["pilot"], 1, 50, "pilot"))
    for k in ("confirm_pilot", "resume", "retry_failed"):
        if b.get(k) is not None:
            need(isinstance(b[k], bool), f"{k} must be a boolean")
            out[k] = b[k]
    if b.get("jobs"):
        need(isinstance(b["jobs"], list) and len(b["jobs"]) <= 1000 and
             all(isinstance(j, str) and JOB_RE.match(j) for j in b["jobs"]), "jobs: list of job ids")
        out["jobs"] = b["jobs"]
    return out


def validate_decisions(b):
    need(isinstance(b, dict), "body must be an object")
    dec, cl = b.get("decisions") or {}, b.get("cleanup") or {}
    need(isinstance(dec, dict) and isinstance(cl, dict), "decisions / cleanup must be objects")
    need(len(dec) + len(cl) <= 5000, "too many decisions")
    out = dict(decisions={}, cleanup={})
    for jid, d in dec.items():
        need(JOB_RE.match(jid or ""), f"bad job id {jid!r}")
        need(isinstance(d, dict) and d.get("decision") in ("approve", "reject"), f"{jid}: decision approve|reject")
        r = d.get("reason") or ""
        need(isinstance(r, str) and len(r) <= 500, f"{jid}: reason max 500 chars")
        out["decisions"][jid] = dict(decision=d["decision"], reason=r)
    for jid, reply in cl.items():
        need(JOB_RE.match(jid or ""), f"bad job id {jid!r}")
        need(isinstance(reply, str) and len(reply) <= 2000, f"{jid}: cleanup reply must be text")
        out["cleanup"][jid] = reply
    return out


def validate_package(b):
    need(isinstance(b, dict), "body must be an object")
    out = {}
    if b.get("per_day") is not None:
        out["per_day"] = int(_num(b["per_day"], 1, 20, "per_day"))
    if b.get("start"):
        need(isinstance(b["start"], str) and DATE_RE.match(b["start"]), "start: YYYY-MM-DD")
        out["start"] = b["start"]
    if b.get("times"):
        need(isinstance(b["times"], list) and all(isinstance(t, str) and TIME_RE.match(t) for t in b["times"]),
             "times: [HH:MM, ...]")
        out["times"] = b["times"]
    return out


class Api:
    def __init__(self, engine, bus, token, origins):
        self.engine, self.bus, self.token, self.origins = engine, bus, token, set(origins)
        self.port = None

    def route(self, method, path, query, body):
        e = self.engine
        parts = [p for p in path.split("/") if p][1:]          # drop "api"
        if method == "GET" and parts == ["health"]:
            return dict(ok=True, **e.health())
        if method == "GET" and parts == ["recipes"]:
            return e.recipes()
        if method == "GET" and parts == ["roots"]:
            return e.roots()
        if parts[:1] != ["batches"]:
            raise KeyError("not found")
        if len(parts) == 1:
            if method == "GET":
                return e.list_batches()
            if method == "POST":
                return e.create_batch(validate_create(body))
        if parts[1:] == ["import"] and method == "POST":
            need(isinstance(body, dict), "body must be an object")
            return e.import_batch(_abs_path(body.get("dir"), "dir", kind="dir"))
        bid = parts[1]
        need(ID_RE.match(bid), "bad batch id")
        rest = parts[2:]
        if method == "GET" and not rest:
            return e.status(bid)
        if method == "GET" and rest == ["estimate"]:
            return e.estimate(bid)
        if method == "POST" and rest == ["run"]:
            return e.run(bid, validate_run(body or {}))
        if method == "POST" and rest == ["cancel"]:
            return e.cancel(bid)
        if method == "GET" and rest == ["review"]:
            return e.review_items(bid)
        if method == "POST" and rest == ["review", "apply"]:
            return e.apply_review(bid, validate_decisions(body))
        if method == "POST" and rest == ["package"]:
            return e.package(bid, validate_package(body or {}))
        if method == "GET" and rest == ["package"]:
            return e.manifest(bid)
        if method == "GET" and rest == ["events"]:
            n = int((query.get("n") or ["50"])[0])
            job = (query.get("job") or [None])[0]
            need(1 <= n <= 1000, "n: 1..1000")
            need(job is None or JOB_RE.match(job), "bad job id")
            return e.events(bid, n, job)
        if method == "GET" and len(rest) == 2 and rest[0] == "jobs":
            need(JOB_RE.match(rest[1]), "bad job id")
            return e.job(bid, rest[1])
        raise KeyError("not found")


def make_handler(api):
    class H(BaseHTTPRequestHandler):
        server_version = "vstudio-desk-engine"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet; never log headers (token)
            pass

        # ------------------------------------------------------------ guards
        def _origin_ok(self):
            o = self.headers.get("Origin")
            return o is None or o in api.origins

        def _host_ok(self):
            return self.headers.get("Host") in (f"127.0.0.1:{api.port}", f"localhost:{api.port}")

        def _auth_ok(self):
            h = self.headers.get("Authorization") or ""
            return h.startswith("Bearer ") and hmac.compare_digest(h[7:].encode(), api.token.encode())

        def _cors(self):
            o = self.headers.get("Origin")
            if o and o in api.origins:
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")

        def _send(self, code, obj):
            data = json.dumps(obj, ensure_ascii=False, default=lambda x: sorted(x) if isinstance(x, set) else str(x)
                              ).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _guard(self):
            if not self._host_ok():
                self._send(421, dict(error="bad host"))
                return False
            if not self._origin_ok():
                self._send(403, dict(error="origin not allowed"))
                return False
            if not self._auth_ok():
                self._send(401, dict(error="unauthorized"))
                return False
            return True

        # ------------------------------------------------------------ verbs
        def do_OPTIONS(self):
            if not self._host_ok() or not self._origin_ok() or not self.headers.get("Origin"):
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method):
            if not self._guard():
                return
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._send(404, dict(error="not found"))
            if method == "GET" and u.path == "/api/stream":
                return self._stream()
            body = None
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._send(413, dict(error="body too large"))
                if n:
                    ctype = self.headers.get("Content-Type") or ""
                    if not ctype.startswith("application/json"):
                        return self._send(415, dict(error="json only"))
                    try:
                        body = json.loads(self.rfile.read(n).decode("utf-8"))
                    except ValueError:
                        return self._send(400, dict(error="invalid json"))
            try:
                res = api.route(method, u.path, parse_qs(u.query), body)
                self._send(200, res)
            except BadRequest as e:
                self._send(400, dict(error=str(e)))
            except KeyError as e:
                self._send(404, dict(error=str(e).strip("'\"")))
            except (FileNotFoundError, ValueError) as e:
                self._send(422, dict(error=str(e)))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._send(500, dict(error=f"{type(e).__name__}: {e}"))

        def _stream(self):
            q = api.bus.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev = q.get(timeout=15)
                        data = json.dumps(ev, ensure_ascii=False, default=str)
                        self.wfile.write(f"event: {ev['type']}\ndata: {data}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                api.bus.unsubscribe(q)

    return H


def serve(api, host="127.0.0.1", port=0):
    httpd = ThreadingHTTPServer((host, port), make_handler(api))
    httpd.daemon_threads = True
    api.port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
