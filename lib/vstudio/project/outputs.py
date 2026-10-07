"""Second-pass editing of every finished output (成片二次编辑): ``python -m vstudio.project output ...``.

An **output** is one finished video the desk app shows: an export of a recipe project's item
(``<item>/<platform>-<orientation>``) or a video of an adopted work folder (``final/A.mp4``). Each output gets an
**edit document** next to the project store - ``<project>/state/outputs/<slug>/edit.json`` (recipe projects) or
``<work>/.vstudio/outputs/<slug>/edit.json`` (work folders) - holding the edit history (steps of ops, undo / redo).
Nothing else in the project or work folder is written; the original output is never overwritten: renders go to
the edit folder (``renders/``).

Two modes, decided per output (``caps`` says what each allows):
  pipeline   our pipeline made the clip and kept its clean (caption-free) master + cues (talkinghead compose,
             a work folder's ``.vstudio/masters.json`` / ``<stem>.master.mp4``): every render re-composes from the
             master - captions are ours (text, style, position, keyword colour), re-layout to other aspects is a
             fresh reframe of the master.
  flattened  only the finished file exists: edits go on top of it. Trims / cuts / speed re-encode, effects and a
             title band overlay it; captions can only be ADDED, in a band layout or over a mask that hides the
             burned ones (burned text is never restyled); re-layout reframes the file (burned text may be cropped:
             the ``band`` layout keeps the whole frame).

Times in ops are seconds on the ORIGINAL output timeline (``time_base: "edited"`` = the current edited timeline,
converted when the op is recorded); positions are fractions of the canvas. Every message has a stable ``code`` +
``params`` with English ``message`` and ``message_zh`` (the desk localises by code).

    list_outputs(dir) / show(dir, out) / edit(dir, out, ops, turn) / undo / redo / revert(dir, out, step) /
    ai(dir, out, instruction, apply, context) / chat / chat_add / chat_update (chat.json transcript)
    render: vstudio.project.outrender.render(dir, out, quality="preview" | "final", targets=[...])
"""
import copy
import glob
import os
import re
import time

from vstudio.batch.util import read_json, sha1_json, write_json

from . import outfx as FX

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
DOC_VERSION = 1
MIN_KEEP_S = 1.0
OPS = ("trim", "cut", "cut_remove", "speed", "loudness", "captions", "caption_text", "caption_style", "caption_add",
       "caption_remove", "caption_placement", "title", "effect_add", "effect_remove", "effect_update", "cover",
       "export_add", "export_remove", "reset")
TARGET_ALIASES = {"3:4": "xiaohongshu:vertical", "9:16": "douyin:vertical", "16:9": "youtube:horizontal",
                  "小红书": "xiaohongshu", "抖音": "douyin", "b站": "bilibili", "B站": "bilibili", "视频号": "douyin",
                  "shorts": "youtube-shorts", "youtube shorts": "youtube-shorts"}
TRANSCRIBE = None            # tests / embedders: fn(path, language) -> transcript dict or [{"w","t","te"}]


# --------------------------------------------------------------------------- messages
def msg(code, message, message_zh=None, **params):
    """A user-facing message: stable ``code`` + ``params`` (the desk localises by code), English ``message``."""
    d = dict(code=code, params=params, message=message)
    if message_zh:
        d["message_zh"] = message_zh
    return d


class OutputError(ValueError):
    def __init__(self, code, message, message_zh=None, **params):
        super().__init__(message)
        self.info = msg(code, message, message_zh, **params)


def _err(code, en, zh=None, **params):
    return OutputError(code, en, zh, **params)


def llm_failed(e, provider=None):
    """A failed ``vstudio.llm.complete`` -> OutputError ``llm-failed`` whose params list EVERY provider tried
    (``tried`` / ``errors`` / ``codes`` / ``attempts``), so the desk can say "Claude Code expired; Codex also
    failed: ..." instead of only the first error."""
    from vstudio import llm
    ei = llm.error_info(e) if isinstance(e, llm.LLMError) else dict(
        code=llm.failure_code(e), tried=[provider], errors=[str(e)[:300]], codes=[llm.failure_code(e)], attempts=[])
    names_ = ", ".join(str(x) for x in ei["tried"] if x) or str(provider or "")
    many = len([x for x in ei["tried"] if x]) > 1
    en = (f"every AI provider failed ({names_}): " if many else "the model call failed: ") + str(e)[:200]
    zh = f"所有 AI 模型都失败了（{names_}）" if many else "模型调用失败"
    return OutputError("llm-failed", en, zh, provider=provider or (ei["tried"][0] if ei["tried"] else None),
                       error=str(e)[:300], code_hint=ei["code"], tried=ei["tried"], errors=ei["errors"],
                       codes=ei["codes"], attempts=ei["attempts"])


AI_CLI_TIMEOUT = 60.0     # s per CLI provider attempt for output ai (an expired claude -p hangs ~3 min otherwise)


# --------------------------------------------------------------------------- owners and outputs
def owner_kind(d):
    d = os.path.abspath(d)
    if os.path.exists(os.path.join(d, "project.yaml")):
        return "project"
    if os.path.exists(os.path.join(d, ".vstudio", "work.json")):
        return "work"
    return None


def _owner(d):
    d = os.path.abspath(d)
    k = owner_kind(d)
    if not k:
        from .core import find
        f = find(d)
        if owner_kind(f) == "project":
            return f, "project"
        if os.path.isdir(d) and _work_files(d):                 # a plain skill folder: adopt it (record only)
            from . import works as W
            W.adopt(d)
            return d, "work"
        raise _err("unknown-owner", f"{d} is neither a project (project.yaml) nor an adopted work folder",
                   f"{d} 不是项目（project.yaml）也不是已登记的作品文件夹", dir=d)
    return d, k


def _work_files(d):
    from . import works as W
    rec = read_json(W.record_path(d), {}) or {}
    rels = list(rec.get("outputs") or []) or W.scan(d)["outputs"]
    out = []
    for r in rels:
        p = os.path.join(d, r)
        if os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO and "/.vstudio/" not in "/" + r:
            out.append(r)
    return out


def edits_root(d, kind):
    return os.path.join(d, "state", "outputs") if kind == "project" else os.path.join(d, ".vstudio", "outputs")


def slug_id(oid):
    s = re.sub(r"[^\w.-]+", "_", oid, flags=re.UNICODE).strip("._")[:60] or "output"
    return f"{s}-{sha1_json(oid, 6)}"


def _probe(path):
    from vstudio import media
    i = media.probe(path)
    return dict(w=int(i.get("display_w") or i["w"]), h=int(i.get("display_h") or i["h"]), fps=float(i["fps"] or 30.0),
                duration=float(i["duration"] or 0.0), has_audio=bool(i["has_audio"]))


def file_sig(path):
    """Cheap content signature (size, mtime, first + last MiB) - stable across reads, changes with the file."""
    import hashlib
    st = os.stat(path)
    h = hashlib.sha1(f"{st.st_size}:{int(st.st_mtime)}".encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if st.st_size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:20]


def _profile_for(w, h, key=None):
    from vstudio import platform as P
    if key:
        try:
            return P.profile(*key.split(":", 1)) if ":" in key else P.profile(key)
        except Exception:  # noqa: BLE001
            pass
    prefer = ["xiaohongshu:vertical", "douyin:vertical", "youtube:horizontal", "xiaohongshu:full", "bilibili:horizontal"]
    for k in prefer + P.list_profiles():
        p = P.profile(*k.split(":"))
        if (p.w, p.h) == (w, h):
            return p
    for k in prefer:                                      # same aspect, other size
        p = P.profile(*k.split(":"))
        if abs(p.w / p.h - w / h) < 0.01:
            return p
    return None


def _project_outputs(pdir):
    from vstudio.batch.store import Store

    from . import manifests as M
    from .core import Project
    p = Project(pdir)
    collect = M.resolve_ref(p.manifest["outputs"]["collect"])
    st = Store(p.state_dir)
    out = []
    try:
        for j in st.jobs():
            if j["state"] == "dropped":
                continue
            rows = st.stage_rows(j["id"])
            try:
                ents = collect(p, j, rows) or []
            except Exception:  # noqa: BLE001  (an unfinished item: nothing to edit yet)
                ents = []
            for e in ents:
                f = e.get("file")
                if not f or not os.path.isfile(f) or os.path.splitext(f)[1].lower() not in VIDEO:
                    continue
                tag = "-".join(x for x in (e.get("platform"), e.get("orientation")) if x) or os.path.basename(f)
                out.append(dict(id=f"{j['id']}/{tag}", file=os.path.abspath(f), item=j["id"], job_state=j["state"],
                                platform=e.get("platform"), orientation=e.get("orientation"),
                                title=(j["params"] or {}).get("title"), cover=e.get("cover"), post=e.get("post"),
                                _rows=rows, _params=j["params"] or {}))
    finally:
        st.close()
    return out


def _work_master(d, rel):
    """A clean master our pipeline left for a work-folder output: ``.vstudio/masters.json`` {rel: {master, cues}}
    (``register_master``), else ``<stem>.master.mp4`` / ``<stem>_clean.mp4`` next to it or in work/."""
    rec = (read_json(os.path.join(d, ".vstudio", "masters.json"), {}) or {}).get(rel)
    if isinstance(rec, dict) and rec.get("master"):
        m = rec["master"] if os.path.isabs(rec["master"]) else os.path.join(d, rec["master"])
        c = rec.get("cues")
        c = (c if os.path.isabs(c) else os.path.join(d, c)) if c else None
        if os.path.isfile(m):
            return m, (c if c and os.path.isfile(c) else None)
    stem = os.path.splitext(os.path.basename(rel))[0]
    here = os.path.dirname(os.path.join(d, rel))
    for folder in (here, os.path.join(d, "work")):
        for name in (f"{stem}.master.mp4", f"{stem}_master.mp4", f"{stem}.clean.mp4", f"{stem}_clean.mp4"):
            m = os.path.join(folder, name)
            if os.path.isfile(m):
                c = next((x for x in (os.path.join(folder, f"{stem}.cues.json"), os.path.join(folder, f"{stem}_cues.json"))
                          if os.path.isfile(x)), None)
                return m, c
    return None, None


def register_master(d, output, master, cues=None):
    """Workflows: say which clean master (+ cues JSON) made a work-folder output, so its second-pass edits
    re-compose from the master (``pipeline`` mode) instead of editing the flattened file."""
    d = os.path.abspath(d)
    rel = os.path.relpath(os.path.abspath(os.path.join(d, output)), d)
    path = os.path.join(d, ".vstudio", "masters.json")
    data = read_json(path, {}) or {}
    data[rel] = dict(master=os.path.abspath(master), cues=os.path.abspath(cues) if cues else None)
    write_json(path, data)
    return data[rel]


def list_outputs(d):
    """-> {ok, dir, kind, outputs [{id, file, title, platform, mode, edited, steps, renders}]} (no media work
    beyond reading edit docs)."""
    d, kind = _owner(d)
    rows = []
    if kind == "project":
        for o in _project_outputs(d):
            rows.append(dict(id=o["id"], file=o["file"], title=o.get("title"), item=o["item"],
                             platform=o.get("platform"), orientation=o.get("orientation"), job_state=o["job_state"]))
    else:
        from . import works as W
        rec = W.show(d) or {}
        for r in _work_files(d):
            rows.append(dict(id=r, file=os.path.join(d, r), title=os.path.splitext(os.path.basename(r))[0],
                             item=None, platform=None, orientation=None, work_title=rec.get("title")))
    root = edits_root(d, kind)
    for r in rows:
        doc = read_json(os.path.join(root, slug_id(r["id"]), "edit.json"), None)
        r["edited"] = bool(doc and doc.get("steps"))
        r["steps"] = len((doc or {}).get("steps") or [])
        r["mode"] = (doc or {}).get("mode")
        r["edit_dir"] = os.path.join(root, slug_id(r["id"]))
    return dict(ok=True, dir=d, kind=kind, outputs=rows)


def _match(rows, output):
    for r in rows:
        if r["id"] == output:
            return r
    ap = os.path.abspath(output)
    for r in rows:
        try:
            if os.path.abspath(r["file"]) == ap or (os.path.exists(ap) and os.path.samefile(r["file"], ap)):
                return r
        except OSError:
            continue
    hits = [r for r in rows if os.path.basename(r["file"]) == output or r["id"].endswith("/" + output)]
    return hits[0] if len(hits) == 1 else None


def _cues_of_job(rows, params):
    """The cues the pipeline burned: proofread's (else compose's), with the review caption edits applied."""
    pr = (rows.get("proofread") or {}).get("out") or {}
    cm = (rows.get("compose") or {}).get("out") or {}
    path = pr.get("cues") if pr.get("cues") and os.path.exists(pr["cues"]) else cm.get("cues")
    d = read_json(path, {}) or {}
    cues = d.get("cues") if isinstance(d, dict) else d
    cues = list(cues or [])
    if params.get("caption_overrides"):
        from vstudio.batch.edits import apply_caption_overrides
        a = read_json(cm.get("cues"), {}) or {}
        cues, _, _ = apply_caption_overrides(cues, params["caption_overrides"],
                                             asr_cues=a.get("cues") if isinstance(a, dict) else a)
    return [dict(start=float(c["start"]), end=float(c["end"]), text=str(c.get("text") or ""),
                 kind=(c.get("meta") or {}).get("kind")) for c in cues if str(c.get("text") or "").strip()]


def _cues_file(path):
    if not path:
        return []
    from vstudio.export import load_cues
    return [dict(start=c.start, end=c.end, text=c.text) for c in load_cues(path) if c.text.strip()]


def resolve(d, output):
    """-> the output record: {id, owner, kind, file, info, mode, master, cues, platform, reason, edit_dir}."""
    d, kind = _owner(d)
    if kind == "project":
        rows = _project_outputs(d)
    else:
        rows = [dict(id=r, file=os.path.join(d, r), title=os.path.splitext(os.path.basename(r))[0])
                for r in _work_files(d)]
    o = _match(rows, output)
    if not o:
        raise _err("unknown-output", f"no output {output!r} in {d} (output list --json shows the ids)",
                   f"{d} 里没有成片 {output!r}", output=output, dir=d, known=[r["id"] for r in rows][:50])
    info = _probe(o["file"])
    rec = dict(id=o["id"], owner=d, kind=kind, file=o["file"], title=o.get("title"), info=info, mode="flattened",
               master=None, master_info=None, cues=[], captions_on=False, platform=None, reason=None,
               edit_dir=os.path.join(edits_root(d, kind), slug_id(o["id"])))
    if o.get("platform"):
        rec["platform"] = f"{o['platform']}:{o['orientation']}" if o.get("orientation") else o["platform"]
    master, cues = None, []
    if kind == "project":
        cm = ((o.get("_rows") or {}).get("compose") or {}).get("out") or {}
        if cm.get("master") and os.path.isfile(cm["master"]):
            master = cm["master"]
            cues = _cues_of_job(o["_rows"], o["_params"])
            rec["captions_on"] = bool(o["_params"].get("captions", True))
        else:
            rec["reason"] = msg("no-master", "the recipe kept no clean master for this output: edits go on top of "
                                "the finished file", "这个成片没有保留干净母版：在成片上叠加编辑")
    else:
        rel = os.path.relpath(o["file"], d)
        master, cpath = _work_master(d, rel)
        if master:
            cues = _cues_file(cpath)
            rec["captions_on"] = bool(cues)
        else:
            rec["reason"] = msg("no-master", "made outside a pipeline that keeps masters: edits go on top of the "
                                "finished file", "不是保留母版的流程做的：在成片上叠加编辑")
    if master:
        mi = _probe(master)
        if abs(mi["duration"] - info["duration"]) > 0.35:
            rec["reason"] = msg("master-mismatch", f"the master ({mi['duration']:.2f}s) does not match the output "
                                f"({info['duration']:.2f}s): editing the finished file",
                                "母版与成片时长不一致：在成片上编辑", master_s=round(mi["duration"], 2),
                                output_s=round(info["duration"], 2))
        else:
            rec.update(mode="pipeline", master=master, master_info=mi, cues=cues)
    rec["profile"] = _profile_for(info["w"], info["h"], rec["platform"])
    return rec


# --------------------------------------------------------------------------- capabilities
def capabilities(rec, doc=None):
    """Flags the desk greys controls with + the notes explaining each limit ({code, params, message})."""
    pipe = rec["mode"] == "pipeline"
    burned = (doc or {}).get("burned") or {}
    caps = dict(mode=rec["mode"], trim=True, cut=True, cut_snap="words", speed=True, loudness=True, effects=True,
                title_band=True, cover=True, export=True, undo=True, ai=True,
                captions_ours=pipe, caption_text=pipe, caption_style=True, caption_restyle_burned=False,
                caption_toggle=pipe, caption_add=True, caption_placements=["ours"] if pipe else ["band", "mask"],
                relayout="master" if pipe else "reframe-file", relayout_layouts=["auto"] if pipe else ["auto", "band"],
                burned_captions=None if pipe else burned.get("captions"), audio=rec["info"]["has_audio"])
    notes = []
    if not pipe:
        notes.append(msg("flattened", "edits are applied on top of the finished file (no clean master)",
                         "在成片上叠加编辑（没有干净母版）"))
        notes.append(msg("captions-add-only", "captions can only be added, in a band layout or over a mask; "
                         "burned-in text cannot be restyled", "字幕只能新增（字幕条布局或遮罩上），已烧录的文字不能改样式"))
        notes.append(msg("relayout-crops-burned", "a re-layout reframes the file: burned text near the edges may be "
                         "cropped (use layout band to keep the whole frame)",
                         "换比例会重新取景，边缘的烧录文字可能被裁掉（用 band 布局保留整幅画面）"))
        if rec.get("reason"):
            notes.append(rec["reason"])
    if not rec["info"]["has_audio"]:
        caps["loudness"] = False
        notes.append(msg("no-audio", "the output has no audio track", "成片没有音轨"))
    return caps, notes


# --------------------------------------------------------------------------- the document
def empty_state():
    return dict(trim=[None, None], cuts=[], speed=1.0, loudness=dict(lufs=None, tp=None),
                captions=dict(enabled=None, style={}, overrides={}, removed=[], added=[], placement=None),
                title=None, effects=[], cover=None, exports=[], seq=0)


class Doc:
    def __init__(self, rec):
        self.rec = rec
        self.dir = rec["edit_dir"]
        self.path = os.path.join(self.dir, "edit.json")
        d = read_json(self.path, None)
        sig = file_sig(rec["file"])
        if not isinstance(d, dict) or d.get("version") != DOC_VERSION:
            d = dict(version=DOC_VERSION, output=rec["id"], owner=rec["owner"], kind=rec["kind"], file=rec["file"],
                     created=_stamp(), steps=[], redo=[])
        if d.get("source_sig") and d["source_sig"] != sig:
            d.setdefault("warnings", []).append(msg("source-changed", "the output file changed since the edits "
                                                    "were made; they are re-applied to the new file",
                                                    "成片文件已变化，编辑会重新应用到新文件").copy())
            d.pop("transcript_sig", None)
            d.pop("burned", None)
        d.update(source_sig=sig, mode=rec["mode"], file=rec["file"], master=rec.get("master"))
        self.d = d

    def save(self):
        self.d["updated"] = _stamp()
        os.makedirs(self.dir, exist_ok=True)
        write_json(self.path, self.d)

    def state(self, steps=None):
        st = empty_state()
        for s in active_steps(self.d["steps"] if steps is None else steps):
            for op in s["ops"]:
                st = fold(st, op)
        if st["captions"]["enabled"] is None:
            st["captions"]["enabled"] = bool(self.rec.get("captions_on"))
        # ids stay unique across reverted steps too (a revert can itself be undone)
        st["seq"] = max([st["seq"]] + [o.get("seq", 0) for s in self.d["steps"] for o in s["ops"]])
        return st


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def reverted_ids(steps):
    """Ids of steps cancelled by a (not itself cancelled) ``revert`` step. Walked newest first, so reverting a
    revert step brings its target back."""
    dead = set()
    for s in reversed(steps):
        if s["id"] in dead:
            continue
        if s.get("revert_of"):
            dead.add(s["revert_of"])
    return dead


def active_steps(steps):
    """The steps whose ops make the current state: everything except revert markers and what they cancel."""
    dead = reverted_ids(steps)
    return [s for s in steps if s["id"] not in dead and not s.get("revert_of")]


# --------------------------------------------------------------------------- fold (pure: normalized op -> state)
def fold(st, op):
    st = copy.deepcopy(st)
    k = op["op"]
    c = st["captions"]
    if k == "trim":
        st["trim"] = [op.get("start"), op.get("end")]
    elif k == "cut":
        st["cuts"] = merge_cuts(st["cuts"] + [[op["start"], op["end"], op.get("why") or ""]])
    elif k == "cut_remove":
        st["cuts"] = [x for i, x in enumerate(st["cuts"]) if i != op["index"]]
    elif k == "speed":
        st["speed"] = op["value"]
    elif k == "loudness":
        st["loudness"] = dict(lufs=op.get("lufs"), tp=op.get("tp"))
    elif k == "captions":
        c["enabled"] = op["enabled"]
    elif k == "caption_text":
        if op["cue"].startswith("a"):
            for a in c["added"]:
                if a["id"] == op["cue"]:
                    a["text"] = op["text"]
        else:
            c["overrides"][op["cue"]] = op["text"]
    elif k == "caption_style":
        c["style"] = {kk: v for kk, v in dict(c["style"], **op["style"]).items() if v is not None}
    elif k == "caption_add":
        for cue in op["cues"]:
            c["added"].append(dict(cue))
        st["seq"] = max(st["seq"], op.get("seq", 0))
        if op.get("placement"):
            c["placement"] = op["placement"]
    elif k == "caption_remove":
        if op["cue"].startswith("a"):
            c["added"] = [a for a in c["added"] if a["id"] != op["cue"]]
        elif op["cue"] not in c["removed"]:
            c["removed"].append(op["cue"])
    elif k == "caption_placement":
        c["placement"] = op["placement"]
    elif k == "title":
        st["title"] = op.get("title")
    elif k == "effect_add":
        st["effects"].append(dict(id=op["id"], effect=op["effect"], start=op["start"], end=op["end"],
                                  params=dict(op["params"])))
        st["seq"] = max(st["seq"], op.get("seq", 0))
    elif k == "effect_remove":
        st["effects"] = [e for e in st["effects"] if e["id"] != op["id"]]
    elif k == "effect_update":
        for e in st["effects"]:
            if e["id"] == op["id"]:
                e["start"], e["end"] = op["start"], op["end"]
                e["params"] = dict(op["params"])
    elif k == "cover":
        st["cover"] = op.get("cover")
    elif k == "export_add":
        st["exports"] = [x for x in st["exports"] if x["target"] != op["target"]] + [
            dict(target=op["target"], layout=op.get("layout") or "auto")]
    elif k == "export_remove":
        st["exports"] = [x for x in st["exports"] if x["target"] != op["target"]]
    elif k == "revert":
        pass                                     # a marker: Doc.state() skips the step it cancels
    elif k == "reset":
        seq = st["seq"]
        st = empty_state()
        st["seq"] = seq
    return st


def merge_cuts(cuts):
    cs = sorted([[float(a), float(b), w] for a, b, w in (list(x)[:3] + [""] * (3 - len(list(x)[:3])) for x in cuts)])
    out = []
    for a, b, w in cs:
        if out and a <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], b)
            out[-1][2] = "; ".join(x for x in (out[-1][2], w) if x)
        else:
            out.append([a, b, w])
    return [[round(a, 3), round(b, 3), w] for a, b, w in out]


# --------------------------------------------------------------------------- timeline
def segments(st, dur):
    """Kept source ranges: trim minus cuts."""
    a = float(st["trim"][0] if st["trim"][0] is not None else 0.0)
    b = float(st["trim"][1] if st["trim"][1] is not None else dur)
    segs = [[a, b]]
    for ca, cb, _ in st["cuts"]:
        nxt = []
        for x, y in segs:
            if cb <= x or ca >= y:
                nxt.append([x, y])
                continue
            if ca > x:
                nxt.append([x, ca])
            if cb < y:
                nxt.append([cb, y])
        segs = nxt
    return [[round(x, 3), round(y, 3)] for x, y in segs if y - x > 0.04]


def joins(st, segs):
    """Transitions at cut joins: [{index k (between seg k and k+1), effect id, transition, duration}]."""
    out = {}
    bounds = [(segs[k][1], segs[k + 1][0]) for k in range(len(segs) - 1)]
    for e in st["effects"]:
        if e["effect"] != "xfade-joins":
            continue
        t = float(e["start"])
        best = None
        for k, (ea, sb) in enumerate(bounds):
            dist = 0.0 if ea - 0.05 <= t <= sb + 0.05 else min(abs(t - ea), abs(t - sb))
            if dist <= 0.35 and (best is None or dist < best[1]):
                best = (k, dist)
        if best is not None:
            k = best[0]
            room = min(segs[k][1] - segs[k][0], segs[k + 1][1] - segs[k + 1][0]) * 0.45
            d = round(min(float(e["params"].get("duration") or 0.4), room), 3)
            if d >= 0.05:
                out[k] = dict(index=k, id=e["id"], transition=e["params"].get("transition") or "fade", duration=d)
    return [out[k] for k in sorted(out)]


class Timeline:
    """Source (original output) seconds <-> edited seconds, through trim, cuts, transitions and speed."""

    def __init__(self, st, dur):
        self.segs = segments(st, dur)
        self.joins = joins(st, self.segs)
        jd = {j["index"]: j["duration"] for j in self.joins}
        self.speed = float(st["speed"] or 1.0)
        self.offs, o = [], 0.0
        for k, (a, b) in enumerate(self.segs):
            self.offs.append(o)
            o += (b - a) - jd.get(k, 0.0)
        self.length_src = sum(b - a for a, b in self.segs) - sum(jd.values())
        self.duration = self.length_src / self.speed

    def to_edit(self, t, side="start"):
        """Edited time of source ``t``; inside a cut -> the next kept start (side start) / previous end (end)."""
        for k, (a, b) in enumerate(self.segs):
            if a - 1e-6 <= t <= b + 1e-6:
                return (self.offs[k] + min(max(t, a), b) - a) / self.speed
            if t < a:
                if side == "start":
                    return self.offs[k] / self.speed
                if k == 0:
                    return None
                pa, pb = self.segs[k - 1]
                return (self.offs[k - 1] + pb - pa) / self.speed
        if side == "end" and self.segs:
            a, b = self.segs[-1]
            return (self.offs[-1] + b - a) / self.speed
        return None

    def to_src(self, e):
        x = float(e) * self.speed
        for k, (a, b) in enumerate(self.segs):
            if x <= self.offs[k] + (b - a) + 1e-6 or k == len(self.segs) - 1:
                return round(a + max(0.0, min(b - a, x - self.offs[k])), 3)
        return None

    def span(self, s, e):
        a, b = self.to_edit(s, "start"), self.to_edit(e, "end")
        if a is None or b is None or b - a < 0.04:
            return None
        return a, b

    def as_dict(self):
        return dict(segments=self.segs, joins=self.joins, speed=self.speed, duration=round(self.duration, 3))


# --------------------------------------------------------------------------- transcript (cut snapping)
def _transcriber():
    if TRANSCRIBE is not None:
        return TRANSCRIBE
    ref = os.environ.get("VSTUDIO_OUTPUT_TRANSCRIBER")
    if ref:
        from vstudio.batch.util import import_ref
        fn = import_ref(ref)
        return lambda path, language=None: fn(path, language=language)

    def run(path, language=None):
        from vstudio import asr
        return asr.transcribe(path, language=language, cache=False)
    return run


def words(doc, required=True):
    """Word timings of the output (source seconds), transcribed once per file signature and cached in the edit
    folder (``transcript.json``). -> [{"w","t","te"}] ([] when unavailable and not required)."""
    path = os.path.join(doc.dir, "transcript.json")
    tr = read_json(path, None)
    if isinstance(tr, dict) and tr.get("sig") == doc.d["source_sig"]:
        return tr["words"]
    if not doc.rec["info"]["has_audio"]:
        if required:
            raise _err("no-audio", "the output has no audio: nothing to transcribe", "成片没有音轨，无法转写")
        return []
    try:
        from vstudio.batch.livestatus import write as lw
        lw(doc.dir, "running", stage="transcribe", message=os.path.basename(doc.rec["file"]), by="output-edit")
        raw = _transcriber()(doc.rec["file"], language=None)
    except Exception as e:  # noqa: BLE001
        if required:
            raise _err("transcribe-failed", f"could not transcribe the output: {str(e)[:200]}",
                       "转写失败", error=str(e)[:200]) from e
        return []
    finally:
        from vstudio.batch.livestatus import write as lw
        lw(doc.dir, "done", stage="transcribe", by="output-edit")
    if isinstance(raw, dict):
        from vstudio import asr
        W = asr.words_of(raw)
    else:
        W = [dict(w=str(w["w"]), t=float(w["t"]), te=float(w["te"])) for w in raw or []]
    os.makedirs(doc.dir, exist_ok=True)
    write_json(path, dict(sig=doc.d["source_sig"], file=doc.rec["file"], words=W, at=_stamp()))
    return W


def _energy(doc, W):
    try:
        from vstudio import cleanup as C
        return C.energy_of(doc.rec["file"], W)
    except Exception:  # noqa: BLE001  (whisper times only)
        return None


# --------------------------------------------------------------------------- burned text detection
def burned_text(doc):
    """{captions: bool, band: lower|middle, box [x0,y0,x1,y1] fractions} of the flattened file (cached)."""
    b = doc.d.get("burned")
    if isinstance(b, dict):
        return b
    out = dict(captions=None, band=None, box=None)
    try:
        from vstudio.intake import inventory as I
        old = I.FACES
        I.FACES = lambda img: []
        try:
            fr = I._frames(doc.rec["file"], doc.rec["info"]["duration"], n=6)
            facts = I.visual_facts([I.frame_stats(img) for _, img in fr], doc.rec["info"]["w"], doc.rec["info"]["h"])
        finally:
            I.FACES = old
        out["captions"] = bool(facts.get("burned_captions"))
        out["band"] = facts.get("caption_band")
        if out["captions"]:
            out["box"] = [0.06, 0.70, 0.94, 0.96] if out["band"] == "lower" else [0.06, 0.53, 0.94, 0.77]
    except Exception:  # noqa: BLE001  (no cv2 / unreadable: unknown)
        pass
    doc.d["burned"] = out
    return out


# --------------------------------------------------------------------------- op validation (-> normalized op)
def _num(v, name, code="bad-param"):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise _err(code, f"{name} must be a number, got {v!r}", f"{name} 需要数字", name=name, value=v) from None
    if x != x:
        raise _err(code, f"{name} must be a number", f"{name} 需要数字", name=name, value=v)
    return x


def _src_time(v, name, op, tl, dur):
    t = _num(v, name)
    if op.get("time_base") == "edited":
        t = tl.to_src(t)
    if t < -0.01 or t > dur + 0.01:
        raise _err("bad-time", f"{name}={t:g}s is outside the output (0-{dur:.2f}s)", f"{name} 超出成片范围",
                   name=name, value=round(t, 3), duration=round(dur, 3))
    return round(min(max(t, 0.0), dur), 3)


def _cue_rows(rec, st):
    """The caption list the editor shows: pipeline cues (id = index) + added ones (id a<n>), source seconds."""
    c = st["captions"]
    rows = []
    for i, cue in enumerate(rec.get("cues") or []):
        k = str(i)
        rows.append(dict(id=k, start=cue["start"], end=cue["end"], text=c["overrides"].get(k, cue["text"]),
                         original=cue["text"], edited=k in c["overrides"], removed=k in c["removed"], added=False,
                         kind=cue.get("kind")))
    for a in c["added"]:
        rows.append(dict(id=a["id"], start=a["start"], end=a["end"], text=a["text"], original=None, edited=False,
                         removed=False, added=True, kind=None))
    return rows


CAPTION_STYLE = dict(size={"type": "number", "minimum": 0.6, "maximum": 1.8}, color={"type": "color"},
                     highlight={"type": "color"}, keywords={"type": "array"}, stroke={"type": "number", "minimum": 0,
                                                                                         "maximum": 0.2},
                     stroke_color={"type": "color"}, position={"enum": ["bottom", "middle", "top", "custom"]},
                     y={"type": "number", "minimum": 0.05, "maximum": 0.95},
                     font={"enum": ["cjk-bold", "cjk", "serif"]}, box={"type": "boolean"},
                     box_color={"type": "color"}, max_lines={"type": "number", "minimum": 1, "maximum": 3})
TITLE_KEYS = ("text", "sub", "color", "band_color", "y", "height", "size")


def _color(v, name):
    if v in (None, ""):
        return None
    from vstudio import draw as D
    try:
        D.rgb(v)
    except (ValueError, TypeError):
        raise _err("bad-param", f"{name}: not a colour ({v!r}; use #RRGGBB)", f"{name} 不是颜色", name=name,
                   value=v) from None
    return v if str(v).startswith("#") or isinstance(v, (list, tuple)) else "#" + str(v)


def _style(raw):
    out, warns = {}, []
    for k, v in (raw or {}).items():
        if k not in CAPTION_STYLE:
            warns.append(msg("unknown-param", f"caption style: unknown key {k!r} dropped", f"字幕样式：未知参数 {k}",
                             name=k))
            continue
        d = CAPTION_STYLE[k]
        if v is None:
            out[k] = None
        elif d.get("type") == "color":
            out[k] = _color(v, k)
        elif d.get("type") == "number":
            x = _num(v, k)
            out[k] = min(max(x, d["minimum"]), d["maximum"])
        elif d.get("type") == "array":
            out[k] = [str(x) for x in (v if isinstance(v, (list, tuple)) else re.split(r"[,，|｜]", str(v))) if str(x).strip()]
        elif d.get("type") == "boolean":
            out[k] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
        elif "enum" in d:
            if v not in d["enum"]:
                raise _err("bad-param", f"caption style {k}: one of {', '.join(d['enum'])}", f"字幕样式 {k} 取值无效",
                           name=k, value=v, allowed=d["enum"])
            out[k] = v
    return out, warns


def target_key(t):
    from vstudio import platform as P
    s = str(t or "").strip()
    s = TARGET_ALIASES.get(s, TARGET_ALIASES.get(s.lower(), s))
    try:
        if ":" in s:
            name, ori = s.split(":", 1)
            ori = TARGET_ALIASES.get(ori, ori)
            p = P.profile(name, ori)
        else:
            p = P.profile(s)
    except Exception:  # noqa: BLE001
        raise _err("unknown-target", f"unknown export target {t!r} (platform[:orientation], 3:4, 9:16, 16:9)",
                   f"未知的导出目标 {t!r}", target=t, known=P.list_profiles()) from None
    return f"{p.name}:{p.orientation}"


def _new_id(st, prefix):
    st["seq"] += 1
    return f"{prefix}{st['seq']}", st["seq"]


def normalize(doc, st, op):
    """Validate one op against the output + the current state -> (normalized op, value, warnings). Raises
    OutputError with a code on a refusal. Pure except for cached transcript / detection reads."""
    rec = doc.rec
    if not isinstance(op, dict) or "op" not in op:
        raise _err("bad-op", "an op is an object with an 'op' key", "操作需要 op 字段")
    k = str(op["op"]).strip().lower().replace("-", "_")
    k = {"add_effect": "effect_add", "remove_effect": "effect_remove", "move_effect": "effect_update",
         "effect_move": "effect_update", "update_effect": "effect_update", "uncut": "cut_remove",
         "caption": "caption_text", "add_caption": "caption_add", "export": "export_add", "title_band": "title",
         "subtitle_style": "caption_style"}.get(k, k)
    if k not in OPS:
        raise _err("unknown-op", f"unknown op {op['op']!r}; ops: {', '.join(OPS)}", f"未知操作 {op['op']!r}",
                   op=op["op"], ops=list(OPS))
    dur = rec["info"]["duration"]
    tl = Timeline(st, dur)
    pipe = rec["mode"] == "pipeline"
    warns, value = [], {}
    n = dict(op=k)

    if k == "trim":
        s = op.get("start", st["trim"][0])
        e = op.get("end", st["trim"][1])
        s = _src_time(s, "start", op, tl, dur) if s is not None else None
        e = _src_time(e, "end", op, tl, dur) if e is not None else None
        a, b = (s or 0.0), (e if e is not None else dur)
        W = words(doc, required=False) if op.get("snap", True) else []
        if W and (s or e is not None):
            from vstudio import cleanup as C
            sa, sb = C.snap_range(W, a, b, _energy(doc, W))
            if s is not None:
                s = round(max(0.0, sa), 3)
            if e is not None:
                e = round(min(dur, sb), 3)
            a, b = (s or 0.0), (e if e is not None else dur)
            value["snapped"] = True
        if b - a < MIN_KEEP_S:
            raise _err("too-short", f"only {b - a:.2f}s would be left (at least {MIN_KEEP_S:g}s)",
                       f"只剩 {b - a:.2f} 秒（至少 {MIN_KEEP_S:g} 秒）", kept_s=round(b - a, 3), min_s=MIN_KEEP_S)
        n.update(start=s, end=e)
        value.update(start=s, end=e)
    elif k == "cut":
        s = _src_time(op.get("start"), "start", op, tl, dur)
        e = _src_time(op.get("end"), "end", op, tl, dur)
        if e <= s:
            raise _err("bad-time", "cut: end must be after start", "剪切：结束要晚于开始", start=s, end=e)
        W = words(doc, required=not op.get("no_snap"))
        said = ""
        if W and not op.get("no_snap"):
            from vstudio import cleanup as C
            r = C.snap_cut(W, _energy(doc, W), s, e)
            if not r:
                raise _err("cut-no-word", f"cut {s:g}-{e:g}s holds no whole word", "这个区间里没有完整的词",
                           start=s, end=e)
            s, e = r
            said = C.join_words([w for w in W if s <= (w["t"] + w["te"]) / 2 <= e])
        n.update(start=s, end=e, why=str(op.get("why") or ""))
        test = fold(st, n)
        kept = sum(b - a for a, b in segments(test, dur))
        if kept < MIN_KEEP_S:
            raise _err("too-short", f"only {kept:.2f}s would be left", f"只剩 {kept:.2f} 秒", kept_s=round(kept, 3),
                       min_s=MIN_KEEP_S)
        value.update(cut=[s, e], words=said, snapped=bool(W), kept_s=round(kept, 3))
    elif k == "cut_remove":
        i = int(_num(op.get("index"), "index"))
        if not 0 <= i < len(st["cuts"]):
            raise _err("unknown-cut", f"no cut #{i} (there are {len(st['cuts'])})", f"没有第 {i} 个剪切",
                       index=i, n=len(st["cuts"]))
        n["index"] = i
    elif k == "speed":
        v = _num(op.get("value", op.get("speed")), "value")
        if not 0.5 <= v <= 2.5:
            raise _err("bad-param", f"speed {v:g} outside 0.5-2.5", "倍速需在 0.5-2.5 之间", name="value", value=v)
        n["value"] = round(v, 3)
    elif k == "loudness":
        if not rec["info"]["has_audio"]:
            raise _err("no-audio", "the output has no audio track", "成片没有音轨")
        lufs = op.get("lufs", op.get("value"))
        n["lufs"] = None if lufs is None else min(-8.0, max(-30.0, _num(lufs, "lufs")))
        n["tp"] = None if op.get("tp") is None else min(-0.1, max(-6.0, _num(op["tp"], "tp")))
    elif k == "captions":
        if not pipe:
            raise _err("captions-not-ours", "the burned-in captions of a flattened output cannot be switched off "
                       "(add captions over a mask instead)", "成片的烧录字幕不能关闭（可以用遮罩盖住再加新字幕）")
        n["enabled"] = bool(op.get("enabled", True))
    elif k in ("caption_text", "caption_remove"):
        cue = str(op.get("cue", op.get("id", "")))
        rows = {r["id"]: r for r in _cue_rows(rec, st)}
        if cue not in rows:
            raise _err("unknown-cue", f"no caption {cue!r}", f"没有字幕 {cue}", cue=cue)
        if not pipe and not cue.startswith("a"):
            raise _err("captions-not-ours", "burned-in captions cannot be edited", "烧录字幕不能修改")
        n["cue"] = cue
        if k == "caption_text":
            text = str(op.get("text") or "").strip()
            if not text:
                raise _err("empty-text", "caption text is empty (use caption_remove)", "字幕不能为空")
            if not cue.startswith("a") and not op.get("force"):
                from vstudio import proofread
                why = proofread.faithful(rows[cue]["original"], text)
                if why:
                    raise _err("not-faithful", f"the new caption no longer says what was said ({why}); pass "
                               "force=true to keep it anyway", "新字幕和原话不一致（可用 force=true 强制）",
                               cue=cue, reason=why)
            n["text"] = text
            value["from"] = rows[cue]["text"]
    elif k == "caption_style":
        sty, w = _style(op.get("style") or {x: v for x, v in op.items() if x not in ("op", "time_base")})
        warns += w
        if not sty:
            raise _err("bad-param", "caption_style needs style keys", "字幕样式没有参数", allowed=list(CAPTION_STYLE))
        if not pipe:
            warns.append(msg("style-added-only", "style applies to the added captions only (burned-in text keeps "
                             "its look)", "样式只作用于新增字幕"))
        n["style"] = sty
    elif k == "caption_add":
        cues = []
        if op.get("from_transcript"):
            s = _src_time(op.get("start", 0.0), "start", op, tl, dur)
            e = _src_time(op.get("end", dur), "end", op, tl, dur)
            W = [w for w in words(doc) if s <= (w["t"] + w["te"]) / 2 <= e]
            if not W:
                raise _err("no-words", "no speech in that range", "这段没有语音")
            from vstudio import subs
            for c in subs.cues_from_words(W, max_chars=int(op.get("max_chars") or 14)):
                cues.append(dict(start=round(c.start, 3), end=round(c.end, 3), text=c.text))
        else:
            text = str(op.get("text") or "").strip()
            if not text:
                raise _err("empty-text", "caption text is empty", "字幕不能为空")
            s = _src_time(op.get("start"), "start", op, tl, dur)
            e = _src_time(op.get("end"), "end", op, tl, dur)
            if e - s < 0.2:
                raise _err("bad-time", "a caption needs at least 0.2s", "字幕至少 0.2 秒", start=s, end=e)
            cues.append(dict(start=s, end=e, text=text))
        tmp = dict(st)
        for c in cues:
            c["id"], n["seq"] = _new_id(tmp, "a")
        n["cues"] = cues
        if not pipe and not (st["captions"].get("placement") or {}).get("mode") in ("band", "mask"):
            b = burned_text(doc)
            n["placement"] = dict(mode="mask", box=b.get("box") or [0.06, 0.74, 0.94, 0.92], style="blur")
            warns.append(msg("placement-auto", "flattened output: the new captions sit on a mask over the lower "
                             "band (caption_placement changes it)", "新字幕放在下方遮罩上（可用 caption_placement 修改）",
                             box=n["placement"]["box"]))
        value["ids"] = [c["id"] for c in cues]
    elif k == "caption_placement":
        if pipe:
            raise _err("placement-pipeline", "captions of a pipeline output are placed in the platform caption box "
                       "(use caption_style position)", "母版成片的字幕位置用 caption_style 的 position 调整")
        mode = str(op.get("mode") or "mask")
        if mode not in ("band", "mask", "none"):
            raise _err("bad-param", "placement mode: band | mask | none", "布局只能是 band / mask / none",
                       name="mode", value=mode)
        pl = dict(mode=mode)
        if mode == "mask":
            box = op.get("box") or (burned_text(doc).get("box")) or [0.06, 0.74, 0.94, 0.92]
            box = [min(1.0, max(0.0, _num(x, "box"))) for x in box][:4]
            if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
                raise _err("bad-param", "box: [x0, y0, x1, y1] fractions", "box 需要 [x0, y0, x1, y1]", name="box")
            pl.update(box=box, style=op.get("style") if op.get("style") in ("blur", "solid") else "blur",
                      always=bool(op.get("always", True)))
        elif mode == "band":
            pl["band"] = min(0.35, max(0.1, _num(op.get("band", 0.2), "band")))
        n["placement"] = pl
    elif k == "title":
        t = {x: op[x] for x in TITLE_KEYS if x in op}
        if not str(t.get("text") or "").strip():
            n["title"] = None
        else:
            for c in ("color", "band_color"):
                if c in t:
                    t[c] = _color(t[c], c)
            for x, lo, hi in (("y", 0.0, 0.9), ("height", 0.05, 0.3), ("size", 0.5, 2.0)):
                if x in t:
                    t[x] = min(hi, max(lo, _num(t[x], x)))
            n["title"] = t
    elif k == "effect_add":
        eid = FX.resolve(op.get("effect"))
        if not eid:
            raise _err("unknown-effect", f"unknown effect {op.get('effect')!r} (output effects --json)",
                       f"未知特效 {op.get('effect')!r}", effect=op.get("effect"), known=list(FX.SPECS))
        sp = FX.SPECS[eid]
        try:
            params, w = FX.validate(eid, op.get("params") or {})
        except ValueError as e:
            raise _err("bad-param", str(e), f"特效参数无效：{e}", effect=eid) from None
        warns += [msg("param-adjusted", x, x, effect=eid) for x in w]
        whole = sp["default_dur"] is None
        s = _src_time(op.get("start", 0.0 if whole else None), "start", op, tl, dur) \
            if (op.get("start") is not None or whole) else None
        if s is None:
            raise _err("bad-time", f"{eid}: start is required", f"{sp['zh']} 需要开始时间", effect=eid)
        if op.get("end") is not None:
            e = _src_time(op["end"], "end", op, tl, dur)
        elif op.get("duration") is not None:
            e = min(dur, s + _num(op["duration"], "duration") * (tl.speed if op.get("time_base") == "edited" else 1))
        else:
            e = dur if whole else min(dur, s + float(sp["default_dur"]))
        if e - s < 0.05 and sp["kind"] not in ("audio", "join"):
            raise _err("bad-time", f"{eid}: end must be after start", "结束要晚于开始", effect=eid, start=s, end=e)
        if eid in ("end-fade", "vlog-grade", "music-bed", "progress-bar-pil") and \
                any(x["effect"] == eid for x in st["effects"]):
            raise _err("duplicate-effect", f"{eid} is already on this output (effect_update changes it)",
                       f"{sp['zh']} 已经有了（用 effect_update 修改）", effect=eid)
        tmp = dict(seq=st["seq"])
        iid, n["seq"] = _new_id(tmp, "fx")
        n.update(id=op.get("id") if op.get("id") and not any(x["id"] == op["id"] for x in st["effects"]) else iid,
                 effect=eid, start=round(s, 3), end=round(max(e, s), 3), params=params)
        if sp["kind"] in ("overlay", "camera", "fullframe", "box") and not tl.span(s, max(e, s)):
            warns.append(msg("effect-cut-away", f"{eid} at {s:g}s falls inside a cut: it will not show",
                             f"{sp['zh']} 在被剪掉的部分里，不会显示", effect=eid, start=s))
        value["id"] = n["id"]
    elif k in ("effect_remove", "effect_update"):
        iid = str(op.get("id") or "")
        cur = next((x for x in st["effects"] if x["id"] == iid), None)
        if not cur:
            raise _err("unknown-effect-instance", f"no effect instance {iid!r}", f"没有特效 {iid}", id=iid,
                       known=[x["id"] for x in st["effects"]])
        n["id"] = iid
        if k == "effect_update":
            s, e = cur["start"], cur["end"]
            if op.get("shift") is not None:
                d = _num(op["shift"], "shift")
                s, e = max(0.0, s + d), min(dur, e + d)
            if op.get("start") is not None:
                s = _src_time(op["start"], "start", op, tl, dur)
                if op.get("end") is None and op.get("duration") is None:
                    e = min(dur, s + (cur["end"] - cur["start"]))
            if op.get("end") is not None:
                e = _src_time(op["end"], "end", op, tl, dur)
            if op.get("duration") is not None:
                e = min(dur, s + _num(op["duration"], "duration"))
            if e < s:
                raise _err("bad-time", "end must be after start", "结束要晚于开始", start=s, end=e)
            patch, w = FX.validate(cur["effect"], op.get("params") or {}, partial=True)
            warns += [msg("param-adjusted", x, x, effect=cur["effect"]) for x in w]
            params = dict(cur["params"], **patch)
            try:
                params, _ = FX.validate(cur["effect"], params)
            except ValueError as ex:
                raise _err("bad-param", str(ex), f"特效参数无效：{ex}", effect=cur["effect"]) from None
            n.update(start=round(s, 3), end=round(e, 3), params=params)
    elif k == "cover":
        if op.get("clear"):
            n["cover"] = None
        else:
            t = _src_time(op.get("t", (st["trim"][0] or 0.0) + 0.5), "t", op, tl, dur)
            style = op.get("style") or "card"
            if style not in ("card", "plain", "band"):
                raise _err("bad-param", "cover style: card | plain | band", "封面样式：card / plain / band",
                           name="style", value=style)
            n["cover"] = dict(t=t, text=str(op.get("text") or ""), style=style)
    elif k in ("export_add", "export_remove"):
        tk = target_key(op.get("target") or op.get("platform"))
        n["target"] = tk
        if k == "export_add":
            lay = op.get("layout") or "auto"
            if lay not in ("auto", "band"):
                raise _err("bad-param", "layout: auto | band", "布局：auto / band", name="layout", value=lay)
            if lay == "band" and pipe:
                warns.append(msg("band-pipeline", "a pipeline output re-lays out from the master; band is not needed",
                                 "母版成片直接重新构图，不需要 band"))
                lay = "auto"
            n["layout"] = lay
            if not pipe and lay == "auto" and (burned_text(doc).get("captions")):
                warns.append(msg("relayout-crops-burned", "burned captions may be cropped by the re-layout; "
                                 "layout band keeps the whole frame", "换比例可能裁掉烧录字幕，band 布局可保留整幅画面",
                                 target=tk))
        elif not any(x["target"] == tk for x in st["exports"]):
            raise _err("unknown-target", f"{tk} is not in this output's exports", f"导出里没有 {tk}", target=tk)
    elif k == "reset":
        pass
    return n, value, warns


def describe(op):
    """A short {code, params, message, message_zh} line for a normalized op (history, AI proposals)."""
    k = op["op"]
    if k == "trim":
        return msg("op-trim", f"trim to {op.get('start') or 0:g}s - {op.get('end') if op.get('end') is not None else 'end'}",
                   "裁剪首尾", start=op.get("start"), end=op.get("end"))
    if k == "cut":
        return msg("op-cut", f"cut {op['start']:g}-{op['end']:g}s", f"剪掉 {op['start']:g}-{op['end']:g} 秒",
                   start=op["start"], end=op["end"])
    if k == "speed":
        return msg("op-speed", f"speed {op['value']:g}x", f"{op['value']:g} 倍速", value=op["value"])
    if k == "effect_add":
        s = FX.SPECS[op["effect"]]
        return msg("op-effect-add", f"add {s['en']} at {op['start']:g}s", f"在 {op['start']:g} 秒加{s['zh']}",
                   effect=op["effect"], start=op["start"], end=op["end"])
    if k == "export_add":
        return msg("op-export-add", f"export {op['target']}", f"导出 {op['target']}", target=op["target"])
    if k == "caption_add":
        return msg("op-caption-add", f"add {len(op['cues'])} caption(s)", f"新增 {len(op['cues'])} 条字幕",
                   n=len(op["cues"]))
    if k == "revert":
        return msg("op-revert", f"revert step {op['step']}", "撤销了其中一步", step=op["step"])
    if k == "title":
        return msg("op-title", "set the title band" if op.get("title") else "remove the title band",
                   "设置标题条" if op.get("title") else "去掉标题条", text=(op.get("title") or {}).get("text"))
    return msg(f"op-{k.replace('_', '-')}", k.replace("_", " "), None,
               **{x: v for x, v in op.items() if x not in ("op", "params", "cues") and not isinstance(v, (dict, list))})


# --------------------------------------------------------------------------- public API
def _load(d, output):
    rec = resolve(d, output)
    return rec, Doc(rec)


def apply_ops(doc, ops, by="user", note=None, dry=False):
    """Normalize every op in order against the evolving state (all or nothing) -> (step, values, warnings)."""
    st = doc.state()
    normed, values, warns = [], [], []
    for i, op in enumerate(ops):
        try:
            n, v, w = normalize(doc, st, op)
        except OutputError as e:
            e.info["params"] = dict(e.info["params"], index=i)
            raise
        st = fold(st, n)
        normed.append(n)
        values.append(v)
        warns += w
    step = dict(id=f"s{len(doc.d['steps']) + 1}-{sha1_json([normed, time.time()], 6)}", at=_stamp(), by=by,
                note=note, ops=normed, describe=[describe(n) for n in normed])
    if not dry:
        doc.d["steps"].append(step)
        doc.d["redo"] = []
        doc.save()
    return step, values, warns


def edit(d, output, ops, by="user", note=None, turn=None):
    """Apply ops as one undo step. ``turn``: the chat turn (``ai`` proposal) these ops come from; it is marked
    applied with the new step id, so the transcript knows which card made which step."""
    rec, doc = _load(d, output)
    if isinstance(ops, dict):
        ops = [ops]
    if not ops:
        raise _err("no-ops", "nothing to apply", "没有操作")
    if turn is not None and not _find_turn(doc, turn):
        raise _err("unknown-turn", f"no chat turn {turn!r}", f"没有这条对话 {turn!r}", turn=turn)
    step, values, warns = apply_ops(doc, ops, by=by, note=note)
    if turn is not None:
        chat_update(d, output, turn, dict(status="applied", applied_step=step["id"], applied_ops=len(ops)), _doc=doc)
    out = show_doc(rec, doc)
    out.update(ok=True, step=step, values=values, warnings=warns + out.get("warnings", []))
    return out


def undo(d, output):
    rec, doc = _load(d, output)
    if not doc.d["steps"]:
        raise _err("nothing-to-undo", "nothing to undo", "没有可撤销的编辑")
    s = doc.d["steps"].pop()
    doc.d["redo"].append(s)
    doc.save()
    out = show_doc(rec, doc)
    out.update(ok=True, undone=s)
    return out


def redo(d, output):
    rec, doc = _load(d, output)
    if not doc.d["redo"]:
        raise _err("nothing-to-redo", "nothing to redo", "没有可重做的编辑")
    s = doc.d["redo"].pop()
    doc.d["steps"].append(s)
    doc.save()
    out = show_doc(rec, doc)
    out.update(ok=True, redone=s)
    return out


def _ids_made(op):
    if op["op"] == "effect_add":
        return {op["id"]}
    if op["op"] == "caption_add":
        return {c["id"] for c in op.get("cues") or []}
    return set()


def _ids_used(op):
    if op["op"] in ("effect_update", "effect_remove"):
        return {op.get("id")}
    if op["op"] in ("caption_text", "caption_remove"):
        return {op.get("cue")}
    return set()


def revert(d, output, step_id, note=None, by="user"):
    """Cancel ONE earlier step without touching the steps after it: a new step ``{op: revert, step}`` is recorded
    (undo / redo it like any step) and the state is re-folded without the cancelled step. Refused with
    ``revert-conflict`` when a later step builds on it (edits an effect / caption it added, removes a cut by index
    after it changed the cut list, or a later reset makes it moot): then only 「回到这一步」 (undo N) is honest."""
    rec, doc = _load(d, output)
    steps = doc.d["steps"]
    k = next((i for i, x in enumerate(steps) if x["id"] == step_id), None)
    if k is None:
        raise _err("unknown-step", f"no step {step_id!r} in the history", f"历史里没有这一步 {step_id!r}",
                   step=step_id)
    target = steps[k]
    dead = reverted_ids(steps)
    if step_id in dead:
        raise _err("already-reverted", "that step is already reverted", "这一步已经撤销过了", step=step_id)
    later = [x for x in steps[k + 1:] if x["id"] not in dead and not x.get("revert_of")]
    made = set().union(*[_ids_made(o) for o in target["ops"]]) if target["ops"] else set()
    cuts = any(o["op"] in ("cut", "cut_remove") for o in target["ops"])
    blockers = []
    for x in later:
        for o in x["ops"]:
            if (_ids_used(o) & made) or (cuts and o["op"] == "cut_remove") or o["op"] == "reset":
                blockers.append(x["id"])
                break
    if blockers:
        raise _err("revert-conflict", f"later step(s) {', '.join(blockers)} build on {step_id}: undo back to it "
                   "instead", f"后面有 {len(blockers)} 步依赖这一步，只能「回到这一步」", step=step_id,
                   steps=blockers, n=len(blockers))
    op = dict(op="revert", step=step_id)
    d_ = describe(op)
    d_["params"]["what"] = [m.get("message") for m in (target.get("describe") or [])][:3]
    st = dict(id=f"s{len(steps) + 1}-{sha1_json([op, time.time()], 6)}", at=_stamp(), by=by, note=note, ops=[op],
              describe=[d_], revert_of=step_id)
    steps.append(st)
    doc.d["redo"] = []
    doc.save()
    _chat_mark_reverted(doc, step_id, st["id"])
    out = show_doc(rec, doc)
    out.update(ok=True, step=st, reverted=step_id)
    return out


# --------------------------------------------------------------------------- chat transcript (per output)
CHAT_VERSION = 1
TURN_STATUS = ("draft", "applied", "discarded", "reverted", "note")


def _chat_path(doc):
    return os.path.join(doc.dir, "chat.json")


def _chat_load(doc):
    c = read_json(_chat_path(doc), None)
    if not isinstance(c, dict) or c.get("version") != CHAT_VERSION or not isinstance(c.get("turns"), list):
        c = dict(version=CHAT_VERSION, output=doc.rec["id"], turns=[])
    return c


def _chat_save(doc, c):
    os.makedirs(doc.dir, exist_ok=True)
    c["updated"] = _stamp()
    write_json(_chat_path(doc), c)


def _find_turn(doc, turn_id):
    return next((x for x in _chat_load(doc)["turns"] if x.get("id") == turn_id), None)


def _clean_turn(t):
    """Only JSON-safe, bounded fields go into the transcript (it is the creator's history, not a log dump)."""
    keep = ("text", "context", "proposed", "dropped", "summary", "provider", "model", "cost_usd", "seconds",
            "warnings", "status", "applied_step", "applied_ops", "reverted_by", "role", "card", "reply")
    out = {k: t[k] for k in keep if k in t}
    if isinstance(out.get("text"), str):
        out["text"] = out["text"][:2000]
    if "status" in out and out["status"] not in TURN_STATUS:
        raise _err("bad-param", f"status: {' | '.join(TURN_STATUS)}", "状态不对", name="status", value=out["status"])
    return out


def chat(d, output):
    """The output's chat transcript: {ok, turns [{id, at, role, text, context, proposed, dropped, summary, provider,
    model, cost_usd, status draft|applied|discarded|reverted|note, applied_step, reverted_by}]}."""
    rec, doc = _load(d, output)
    return dict(ok=True, output=rec["id"], turns=_chat_load(doc)["turns"], path=_chat_path(doc))


def chat_add(d, output, turn, _doc=None):
    """Append one turn (the desk records its own cards: slash-command cards, notes). -> {ok, turn}."""
    if not isinstance(turn, dict):
        raise _err("bad-param", "a turn is an object", "对话需要是对象", name="turn")
    doc = _doc or _load(d, output)[1]
    c = _chat_load(doc)
    t = dict(_clean_turn(turn), id=f"t{len(c['turns']) + 1}-{sha1_json([turn, time.time()], 4)}", at=_stamp())
    t.setdefault("role", "user")
    t.setdefault("status", "note")
    c["turns"].append(t)
    c["turns"] = c["turns"][-500:]
    _chat_save(doc, c)
    return dict(ok=True, turn=t)


def chat_update(d, output, turn_id, patch, _doc=None):
    """Patch one turn (status, applied_step, ...). -> {ok, turn}."""
    if not isinstance(patch, dict):
        raise _err("bad-param", "the patch is an object", "需要对象", name="set")
    doc = _doc or _load(d, output)[1]
    c = _chat_load(doc)
    for t in c["turns"]:
        if t.get("id") == turn_id:
            t.update(_clean_turn(patch))
            t["updated"] = _stamp()
            _chat_save(doc, c)
            return dict(ok=True, turn=t)
    raise _err("unknown-turn", f"no chat turn {turn_id!r}", f"没有这条对话 {turn_id!r}", turn=turn_id)


def _chat_mark_reverted(doc, step_id, by_step):
    c = _chat_load(doc)
    hit = False
    for t in c["turns"]:
        if t.get("applied_step") == step_id:
            t.update(status="reverted", reverted_by=by_step, updated=_stamp())
            hit = True
    if hit:
        _chat_save(doc, c)


def show(d, output):
    rec, doc = _load(d, output)
    out = show_doc(rec, doc)
    out["ok"] = True
    return out


def show_doc(rec, doc):
    st = doc.state()
    dead = reverted_ids(doc.d["steps"])
    caps, notes = capabilities(rec, doc.d if rec["mode"] == "flattened" else None)
    tl = Timeline(st, rec["info"]["duration"])
    from . import outrender as R
    try:
        renders = R.render_status(rec, doc, st)
    except Exception as e:  # noqa: BLE001
        renders = dict(error=str(e)[:200])
    effects = []
    for e in st["effects"]:
        sp = FX.SPECS[e["effect"]]
        span = tl.span(e["start"], e["end"]) if sp["kind"] not in ("audio", "join", "look", "end") else None
        effects.append(dict(e, label=dict(en=sp["en"], zh=sp["zh"]), kind=sp["kind"], stage=sp["stage"],
                            edited=list(span) if span else None))
    prof = rec.get("profile")
    out = dict(output=dict(id=rec["id"], file=rec["file"], title=rec.get("title"), owner=rec["owner"], kind=rec["kind"],
                           mode=rec["mode"], canvas=[rec["info"]["w"], rec["info"]["h"]], fps=rec["info"]["fps"],
                           duration=round(rec["info"]["duration"], 3), has_audio=rec["info"]["has_audio"],
                           platform=rec.get("platform") or (f"{prof.name}:{prof.orientation}" if prof else None),
                           master=rec.get("master")),
               caps=caps, caps_notes=notes, state=st, captions=_cue_rows(rec, st) if (rec["cues"] or
                                                                                      st["captions"]["added"]) else [],
               effects=effects, timeline=tl.as_dict(),
               history=dict(steps=[dict(id=s["id"], at=s["at"], by=s.get("by"), note=s.get("note"),
                                        describe=s.get("describe") or [describe(o) for o in s["ops"]],
                                        reverted=s["id"] in dead, revert_of=s.get("revert_of"))
                                   for s in doc.d["steps"]], undo=len(doc.d["steps"]), redo=len(doc.d["redo"])),
               chat=_chat_load(doc)["turns"],
               renders=renders, warnings=list(doc.d.get("warnings") or []),
               paths=dict(doc=doc.path, dir=doc.dir, renders=os.path.join(doc.dir, "renders")))
    return out


# --------------------------------------------------------------------------- AI: instruction -> ops
AI_SYSTEM = """You edit ONE finished short video by proposing edit operations as JSON. You never render anything.
Rules:
- Use only the ops listed and only effect ids from the effect catalogue (never invent an effect, op or param).
- Times are seconds on the ORIGINAL output timeline (the transcript / captions below use it).
- Positions are fractions of the canvas (x, y = centre, 0..1). Keep text short and in the content's language.
- Respect the capability flags (e.g. a flattened output cannot restyle or edit burned-in captions).
- Prefer few, purposeful ops; do not repeat existing effects.
Return {"ops": [{"op": ..., ...}], "summary": "<one sentence, English>"}."""

OP_DOC = {
    "trim": "{op, start?, end?} keep only this source range",
    "cut": "{op, start, end, why?} remove an inner range (snapped to whole words)",
    "speed": "{op, value} 0.5-2.5",
    "loudness": "{op, lufs} e.g. -14",
    "captions": "{op, enabled} pipeline only",
    "caption_text": "{op, cue, text} pipeline cues only; must say what was said",
    "caption_style": "{op, style: {size 0.6-1.8, color, highlight, keywords [..], position bottom|middle|top, font}}",
    "caption_add": "{op, start, end, text} or {op, from_transcript: true, start?, end?}",
    "caption_remove": "{op, cue}",
    "title": "{op, text, sub?} title band at the top ('' removes it)",
    "effect_add": "{op, effect, start, end?, params {..}}",
    "effect_remove": "{op, id}",
    "effect_update": "{op, id, start?, end?, shift?, params?}",
    "cover": "{op, t, text, style card|plain|band}",
    "export_add": "{op, target: platform[:orientation] | 3:4 | 9:16 | 16:9, layout?: auto|band}",
}


def _ai_context(rec, doc, st, use_asr=True):
    caps, _ = capabilities(rec, doc.d if rec["mode"] == "flattened" else None)
    lines = []
    rows = _cue_rows(rec, st)
    if rows:
        lines = [f"[{r['id']}] {r['start']:.2f}-{r['end']:.2f} {r['text']}" for r in rows if not r["removed"]][:400]
    else:
        W = words(doc, required=False) if use_asr else []
        if not W:
            tr = read_json(os.path.join(doc.dir, "transcript.json"), None)
            W = (tr or {}).get("words") or []
        if W:
            from vstudio import subs
            lines = [f"{c.start:.2f}-{c.end:.2f} {c.text}" for c in subs.cues_from_words(W, max_chars=24)][:400]
    fx = [dict(id=r["id"], zh=r["label"]["zh"], en=r["label"]["en"], what=r["description"]["en"],
               stage=r["stage"], params={p: {kk: vv for kk, vv in d.items() if kk in ("type", "default", "enum",
                                                                                     "minimum", "maximum",
                                                                                     "required")}
                                         for p, d in r["params"].items()})
          for r in FX.catalogue()]
    return dict(output=dict(duration=round(rec["info"]["duration"], 2), canvas=[rec["info"]["w"], rec["info"]["h"]],
                            mode=rec["mode"], platform=rec.get("platform")),
                caps=caps, state=dict(trim=st["trim"], cuts=st["cuts"], speed=st["speed"], title=st["title"],
                                      effects=[dict(id=e["id"], effect=e["effect"], start=e["start"], end=e["end"])
                                               for e in st["effects"]], exports=st["exports"],
                                      caption_style=st["captions"]["style"]),
                ops=OP_DOC, effects=fx, transcript=lines)


def check_context(ctx, rec, st):
    """``ai --context``: what the creator is pointing at -> a clean dict {range [a, b], cues [..], effect} (seconds on
    the original timeline). Refusals: ``bad-context`` (shape / range), ``unknown-effect-instance``."""
    if ctx in (None, "", {}):
        return None
    if not isinstance(ctx, dict):
        raise _err("bad-context", "context is an object {range, cues, effect}", "上下文需要 {range, cues, effect}")
    out = {}
    dur = rec["info"]["duration"]
    if ctx.get("range") is not None:
        r = ctx["range"]
        if not (isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(x, (int, float)) and
                                                                   not isinstance(x, bool) for x in r)):
            raise _err("bad-context", "range is [start, end] in seconds", "range 需要 [开始, 结束] 秒", name="range")
        a, b = float(r[0]), float(r[1])
        if not (0 <= a < b <= dur + 0.5):
            raise _err("bad-context", f"range {a:g}-{b:g}s is outside the clip (0-{dur:.1f}s)",
                       f"选区 {a:g}-{b:g} 秒超出片长", name="range", start=a, end=b, duration=round(dur, 2))
        out["range"] = [round(a, 3), round(min(b, dur), 3)]
    if ctx.get("cues") is not None:
        cs = ctx["cues"]
        if not (isinstance(cs, list) and len(cs) <= 50 and all(isinstance(x, (str, int)) for x in cs)):
            raise _err("bad-context", "cues is a list of cue ids", "cues 需要字幕 id 列表", name="cues")
        out["cues"] = [str(x) for x in cs]
    if ctx.get("effect") is not None:
        fid = ctx["effect"]
        if not any(e["id"] == fid for e in st["effects"]):
            raise _err("unknown-effect-instance", f"no effect {fid!r} on this output", f"没有这个效果 {fid!r}",
                       id=fid)
        out["effect"] = fid
    return out or None


def _focus(rec, st, ctx):
    """The context spelled out for the model: the selected words / cues / the effect instance."""
    f = dict(ctx)
    if ctx.get("cues"):
        rows = {r["id"]: r for r in _cue_rows(rec, st)}
        f["cue_rows"] = [dict(id=c, start=rows[c]["start"], end=rows[c]["end"], text=rows[c]["text"])
                         for c in ctx["cues"] if c in rows]
    if ctx.get("effect"):
        f["effect_instance"] = next(e for e in st["effects"] if e["id"] == ctx["effect"])
    return f


def _rule_ops(text, dur, ctx=None):
    """Offline fallback (no model configured): a few literal phrases -> ops (``ctx``: the selection they refer to)."""
    ops = []
    rng = (ctx or {}).get("range")
    if rng and re.search(r"剪掉|删掉|去掉|cut|remove|delete", text, re.I) and \
            re.search(r"这段|这里|这部分|选中|this|it\b|selection|here", text, re.I):
        ops.append(dict(op="cut", start=rng[0], end=rng[1]))
    if rng and re.search(r"推镜|放大|zoom", text, re.I):
        ops.append(dict(op="effect_add", effect="punch-in", start=rng[0], end=rng[1]))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:倍速?|x\b|×)", text, re.I)
    if m:
        ops.append(dict(op="speed", value=float(m.group(1))))
    m = re.search(r"(?:去掉|剪掉|删掉|cut)\s*(?:开头|前|the first)\s*(\d+(?:\.\d+)?)\s*(?:秒|s)", text, re.I)
    if m:
        ops.append(dict(op="trim", start=float(m.group(1))))
    m = re.search(r"(?:去掉|剪掉|删掉|cut)\s*(?:结尾|最后|the last)\s*(\d+(?:\.\d+)?)\s*(?:秒|s)", text, re.I)
    if m:
        ops.append(dict(op="trim", end=max(0.0, dur - float(m.group(1)))))
    for word, tgt in (("小红书", "xiaohongshu:vertical"), ("抖音", "douyin:vertical"), ("b站", "bilibili:horizontal"),
                      ("youtube", "youtube:horizontal"), ("视频号", "douyin:vertical"), ("3:4", "xiaohongshu:vertical"),
                      ("9:16", "douyin:vertical"), ("16:9", "youtube:horizontal")):
        if word in text.lower() and re.search(r"导出|export|发|版本|做一个|出一版", text, re.I):
            ops.append(dict(op="export_add", target=tgt))
    if re.search(r"进度条|progress bar", text, re.I):
        ops.append(dict(op="effect_add", effect="progress-bar-pil", start=0))
    if re.search(r"淡出|fade out", text, re.I):
        ops.append(dict(op="effect_add", effect="end-fade", start=0))
    m = re.search(r"(-\d+(?:\.\d+)?)\s*LUFS", text, re.I)
    if m:
        ops.append(dict(op="loudness", lufs=float(m.group(1))))
    seen, out = set(), []
    for o in ops:
        key = sha1_json(o)
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def ai(d, output, instruction, apply=False, provider=None, model=None, use_asr=True, context=None, record=True,
       timeout=None):
    """Natural language -> validated ops (task ``output_edit`` of vstudio.llm). Every proposed op is checked by the
    same validator as ``edit``; unknown ops / effects / params are dropped with a reason, never invented.
    -> {ok, proposed [{op, describe}], dropped [{op, error}], summary, provider, model, cost_usd, applied?}."""
    from vstudio import llm
    rec, doc = _load(d, output)
    st = doc.state()
    focus = check_context(context, rec, st)
    ctx = _ai_context(rec, doc, st, use_asr=use_asr)
    if focus:
        ctx["focus"] = _focus(rec, st, focus)
    route = llm.route("output_edit", provider, model)
    t0 = time.time()
    warns, raw_ops, summary, cost, used = [], [], None, 0.0, dict(provider=route.provider, model=route.model)
    if route.provider == "none":
        raw_ops = _rule_ops(instruction, rec["info"]["duration"], focus)
        used = dict(provider="rules", model=None)
        warns.append(msg("no-model", "no model is configured for task output_edit: only literal phrases were "
                         "understood (persona llm.tasks.output_edit or llm.default)",
                         "没有配置 output_edit 模型，只理解了字面指令"))
    else:
        import json as _json
        point = ""
        if focus:
            point = ("\n\nThe creator is pointing at `focus` in the context (a selected range of the timeline, caption "
                     "cues and / or one effect instance). Words like this / here / it / 这段 / 这里 / 这个 mean the "
                     "focus: change only that part (an effect in focus: effect_update that id) unless the "
                     "instruction clearly says otherwise.")
        prompt = (f"Instruction from the creator:\n{instruction}{point}\n\nContext (JSON):\n"
                  + _json.dumps(ctx, ensure_ascii=False, default=str))
        schema = {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}},
                                                   "summary": {"type": "string"}}, "required": ["ops"]}
        try:
            ct = timeout if timeout is not None else (None if os.environ.get("VSTUDIO_LLM_CLI_TIMEOUT")
                                                      else AI_CLI_TIMEOUT)
            r = llm.complete("output_edit", AI_SYSTEM, prompt, schema=schema, provider=provider, model=model,
                             max_tokens=6000, cli_timeout=ct)
        except Exception as e:  # noqa: BLE001
            raise llm_failed(e, route.provider) from e
        j = r.get("json") or {}
        raw_ops = j.get("ops") if isinstance(j, dict) else None
        if not isinstance(raw_ops, list):
            raise _err("llm-bad-json", "the model did not return {ops: [...]}", "模型没有返回 ops 列表",
                       provider=r["provider"])
        summary = j.get("summary")
        cost = r.get("cost_usd") or 0.0
        used = dict(provider=r["provider"], model=r["model"], routed=route.provider, fallback=r.get("fallback"))
    proposed, dropped = [], []
    cur = st
    for op in raw_ops:
        if not isinstance(op, dict):
            dropped.append(dict(op=op, error=msg("bad-op", "not an object", "不是对象")))
            continue
        clean = {k: v for k, v in op.items() if k not in ("why", "reason", "description")}
        try:
            n, _, w = normalize(doc, cur, clean)
        except OutputError as e:
            dropped.append(dict(op=op, error=e.info))
            continue
        cur = fold(cur, n)
        proposed.append(dict(op=clean, normalized=n, describe=describe(n), why=op.get("why") or op.get("reason"),
                             warnings=w))
    out = dict(ok=True, instruction=instruction, context=focus, proposed=proposed, ops=[p["op"] for p in proposed],
               dropped=dropped, summary=summary, warnings=warns, cost_usd=cost, seconds=round(time.time() - t0, 2),
               **used)
    turn = None
    if record:
        turn = chat_add(d, output, dict(role="ai", text=instruction, context=focus, summary=summary,
                                        proposed=[dict(op=p["normalized"], describe=p["describe"], why=p["why"])
                                                  for p in proposed],
                                        dropped=[dict(error=x["error"]) for x in dropped], warnings=warns,
                                        provider=used.get("provider"), model=used.get("model"), cost_usd=cost,
                                        seconds=out["seconds"], status="draft" if proposed else "note"),
                        _doc=doc)["turn"]
        out["turn"] = turn["id"]
    if apply and proposed:
        res = edit(d, output, [p["op"] for p in proposed], by="ai", note=instruction,
                   turn=turn["id"] if turn else None)
        out.update(applied=True, step=res["step"], show=res)
    else:
        out["applied"] = False
    return out
