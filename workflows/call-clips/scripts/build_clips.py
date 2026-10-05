#!/usr/bin/env python3
"""Drive every clip in a clips.json end to end: hook montage + sped-up body ->
masked, subtitled, panelled, loudness-normalised mp4 (vertical, trio or landscape,
depending on --renderer).

The timeline is assembled BEFORE tracking, so the face track, the subtitles and
the note panels all live in the same final-frame space and cannot drift apart.

Pieces are cut from the source, each at its own speed, then dissolved together
with xfade/acrossfade. A dissolve of D seconds shortens the joint by D, so the
offset of piece k is sum(previous durations) - k*D.

Everything in clips.json is authored in SOURCE seconds; this script is the only
place that converts to final time.

Run from the project (video) directory; it writes work/ and out/ there:
  python3 $VSTUDIO/workflows/call-clips/scripts/build_clips.py --config clips.json [--only <id>]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from find_disfluencies import Audio, find_cuts, split_window
from vstudio.config import persona

PY = sys.executable
_CC = persona().get("call_clips") or {}
LUFS = (persona().get("audio") or {}).get("loudness_lufs", -14)


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


def cut_piece(src, start, end, speed, out, gain_db=0.0):
    """One timeline piece, already at its final speed."""
    af = f"atempo={speed:.4f}"
    if gain_db:
        af += f",volume={gain_db}dB"
    sh(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
        "-i", src,
        "-filter:v", f"setpts=PTS/{speed:.4f}",
        "-filter:a", af,
        "-c:v", "libx264", "-crf", "14", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k", "-y", out])
    return (end - start) / speed


def offsets_of(durs, xfs):
    """Where each piece starts in the dissolved output. Piece k's fade begins
    xfs[k] before the previous output ends, and that value is also exactly the
    `offset` xfade wants for that join. xfs[0] is unused."""
    out = [0.0]
    for k in range(1, len(durs)):
        out.append(out[-1] + durs[k - 1] - xfs[k])
    return out


CHUNK = 30


def dissolve(pieces, durs, xfs, out):
    """Chain pieces with xfade on video and acrossfade on audio. A long-form
    timeline has 150+ pieces, too many inputs for one filter graph, so it is
    dissolved in chunks and the chunks are then dissolved together. The offset
    maths is linear, so the result is identical to a single pass."""
    if len(pieces) > CHUNK:
        outs, odurs, oxfs = [], [], []
        for c0 in range(0, len(pieces), CHUNK):
            sl = slice(c0, c0 + CHUNK)
            o = f"{out[:-4]}.chunk{c0 // CHUNK}.mp4"
            sub_x = [0.0] + list(xfs[sl][1:])
            _dissolve(pieces[sl], durs[sl], sub_x, o)
            outs.append(o)
            odurs.append(sum(durs[sl]) - sum(sub_x[1:]))
            oxfs.append(xfs[c0] if c0 else 0.0)
        dissolve(outs, odurs, oxfs, out)
        return
    _dissolve(pieces, durs, xfs, out)


def _dissolve(pieces, durs, xfs, out):
    if len(pieces) == 1:
        subprocess.run(["cp", pieces[0], out], check=True)
        return
    args = []
    for p in pieces:
        args += ["-i", p]
    offs = offsets_of(durs, xfs)
    fc = []
    vcur, acur = "0:v", "0:a"
    for i in range(1, len(pieces)):
        fc.append(f"[{vcur}][{i}:v]xfade=transition=fade:duration={xfs[i]}:"
                  f"offset={offs[i]:.3f}[v{i}]")
        fc.append(f"[{acur}][{i}:a]acrossfade=d={xfs[i]}:c1=tri:c2=tri[a{i}]")
        vcur, acur = f"v{i}", f"a{i}"
    sh(["ffmpeg", "-v", "error"] + args + ["-filter_complex", ";".join(fc),
        "-map", f"[{vcur}]", "-map", f"[{acur}]",
        "-c:v", "libx264", "-crf", "14", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k", "-y", out])


TERM_FIX = None


MAX_CHARS = 18


def load_subs(whisper, pieces_meta, work_id):
    """Map whisper segments from source time into final timeline time."""
    import build_subs
    from build_subs import fix
    build_subs._load_persona_fixes()
    # per-recording term fixes live in clips.json, ahead of persona + shared list
    if TERM_FIX and not getattr(build_subs, "_extended", False):
        build_subs.TERM_FIX[:0] = [tuple(x) for x in TERM_FIX]
        build_subs._extended = True

    lines = []
    segs = json.load(open(whisper, encoding="utf-8"))["segments"]
    for pm in pieces_meta:
        s0, s1, spd, off = pm["start"], pm["end"], pm["speed"], pm["offset"]
        edge = pm["xf"] / 2 if pm["k"] else 0.0
        lo, hi = off + edge, off + pm["dur"] - (0.0 if pm["last"] else pm["xf"] / 2)
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
                txt = fix("".join(w["word"] for w in kept))
                t0, t1 = kept[0]["start"], kept[-1]["end"]
            else:
                txt = fix(s["text"])
                t0, t1 = s["start"], s["end"]
            if not txt:
                continue
            a = off + (max(t0, s0) - s0) / spd
            b = off + (min(t1, s1) - s0) / spd
            a, b = max(a, lo), min(b, hi)
            if b - a < 0.28:
                continue
            if lines and lines[-1]["end"] > a - 0.45 and \
                    len(lines[-1]["text"] + txt) <= MAX_CHARS and lines[-1]["piece"] == pm["k"]:
                prev = lines[-1]["text"]
                # "marketing" + "FDE" must not fuse into "marketingFDE"
                sep = " " if re.match(r"[A-Za-z0-9%]", prev[-1:]) and re.match(r"[A-Za-z]", txt) else ""
                lines[-1]["text"] = prev + sep + txt
                lines[-1]["end"] = b
                continue
            lines.append({"start": a, "end": b, "text": txt, "piece": pm["k"]})

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
    ap.add_argument("--sub-max-chars", type=int, default=18)
    ap.add_argument("--reuse", action="store_true",
                    help="skip cutting/dissolving/tracking when work files exist; "
                         "for restyling the frame without re-encoding the timeline")
    ap.add_argument("--subs-only", action="store_true",
                    help="stop after subs/title json, e.g. to add an English track before rendering")
    args = ap.parse_args()
    if args.no_mask:
        args.no_track = True

    global MAX_CHARS, TERM_FIX
    MAX_CHARS = args.sub_max_chars

    C = json.load(open(args.config, encoding="utf-8"))
    TERM_FIX = C.get("term_fix")
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

    global DURS, AUDIO, SEGS
    if C.get("auto_trim"):
        AUDIO = Audio(C["audio"])
        if isinstance(C.get("extra_cuts"), str):
            # a path: editor cuts reviewed separately, [[from, to, why], ...]
            C["extra_cuts"] = json.load(open(C["extra_cuts"], encoding="utf-8"))
        SEGS = json.load(open(C["whisper"], encoding="utf-8"))["segments"]
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
                cuts = find_cuts(AUDIO, SEGS, lo, hi, C.get("extra_cuts"))
                parts = split_window(lo, hi, cuts) or [[lo, hi]]
                trimmed = sum(b - a for a, b, _ in cuts)
                if cuts:
                    print(f"  window {lo:.1f}-{hi:.1f}: {len(cuts)} auto cuts, -{trimmed:.1f}s")
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

        raw = f"work/{cid}.raw.mp4"
        track_paths = ([f"work/{cid}.track.{g['name']}.json" for g in guests]
                       if guests else [f"work/{cid}.track.json"])
        reuse = args.reuse and os.path.exists(raw) and (
            args.no_track or all(os.path.exists(t) for t in track_paths))
        paths, durs = [], []
        for k, (s0, s1, spd, gain) in enumerate(specs):
            p = f"work/{cid}.p{k}.mp4"
            # durations are deterministic, so a reuse run can compute them
            durs.append((s1 - s0) / spd if reuse else cut_piece(src, s0, s1, spd, p, gain))
            paths.append(p)
        offs = offsets_of(durs, xfs)
        meta = [{"k": k, "start": s0, "end": s1, "speed": spd, "dur": durs[k],
                 "offset": offs[k], "xf": xfs[k], "last": k == len(specs) - 1}
                for k, (s0, s1, spd, _) in enumerate(specs)]

        if not reuse:
            dissolve(paths, durs, xfs, raw)

        hook_end = meta[n_hooks]["offset"] if n_hooks else 0.0
        total = meta[-1]["offset"] + meta[-1]["dur"]
        print(f"  {n_hooks} hooks -> body at {hook_end:.2f}s, "
              f"{len(windows)} windows, total {total:.1f}s")

        def src_to_final(t):
            """Source seconds -> final timeline seconds, via the window the
            time falls in. Returns None for material that was cut out."""
            for pm in meta[n_hooks:]:
                if pm["start"] <= t <= pm["end"]:
                    return pm["offset"] + (t - pm["start"]) / pm["speed"], pm
            return None, None

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

        subs = load_subs(C["whisper"], meta, cid)
        # a carded seam hides its subtitles behind the card; a silent trim
        # only needs the dissolve itself kept clear
        blanks = [(meta[n_hooks + j]["offset"] - (1.0 if j in carded else 0.05),
                   meta[n_hooks + j]["offset"] + meta[n_hooks + j]["xf"]
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
        tj["node_cards"] = [[meta[n_hooks + j]["offset"] + XFADE / 2, title]
                            for j, title in enumerate(nodes, start=1) if title]

        # a panel may stay up across a silent trim -- nothing changed -- but
        # never across a node card, so a "section" runs between carded seams
        def section_end(i):
            """End of the run of windows starting at 0-based index i, walking
            forward over silent trims and stopping at the next node card."""
            k = i
            while k + 1 < len(windows) and (k + 1) not in carded:
                k += 1
            return meta[n_hooks + k]["offset"] + meta[n_hooks + k]["dur"]

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
            limit = section_end(pm["k"] - n_hooks) - 0.4
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
        if guests:
            render_cmd += ["--guests-json", f"work/{cid}.guests.json"]
        if C.get("track_host"):
            render_cmd += ["--host-track", f"work/{cid}.track.host.json"]
        if args.no_mask:
            render_cmd += ["--no-mask"]
        for kv in args.renderer_arg:
            k, _, v = kv.partition("=")
            render_cmd += [f"--{k}", v]
        sh(render_cmd)

        # two-pass loudness to the persona's delivery target (-14 LUFS default)
        log = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", f"work/{cid}.novol.mp4",
             "-af", f"loudnorm=I={LUFS}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        m = json.loads(re.findall(r"\{[^{}]*input_i[^{}]*\}", log, re.S)[-1])
        sh(["ffmpeg", "-v", "error", "-i", f"work/{cid}.novol.mp4",
            "-af", f"loudnorm=I={LUFS}:TP=-1.5:LRA=11:measured_I={m['input_i']}:"
                   f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                   f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
            "-c:v", "copy", "-tag:v", "avc1",
            # write bt709 into the h264 VUI itself; container flags alone
            # leave iOS guessing and shifting the colours
            "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-y", f"out/{cid}.mp4"])
        print(f"  --> out/{cid}.mp4")


if __name__ == "__main__":
    main()
