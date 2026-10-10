"""The engine drafts the files an ``author`` checkpoint asks for, so a creator is never handed a raw config to write.

An author checkpoint (promo-recut's keep spans and packaging, an explainer's script, a launch kit's config, ...) used
to stop with "write <file>" - and its item was seeded with the recipe's SYNTHETIC example, which the autopilot then
took for her answer. Now, when the gate reaches it:

    missing / template   no file, or the untouched template / example the item was seeded with: never an answer.
                         The engine drafts it: the recipe's own drafter (``DRAFTERS[(recipe, checkpoint)]``, e.g.
                         promo-recut keep spans from the transcript + her request), else the generic AI drafter (the
                         template + the format guide + her request -> the file, checked to parse). No model / a
                         reply that does not parse: no draft (the checkpoint waits for her, said plainly).
    drafted              the engine's draft, unchanged since (its record holds the file's sha): the default answer
    hers                 she (or her agent) edited it: used as it is

The record next to the file (``<file>.<checkpoint>.draft.json``): {by ai | rules, provider, model, sha, at, instruction, review}.
``review`` is what the Inbox shows instead of the file (never YAML, raw seconds or paths as the primary view):
{kind keep-spans | package | outline | text, summary {code, params}, lines [{code, params}], + per kind: segments
(keep spans: the transcript with kept / cut parts), text (a script)}. ``redraft(project, cp, item, instruction)`` is
"ask in plain words": a new draft that follows her instruction, the stored payload updated in place.
"""
import hashlib
import json
import os
import re
import time

from . import manifests as M

SIDE = ".draft.json"
TEXT_EXT = (".yaml", ".yml", ".json", ".md", ".txt", ".html", ".htm")
DOC_CHARS = 9000
TEMPLATE_CHARS = 12000
LANGS = {"en": "English", "zh": "Simplified Chinese", "fr": "French"}


# --------------------------------------------------------------------------- the context a drafter gets
class Ctx:
    """What a drafter knows about the item, at run time (a gate's ``Env``) or later (``redraft``)."""

    def __init__(self, project_dir, item, params, recipe, spec=None):
        self.project_dir, self.item, self.recipe = project_dir, item, recipe
        self.params = params or {}
        self.inputs = dict(self.params.get("_inputs") or {})
        self.item_dir = self.params.get("_item_dir") or os.path.join(project_dir, "items", item)
        self.spec = spec or {}
        self.m = M.get(recipe)
        self.workflow_dir = os.path.join(M.WORKFLOWS, self.m["workflow"])
        self._data = None

    @classmethod
    def of_env(cls, env):
        return cls(env.project_dir, env.job, env.params, env.m["id"], env.spec)

    @property
    def data(self):
        """project.yaml (her request lives there: ``prompt``)."""
        if self._data is None:
            try:
                import yaml
                with open(os.path.join(self.project_dir, "project.yaml"), encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or {}
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def request(self):
        d = self.data
        bits = [d.get("prompt") or "", d.get("name") or "", str(self.params.get("title") or "")]
        return "\n".join(dict.fromkeys(b for b in bits if b)).strip()

    def lang(self):
        """The language her review texts are written in: the autopilot's (the app's UI language), else the request's."""
        ap = self.data.get("autopilot")
        if isinstance(ap, dict) and ap.get("lang") in LANGS:
            return ap["lang"]
        from vstudio.publish import detect_lang
        return "en" if detect_lang(self.request() or "") == "en" else "zh"

    def item_path(self, *names):
        os.makedirs(self.item_dir, exist_ok=True)
        return os.path.join(self.item_dir, *names)

    def tctx(self):
        from .build import static_tctx
        return static_tctx(self.m, self.params, self.item)


# --------------------------------------------------------------------------- state
def sha(path):
    if os.path.isdir(path):
        from .adapters.common import dir_sha
        return dir_sha(path)
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:16]
    except OSError:
        return None


def side_path(path, cp_id):
    """``<file>.<checkpoint>.draft.json``: one record per checkpoint (promo-recut's keep and package share a file)."""
    return f"{path.rstrip(chr(47) + chr(92))}.{cp_id}{SIDE}"


def read_side(path, cp_id):
    try:
        with open(side_path(path, cp_id), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def write_side(path, cp_id, rec):
    rec = dict(rec, sha=sha(path), at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    with open(side_path(path, cp_id), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1, default=str)
    return rec


def is_template(path, template=None):
    """The untouched seed: byte-identical to the recipe's template, or still the SYNTHETIC example."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(600)
            body = head + f.read()
    except OSError:
        return False
    if template and os.path.isfile(template):
        try:
            with open(template, "rb") as f:
                if f.read() == body:
                    return True
        except OSError:
            pass
    return b"SYNTHETIC" in head


def state(path, template=None, cp=None, recipe=None):
    """missing | template | drafted | hers (module doc). ``cp`` / ``recipe``: a checkpoint that shares its file with
    another one (promo-recut package after keep) is "missing" until its own part is in the file."""
    if not path or not os.path.exists(path) or (os.path.isfile(path) and os.path.getsize(path) == 0):
        return "missing"
    if os.path.isdir(path) and not sha(path):
        return "missing"
    if is_template(path, template):
        return "template"
    cid = (cp or {}).get("id") if isinstance(cp, dict) else cp
    side = read_side(path, cid) if cid else None
    if side and side.get("sha") and side["sha"] == sha(path):
        return "drafted"
    part = _part_present(recipe, cid)
    if part and not side and not part(path):
        return "missing"
    return "hers"


def _part_present(recipe, cp_id):
    from .adapters import promo
    return {("promo-recut", "package"): promo.package_present}.get((recipe, cp_id))


# --------------------------------------------------------------------------- drafting
def _drafter(recipe, cp_id):
    from .adapters import preproduction, promo
    return {("promo-recut", "keep"): promo.draft_keep, ("promo-recut", "package"): promo.draft_package,
            ("preproduction", "lock"): preproduction.draft_script}.get((recipe, cp_id))


def _reviewer(recipe, cp_id):
    from .adapters import promo
    return {("promo-recut", "keep"): promo.review_keep, ("promo-recut", "package"): promo.review_package}.get(
        (recipe, cp_id))


def ensure(ctx, cp, path, template=None, instruction=None, complete=None, force=False, echo=None):
    """Draft the file when there is no usable one (missing / the untouched template) or ``force``. -> the draft
    record, None (nothing drafted: no model, a reply that did not parse, a kind the AI cannot write), or the
    existing record / None when the file is drafted / hers already."""
    st = state(path, template, cp, ctx.recipe)
    if st in ("drafted", "hers") and not force:
        return read_side(path, cp["id"])
    fn = _drafter(ctx.recipe, cp["id"]) or generic
    try:
        rec = fn(ctx, cp, path, template=template, instruction=instruction, complete=complete)
    except Exception as e:  # noqa: BLE001  (a draft that failed leaves the checkpoint to her, with the reason)
        if echo:
            echo(f"draft {cp['id']}: {e}")
        return dict(failed=str(e)[:300])
    if not rec:
        return None
    rec = write_side(path, cp["id"], rec)
    return rec


def review(ctx, cp, path, template=None):
    """The Inbox's view of the file (see the module doc), for any state: drafted / hers files are reviewed from
    their content; a missing / template file has no review."""
    st = state(path, template, cp, ctx.recipe)
    if st in ("missing", "template"):
        return None
    side = read_side(path, cp["id"]) if st == "drafted" else None
    fn = _reviewer(ctx.recipe, cp["id"])
    if fn:
        try:
            return fn(ctx, cp, path, side)
        except Exception:  # noqa: BLE001  (a file she broke: the generic outline still says what is in it)
            pass
    return outline_review(path, side)


# --------------------------------------------------------------------------- the generic AI drafter
GENERIC_SYSTEM = ("You prepare the working files of a video-editing pipeline so the creator never has to write them. "
                  "You get her request, what the item is made from, the file's format (its template and the "
                  "workflow's guide). Write the complete file for HER video: real content from her request and "
                  "materials, never the template's example content, never placeholders. Keep the template's "
                  "structure and keys. Reply with JSON only: {\"content\": \"<the whole file>\", \"summary\": \"<one "
                  "sentence: what you wrote>\"}.")


def _read(path, n):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(n)
    except (OSError, UnicodeDecodeError):
        return ""


def _materials_text(ctx):
    out = []
    for k, v in ctx.inputs.items():
        for p in (v if isinstance(v, list) else [v]):
            if isinstance(p, str):
                out.append(f"{k}: {os.path.basename(p)}")
                if p.lower().endswith((".md", ".txt")) and os.path.isfile(p):
                    out.append(_read(p, 4000))
    return "\n".join(out[:80])


def _valid(path, text):
    ext = os.path.splitext(path)[1].lower()
    if not text or not text.strip():
        return False
    if ext in (".yaml", ".yml"):
        import yaml
        try:
            return isinstance(yaml.safe_load(text), (dict, list))
        except yaml.YAMLError:
            return False
    if ext == ".json":
        try:
            json.loads(text)
            return True
        except ValueError:
            return False
    if ext in (".html", ".htm"):
        return "<" in text and ">" in text
    return True


def generic(ctx, cp, path, template=None, instruction=None, complete=None, template_text=None):
    """The AI writes the file from the template + the format guide + her request. Only text formats (never a
    folder or code the engine would execute). ``template_text``: the structure when there is no template file.
    -> record or None."""
    if os.path.isdir(path) or not path.lower().endswith(TEXT_EXT):
        return None
    a = cp.get("author") or {}
    tpl = template_text or (_read(template, TEMPLATE_CHARS) if template else "")
    cur = _read(path, TEMPLATE_CHARS) if state(path, template, cp, ctx.recipe) in ("drafted", "hers") else ""
    doc = _read(os.path.join(M.ROOT, a["doc"]), DOC_CHARS) if a.get("doc") else ""
    lang = ctx.lang()
    body = "\n\n".join(x for x in [
        f"Request: {ctx.request() or '(none)'}",
        f"Write: {os.path.basename(path)} ({a.get('format') or 'text'}) for the step "
        f"\"{(cp.get('labels') or {}).get('en') or cp['id']}\": {(cp.get('help') or {}).get('en') or ''}",
        f"Materials:\n{_materials_text(ctx)}" if ctx.inputs else "",
        f"Current file (change only what the instruction asks):\n{cur}" if cur and instruction else "",
        f"Instruction from the creator: {instruction}" if instruction else "",
        f"Template (structure only):\n{tpl}" if tpl else "",
        f"Format guide (excerpt):\n{doc}" if doc else "",
        f"Write the summary in {LANGS.get(lang, 'English')}; the file's own texts in the request's language."] if x)
    if complete is None:
        from vstudio import llm
        complete = llm.complete
    r = complete("planner", GENERIC_SYSTEM, body, schema=True, max_tokens=8000, timeout=240, cli_timeout=240,
                 retries=1)
    if not isinstance(r, dict) or r.get("provider") == "none":
        return None
    js = r.get("json") if isinstance(r.get("json"), dict) else {}
    text = js.get("content")
    if not isinstance(text, str) or not _valid(path, text) or (tpl and text.strip() == tpl.strip()):
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    summ = str(js.get("summary") or "").strip()[:300]
    rv = outline_review(path, None)
    rv["summary"] = dict(code="draft.generic", params=dict(text=summ)) if summ else rv["summary"]
    return dict(by="ai", provider=r.get("provider"), model=r.get("model"), instruction=instruction, review=rv)


# --------------------------------------------------------------------------- plain-language views
def _short(v, n=90):
    s = " ".join(str(v).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _human_key(k):
    return str(k).replace("_", " ").strip().capitalize()


def outline_review(path, side=None):
    """Any file -> {kind, summary, lines}: a script / text as its text (what she reads), a config as a few
    "Label: value" lines and list counts - never its syntax."""
    if side and isinstance(side.get("review"), dict) and side["review"].get("kind"):
        return side["review"]
    ext = os.path.splitext(path)[1].lower()
    if os.path.isdir(path):
        files = sorted(f for f in os.listdir(path) if not f.startswith("."))
        return dict(kind="outline", summary=dict(code="draft.files", params=dict(n=len(files))),
                    lines=[dict(code="draft.line", params=dict(label=f)) for f in files[:12]])
    text = _read(path, 200_000)
    if ext in (".md", ".txt"):
        clean = re.sub(r"^\s*#.*SYNTHETIC.*$", "", text, flags=re.M | re.I).strip()
        heads = [ln.lstrip("# ").strip() for ln in clean.splitlines() if ln.startswith("#")]
        return dict(kind="text", text=clean[:20000], summary=dict(code="draft.text", params=dict(
            n=len(heads), chars=len(clean))), lines=[dict(code="draft.line", params=dict(label=h)) for h in heads[:12]])
    data = None
    try:
        if ext in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(text)
        elif ext == ".json":
            data = json.loads(text)
    except Exception:  # noqa: BLE001
        data = None
    lines = []
    if isinstance(data, list):
        for x in data[:12]:
            lab = next((x[k] for k in ("title", "text", "question", "q", "name", "word", "label", "point")
                        if isinstance(x, dict) and isinstance(x.get(k), str)), None) if isinstance(x, dict) else x
            lines.append(dict(code="draft.line", params=dict(label=_short(lab if lab is not None else x))))
        return dict(kind="outline", summary=dict(code="draft.items", params=dict(n=len(data))), lines=lines)
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip():
                lines.append(dict(code="draft.kv", params=dict(label=_human_key(k), value=_short(v, 60))))
            elif isinstance(v, list) and v:
                lines.append(dict(code="draft.kn", params=dict(label=_human_key(k), n=len(v))))
            elif isinstance(v, dict) and v:
                sub = next((x for x in v.values() if isinstance(x, str) and x.strip()), None)
                if sub:
                    lines.append(dict(code="draft.kv", params=dict(label=_human_key(k), value=_short(sub, 60))))
            if len(lines) >= 10:
                break
        return dict(kind="outline", summary=dict(code="draft.config", params=dict(n=len(lines))), lines=lines)
    if ext in (".html", ".htm"):
        from vstudio.intake.sources import html_text
        title, body = html_text(text)
        return dict(kind="outline", summary=dict(code="draft.page", params=dict(title=_short(title or "", 60))),
                    lines=[dict(code="draft.line", params=dict(label=_short(ln))) for ln in body.splitlines()[:8]])
    return dict(kind="outline", summary=dict(code="draft.file", params={}), lines=[])


# --------------------------------------------------------------------------- "ask in plain words"
def redraft(project, cp_id, item, instruction=None, complete=None):
    """A new draft of an author checkpoint's file that follows ``instruction`` (None: draft it now, e.g. an older
    project whose file is still the template). Updates the stored payload in place (review, default, digest), so
    the Inbox shows the new draft at once. -> {ok, review, state, failed?}."""
    from .build import file_sha
    cp = project.checkpoint(cp_id)
    a = cp.get("author") or {}
    need_item = cp["scope"] != "project"
    target = item if need_item else "*"
    rows = {r["id"]: r for r in project.jobs_rows()}
    row = rows.get(item) or next(iter(rows.values()), {})
    params = dict(project.params(), **row)
    params.setdefault("_project_dir", project.dir)
    params.setdefault("_item_dir", os.path.join(project.dir, "items", item))
    ctx = Ctx(project.dir, item, params, project.manifest["id"], project.data.get("spec") or {})
    pay_path = os.path.join(project.state_dir, "checkpoints", item, f"{cp_id}.json")
    try:
        with open(pay_path, encoding="utf-8") as f:
            pay = json.load(f)
    except (OSError, ValueError):
        pay = None
    path = M.fmt(a["file"], ctx.tctx()) if a.get("file") else (pay or {}).get("file")
    if not path:
        raise ValueError(f"{cp_id}: no file to draft")
    tpl = os.path.join(M.ROOT, a["template"]) if a.get("template") else None
    rec = ensure(ctx, cp, path, tpl, instruction=instruction, complete=complete, force=True)
    st = state(path, tpl, cp, ctx.recipe)
    rv = review(ctx, cp, path, tpl)
    if isinstance(pay, dict):
        dig = file_sha(path) or "missing"
        props = ((cp.get("answer") or {}).get("properties") or {})
        done = dict(lock=True) if "lock" in props and "done" not in props else dict(done=True)
        pay.update(review=rv, draft_state=st, exists=st != "missing", default=done
                   if st in ("drafted", "hers") else None, digest=dig, options=[dict(file=path, sha=dig)],
                   draft_by=(read_side(path, cp_id) or {}).get("by") if st == "drafted" else None,
                   draft_error=(rec or {}).get("failed"))
        pay.pop("content", None)
        with open(pay_path, "w", encoding="utf-8") as f:
            json.dump(pay, f, ensure_ascii=False, indent=1, default=str)
    from . import autopilot as AP
    AP.log(project, dict(event="redrafted", checkpoint=cp_id, item=target, instruction=instruction,
                         by=(rec or {}).get("by"), state=st))
    return dict(ok=st in ("drafted", "hers"), state=st, review=rv, failed=(rec or {}).get("failed"))
