"""Render an output's edit document (``output render``): only the stages whose inputs changed run again.

Stage chain per target (the output's own canvas = ``primary``, or an extra platform from ``export_add``):

  canvas    the source on the target canvas: pipeline mode reframes the clean master (face-tracked, pad-blur
            fallback; same aspect = a plain scale); flattened mode uses the finished file (another aspect:
            reframe, or the ``band`` layout in the frame pass)                       key: source sig + canvas
  timeline  trim + inner cuts (+ transitions at the joins), speed, grade, end fade (ffmpeg)
                                                                                   key: canvas + those ops
  audio     timeline audio + SFX + music bed -> loudness target (two-pass)        key: timeline + audio ops
  final     frame pass (mask / band layout, punch-in, overlays, cards, title band, captions, progress bar) +
            encode with the audio stem; preview = low bitrate at the SAME resolution, final = delivery encode
                                                                                   key: timeline + audio + visual
  cover     a frame of the timeline + cover text (when ``cover`` is set)          key: timeline + cover

Each stage file is ``<edit dir>/cache/<stage>-<key>.*`` (a hit = no work); the result is copied to
``<edit dir>/renders/<target>.<quality>.mp4`` (+ ``.cover.jpg``) with ``renders/manifest.json``. Every render
writes ``.vstudio/status.json`` heartbeats (vstudio.batch.livestatus) into the edit folder and the owning
project / work folder (the owner's previous record is restored afterwards).
"""
import os
import shutil
import subprocess
import tempfile
import time

import numpy as np

from vstudio.batch.util import read_json, sha1_json, write_json

from . import outfx as FX
from . import outputs as OUT

QUALITIES = ("preview", "final")
INTER = dict(preview=dict(crf=24, preset="ultrafast"), final=dict(crf=14, preset="veryfast"))
KEEP_PER_STAGE = 4


def _media():
    from vstudio import media
    return media


# --------------------------------------------------------------------------- targets
def targets_of(rec, st, wanted=None):
    """[{target, w, h, profile, layout}] - ``primary`` first, then the state's exports (``wanted`` filters)."""
    from vstudio import platform as P
    out = [dict(target="primary", w=rec["info"]["w"], h=rec["info"]["h"], profile=rec.get("profile"), layout="auto")]
    for x in st["exports"]:
        name, ori = x["target"].split(":")
        p = P.profile(name, ori)
        out.append(dict(target=x["target"], w=p.w, h=p.h, profile=p, layout=x.get("layout") or "auto"))
    if wanted and wanted not in ("all", ["all"]):
        want = [wanted] if isinstance(wanted, str) else list(wanted)
        want = ["primary" if w == "primary" else OUT.target_key(w) for w in want]
        missing = [w for w in want if w not in [t["target"] for t in out]]
        if missing:
            raise OUT.OutputError("unknown-target", f"{', '.join(missing)} is not an export of this output (add it "
                                  "with export_add)", f"{', '.join(missing)} 不在导出列表里", targets=missing)
        out = [t for t in out if t["target"] in want]
    return out


def _safe(tg):
    from vstudio import platform as P
    W, H = tg["w"], tg["h"]
    p = tg.get("profile")
    if p is not None:
        x0, y0, x1, y1 = P.safe_box(p)
        sx, sy = W / p.w, H / p.h
        return (x0 * sx, y0 * sy, x1 * sx, y1 * sy)
    return (W * 0.05, H * 0.05, W * 0.95, H * 0.95)


def _caption_box(tg):
    from vstudio import platform as P
    W, H = tg["w"], tg["h"]
    p = tg.get("profile")
    if p is not None:
        x0, y0, x1, y1 = P.caption_box(p)
        sx, sy = W / p.w, H / p.h
        return (x0 * sx, y0 * sy, x1 * sx, y1 * sy)
    return (W * 0.08, H * 0.76, W * 0.92, H * 0.9)


# --------------------------------------------------------------------------- the plan (keys only, no media work)
def _src(rec):
    return rec["master"] if rec["mode"] == "pipeline" else rec["file"]


def plan(rec, doc, st, tg, quality):
    """-> dict of stage specs {canvas, timeline, audio, final, cover} with their keys (pure; used by render and by
    ``show`` to say whether a render is fresh)."""
    info = rec["master_info"] if rec["mode"] == "pipeline" else rec["info"]
    src = _src(rec)
    sig = OUT.file_sig(src)
    dur = rec["info"]["duration"]
    tl = OUT.Timeline(st, dur)
    band = rec["mode"] == "flattened" and (tg["layout"] == "band" or
                                           (st["captions"].get("placement") or {}).get("mode") == "band")
    same = (info["w"], info["h"]) == (tg["w"], tg["h"])
    canvas = dict(src=src, sig=sig, w=tg["w"], h=tg["h"], src_wh=[info["w"], info["h"]],
                  op="none" if (same or band) else ("scale" if abs(info["w"] / info["h"] - tg["w"] / tg["h"]) < 0.01
                                                    else "reframe"),
                  safe=[round(x, 2) for x in _safe(tg)])
    # no canvas work: the key is the source alone, so targets sharing it share the timeline / audio stages
    canvas["key"] = sha1_json(["canvas", src, sig] if canvas["op"] == "none" else ["canvas", canvas, quality], 16)
    effs = st["effects"]
    grade = next((e["params"] for e in effs if e["effect"] == "vlog-grade"), None)
    endf = next((e["params"] for e in effs if e["effect"] == "end-fade"), None)
    full = len(tl.segs) == 1 and abs(tl.segs[0][0]) < 1e-3 and abs(tl.segs[0][1] - dur) < 0.02
    timeline = dict(segs=tl.segs, joins=tl.joins, speed=tl.speed, grade=grade, end_fade=endf,
                    duration=round(tl.duration, 3), has_audio=info["has_audio"])
    timeline["op"] = "none" if (full and tl.speed == 1.0 and not grade and not endf) else "ffmpeg"
    timeline["key"] = sha1_json(["timeline", canvas["key"], timeline, quality if timeline["op"] != "none" else None], 16)
    sfx = sorted([[round(tl.to_edit(e["start"], "start") or 0.0, 3), e["params"]["name"], e["params"].get("gain", 1.0)]
                  for e in effs if e["effect"] == "sfx-placement" and tl.span(e["start"], e["start"] + 0.05)])
    music = next((dict(e["params"], sig=OUT.file_sig(e["params"]["file"]))
                  for e in effs if e["effect"] == "music-bed" and os.path.exists(e["params"].get("file") or "")), None)
    prof = tg.get("profile")
    lufs = st["loudness"].get("lufs") or (prof.loudness["lufs"] if prof is not None else -14.0)
    tp = st["loudness"].get("tp") or (prof.loudness["tp"] if prof is not None else -1.5)
    audio = dict(sfx=sfx, music=music, lufs=lufs, tp=tp, has_audio=info["has_audio"])
    audio["op"] = "none" if not (info["has_audio"] or sfx or music) else "mix"
    audio["key"] = sha1_json(["audio", timeline["key"], audio], 16)
    vis = visual_spec(rec, st, tl, tg, band)
    final = dict(visual=vis, quality=quality, canvas=[tg["w"], tg["h"]],
                 encode=(prof.encode if prof is not None and quality == "final" else None))
    final["op"] = "frames" if (vis["layers"] or vis["captions"] or vis["title"] or vis["mask"] or vis["band"] or
                               vis["dips"] or (canvas["op"] == "none" and not same and not band)) else "encode"
    final["key"] = sha1_json(["final", timeline["key"], audio["key"], final], 16)
    cover = None
    if st.get("cover"):
        cv = st["cover"]
        cover = dict(cv, edit_t=tl.to_edit(cv["t"], "start"), size=_cover_size(tg))
        cover["key"] = sha1_json(["cover", timeline["key"], cover, rec["mode"]], 16)
    return dict(target=tg["target"], quality=quality, canvas=canvas, timeline=timeline, audio=audio, final=final,
                cover=cover, tl=tl, band=band)


def _cover_size(tg):
    from vstudio import platform as P
    p = tg.get("profile")
    if p is not None:
        return list(P.cover_size(p))
    return [tg["w"], tg["h"]]


def visual_spec(rec, st, tl, tg, band):
    """Everything the frame pass draws, in edited seconds (JSON: it is part of the final key)."""
    layers = []
    for e in st["effects"]:
        sp = FX.SPECS[e["effect"]]
        if sp["stage"] != "frame":
            continue
        if sp["kind"] == "progress":
            span = (0.0, tl.duration)
            chs = []
            for c in e["params"].get("chapters") or []:
                try:
                    s = tl.span(float(c.get("start", 0)), float(c.get("end", rec["info"]["duration"])))
                except (TypeError, ValueError):
                    s = None
                if s:
                    chs.append([round(s[0], 3), round(s[1], 3), str(c.get("label") or c.get("title") or "")])
            layers.append(dict(e, a=0.0, b=round(tl.duration, 3), _chapters_edit=chs))
            continue
        span = tl.span(e["start"], e["end"])
        if span:
            layers.append(dict(e, a=round(span[0], 3), b=round(span[1], 3)))
    dips = []
    jids = {j["id"] for j in tl.joins}
    for e in st["effects"]:
        if e["effect"] == "xfade-joins" and e["id"] not in jids:
            t = tl.to_edit(e["start"], "start")
            if t is not None:
                tr = e["params"].get("transition") or "fade"
                dips.append(dict(t=round(t, 3), d=float(e["params"].get("duration") or 0.4),
                                 color="white" if tr in ("flash", "light-leak", "whip", "zoom", "iris") else "black"))
    c = st["captions"]
    caps = []
    if rec["mode"] == "pipeline" and c["enabled"]:
        for i, cue in enumerate(rec.get("cues") or []):
            k = str(i)
            if k in c["removed"]:
                continue
            s = tl.span(cue["start"], cue["end"])
            if s:
                caps.append([round(s[0], 3), round(s[1], 3), c["overrides"].get(k, cue["text"])])
    for a in c["added"]:
        s = tl.span(a["start"], a["end"])
        if s:
            caps.append([round(s[0], 3), round(s[1], 3), a["text"]])
    caps.sort()
    pl = c.get("placement") or {}
    mask = None
    if rec["mode"] == "flattened" and pl.get("mode") == "mask":
        mask = dict(box=pl["box"], style=pl.get("style") or "blur", always=pl.get("always", True))
    bandspec = None
    if band:
        bandspec = dict(band=float(pl.get("band") or 0.2), title=bool(st.get("title")))
    return dict(layers=layers, captions=caps, style=c["style"], title=st.get("title"), mask=mask, band=bandspec,
                dips=dips, safe=[round(x, 2) for x in _safe(tg)], caption_box=[round(x, 2) for x in _caption_box(tg)],
                mode=rec["mode"])


# --------------------------------------------------------------------------- status / heartbeats
class Status:
    def __init__(self, rec, doc):
        from vstudio.batch import livestatus as LS
        self.LS = LS
        self.dirs = [doc.dir, rec["owner"]]
        self.prev = LS._read_raw(rec["owner"])
        self.label = rec["id"]

    def beat(self, stage, progress=None, message=None):
        for d in self.dirs:
            self.LS.write(d, "running", stage=f"output-edit:{stage}", progress=progress,
                          message=message or self.label, by="output-edit")

    def end(self, ok, message=None):
        self.LS.write(self.dirs[0], "done" if ok else "failed", stage="output-edit", progress=1.0 if ok else None,
                      message=message or self.label, by="output-edit")
        p = self.prev
        if p and p.get("status") in self.LS.STATES and p.get("status") != "running":
            self.LS.write(self.dirs[1], p["status"], stage=p.get("stage"), progress=p.get("progress"),
                          message=p.get("message"), eta=p.get("eta"), needs_you=p.get("needs_you"),
                          by=p.get("updated_by"))
        else:
            self.LS.write(self.dirs[1], "done" if ok else "failed", stage="output-edit",
                          message=message or self.label, by="output-edit")


# --------------------------------------------------------------------------- stage runners
def _enc(quality, crf=None, preset=None, audio=True, final_encode=None):
    m = _media()
    if quality == "preview":
        return m.delivery_args(crf=30, preset="ultrafast", maxrate="2M", bufsize="4M", audio=audio,
                               audio_bitrate="96k")
    if quality == "final":
        enc = final_encode or {}
        return m.delivery_args(crf=enc.get("crf"), preset="medium", maxrate=enc.get("maxrate"),
                               bufsize=enc.get("bufsize"), audio=audio)
    i = INTER[crf]
    return m.delivery_args(crf=i["crf"], preset=i["preset"], audio=audio, audio_bitrate="256k", faststart=False)


def run_canvas(spec, out, quality, safe):
    m = _media()
    if spec["op"] == "scale":
        m.run(["ffmpeg", "-y", "-v", "error", "-i", spec["src"], "-map", "0:v:0", "-map", "0:a:0?", "-vf",
               f"scale={spec['w']}:{spec['h']}:flags=lanczos,setsar=1", *_enc("inter", quality), out])
        return out
    from vstudio import reframe as R
    pl = R.plan(spec["src"], spec["w"], spec["h"], mode="face", safe=tuple(safe), fallback="pad-blur")
    R.render(spec["src"], out, pl, encode_args=_enc("inter", quality))
    return out


def run_timeline(spec, src, out, quality, workdir):
    from vstudio import xfade
    m = _media()
    info = m.probe(src)
    fps = info["fps"] or 30.0
    has_a = bool(info["has_audio"])
    g, segs = [], spec["segs"]
    for k, (a, b) in enumerate(segs):
        g.append(f"[0:v:0]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS,fps={fps:.6g},format=yuv420p,"
                 f"settb=AVTB[v{k}]")
        if has_a:
            g.append(f"[0:a:0]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,aresample=48000,"
                     f"aformat=channel_layouts=stereo[a{k}]")
    jd = {j["index"]: j for j in spec["joins"]}
    cv, ca, L = "v0", "a0", segs[0][1] - segs[0][0]
    for k in range(1, len(segs)):
        n = segs[k][1] - segs[k][0]
        j = jd.get(k - 1)
        if j:
            tr = xfade.ffmpeg_transition(j["transition"])
            d = j["duration"]
            g.append(f"[{cv}][v{k}]xfade=transition={tr}:duration={d:.4f}:offset={max(0.0, L - d):.4f}[vx{k}]")
            if has_a:
                g.append(f"[{ca}][a{k}]acrossfade=d={d:.4f}[ax{k}]")
            L += n - d
        else:
            g.append(f"[{cv}][v{k}]concat=n=2:v=1:a=0[vx{k}]")
            if has_a:
                g.append(f"[{ca}][a{k}]concat=n=2:v=0:a=1[ax{k}]")
            L += n
        cv, ca = f"vx{k}", f"ax{k}"
    vch, ach = [], []
    s = spec["speed"]
    if abs(s - 1.0) > 1e-6:
        vch.append(f"setpts=PTS/{s:.6g}")
        ach.append(m.atempo_chain(s))
    gr = spec.get("grade")
    if gr:
        vch.append(f"eq=saturation={float(gr.get('sat', 1.12)):.3f}:contrast={float(gr.get('contrast', 1.05)):.3f}")
        if gr.get("warm", True):
            vch.append("colorbalance=rs=0.04:gs=0.0:bs=-0.04:rm=0.03:bm=-0.03")
    ef = spec.get("end_fade")
    D = L / s
    if ef:
        d = min(float(ef.get("duration") or 1.0), D * 0.5)
        vch.append(f"fade=t=out:st={max(0.0, D - d):.4f}:d={d:.4f}")
        ach.append(f"afade=t=out:st={max(0.0, D - d):.4f}:d={d:.4f}")
    g.append(f"[{cv}]" + (",".join(vch) if vch else "null") + "[vout]")
    if has_a:
        g.append(f"[{ca}]" + (",".join(ach) if ach else "anull") + "[aout]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, *m.filter_complex_args(";".join(g), workdir), "-map", "[vout]"]
    cmd += (["-map", "[aout]"] if has_a else [])
    cmd += _enc("inter", quality, audio=has_a) + [out]
    m.run(cmd)
    return out


def run_audio(spec, src, out, duration, workdir):
    from vstudio import audio as A
    m = _media()
    mix = os.path.join(workdir, "mix.wav")
    has_a = m.probe(src)["has_audio"]
    if has_a:
        x = A.decode_audio(src, sr=A.SR, channels=2)
    else:
        x = np.zeros((int(round(duration * A.SR)), 2), np.float32)
    if spec["sfx"]:
        ev = [dict(t=t, sfx=name, gain_db=float(20 * np.log10(max(1e-3, float(g)))) if g else -60.0)
              for t, name, g in spec["sfx"]]
        A.place_sfx(x, ev, sr=A.SR)
    A.write_wav(mix, x, A.SR)
    if spec["music"]:
        mm = spec["music"]
        bed = os.path.join(workdir, "bed.wav")
        A.mix_bed(mix, mm["file"], bed, duck_db=float(mm.get("duck_db", -10)), music_lufs=float(mm.get("music_lufs", -30)))
        mix = bed
    A.loudnorm_2pass(mix, out, lufs=float(spec["lufs"]), tp=float(spec["tp"]))
    return out


def run_cover(spec, src, out, mode):
    from PIL import Image

    from vstudio.batch.edits import _text_cover
    from vstudio import export as X
    m = _media()
    d = tempfile.mkdtemp(prefix="vcover-")
    try:
        fr = os.path.join(d, "frame.jpg")
        m.grab_frame(src, max(0.0, float(spec.get("edit_t") or 0.0)), fr)
        im = Image.open(fr).convert("RGB")
        W, H = spec["size"]
        im = X.fit_cover(im, (W, H)) if (im.width, im.height) != (W, H) else im
        im.save(fr, quality=95)
        style, text = spec.get("style") or "card", spec.get("text") or ""
        if style == "plain" or not text:
            shutil.copy(fr, out)
        elif style == "band":
            from vstudio import draw as Dr
            im = Image.open(fr).convert("RGBA")
            bh = int(H * 0.22)
            band = Image.new("RGBA", (W, bh), Dr.brand()["ground"] + (235,))
            im.alpha_composite(band, (0, H - bh))
            f = Dr.fit_font(text.replace("|", " "), "cjk-bold", int(bh * 0.36), int(W * 0.9))
            lay = Dr.text_layer(text.replace("|", " "), f, stroke=0, shadow_alpha=0, max_w=int(W * 0.9))
            im.alpha_composite(lay, ((W - lay.width) // 2, H - bh + (bh - lay.height) // 2))
            im.convert("RGB").save(out, quality=92)
        else:
            _text_cover(fr, text, out)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


# --------------------------------------------------------------------------- frame pass
class Captions:
    def __init__(self, vis, W, H, prof, band_rect=None, mask_rect=None):
        from vstudio import draw as Dr
        self.Dr = Dr
        self.cues = vis["captions"]
        self.st = dict(vis["style"] or {})
        self.W, self.H, self.prof = W, H, prof
        self.box = tuple(vis["caption_box"])
        self.band_rect, self.mask_rect = band_rect, mask_rect
        self.cache = {}

    def _size(self, text):
        from vstudio import platform as P
        if self.prof is not None:
            fit = P.fit_text_size(self.prof, text.replace("\n", " "))
            s = fit["size"] * self.W / self.prof.w
        else:
            s = min(self.W, self.H) * 0.055
        return max(14, int(s * float(self.st.get("size") or 1.0)))

    def layer(self, k, text):
        if k not in self.cache:
            Dr = self.Dr
            size = self._size(text)
            f = Dr.load_font(self.st.get("font") or "cjk-bold", size)
            stroke = max(2, int(size * float(self.st.get("stroke", 0.08) if self.st.get("stroke") is not None else 0.08)))
            x0, _, x1, _ = self.box
            maxw = (self.band_rect[2] - self.band_rect[0]) * 0.92 if self.band_rect else (x1 - x0)
            im = Dr.text_layer(text, f, fill=Dr.rgba(self.st.get("color") or "#FFFFFF"),
                               hl_fill=self.st.get("highlight"), stroke=stroke,
                               stroke_fill=Dr.rgba(self.st.get("stroke_color") or (20, 20, 20)),
                               keywords=self.st.get("keywords") or None, max_w=int(maxw), pad=8)
            if self.st.get("box"):
                from PIL import Image
                bg = Dr.rounded_rect((im.width + 24, im.height + 8), int(size * 0.3),
                                     Dr.rgba(self.st.get("box_color") or (0, 0, 0), 150))
                bg.alpha_composite(im, (12, 4))
                im = bg
                del Image
            self.cache[k] = np.asarray(im)
        return self.cache[k]

    def draw(self, img, t):
        for k, (a, b, text) in enumerate(self.cues):
            if a <= t < b:
                L = self.layer(k, text)
                h, w = L.shape[:2]
                if self.band_rect:
                    x0, y0, x1, y1 = self.band_rect
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                elif self.mask_rect:
                    x0, y0, x1, y1 = self.mask_rect
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                else:
                    pos = self.st.get("position") or "bottom"
                    x0, y0, x1, y1 = self.box
                    cx = (x0 + x1) / 2
                    cy = {"bottom": (y0 + y1) / 2, "middle": self.H * 0.6, "top": self.H * 0.22}.get(
                        pos, float(self.st.get("y") or 0.8) * self.H)
                    if pos == "bottom":
                        cy = min(cy, y1 - h / 2)
                self.Dr.alpha_paste(img, L, (cx, cy), center=True, bgr=True)
                break
        return img


def _title_layer(title, W, h_px):
    from vstudio import draw as Dr
    from PIL import Image
    band = Image.new("RGBA", (W, h_px), Dr.rgba(title.get("band_color") or Dr.brand()["ground"], 232))
    text = str(title.get("text") or "")
    sub = str(title.get("sub") or "")
    size = int(h_px * (0.42 if sub else 0.5) * float(title.get("size") or 1.0))
    f = Dr.fit_font(text, "cjk-bold", size, int(W * 0.9))
    lay = Dr.text_layer(text, f, fill=Dr.rgba(title.get("color") or "#FFFFFF"), stroke=0, shadow_alpha=0, pad=2)
    if sub:
        fs = Dr.fit_font(sub, "cjk", int(size * 0.55), int(W * 0.9))
        sl = Dr.text_layer(sub, fs, fill=Dr.rgba(Dr.brand()["highlight"]), stroke=0, shadow_alpha=0, pad=2)
        tot = lay.height + sl.height
        y = (h_px - tot) // 2
        band.alpha_composite(lay, ((W - lay.width) // 2, max(0, y)))
        band.alpha_composite(sl, ((W - sl.width) // 2, max(0, y + lay.height)))
    else:
        band.alpha_composite(lay, ((W - lay.width) // 2, max(0, (h_px - lay.height) // 2)))
    return np.asarray(band)


def _band_layout(W, H, sw, sh, band_frac, title):
    """(video rect x, y, w, h on the canvas, top band rect, bottom band rect)."""
    top = int(H * 0.12) if title else 0
    bot = int(H * band_frac)
    avail_h = H - top - bot
    k = min(W / sw, avail_h / sh)
    vw, vh = int(sw * k) // 2 * 2, int(sh * k) // 2 * 2
    x = (W - vw) // 2
    y = top + (avail_h - vh) // 2
    return (x, y, vw, vh), (0, 0, W, top) if top else None, (0, y + vh, W, H)


def frame_pass(src, out, audio_wav, vis, tg, fps, quality, final_encode, beat):
    import cv2

    from vstudio import draw as Dr
    m = _media()
    info = m.probe(src)
    sw, sh = int(info["w"]), int(info["h"])
    W, H = tg["w"], tg["h"]
    n_total = max(1, int(round(float(info["duration"]) * fps)))
    safe = tuple(vis["safe"])
    layers = []
    for e in vis["layers"]:
        inst = dict(e, _chapters_edit=e.get("_chapters_edit") or [])
        L = FX.make_layer(inst, W if not FX.LAYERS[e["effect"]].camera else sw,
                          H if not FX.LAYERS[e["effect"]].camera else sh, safe if not FX.LAYERS[e["effect"]].camera else None)
        if L:
            layers.append((e["a"], e["b"], L))
    cams = [x for x in layers if x[2].camera]
    ovs = [x for x in layers if not x[2].camera]
    band = vis["band"]
    vid_rect = top_rect = bot_rect = None
    if band:
        vid_rect, top_rect, bot_rect = _band_layout(W, H, sw, sh, band["band"], bool(vis["title"]))
    mask = vis["mask"]
    mrect = None
    if mask:
        bx = mask["box"]
        mrect = (int(bx[0] * sw), int(bx[1] * sh), int(bx[2] * sw), int(bx[3] * sh))
    cap_mask_rect = None
    if mrect and not band:
        sx, sy = W / sw, H / sh
        cap_mask_rect = (mrect[0] * sx, mrect[1] * sy, mrect[2] * sx, mrect[3] * sy)
    caps = Captions(vis, W, H, tg.get("profile"), band_rect=bot_rect, mask_rect=cap_mask_rect) if vis["captions"] else None
    title = vis["title"]
    title_arr = title_y = None
    if title:
        if top_rect:
            title_arr = _title_layer(title, W, top_rect[3])
            title_y = 0
        else:
            hp = int(H * float(title.get("height") or 0.1))
            title_arr = _title_layer(title, W, hp)
            title_y = int(float(title["y"]) * H) if title.get("y") is not None else int(safe[1])
    cap_spans = [(a, b) for a, b, _ in (vis["captions"] or [])]
    ground = np.array(Dr.brand()["ground"][::-1], np.uint8)

    dec = [m.ffmpeg_bin(), "-v", "error", "-i", src, "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    enc = [m.ffmpeg_bin(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", f"{fps:.6g}", "-i", "-"]
    has_a = audio_wav is not None
    if has_a:
        enc += ["-i", audio_wav, "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    else:
        enc += ["-map", "0:v:0"]
    enc += _enc(quality, audio=has_a, final_encode=final_encode) + [out]
    pd = subprocess.Popen(dec, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pe = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    fsz = sw * sh * 3
    i = 0
    try:
        while True:
            buf = pd.stdout.read(fsz)
            if len(buf) < fsz:
                break
            t = i / fps
            img = np.frombuffer(buf, np.uint8).reshape(sh, sw, 3).copy()
            if mrect and (mask.get("always", True) or any(a <= t < b for a, b in cap_spans)):
                x0, y0, x1, y1 = mrect
                roi = img[y0:y1, x0:x1]
                if roi.size:
                    if mask.get("style") == "solid":
                        img[y0:y1, x0:x1] = (roi.astype(np.float32) * 0.08 + ground * 0.92).astype(np.uint8)
                    else:
                        k = max(15, (min(roi.shape[:2]) // 3) | 1)
                        img[y0:y1, x0:x1] = (cv2.GaussianBlur(roi, (k, k), 0).astype(np.float32) * 0.55).astype(np.uint8)
            for a, b, L in cams:
                if a <= t < b:
                    L.draw(img, t - a, b - a)
            if band:
                x, y, vw, vh = vid_rect
                small = cv2.resize(img, (max(2, W // 12), max(2, H // 12)), interpolation=cv2.INTER_AREA)
                bg = cv2.GaussianBlur(cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR), (0, 0), 9)
                canvas = (bg.astype(np.float32) * 0.35).astype(np.uint8)
                canvas[y:y + vh, x:x + vw] = cv2.resize(img, (vw, vh), interpolation=cv2.INTER_AREA)
                img = canvas
            elif (sw, sh) != (W, H):
                img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
            for a, b, L in ovs:
                if a <= t < b or (L.__class__.__name__ == "Progress" and a <= t <= b + 1.0):
                    L.draw(img, t - a, b - a)
            if title_arr is not None:
                Dr.alpha_paste(img, title_arr, (0, title_y), bgr=True)
            if caps:
                caps.draw(img, t)
            for dp in vis["dips"]:
                u = abs(t - dp["t"]) / max(0.05, dp["d"] / 2)
                if u < 1:
                    k = 1 - u
                    col = 255.0 if dp["color"] == "white" else 0.0
                    img[:] = (img.astype(np.float32) * (1 - k) + col * k).astype(np.uint8)
            pe.stdin.write(img.tobytes())
            i += 1
            if i % 30 == 0:
                beat(i / n_total)
    except BrokenPipeError:
        pass
    finally:
        try:
            pe.stdin.close()
        except BrokenPipeError:
            pass
        pd.stdout.close()
        pd.wait()
        err = pe.stderr.read().decode(errors="replace")
        rc = pe.wait()
    if rc != 0 or i == 0:
        raise RuntimeError(f"frame pass failed (encoder exit {rc}, {i} frames): {err[-400:]}")
    return out


def run_encode(src, out, audio_wav, quality, final_encode, tg):
    m = _media()
    info = m.probe(src)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
    if audio_wav:
        cmd += ["-i", audio_wav, "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    else:
        cmd += ["-map", "0:v:0"]
    if (int(info["w"]), int(info["h"])) != (tg["w"], tg["h"]):
        cmd += ["-vf", f"scale={tg['w']}:{tg['h']}:flags=lanczos,setsar=1"]
    cmd += _enc(quality, audio=bool(audio_wav), final_encode=final_encode) + [out]
    m.run(cmd)
    return out


# --------------------------------------------------------------------------- render
def _cache(doc, stage, key, ext):
    d = os.path.join(doc.dir, "cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{stage}-{key}{ext}")


def _gc(doc, stage, keep_path):
    d = os.path.join(doc.dir, "cache")
    rows = sorted((os.path.getmtime(os.path.join(d, f)), f) for f in os.listdir(d) if f.startswith(stage + "-"))
    for _, f in rows[:-KEEP_PER_STAGE]:
        p = os.path.join(d, f)
        if p != keep_path:
            try:
                os.remove(p)
            except OSError:
                pass


def _stage(doc, stages, stage, key, ext, fn, st_obj):
    path = _cache(doc, stage, key, ext)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        os.utime(path)
        stages.append(dict(stage=stage, key=key, cached=True, seconds=0.0, file=path))
        return path
    st_obj.beat(stage)
    t0 = time.time()
    tmp = path + ".part" + ext
    fn(tmp)
    os.replace(tmp, path)
    stages.append(dict(stage=stage, key=key, cached=False, seconds=round(time.time() - t0, 2), file=path))
    _gc(doc, stage, path)
    return path


def manifest_path(doc):
    return os.path.join(doc.dir, "renders", "manifest.json")


def render_status(rec, doc, st):
    """Existing renders of the output and whether each is fresh (its key matches the current edit state)."""
    man = read_json(manifest_path(doc), {}) or {}
    out = []
    for tg in targets_of(rec, st):
        for q in QUALITIES:
            r = (man.get("renders") or {}).get(f"{tg['target']}.{q}")
            if not r:
                continue
            key = plan(rec, doc, st, tg, q)["final"]["key"]
            out.append(dict(target=tg["target"], quality=q, file=r["file"], exists=os.path.exists(r["file"]),
                            cover=r.get("cover"), fresh=r.get("key") == key and os.path.exists(r["file"]), at=r.get("at"),
                            duration=r.get("duration")))
    return out


def render(d, output, quality="preview", targets=None, on_event=None, with_ops=None):
    """Render the output's current edit (preview or final) for ``targets`` (default primary; "all" = primary +
    every export). -> {ok, output, quality, targets [{target, file, cover, canvas, duration, key, cached, stages
    [{stage, key, cached, seconds}], warnings}], seconds}.

    ``with_ops``: a before / after preview of ops that are NOT applied (cuts, speed: what the player cannot fake):
    the ops are validated like ``edit`` against the current state, rendered at preview quality into
    ``renders/<target>.compare.mp4``; edit.json and the render manifest are not touched."""
    if quality not in QUALITIES:
        raise OUT.OutputError("bad-param", f"quality: {' | '.join(QUALITIES)}", "质量只能是 preview / final",
                              name="quality", value=quality)
    rec, doc = OUT._load(d, output)
    st = doc.state()
    compare = with_ops is not None
    if compare:
        if quality != "preview":
            raise OUT.OutputError("bad-param", "--with-ops renders a preview only", "对比预览只能是 preview 质量",
                                  name="quality", value=quality)
        ops = [with_ops] if isinstance(with_ops, dict) else with_ops
        if not isinstance(ops, list) or not ops:
            raise OUT.OutputError("no-ops", "--with-ops needs a JSON op or list of ops", "需要 --with-ops 操作")
        step, _, _ = OUT.apply_ops(doc, ops, dry=True)
        for n in step["ops"]:
            st = OUT.fold(st, n)
    tgs = targets_of(rec, st, targets or ["primary"])
    status = Status(rec, doc)
    t_all = time.time()
    results = []
    emit = on_event or (lambda ev: None)
    ok = False
    try:
        for n_t, tg in enumerate(tgs):
            emit(dict(event="target-start", target=tg["target"], quality=quality))
            p = plan(rec, doc, st, tg, quality)
            stages, warns = [], []
            work = tempfile.mkdtemp(prefix="voutedit-")
            try:
                src = p["canvas"]["src"]
                if p["canvas"]["op"] != "none":
                    src = _stage(doc, stages, "canvas", p["canvas"]["key"], ".mp4",
                                 lambda o: run_canvas(p["canvas"], o, quality, p["canvas"]["safe"]), status)
                    emit(dict(event="stage-done", target=tg["target"], **{k: v for k, v in stages[-1].items()
                                                                          if k != "file"}))
                if p["timeline"]["op"] != "none":
                    src = _stage(doc, stages, "timeline", p["timeline"]["key"], ".mp4",
                                 lambda o, s=src: run_timeline(p["timeline"], s, o, quality, work), status)
                    emit(dict(event="stage-done", target=tg["target"], **{k: v for k, v in stages[-1].items()
                                                                          if k != "file"}))
                wav = None
                if p["audio"]["op"] != "none":
                    wav = _stage(doc, stages, "audio", p["audio"]["key"], ".wav",
                                 lambda o, s=src: run_audio(p["audio"], s, o, p["timeline"]["duration"], work), status)
                    emit(dict(event="stage-done", target=tg["target"], **{k: v for k, v in stages[-1].items()
                                                                          if k != "file"}))
                fps = _media().probe(src)["fps"] or rec["info"]["fps"]

                def fin(o, s=src, w=wav):
                    if p["final"]["op"] == "frames":
                        frame_pass(s, o, w, p["final"]["visual"], tg, fps, quality, p["final"]["encode"],
                                   lambda prog: status.beat("frames", progress=round((n_t + prog) / len(tgs), 3)))
                    else:
                        run_encode(s, o, w, quality, p["final"]["encode"], tg)
                    return o
                fpath = _stage(doc, stages, "final", p["final"]["key"], ".mp4", fin, status)
                emit(dict(event="stage-done", target=tg["target"], **{k: v for k, v in stages[-1].items() if k != "file"}))
                cpath = None
                if p["cover"]:
                    cpath = _stage(doc, stages, "cover", p["cover"]["key"], ".jpg",
                                   lambda o, s=src: run_cover(p["cover"], s, o, rec["mode"]), status)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            rdir = os.path.join(doc.dir, "renders")
            os.makedirs(rdir, exist_ok=True)
            name = tg["target"].replace(":", "-")
            dst = os.path.join(rdir, f"{name}.{'compare' if compare else quality}.mp4")
            _link(fpath, dst)
            cdst = None
            if cpath and not compare:
                cdst = os.path.join(rdir, f"{name}.cover.jpg")
                _link(cpath, cdst)
            info = _media().probe(dst)
            if rec["mode"] == "flattened" and tg["target"] != "primary" and tg["layout"] == "auto":
                warns.append(OUT.msg("relayout-crops-burned", "re-layout of a flattened file: check that no burned "
                                     "text is cropped (layout band keeps the whole frame)",
                                     "成片重新构图：检查烧录文字是否被裁掉", target=tg["target"]))
            if tg.get("profile") is not None:
                from vstudio import platform as P
                for w in P.check_length(tg["profile"], info["duration"]):
                    warns.append(OUT.msg("length", w, None, target=tg["target"]))
            res = dict(target=tg["target"], quality=quality, file=dst, cover=cdst, canvas=[tg["w"], tg["h"]],
                       layout=tg["layout"], duration=round(info["duration"], 3), key=p["final"]["key"],
                       cached=all(s["cached"] for s in stages), stages=[{k: v for k, v in s.items() if k != "file"}
                                                                        for s in stages], warnings=warns)
            results.append(res)
            if compare:
                res["compare"] = True
                emit(dict(event="target-done", **{k: v for k, v in res.items() if k != "stages"}))
                continue
            man = read_json(manifest_path(doc), {}) or {}
            man.setdefault("renders", {})[f"{tg['target']}.{quality}"] = dict(file=dst, cover=cdst, key=res["key"],
                                                                             at=OUT._stamp(),
                                                                             duration=res["duration"],
                                                                             steps=len(doc.d["steps"]))
            man["output"] = rec["id"]
            write_json(manifest_path(doc), man)
            emit(dict(event="target-done", **{k: v for k, v in res.items() if k != "stages"}))
        ok = True
    except OUT.OutputError:
        raise
    except Exception as e:  # noqa: BLE001
        raise OUT.OutputError("render-failed", f"render failed: {str(e)[:300]}", "渲染失败", error=str(e)[:300]) from e
    finally:
        status.end(ok)
    return dict(ok=True, output=rec["id"], mode=rec["mode"], quality=quality, targets=results,
                seconds=round(time.time() - t_all, 2), edit_dir=doc.dir, compare=compare)


def _link(src, dst):
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
