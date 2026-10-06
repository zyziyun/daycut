"""Recipe ``longform-split``: screen-share lecture slices in the longform-to-short split layout, per batch job.

Each job (one row of the job list: source range, ``cuts``, ``title``, ``chapter``, ``hook``, ``notes``, ``tags``,
``platforms``) runs through the vertical pipeline of ``workflows/longform-to-short`` instead of
``vstudio.export``'s generic reframe: title / speaker band on top, a content-following screen crop below that
zooms until a text line is readable (``screen.min_text_px``), chapter card, 记笔记 panel (the row's ``notes``),
captions in each platform's caption box, the per-episode cold-open hook, cover + post copy - and the
privacy guards: the screen crop never leaves the screen region (geometry crop minus ``privacy.exclude``),
``privacy.exclude`` rects are painted out of every source frame first, covers are cut from the source through
the same guards, and pad-blur (which shows the whole frame) is refused while an exclude is set.

Stage DAG (shared per source: probe, extract, asr, geometry):
  probe(io) -> extract(io; skipped with inputs.transcript) -> asr(asr: ONE transcript per source) ->
  geometry(cpu: the workflow's analyze.py geo frames + geometry.py once per source -> crop spans, clipped
  against privacy.exclude; or screen.region) -> cleanup(cpu: row range snapped word-safe, row ``cuts`` snapped
  and removed, vstudio.cleanup.analyze on what is left -> EDL + review sheet + confirm list; hook edge
  snapped + end-extended) -> compose(cpu-render: a per-job work dir (config.json, keep_list.json from the EDL +
  the creator's reply, hook_edges.json, crop_spans.json, the shared transcript linked as audio16k.json) ->
  build_timeline.py, make_audio_assets.py, render.py with render.audio_only, build_subs.py) ->
  export(cpu-render: make_vertical.py --targets <job platforms>: one master per canvas + per-target export with
  captions, cover, post) -> verify(asr: re-ASR of the job's audio, lost words) -> qc(cpu: the batch gates +
  privacy) ; preview(cpu-render).

The workflow scripts run unchanged as subprocesses inside the job's stage folder (their own CLI); the batch
only writes their inputs. See references/BATCH.md ("longform-split").
"""
import os
import re
import shutil
import subprocess
import sys

from . import spec as S
from . import stages as ST
from .recipes import Recipe, Stage, register
from .util import parse_time, read_json, sha1_json, write_json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LFS = os.path.join(ROOT, "workflows", "longform-to-short", "scripts")
LIB = os.path.join(ROOT, "lib")
MODES = ("split", "screen", "speaker", "pad-blur")
PAD_IN, PAD_OUT, FADE_OUT = 0.15, 0.25, 0.04          # build_keep_list.py keep.pad_in / pad_out, render cut fade
SCREEN_KEYS = ("min_scale", "max_scale", "sample_hz", "change_luma", "min_change_px", "analysis_w", "page_change",
               "follow", "ink", "headroom", "min_text_px", "max_upscale", "sharpen", "popups", "popup_min_frac",
               "popup_max_s", "scroll_min_px")


class PrivacyError(ValueError):
    pass


# --------------------------------------------------------------------------- privacy geometry
_RECT_STR = re.compile(r"^\s*([xy])\s*(>=|>|<=|<)\s*(-?\d+(?:\.\d+)?)\s*$")


def resolve_rects(rects, W, H):
    """privacy.exclude entries -> [[x0, y0, x1, y1]] ints inside the W x H frame.

    Entries: [x0, y0, x1, y1] (null = the frame edge), {x0, y0, x1, y1} (missing = frame edge) or a half-plane
    string "x >= 960" / "x<300" / "y >= 600"."""
    out = []
    for r in rects or ():
        if isinstance(r, str):
            m = _RECT_STR.match(r)
            if not m:
                raise ValueError(f"privacy.exclude {r!r}: use [x0, y0, x1, y1] or 'x >= 960'")
            ax, op, v = m.group(1), m.group(2), float(m.group(3))
            lo, hi = (v, None) if op.startswith(">") else (None, v)
            box = [lo, None, hi, None] if ax == "x" else [None, lo, None, hi]
        elif isinstance(r, dict):
            box = [r.get("x0"), r.get("y0"), r.get("x1"), r.get("y1")]
        else:
            box = (list(r) + [None] * 4)[:4]
        x0, y0, x1, y1 = [d if v is None else float(v) for v, d in zip(box, (0, 0, W, H))]
        x0, x1 = max(0, int(x0)), min(W, int(round(x1 + 0.4999)))
        y0, y1 = max(0, int(y0)), min(H, int(round(y1 + 0.4999)))
        if x1 > x0 and y1 > y0:
            out.append([x0, y0, x1, y1])
    return out


def _inter(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def clip_region(region, excludes):
    """Screen region [x0, y0, x1, y1] minus the exclude rects that span its full height (cut the side they are
    on) or full width. -> (region or None when nothing is left, partial overlaps [rect] left to the paint-out)."""
    x0, y0, x1, y1 = [int(v) for v in region]
    partial = []
    for e in excludes or ():
        if not _inter((x0, y0, x1, y1), e):
            continue
        ex0, ey0, ex1, ey1 = e
        if ey0 <= y0 and ey1 >= y1:                  # a full-height column
            if ex0 <= x0 and ex1 >= x1:
                return None, partial
            if ex0 > x0:
                x1 = min(x1, ex0)
            else:
                x0 = max(x0, ex1)
        elif ex0 <= x0 and ex1 >= x1:                # a full-width band
            if ey0 > y0:
                y1 = min(y1, ey0)
            else:
                y0 = max(y0, ey1)
        else:
            partial.append(list(e))
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    if w < 16 or h < 16:
        return None, partial
    return [x0, y0, x0 + w, y0 + h], [e for e in partial if _inter((x0, y0, x0 + w, y0 + h), e)]


def _xyxy(crop):
    cw, ch, cx, cy = crop
    return [cx, cy, cx + cw, cy + ch]


def _whxy(r):
    return [r[2] - r[0], r[3] - r[1], r[0], r[1]]


# --------------------------------------------------------------------------- helpers
def _p(job):
    return job["params"]


def _vcfg(spec):
    return dict(spec.get("vertical") or {})


def _screen(spec):
    return dict(spec.get("screen") or {})


def _hook_speed(p):
    if p.get("hook_speed"):
        return float(p["hook_speed"])
    from vstudio.config import persona
    return float(((persona().get("longform") or {}).get("speed") or {}).get("hook", 1.1))


def _cuts(v):
    out = []
    for c in v or ():
        if isinstance(c, dict):
            c = [c.get("start", c.get("t0")), c.get("end", c.get("t1")), c.get("why", c.get("reason", ""))]
        elif isinstance(c, str):
            a, b = re.split(r"(?<=\d)\s*-\s*(?=\d)", c.strip(), maxsplit=1)
            c = [a, b, ""]
        a, b = parse_time(c[0]), parse_time(c[1])
        if b > a:
            out.append([a, b, str(c[2]) if len(c) > 2 and c[2] is not None else ""])
    return sorted(out)


def _subtract(a, b, cuts, min_len=0.06):
    out, cur = [], a
    for ca, cb in sorted((float(c[0]), float(c[1])) for c in cuts):
        if cb <= cur or ca >= b:
            continue
        if ca > cur:
            out.append((cur, ca))
        cur = max(cur, cb)
    if cur < b:
        out.append((cur, b))
    return [(round(x, 3), round(y, 3)) for x, y in out if y - x >= min_len]


def _hook_lines(h):
    """Hook caption lines for the title band: the row's lines, a long single line split in two at a comma."""
    lines = [str(x) for x in (h.get("lines") or []) if str(x).strip()]
    if len(lines) == 1 and len(lines[0]) > 14:
        t = lines[0]
        cuts = [m.end() for m in re.finditer(r"[，,、：:；;]\s*", t)]
        if cuts:
            k = min(cuts, key=lambda i: abs(i - len(t) / 2))
            if 3 <= k <= len(t) - 3:
                return [t[:k].rstrip("，,、：:；; "), t[k:].strip()]
    return lines


def _title_parts(title):
    """Cover big1 / big2 from a title: split at the first strong punctuation, else in the middle."""
    t = (title or "").strip()
    m = re.search(r"[：:，,？?！!]", t)
    if m and 2 <= m.start() <= len(t) - 2:
        return t[:m.start() + (1 if t[m.start()] in "？?！!" else 0)], t[m.end():].strip()
    if len(t) <= 8:
        return t, ""
    k = len(t) // 2
    return t[:k], t[k:]


def _post_body(p):
    if p.get("body"):
        return str(p["body"])
    notes = [str(n) for n in (p.get("notes") or [])]
    return "\n".join(f"· {n}" for n in notes)


def _script(name, work, *args, timeout=None):
    """Run a longform-to-short script on work/config.json (cwd = work); output -> work/<name>.log."""
    env = dict(os.environ)
    env["PYTHONPATH"] = LIB + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, os.path.join(LFS, name), os.path.join(work, "config.json"), *map(str, args)]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, env=env, timeout=timeout)
    with open(os.path.join(work, os.path.splitext(name)[0] + ".log"), "w", encoding="utf-8") as f:
        f.write(" ".join(cmd) + "\n\n" + (r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or ""))
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or ""))[-1500:]
        raise RuntimeError(f"longform-to-short {name} failed (exit {r.returncode}): {tail}")
    return r.stdout


def _link(src, dst):
    if os.path.lexists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def whisper_json(transcript, dst):
    """The shared transcript as the workflow's audio16k.json (whisper segments with words): copied when it already
    has that shape, else rebuilt from vstudio.cleanup.load_words (no re-transcription either way)."""
    data = read_json(transcript) if isinstance(transcript, str) else transcript
    segs = data.get("segments") if isinstance(data, dict) else None
    if segs and all({"start", "end", "text"} <= set(s) for s in segs) and \
            all({"word", "start", "end"} <= set(w) for s in segs for w in s.get("words") or []):
        if isinstance(transcript, str):              # a copy, never a hard link: inputs.transcript may be the
            shutil.copyfile(os.path.abspath(transcript), dst)   # creator's own file (read-only to the batch)
        else:
            write_json(dst, data)
        return dst
    from vstudio import cleanup as C
    W = C.load_words(data)
    groups, cur = [], []
    for w in W:
        cur.append(w)
        if w["end"]:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = dict(text="", language=(data or {}).get("language") if isinstance(data, dict) else None, segments=[
        dict(start=g[0]["t"], end=g[-1]["te"], text=C.join_words(g),
             words=[dict(word=w["w"], start=w["t"], end=w["te"]) for w in g]) for g in groups])
    write_json(dst, out)
    return dst


# --------------------------------------------------------------------------- the workflow config of one job
def lfc_config(p, spec, geo, out_dir):
    """Batch job params + spec -> the longform-to-short config dict (one episode = this job)."""
    from .edits import key_copy
    vs, scr = _vcfg(spec), _screen(spec)
    title = p.get("title") or ""
    title0 = key_copy(p, "title") or ""                # the planned title (cover / title band); review copy edits
    series = p.get("series") or vs.get("series") or ""  # change only the post
    k, n = (p.get("_series_no") or [1, 1])[:2]
    b1, b2 = _title_parts(title0)
    item = dict(chapters=[1, 1], title=title, body=_post_body(p), big1=p.get("big1") or b1,
                big2=p.get("big2") if p.get("big2") is not None else b2,
                sub=p.get("sub") if p.get("sub") is not None else (p.get("chapter") or ""),
                eyebrow=f"{series} · {k}/{n}" if series else f"{k}/{n}")
    cov = p.get("cover") if isinstance(p.get("cover"), dict) else {}
    if p.get("cover_shot") is not None:
        item["shot_src"] = parse_time(p["cover_shot"])
    elif cov.get("src") is not None:
        item["shot_src"] = float(cov["src"])
    h = p.get("hook")
    if h and h.get("src"):
        item["hook"] = dict(src=[float(x) for x in h["src"]], lines=_hook_lines(h))
    a, b = p["range"]
    panels = []
    if p.get("notes"):
        nc = dict(spec.get("notes") or {})
        win = p.get("notes_src")
        if win:
            win = [parse_time(x) for x in (win if isinstance(win, (list, tuple)) else str(win).split("-"))]
        else:
            w = float(p.get("notes_window") or nc.get("window", 20.0))
            win = [max(a, b - w), b]
        panels.append(dict(title=p.get("notes_title") or p.get("chapter") or nc.get("title") or "要点",
                           lines=[str(x) for x in p["notes"]], src=[float(win[0]), float(win[1])]))
    vert = dict(mode=p.get("layout") or "split", exclude=[list(e) for e in p.get("_exclude") or []],
                screen={k_: v for k_, v in scr.items() if k_ in SCREEN_KEYS}, split=dict(vs.get("split") or {}),
                series=series, export_preset=p.get("preset") or "medium",
                hook_captions=vs.get("hook_captions", "hide"))
    if vs.get("speaker"):
        vert["speaker"] = dict(vs["speaker"])
    if vs.get("segments"):
        vert["segments"] = vs["segments"]
    speeds = dict(lecture=float(p.get("speed") or 1.0), hook=_hook_speed(p))
    cfg = dict(
        src=p["source"], out=out_dir, language=p.get("language") or (spec.get("asr") or {}).get("language"),
        targets=list(p.get("platforms") or []), speeds=speeds, share=geo["share"], default_crop=geo["default_crop"],
        cuts=[], cards=dict(dur=float((spec.get("cards") or {}).get("dur", 1.6)), number=[int(k), int(n)]),
        panel_tag=(spec.get("notes") or {}).get("tag", "记笔记"), panels=panels, vertical=vert,
        render=dict(fps=int((spec.get("render") or {}).get("fps", 24)), audio_only=True),
        subtitles=dict(spec.get("subtitles") or {}),
        episodes=dict(series=series, items=[item]),
        publish=dict(title=title0, body=item["body"], tags=list(p.get("tags") or [])))
    if spec.get("style"):
        cfg["style"] = dict(spec["style"])
    return cfg


# --------------------------------------------------------------------------- expansion
def expand_split(spec, rows):
    from vstudio import media
    from vstudio import platform as PF
    src = (spec.get("inputs") or {}).get("source")
    if not src:
        raise ValueError("longform-split: inputs.source (the long recording) is required")
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    info = media.probe(src)
    total, W, H = float(info["duration"]), int(info["display_w"]), int(info["display_h"])
    excl = resolve_rects((spec.get("privacy") or {}).get("exclude"), W, H)
    vs, scr = _vcfg(spec), _screen(spec)
    ud = spec.get("_user_defaults") or {}
    spk = (vs.get("speaker") or {}).get("region")
    if spk and any(_inter(spk, e) for e in excl):
        raise PrivacyError(f"vertical.speaker.region {spk} overlaps privacy.exclude {excl}: the speaker band would "
                           "show an excluded region; give the HOST's own camera tile only")
    if scr.get("region"):
        reg, _ = clip_region(scr["region"], excl)
        if reg is None:
            raise PrivacyError(f"screen.region {scr['region']} lies inside privacy.exclude {excl}")
    items = []
    for k, r in enumerate(rows):
        p = S.with_defaults(spec, r)
        if not p.get("range"):
            raise ValueError(f"longform-split: job {r['id']} has no range (start/end)")
        a, b = max(0.0, p["range"][0]), min(total, p["range"][1])
        if b - a < 1.0:
            raise ValueError(f"job {r['id']}: range {p['range']} is empty / outside the {total:.1f}s recording")
        mode = r.get("layout") or ud.get("layout") or vs.get("mode") or "split"
        if mode not in MODES:
            raise ValueError(f"job {r['id']}: layout {mode!r} - longform-split layouts are {', '.join(MODES)} "
                             "(face / center / letterbox are longform-slices reframes)")
        if mode == "pad-blur" and excl:
            raise PrivacyError(f"job {r['id']}: layout pad-blur is refused while privacy.exclude is set - it fits the "
                               "whole frame (participant tiles included); use split or screen")
        for t in p.get("platforms") or []:
            prof = PF.parse_targets([t])[0]
            if prof.w >= prof.h:
                raise ValueError(f"job {r['id']}: {t} is not a vertical target; longform-split makes 3:4 / 9:16 "
                                 "slices (xiaohongshu:vertical, xiaohongshu:full, douyin, youtube-shorts, ...)")
        cuts = _cuts(p.get("cuts"))
        p.update(range=[a, b], layout=mode, cuts=cuts, source=src, _exclude=excl, _series_no=[k + 1, len(rows)])
        hook = p.get("hook") or (p.get("hooks") or [None])[0]
        speech = sum(y - x for x, y in _subtract(a, b, cuts))
        p["_dur"] = round(speech + ((hook["src"][1] - hook["src"][0]) if hook else 0.0), 3)
        p["_src_dur"] = round(total, 3)
        items.append(dict(item=r["id"], params=p))
    return items


# --------------------------------------------------------------------------- stages
def run_geometry(ctx):
    """Screen region per source, once: screen.region, else the workflow's geo frames + geometry.py crop spans;
    every crop clipped against privacy.exclude."""
    from vstudio import media
    p, spec = ctx.params, ctx.spec
    src = p["source"]
    info = media.probe(src)
    dur = float(info["duration"])
    excl = [list(e) for e in p.get("_exclude") or []]
    scr = _screen(spec)
    frame = None
    if scr.get("region"):
        spans = [dict(t0=0, t1=dur, header="screen.region", crop=_whxy([int(v) for v in scr["region"]]))]
    else:
        work = ctx.path("work")
        os.makedirs(work, exist_ok=True)
        write_json(os.path.join(work, "config.json"), dict(src=src, out=ctx.path("out"), duration=dur,
                                                           geometry=dict(scr.get("geometry") or {})))
        _script("analyze.py", work, "--skip", "audio,subs,silence")
        _script("geometry.py", work)
        spans = read_json(os.path.join(work, "crop_spans.json"), [])
        geo = os.path.join(work, "geo")
        pngs = sorted(f for f in os.listdir(geo) if f.endswith(".png")) if os.path.isdir(geo) else []
        if pngs:                                     # one sample frame kept (privacy check / docs), the rest goes
            frame = ctx.path("frame.png")
            shutil.copy(os.path.join(geo, pngs[len(pngs) // 2]), frame)
        shutil.rmtree(geo, ignore_errors=True)
    out, partial, longest = [], [], None
    for sp in spans:
        sp = dict(sp)
        if sp.get("crop"):
            reg, part = clip_region(_xyxy(sp["crop"]), excl)
            partial += part
            sp["crop"] = _whxy(reg) if reg else None
            if reg and (longest is None or sp["t1"] - sp["t0"] > longest[0]):
                longest = (sp["t1"] - sp["t0"], sp["crop"])
        out.append(sp)
    if longest is None:
        raise ValueError("geometry: no screen-share region found in the recording (dark-mode share? tune "
                         "screen.geometry.bright) - set screen.region [x0, y0, x1, y1] in the batch spec")
    path = write_json(ctx.path("crop_spans.json"), out)
    files = [path] + ([frame] if frame else [])
    return dict(crop_spans=path, default_crop=longest[1], share=_xyxy(longest[1]), exclude=excl,
                partial_excludes=partial, size=[info["display_w"], info["display_h"]], frame=frame,
                spans=len(out), files=files, digest=sha1_json([out, excl]))


def hook_skip_lead_fillers(W, en, ha, hb, pad=None):
    """A cold open never starts on a filler: skip the hook's leading fillers / hesitations (然后, 嗯, 就是 ...)
    and start in the quiet just before the first content word (body cleanup auto-cuts the same words, the
    hook is not cleaned). Whisper often stretches such a word over the silence before the next one, so the
    new start is the end of the last quiet run before that word's midpoint (-pad), never its whisper start.
    No quiet run (words glued together) -> the start stays (cutting there could clip a word)."""
    from vstudio import cleanup as C
    pad = C.COMMON["pad"] if pad is None else pad
    fl = C._all_fillers()
    inner = [w for w in W if ha <= C._mid(w) <= hb]
    k = 0
    while k < len(inner) - 1 and inner[k]["n"] in fl:
        k += 1
    if k == 0 or en is None or en.thr is None:
        return ha
    first = inner[k]
    runs = en.quiet_in(inner[k - 1]["t"], C._mid(first))
    if not runs:
        return ha
    return round(max(ha, runs[-1][0], runs[-1][1] - pad), 3)


def run_cleanup_split(ctx):
    """Row range -> word-safe edges, row cuts snapped and removed, vstudio.cleanup.analyze on the rest."""
    from vstudio import cleanup as C
    p, src = ctx.params, ctx.params["source"]
    tr = ctx.inputs["asr"]["transcript"]
    W = C.load_words(tr)
    prof = p.get("cleanup_profile")
    prof = None if prof in (None, "off") else prof
    ov = ST.cleanup_overrides(p)
    a, b = p["range"]
    speed = float(p.get("speed") or 1.0)
    en = C.energy_of(src, W, [(a - 1.0, b + 1.0)], prof, ov)
    if W:
        lo, hi = C.word_limits(W, a, b)
        sa, sb = C.snap_range(W, a, b, en)
        a2, b2 = min(sa, max(a - PAD_IN, lo, 0.0)), max(sb, min(b + PAD_OUT, hi - 0.03))
        b2, _, _ = C.extend_end(W, en, a2, b2, FADE_OUT, speed)
        cuts = C.snap_cuts(W, en, p.get("cuts") or [], [(a2, b2)])
    else:
        a2, b2, cuts = a, b, [list(c) for c in p.get("cuts") or []]
    ranges = _subtract(a2, b2, cuts)
    if not ranges:
        raise ValueError(f"range {a}-{b} minus cuts leaves nothing")
    lang = p.get("language") or (ctx.spec.get("asr") or {}).get("language")
    body = C.analyze(src, transcript=tr, ranges=ranges, language=lang, profile=prof, overrides=ov,
                     out=ctx.path("body.cleanup.json"), review=ctx.path("body_review.md"), force=True)
    out = dict(body=body["_path"], hook=None, edges=[a2, b2], ranges=[list(r) for r in ranges], cuts=cuts,
               files=[body["_path"]])
    h = p.get("hook")
    if h and h.get("src") and W:
        h0, h1 = [float(x) for x in h["src"]]
        enh = C.energy_of(src, W, [(h0 - 1.0, h1 + 1.0)], prof, ov)
        ha, hb = C.snap_range(W, h0, h1, enh)
        ha = hook_skip_lead_fillers(W, enh, ha, hb)
        hb, _, info = C.extend_end(W, enh, ha, hb, FADE_OUT, _hook_speed(p))
        out["hook_edge"] = dict(src=[h0, h1], edge=[round(ha, 3), round(hb, 3)], info=info)
    edits = [dict(e, part="body") for e in body["edits"]]
    confirm = [dict(id=e["id"], part=e["part"], kind=e["kind"], text=e.get("text", ""), t0=e["t0"], t1=e["t1"],
                    before=e.get("before", ""), after=e.get("after", ""), reason=e.get("reason", ""),
                    confidence=e.get("confidence")) for e in edits if e["action"] == "confirm"]
    write_json(ctx.path("confirm.json"), confirm)
    out.update(confirm=len(confirm), auto=sum(e["action"] == "auto" for e in edits), confirm_file=ctx.path("confirm.json"),
               policy=C.policy_counts(edits),
               saved_s=round(body["stats"]["source_s"] - body["stats"]["auto_s"], 2))
    return out


def _keep_pieces(p, edl):
    from vstudio import cleanup as C
    E = read_json(edl)
    if p.get("cleanup_profile") == "off":
        return [tuple(r) for r in E["ranges"]]
    reply = p.get("cleanup_reply")
    r = C.parse_reply(reply) if reply else dict(approve=set(), keep=set(), all_confirm=False)
    ids = {e["id"] for e in E["edits"]}
    return C.keep_segments(E["edits"], E["ranges"], set(r["approve"]) & ids, set(r["keep"]) & ids,
                           bool(r["all_confirm"]), min_piece=(E.get("settings") or {}).get("min_piece"),
                           words=E.get("words"))


def _out_time(timeline, t):
    """Output time of source second ``t`` that is NOT played (cut): where the cut sits in the output (the start
    of the next body piece after it, else the end of the last one)."""
    best = None
    for it in timeline:
        if it["kind"] == "card" or it.get("hook"):
            continue
        t0, t1, sp, f0 = float(it["t0"]), float(it["t1"]), float(it["speed"]), float(it["final_t0"])
        if t0 <= t < t1:
            return f0 + (t - t0) / sp
        if t0 >= t and (best is None or t0 < best[0]):
            best = (t0, f0)
    if best:
        return best[1]
    body = [it for it in timeline if it["kind"] != "card" and not it.get("hook")]
    if not body:
        return 0.0
    it = body[-1]
    return float(it["final_t0"]) + (float(it["t1"]) - float(it["t0"])) / float(it["speed"])


def _sidecar(final, timeline, transcript, total, language, edges=None):
    """<final>.cleanup.json for ``cleanup.verify``: every word the job should still say, in OUTPUT time
    (hook first, then the body - the order a fresh ASR hears them), identity time map over the output.
    ``removed`` = the words inside the job's range edges that the cut dropped (filler / repeat edits, row cuts),
    at the output time of their cut: verify never reports those as lost."""
    from vstudio import cleanup as C
    W = C.load_words(transcript)
    words = []
    for it in timeline:
        if it["kind"] == "card":
            continue
        t0, t1, sp, f0 = float(it["t0"]), float(it["t1"]), float(it["speed"]), float(it["final_t0"])
        for w in W:
            m = (w["t"] + w["te"]) / 2
            if t0 <= m < t1:
                words.append(dict(w=w["w"], t=round(f0 + (max(w["t"], t0) - t0) / sp, 3),
                                  te=round(f0 + (min(w["te"], t1) - t0) / sp, 3), src=w["t"]))
    played = [(float(it["t0"]), float(it["t1"])) for it in timeline if it["kind"] != "card"]
    removed = []
    if edges:
        for w in W:
            m = (w["t"] + w["te"]) / 2
            if edges[0] <= m <= edges[1] and not any(a <= m < b for a, b in played):
                removed.append(dict(w=w["w"], t=round(_out_time(timeline, m), 3), src=w["t"]))
    clips = [it for it in timeline if it["kind"] != "card"]
    joints = [round(float(y["final_t0"]), 3) for x, y in zip(clips, clips[1:])     # output-time cut joints
              if abs(float(y["t0"]) - float(x["t1"])) > 1e-3]
    side = os.path.splitext(final)[0] + ".cleanup.json"
    tm = [dict(kind="clip", src0=0.0, src1=float(total), speed=1.0, source=0, dst0=0.0, dur=float(total), xfade=0.0,
               tag="body")]
    write_json(side, dict(tool="vstudio.batch.lfsplit", tag=sha1_json([t["t"] for t in words], 8), source=final,
                          out=final, language=language, expected=[dict(w=w["w"], t=w["t"], te=w["te"]) for w in words],
                          words=words, removed=removed, timemap=tm, keep=[[0.0, float(total)]], joints=joints))
    return side


def run_compose_split(ctx):
    """Per-job work dir -> build_timeline / make_audio_assets / render (audio only) / build_subs."""
    p, spec = ctx.params, ctx.spec
    geo, cl = ctx.inputs["geometry"], ctx.inputs["cleanup"]
    tr = ctx.inputs["asr"]["transcript"]
    work, out = ctx.path("work"), ctx.path("out")
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    cfg = lfc_config(p, spec, geo, out)
    write_json(os.path.join(work, "config.json"), cfg)
    _link(geo["crop_spans"], os.path.join(work, "crop_spans.json"))
    whisper_json(tr, os.path.join(work, "audio16k.json"))
    pieces = _keep_pieces(p, cl["body"])
    if not pieces:
        raise ValueError("nothing left to keep after cleanup")
    chapter = p.get("chapter")
    write_json(os.path.join(work, "keep_list.json"), [dict(t0=pieces[0][0], t1=pieces[-1][1], ids=[], chapter=chapter,
                                                           keep=[list(x) for x in pieces], episode=1)])
    if cl.get("hook_edge"):
        write_json(os.path.join(work, "hook_edges.json"), {"ep1": dict(src=cl["hook_edge"]["src"],
                                                                         edge=cl["hook_edge"]["edge"])})
    _script("build_timeline.py", work)
    _script("make_audio_assets.py", work)
    _script("render.py", work)
    _script("build_subs.py", work)
    timeline = read_json(os.path.join(work, "timeline.json"))
    last = timeline[-1]
    total = float(last["final_t0"]) + (float(last["dur"]) if last["kind"] == "card" else
                                       (float(last["t1"]) - float(last["t0"])) / float(last["speed"]))
    hook_dur = sum((it["t1"] - it["t0"]) / it["speed"] for it in timeline if it.get("hook"))
    cards = [[round(float(it["final_t0"]), 3), round(float(it["final_t0"]) + float(it["dur"]), 3)]
             for it in timeline if it["kind"] == "card"]
    cues = read_json(os.path.join(work, "cues.json"), [])
    cues_path = write_json(ctx.path("cues.json"), {"cues": cues})
    final = os.path.join(out, "final.mp4")
    lang = cfg.get("language")
    side = _sidecar(final, timeline, os.path.join(work, "audio16k.json"), total, lang, edges=cl.get("edges"))
    return dict(work=work, timeline=os.path.join(work, "timeline.json"), cues=cues_path, final=final, sidecar=side,
                duration=round(total, 3), hook_dur=round(hook_dur, 3), n_cues=len(cues), cards=cards,
                pieces=len(pieces), files=[final, cues_path, os.path.join(work, "timeline.json"),
                                           os.path.join(work, "cues.json")])


def run_export_split(ctx):
    """make_vertical.py for the job's targets: one master per canvas, one export per target (+ cover, post)."""
    p, spec = ctx.params, ctx.spec
    geo, c = ctx.inputs["geometry"], ctx.inputs["compose"]
    work, out = ctx.path("work"), ctx.path("out")
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(work, "config.json"), lfc_config(p, spec, geo, out))
    _link(os.path.join(c["work"], "crop_spans.json"), os.path.join(work, "crop_spans.json"))
    pr = (ctx.inputs.get("proofread") or {}).get("cues")
    cues = (read_json(pr, {}) or {}).get("cues", []) if pr else read_json(os.path.join(c["work"], "cues.json"), [])
    if p.get("caption_overrides"):                         # review caption edits (`job edit --op caption`)
        from .edits import apply_caption_overrides
        cues, _, missed = apply_caption_overrides(cues, p["caption_overrides"])
        for m in missed:
            ctx.log(f"caption edit not applied (cue changed since): #{m.get('i')} {m.get('from')!r}")
    write_json(os.path.join(work, "cues.json"), cues)      # proofread captions (make_vertical reads a bare list)
    timeline = read_json(os.path.join(c["work"], "timeline.json"))
    hook_text = spoken_hook_lines(timeline, cues)          # the hook band says what the audio says (proofread)
    write_json(os.path.join(work, "timeline.json"), timeline)
    _link(c["final"], os.path.join(out, "final.mp4"))
    plats = list(p.get("platforms") or [])
    mpreset = (spec.get("vertical") or {}).get("master_preset", "veryfast")
    stash = os.path.join(ctx.batch_dir, "jobs", ctx.job["id"], "export.masters")
    mkey = master_key(read_json(os.path.join(work, "config.json")), timeline, c, mpreset)
    reused = reuse_masters(stash, mkey, os.path.join(work, "vertical"), _canvases(ctx.job))
    extra = ["--reuse-masters"] if reused else []
    if reused:
        ctx.log(f"vertical masters reused ({', '.join(reused)}): captions / cover / post only")
    _script("make_vertical.py", work, "--targets", ",".join(plats), "--preset", mpreset, *extra)
    keep_masters(stash, mkey, os.path.join(work, "vertical"))
    ep = os.path.join(out, "vertical", "ep1")
    entries = read_json(os.path.join(ep, "manifest.json"), []) or []
    if not entries:
        raise RuntimeError("make_vertical.py wrote no exports")
    plans, overlap, modes = {}, 0, set()
    vdir = os.path.join(work, "vertical")
    fps = float((spec.get("render") or {}).get("fps", 24))
    for d in sorted(os.listdir(vdir)):
        pl = read_json(os.path.join(vdir, d, "plan.json"))
        if not pl:
            continue
        overlap += int(pl.get("privacy_overlap_frames") or 0)
        modes |= {it.get("mode") for it in pl.get("items") or [] if it.get("mode")}
        plans[d] = dict(band=pl.get("band"), privacy_overlap_frames=pl.get("privacy_overlap_frames"),
                        exclude=pl.get("exclude"), screen=screen_summary(pl, timeline, fps),
                        text_px=[(it.get("screen") or {}).get("text_px") for it in pl.get("items") or []
                                 if it.get("screen")])
    warnings = [w for e in entries for w in e.get("warnings") or []]
    exports = [dict(platform=e["platform"], orientation=e["orientation"], file=os.path.join(ep, e["file"]),
                    cover=os.path.join(ep, e["cover"]) if e.get("cover") else None,
                    post=os.path.join(ep, e["post"]) if e.get("post") else None, duration=e["duration"])
               for e in entries]
    from .lengthfit import fit_exports
    fit = fit_exports(exports, p, spec, timeline, preset=p.get("preset") or "medium")
    for x in exports:                                 # a shorter platform variant: the manifest says so
        for e in entries:
            if (e["platform"], e["orientation"]) == (x["platform"], x["orientation"]) and x.get("variant"):
                e.update(duration=x["duration"], variant=x["variant"])
                e.pop("loudness", None)
    man = write_json(ctx.path("manifest.json"), dict(exports=entries, warnings=warnings, plans=plans, length_fit=fit,
                                                     hook_lines=hook_text))
    files = [x["file"] for x in exports] + [x["cover"] for x in exports if x["cover"]]
    return dict(manifest=man, files=files, exports=exports, warnings=warnings, length_fit=fit,
                privacy=dict(exclude=p.get("_exclude") or [], overlap_frames=overlap, modes=sorted(m for m in modes if m),
                             plans=plans))


# --------------------------------------------------------------------------- vertical master reuse
_ITEM_COPY = ("title", "body", "big1", "big2", "sub", "shot_src", "eyebrow")


def _sig(path):
    try:
        st = os.stat(path)
        return [os.path.basename(path), st.st_size, int(st.st_mtime)]
    except OSError:
        return None


def master_key(cfg, timeline, compose_out, preset):
    """What the caption-free vertical masters depend on: the job's make_vertical config minus the per-target /
    cover / post parts, the timeline (incl. the hook lines the title band shows), the compose audio, the crop
    spans, the master preset and the workflow code."""
    c = dict(cfg or {})
    for k in ("targets", "out", "publish"):
        c.pop(k, None)
    ep = dict(c.get("episodes") or {})
    ep["items"] = [{k: v for k, v in it.items() if k not in _ITEM_COPY} for it in ep.get("items") or []]
    c["episodes"] = ep
    vert = dict(c.get("vertical") or {})
    vert.pop("export_preset", None)
    c["vertical"] = vert
    pt = (cfg or {}).get("publish") or {}
    code = [_sig(os.path.join(LFS, n)) for n in ("make_vertical.py", "_vertical.py", "_lfc.py")]
    return sha1_json([c, timeline, pt.get("title"), _sig(compose_out.get("final") or ""),
                      _sig(os.path.join(compose_out.get("work") or "", "crop_spans.json")), preset, code])


def reuse_masters(stash, key, vdir, canvases):
    """Link the stashed masters (+ plan.json) of ``key`` into ``vdir`` when every canvas has one -> [WxH] or []."""
    names = [f"{w}x{h}" for (w, h) in sorted(canvases)]
    if not names or read_json(os.path.join(stash, "key.json"), {}).get("key") != key:
        return []
    for n in names:
        if not all(os.path.exists(os.path.join(stash, n, f)) for f in ("master.mp4", "plan.json")):
            return []
    for n in names:
        os.makedirs(os.path.join(vdir, n), exist_ok=True)
        for f in ("master.mp4", "plan.json"):
            _link(os.path.join(stash, n, f), os.path.join(vdir, n, f))
    return names


def keep_masters(stash, key, vdir):
    """After an export: hard-link its masters into the stash (the export stage folder is wiped on a re-run)."""
    if not os.path.isdir(vdir):
        return
    tmp = stash + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    for d in sorted(os.listdir(vdir)):
        m, pl = os.path.join(vdir, d, "master.mp4"), os.path.join(vdir, d, "plan.json")
        if os.path.exists(m) and os.path.exists(pl):
            os.makedirs(os.path.join(tmp, d), exist_ok=True)
            _link(m, os.path.join(tmp, d, "master.mp4"))
            _link(pl, os.path.join(tmp, d, "plan.json"))
            n += 1
    if not n:
        shutil.rmtree(tmp, ignore_errors=True)
        return
    write_json(os.path.join(tmp, "key.json"), dict(key=key))
    shutil.rmtree(stash, ignore_errors=True)
    os.replace(tmp, stash)


def ensure_stash(batch_dir, jid, rows, spec):
    """A job exported before the master stash existed: stash its current masters under the key its export would
    compute now (so the first review edit is a re-burn too). No-op when stashed / not exported."""
    stash = os.path.join(batch_dir, "jobs", jid, "export.masters")
    if os.path.exists(os.path.join(stash, "key.json")):
        return False
    ex, cm = rows.get("export") or {}, rows.get("compose") or {}
    if ex.get("state") != "done" or cm.get("state") != "done":
        return False
    work = os.path.join(batch_dir, "jobs", jid, "export", "work")
    cfg, tl = read_json(os.path.join(work, "config.json")), read_json(os.path.join(work, "timeline.json"))
    if not cfg or not tl:
        return False
    key = master_key(cfg, tl, cm.get("out") or {}, (spec.get("vertical") or {}).get("master_preset", "veryfast"))
    keep_masters(stash, key, os.path.join(work, "vertical"))
    return os.path.exists(os.path.join(stash, "key.json"))


def spoken_hook_lines(timeline, cues, max_one=16):
    """Hook items of ``timeline`` get ``hook_lines`` from the (proofread) captions spoken in their window - the
    title band then shows exactly what the cold open says, and make_vertical hides the captions under it.
    Returns {item index: lines}."""
    from vstudio.subs import balanced_wrap
    out = {}
    for k, it in enumerate(timeline):
        if not it.get("hook") or it.get("kind") == "card":
            continue
        a = float(it["final_t0"])
        b = a + (float(it["t1"]) - float(it["t0"])) / float(it["speed"])
        txt = [c["text"].strip() for c in cues if a - 0.05 <= (c["start"] + c["end"]) / 2 < b and c["text"].strip()]
        if not txt:
            continue
        full = "".join(txt)
        if len(full) <= max_one:
            lines = [full]
        elif len(txt) >= 2:                          # break at the caption boundary nearest the middle
            cum = [len("".join(txt[:i])) for i in range(1, len(txt))]
            i = min(range(len(cum)), key=lambda j: abs(cum[j] - len(full) / 2)) + 1
            lines = ["".join(txt[:i]), "".join(txt[i:])]
        else:
            lines = balanced_wrap(full, len(full) / 2 + 1)[:2]
            if len(lines) > 2:
                lines = [lines[0], "".join(lines[1:])]
        it["hook_lines"] = [ln for ln in lines if ln]
        out[k] = it["hook_lines"]
    return out


def screen_summary(plan, timeline, fps):
    """The screen-crop facts QC needs from one canvas plan: zoom, text size, follow, popups in output time."""
    items = [it for it in plan.get("items") or [] if it.get("screen")]
    pops = []
    for it in items:
        k = it.get("item")
        f0 = float(timeline[k]["final_t0"]) if k is not None and k < len(timeline) else 0.0
        for pp in (it["screen"].get("popups") or []):
            pops.append(dict(t=round(f0 + pp["f0"] / fps, 2), dur=pp["dur"], cover=pp["cover"], masked=pp["masked"]))
    tp = [it["screen"].get("text_px") for it in items if it["screen"].get("text_px")]
    return dict(scale=max([it["screen"].get("scale") or 0 for it in items] or [0]),
                text_px_min=min(tp) if tp else None, text_small=any(it["screen"].get("text_small") for it in items),
                moving=sum((it["screen"].get("p95_speed") or 0) > 0.002 for it in items), items=len(items),
                scrolls=sum(it["screen"].get("scrolls") or 0 for it in items), popups=pops,
                visible=visible_popups(plan), static=static_overlays(plan))


def visible_popups(plan):
    """Popups the output scan (make_vertical: the rendered master sampled at 2 fps) still saw on screen:
    [dict(t, dur, cover, box)] in output seconds, or None when the plan predates the scan."""
    if "visible_popups" not in plan:
        return None
    return [dict(t=x["t"], dur=x["dur"], cover=x.get("cover"), box=x.get("box")) for x in plan["visible_popups"]]


def static_overlays(plan):
    """Persistent UI panels the output scan (make_vertical: ``_vertical.scan_static_overlays``, the rendered master
    at 2 fps) saw inside the screen crop - an editor's block / selection menu or a toolbar left open over whole
    items, which the popup scan (a box appearing AND vanishing inside one item) misses:
    [dict(t, dur, box canvas px, cover, evidence, hug, items)] in output seconds, or None when the plan predates
    the scan. evidence: shadow (a floating card with a drop shadow), pinned (the page changes around it, it
    stays), appeared / vanished (it comes / goes over an unchanged page); hug: the crop edge cutting it."""
    if "static_overlays" not in plan:
        return None
    return [dict(t=x["t"], dur=x["dur"], box=x.get("box"), cover=x.get("cover"), evidence=x.get("evidence") or [],
                 hug=x.get("hug"), items=x.get("items") or []) for x in plan["static_overlays"]]


def run_verify_split(ctx):
    from vstudio import cleanup as C
    o = ST.hear_opts(ctx.job, ctx.spec)
    fn = ST._transcriber(ctx.spec)
    tfn = (lambda path: fn(path, language=o["language"], prompt=o["prompt"])) if fn else None
    final = ctx.inputs["compose"]["final"]
    got = ST.hear(final, tfn, o)
    heard = write_json(ctx.path("heard.json"), got)
    r = C.verify(final, got=got, write=False, recheck=True, transcriber=tfn, language=o["language"],
                 prompt=o["prompt"])
    rep = {"body": dict(ok=r["ok"], missing=r["missing"], leftovers=r["leftovers"], variants=r["variants"],
                        ignored=r["ignored"], rechecked=r["rechecked"])}
    path = write_json(ctx.path("verify.json"), rep)
    cost = 0.0
    if not fn and o["backend"] == "openai":
        cost = _out_dur(ctx.job, ctx.spec) / 60.0 * ST._price(ctx.spec, "openai_whisper_min", ST.PRICE_WHISPER_PER_MIN)
    return dict(ok=r["ok"], report=path, files=[path, heard], cost_usd=cost, missing=len(r["missing"]), heard=heard)


def screen_checks(job, spec, export_out):
    """Screen-crop QC: editor popups the rendered master still shows (make_vertical's 2 fps output scan, every
    screen item, popups covering >= qc.popup_scan_cover (0.02) for > qc.popup_s (1 s): warn with the timestamps);
    editor popups the analysis left visible (not masked: one that stays open, or ``popups: hold / off``)
    covering > qc.popup_cover (0.05) of the crop for > qc.popup_s (1 s) -> warn; persistent UI panels (a menu /
    toolbar left open over whole items: the static overlay scan) shown >= qc.overlay_s (1 s) -> warn
    ``screen-overlay-static`` with times + boxes (one already reported as a visible popup is not repeated);
    text lines drawn smaller than qc.text_px_min -> warn."""
    from .qc import _c
    q = dict(dict(popup_cover=0.05, popup_s=1.0, text_px_min=14.0, popup_scan_cover=0.02, overlay_s=1.0),
             **((spec.get("qc") or {})))
    out = []
    for canvas, pl in (((export_out or {}).get("privacy") or {}).get("plans") or {}).items():
        sc = pl.get("screen") or {}
        vis = sc.get("visible")
        bad = []
        if vis is not None:                            # what the rendered master really shows (2 fps scan)
            bad = [x for x in vis if x["dur"] > q["popup_s"] and (x.get("cover") or 0) >= q["popup_scan_cover"]]
            out.append(_c("screen-popup-visible", not bad, [[x["t"], x["dur"], x.get("cover")] for x in bad],
                          "editor popup still visible in the output: " +
                          ", ".join(f"{x['t']:.1f}-{x['t'] + x['dur']:.1f}s" for x in bad), severity="warn", target=canvas))
        sto = sc.get("static")
        if sto is not None:                            # toolbars / menus left open (static overlay scan)
            def _seen(x):                              # already reported as a visible popup (same time, same box)
                return any(p["t"] < x["t"] + x["dur"] and x["t"] < p["t"] + p["dur"] and p.get("box") and x.get("box")
                           and _boxes_meet(p["box"], x["box"]) for p in bad)
            st = [x for x in sto if x["dur"] >= q["overlay_s"] and not _seen(x)]
            out.append(_c("screen-overlay-static", not st,
                          [dict(t=x["t"], dur=x["dur"], box=x.get("box"), evidence=x.get("evidence"), hug=x.get("hug"))
                           for x in st],
                          "UI toolbar / menu left open over the screen: " +
                          ", ".join(f"{x['t']:.1f}-{x['t'] + x['dur']:.1f}s at {x.get('box')}"
                                    + (f" (cut by the {x['hug']} edge)" if x.get("hug") else "") for x in st),
                          severity="warn", target=canvas))
        big = [x for x in sc.get("popups") or [] if x["cover"] > q["popup_cover"] and x["dur"] > q["popup_s"]]
        shown = [x for x in big if not x.get("masked")]
        out.append(_c("screen-popup", not shown, [[x["t"], x["dur"], x["cover"], x["masked"]] for x in big],
                      "editor popup over the page: " + ", ".join(f"{x['t']:.1f}s for {x['dur']:.1f}s ({x['cover']:.0%})"
                                                                 for x in shown), severity="warn", target=canvas))
        tp = sc.get("text_px_min")
        out.append(_c("screen-text", tp is None or tp >= q["text_px_min"], tp,
                      f"text lines only {tp}px tall at the {sc.get('scale')}x zoom cap", severity="warn", target=canvas))
    return out


def _boxes_meet(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def privacy_checks(job, export_out):
    from .qc import _c
    pv = (export_out or {}).get("privacy") or {}
    excl = pv.get("exclude") or []
    out = [_c("privacy-overlap", int(pv.get("overlap_frames") or 0) == 0, pv.get("overlap_frames"),
              f"screen crop touched privacy.exclude on {pv.get('overlap_frames')} frame(s)")]
    if excl:
        out.append(_c("privacy-layout", "pad-blur" not in (pv.get("modes") or []), pv.get("modes"),
                      "pad-blur layout used while privacy.exclude is set"))
    return out


def run_qc_split(ctx):
    from .qc import run_gates
    res = run_gates(ctx.job, ctx.spec, ctx.inputs, extra=privacy_checks(ctx.job, ctx.inputs.get("export")) +
                    screen_checks(ctx.job, ctx.spec, ctx.inputs.get("export")))
    path = write_json(ctx.path("qc.json"), res)
    return dict(res, report=path, files=[path])


# --------------------------------------------------------------------------- stage list
def _dur(job, spec):
    return float(_p(job).get("_dur") or 0.0)


def _out_dur(job, spec):
    p = _p(job)
    return _dur(job, spec) / float(p.get("speed") or 1.0) + 1.6


def _canvases(job):
    from vstudio import platform as PF
    return {PF.parse_targets([t])[0].size for t in _p(job).get("platforms") or []}


def _export_units(job, spec):
    """Output seconds x (one export per target + ~2x per vertical master: numpy compose + encode per canvas)."""
    return _out_dur(job, spec) * (len(_p(job).get("platforms") or []) + 2 * max(1, len(_canvases(job))))


def _keyp(*keys):
    return lambda job, spec: {k: _p(job).get(k) for k in keys}


def _geo_params(job, spec):
    scr = _screen(spec)
    return dict(ST._stat_params(job, spec), region=scr.get("region"), geometry=scr.get("geometry"),
                exclude=_p(job).get("_exclude"))


def _compose_params(job, spec):
    d = _keyp("range", "cuts", "hook", "chapter", "speed", "hook_speed", "cleanup_reply", "cleanup_profile",
              "language")(job, spec)                 # copy (title, notes, tags, cover) is the export's business
    return dict(d, subtitles=spec.get("subtitles"), cards=spec.get("cards"), render=spec.get("render"))


def _export_params(job, spec):
    from .edits import key_copy
    d = _keyp("platforms", "notes", "notes_src", "notes_window", "notes_title", "chapter",
              "series", "layout", "preset", "big1", "big2", "sub", "cover_shot", "_series_no", "_exclude")(job, spec)
    d.update({k: key_copy(_p(job), k) for k in ("title", "body", "tags")})   # review copy edits patch the posts
    for k in ("caption_overrides", "cover"):           # review edits; only when set (older batches keep their keys)
        if _p(job).get(k):
            d[k] = _p(job)[k]
    return dict(d, vertical=spec.get("vertical"), screen=spec.get("screen"), style=spec.get("style"),
                notes_cfg=spec.get("notes"), cards=spec.get("cards"), render=spec.get("render"),
                max_len=_p(job).get("max_len") or (spec.get("defaults") or {}).get("max_len") or spec.get("max_len"),
                trims=_p(job).get("trims"), v=2)


def split_stages():
    base = {s.name: s for s in ST.speech_stages()}
    return [
        base["probe"], base["extract"], base["asr"],
        Stage("geometry", "cpu", run_geometry, deps=("probe",), shared=True, params=_geo_params, units=ST._src_dur),
        Stage("cleanup", "cpu", run_cleanup_split, deps=("probe", "asr"),
              params=ST.cleanup_params("range", "cuts", "hook", "speed", "hook_speed", "cleanup_profile",
                                       "cleanup_overrides", "cleanup_policy", "language"), units=_dur, version=5),
        Stage("compose", "cpu-render", run_compose_split, deps=("cleanup", "geometry", "asr"), params=_compose_params,
              units=_dur, purge=("work/seg/*", "work/*.wav", "work/*.mkv", "out/final.mp4"), version=3),
        base["glossary"], base["proofread"],
        Stage("export", "cpu-render", run_export_split, deps=("compose", "geometry", "proofread"), params=_export_params,
              units=_export_units, purge=("work/vertical/*/master.mp4", "work/vertical/*.mp4",
                                          "out/vertical/ep1/*.mp4")),
        Stage("verify", "asr", run_verify_split, deps=("compose",), params=lambda j, s: ST.hear_opts(j, s),
              units=_out_dur, enabled=ST._verify_on, cost=ST._asr_cost(_out_dur), version=5),
        Stage("qc", "cpu", run_qc_split, deps=("cleanup", "compose", "export", "verify"),
              params=lambda j, s: dict(qc=s.get("qc") or {}, title=_p(j).get("title"), recipe=j.get("recipe"),
                                       max_len=_p(j).get("max_len") or s.get("max_len"), v=2),
              units=lambda j, s: _out_dur(j, s) * max(1, len(_p(j).get("platforms") or []))),
        Stage("preview", "cpu-render", ST.run_preview, deps=("export",), units=lambda j, s: 1.0),
    ]


register(Recipe("longform-split", split_stages(), expand_split,
                "screen-share lecture slices in the longform-to-short split layout (title band + text-following "
                "screen crop, chapter card, 记笔记 panel, hook, captions, cover, post; privacy.exclude honoured)",
                label="Screen-share lecture -> split-layout slices",
                inputs=[dict(key="inputs.source", label="Screen-share recording", kind="file", required=True,
                             accept=ST.VIDEO_ACCEPT, help="the long recording; may come from the segments.yaml header "
                                                          "`source:` instead"),
                        ST.IN_SEGMENTS, ST.IN_TRANSCRIPT,
                        dict(key="privacy.exclude", label="Hidden regions", kind="rects", required=False,
                             help='participant tiles / name tags never shown, e.g. "x >= 960" or [x0, y0, x1, y1]'),
                        dict(key="screen.region", label="Screen region (optional)", kind="rect", required=False,
                             help="[x0, y0, x1, y1] of the shared page; default: detected once per source"),
                        dict(key="vertical.series", label="Series name", kind="text", required=False)],
                row_keys=ST.COMMON_ROW + ["cuts", "chapter", "notes", "notes_src", "notes_window", "big1", "big2",
                                          "sub", "cover_shot", "series"]))

__all__ = ["resolve_rects", "clip_region", "lfc_config", "expand_split", "whisper_json", "PrivacyError"]
