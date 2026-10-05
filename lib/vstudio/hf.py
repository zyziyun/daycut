"""HyperFrames effect generators: CSS / HTML / GSAP snippets any HyperFrames project can compose.

Every generator returns a dict {"css", "html", "js"} (missing parts are ""). Paste css into one <style>,
html into the root composition, js after `const tl = gsap.timeline({ paused: true })` (see prelude()).

    from vstudio import hf
    tl = hf.prelude()                                         # const tl + const $ helper
    ss = hf.split_screen([[3.0, 9.5]], inset="inset(40px 520px 120px 500px round 28px)", x=-440)
    cards = hf.screenshot_cards([dict(id="c1", img="assets/img/shot.png", w=1200, h=2400, s=3.0, e=9.5,
                                      scroll=[[3.0, 0], [6.0, 400]], hl=[[4.0, 120, 170, 0.6]])])
    tr = hf.scene_transitions([hf.transition("push", "w-a", "w-b", at=12.0, d=0.7)])

Values: any time / number / list argument may be a Python value (inlined as JSON) or `JS("D.X")`, a raw
JS expression, so a page can keep its data in one object (promo-recut does: `const D = {...}`) and the
generators just reference it. HTML timing (data-start / data-duration) always takes Python numbers.

HyperFrames rules these snippets respect (learned the hard way in this repo):
  * every overlay starts at `opacity: 0` in CSS and is revealed by the timeline (seek-safe, no flash at t=0);
  * one `fromTo` per target - later moves use `to()`; scene transitions use `immediateRender: false`
    on incoming tweens and an identity `tl.set` baseline at t=0;
  * the outgoing scene / clip must still be alive while a transition runs (extend its data-duration);
  * asset paths are project-root-relative (`assets/img/x.png`, never `../assets/...`).
Style reference: vstudio.overlays.hf_progress / hf_cue_css (progress bar + subtitle cue CSS live there).
"""
import json

__all__ = ["JS", "prelude", "subtitles", "split_screen", "punch_in", "punch_at", "screenshot_cards", "chips",
           "freeze_clips", "freeze_hold", "zoom_through", "framed_screen", "grid_backdrop_css", "step_labels",
           "badge", "tag", "title_card", "enter_zoom", "stamp", "end_card", "transition", "scene_transitions",
           "TRANSITIONS", "indent", "subtitles_html"]


class JS(str):
    """A raw JavaScript expression (emitted verbatim instead of JSON-encoded)."""


def _v(x):
    return str(x) if isinstance(x, JS) else json.dumps(x, ensure_ascii=False)


def _t(base, *offs):
    """JS time expression `base + off ...`; offsets may be numbers or JS."""
    s = _v(base)
    for o in offs:
        if isinstance(o, JS):
            s += f" + {o}"
        elif o > 0:
            s += f" + {o}"
        elif o < 0:
            s += f" - {-o}"
    return s


def r(x):
    return round(x, 3)


def indent(text, n):
    """Indent every non-empty line by n spaces (to nest a snippet inside a block)."""
    pad = " " * n
    return "".join(pad + ln if ln.strip() else ln for ln in text.splitlines(True))


def _out(css="", html="", js=""):
    return {"css": css, "html": html, "js": js}


def prelude(tl="tl"):
    """Timeline + `$` helper every snippet below assumes."""
    return (f"const {tl} = gsap.timeline({{ paused: true }});\n"
            "const $ = (s) => document.querySelector(s);\n")


# ---------------------------------------------------------------- text & captions
def subtitles(cues, container="#subs", height=1080, tl="tl"):
    """Keyword subtitles: cues [{s, e, t}] where t is already-escaped HTML (vstudio.overlays.cue_html turns
    【term】 into <em>). Pair with overlays.hf_cue_css for the .cue style. Each cue pops up (y 14 -> 0) and
    fades out. css = the container; place subtitles_html(start, duration) in the root."""
    css = f"{container} {{ position: absolute; left: 0; right: 0; top: 0; height: {height}px; pointer-events: none; }}\n"
    js = (f'const subs = $("{container}");\n'
          f"{_v(cues)}.forEach((c, i) => {{\n"
          '  const el = document.createElement("div"); el.className = "cue"; el.id = "cue" + i;\n'
          "  el.innerHTML = c.t; subs.appendChild(el);   // escaped, 【term】 -> <em> (vstudio.overlays.cue_html)\n"
          f'  {tl}.fromTo(el, {{ opacity: 0, y: 14 }}, {{ opacity: 1, y: 0, duration: 0.18, ease: "power2.out" }}, c.s);\n'
          f'  {tl}.to(el, {{ opacity: 0, duration: 0.12, ease: "none" }}, Math.max(c.s + 0.25, c.e - 0.12));\n'
          "});\n")
    return _out(css, "", js)


def subtitles_html(start, duration, container="subs", track=7):
    return f'<div id="{container}" class="clip" data-start="{start}" data-duration="{r(duration)}" data-track-index="{track}"></div>'


# ---------------------------------------------------------------- camera / zoom
def split_screen(windows, inset, x=0, y=0, target="#face", dur=0.7, lead=0.15, tail=0.3, bridge=0.2, tl="tl",
                 scale=None):
    """Split screen: the full-frame `target` (a wrapper around the talking-head video) is clipped to `inset`
    (CSS clip-path inset(...)) and slid by (x, y) for each [start, end] window, then restored. Windows closer
    than `bridge` s are merged so the face does not bounce. Put the other half (cards, a screen recording)
    in the freed area. scale: optional zoom of the clipped band (transform-origin 0 0; < 1 shows more of
    the frame in the same band, > 1 tighter); `inset` and (x, y) are in the unscaled element's px."""
    W = _v(windows)
    sc_in = f", scale: {_v(scale)}" if scale is not None else ""
    sc_out = ", scale: 1" if scale is not None else ""
    css = f"{target} {{ transform-origin: 0 0; }}\n"
    js = ('const FULL = "inset(0px 0px 0px 0px round 0px)";\n'
          f'{tl}.set("{target}", {{ clipPath: FULL, x: 0, y: 0{sc_out} }}, 0);\n'
          f"{W}.forEach(([s, e], i) => {{\n"
          f"  const prevEnd = i ? {W}[i - 1][1] : -1;\n"
          f'  if (s - prevEnd > {bridge}) {tl}.to("{target}", {{ clipPath: {_v(inset)}, x: {_v(x)}, y: {_v(y)}{sc_in}, duration: {dur}, ease: "power3.inOut" }}, s - {lead});\n'
          f"  const next = {W}[i + 1];\n"
          f'  if (!next || next[0] - e > {bridge}) {tl}.to("{target}", {{ clipPath: FULL, x: 0, y: 0{sc_out}, duration: {dur}, ease: "power3.inOut" }}, e - {tail});\n'
          "});\n")
    return _out(css, "", js)


def punch_in(windows, target="#face-zoom", scale=1.14, in_dur=0.45, out_dur=0.5, tl="tl"):
    """Punch-in zoom: scale `target` up at each window start, back to 1 at its end. Use an inner wrapper
    (not the video) so it composes with split_screen / zoom_through on the outer one."""
    js = (f"{_v(windows)}.forEach(([s, e]) => {{\n"
          f'  {tl}.to("{target}", {{ scale: {scale}, duration: {in_dur}, ease: "power2.out" }}, s);\n'
          f'  {tl}.to("{target}", {{ scale: 1.0, duration: {out_dur}, ease: "power2.inOut" }}, e);\n'
          "});\n")
    return _out("", "", js)


def punch_at(target, at, scale=1.16, dur=0.5, origin="50% 38%", tl="tl"):
    """Single punch-in that stays (e.g. on the punchline before a stamp)."""
    return _out("", "", f'{tl}.to("{target}", {{ scale: {scale}, duration: {dur}, ease: "power2.out", transformOrigin: "{origin}" }}, {_v(at)});\n')


def enter_zoom(target, at, from_scale=1.15, dur=0.6, tl="tl"):
    """Wrapper entrance: settles from from_scale + transparent to 1 (outro after a montage). css hides it."""
    return _out(f"{target} {{ opacity: 0; }}\n", "",
                f'{tl}.fromTo("{target}", {{ scale: {from_scale}, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: {dur}, ease: "power3.out" }}, {_v(at)});\n')


# ---------------------------------------------------------------- cards & overlays
def screenshot_cards(cards, card_w=760, card_h=740, left=1100, top=60, accent="#FF2442", tl="tl",
                     cards_js=None, card_w_js=None):
    """3D screenshot cards: slide in with rotationY, drift, scroll the image to [t, y] keyframes, highlighter
    rows sweep in ([t, y0, y1, width fraction], image px) and an optional red box [t, y0, y1] pops.
    cards: [{id, img, w, h, s, e, scroll: [[t, y], ...], hl: [...], box?}] (w/h = image px).
    cards_js / card_w_js: JS expressions to reference instead of inlining (html still uses the Python values)."""
    CW = _v(card_w_js if card_w_js is not None else card_w)
    cw = card_w
    css = (f".card {{ position: absolute; left: {left}px; top: {top}px; width: {cw}px; height: {card_h}px; border-radius: 22px; overflow: hidden; background: #fff;\n"
           f"  box-shadow: 0 30px 80px rgba(0,0,0,.45), 0 0 0 1px rgba(0,0,0,.08); opacity: 0; }}\n"
           f".card img {{ position: absolute; left: 0; top: 0; width: {cw}px; display: block; }}\n"
           ".hl { position: absolute; left: 14px; height: 0; background: rgba(255, 214, 10, .45); mix-blend-mode: multiply; border-radius: 6px; transform-origin: 0 50%; }\n"
           f".box {{ position: absolute; left: 10px; width: {cw - 20}px; border: 5px solid {accent}; border-radius: 16px; transform-origin: 50% 50%; opacity: 0; }}\n")
    html = "".join(f'<div class="card" id="{cd["id"]}"><div class="scroller" id="{cd["id"]}-s"><img src="{cd["img"]}" alt="" /><div id="{cd["id"]}-hls"></div></div></div>'
                   for cd in cards)
    js = (f"{_v(cards_js if cards_js is not None else cards)}.forEach((c) => {{\n"
          f"  const k = {CW} / c.w;\n"
          '  const card = $("#" + c.id), scr = $("#" + c.id + "-s"), hls = $("#" + c.id + "-hls");\n'
          f"  {tl}.fromTo(card, {{ opacity: 0, x: 140, rotationY: -28, transformPerspective: 1400 }},\n"
          '                  { opacity: 1, x: 0, rotationY: -6, duration: 0.75, ease: "power3.out" }, c.s);\n'
          f'  {tl}.to(card, {{ rotationY: -2, y: -8, duration: Math.max(1, c.e - c.s - 1.2), ease: "sine.inOut" }}, c.s + 0.75);\n'
          f'  {tl}.to(card, {{ opacity: 0, x: 80, rotationY: 18, duration: 0.45, ease: "power2.in" }}, c.e - 0.45);\n'
          f"  {tl}.set(scr, {{ y: -c.scroll[0][1] * k }}, 0);\n"
          "  c.scroll.slice(1).forEach(([t, y], j) => {\n"
          "    const t0 = c.scroll[j][0];\n"
          f'    {tl}.to(scr, {{ y: -y * k, duration: Math.min(1.2, Math.max(0.6, t - t0)), ease: "power2.inOut" }}, t - 0.2);\n'
          "  });\n"
          "  (c.hl || []).forEach(([t, y0, y1, frac], j) => {\n"
          '    const h = document.createElement("div"); h.className = "hl"; h.id = c.id + "-hl" + j;\n'
          f'    h.style.top = (y0 * k - 6) + "px"; h.style.height = ((y1 - y0) * k + 12) + "px"; h.style.width = (({CW} - 28) * frac) + "px";\n'
          "    hls.appendChild(h);\n"
          f'    {tl}.fromTo(h, {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.5, ease: "power2.out" }}, t);\n'
          "  });\n"
          "  if (c.box) {\n"
          '    const [t, y0, y1] = c.box, b = document.createElement("div"); b.className = "box"; b.id = c.id + "-box";\n'
          '    b.style.top = (y0 * k - 10) + "px"; b.style.height = ((y1 - y0) * k + 20) + "px"; hls.appendChild(b);\n'
          f'    {tl}.fromTo(b, {{ opacity: 0, scale: 1.15 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)" }}, t);\n'
          "  }\n"
          "});\n")
    return _out(css, html, js)


def chips(items, end, left=1080, top=822, width=800, ink="#ECEEF2", gold="#F4D35E", tl="tl", items_js=None):
    """Row of pills that pop in one by one ([t, text, star]); star = gold fill. All fade at `end`.
    html is the #chips row (place it inside a clip). items_js overrides the JS data reference."""
    css = (f"#chips {{ position: absolute; left: {left}px; top: {top}px; width: {width}px; display: flex; gap: 9px; flex-wrap: nowrap; }}\n"
           f'.chip {{ font: 700 23px "CJK"; color: {ink}; padding: 7px 14px; border-radius: 999px; background: rgba(16,20,34,.82);\n'
           "  border: 2px solid rgba(255,255,255,.22); opacity: 0; white-space: nowrap; }\n"
           f".chip.star {{ color: #111; background: {gold}; border-color: {gold}; }}\n")
    inner = "".join(f'<div class="chip{" star" if st else ""}" id="chip{i}">{t}</div>' for i, (_, t, st) in enumerate(items))
    I = _v(items_js if items_js is not None else items)
    js = (f"{I}.forEach(([t], i) => {{\n"
          f'  {tl}.fromTo("#chip" + i, {{ opacity: 0, y: 16, scale: 0.9 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.3, ease: "back.out(1.7)" }}, t);\n'
          "});\n"
          f'if ({I}.length) {tl}.to("#chips", {{ opacity: 0, duration: 0.35 }}, {_t(end, -0.4)});\n')
    return _out(css, f'<div id="chips">{inner}</div>', js)


def badge(text, start, duration, at, left=160, top=954, accent="#FF2442", el="mbadge", track=4, tl="tl"):
    """Small solid label (e.g. 精选) that slides in from the left at `at`."""
    css = f'#{el} {{ position: absolute; left: {left}px; top: {top}px; padding: 4px 16px; border-radius: 10px; background: {accent}; color: #fff; font: 700 28px "CJK"; opacity: 0; }}\n'
    html = f'<div id="{el}" class="clip" data-start="{r(start)}" data-duration="{r(duration)}" data-track-index="{track}">{text}</div>' if text else ""
    js = f'if ($("#{el}")) {tl}.fromTo("#{el}", {{ opacity: 0, x: -20 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "power2.out" }}, {_v(at)});\n'
    return _out(css, html, js)


def tag(text, start, duration, at, pos_css="right:160px; top:956px;", el="mtag", track=4, tl="tl"):
    """Outlined pill (e.g. 完整版 · 节选 · 1.1×) that fades in."""
    css = (f'#{el} {{ position: absolute; {pos_css} font: 400 24px "CJK"; color: rgba(236,238,242,.75); padding: 8px 18px;\n'
           "  border: 1.5px solid rgba(236,238,242,.3); border-radius: 999px; opacity: 0; }\n")
    html = f'<div id="{el}" class="clip" data-start="{r(start)}" data-duration="{r(duration)}" data-track-index="{track}">{text}</div>' if text else ""
    js = f'if ($("#{el}")) {tl}.fromTo("#{el}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5 }}, {_v(at)});\n'
    return _out(css, html, js)


def title_card(title, start, at, sub=None, top=400, size=96, gold="#F4D35E", el="mtitle", hold=1.9, track=5, tl="tl"):
    """Centred boxed title + gold subtitle that pops in (back.out) at `at` and lifts away `hold` s later."""
    css = (f"#{el} {{ position: absolute; left: 0; right: 0; top: {top}px; display: flex; flex-direction: column; align-items: center; gap: 18px; opacity: 0; }}\n"
           f'#{el} span {{ font: 700 {size}px "CJK"; color: #fff; padding: 18px 56px; border-radius: 24px; background: rgba(11,16,32,.82); border: 2px solid {gold}b3; text-shadow: 0 6px 30px rgba(0,0,0,.6); }}\n'
           f'#{el} small {{ font: 400 34px "CJK"; color: {gold}; text-shadow: 0 2px 10px rgba(0,0,0,.9); }}\n')
    html = ""
    if title:
        html = (f'<div id="{el}" class="clip" data-start="{r(start)}" data-duration="{round(hold + 0.5, 3)}" data-track-index="{track}"><span>{title}</span>'
                + (f"<small>{sub}</small>" if sub else "") + "</div>")
    js = (f'if ($("#{el}")) {{\n'
          f'  {tl}.fromTo("#{el}", {{ opacity: 0, scale: 0.92 }}, {{ opacity: 1, scale: 1, duration: 0.45, ease: "back.out(1.6)" }}, {_t(at, 0.05)});\n'
          f'  {tl}.to("#{el}", {{ opacity: 0, y: -20, duration: 0.4, ease: "power2.in" }}, {_t(at, round(hold + 0.05, 3))});\n'
          "}\n")
    return _out(css, html, js)


def stamp(text, start, duration, at, left=1290, top=230, accent="#FF2442", size=96, angle=-12, el="stamp", track=4, tl="tl"):
    """Rubber stamp: bordered word slams in from scale 2.2 at `at` (back.out), tilted `angle` deg."""
    css = (f'#{el} {{ position: absolute; left: {left}px; top: {top}px; padding: 10px 30px; border: 7px solid {accent}; color: {accent}; font: 700 {size}px "CJK";\n'
           "  border-radius: 18px; opacity: 0; background: rgba(255,255,255,.12); }\n")
    html = f'<div id="{el}" class="clip" data-start="{r(start)}" data-duration="{r(duration)}" data-track-index="{track}">{text}</div>' if text else ""
    js = f'if ($("#{el}")) {tl}.fromTo("#{el}", {{ opacity: 0, scale: 2.2, rotation: {angle} }}, {{ opacity: 1, scale: 1, rotation: {angle}, duration: 0.3, ease: "back.out(2)" }}, {_v(at)});\n'
    return _out(css, html, js)


def end_card(start, duration, kicker="", main="", sub="", at=None, size=80, gold="#F4D35E", track=5, tl="tl"):
    """End card: serif kicker, big main line, dim sub line, staggered fade-ups from `at` (default start)."""
    at = start if at is None else at
    css = ("#endcard { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 0 60px; }\n"
           f'#end-k {{ font: italic 46px "Serif"; color: {gold}; opacity: 0; }}\n'
           f'#end-m {{ margin-top: 26px; font: 700 {size}px "CJK"; color: #fff; opacity: 0; }}\n'
           '#end-s { margin-top: 30px; font: 400 34px "CJK"; color: rgba(236,238,242,.75); opacity: 0; }\n')
    html = (f'<div id="endcard" class="full clip" data-start="{r(start)}" data-duration="{r(duration)}" data-track-index="{track}">\n'
            f'    <div id="end-k">{kicker}</div>\n'
            f'    <div id="end-m">{main}</div>\n'
            f'    <div id="end-s">{sub}</div>\n'
            "  </div>")
    js = (f'{tl}.fromTo("#end-k", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, {_t(at, 0.15)});\n'
          f'{tl}.fromTo("#end-m", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.55, ease: "power2.out" }}, {_t(at, 0.45)});\n'
          f'{tl}.fromTo("#end-s", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5 }}, {_t(at, 1.0)});\n')
    return _out(css, html, js)


# ---------------------------------------------------------------- freeze / hold
def freeze_clips(src, freeze_src, start, cut_at, hold, media_dur, rate=1.0, ids=("body", "freeze", "body2"), track=2):
    """Freeze-frame hold in the media layer: the video is split into two clips with a still (extract it with
    ffmpeg -ss cut_at -frames:v 1) between them; the second clip resumes via data-media-start.
    cut_at = media second of the freeze; media_dur = total media seconds; returns html only."""
    a, f, b = ids
    T = start + cut_at / rate
    return (f'<video id="{a}" class="full" src="{src}" playsinline data-has-audio="true" data-start="{r(start)}" data-duration="{r(cut_at / rate)}" data-playback-rate="{rate}" data-track-index="{track}" data-volume="1"></video>\n'
            f'    <img id="{f}" class="full clip" src="{freeze_src}" alt="" data-start="{r(T)}" data-duration="{r(hold)}" data-track-index="{track}" />\n'
            f'    <video id="{b}" class="full" src="{src}" playsinline data-has-audio="true" data-start="{r(T + hold)}" data-duration="{r((media_dur - cut_at) / rate)}" data-media-start="{r(cut_at)}" data-playback-rate="{rate}" data-track-index="{track}" data-volume="1"></video>')


def freeze_hold(at, hold, fly_from=(380, -150), label="", image="", left=160, top=250, width=1600,
                accent="#FF2442", gold="#F4D35E", clip=None, track=6, tl="tl"):
    """Over a frozen frame: dim the picture and fly a zoomed card (e.g. the prompt from a screenshot) out
    from offset `fly_from` (towards where it sits in the screenshot), hold, fly it back. clip = (start, dur)
    for the html data-start/duration (default (at, hold) when those are numbers)."""
    css = ("#pz-dim { background: rgba(5,8,16,.72); opacity: 0; }\n"
           f"#pz-box {{ position: absolute; left: {left}px; top: {top}px; width: {width}px; padding: 26px 30px 30px; border-radius: 26px; background: #EFEFEC;\n"
           f"  box-shadow: 0 40px 120px rgba(0,0,0,.6), 0 0 0 6px {accent}; transform-origin: 85% 10%; opacity: 0; }}\n"
           f'#pz-label {{ position: absolute; left: 0; top: -70px; font: 700 40px "CJK"; color: {gold}; opacity: 0; }}\n'
           f"#pz-img {{ display: block; width: {width - 60}px; }}\n")
    cs, cd = clip if clip else (at, hold)
    html = (f'<div id="pz" class="clip full" data-start="{r(cs)}" data-duration="{r(cd)}" data-track-index="{track}">\n'
            f'    <div id="pz-dim" class="full"></div>\n'
            f'    <div id="pz-box"><div id="pz-label">{label}</div>'
            + (f'<img id="pz-img" src="{image}" alt="" />' if image else "") + "</div>\n  </div>")
    F = _v(list(fly_from) if not isinstance(fly_from, JS) else fly_from)
    fx, fy = (JS(f"{F}[0]"), JS(f"{F}[1]")) if isinstance(fly_from, JS) else (fly_from[0], fly_from[1])
    end = JS(f"{_v(at)} + {_v(hold)}")
    js = (f'{tl}.fromTo("#pz-dim", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, {_v(at)});\n'
          f'{tl}.fromTo("#pz-box", {{ opacity: 0, scale: 0.3, x: {_v(fx)}, y: {_v(fy)} }}, {{ opacity: 1, scale: 1, x: 0, y: 0, duration: 0.45, ease: "power3.out" }}, {_v(at)});\n'
          f'{tl}.fromTo("#pz-label", {{ opacity: 0, y: 10 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, {_t(at, 0.35)});\n'
          f'{tl}.to("#pz-box", {{ opacity: 0, scale: 0.3, x: {_v(fx)}, y: {_v(fy)}, duration: 0.35, ease: "power2.in" }}, {_t(end, -0.38)});\n'
          f'{tl}.to("#pz-dim", {{ opacity: 0, duration: 0.3 }}, {_t(end, -0.3)});\n')
    return _out(css, html, js)


# ---------------------------------------------------------------- framed screen / zoom-through
def grid_backdrop_css(el="plate-grid", cell=64):
    """Faint square grid behind a framed screen."""
    return (f"#{el} {{ background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), "
            f"linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px); background-size: {cell}px {cell}px; }}\n")


def framed_screen(src, start, duration, exit_at, rate=1.0, left=0, top=0, width=1920, height=1080,
                  video_id="montage", grid=True, track=3, grid_track=1, tl="tl"):
    """A rounded, shadowed "screen" (#screen > #screen-frame > video) on a grid backdrop. Enter it with
    zoom_through(); js here = the exit (frame shrinks away at exit_at - 0.45; keep the clip alive until then)."""
    css = ("#screen { transform-origin: 50% 45%; opacity: 0; }\n"
           f"#screen-frame {{ position: absolute; left: {left}px; top: {top}px; width: {width}px; height: {height}px; border-radius: 26px; overflow: hidden;\n"
           "  box-shadow: 0 40px 120px rgba(0,0,0,.6), 0 0 0 2px rgba(255,255,255,.12); }\n"
           f"#{video_id} {{ position: absolute; left: 0; top: 0; width: {width}px; height: {height}px; object-fit: cover; }}\n")
    html = ((f'<div id="plate-grid" class="full clip" data-start="{r(start)}" data-duration="{r(duration)}" data-track-index="{grid_track}"></div>\n  ' if grid else "")
            + '<div id="screen" class="wrap"><div id="screen-frame">\n'
            f'    <video id="{video_id}" src="{src}" playsinline data-has-audio="true" data-start="{r(start)}" data-duration="{r(duration)}" data-playback-rate="{rate}" data-track-index="{track}" data-volume="1"></video>\n'
            "  </div></div>")
    js = f'{tl}.to("#screen", {{ scale: 0.6, opacity: 0, duration: 0.6, ease: "power3.in" }}, {_t(exit_at, -0.45)});\n'
    return _out(css, html, js)


def zoom_through(at, until, scale_in=0.84, y=-44, drift=0.85, source="#face", screen="#screen", tl="tl"):
    """Zoom through the current shot into a framed screen: `source` scales up + blurs out while the screen
    lands from 1.25 to scale_in, then drifts to `drift` until `until`. Keep `source`'s video playing ~0.5 s
    past `at` (overlap) so nothing goes blank."""
    js = (f'{tl}.to("{source}", {{ scale: 1.35, opacity: 0, filter: "blur(10px)", transformOrigin: "50% 45%", duration: 0.7, ease: "power3.in" }}, {_t(at, -0.1)});\n'
          f'{tl}.fromTo("{screen}", {{ scale: 1.25, opacity: 0 }}, {{ scale: {_v(scale_in)}, y: {_v(y)}, opacity: 1, duration: 0.9, ease: "power3.out" }}, {_t(at, 0.1)});\n'
          f'{tl}.to("{screen}", {{ scale: {_v(drift)}, duration: Math.max(0.5, {_v(until)} - {_v(at)} - 1.5), ease: "sine.inOut" }}, {_t(at, 1.0)});\n')
    return _out("", "", js)


def step_labels(labels, start, duration, left=262, top=958, ink="#ECEEF2", gold="#F4D35E", track=4, tl="tl", labels_js=None):
    """Numbered step labels (01 为什么 → 02 ...) that swap in place: labels [{s, e, n, t}]."""
    css = (f'#mlabel {{ position: absolute; left: {left}px; top: {top}px; font: 700 30px "CJK"; color: {ink}; }}\n'
           ".ml { position: absolute; left: 0; top: 0; white-space: nowrap; opacity: 0; }\n"
           f'.ml b {{ font: italic 34px "Serif"; color: {gold}; margin-right: 14px; }}\n')
    html = (f'<div id="mlabel" class="clip" data-start="{r(start)}" data-duration="{r(duration)}" data-track-index="{track}">'
            + "".join(f'<div class="ml" id="ml{m["n"]}"><b>{m["n"]:02d}</b>{m["t"]}</div>' for m in labels) + "</div>")
    js = (f"{_v(labels_js if labels_js is not None else labels)}.forEach((m) => {{\n"
          f'  {tl}.fromTo("#ml" + m.n, {{ opacity: 0, x: -24 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "power2.out" }}, m.s + 0.1);\n'
          f'  {tl}.to("#ml" + m.n, {{ opacity: 0, duration: 0.2 }}, m.e - 0.2);\n'
          "});\n")
    return _out(css, html, js)


# ---------------------------------------------------------------- scene transitions
TRANSITIONS = ("blur", "fade", "push", "vpush", "iris", "zoom", "focus", "blocks", "chroma", "flip", "zoomout")


def transition(type, out_id, in_id, at, d, n=None):
    """One transition spec for scene_transitions(): wrapper ids (no '#'), start second, length."""
    if type not in TRANSITIONS:
        raise ValueError(f"unknown transition {type!r}; one of {TRANSITIONS}")
    t = {"o": out_id, "i": in_id, "type": type, "d": d, "T": at}
    return {"n": n, **t} if n is not None else t


def scene_transitions(trans, W=1920, H=1080, wrap=".scene-wrap", blocks=8, block_color="#111A33",
                      block_edge="#1B2645", tl="tl"):
    """Scene-to-scene transitions on wrapper divs (one untimed wrapper per scene host). trans = list of
    transition() dicts. Types: blur, fade, push, vpush, iris, zoom, focus, blocks, chroma, flip, zoomout.
    The OUTGOING scene must live `d` s past the transition start. html = the #tx-blocks overlay (z 40)."""
    css = (f"{wrap} {{ position: absolute; inset: 0; width: {W}px; height: {H}px; transform-origin: 50% 45%; }}\n"
           "#tx-blocks { position: absolute; inset: 0; z-index: 40; pointer-events: none; display: flex; }\n"
           f".tx-block {{ flex: 1; height: 100%; background: {block_color}; border-right: 1px solid {block_edge}; transform-origin: 50% 0%; }}\n")
    html = '<div id="tx-blocks">' + '<div class="tx-block"></div>' * blocks + "</div>"
    js = f"""const TR = {_v(trans)};
const ID = {{ x: 0, y: 0, scale: 1, rotationY: 0, opacity: 1, filter: "blur(0px)", clipPath: "circle(150% at 50% 45%)" }};
document.querySelectorAll("{wrap}").forEach((w) => {tl}.set(w, ID, 0));
{tl}.set(".tx-block", {{ scaleY: 0 }}, 0);
const IR = {{ immediateRender: false }};
TR.forEach((t) => {{
  const o = "#" + t.o, i = "#" + t.i, T = t.T, d = t.d;
  switch (t.type) {{
    case "blur":
    case "fade": {{
      const b = t.type === "blur" ? 10 : 0;
      {tl}.to(o, {{ opacity: 0, filter: `blur(${{b}}px)`, duration: d, ease: "sine.inOut" }}, T);
      {tl}.fromTo(i, {{ opacity: 0, filter: `blur(${{b}}px)` }}, {{ opacity: 1, filter: "blur(0px)", duration: d, ease: "sine.inOut", ...IR }}, T);
      break; }}
    case "push":
      {tl}.to(o, {{ x: -{W}, filter: "blur(4px)", duration: d, ease: "power3.inOut" }}, T);
      {tl}.fromTo(i, {{ x: {W}, filter: "blur(4px)" }}, {{ x: 0, filter: "blur(0px)", duration: d, ease: "power3.inOut", ...IR }}, T);
      break;
    case "vpush":
      {tl}.to(o, {{ y: -{H}, opacity: 0.4, duration: d, ease: "power3.inOut" }}, T);
      {tl}.fromTo(i, {{ y: {H} }}, {{ y: 0, duration: d, ease: "power3.inOut", ...IR }}, T);
      break;
    case "iris":
      {tl}.to(o, {{ scale: 0.94, opacity: 0, duration: d, ease: "power2.inOut" }}, T);
      {tl}.fromTo(i, {{ clipPath: "circle(0% at 50% 45%)" }}, {{ clipPath: "circle(150% at 50% 45%)", duration: d, ease: "power2.in", ...IR }}, T);
      break;
    case "zoom":
      {tl}.to(o, {{ scale: 1.8, opacity: 0, filter: "blur(10px)", duration: d, ease: "power3.in" }}, T);
      {tl}.fromTo(i, {{ scale: 0.7, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: d, ease: "power3.out", ...IR }}, T + d * 0.25);
      break;
    case "focus":
      {tl}.to(o, {{ filter: "blur(16px)", opacity: 0, scale: 1.04, duration: d, ease: "power2.inOut" }}, T);
      {tl}.fromTo(i, {{ filter: "blur(16px)", opacity: 0, scale: 0.97 }}, {{ filter: "blur(0px)", opacity: 1, scale: 1, duration: d, ease: "power2.inOut", ...IR }}, T + d * 0.3);
      break;
    case "blocks": {{
      const h = d / 2;
      {tl}.fromTo(".tx-block", {{ scaleY: 0, transformOrigin: "50% 0%" }}, {{ scaleY: 1, duration: h, ease: "power3.in", stagger: 0.035, ...IR }}, T);
      {tl}.to(o, {{ opacity: 0, duration: 0.01 }}, T + h + 0.25);
      {tl}.fromTo(i, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.01, ...IR }}, T + h + 0.25);
      {tl}.to(".tx-block", {{ scaleY: 0, transformOrigin: "50% 100%", duration: h, ease: "power3.out", stagger: 0.035 }}, T + h + 0.3);
      break; }}
    case "chroma": {{
      const k = [8, -12, 6, -4, 0];
      const sh = (a) => `drop-shadow(${{a}}px 0 0 rgba(252,98,85,0.75)) drop-shadow(${{-a}}px 0 0 rgba(88,196,221,0.75))`;
      {tl}.to(o, {{ opacity: 0, duration: d * 0.6, ease: "steps(4)" }}, T);
      {tl}.fromTo(i, {{ opacity: 0, x: 18 }}, {{ opacity: 1, x: 0, duration: d * 0.6, ease: "steps(5)", ...IR }}, T + d * 0.15);
      k.forEach((a, j) => {tl}.set([o, i], {{ filter: a ? sh(a) : "none" }}, T + j * d / 5));
      break; }}
    case "flip":
      {tl}.to(o, {{ rotationY: -90, transformPerspective: 1600, opacity: 0.2, duration: d / 2, ease: "power2.in" }}, T);
      {tl}.fromTo(i, {{ rotationY: 90, transformPerspective: 1600, opacity: 0.2 }}, {{ rotationY: 0, opacity: 1, duration: d / 2, ease: "power2.out", ...IR }}, T + d / 2);
      {tl}.set(i, {{ opacity: 0 }}, T);
      break;
    case "zoomout":
      {tl}.to(o, {{ scale: 0.86, opacity: 0, filter: "blur(6px)", duration: d, ease: "power2.inOut" }}, T);
      {tl}.fromTo(i, {{ scale: 1.08, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: d, ease: "power2.out", ...IR }}, T + d * 0.3);
      break;
  }}
}});
"""
    return _out(css, html, js)
