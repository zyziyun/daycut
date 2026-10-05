#!/usr/bin/env python3
"""Drive every clip in a clips.json end to end: hook montage + sped-up body ->
masked, subtitled, panelled, loudness-normalised mp4 (vertical, trio or landscape,
depending on --renderer).

The timeline is assembled BEFORE tracking, so the face track, the subtitles and
the note panels all live in the same final-frame space and cannot drift apart.

Pieces are cut from the source, each at its own speed, then dissolved together
(vstudio.cut.xfade_assemble: frame-quantised durations, xfade + acrossfade). A
dissolve of D seconds shortens the joint by D, so piece k starts at
offset[k-1] + dur[k-1] - D; the resulting cut.TimeMap is the one source->final map
used for subtitles, panels, node cards and chapters.

Everything in clips.json is authored in SOURCE seconds; this script is the only
place that converts to final time.

Platform (wave B): ``--platform`` / clips.json ``"platform"`` (xiaohongshu, douyin, youtube-shorts,
youtube, bilibili ...) is passed to the renderer (canvas, safe box, caption box) and the clip length is
checked against that platform. ``name_mask`` (blur | cover | off | {mode, box, tiles, extra}) hides the
call app's name labels. ``"auto_trim": true`` cleans every window with the shared speech-cleanup tool
(``vstudio.cleanup.clean`` per window via cut_profiles.py; ``cut_profile`` classic = gentle (default) | word =
standard | gentle | standard | tight); a reviewed sheet (find_disfluencies.py = ``cleanup analyze --ranges``)
is applied with clips.json ``"cleanup_edl"`` + ``"cleanup_reply"`` ("确认 3,5 / 保留 7").
Hooks: each hook's end is moved over its last word's sounding tail plus the dissolve, never into the next
word, and the hook->body fade is shortened when that pause is tight (``cleanup.extend_end``; clips.json
``"hook_tail": false`` keeps the authored ends). ``"speakers"`` (speaker_timeline.py output, source
time) is mapped to final time as work/<id>.speakers.json for render_trio's active-speaker layout.
``--clean-master`` renders a caption-free out/<id>.clean.mp4 + work/<id>.cues.json for
``python -m vstudio.export``.

Run from the project (video) directory; it writes work/ and out/ there:
  python3 $VSTUDIO/workflows/call-clips/scripts/build_clips.py --config clips.json [--only <id>]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_subs import fix
import active_speaker
import cut_profiles
import layout
from vstudio import audio, media
from vstudio import platform as P
from vstudio import cleanup
from vstudio.config import persona
from vstudio.cut import xfade_assemble

PY = sys.executable
_CC = persona().get("call_clips") or {}


def script(name):
    """A sibling script of this one, whatever the cwd."""
    return os.path.join(HERE, name)


def resolve(path):
    """A path from the CLI/config: as given (relative to the project dir) if it
    exists, else relative to the workflow folder (so "assets/cat.png" and
    "scripts/render_trio.py" or just "render_trio.py" work from anywhere)."""
    if not path or os.path.exists(path):
        return path
    for base in (WORKFLOW, HERE):
        p = os.path.join(base, path)
        if os.path.exists(p):
            return p
    sys.exit(f"not found: {path}")

XFADE = 0.5        # a section change, announced by a node card
TRIM_FADE = 0.16   # a silent redaction: a breath, not a transition
AUTO_FADE = 0.06   # an auto-trimmed stumble or pause: just enough to hide the click


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # stdout too: verify_coverage.py reports its FAIL there
        sys.exit(f"FAILED: {' '.join(cmd[:6])}...\n{r.stdout[-1500:]}{r.stderr[-1500:]}")
    return r.stdout


# intermediate timeline encode (the renderer re-encodes it for delivery)
RAW_ARGS = ["-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
CHUNK = 30


def timeline_fps(src):
    """Output frame rate: the source's, as an integer when it is one (30, 25)."""
    f = media.probe(src)["fps"] or 30.0
    return int(round(f)) if abs(f - round(f)) < 0.01 else f


def plan(pieces, xfs, fps):
    """Timing of the dissolved timeline without rendering it: an Assembly whose
    timemap (source -> final, tags "hook"/"body") drives everything downstream.
    mute_pad=False keeps call-clips' plain acrossfade: a muted pad would reach
    past a window edge into cut (or redacted) footage."""
    return xfade_assemble(pieces, xfade=xfs, mute_pad=False, fps=fps)


def _render(src, pieces, xfs, fps, out):
    """One ffmpeg pass: every piece is its own input-seeked read of the source
    (so only its span is decoded), then speed + xfade/acrossfade in one graph."""
    local = [dict(p, input=k, start=0.0, end=p["end"] - p["start"]) for k, p in enumerate(pieces)]
    asm = xfade_assemble(local, xfade=xfs, mute_pad=False, fps=fps)
    cmd = ["ffmpeg", "-y"]
    for p in pieces:
        cmd += ["-ss", f"{p['start']:.3f}", "-t", f"{p['end'] - p['start'] + 0.25:.3f}", "-i", src]
    media.run(cmd + media.filter_complex_args(asm.graph, workdir="work")
              + ["-map", asm.vout, "-map", asm.aout] + RAW_ARGS + [out])
    return asm


def render_timeline(src, pieces, xfs, fps, out):
    """Render the whole timeline. A long-form timeline has 150+ pieces, too many
    inputs for one graph, so it is dissolved in chunks of CHUNK and the chunks are
    then dissolved together; durations are whole frames, so the offset maths
    (and the plan's TimeMap) is identical to a single pass."""
    if len(pieces) <= CHUNK:
        return _render(src, pieces, xfs, fps, out)
    outs, joins, totals = [], [0.0], []
    for c0 in range(0, len(pieces), CHUNK):
        o = f"{out[:-4]}.chunk{c0 // CHUNK}.mp4"
        sub_x = [0.0] + list(xfs[c0 + 1:c0 + CHUNK])
        totals.append(_render(src, pieces[c0:c0 + CHUNK], sub_x, fps, o).total)
        outs.append(o)
        if c0:
            joins.append(xfs[c0])
    asm = xfade_assemble([(k, 0.0, d) for k, d in enumerate(totals)], xfade=joins, mute_pad=False, fps=fps)
    cmd = ["ffmpeg", "-y"]
    for o in outs:
        cmd += ["-i", o]
    media.run(cmd + media.filter_complex_args(asm.graph, workdir="work")
              + ["-map", asm.vout, "-map", asm.aout] + RAW_ARGS + [out])
    for o in outs:
        os.remove(o)
    return asm


TERM_FIX = None


MAX_CHARS = 18


def load_subs(whisper, tm):
    """Map whisper segments from source time into final timeline time, piece by
    piece through the TimeMap's clip items (a line never crosses a join)."""
    items = tm.segments
    lines = []
    segs = json.load(open(whisper, encoding="utf-8"))["segments"]
    for k, it in enumerate(items):
        s0, s1, spd, off = it["src0"], it["src1"], it["speed"], it["dst0"]
        # a line stays clear of the dissolve halves on both sides of its piece
        lo = off + it["xfade"] / 2
        hi = off + it["dur"] - (items[k + 1]["xfade"] / 2 if k + 1 < len(items) else 0.0)
        for s in segs:
            if s["end"] <= s0 or s["start"] >= s1:
                continue
            ws = s.get("words") or []
            if (s["start"] < s0 - 0.05 or s["end"] > s1 + 0.05) and ws:
                # the segment straddles a cut: keep only the words in this
                # piece, or a trimmed stutter would still be on screen
                kept = [w for w in ws if s0 <= (w["start"] + w["end"]) / 2 <= s1]
                if not kept:
                    continue
                txt = fix("".join(w["word"] for w in kept), TERM_FIX)
                t0, t1 = kept[0]["start"], kept[-1]["end"]
            else:
                txt = fix(s["text"], TERM_FIX)
                t0, t1 = s["start"], s["end"]
            if not txt:
                continue
            a = off + (max(t0, s0) - s0) / spd
            b = off + (min(t1, s1) - s0) / spd
            a, b = max(a, lo), min(b, hi)
            if b - a < 0.28:
                continue
            if lines and lines[-1]["end"] > a - 0.45 and \
                    len(lines[-1]["text"] + txt) <= MAX_CHARS and lines[-1]["piece"] == k:
                prev = lines[-1]["text"]
                # "marketing" + "FDE" must not fuse into "marketingFDE"
                sep = " " if re.match(r"[A-Za-z0-9%]", prev[-1:]) and re.match(r"[A-Za-z]", txt) else ""
                lines[-1]["text"] = prev + sep + txt
                lines[-1]["end"] = b
                continue
            lines.append({"start": a, "end": b, "text": txt, "piece": k})

    for i, ln in enumerate(lines[:-1]):
        ln["end"] = min(lines[i + 1]["start"], ln["end"] + 0.3)
        ln.pop("piece")
    if lines:
        lines[-1].pop("piece", None)
    return lines


def main():
    ap = argparse.ArgumentParser(
        description="Cut, dissolve, face-track, verify, subtitle, render and loudnorm every clip "
                    "in clips.json. Run from the project dir; writes work/ and out/.")
    ap.add_argument("--config", default="clips.json")
    ap.add_argument("--only", default=None, help="build just this clip id")
    ap.add_argument("--body-speed", type=float, default=_CC.get("body_speed", 1.2))
    ap.add_argument("--hook-speed", type=float, default=_CC.get("hook_speed", 1.35))
    ap.add_argument("--hook-gain", type=float, default=_CC.get("hook_gain_db", 3.0))
    ap.add_argument("--renderer", default="render_vertical.py",
                    help="render_vertical.py | render_trio.py | render_landscape.py | "
                         "render_landscape_trio.py, or a path")
    ap.add_argument("--sticker", default=_CC.get("sticker", "assets/cat.png"))
    ap.add_argument("--renderer-arg", action="append", default=[],
                    help="extra KEY=VALUE passed through to the renderer")
    ap.add_argument("--no-track", action="store_true",
                    help="renderer covers the guest's whole tile, so no face track is needed")
    ap.add_argument("--no-mask", action="store_true",
                    help="nobody is hidden (two-person renderers only): skip tracking and "
                         "verification and render both faces as recorded")
    ap.add_argument("--sub-max-chars", type=int, default=None,
                    help="merge subtitle segments up to this many chars (default 18; with a platform, "
                         "the profile's caption max_chars_zh, e.g. 14)")
    ap.add_argument("--reuse", action="store_true",
                    help="skip cutting/dissolving/tracking when work files exist; "
                         "for restyling the frame without re-encoding the timeline")
    ap.add_argument("--subs-only", action="store_true",
                    help="stop after subs/title json, e.g. to add an English track before rendering")
    ap.add_argument("--platform", default=None,
                    help="platform profile for the renderer (canvas, safe/caption boxes) and the length "
                         "check, e.g. xiaohongshu, douyin, youtube-shorts, youtube; overrides clips.json "
                         "'platform'. 'legacy' = the fixed pre-platform layouts")
    ap.add_argument("--cut-profile", default=None, choices=list(cut_profiles.PROFILES),
                    help="auto-trim profile (vstudio.cleanup): classic (= gentle) | word (= standard) | gentle | "
                         "standard | tight. Default: clips.json cut_profile, persona call_clips.cut_profile, "
                         "persona cleanup.profile, else classic")
    ap.add_argument("--clean-master", action="store_true",
                    help="render caption-free out/<id>.clean.mp4 (+ work/<id>.cues.json) for vstudio.export")
    args = ap.parse_args()
    if args.no_mask:
        args.no_track = True

    global MAX_CHARS, TERM_FIX

    C = json.load(open(args.config, encoding="utf-8"))
    TERM_FIX = C.get("term_fix")
    cut_profile = args.cut_profile or C.get("cut_profile") or cut_profiles.default_profile()
    platform = args.platform or C.get("platform")
    family = "horizontal" if "landscape" in os.path.basename(args.renderer) else "vertical"
    if platform is None and os.path.basename(args.renderer) == "render_vertical.py":
        platform = "default"            # render_vertical's own default: the persona platform, safe zone on
    prof = layout.resolve(platform, family) if platform else None
    if prof is not None:
        print(f"platform {prof.key} {prof.w}x{prof.h}  safe={P.safe_box(prof)}  caption={P.caption_box(prof)}")
    MAX_CHARS = args.sub_max_chars or (int(prof.caption.get("max_chars_zh", 18)) if prof is not None else 18)
    nm = C.get("name_mask")
    nm = layout.parse_name_mask(nm) if nm is not None else None
    args.renderer = resolve(args.renderer)
    args.sticker = resolve(args.sticker)
    for g in C.get("guests") or []:
        g["sticker"] = resolve(g.get("sticker") or args.sticker)
    src, host = C["source"], C["host_region"]
    # "guests": [{name, region, sticker, label}] masks several people, each with
    # their own track; the legacy single guest_region still works
    guests = C.get("guests")
    guest = C.get("guest_region") or (guests[0]["region"] if guests else None)
    os.makedirs("work", exist_ok=True)
    os.makedirs("out", exist_ok=True)

    # one word list + one calibrated energy envelope (vstudio.cleanup) for auto-trim and hook edges
    WORDS = EN = None
    if C.get("whisper") and os.path.exists(C["whisper"]):
        WORDS = cut_profiles.words_of(json.load(open(C["whisper"], encoding="utf-8"))["segments"])
        if C.get("audio") and os.path.exists(C["audio"]):
            EN = cut_profiles.energy(C["audio"], WORDS, None, cut_profile)
    EDL_EDITS, DEC = None, cleanup.parse_reply("")
    if C.get("auto_trim"):
        if WORDS is None or EN is None:
            sys.exit("auto_trim needs \"audio\" (16 kHz wav) and \"whisper\" (word timestamps)")
        if isinstance(C.get("extra_cuts"), str):
            # a path: editor cuts reviewed separately, [[from, to, why], ...]
            C["extra_cuts"] = json.load(open(C["extra_cuts"], encoding="utf-8"))
        if C.get("cleanup_edl"):
            # the creator reviewed find_disfluencies.py's sheet: apply exactly those decisions
            EDL_EDITS = json.load(open(C["cleanup_edl"], encoding="utf-8"))["edits"]
            DEC = cleanup.parse_reply(C.get("cleanup_reply", ""))
            print(f"cleanup: {C['cleanup_edl']} reply {C.get('cleanup_reply', '') or '(none: AUTO edits only)'}")
        print(f"auto-trim profile {cut_profile} -> {cut_profiles.resolve(cut_profile)}")
    for c in C["clips"]:
        cid = c["id"]
        if args.only and args.only != cid:
            continue
        print(f"=== {cid}")

        windows = c.get("windows") or [[c["start"], c["end"]]]
        nodes = c.get("nodes", [])
        # auto_trim splits every window at its stumbles and pauses; each new
        # seam is an "auto" join with no card and a very short fade
        exp, titles, kinds = [], [], []
        for j, (lo, hi) in enumerate(windows):
            if j:
                t = nodes[j - 1] if j - 1 < len(nodes) else None
                # "~" = a full dissolve with no card, for joining separate
                # moments (a quote compilation) without announcing sections
                titles.append(t if t != "~" else None)
                kinds.append("fade" if t == "~" else "card" if t else "trim")
            parts = [[lo, hi]]
            if C.get("auto_trim"):
                res = cut_profiles.window(WORDS, EN, lo, hi, C.get("extra_cuts"), cut_profile, edits=EDL_EDITS,
                                          approve=DEC["approve"], keep=DEC["keep"], all_confirm=DEC["all_confirm"])
                parts = [list(p) for p in res["keep"]] or [[lo, hi]]
                trimmed = (hi - lo) - sum(b - a for a, b in parts)
                if res["cuts"]:
                    print(f"  window {lo:.1f}-{hi:.1f}: {len(res['cuts'])} auto cuts, -{trimmed:.1f}s")
            for k, w in enumerate(parts):
                if k:
                    titles.append(None)
                    kinds.append("auto")
                exp.append(w)
        windows, nodes = exp, titles
        carded = {j for j, title in enumerate(nodes, start=1) if title}
        specs = [(h[0], h[1], args.hook_speed, args.hook_gain) for h in c.get("hooks", [])]
        specs += [(w[0], w[1], args.body_speed, 0.0) for w in windows]
        n_hooks = len(specs) - len(windows)
        # hook joins and carded seams get the full dissolve; a silent redaction
        # gets a short one so it lands as a breath rather than a scene change
        fade_of = {"card": XFADE, "fade": XFADE, "trim": TRIM_FADE, "auto": AUTO_FADE}
        xfs = [0.0] + [XFADE if k <= n_hooks else fade_of[kinds[k - n_hooks - 1]]
                       for k in range(1, len(specs))]
        if n_hooks and EN is not None and C.get("hook_tail", True):
            # whisper word ends run early: end each hook after its last word's sounding tail,
            # plus the dissolve, so the fade never swallows that word (cleanup.extend_end)
            for k in range(n_hooks):
                h0, h1, spd, gain = specs[k]
                nh1, nf, info = cleanup.extend_end(WORDS, EN, h0, h1, xfs[k + 1], spd)
                specs[k] = (h0, nh1, spd, gain)
                xfs[k + 1] = nf
                if info:
                    print(f"  hook {k + 1}: {info}")

        raw = f"work/{cid}.raw.mp4"
        track_paths = ([f"work/{cid}.track.{g['name']}.json" for g in guests]
                       if guests else [f"work/{cid}.track.json"])
        reuse = args.reuse and os.path.exists(raw) and (
            args.no_track or all(os.path.exists(t) for t in track_paths))
        pieces = [dict(start=s0, end=s1, speed=spd, gain_db=gain, tag="hook" if k < n_hooks else "body")
                  for k, (s0, s1, spd, gain) in enumerate(specs)]
        fps = timeline_fps(src)
        # timing is deterministic (whole frames), so a reuse run plans without rendering
        tm = plan(pieces, xfs, fps).timemap
        if not reuse:
            render_timeline(src, pieces, xfs, fps, raw)
        items = tm.segments

        hook_end = items[n_hooks]["dst0"] if n_hooks else 0.0
        total = tm.duration
        print(f"  {n_hooks} hooks -> body at {hook_end:.2f}s, "
              f"{len(windows)} windows, total {total:.1f}s")
        if prof is not None:
            for w in P.check_length(prof, total):
                print(f"  WARN {w}")

        def src_to_final(t):
            """Source seconds -> (final seconds, piece index) through the body
            pieces of the TimeMap; (None, None) for material that was cut out."""
            f = tm.to_final(t, tag="body")
            if f is None:
                return None, None
            k = max(k for k, it in enumerate(items) if it["tag"] == "body"
                    and it["src0"] - 1e-6 <= t <= it["src1"] + 1e-6)
            return f, k

        if not reuse and not args.no_track:
            regions = [g["region"] for g in guests] if guests else [guest]
            # optional per-guest "search"/"upscale" for a small face, e.g. a
            # portrait phone video pillarboxed inside a wide tile
            extra = [(["--search", g["search"], "--upscale", str(g.get("upscale", 2))]
                      if g.get("search") else []) for g in guests] if guests else [[]]
            for reg, tp, ex in zip(regions, track_paths, extra):
                print("  " + sh([PY, script("track_face.py"), raw, "--region", reg,
                                 "--out", tp] + ex).strip())
            # the mask is only as good as its proof: every track must pass
            stickers = [g["sticker"] for g in guests] if guests else [args.sticker]
            if C.get("track_host"):
                # the host is not masked; this track only steers the crop
                print("  " + sh([PY, script("track_face.py"), raw, "--region", host,
                                 "--out", f"work/{cid}.track.host.json"]).strip())
            # verify with the same sticker geometry the renderer will use
            geo = []
            for kv in args.renderer_arg:
                k, _, v = kv.partition("=")
                if k in ("scale", "y-offset"):
                    geo += [f"--{k}", v]
            for tp, stk in zip(track_paths, stickers):
                out = sh([PY, script("verify_coverage.py"), "--track", tp,
                          "--sticker", stk] + geo)
                print("  " + out.strip().splitlines()[-2].strip() + " " + out.strip().splitlines()[-1].strip())

        subs = load_subs(C["whisper"], tm)
        # a carded seam hides its subtitles behind the card; a silent trim
        # only needs the dissolve itself kept clear
        blanks = [(items[n_hooks + j]["dst0"] - (1.0 if j in carded else 0.05),
                   items[n_hooks + j]["dst0"] + items[n_hooks + j]["xfade"]
                   + (1.0 if j in carded else 0.05))
                  for j in range(1, len(windows))
                  # auto-trims and quote dissolves carry speech right up to
                  # the join; blanking them would drop real lines
                  if kinds[j - 1] in ("card", "trim")]
        subs = [s for s in subs
                if not any(a < (s["start"] + s["end"]) / 2 < b for a, b in blanks)]
        tmap = C.get("translations")
        if tmap and os.path.exists(tmap):
            # English is keyed by the final Chinese text, so re-cutting the
            # timeline (which renumbers lines) never misaligns it
            en = json.load(open(tmap, encoding="utf-8"))
            miss = 0
            for ln in subs:
                ln["zh"] = ln["text"]
                ln["en"] = en.get(ln["text"], "")
                miss += not ln["en"]
            if miss:
                print(f"  WARN {miss} lines have no English")
        json.dump(subs, open(f"work/{cid}.subs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # the same lines as vstudio.subs.Cue dicts, for re-burning per platform with vstudio.export
        json.dump([dict(start=round(s["start"], 3), end=round(s["end"], 3), text=s.get("zh") or s["text"],
                        **({"alt": s["en"]} if s.get("en") else {})) for s in subs],
                  open(f"work/{cid}.cues.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {len(subs)} subtitle lines")

        tj = dict(c)
        # speaker labels: per clip, else top-level config, else the renderer default
        for key in ("guest_label", "host_label"):
            if not tj.get(key) and C.get(key):
                tj[key] = C[key]
        tj["hook_end"] = hook_end
        # a node card sits on each internal edit, centred in its dissolve
        # a null entry in `nodes` is a silent trim -- excise a few seconds
        # without announcing a section that did not change
        tj["node_cards"] = [[items[n_hooks + j]["dst0"] + XFADE / 2, title]
                            for j, title in enumerate(nodes, start=1) if title]

        # a panel may stay up across a silent trim -- nothing changed -- but
        # never across a node card, so a "section" runs between carded seams
        def section_end(i):
            """End of the run of windows starting at 0-based index i, walking
            forward over silent trims and stopping at the next node card."""
            k = i
            while k + 1 < len(windows) and (k + 1) not in carded:
                k += 1
            return items[n_hooks + k]["dst0"] + items[n_hooks + k]["dur"]

        panels = []
        for a, d, title, bullets in c.get("panels", []):
            fa, pm = src_to_final(a)
            if fa is None and C.get("auto_trim"):
                # the anchor fell into an auto-trimmed pause: open on the
                # next kept word instead
                nxt = [w[0] for w in windows if 0 < w[0] - a < 12.0]
                if nxt:
                    fa, pm = src_to_final(nxt[0])
            if fa is None:
                sys.exit(f"{cid}: panel '{title}' at {a}s is inside a cut, move it")
            # a panel must be gone before a node card arrives, or the frame
            # carries two cards at once
            limit = section_end(pm - n_hooks) - 0.4
            for nat, _ in tj["node_cards"]:
                if fa < nat:
                    limit = min(limit, nat - 1.9)
            panels.append([fa, min(d / args.body_speed, limit - fa), title, bullets])
            if panels[-1][1] < 4.0:
                print(f"  WARN panel '{title}' squeezed to {panels[-1][1]:.1f}s")
            near = [nat for nat, _ in tj["node_cards"] if 0 <= fa - nat < 2.5]
            if near:
                print(f"  WARN panel '{title}' opens {fa - near[0]:.1f}s after a "
                      f"node card; push its anchor later")
        # panels may now span silent trims, so two can collide; never let a
        # frame carry two 记笔记 cards
        panels.sort()
        for i in range(len(panels) - 1):
            if panels[i][0] + panels[i][1] > panels[i + 1][0] - 0.3:
                panels[i][1] = panels[i + 1][0] - 0.3 - panels[i][0]
                print(f"  WARN panel '{panels[i][2]}' trimmed to "
                      f"{panels[i][1]:.1f}s to clear the next one")
        tj["panels"] = panels
        # progress-bar chapters, authored in source seconds like everything else
        chs = []
        for a, label in c.get("chapters", []):
            fa, _ = src_to_final(a)
            if fa is None:
                nxt = [w[0] for w in windows if 0 < w[0] - a < 12.0]
                fa = src_to_final(nxt[0])[0] if nxt else None
            if fa is None:
                sys.exit(f"{cid}: chapter '{label}' at {a}s is inside a cut, move it")
            chs.append((fa, label))
        tj["chapters"] = [[chs[i][0], chs[i + 1][0] if i + 1 < len(chs) else total, lab]
                          for i, (_, lab) in enumerate(chs)]
        if chs:
            tj["chapters"][0][0] = hook_end       # the bar covers the whole body
        tj["total"] = total
        json.dump(tj, open(f"work/{cid}.title.json", "w", encoding="utf-8"), ensure_ascii=False)

        if guests:
            gj = [dict(g, track=tp) for g, tp in zip(guests, track_paths)]
            json.dump(gj, open(f"work/{cid}.guests.json", "w", encoding="utf-8"), ensure_ascii=False)
        spk_path = None
        if C.get("speakers") and guests:
            # who gets the big tile in render_trio's stage layout: speaker_timeline.py labels
            # (tile names = each guest's "name", and "host" or clips.json "host_speaker")
            host_lab = C.get("host_speaker", "host")
            valid = {g["name"] for g in guests} | {host_lab}
            times, labels = active_speaker.load(C["speakers"])
            raw_lab = active_speaker.to_final(times, labels, tm, total, valid=valid)
            raw_lab = ["host" if x == host_lab else x for x in raw_lab]
            act = active_speaker.smooth(raw_lab, default="host",
                                        min_run=float(C.get("speaker_min_run", 1.6)))
            spk_path = f"work/{cid}.speakers.json"
            json.dump({"step": active_speaker.STEP, "labels": act}, open(spk_path, "w"))
            sw = active_speaker.switches(act)
            print(f"  active speaker: {len(sw)} turns ("
                  + ", ".join(f"{t:.1f}s {x}" for t, x in sw[:8]) + (" ..." if len(sw) > 8 else "") + ")")
        if args.subs_only:
            print("  --subs-only: stopping before render")
            continue
        render_cmd = [PY, args.renderer, raw,
                      "--track", track_paths[0],
                      "--sticker", args.sticker,
                      "--subs", f"work/{cid}.subs.json",
                      "--title-json", f"work/{cid}.title.json",
                      "--guest-region", guest, "--host-region", host,
                      "--out", f"work/{cid}.novol.mp4"]
        if platform:
            render_cmd += ["--platform", platform]
        if nm is not None:
            render_cmd += ["--name-mask", nm["mode"], "--name-box", ",".join(str(v) for v in nm["box"]),
                           "--name-tiles", nm["tiles"]]
            if nm.get("extra"):
                render_cmd += ["--name-extra", ";".join(",".join(str(int(v)) for v in r) for r in nm["extra"])]
        if args.clean_master:
            render_cmd += ["--no-subs"]
        if guests:
            render_cmd += ["--guests-json", f"work/{cid}.guests.json"]
        if C.get("track_host"):
            render_cmd += ["--host-track", f"work/{cid}.track.host.json"]
        if args.no_mask:
            render_cmd += ["--no-mask"]
        if spk_path and os.path.basename(args.renderer) == "render_trio.py":
            render_cmd += ["--speakers", spk_path]
        for kv in args.renderer_arg:
            k, _, v = kv.partition("=")
            render_cmd += [f"--{k}", v]
        sh(render_cmd)

        # two-pass loudness to the persona's delivery target (-14 LUFS default),
        # then bt709 written into the h264 VUI itself (container flags alone leave
        # iOS guessing and shifting the colours) + faststart, all stream copy
        lufs = tp = None
        if prof is not None:
            lufs, tp = prof.loudness["lufs"], prof.loudness["tp"]
        audio.loudnorm_2pass(f"work/{cid}.novol.mp4", f"work/{cid}.ln.mp4", lufs=lufs, tp=tp if tp is not None else -1.5)
        final = f"out/{cid}.clean.mp4" if args.clean_master else f"out/{cid}.mp4"
        media.retag_bt709(f"work/{cid}.ln.mp4", final)
        print(f"  --> {final}")
        if args.clean_master:
            print(f"  multi-platform: python3 -m vstudio.export {final} --platforms xiaohongshu,douyin,youtube-shorts "
                  f"--cues work/{cid}.cues.json --out exports/{cid}")


if __name__ == "__main__":
    main()
