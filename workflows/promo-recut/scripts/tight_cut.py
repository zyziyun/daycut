#!/usr/bin/env python3
"""Tight-cut a talking-head recording from a project config, with the shared speech-cleanup tool
(vstudio.cleanup: 气口 / fillers / repeats / restarts / merged fillers, word-safe frame-exact cuts).

  transcribe (whisper, word timestamps)  -> work/audio.json
  --suggest     cleanup.analyze on the KEEP spans (cut.body / cut.outro / cut.extra, snapped word-safe)
                -> work/cleanup.json (EDL) + work/cleanup_review.md: 待确认 CONFIRM / 自动删 AUTO / 气口 / 保留 KEEP.
                The creator answers it; put the answer in the config: cut.reply: "确认 3,5,9 / 保留 7"
  --draft-subs  print subtitle lines (raw seconds) from the words that survive the cleanup
  (default)     grade the raw, cleanup.apply per part (auto edits + cut.reply, never a CONFIRM row without a
                yes) -> work/body.mp4, outro.mp4, extra cuts (+ <part>.cleanup.json sidecars), loudnorm; the
                highlights montage with internal crossfades; work/layout.json (raw -> cut TimeMaps, word times)
  --verify      cleanup.verify every part: re-ASR, lost content words -> exit 1; leftover fillers / repeats listed

Legacy config keys still work, translated to cleanup decisions: cut.drop [a, b) (word START in the range)
approves the cleanup edit covering those words (else becomes a word-safe editor cut); cut.patch
[whisper_start, real_start] approves the matching merged-filler edit (else an editor cut up to real_start);
cut.pause_threshold / pad_in / pad_out -> cleanup pause_min / kept gap; cut.fillers -> fillers_extra.

Run from anywhere:  python3 $VSTUDIO/workflows/promo-recut/scripts/tight_cut.py promo.config.yaml [--suggest]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project, P, hook_speed  # noqa: E402
import screen_crop  # noqa: E402
from vstudio import asr, audio, cleanup, cut, media  # noqa: E402


def words_of(transcript):
    """Whisper-shaped words [{word, start, end}] (leading spaces kept, so English re-joins cleanly)."""
    return [dict(w) for s in transcript["segments"] for w in s.get("words", [])]


# ---------------------------------------------------------------- transcript
def transcribe(prj, src):
    return asr.transcribe(src, language=prj.get("language"), model=prj.get("whisper_model"),
                          cache=False, fix_terms=False)


def load_words(prj, force=False):
    js = prj.w("audio.json")
    if force or not os.path.exists(js):
        tr = transcribe(prj, prj.p(prj.cfg["talk"]))
        json.dump({k: tr[k] for k in ("language", "text", "segments") if k in tr}, open(js, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("transcript ->", js)
    return words_of(json.load(open(js, encoding="utf-8")))


def audio_wav(prj):
    wav = prj.w("audio.wav")
    if not os.path.exists(wav):
        media.extract_wav(prj.p(prj.cfg["talk"]), wav)
    return wav


# ---------------------------------------------------------------- config -> cleanup
def parts_of(prj):
    """{part name: KEEP spans (raw s)}: body, outro, then cut.extra."""
    parts = {"body": prj.get("cut.body", []) or [], "outro": prj.get("cut.outro", []) or []}
    parts.update(prj.get("cut.extra", {}) or {})
    return {k: [(float(a), float(b)) for a, b in v] for k, v in parts.items() if v}


def overrides_of(prj):
    """cleanup overrides: cut.cleanup {...} + the legacy tighten knobs and cut.fillers."""
    ov = dict(prj.get("cut.cleanup", {}) or {})
    if prj.get("cut.pause_threshold") is not None:
        ov.setdefault("pause_min", float(prj.get("cut.pause_threshold")))
    if prj.get("cut.pad_in") is not None or prj.get("cut.pad_out") is not None:
        g = float(prj.get("cut.pad_in", 0.06) or 0) + float(prj.get("cut.pad_out", 0.08) or 0)
        ov.setdefault("gap_min", g)
        ov.setdefault("gap_max", g)
    if prj.get("cut.fillers"):
        ov.setdefault("fillers_extra", list(prj.get("cut.fillers")))
    return ov


def snapped_parts(prj, cw=None, en=None):
    """KEEP spans made word-safe (cleanup.snap_range: never inside / into a neighbour word)."""
    parts = parts_of(prj)
    if cw is None:
        load_words(prj)
        cw = cleanup.load_words(prj.w("audio.json"))
    if en is None:
        en = cleanup.energy_of(audio_wav(prj), cw, [s for v in parts.values() for s in v],
                               prj.get("cut.profile"), overrides_of(prj))
    return {k: [cleanup.snap_range(cw, a, b, en) for a, b in v] for k, v in parts.items()}


def analyze(prj):
    """cleanup.analyze of the talk over the snapped KEEP spans -> work/cleanup.json + work/cleanup_review.md."""
    load_words(prj)
    parts = snapped_parts(prj)
    rg = [s for v in parts.values() for s in v]
    print("cleanup.analyze ->", prj.w("cleanup.json"))
    edl = cleanup.analyze(prj.p(prj.cfg["talk"]), transcript=prj.w("audio.json"), ranges=rg,
                          language=prj.get("language"), profile=prj.get("cut.profile"), overrides=overrides_of(prj),
                          out=prj.w("cleanup.json"), review=prj.w("cleanup_review.md"), force=True)
    edl["_parts"] = parts
    return edl


def _same_ranges(a, b):
    return len(a) == len(b) and all(abs(x[0] - y[0]) < 2e-3 and abs(x[1] - y[1]) < 2e-3 for x, y in zip(a, b))


def get_edl(prj):
    """The current EDL. Re-analyses when it is missing or the KEEP spans changed; refuses when the config already
    holds decisions by id (cut.reply / approve / keep_ids) for an EDL whose ids would change."""
    path = prj.w("cleanup.json")
    parts = snapped_parts(prj)
    want = cleanup.norm_ranges([s for v in parts.values() for s in v])
    if os.path.exists(path):
        edl = json.load(open(path, encoding="utf-8"))
        dur = edl["source"]["duration"]
        want = [(max(0.0, a), min(dur, b)) for a, b in want]
        if _same_ranges([tuple(r) for r in edl["ranges"]], want):
            edl["_parts"] = parts
            return edl
        if prj.get("cut.reply") or prj.get("cut.approve") or prj.get("cut.keep_ids"):
            raise SystemExit("the KEEP spans changed since work/cleanup.json was made, so its edit ids changed too: "
                             "run --suggest again and re-confirm cut.reply against the new work/cleanup_review.md")
    return analyze(prj)


def translate(edl, prj, en=None):
    """Config decisions -> (approve, keep, all_confirm, extra_cuts, notes).
    cut.reply / cut.approve / cut.keep_ids / cut.all_confirm are cleanup decisions as they are. Legacy cut.drop
    [a, b) approves every word edit whose words all start inside it; dropped words no edit covers become an
    editor cut between the neighbouring words (word-safe edges). Legacy cut.patch [whisper_start, real_start]
    approves the filler-merged edit with that patch, else an editor cut up to real_start."""
    r = cleanup.parse_reply(prj.get("cut.reply") or "")
    ap = set(r["approve"]) | {int(x) for x in prj.get("cut.approve", []) or []}
    kp = set(r["keep"]) | {int(x) for x in prj.get("cut.keep_ids", []) or []}
    allc = bool(r["all_confirm"] or prj.get("cut.all_confirm"))
    W = cleanup.load_words(edl["words"])
    extra, notes = [], []
    for a, b in prj.get("cut.drop", []) or []:
        idx = {w["i"] for w in W if a - 0.01 <= w["t"] < b - 0.01}
        if not idx:
            notes.append(f"drop [{a}, {b}): no word starts there - ignored")
            continue
        covered = set()
        for e in edl["edits"]:
            if e["words"] and set(e["words"]) <= idx:
                ap.add(e["id"])
                covered |= set(e["words"])
                notes.append(f"drop [{a}, {b}) -> approve #{e['id']} {e['kind']} '{e['text']}'")
        rest = sorted(idx - covered)
        groups = []
        for i in rest:
            if groups and i == groups[-1][-1] + 1:
                groups[-1].append(i)
            else:
                groups.append([i])
        for g in groups:
            first, last = W[g[0]], W[g[-1]]
            prev = W[g[0] - 1] if g[0] > 0 else None
            nxt = W[g[-1] + 1] if g[-1] + 1 < len(W) else None
            c0 = (prev["te"] + first["t"]) / 2 if prev else first["t"] - 0.05
            c1 = (last["te"] + nxt["t"]) / 2 if nxt else last["te"] + 0.1
            if en is not None and nxt:                  # the dropped word sounds past whisper's end: cut its tail too,
                lim = max(last["te"], nxt["t"])          # but never into the next word (no quiet run found in a short
                c1 = max(c1, min(cleanup.word_tail(en, last["te"], lim, quiet_run=0.03), lim))   # gap: stop at its start)
            c0 = cleanup.safe_edge(W, c0, en, side="end") if prev else c0
            c1 = cleanup.safe_edge(W, c1, en, side="start") if nxt else c1
            if c1 > c0:
                txt = "".join(W[i]["w"] for i in g)
                extra.append((round(c0, 3), round(c1, 3), f"drop:{txt}"))
                notes.append(f"drop [{a}, {b}) -> editor cut {c0:.2f}-{c1:.2f}s '{txt}' (no cleanup edit covers it)")
    for ws, rs in prj.get("cut.patch", []) or []:
        hit = [e for e in edl["edits"] if e.get("patch") and abs(e["patch"][0] - ws) < 0.05]
        if hit:
            ap.add(hit[0]["id"])
            notes.append(f"patch [{ws}, {rs}] -> approve #{hit[0]['id']} filler-merged '{hit[0]['text']}'")
            continue
        prev = [w for w in W if w["te"] <= ws + 0.01]
        c0 = max(ws, prev[-1]["te"] + 0.02) if prev else ws
        if rs - 0.02 > c0:
            extra.append((round(c0, 3), round(rs - 0.02, 3), "patch"))
            notes.append(f"patch [{ws}, {rs}] -> editor cut {c0:.2f}-{rs - 0.02:.2f}s (no merged-filler edit matched)")
    return ap, kp, allc, extra, notes


# ---------------------------------------------------------------- suggest
def suggest(prj):
    edl = analyze(prj)
    print(cleanup.review_sheet(edl))
    s = edl["stats"]
    print(f"\ncleanup: {s['auto']} auto, {s['confirm']} to confirm, {s['keep']} kept as real words; "
          f"{s['source_s']:.1f}s -> {s['auto_s']:.1f}s with the auto edits.  Sheet: {prj.w('cleanup_review.md')}")
    *_, notes = translate(edl, prj)
    for n in notes:
        print("  config:", n)
    for g0, g1, v in cut.voiced_gaps(words_of(json.load(open(prj.w("audio.json"), encoding="utf-8"))),
                                     audio_wav(prj)):
        print(f"  no-words {g0:8.2f}{g1:8.2f}  {v:.2f}s of speech with no transcript: ASR skipped it -"
              " listen; the cleanup keeps it whole")
    print("\nThe creator listens to the CONFIRM rows (ffplay -ss <t-0.5> -t 2 work/audio.wav) and answers;\n"
          "put the answer in the config:  cut.reply: \"确认 3,5,9 / 保留 7\"  (default: AUTO rows only).")


# ---------------------------------------------------------------- draft subtitles
def draft_subs(prj):
    maxc = P("subtitles.max_cjk_chars", 18)
    edl = get_edl(prj)
    ap, kp, allc, extra, _ = translate(edl, prj)
    W = cleanup.load_words(edl["words"])
    spans = edl["_parts"].get("body", []) + edl["_parts"].get("outro", [])
    ks = cleanup.keep_segments(edl["edits"], spans, ap, kp, allc, extra, words=W)
    keep = [w for w in W if any(a <= (w["t"] + w["te"]) / 2 <= b for a, b in ks)]
    lines, cur = [], []
    for w in keep:
        if cur and (w["t"] - cur[-1]["te"] > 0.25 or len("".join(c["w"] for c in cur)) >= maxc):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        t = asr.apply_term_fixes(cleanup.join_words(ln).strip())   # persona + generic fixes
        out.append([round(ln[0]["t"], 2), round(ln[-1]["te"], 2), t])
    print("[\n" + ",\n".join("  " + json.dumps(o, ensure_ascii=False) for o in out) + "\n]")
    print("\nEdit the text (punctuation, 【term】 highlights), split body vs outro, paste into subtitles.body / subtitles.outro.")


# ---------------------------------------------------------------- cut
def enc_args(crf=16):
    """H.264 + AAC args from vstudio.media's encoder selection (the bundled LGPL ffmpeg has no libx264:
    h264_videotoolbox there)."""
    return media.delivery_args(crf=crf, preset="fast", faststart=False)


def clean_cfr(src, workdir, fps=30):
    """A clean, zero-based, constant-frame-rate re-encode of `src` in workdir (cached): every frame re-timed
    N / rate, audio re-timed by sample count. Cures sources whose timestamps jump (e.g. joined with
    `concat -c copy`), on which trim-based assembly silently comes out short."""
    stem = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(workdir, f"{stem}.cfr.mp4")
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
        return out
    info = media.probe(src)
    fq = info.get("fps_q") or 0
    rate = f"{fq.numerator}/{fq.denominator}" if fq else str(fps)
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", src, "-map", "0:v:0", "-vf",
           f"setpts=N/({rate})/TB,fps={fps},format=yuv420p"]
    if info.get("has_audio"):
        cmd += ["-map", "0:a:0", "-af", "aresample=48000:async=1,asetpts=N/SR/TB"]
    tmp = out[:-4] + ".part.mp4"
    media.run(cmd + media.delivery_args(crf=14, preset="fast", audio=bool(info.get("has_audio")), faststart=False) + [tmp])
    os.replace(tmp, out)
    return out


def render_checked(asm, src, out, workdir, fps=30, what="montage", tol=0.5, args=None):
    """cut.render_assembly + a duration check against the plan (sum of clips - crossfades, +-tol s). A short
    (or long) render means the source's timestamps are not continuous: re-encode it to a clean CFR copy in
    workdir and retry once; still off -> a clear error. Returns the source actually used."""
    args = enc_args() if args is None else args
    cut.render_assembly(asm, [src], out, args=args)
    got = media.duration(out)
    if abs(got - asm.total) <= tol:
        return src
    print(f"  {what}: rendered {got:.2f}s but planned {asm.total:.2f}s (clips - crossfades): the source's timestamps "
          "look discontinuous; re-encoding it to a clean CFR copy and retrying")
    fixed = clean_cfr(src, workdir, fps)
    cut.render_assembly(asm, [fixed], out, args=args)
    got = media.duration(out)
    if abs(got - asm.total) > tol:
        raise SystemExit(f"{what}: rendered {got:.2f}s but planned {asm.total:.2f}s even from the clean re-encode "
                         f"{fixed}: check the clip times against the source length ({media.duration(src):.2f}s)")
    return fixed


def montage(src, clips, out, xf, scale, fps, lufs, workdir=None):
    """Highlights montage with internal dissolves (vstudio.cut.xfade_assemble, plain acrossfade:
    mute_pad=False keeps the old clip timing the step labels rely on) -> duration check -> two-pass loudnorm."""
    asm = cut.xfade_assemble(clips, xfade=xf, mute_pad=False, fps=fps, size=scale,
                             src_durations=[media.duration(src)])
    tmp = out[:-4] + ".raw.mp4"
    render_checked(asm, src, tmp, workdir or os.path.dirname(os.path.abspath(out)), fps,
                   args=media.delivery_args(crf=16, preset="fast", faststart=False, audio_bitrate="192k"))
    audio.loudnorm_2pass(tmp, out, lufs=lufs)
    os.remove(tmp)


# ---------------------------------------------------------------- hooks (the creator's picks, never auto)
def hook_items(prj):
    """Config hooks.items -> [{"spans": [(a, b)], "lines": [...]}] (raw seconds). Empty when not set."""
    out = []
    for k, it in enumerate((prj.get("hooks") or {}).get("items") or []):
        spans = it.get("spans") if isinstance(it, dict) else None
        if not spans:
            raise SystemExit(f"hooks.items[{k}]: needs spans: [[raw_start, raw_end], ...]")
        sp = [(float(a), float(b)) for a, b in spans]
        for a, b in sp:
            if b - a < 0.3:
                raise SystemExit(f"hooks.items[{k}]: span [{a}, {b}] is shorter than 0.3 s")
        lines = it.get("lines") or []
        out.append({"spans": sp, "lines": [lines] if isinstance(lines, str) else list(lines)})
    return out


def hook_plan(items, speed, fps=30):
    """Pieces for cut.xfade_assemble (hard cuts, every span at `speed`, 20/30 ms edge fades so nothing
    clicks) + which item each piece belongs to."""
    pieces, owner = [], []
    for k, it in enumerate(items):
        for a, b in it["spans"]:
            d = (b - a) / speed
            pieces.append(dict(start=a, end=b, speed=speed, tag="hook",
                               af=f"afade=t=in:d=0.02,afade=t=out:st={max(0.0, d - 0.03):.3f}:d=0.03"))
            owner.append(k)
    return pieces, owner


def hook_times(asm, owner, items):
    """[{s, e, lines}] per item in hooks.mp4 seconds (from the assembly's frame-exact offsets)."""
    out = []
    for k, it in enumerate(items):
        idx = [i for i, o in enumerate(owner) if o == k]
        s = asm.offsets[idx[0]]
        e = asm.offsets[idx[-1]] + asm.durations[idx[-1]]
        out.append({"s": round(s, 3), "e": round(e, 3), "lines": it["lines"]})
    return out


def build_hooks(prj, graded, fps, lufs, force=False):
    """work/hooks.mp4: the creator's hook picks (config hooks.items, in her order) cut from the graded raw with
    word-safe edges (cleanup.snap_range), sped up (hooks.speed, default format / persona hook speed), hard
    cuts. Returns (duration, [{s, e, lines}]) or (None, None) when no hooks are configured."""
    items = hook_items(prj)
    if not items:
        return None, None
    speed = hook_speed(prj)
    cw = cleanup.load_words(prj.w("audio.json"))
    spans = [s for it in items for s in it["spans"]]
    en = cleanup.energy_of(audio_wav(prj), cw, spans, prj.get("cut.profile"), overrides_of(prj))
    for it in items:
        it["spans"] = [cleanup.snap_range(cw, a, b, en) for a, b in it["spans"]]
    pieces, owner = hook_plan(items, speed, fps)
    out, meta = prj.w("hooks.mp4"), prj.w("hooks.json")
    sig = dict(items=items, speed=speed, fps=fps, lufs=lufs, src=os.path.getmtime(graded))
    if not force and os.path.exists(out) and os.path.exists(meta):
        old = json.load(open(meta, encoding="utf-8"))
        if old.get("sig") == json.loads(json.dumps(sig)):
            return old["duration"], old["items"]
    asm = cut.xfade_assemble(pieces, xfade=0.0, mute_pad=False, fps=fps, src_durations=[media.duration(graded)],
                             seek=True)
    tmp = out[:-4] + ".raw.mp4"
    render_checked(asm, graded, tmp, prj.work, fps, what="hooks")
    audio.loudnorm_2pass(tmp, out, lufs=lufs)
    os.remove(tmp)
    times = hook_times(asm, owner, items)
    dur = media.duration(out)
    json.dump(dict(sig=sig, duration=dur, items=times), open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  hooks: {len(items)} picks at {speed:g}x -> {dur:.2f}s  {out}")
    return dur, times


def cut_part(edl, spans, graded, out, decisions, lufs, fps, force=False):
    """cleanup.apply of one part (its KEEP spans) on the graded raw -> out (+ out's .cleanup.json sidecar),
    then a two-pass loudnorm voice stem. Returns the apply result (timemap = raw -> cut file)."""
    ap, kp, allc, extra = decisions
    part = {k: v for k, v in edl.items() if not k.startswith("_")}
    part["ranges"] = [list(s) for s in spans]
    res = cleanup.apply(part, approve=ap, keep=kp, all_confirm=allc, extra_cuts=extra, out=out, media_path=graded,
                        fps=fps, force=force)
    if not res["reused"]:
        tmp = out[:-4] + ".raw.mp4"
        os.replace(out, tmp)
        audio.loudnorm_2pass(tmp, out, lufs=lufs)
        os.remove(tmp)
    return res


def do_cut(prj, args):
    fps = P("export.fps", 30)
    voice = P("audio.voice_lufs", -16)
    talk = prj.p(prj.cfg["talk"])
    graded = prj.w("raw_graded.mp4")
    if args.regrade or not os.path.exists(graded):
        vf = [f"fps={fps}"]
        hdr = prj.get("hdr_tonemap")
        if hdr:   # true = force, "auto" = only when the source is HLG/PQ
            tone = media.hdr_to_sdr_args(talk, force=hdr is True)
            if tone:
                vf.append(tone)
        if prj.get("grade"):
            vf.append(prj.get("grade"))
        vf.append("format=yuv420p")
        media.run(["ffmpeg", "-y", "-i", talk, "-vf", ",".join(vf),
                   *media.delivery_args(crf=14, preset="fast", faststart=False, audio_bitrate="192k"), graded])

    edl = get_edl(prj)
    en = cleanup.energy_of(audio_wav(prj), edl["words"], edl["ranges"], edl["profile"], overrides_of(prj))
    ap, kp, allc, extra, notes = translate(edl, prj, en)
    for n in notes:
        print("  config:", n)
    layout = {"D": {}, "maps": {}, "words": {}, "cleanup": {}}
    for name, spans in edl["_parts"].items():
        out = prj.w(f"{name}.mp4")
        res = cut_part(edl, spans, graded, out, (ap, kp, allc, extra), voice, fps, force=args.regrade)
        side = json.load(open(res["sidecar"], encoding="utf-8"))
        layout["D"][name] = media.duration(out)
        layout["maps"][name] = res["timemap"].to_list()        # vstudio.cut.TimeMap items (raw -> cut file)
        layout["words"][name] = [dict(w=w["w"], t=w["t"], te=w["te"], raw=w["src"]) for w in side["words"]]
        layout["cleanup"][name] = dict(applied=res["applied"], sidecar=os.path.basename(res["sidecar"]))
        print(f"  {name}: {len(res['keep'])} segments, {len(res['applied'])} cleanup edits -> {layout['D'][name]:.2f}s")

    m = prj.get("montage") or {}
    if m.get("clips"):
        clips = [(c[0], c[1]) for c in m["clips"]]
        out = prj.w("montage.mp4")
        hsrc, crop = screen_crop.clean(prj.p(prj.cfg["highlights"]), m.get("crop"), prj.work)   # privacy crop
        stamp = prj.w("montage.src")
        want = f"{hsrc}|{crop}"
        stale = open(stamp).read() != want if os.path.exists(stamp) else crop is not None
        if args.remontage or not os.path.exists(out) or stale:
            montage(hsrc, clips, out, m.get("crossfade", 0.3), m.get("scale", "1920:1080"), fps, voice - 1, prj.work)
            open(stamp, "w").write(want)
        layout["D"]["montage"] = media.duration(out)
        layout["clips"] = [[c[0], c[1]] for c in clips]
    hd, ht = build_hooks(prj, graded, fps, voice, force=args.regrade or args.rehook)
    if hd:
        layout["D"]["hooks"] = hd
        layout["hooks"] = ht
    json.dump(layout, open(prj.w("layout.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("layout ->", prj.w("layout.json"), {k: round(v, 2) for k, v in layout["D"].items()})
    print("Next: python3 tight_cut.py <config> --verify   (ASR the cut, listen to every join)")
    return layout


def verify(prj, transcriber=None):
    """cleanup.verify of every cut part (re-ASR vs the words that should remain). Returns the number of lost spans."""
    missing = 0
    for name in parts_of(prj):
        f = prj.w(f"{name}.mp4")
        if not os.path.exists(f) or not os.path.exists(prj.w(f"{name}.cleanup.json")):
            continue
        print(f"\n=== {name} ({media.duration(f):.2f}s) ===")
        rep = cleanup.verify(f, transcriber=transcriber or (lambda p: transcribe(prj, p)))
        for x in rep["leftovers"]:
            print(f"  ! leftover @{x['t_out']:.2f}s '{x['text']}': {x['why']}")
        for x in rep["missing"]:
            print(f"  ! {x['kind']} '{x['text']}' raw {x['t_src']:.2f}s / cut {x['t_out']}s")
        missing += len(rep["missing"])
    if missing:
        print(f"\n{missing} span(s) lost speech: add 保留 N for the edit that covers it to cut.reply "
              "(or remove the cut.drop / cut.patch entry) and re-cut.")
    return missing


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("config", help="project config (JSON or YAML); paths inside are relative to its folder")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--suggest", action="store_true", help="cleanup.analyze -> work/cleanup_review.md and exit")
    g.add_argument("--draft-subs", action="store_true", help="print subtitle lines from kept words and exit")
    g.add_argument("--verify", action="store_true", help="re-ASR the cut files, flag lost words (exit 1)")
    ap.add_argument("--retranscribe", action="store_true", help="re-run whisper on the raw recording")
    ap.add_argument("--regrade", action="store_true", help="re-render work/raw_graded.mp4 (and the cut parts)")
    ap.add_argument("--remontage", action="store_true", help="re-render work/montage.mp4")
    ap.add_argument("--rehook", action="store_true", help="re-render work/hooks.mp4 (hooks.items)")
    a = ap.parse_args()
    prj = Project(a.config)
    if a.verify:
        return 1 if verify(prj) else 0
    load_words(prj, a.retranscribe)
    if a.suggest:
        return suggest(prj)
    if a.draft_subs:
        return draft_subs(prj)
    do_cut(prj, a)


if __name__ == "__main__":
    sys.exit(main())
