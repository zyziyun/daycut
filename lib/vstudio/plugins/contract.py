"""The plugin contract (API_VERSION 1). Three kinds; a plugin is a manifest (plugin.yaml) + an entry.

importer        bring an external board / project in as Create shots.
                ``sniff(path) -> 0..1`` (how sure it can read ``path``), ``load(path) -> Board`` (board.py).
                Or a command (any language): ``command: [./import, "{path}"]`` printing a Board as JSON on stdout.
shot-provider   anything that can make a shot. The Create Provider protocol (vstudio.create.providers.base):
                ``info`` {id, label, kind cloud|mcp|manual|local|render, needs, models, concurrency}, ``status()``,
                ``estimate`` = the manifest's ``rates`` (rates.json entries, so the spend gate prices it like a
                built-in), ``submit(job) -> task id`` (PAID: only after the spend gate, never retried),
                ``poll(task_id)``, ``download(url, path)`` (= fetch). kind ``render`` providers are free local
                renderers (HyperFrames, Remotion, manim...): ``render(job_dir, job) -> [files]`` instead of
                submit/poll, run in parallel lanes by ``make`` (lanes.py) with no spend gate (they cost nothing).
agent-runner    hand a job folder to an external agent / CLI (Claude Code, Codex, a HyperFrames agent, any
                command that reads the folder and writes outputs/): ``command(job) -> argv`` + ``env(job)``;
                the lanes run it with cwd = the job folder, stdin = brief.md, a heartbeat in status.json, a
                timeout, then the QC gate (jobfolder.py). Or declare ``command:`` in the manifest, no Python.

Cost declaration (manifest ``cost.kind``): free | local | subscription (the user's own Claude / Codex plan, nothing
charged by Reelfold) | paid. ``paid`` never runs outside the spend gate: a paid shot provider goes through the
finals estimate + confirm code like Kling; a paid agent runner / render provider is refused by ``make``.
Permissions (manifest ``permissions``): read-files | write-job | exec:<cli> | network | spend - shown to the user
in Settings; third-party plugins start disabled until the user turns them on.
"""
import os
import shutil

API_VERSION = 1
KINDS = ("importer", "shot-provider", "agent-runner")
COSTS = ("free", "local", "subscription", "paid")


class Importer:
    """Subclass: set ``id`` and ``exts``; implement ``sniff`` / ``load``."""
    id = "importer"
    exts = ()

    def __init__(self, manifest=None):
        self.manifest = manifest or {}

    def sniff(self, path):
        ext = os.path.splitext(str(path))[1].lower()
        return 0.5 if ext and ext in self.exts else 0.0

    def load(self, path):
        raise NotImplementedError


class AgentRunner:
    """Subclass: ``command(job)`` -> argv (cwd = the job folder, stdin = brief.md), ``status()``."""
    id = "agent"
    exe = None                      # the CLI it needs (status: ready when it is found)

    def __init__(self, manifest=None, settings=None):
        self.manifest = manifest or {}
        self.settings = settings or {}

    def find(self):
        from vstudio.llm import find_cli
        return find_cli(self.exe) if self.exe else None

    def status(self):
        if self.exe and not self.find():
            return dict(ready=False, code="create.plugin.not-ready", params=dict(detail=f"`{self.exe}` not found"))
        return dict(ready=True, code="create.plugins.ready", params={})

    def env(self, job):
        return {}

    def command(self, job):
        raise NotImplementedError


class CommandRunner(AgentRunner):
    """A runner declared in a manifest: ``command: ["mytool", "--in", "{job_dir}", "--out", "{outputs}"]``.
    Placeholders: {job_dir} {inputs} {outputs} {brief} {job_json} {shot} {episode}."""

    def __init__(self, manifest=None, settings=None):
        super().__init__(manifest, settings)
        self.argv = list(self.settings.get("command") or (manifest or {}).get("command") or [])
        self.exe = self.argv[0] if self.argv and not os.path.isabs(self.argv[0]) else None
        self.id = (manifest or {}).get("id") or "command"

    def find(self):
        if not self.argv:
            return None
        a0 = self.argv[0]
        if os.path.isabs(a0) or a0.startswith("./"):
            base = (self.manifest or {}).get("_dir") or ""
            p = a0 if os.path.isabs(a0) else os.path.join(base, a0[2:])
            return p if os.path.isfile(p) and os.access(p, os.X_OK) else None
        return shutil.which(a0)

    def status(self):
        if not self.argv:
            return dict(ready=False, code="create.plugin.not-ready", params=dict(detail="no command set"))
        if not self.find():
            return dict(ready=False, code="create.plugin.not-ready", params=dict(detail=f"`{self.argv[0]}` not found"))
        return dict(ready=True, code="create.plugins.ready", params={})

    def command(self, job):
        exe = self.find()
        vals = dict(job_dir=job["dir"], inputs=os.path.join(job["dir"], "inputs"),
                    outputs=os.path.join(job["dir"], "outputs"), brief=os.path.join(job["dir"], "brief.md"),
                    job_json=os.path.join(job["dir"], "job.json"), shot=job.get("shot", ""),
                    episode=job.get("episode", ""))
        out = [exe] + [str(a).format(**vals) for a in self.argv[1:]]
        return out
