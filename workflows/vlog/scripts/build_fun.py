#!/usr/bin/env python3
"""Fun, fast-paced travel vlog ("style": "fun" in edit.json): beat-cut montage with speed ramps, whip /
zoom-punch / flash / light-leak / glitch transitions, title pop, location tags, day stamps, date stamps,
word pops, a route map card, photo inserts, talking-to-camera speech with captions, SFX and a ducked
music bed - sized for one platform profile.

    python3 build_fun.py work/edit.json                       # render work/<out>
    python3 build_fun.py work/edit.json --platform youtube    # override the edit.json platform
    python3 build_fun.py work/edit.json --dry-run             # plan + report only (no render)
    python3 build_fun.py work/edit.json --clean-master        # also a caption-free master + cues.json/.srt

Outputs (next to ``out``): <stem>.mp4 (music + voice + SFX), <stem>.nomusic.mp4 (voice + SFX, A13),
<stem>.report.json (beat grid, cuts + beats.verify, transitions, hits, overlays with boxes, cue sheet,
loudness, warnings), <stem>.cues.json/.srt when there is speech, <stem>.clean.mp4 with --clean-master.
Schema, knobs and the aesthetic rules applied: ../WORKFLOW.md ("Fun style").
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os
import re
import subprocess
import time

import numpy as np

from vstudio import audio as A
from vstudio import beats as BT
from vstudio import media
from vstudio import platform as P
from vstudio.config import persona

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from funvlog import frames as FR  # noqa: E402
from funvlog import gfx as G  # noqa: E402
from funvlog import mix as MX  # noqa: E402
from funvlog.plan import Planner, music_origin  # noqa: E402


def vlog_persona():
    return persona().get("vlog", {}) or {}


def default_platform():
    d = (persona().get("platforms") or {}).get("default") or "xiaohongshu"
    d = str(d).split(",")[0].strip()
    if ":" in d:
        return d
    try:
        P.profile(d, "full")
        return f"{d}:full"
    except KeyError:
        return d


def resolve_profile(cfg, override=None):
    spec = override or cfg.get("platform") or default_platform()
    prof = P.profile(spec)
    if cfg.get("res"):                                     # explicit canvas wins (kept for old configs)
        w, h = (int(v) for v in cfg["res"])
        prof = P.profile(spec, overrides=dict(w=w, h=h)) if (w, h) != (prof.w, prof.h) else prof
    return prof


class Writer:
    def __init__(self, path, W, H, fps, vargs):
        cmd = [media.ffmpeg_bin(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
               "-r", str(fps), "-i", "-", *vargs, "-an", path]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.path, self.n = path, 0

    def write(self, img):
        self.p.stdin.write(np.ascontiguousarray(img).tobytes())
        self.n += 1

    def close(self):
        self.p.stdin.close()
        err = self.p.stderr.read().decode("utf-8", "replace")
        if self.p.wait() != 0:
            raise media.FFmpegError(f"encode failed for {self.path}:\n{err[-1500:]}")


def build_elements(cfg, g, tl, cuts, meta, pl, fps):
    """Overlay elements + the reveal events they imply for the cue sheet."""
    els, reveals = [], []
    P_ = pl.period
    title = cfg.get("title")
    intro_t = pl.bt(meta["intro_n"])
    t_next = intro_t
    if title:
        tt = title if isinstance(title, dict) else dict(text=str(title))
        hold = max(1.2, float(tt.get("hold", 3 * P_)))
        e = G.TitlePop(g, tt["text"], intro_t, hold=hold, sub=tt.get("sub"))
        els.append(e)
        reveals.append(dict(t=intro_t + 0.05, kind="text", note="title pop"))
        t_next = e.t1
    mp = cfg.get("map")
    slot = next((s for s in tl if s.get("map_slot")), None)
    if mp and slot is not None:
        e = G.MapCard(g, mp["places"], slot["t0"], slot["t1"], title=mp.get("title"))
        els.append(e)
        for k, pt in enumerate(e.pin_times):
            reveals.append(dict(t=pt, kind="tick", note=f"map pin {k + 1}"))
        reveals.append(dict(t=slot["t0"] + 0.1, kind="move", note="map card slides in"))
    seen_place, seen_day = None, None
    last_tag, last_day = None, None
    word_slots = []

    def cut_short(prev, new, tail):
        """The previous corner element leaves before the next one lands (no stacked tags)."""
        if prev is not None and prev.t1 > new.t0:
            prev.hold = max(0.3, new.t0 - prev.t0 - tail - 0.02)
            prev.t1 = prev.t0 + prev.hold + tail
    for s in tl:
        if s["role"] != "body":
            continue
        if s.get("place") and s.get("place") != seen_place:
            e = G.LocationTag(g, s["place"], s["t0"] + 0.12)
            cut_short(last_tag, e, 0.35 + 0.25)
            last_tag = e
            els.append(e)
            reveals.append(dict(t=e.t0 + 0.2, kind="item", note=f"location tag {s['place']}"))
        seen_place = s.get("place") or seen_place
        if s.get("day") is not None and s.get("day") != seen_day:
            lab = s.get("day_label") or f"{cfg.get('day_word', 'DAY')} {s['day']}"
            e = G.DayStamp(g, lab, s["t0"] + 0.1)
            cut_short(last_day, e, 0.2)
            last_day = e
            els.append(e)
            reveals.append(dict(t=e.t0 + 0.1, kind="stamp", note=f"{lab} stamp"))
            seen_day = s["day"]
        if s.get("date"):
            els.append(G.DateStamp(g, str(s["date"]), s["t0"], s["t1"]))
        if s.get("pop"):
            e = G.WordPop(g, str(s["pop"]), s["t0"], hold=max(0.6, 2 * P_ - 0.1), k=len(word_slots))
            els.append(e)
            word_slots.append(e)
            reveals.append(dict(t=e.t0, kind="item", note=f"word pop {s['pop']}"))
        if s["kind"] == "photo":
            reveals.append(dict(t=s["t0"], kind="photo", note="photo insert"))
        if s.get("freeze"):
            reveals.append(dict(t=s["t1"] - s["freeze_s"], kind="photo", note="photo freeze"))
    # auto word pops on bar lines of broll montage shots, away from other centred text
    words = list(cfg.get("word_pops") or [])
    if words:
        busy = [(e.t0 - 0.2, e.t1 + 0.2) for e in els if e.kind in ("title", "map", "word")]
        last = -1e9
        for s in tl:
            if not words:
                break
            if s["role"] != "body" or s.get("speech") or s["kind"] == "photo":
                continue
            n = s["n0"] if pl.is_bar(s["n0"]) else pl.next_bar(s["n0"])
            if n >= s["n0"] + s["nb"]:
                continue
            t = pl.bt(n)
            hold = max(0.6, 2 * P_ - 0.1)
            if t - last < 8 * P_ or any(a < t + hold and t < b for a, b in busy):
                continue
            e = G.WordPop(g, words.pop(0), t, hold=hold, k=len(word_slots))
            els.append(e)
            word_slots.append(e)
            reveals.append(dict(t=t, kind="item", note="word pop"))
            last = t
    end = cfg.get("end_card")
    if end and meta.get("outro_n") is not None:
        ed = end if isinstance(end, dict) else dict(text=str(end))
        t0 = max(pl.bt(meta["outro_n"] + 4), pl.bt(meta["n_end"]) - 3.0)
        els.append(G.EndCard(g, ed["text"], t0, pl.bt(meta["n_end"]) + 1.0, sub=ed.get("sub")))
        reveals.append(dict(t=t0 + 0.05, kind="text", note="end card"))
    if meta.get("finale_n") is not None:
        reveals.append(dict(t=pl.bt(meta["finale_n"]), kind="finale", note="finale"))
    G.resolve_collisions(els, g)                       # layout-aware: tags / stamps of any kind never overlap
    order = {"map": 0, "end": 0, "title": 2, "word": 3, "location": 4, "day": 4, "date": 4}
    els.sort(key=lambda e: order.get(e.kind, 5))
    return els, reveals


def cut_events(cuts):
    sfx = {"whip": "whip", "zoom": "landing", "leak": "scene", "glitch": "zoom", "flash": "landing"}
    out = []
    for c in cuts:
        if c["kind"] == "zoom" and c["reason"] == "finale":
            continue                                   # the finale reveal carries riser -> impact -> sparkle
        if c["kind"] == "leak" and c["reason"] == "photo":
            continue                                   # the photo's shutter is its sound
        if c["kind"] in sfx:
            out.append(dict(t=c["t"], kind=sfx[c["kind"]], note=f"{c['kind']} ({c['reason']})"))
    return out


def captions(tl, prof):
    """Timeline cues from the speech shots' words (subs.cues_from_words), clipped to their shots. Words go
    through the shot's kept pieces with ``cleanup.timemap`` + ``cleanup.remap_words`` (cut words drop out)."""
    from vstudio import cleanup as CL
    from vstudio import subs
    cues = []
    for s in tl:
        if not s.get("speech") or not s.get("words"):
            continue
        tw = [dict(w=w["w"], t=s["t0"] + w["t"], te=s["t0"] + w["te"])
              for w in CL.remap_words(s["words"], CL.timemap(s["pieces"]))]
        if not tw:
            continue
        cjk = any(ord(ch) >= 0x2E80 for w in tw for ch in w["w"])
        mc = prof.caption["max_chars_zh"] if cjk else prof.caption["max_chars_en"]
        for c in subs.cues_from_words(tw, max_chars=mc):
            if not cjk:                                # latin: "word,word" -> "word, word"
                c.text = re.sub(r"([,.!?;:])(?=[A-Za-z0-9])", r"\1 ", c.text)
            c.end = min(c.end, s["t1"] - 0.02)
            if c.end > c.start:
                cues.append(c)
    return cues


def render(cfg, base, out, prof, pl, tl, cuts, meta, els, cues, clean, report, preset):
    fps = pl.fps
    W, H = prof.w, prof.h
    g_unit = min(W, H) / 1080.0
    enc = dict(prof.encode)
    vargs = media.delivery_args(crf=enc.get("crf"), preset=preset, audio=None, faststart=False,
                                maxrate=enc.get("maxrate"), bufsize=enc.get("bufsize"))
    stem = os.path.splitext(out)[0]
    w_main = Writer(stem + ".video.mp4", W, H, fps, vargs)
    w_clean = Writer(stem + ".clean.video.mp4", W, H, fps, vargs) if clean else None
    cap = None
    if cues:
        from vstudio import export as X
        cap = X.caption_overlay(prof, cues, fps)
    fx = {}
    for c in cuts:
        pre, post = FR.trans_frames(c["kind"], fps)
        for f in range(c["frame"] - pre, c["frame"] + post):
            fx.setdefault(f, []).append(c)
    grade = {**FR.DEFAULT_FUN_GRADE, **(vlog_persona().get("fun_grade") or {}), **(cfg.get("grade") or {})}
    fit_cache = {}
    safe = P.safe_box(prof)
    mode = cfg.get("reframe", "face")
    fallback = cfg.get("reframe_fallback", "pad-blur")
    photo_k = 0
    report["shots"] = []
    t_start = time.time()
    for s in tl:
        n = s["f1"] - s["f0"]
        if n <= 0:
            continue
        rinfo = {}
        if s["kind"] == "photo":
            img = FR.load_photo(s["src"], pl.cache)
            gen = FR.photo_frames(img, n, W, H, g_unit, style=s.get("style", cfg.get("photo_style", "card")),
                                  k_index=photo_k, fps=fps)
            photo_k += 1
        else:
            if s.get("speech"):
                times = FR.piece_times(s["pieces"], n, fps)
            else:
                live_n = n - int(round(s.get("freeze_s", 0.0) * fps)) if s.get("freeze") else n
                times = FR.ramp_times(s["ramp_keys"], max(1, live_n) / fps, max(1, live_n), s["start"])
                if live_n < n:
                    times = np.concatenate([times, np.full(n - live_n, times[-1] if len(times) else s["start"])])
            hdr_mode = cfg.get("hdr", "auto")
            vf = ""
            if hdr_mode not in (False, "false"):
                vf = media.hdr_to_sdr_args(s["src"], transfer=media.probe(s["src"])["transfer"],
                                           force=hdr_mode in (True, "true"))
            vf = ",".join(x for x in (vf, FR.grade_chain(grade, cfg.get("warm", True), cfg.get("sharpen", True),
                                                          float(s.get("bright", 0.0)))) if x)
            fmode = s.get("fit") or mode
            fa = dict(mode=fmode, fallback=fallback, safe=safe, cache=fit_cache)
            ff = int(n - round(s.get("freeze_s", 0.0) * fps)) if s.get("freeze") else None
            gen = FR.video_shot_frames(s["src"], times, W, H, fa, vf=vf, blend=cfg.get("blend_slowmo", True),
                                       freeze_from=ff, card=FR.card_renderer(W, H, g_unit) if ff else None,
                                       report=rinfo)
        k = -1
        for k, img in enumerate(gen):
            if k >= n:
                break
            f = s["f0"] + k
            if not img.flags.writeable:
                img = img.copy()
            if s.get("bg_blur"):
                img = FR.soft_bg(img)
            for c in fx.get(f, ()):
                img = FR.apply_transition(img, c["kind"], f - c["frame"], fps, c.get("dir", 1), seed=c["i"])
            t = f / fps
            for e in els:
                if e.active(t):
                    e.draw(img, t)
            if w_clean:
                w_clean.write(img)
            if cap:
                cap(f, t, img)
            w_main.write(img)
        while k < n - 1:                                   # never short: hold the last frame
            k += 1
            w_main.write(img)
            if w_clean:
                w_clean.write(img)
        report["shots"].append(dict(role=s["role"], kind=s["kind"], src=os.path.basename(s["src"]),
                                    t0=round(s["t0"], 4), t1=round(s["t1"], 4), frames=n, beats=s["nb"],
                                    window=[round(v, 3) for v in s.get("src_span", ())] or None,
                                    speech=bool(s.get("speech")), ramp=s.get("ramp"), auto=bool(s.get("auto")),
                                    section=s.get("section"), reframe=rinfo or None))
        print(f"  [{s['role']:6s}] {os.path.basename(s['src'])[:28]:28s} {s['t0']:6.2f}-{s['t1']:6.2f}s "
              f"{s['nb']:2d} beats {rinfo.get('mode_used', s['kind'])}", flush=True)
    w_main.close()
    if w_clean:
        w_clean.close()
    report["render_s"] = round(time.time() - t_start, 1)
    return w_main.path, (w_clean.path if w_clean else None), w_main.n


def accent_pieces(cfg, tl, warnings):
    """``keep_audio`` (per shot, or top-level default): the native sound of a non-speech video shot kept as
    an accent under the music. true = -8 dB under the persona voice level, a number = that offset in dB.
    Constant-speed shots only (0.5-2x, atempo); ramped shots are skipped with a warning; a freeze is silent."""
    out = []
    for s in tl:
        ka = s.get("keep_audio", cfg.get("keep_audio", False))
        if ka is False or ka is None or s["kind"] != "video" or s.get("speech") or s.get("map_slot"):
            continue
        name = os.path.basename(s["src"])
        if not media.probe(s["src"])["has_audio"]:
            continue
        keys = s.get("ramp_keys") or []
        rates = {round(float(r), 4) for _, r in keys} or {float(s.get("speed", 1.0))}
        if len(rates) > 1:
            warnings.append(f"{name}: keep_audio skipped on a speed-ramped shot")
            continue
        rate = rates.pop()
        if not 0.5 <= rate <= 2.0:
            warnings.append(f"{name}: keep_audio skipped at {rate:g}x (atempo needs 0.5-2x)")
            continue
        a, b = s["src_span"]
        gain = -8.0 if ka is True else float(ka)
        out.append(dict(src=s["src"], a=float(a), b=float(b), t=s["t0"], rate=rate, gain_db=gain))
    return out


def mux(video, wav, out, T):
    br = str((persona().get("export") or {}).get("audio_bitrate", "192k"))
    media.run([media.ffmpeg_bin(), "-y", "-i", video, "-i", wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
               "-c:a", "aac", "-b:a", br, "-ar", str(A.SR), "-ac", "2", "-t", f"{T:.4f}", "-movflags", "+faststart",
               out])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fun / fast-paced travel vlog from an edit.json with style: fun.")
    ap.add_argument("config", help="edit.json (style: fun)")
    ap.add_argument("--platform", help="platform[:orientation] (default: edit.json platform, else persona "
                                       "platforms.default in its full-screen vertical orientation)")
    ap.add_argument("--clean-master", action="store_true", help="also write a caption-free master + cues for "
                                                                "python -m vstudio.export")
    ap.add_argument("--dry-run", action="store_true", help="plan and write the report only")
    ap.add_argument("--preset", default=None, help="x264 preset (default edit.json preset or medium)")
    ap.add_argument("--no-asr", action="store_true", help="never run whisper (transcript files / loudness only)")
    a = ap.parse_args(argv)

    base = os.path.dirname(os.path.abspath(a.config))
    with open(a.config) as f:
        cfg = json.load(f)
    if a.no_asr:
        cfg["asr"] = False
    out = os.path.join(base, os.path.expanduser(cfg.get("out", "fun_vlog.mp4")))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stem = os.path.splitext(out)[0]
    cache = os.path.join(os.path.dirname(out), "fun_cache")
    os.makedirs(cache, exist_ok=True)
    prof = resolve_profile(cfg, a.platform)
    fps = int(cfg.get("fps") or prof.fps.get("default", 30))
    warnings = []

    music = cfg.get("music")
    if not music:
        raise SystemExit("fun style needs \"music\" (the cuts follow its beat grid)")
    music = os.path.join(base, os.path.expanduser(music))
    print(f"[fun] platform {prof.key} {prof.w}x{prof.h} @ {fps} fps; analysing {os.path.basename(music)}", flush=True)
    b = BT.analyze(music)
    b.save(os.path.join(cache, "beats.json"))
    m0 = music_origin(b, cfg.get("music_start", "auto"))
    cfg["_m0"] = m0
    bv = b.shift(-m0)                                    # music time -> video time
    if not b.grid_ok:
        warnings.append(f"beat grid not linear (p90 residual {b.residual_p90_ms:.0f} ms): cuts follow tracked beats")
    pl = Planner(cfg, base, prof, bv, fps, cache, warnings)
    tl, cuts, meta = pl.plan()
    T = pl.bt(meta["n_end"])
    music_avail = b.duration - m0
    if T > music_avail + 0.05:
        warnings.append(f"timeline {T:.1f}s is longer than the music after its start ({music_avail:.1f}s): the bed "
                        "loops and cuts past the end follow the extrapolated grid; trim shots or pick a longer track")
    warnings += P.check_length(prof, T)
    safe, capbox = P.safe_box(prof), P.caption_box(prof)
    g = G.Geometry(prof, safe, capbox)
    els, reveals = build_elements(cfg, g, tl, cuts, meta, pl, fps)
    cue_sheet = A.cue_sheet_for(cut_events(cuts), reveals, kind="travel-fun", beats=bv) if cfg.get("sfx", True) else []
    cap_cues = captions(tl, prof) if cfg.get("captions", True) else []
    cut_times = [c["t"] for c in cuts]
    ver = BT.verify(cut_times, bv, tol_frames=1, fps=fps) if cut_times else dict(ok=True, rows=[])
    report = dict(config=os.path.abspath(a.config), platform=prof.key, canvas=[prof.w, prof.h], fps=fps,
                  duration=round(T, 4), frames=int(round(T * fps)), music=os.path.basename(music),
                  bpm=round(float(b.bpm), 3), grid_ok=bool(b.grid_ok), music_start=round(m0, 4),
                  period=round(pl.period, 5), unit_beats=pl.u, safe_box=list(safe), caption_box=list(capbox),
                  arc=meta["arc"], hook_end=round(pl.bt(meta["hook_end"]), 4),
                  finale=round(pl.bt(meta["finale_n"]), 4) if meta.get("finale_n") is not None else None,
                  drops=[round(pl.bt(d), 4) for d in meta.get("drops_used", [])], hits=meta["hits"],
                  cuts=cuts, verify=dict(ok=ver["ok"], max_abs_frames=ver.get("max_abs_frames", 0.0),
                                         mean_abs_ms=ver.get("mean_abs_ms", 0.0), bad=ver.get("bad", [])),
                  elements=[e.info() for e in els], cue_sheet=cue_sheet,
                  captions=[c.to_dict() for c in cap_cues], speech=pl.speech_log, warnings=warnings,
                  whip=dict(zip(("frames_per_side", "travel_px", "peak_px_per_frame"),
                                [round(v, 1) for v in FR.whip_params(prof.w, fps)])))
    rp = stem + ".report.json"
    if cap_cues:
        from vstudio import subs
        with open(stem + ".cues.json", "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cap_cues], f, ensure_ascii=False, indent=1)
        subs.srt_write(cap_cues, stem + ".srt")
    print(f"[fun] {len(tl)} shots, {len(cuts)} cuts, {T:.2f}s at {b.bpm:.1f} BPM (music from {m0:.2f}s); "
          f"beat check: max {report['verify']['max_abs_frames']:.2f} frames", flush=True)
    if a.dry_run:
        report["dry_run"] = True
        _dump(rp, report)
        for w in warnings:
            print("WARN", w)
        print(rp)
        return report
    preset = a.preset or cfg.get("preset", "medium")
    vid, vclean, nfr = render(cfg, base, out, prof, pl, tl, cuts, meta, els, cap_cues, a.clean_master, report, preset)
    pieces = []
    for s in tl:
        if s.get("speech"):
            off = 0.0
            for x0, x1 in s["pieces"]:
                pieces.append(dict(src=s["src"], a=x0, b=x1, t=s["t0"] + off))
                off += x1 - x0
    accents = accent_pieces(cfg, tl, warnings)
    mixd = MX.build_mix(os.path.join(cache, os.path.basename(stem) + "_audio"), T, music, m0, pieces, cue_sheet, prof,
                        music_lufs=float(cfg.get("music_lufs", vlog_persona().get("fun_music_lufs", -19))),
                        duck_db=float(cfg.get("duck_db", -12)), fade_out=float(cfg.get("music_fade", 1.5)),
                        accent_pieces=accents)
    mux(vid, mixd["mix"], out, T)
    mux(vid, mixd["nomusic"], stem + ".nomusic.mp4", T)
    if vclean:
        mux(vclean, mixd["mix"], stem + ".clean.mp4", T)
        os.remove(vclean)
    os.remove(vid)
    m = A.measure_loudness(out, prof.loudness["lufs"], prof.loudness["tp"])
    report["loudness"] = dict(i=round(m["input_i"], 2), tp=round(m["input_tp"], 2), target=prof.loudness)
    if abs(m["input_i"] - prof.loudness["lufs"]) > 1.0:
        warnings.append(f"loudness {m['input_i']:.1f} LUFS vs target {prof.loudness['lufs']}")
    report["files"] = dict(master=os.path.basename(out), nomusic=os.path.basename(stem + ".nomusic.mp4"),
                           clean=os.path.basename(stem + ".clean.mp4") if vclean else None,
                           cues=os.path.basename(stem + ".cues.json") if cap_cues else None)
    report["mix"] = dict(premix_lufs=mixd["premix_lufs"], gain_db=mixd["gain_db"],
                         duck_measured_db=mixd.get("duck_measured_db"), duck_db=float(cfg.get("duck_db", -12)))
    report["frames_written"] = nfr
    _dump(rp, report)
    for w in warnings:
        print("WARN", w)
    print(f"DONE -> {out}  ({T:.2f}s, {report['loudness']['i']} LUFS)\nreport -> {rp}")
    if vclean:
        print(f"multi-platform: python -m vstudio.export {stem}.clean.mp4 --platforms douyin,youtube-shorts "
              f"--cues {stem}.cues.json --out exports/")
    return report


def _dump(path, obj):
    def conv(o):
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        return str(o)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=conv)


if __name__ == "__main__":
    main()
