"""HyperFrames: import a project's storyboard as a board, and render a frame's composition as a shot.

A HyperFrames project (https://hyperframes.heygen.com) is a folder with ``hyperframes.json`` / ``index.html`` (the
root composition: clips with data-composition-id / data-composition-src / data-start / data-duration), usually a
``STORYBOARD.md`` (frontmatter + one ``## Frame N — Title`` section per frame with ``- key: value`` bullets:
duration, src, scene, voiceover, transition_in, status ...) and a ``BRIEF.md`` (frontmatter: message, aspect ...).

Import order: STORYBOARD.md frames; else the root index.html clips; titles / aspect from the frontmatter. Each frame
-> one shot (duration, title, scene -> action, voiceover, narrative -> notes, ref {kind: hyperframes, project, src})
routed to ``plugin:hyperframes`` when its composition file exists.

Render (shot provider, kind render, free): ``hyperframes render --composition <src> --quality draft --output
<job>/outputs/<shot>.mp4`` in the project, with the project's own CLI (node_modules/.bin/hyperframes) or one on
PATH - never an ``npx`` download. No CLI: the shot waits for you (render it in HyperFrames, drop the file on it).
"""
import html.parser
import os
import re
import shutil
import subprocess

import yaml

from vstudio.create.providers.base import Provider
from vstudio.plugins.contract import Importer

FRAME_RE = re.compile(r"^#{2,3}\s*(?:Frame|Beat|Scene|镜头|帧)\s*(\d+)?\s*(?:[—–:\-]+\s*)?(.*)$", re.I)
BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][\w ]{0,30}):\s*(.*)$")
ALIASES = {"vo": "voiceover", "voice_over": "voiceover", "narration": "voiceover", "description": "scene",
           "summary": "scene", "caption": "scene", "transition": "transition_in"}


def _front(text):
    """(frontmatter dict, body) of a markdown file."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            try:
                fm = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                fm = {}
            return (fm if isinstance(fm, dict) else {}), text[end + 4:]
    return {}, text


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'“”":
        v = v[1:-1]
    return v.strip().strip("“”").strip()


def parse_storyboard(text):
    """STORYBOARD.md -> (globals, [frame {number, title, fields{}, narrative}])."""
    fm, body = _front(text)
    frames, cur, in_meta = [], None, False
    for line in body.splitlines():
        m = FRAME_RE.match(line.strip())
        if m and line.lstrip().startswith("#"):
            cur = dict(number=int(m.group(1)) if m.group(1) else None, title=m.group(2).strip(), fields={},
                       narrative=[])
            frames.append(cur)
            in_meta = True
            continue
        if cur is None:
            continue
        b = BULLET_RE.match(line)
        if b and in_meta:
            k = b.group(1).strip().lower().replace(" ", "_")
            cur["fields"][ALIASES.get(k, k)] = _unquote(b.group(2))
            continue
        if line.strip():
            in_meta = False
            cur["narrative"].append(line.rstrip())
    for f in frames:
        f["narrative"] = "\n".join(f["narrative"]).strip()
    return fm, frames


class _Clips(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.root, self.clips = {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-composition-id" not in a:
            return
        if not self.root and a.get("data-composition-src") is None:
            self.root = a
            return
        if a.get("data-composition-src") or a.get("data-duration"):
            self.clips.append(a)


def parse_index(text):
    p = _Clips()
    p.feed(text)
    return p.root, p.clips


def project_dir(path):
    p = os.path.abspath(str(path))
    if os.path.isfile(p):
        p = os.path.dirname(p)
    return p


def is_project(path):
    d = project_dir(path)
    if os.path.exists(os.path.join(d, "hyperframes.json")):
        return True
    idx = os.path.join(d, "index.html")
    if os.path.exists(idx):
        try:
            with open(idx, encoding="utf-8", errors="replace") as f:
                return "data-composition-id" in f.read(200000)
        except OSError:
            return False
    sb = os.path.join(d, "STORYBOARD.md")
    return os.path.exists(sb)


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


class HyperFramesImporter(Importer):
    id = "hyperframes"
    exts = (".md", ".html")

    def sniff(self, path):
        p = str(path)
        if os.path.isdir(p):
            return 0.95 if is_project(p) else 0.0
        name = os.path.basename(p).lower()
        if name in ("storyboard.md", "hyperframes.json"):
            return 0.95
        if name.endswith(".html"):
            try:
                return 0.9 if "data-composition-id" in _read(p)[:200000] else 0.0
            except OSError:
                return 0.0
        if name.endswith(".md"):
            try:
                t = _read(p)[:20000]
            except OSError:
                return 0.0
            return 0.8 if re.search(r"^#{2,3}\s*Frame\s*\d", t, re.M | re.I) else 0.0
        return 0.0

    def load(self, path):
        d = project_dir(path)
        given = os.path.abspath(str(path))
        sb = given if given.lower().endswith(".md") else os.path.join(d, "STORYBOARD.md")
        brief = {}
        if os.path.exists(os.path.join(d, "BRIEF.md")):
            brief, _ = _front(_read(os.path.join(d, "BRIEF.md")))
        index_html = given if given.lower().endswith(".html") else os.path.join(d, "index.html")
        root, clips = parse_index(_read(index_html)) if os.path.exists(index_html) else ({}, [])
        title = None
        try:
            import json
            title = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8")).get("name")
        except (OSError, ValueError, AttributeError):
            pass
        shots = []
        g = {}
        if os.path.exists(sb):
            g, frames = parse_storyboard(_read(sb))
            by_src = {c.get("data-composition-src"): c for c in clips}
            for fr in frames:
                f = fr["fields"]
                src = f.get("src")
                clip = by_src.get(src) or {}
                dur = clip.get("data-duration") or f.get("duration")          # the built clip's real length
                ref = dict(kind="hyperframes", project=d, src=src or None, frame=fr["number"],
                           status=f.get("status") or "outline")
                exists = bool(src) and os.path.exists(os.path.join(d, src))
                extra = {k: v for k, v in f.items() if k not in ("src", "duration", "scene", "voiceover",
                                                                  "transition_in", "status", "poster")}
                notes = "\n".join([fr["narrative"]] + [f"{k}: {v}" for k, v in extra.items()]).strip()
                shots.append(dict(dur=dur or 3, title=fr["title"], action=f.get("scene") or fr["title"],
                                  voiceover=f.get("voiceover"), transition=f.get("transition_in"), notes=notes,
                                  ref=ref, source="plugin:hyperframes" if exists else None))
        elif clips:
            for c in clips:
                src = c.get("data-composition-src")
                cid = c.get("data-composition-id") or ""
                shots.append(dict(dur=c.get("data-duration") or 3, title=cid.replace("-", " ").strip(),
                                  action=cid.replace("-", " "),
                                  ref=dict(kind="hyperframes", project=d, src=src, start=c.get("data-start")),
                                  source="plugin:hyperframes" if src and os.path.exists(os.path.join(d, src)) else None))
        fmt = g.get("format") or brief.get("aspect") or brief.get("format")
        if not fmt and root.get("data-width") and root.get("data-height"):
            fmt = f"{root['data-width']}x{root['data-height']}"
        folder = os.path.basename(d) if os.path.basename(d) not in ("project", "src", "") else \
            os.path.basename(os.path.dirname(d))
        msg = next((m for m in (g.get("message"), brief.get("message"))
                    if m and not str(m).upper().startswith("TODO")), None)
        return dict(title=brief.get("title") or (title if title and title != "project" else None) or folder,
                    aspect=str(fmt or "9:16").split("#")[0].strip(), message=msg,
                    source=dict(kind="hyperframes", project=d), shots=shots)


def find_cli(project=None):
    if project:
        p = os.path.join(project, "node_modules", ".bin", "hyperframes")
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("hyperframes")


class HyperFramesProvider(Provider):
    """Free local renderer (kind render): one composition -> one MP4. ``render`` raises ExternalNeeded when no CLI
    (the shot then waits for a file you render in HyperFrames yourself)."""
    info = dict(id="hyperframes", label={"en": "HyperFrames", "zh": "HyperFrames", "fr": "HyperFrames"},
                kind="render", needs=[], tos="renders on this Mac with the project's own HyperFrames CLI",
                license=None, models=["composition"], concurrency=2)

    def status(self):
        if find_cli():
            return dict(ready=True, code="create.plugins.ready", params={})
        return dict(ready=True, code="create.plugins.ready", params=dict(note="uses each project's own CLI"))

    def render(self, job, timeout=1800):
        ref = job.get("ref") or {}
        project, src = ref.get("project"), ref.get("src")
        if not project or not os.path.isdir(project):
            raise ExternalNeeded("no HyperFrames project for this shot")
        exe = find_cli(project)
        if not exe:
            raise ExternalNeeded("HyperFrames CLI not installed in the project (npm i) or on PATH")
        out = os.path.join(job["dir"], "outputs", f"{job.get('shot') or 'shot'}.mp4")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cmd = [exe, "render", "--quality", "draft", "--output", out]
        if src:
            cmd[2:2] = ["--composition", src]
        with open(os.path.join(job["dir"], "log.txt"), "a", encoding="utf-8") as log:
            r = subprocess.run(cmd, cwd=project, stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        if r.returncode:
            raise RuntimeError(f"hyperframes render exited {r.returncode} (see log.txt)")
        return [out]


class ExternalNeeded(RuntimeError):
    """The shot has to be made outside Reelfold (no renderer here): it waits for a dropped file."""
