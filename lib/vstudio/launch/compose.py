"""Plan -> a HyperFrames project (index.html + assets) -> rendered, delivered MP4.

    from vstudio.launch import compose as CO
    proj = CO.build(cfg, plan, "kit/build/demo-en-16x9")       # writes the project, returns its dir
    CO.render(proj, "kit/demo/demo-en-16x9.mp4")             # npx hyperframes render + delivery (BT.709, faststart)

The look comes from the brand theme (vstudio.theme tokens: paper, ink, one accent, marker for the highlighted
word) and the brand fonts. Motion: kinetic captions (words rise in, the 【term】 gets a marker sweep), the product
window crossfades between scenes and its camera punches in on every action the capture recorded. No voice, no
music unless the config adds them (music must carry a license; a TTS voice-over is labelled "AI voice").
HyperFrames CLI: ``npx hyperframes`` (set $VSTUDIO_HYPERFRAMES to pin a version, e.g. hyperframes@0.8.130).
"""
import html
import json
import os
import shutil
import subprocess

from vstudio import media

from . import brand as B
from . import config as C
from . import story as S

GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
DISPLAY_W = 560                 # display font weight used on screen (and when measuring)


def _e(s):
    return html.escape(s or "", quote=True)


def _r(x):
    return round(float(x), 3)


def hyperframes_cmd():
    spec = os.environ.get("VSTUDIO_HYPERFRAMES") or "hyperframes"
    return ["npx", spec]


# ------------------------------------------------------------------------------------------------ text
def caption_html(lines, cls="w"):
    """Fitted lines -> spans: one .w per word (CJK: per character run) and .mk around the 【term】."""
    out = []
    for ln in lines:
        parts, buf, i = [], "", 0
        while i < len(ln):
            if ln[i] == "【":
                j = ln.find("】", i)
                j = len(ln) if j < 0 else j
                if buf:
                    parts.append(("t", buf))
                    buf = ""
                parts.append(("m", ln[i + 1:j]))
                i = j + 1
            else:
                buf += ln[i]
                i += 1
        if buf:
            parts.append(("t", buf))
        spans = []
        for kind, txt in parts:
            if kind == "m":
                spans.append(f'<span class="{cls} mk">{_e(txt)}</span>')
                continue
            for w in _words(txt):
                spans.append(f'<span class="{cls}">{_e(w)}</span>' if w.strip() else _e(w))
        out.append('<span class="ln">' + "".join(spans) + "</span>")
    return "<br>".join(out)


def _words(txt):
    import re
    if any("㐀" <= c <= "鿿" for c in txt):
        return re.findall(r"[㐀-鿿][，。、！？；：]?|[^㐀-鿿]+", txt)
    return re.findall(r"\S+|\s+", txt)


# ------------------------------------------------------------------------------------------------ assets
def _asset(src, proj, sub, name=None):
    d = os.path.join(proj, "assets", sub)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, name or os.path.basename(src))
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        shutil.copy2(src, dst)
    return os.path.relpath(dst, proj)


def _frame(src, t, proj, name):
    d = os.path.join(proj, "assets", "frames")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, name)
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        media.grab_frame(src, max(0.0, t), out, quality=2)
    return os.path.relpath(out, proj)


def _music(cfg, proj, total):
    m = cfg.get("music")
    if not m:
        return None
    d = os.path.join(proj, "assets", "audio")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "music.m4a")
    fo = max(0.0, total - 1.6)
    media.run(["ffmpeg", "-y", "-i", m["file"], "-t", f"{total:.3f}", "-af",
               f"afade=t=in:d=0.4,afade=t=out:st={fo:.3f}:d=1.6", "-c:a", "aac", "-b:a", "192k", out])
    return os.path.relpath(out, proj)


def _vo(cfg, scene, proj, lang):
    from vstudio import tts
    vo = cfg.get("voiceover") or {}
    d = os.path.join(proj, "assets", "audio")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"vo-{scene['id']}-{lang}.wav")
    tts.synth(C.plain(scene["vo"]), engine=vo.get("engine") or "auto", voice=vo.get("voice"), out=out)
    return os.path.relpath(out, proj), media.probe(out)["duration"]


# ------------------------------------------------------------------------------------------------ build
CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: {W}px; height: {H}px; overflow: hidden; background: var(--paper); }
#root { position: relative; width: {W}px; height: {H}px; overflow: hidden; background: var(--paper); color: var(--ink); }
.full { position: absolute; left: 0; top: 0; width: {W}px; height: {H}px; }
.scene { position: absolute; left: 0; top: 0; width: {W}px; height: {H}px; opacity: 0; }
.kicker { position: absolute; font-family: {TEXT}; font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
  color: var(--accent); opacity: 0; display: flex; align-items: center; gap: .7em; white-space: nowrap; }
.kicker i { display: inline-block; width: 2.2em; height: 2px; background: var(--accent); }
.cap { position: absolute; font-family: {DISPLAY}; font-weight: 560; line-height: 1.16; letter-spacing: -.012em;
  color: var(--ink); }
.cap .w { display: inline-block; opacity: 0; white-space: pre; }
.cap .mk { padding: 0 .12em; margin: 0 -.04em; border-radius: .12em;
  background-image: linear-gradient(var(--marker), var(--marker)); background-repeat: no-repeat;
  background-position: 0 88%; background-size: 0% 46%; }
.win { position: absolute; overflow: hidden; border-radius: 16px; background: var(--card);
  box-shadow: 0 22px 60px rgba(30,27,24,.16), 0 0 0 1px rgba(30,27,24,.09); opacity: 0; }
.cam { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.cam > img, .cam > video { position: absolute; left: 0; top: 0; width: 100%; height: 100%; object-fit: fill; }
.center { position: absolute; left: 0; width: {W}px; text-align: center; }
.mark { position: absolute; opacity: 0; }
.title { font-family: {DISPLAY}; font-weight: 600; letter-spacing: -.02em; color: var(--ink); line-height: 1.04; }
.oneliner { font-family: {DISPLAY}; font-weight: 420; color: var(--ink2); line-height: 1.25; }
.oneliner .w, .title .w, .cta .w { display: inline-block; opacity: 0; white-space: pre; }
.chip { display: inline-block; font-family: {TEXT}; font-weight: 600; letter-spacing: .08em; color: var(--accent);
  border: 2px solid var(--accent); border-radius: 999px; padding: .28em .9em; opacity: 0; }
.rule { position: absolute; height: 2px; background: var(--accent); opacity: 0; }
.cta { font-family: {DISPLAY}; font-weight: 560; color: var(--ink); line-height: 1.2; }
.site { font-family: {TEXT}; font-weight: 600; color: var(--accent); letter-spacing: .02em; opacity: 0; }
.sub { font-family: {TEXT}; font-weight: 400; color: var(--ink2); opacity: 0; }
.ailabel { position: absolute; font-family: {TEXT}; font-size: 20px; color: var(--ink2); opacity: .85; }
"""


def _fit_caption(text, lang, layout, files):
    x0, y0, x1, y1 = layout["text"]
    px, lines = B.fit(text, files["display"], layout["caption_px"], x1 - x0, layout["caption_lines"], lang, DISPLAY_W)
    return px, lines


def _ease_in_words(tl_lines, sel, at, stagger=0.055, dur=0.42, rise="0.38em"):
    tl_lines.append(f'tl.fromTo("{sel}", {{opacity: 0, y: "{rise}"}}, {{opacity: 1, y: 0, duration: {dur}, '
                    f'ease: "power3.out", stagger: {stagger}}}, {_r(at)});')


def build(cfg, plan, proj, quiet=False):
    """Write ``proj``/index.html (+ assets, plan.json, cues.json) for a story plan. Returns proj."""
    os.makedirs(proj, exist_ok=True)
    lang, W, H, L = plan["lang"], plan["W"], plan["H"], plan["layout"]
    T = B.theme(cfg)
    p = cfg["product"]
    files = B.font_files(cfg, lang)
    # every string on screen, for CJK subsetting
    end = cfg.get("end_card") or {}
    strings = [p["name"], C.text(p.get("name_zh"), lang), C.text(p.get("one_liner"), lang), C.text(end.get("cta"), lang),
               C.text(end.get("sub"), lang), p.get("site", ""), p.get("version", ""), "AI voice AI 配音"]
    for s in plan["scenes"]:
        strings += [s.get("kicker", ""), s.get("caption", "")]
    faces = B.stage_fonts(cfg, os.path.join(proj, "assets", "fonts"), "".join(strings), [lang])
    from vstudio import theme as TH
    css = TH.css_vars(T) + "\n" + B.font_css(faces) + CSS
    css = (css.replace("{W}", str(W)).replace("{H}", str(H))
           .replace("{DISPLAY}", B.families(faces, lang, "display")).replace("{TEXT}", B.families(faces, lang, "text")))
    body, js, tracks = [], [], [1, 2]
    total = plan["duration"]
    body.append(f'<div id="bg" class="full clip" data-start="0" data-duration="{_r(total)}" data-track-index="0"></div>')
    b = cfg.get("brand") or {}
    mark = _asset(b["mark"], proj, "brand") if b.get("mark") else None
    logo = _asset(b["logo"], proj, "brand") if b.get("logo") else None
    vo_on = (cfg.get("voiceover") or {}).get("enabled")
    n = len(plan["scenes"])
    cues = S.caption_cues(plan)
    for i, s in enumerate(plan["scenes"]):
        sid, st, du = f"s{i}", s["start"], s["dur"]
        track = tracks[i % 2]
        inner = []
        last_scene = i == n - 1
        # scene in / out (the first scene is already there at frame 0; a loop's last scene fades to the tail)
        if i == 0:
            js.append(f'tl.set("#{sid}", {{opacity: 1}}, 0);')
        else:
            js.append(f'tl.fromTo("#{sid}", {{opacity: 0}}, {{opacity: 1, duration: {plan["xf"]}, ease: "none"}}, {_r(st)});')
        if not last_scene or plan["loop"]:
            js.append(f'tl.to("#{sid}", {{opacity: 0, duration: {plan["xf"]}, ease: "none"}}, {_r(st + du - plan["xf"])});')
        if s["kind"] == "feature":
            x0, y0, x1, y1 = L["text"]
            kpx = L["kicker_px"]
            px, lines = _fit_caption(s["caption"], lang, L, files)
            num = "" if plan["cut"] != "demo" else f"{sum(1 for z in plan['scenes'][:i + 1] if z['kind'] == 'feature'):02d}"
            ktxt = f"{num} · {s['kicker']}" if num and s["kicker"] else s["kicker"]
            # the caption sits on the window (bottom-anchored), the kicker on the caption
            ctop = max(y0 + int(kpx * 1.9), L["win"][1] - L.get("gap", 36) - int(px * 1.16 * len(lines)))
            ktop = ctop - int(kpx * 1.9)
            inner.append(f'<div class="kicker" id="{sid}k" style="left:{x0}px; top:{ktop}px; font-size:{kpx}px">'
                         f'<i></i>{_e(ktxt)}</div>')
            inner.append(f'<div class="cap" id="{sid}c" style="left:{x0}px; top:{ctop}px; width:{x1 - x0}px; '
                         f'font-size:{px}px">{caption_html(lines)}</div>')
            wx, wy, ww, wh = L["win"]
            m = s["media"]
            sw, sh = m.get("w") or ww, m.get("h") or wh
            k0 = s["cam"][0]
            cam = f'<div class="cam" id="{sid}m" style="width:{sw}px; height:{sh}px">'
            js.append(f'tl.set("#{sid}m", {{x: {k0["x"]}, y: {k0["y"]}, scale: {k0["scale"]}}}, 0);')
            tag = f"{sid}-{s['shot']}"
            if m["kind"] == "video":
                src = _asset(m["file"], proj, "shots")
                segs = m.get("segs") or [(m["at"], m["until"], m["rate"])]
                last = _frame(m["file"], segs[-1][1] - 0.05, proj, f"{tag}-last.jpg")
                cam += f'<img src="{last}" alt="">'
                off = 0.0
                for k, (m0, m1, rate) in enumerate(segs):      # speed ramp: one clip per segment, back to back
                    d = (m1 - m0) / rate
                    if off >= s["play"] - 1e-3:
                        break
                    d = min(d, s["play"] - off)
                    cam += (f'<video id="{sid}v{k}" src="{src}" muted playsinline data-start="{_r(st + off)}" '
                            f'data-duration="{_r(d)}" data-media-start="{_r(m0)}" data-playback-rate="{round(rate, 4)}" '
                            f'data-track-index="{3 + i % 2}" data-volume="0"></video>')
                    off += d
            else:
                cam += f'<img src="{_asset(m["file"], proj, "shots")}" alt="">'
            cam += "</div>"
            inner.append(f'<div class="win" id="{sid}w" style="left:{wx}px; top:{wy}px; width:{ww}px; height:{wh}px">'
                         f'{cam}</div>')
            loop_first = plan["loop"] and i == 0
            if loop_first:                                   # the loop's frame 0 = its last frame: no entrance
                js.append(f'tl.set(["#{sid}k", "#{sid}w"], {{opacity: 1}}, 0);')
            else:
                js.append(f'tl.fromTo("#{sid}k", {{opacity: 0, x: -14}}, {{opacity: 1, x: 0, duration: 0.4, '
                          f'ease: "power2.out"}}, {_r(st + 0.05)});')
                js.append(f'tl.fromTo("#{sid}w", {{opacity: 0, y: 26}}, {{opacity: 1, y: 0, duration: 0.55, '
                          f'ease: "power3.out"}}, {_r(st)});')
            if plan["loop"]:
                js.append(f'tl.set("#{sid}k", {{opacity: 1}}, {_r(st)});')
            _ease_in_words(js, f"#{sid}c .w", st + 0.2)
            nw = sum(len(_words(C.plain(ln))) for ln in lines)
            js.append(f'tl.to("#{sid}c .mk", {{backgroundSize: "100% 46%", duration: 0.55, ease: "power2.out"}}, '
                      f'{_r(st + 0.25 + 0.055 * nw * 0.5 + 0.3)});')
            for k in s["cam"][1:]:
                js.append(f'tl.to("#{sid}m", {{x: {k["x"]}, y: {k["y"]}, scale: {k["scale"]}, duration: {k["d"]}, '
                          f'ease: "{k["ease"]}"}}, {_r(st + k["t"])});')
            if vo_on and s.get("vo"):
                vsrc, vdur = _vo(cfg, s, proj, lang)
                body.append(f'<audio src="{vsrc}" data-start="{_r(st + 0.35)}" data-duration="{_r(vdur)}" '
                            f'data-track-index="8" data-volume="1"></audio>')
        elif s["kind"] == "title":
            mpx = int(L["title_px"] * 1.05)
            ty = H * (0.36 if H > W else 0.33)
            if mark:
                inner.append(f'<img class="mark" id="{sid}i" src="{mark}" alt="" style="left:{(W - mpx) // 2}px; '
                             f'top:{int(ty - mpx * 1.35)}px; width:{mpx}px; height:{mpx}px">')
                js.append(f'tl.fromTo("#{sid}i", {{opacity: 0, scale: .86}}, {{opacity: 1, scale: 1, duration: .6, '
                          f'ease: "back.out(1.6)"}}, 0.05);')
            name = p["name"] + (f" {C.text(p.get('name_zh'), lang)}" if lang == "zh" and p.get("name_zh") else "")
            inner.append(f'<div class="center title" id="{sid}t" style="top:{int(ty)}px; font-size:{L["title_px"]}px">'
                         f'{caption_html([name])}</div>')
            _ease_in_words(js, f"#{sid}t .w", 0.25, stagger=0.08, dur=0.5)
            ol = C.text(p.get("one_liner"), lang)
            olw = W - 2 * L["text"][0]
            opx, olines = B.fit(ol, files["display"], (L["oneliner_px"], int(L["oneliner_px"] * 0.7)), olw, 2, lang, 420)
            oy = int(ty + L["title_px"] * 1.35)
            inner.append(f'<div class="center oneliner" id="{sid}o" style="top:{oy}px; font-size:{opx}px">'
                         f'{caption_html(olines)}</div>')
            _ease_in_words(js, f"#{sid}o .w", 0.7, stagger=0.045, dur=0.42)
            if p.get("version"):
                cy = oy + int(opx * 1.3 * len(olines) + opx * 0.9)
                inner.append(f'<div class="center" style="top:{cy}px"><span class="chip" id="{sid}v" '
                             f'style="font-size:{int(L["kicker_px"] * 0.95)}px">{_e(p["version"])}</span></div>')
                js.append(f'tl.fromTo("#{sid}v", {{opacity: 0, y: 10}}, {{opacity: 1, y: 0, duration: .4, '
                          f'ease: "power2.out"}}, 1.25);')
        elif s["kind"] == "end":
            ty = H * (0.34 if H > W else 0.3)
            lw = int(min(W * 0.46, 760))
            if logo:
                inner.append(f'<img class="mark" id="{sid}l" src="{logo}" alt="" style="left:{(W - lw) // 2}px; '
                             f'top:{int(ty)}px; width:{lw}px">')
                js.append(f'tl.fromTo("#{sid}l", {{opacity: 0, y: 18}}, {{opacity: 1, y: 0, duration: .55, '
                          f'ease: "power3.out"}}, {_r(st + 0.1)});')
                cy = ty + lw * 0.32
            else:
                inner.append(f'<div class="center title" id="{sid}n" style="top:{int(ty)}px; '
                             f'font-size:{L["title_px"]}px">{caption_html([p["name"]])}</div>')
                _ease_in_words(js, f"#{sid}n .w", st + 0.1)
                cy = ty + L["title_px"] * 1.4
            cta = C.text(end.get("cta"), lang) or C.text(p.get("one_liner"), lang)
            cpx, clines = B.fit(cta, files["display"], (int(L["oneliner_px"] * 1.1), int(L["oneliner_px"] * 0.7)),
                                W - 2 * L["text"][0], 2, lang, DISPLAY_W)
            inner.append(f'<div class="center cta" id="{sid}c" style="top:{int(cy)}px; font-size:{cpx}px">'
                         f'{caption_html(clines)}</div>')
            _ease_in_words(js, f"#{sid}c .w", st + 0.35, stagger=0.05)
            sy = cy + cpx * 1.25 * len(clines) + cpx * 0.6
            if p.get("site"):
                site = p["site"].replace("https://", "").replace("http://", "").rstrip("/")
                inner.append(f'<div class="center site" id="{sid}s" style="top:{int(sy)}px; '
                             f'font-size:{int(cpx * 0.72)}px">{_e(site)}</div>')
                js.append(f'tl.fromTo("#{sid}s", {{opacity: 0}}, {{opacity: 1, duration: .4}}, {_r(st + 0.9)});')
                sy += cpx * 1.2
            sub = C.text(end.get("sub"), lang)
            if sub:
                inner.append(f'<div class="center sub" id="{sid}u" style="top:{int(sy)}px; '
                             f'font-size:{int(L["kicker_px"] * 0.95)}px">{_e(sub)}</div>')
                js.append(f'tl.fromTo("#{sid}u", {{opacity: 0}}, {{opacity: 1, duration: .4}}, {_r(st + 1.1)});')
        body.append(f'<div class="scene clip" id="{sid}" data-start="{_r(st)}" data-duration="{_r(du)}" '
                    f'data-track-index="{track}">' + "".join(inner) + "</div>")
    if plan["loop"]:
        # tail: a still of the first scene's opening frame fades in over the last crossfade -> seamless loop
        s0 = plan["scenes"][0]
        m = s0["media"]
        first = (_frame(m["file"], m["at"], proj, "tail-first.jpg") if m["kind"] == "video"
                 else _asset(m["file"], proj, "shots"))
        wx, wy, ww, wh = L["win"]
        x0, y0, _, _ = L["text"]
        k0 = s0["cam"][0]
        sw, sh = m.get("w") or ww, m.get("h") or wh
        kick = plan["scenes"][0]["kicker"]
        kpx0 = L["kicker_px"]
        px0, lines0 = _fit_caption(s0["caption"], lang, L, files)
        y0 = max(y0 + int(kpx0 * 1.9), L["win"][1] - L.get("gap", 36) - int(px0 * 1.16 * len(lines0))) - int(kpx0 * 1.9)
        tail_at = total - plan["xf"]
        body.append(f'<div class="scene clip" id="tail" data-start="{_r(tail_at)}" data-duration="{_r(plan["xf"])}" '
                    f'data-track-index="5"><div class="kicker" style="left:{x0}px; top:{y0}px; '
                    f'font-size:{L["kicker_px"]}px; opacity:1"><i></i>{_e(kick)}</div>'
                    f'<div class="win" style="left:{wx}px; top:{wy}px; width:{ww}px; height:{wh}px; opacity:1">'
                    f'<div class="cam" id="tailm" style="width:{sw}px; height:{sh}px"><img src="{first}" alt="">'
                    f'</div></div></div>')
        js.append(f'tl.set("#tailm", {{x: {k0["x"]}, y: {k0["y"]}, scale: {k0["scale"]}}}, 0);')
        js.append(f'tl.fromTo("#tail", {{opacity: 0}}, {{opacity: 1, duration: {plan["xf"]}, ease: "none"}}, {_r(tail_at)});')
    if vo_on:
        label = "AI 配音" if lang == "zh" else "AI voice"
        body.append(f'<div class="ailabel clip" data-start="0" data-duration="{_r(total)}" data-track-index="9" '
                    f'style="left:{L["text"][0]}px; bottom:{max(24, int(H * 0.03))}px">{label}</div>')
    music = _music(cfg, proj, total)
    if music:
        vol = 0.22 if vo_on else 0.5
        body.append(f'<audio src="{music}" data-start="0" data-duration="{_r(total)}" data-track-index="7" '
                    f'data-volume="{vol}"></audio>')
    doc = f"""<!doctype html>
<html lang="{'zh-CN' if lang == 'zh' else 'en'}"><head><meta charset="utf-8">
<script src="{GSAP}"></script>
<style>
{css}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-width="{W}" data-height="{H}" data-duration="{_r(total)}">
{chr(10).join(body)}
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
window.__timelines = window.__timelines || {{}};
window.__timelines["main"] = tl;
</script>
</body></html>
"""
    with open(os.path.join(proj, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)
    with open(os.path.join(proj, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    with open(os.path.join(proj, "cues.json"), "w", encoding="utf-8") as f:
        json.dump({"cues": cues}, f, ensure_ascii=False, indent=1)
    if not quiet:
        print(f"built {proj} ({plan['cut']} {lang} {plan['aspect']}, {total:.1f}s, {len(plan['scenes'])} scenes)")
    return proj


# ------------------------------------------------------------------------------------------------ render
def render(proj, out, quality="delivery", fps=30, lufs=-14.0):
    """HyperFrames render -> deliver: loudness (only when there is audio), BT.709 tags, +faststart."""
    if not shutil.which("npx"):
        raise RuntimeError("npx (Node) not found: HyperFrames needs Node 18+")
    raw = os.path.join(proj, "renders", "_raw.mp4")
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    r = subprocess.run(hyperframes_cmd() + ["render", "--quality", quality, "--fps", str(fps),
                                            "--video-frame-format", "png", "--output", "renders/_raw.mp4"], cwd=proj, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(raw):
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-25:])
        raise RuntimeError(f"hyperframes render failed in {proj}:\n{tail}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    info = media.probe(raw)
    if info.get("has_audio"):
        from vstudio import audio
        tmp = out[:-4] + ".loud.mp4"
        audio.loudnorm_2pass(raw, tmp, lufs=lufs)
        media.retag_bt709(tmp, out)
        os.remove(tmp)
    else:
        media.retag_bt709(raw, out)
    return out


def cover(video, t, out):
    """A cover = one frame of the video (same canvas), JPEG."""
    return media.grab_frame(video, t, out, quality=2)


def gif(video, out, width=960, fps=15):
    """Looping GIF for a README (palette per file, no dither banding on flat paper)."""
    pal = out + ".palette.png"
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    media.run(["ffmpeg", "-y", "-i", video, "-vf", vf + ",palettegen=max_colors=128:stats_mode=diff", pal])
    media.run(["ffmpeg", "-y", "-i", video, "-i", pal, "-lavfi",
               vf + " [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", "-loop", "0", out])
    os.remove(pal)
    return out
