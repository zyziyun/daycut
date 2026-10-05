#!/usr/bin/env python3
"""Generate the HyperFrames index.html for a promo recut from the project config + work/layout.json.

Packaging: split-screen talking head (clip-path inset + slide) next to 3D screenshot cards that scroll to
the part being talked about, highlighter sweeps and a red box; chips row; subtitles with 【term】 highlight;
punch-ins; freeze-frame hold with a prompt card flying out of a screenshot (body video split in two clips +
data-media-start); zoom-through into a framed "screen" playing the highlights montage at its own rate with
step labels + badge/title; outro punch + stamp; end card; chapter progress bar on a scrim.

  python3 $VSTUDIO/workflows/promo-recut/scripts/build_promo.py promo.config.json [--orientation vertical]

Writes <promo_dir>/index.html, copies media + subset fonts into <promo_dir>/assets/, extracts the freeze
frame, and writes <promo_dir>/timeline.json (section + chapter times, used by post_copy.py).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project, P, link_or_copy  # noqa: E402
from vstudio import media, overlays, render  # noqa: E402
from vstudio.cut import TimeMap  # noqa: E402

# ---------------------------------------------------------------- geometry per orientation
GEO = {
    "horizontal": dict(
        W=1920, H=1080, face_pos="50% 50%",
        split_inset="inset(40px 520px 120px 500px round 28px)", split_x=-440, split_y=0,
        card_l=1100, card_t=60, CW=760, CHH=740, chips_l=1080, chips_t=822, chips_w=800,
        cue_lr=160, cue_t=922, cue_fs=50,
        scrim_t=990, scrim_h=90, bar_l=80, bar_t=1046, bar_w=1760, chap_t=1012,
        pz_l=160, pz_t=250, pz_w=1600,
        scr_l=0, scr_t=0, scr_w=1920, scr_h=1080, scr_in=0.84, scr_y=-44, scr_drift=0.85,
        mbadge_l=160, mbadge_t=954, mlabel_l=262, mlabel_t=958, mtag_css="right:160px; top:956px;",
        mtitle_t=400, mtitle_fs=96, stamp_l=1290, stamp_t=230, end_fs=80,
    ),
    "vertical": dict(
        W=1080, H=1920, face_pos="50% 50%",
        split_inset="inset(200px 40px 1000px 40px round 28px)", split_x=0, split_y=0,
        card_l=90, card_t=1000, CW=900, CHH=560, chips_l=60, chips_t=936, chips_w=960,
        cue_lr=60, cue_t=820, cue_fs=54,
        scrim_t=1580, scrim_h=120, bar_l=60, bar_t=1640, bar_w=960, chap_t=1606,
        pz_l=50, pz_t=560, pz_w=980,
        scr_l=0, scr_t=656, scr_w=1080, scr_h=608, scr_in=0.94, scr_y=0, scr_drift=0.95,
        mbadge_l=60, mbadge_t=1296, mlabel_l=170, mlabel_t=1300, mtag_css="left:60px; top:1380px;",
        mtitle_t=360, mtitle_fs=72, stamp_l=560, stamp_t=380, end_fs=60,
    ),
}


def r(x):
    return round(x, 3)


FONT_NAMES = ("cjk-400", "cjk-700", "serif", "serif-italic")
FONT_FMT = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype", ".ttf": "truetype"}


def font_faces(fdir, text=None):
    """Subset Noto Sans SC + STIX Two Text to `text` (vstudio.render.subset_project_fonts), or with
    text=None reuse what is already in fdir. -> {name: (url, css format)}."""
    if text is not None:
        paths = render.subset_project_fonts(fdir, text)
    else:
        have = {os.path.splitext(f)[0]: os.path.join(fdir, f) for f in sorted(os.listdir(fdir))}
        paths = {n: have[n] for n in FONT_NAMES if n in have}
    return {n: (f"assets/fonts/{os.path.basename(p)}", FONT_FMT.get(os.path.splitext(p)[1].lower(), "opentype"))
            for n, p in paths.items()}


def all_strings(x):
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return "".join(all_strings(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return "".join(all_strings(v) for v in x)
    return ""


def scaffold(promo, name):
    os.makedirs(promo, exist_ok=True)
    files = {
        "hyperframes.json": {"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                             "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
                             "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
                             "media": {"autoProxy": True}, "authoringSkill": "general-video"},
        "meta.json": {"id": name, "name": name},
    }
    for fn, data in files.items():
        p = os.path.join(promo, fn)
        if not os.path.exists(p):
            json.dump(data, open(p, "w"), indent=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("config")
    ap.add_argument("--orientation", choices=["horizontal", "vertical"], default=None,
                    help="default: config 'orientation' or horizontal")
    ap.add_argument("--no-fonts", action="store_true", help="skip font subsetting (reuse existing assets/fonts)")
    a = ap.parse_args()

    prj = Project(a.config)
    c = prj.cfg
    ori = a.orientation or c.get("orientation", "horizontal")
    g = dict(GEO[ori]); g.update((c.get("layout") or {}).get(ori, {}))
    W, Hc = g["W"], g["H"]
    promo = prj.p(c.get("promo_dir_vertical" if ori == "vertical" else "promo_dir",
                        "promo-vertical" if ori == "vertical" else "promo"))
    scaffold(promo, os.path.basename(promo))
    L = json.load(open(prj.w("layout.json"), encoding="utf-8"))
    D = L["D"]

    brand = P("brand", {}) or {}
    ACC, HL, INK, GROUND = brand.get("accent", "#FF2442"), brand.get("highlight", "#FFD60A"), brand.get("ink", "#ECEEF2"), brand.get("ground", "#0B1020")
    GOLD = brand.get("highlight_alt", "#F4D35E")

    # ---------------- timeline
    BR = prj.get("rates.body", P("speed.body", 1.1))
    MR = prj.get("rates.montage", P("speed.b_roll", 1.1))
    mcfg = c.get("montage") or {}
    XF = mcfg.get("crossfade", 0.3)
    hold = c.get("hold") or {}
    HOLD_AT, HOLD = (hold.get("at"), hold.get("duration", 2.6)) if hold else (None, 0.0)
    has_m = "montage" in D
    has_o = "outro" in D
    H = 0.0
    B = D["body"] / BR + HOLD
    TZ = mcfg.get("zoom_through", 0.5) if has_m else 0.0
    M = H + B - TZ
    Mdur = D["montage"] / MR if has_m else 0.0
    O = M + Mdur if has_m else H + B
    Odur = D["outro"] / BR if has_o else 0.0
    E = O + Odur
    endc = c.get("end_card") or {}
    END = endc.get("duration", 3.2) if endc else 0.0
    TOTAL = round(E + END, 3)

    bmap = TimeMap.from_list(L["maps"]["body"])
    omap = TimeMap.from_list(L["maps"]["outro"]) if L["maps"].get("outro") else None

    def cut_t(tm, raw):  # raw second -> cut-file second; inside a cut -> start of the next kept span
        t = tm.to_final(raw, snap="fwd")
        return tm.to_final(raw, snap="back") if t is None else t

    def BT(raw):  # raw recording second (body) -> final second
        return H + cut_t(bmap, raw) / BR + (HOLD if HOLD_AT is not None and raw >= HOLD_AT else 0)

    def OT(raw):  # raw recording second (outro) -> final second
        return O + cut_t(omap, raw) / BR

    TC = cut_t(bmap, HOLD_AT) if HOLD_AT is not None else D["body"]
    T_HOLD = H + TC / BR

    def when(x):  # chapter / named anchor -> final second
        if isinstance(x, (int, float)):
            return BT(x)
        return {"start": H, "montage": M + TZ, "outro": O, "end": E}[x]

    # ---------------- subtitles
    subs = c.get("subtitles") or {}
    cues = [{"s": r(BT(s)), "e": r(BT(e) + 0.15), "t": overlays.cue_html(t)} for s, e, t in subs.get("body", [])]
    if has_o:
        cues += [{"s": r(OT(s)), "e": r(OT(e) + 0.15), "t": overlays.cue_html(t)} for s, e, t in subs.get("outro", [])]
    for x, y in zip(cues, cues[1:]):
        if 0 < y["s"] - x["e"] < 0.25:
            x["e"] = r(y["s"] - 0.02)
    for cu in cues:  # captions must be gone before the zoom-through
        if has_m and cu["s"] < M + TZ < cu["e"] + 1:
            cu["e"] = r(min(cu["e"], M - 0.08))

    # ---------------- montage step labels (label null = previous label continues)
    mlab, t = [], 0.0
    for clip in (mcfg.get("clips") or []) if has_m else []:
        s, e = clip[0], clip[1]
        lab = clip[2] if len(clip) > 2 else None
        if lab:
            mlab.append({"s": r(M + TZ + t), "n": len(mlab) + 1, "t": lab})
        t += (e - s - XF) / MR
    for x, y in zip(mlab, mlab[1:]):
        x["e"] = y["s"]
    if mlab:
        mlab[-1]["e"] = r(O - 0.2)

    # ---------------- cards, chips, splits, punches, chapters
    img_dir = os.path.join(promo, "assets", "img")
    from PIL import Image
    CARDS = []
    for i, cd in enumerate(c.get("cards") or []):
        src = prj.p(cd["img"]); base = os.path.basename(src)
        link_or_copy(src, os.path.join(img_dir, base))
        iw, ih = Image.open(src).size
        scroll = cd.get("scroll") or [[cd["start"], 0]]
        CARDS.append({"id": f"c{i + 1}", "img": f"assets/img/{base}", "w": iw, "h": ih,
                      "s": BT(cd["start"]), "e": BT(cd["end"]),
                      "scroll": [[BT(tt), y] for tt, y in scroll],
                      "hl": [[BT(tt), y0, y1, fr] for tt, y0, y1, fr in cd.get("highlights", [])],
                      **({"box": [BT(cd["box"][0]), cd["box"][1], cd["box"][2]]} if cd.get("box") else {})})
    chips = c.get("chips") or {}
    CHIPS = [[BT(tt), txt, int(bool(star[0])) if star else 0] for tt, txt, *star in chips.get("items", [])]
    CHIP_END = BT(chips["end"]) if chips.get("end") is not None else (CARDS[-1]["e"] if CARDS else 0)
    if c.get("split"):
        SPLITS = [[BT(s), BT(e)] for s, e in c["split"]]
    else:  # derive from card windows, bridging short gaps so the face does not bounce
        SPLITS = []
        for cd in CARDS:
            if SPLITS and cd["s"] - SPLITS[-1][1] < 0.8:
                SPLITS[-1][1] = cd["e"]
            else:
                SPLITS.append([cd["s"], cd["e"]])
    PUNCH = [[BT(s), BT(e)] for s, e in c.get("punch", [])]
    chs = c.get("chapters") or []
    CHAP = [[when(x[0]), when(chs[i + 1][0]) if i + 1 < len(chs) else TOTAL, x[1]] for i, x in enumerate(chs)]
    oc = c.get("outro") or {}
    OUTRO_PUNCH = OT(oc["punch_at"]) if has_o and oc.get("punch_at") is not None else None

    # ---------------- media
    vdir = os.path.join(promo, "assets", "video")
    for name in ["body"] + (["montage"] if has_m else []) + (["outro"] if has_o else []):
        link_or_copy(prj.w(f"{name}.mp4"), os.path.join(vdir, f"{name}.mp4"))
    if HOLD_AT is not None:
        os.makedirs(img_dir, exist_ok=True)
        media.run(["ffmpeg", "-y", "-ss", f"{TC:.3f}", "-i", prj.w("body.mp4"), "-frames:v", "1", "-q:v", "2",
             os.path.join(img_dir, "freeze.jpg")])
        if hold.get("image"):
            link_or_copy(prj.p(hold["image"]), os.path.join(img_dir, "hold-" + os.path.basename(hold["image"])))

    # ---------------- fonts (Noto Sans SC + STIX Two Text, subset to what this video uses)
    text = all_strings(c) + "".join(chr(i) for i in range(32, 127)) + "「」，。：？！—·×★→↓“”"
    fdir = os.path.join(promo, "assets", "fonts")
    faces = font_faces(fdir, None if (a.no_fonts and os.path.isdir(fdir)) else text)

    DATA = dict(T_HOLD=T_HOLD, HOLD=HOLD, H=H, M=M, TZ=TZ, O=O, E=E, TOTAL=TOTAL, cues=cues, mlab=mlab,
                CARDS=CARDS, CHIPS=CHIPS, CHIP_END=CHIP_END, SPLITS=SPLITS, PUNCH=PUNCH,
                OUTRO_PUNCH=OUTRO_PUNCH, CW=g["CW"],
                SPLIT=g["split_inset"], SPLIT_X=g["split_x"], SPLIT_Y=g["split_y"],
                SCR_IN=g["scr_in"], SCR_Y=g["scr_y"], SCR_DRIFT=g["scr_drift"],
                FLY=hold.get("fly_from", [380, -150]), HAS_M=has_m, HAS_O=has_o, HAS_END=bool(endc),
                HAS_HOLD=HOLD_AT is not None, INK=INK)
    # progress bar + chapter labels on a scrim, and the cue style: shared HyperFrames snippets
    prog = overlays.hf_progress(CHAP, H, TOTAL, geo=g, font_family="CJK", track_index=8)
    cue_css = overlays.hf_cue_css(g, font_family="CJK", highlight=HL)

    html = render_html(g, DATA, faces, c, D, BR, MR, Mdur, Odur, END, hold, mcfg, oc, endc,
                       dict(ACC=ACC, HL=HL, INK=INK, GROUND=GROUND, GOLD=GOLD), prog, cue_css)
    open(os.path.join(promo, "index.html"), "w", encoding="utf-8").write(html)
    json.dump({"orientation": ori, "total": TOTAL, "body_end": M + TZ, "montage": [M, O] if has_m else None,
               "outro": [O, E] if has_o else None, "chapters": [[r(s), r(e), lab] for s, e, lab in CHAP]},
              open(os.path.join(promo, "timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{promo}/index.html  {W}x{Hc}  total {TOTAL:.1f}s · body→{M:.1f} · montage→{O:.1f} · outro→{E:.1f}")
    print("Next: cd into it, `npx hyperframes check`, snapshot mid-transition frames, then scripts/export.sh")


def render_html(g, DATA, faces, c, D, BR, MR, Mdur, Odur, END, hold, mcfg, oc, endc, col, prog, cue_css):
    W, Hc = g["W"], g["H"]
    H, M, TZ, O, E, TOTAL = DATA["H"], DATA["M"], DATA["TZ"], DATA["O"], DATA["E"], DATA["TOTAL"]
    T_HOLD, HOLD = DATA["T_HOLD"], DATA["HOLD"]
    TC = (T_HOLD - H) * BR
    B = D["body"] / BR + HOLD
    ff = lambda fam, key, extra: f'@font-face {{ font-family: "{fam}"; src: url("{faces[key][0]}") format("{faces[key][1]}"); {extra} }}'
    fonts_css = "\n".join([ff("CJK", "cjk-400", "font-weight: 400;"), ff("CJK", "cjk-700", "font-weight: 700;"),
                           ff("Serif", "serif", "font-style: normal;"), ff("Serif", "serif-italic", "font-style: italic;")])
    ACC, HL, INK, GROUND, GOLD = col["ACC"], col["HL"], col["INK"], col["GROUND"], col["GOLD"]
    CW, CHH = g["CW"], g["CHH"]

    if DATA["HAS_HOLD"]:
        body_html = (
            f'<video id="body" class="full" src="assets/video/body.mp4" playsinline data-has-audio="true" data-start="{r(H)}" data-duration="{r(TC / BR)}" data-playback-rate="{BR}" data-track-index="2" data-volume="1"></video>\n'
            f'    <img id="freeze" class="full clip" src="assets/img/freeze.jpg" alt="" data-start="{r(T_HOLD)}" data-duration="{r(HOLD)}" data-track-index="2" />\n'
            f'    <video id="body2" class="full" src="assets/video/body.mp4" playsinline data-has-audio="true" data-start="{r(T_HOLD + HOLD)}" data-duration="{r((D["body"] - TC) / BR)}" data-media-start="{r(TC)}" data-playback-rate="{BR}" data-track-index="2" data-volume="1"></video>')
        himg = "assets/img/hold-" + os.path.basename(hold["image"]) if hold.get("image") else ""
        pz_html = (f'<div id="pz" class="clip full" data-start="{r(T_HOLD)}" data-duration="{r(HOLD)}" data-track-index="6">\n'
                   f'    <div id="pz-dim" class="full"></div>\n'
                   f'    <div id="pz-box"><div id="pz-label">{hold.get("label", "")}</div>'
                   + (f'<img id="pz-img" src="{himg}" alt="" />' if himg else "") + '</div>\n  </div>')
    else:
        body_html = f'<video id="body" class="full" src="assets/video/body.mp4" playsinline data-has-audio="true" data-start="{r(H)}" data-duration="{r(B)}" data-playback-rate="{BR}" data-track-index="2" data-volume="1"></video>'
        pz_html = ""

    cards_html = "".join(f'<div class="card" id="{cd["id"]}"><div class="scroller" id="{cd["id"]}-s"><img src="{cd["img"]}" alt="" /><div id="{cd["id"]}-hls"></div></div></div>' for cd in DATA["CARDS"])
    chips_html = "".join(f'<div class="chip{" star" if st else ""}" id="chip{i}">{t}</div>' for i, (_, t, st) in enumerate(DATA["CHIPS"]))

    m_html = ""
    if DATA["HAS_M"]:
        m_html = f'''<div id="plate-grid" class="full clip" data-start="{r(M)}" data-duration="{r(Mdur + TZ)}" data-track-index="1"></div>
  <div id="screen" class="wrap"><div id="screen-frame">
    <video id="montage" src="assets/video/montage.mp4" playsinline data-has-audio="true" data-start="{r(M)}" data-duration="{r(Mdur + TZ)}" data-playback-rate="{MR}" data-track-index="3" data-volume="1"></video>
  </div></div>
  <div id="mlabel" class="clip" data-start="{r(M + TZ)}" data-duration="{r(Mdur)}" data-track-index="4">{"".join(f'<div class="ml" id="ml{m["n"]}"><b>{m["n"]:02d}</b>{m["t"]}</div>' for m in DATA["mlab"])}</div>'''
        if mcfg.get("tag"):
            m_html += f'\n  <div id="mtag" class="clip" data-start="{r(M + TZ)}" data-duration="{r(Mdur)}" data-track-index="4">{mcfg["tag"]}</div>'
        if mcfg.get("badge"):
            m_html += f'\n  <div id="mbadge" class="clip" data-start="{r(M + TZ)}" data-duration="{r(Mdur)}" data-track-index="4">{mcfg["badge"]}</div>'
        if mcfg.get("title"):
            m_html += (f'\n  <div id="mtitle" class="clip" data-start="{r(M + TZ)}" data-duration="2.4" data-track-index="5"><span>{mcfg["title"]}</span>'
                       + (f'<small>{mcfg["title_sub"]}</small>' if mcfg.get("title_sub") else "") + '</div>')

    o_html = ""
    if DATA["HAS_O"]:
        o_html = f'<div id="ow" class="wrap"><video id="outro" class="full" src="assets/video/outro.mp4" playsinline data-has-audio="true" data-start="{r(O)}" data-duration="{r(Odur)}" data-playback-rate="{BR}" data-track-index="2" data-volume="1"></video></div>'
        if oc.get("stamp"):
            o_html += f'\n  <div id="stamp" class="clip" data-start="{r(O)}" data-duration="{r(Odur)}" data-track-index="4">{oc["stamp"]}</div>'
    end_html = ""
    if DATA["HAS_END"]:
        end_html = f'''<div id="endcard" class="full clip" data-start="{r(E)}" data-duration="{END}" data-track-index="5">
    <div id="end-k">{endc.get("kicker", "")}</div>
    <div id="end-m">{endc.get("main", "")}</div>
    <div id="end-s">{endc.get("sub", "")}</div>
  </div>'''

    return f'''<!doctype html>
<html lang="{c.get("language", "zh")}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={W}, height={Hc}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
{fonts_css}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {W}px; height: {Hc}px; overflow: hidden; background: {GROUND}; }}
#root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {GROUND}; font-family: "CJK", sans-serif; }}
.full {{ position: absolute; inset: 0; width: {W}px; height: {Hc}px; }}
video.full, img.full {{ object-fit: cover; object-position: {g["face_pos"]}; }}
#plate {{ background: radial-gradient(ellipse 70% 60% at 50% 42%, #16203d 0%, {GROUND} 62%, #070a14 100%); }}
#plate-grid {{ background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px); background-size: 64px 64px; }}
.wrap {{ position: absolute; inset: 0; width: {W}px; height: {Hc}px; transform-origin: 50% 40%; }}
#face {{ transform-origin: 0 0; }}
#screen {{ transform-origin: 50% 45%; opacity: 0; }}
#screen-frame {{ position: absolute; left: {g["scr_l"]}px; top: {g["scr_t"]}px; width: {g["scr_w"]}px; height: {g["scr_h"]}px; border-radius: 26px; overflow: hidden;
  box-shadow: 0 40px 120px rgba(0,0,0,.6), 0 0 0 2px rgba(255,255,255,.12); }}
#montage {{ position: absolute; left: 0; top: 0; width: {g["scr_w"]}px; height: {g["scr_h"]}px; object-fit: cover; }}
#ow {{ opacity: 0; }}
.card {{ position: absolute; left: {g["card_l"]}px; top: {g["card_t"]}px; width: {CW}px; height: {CHH}px; border-radius: 22px; overflow: hidden; background: #fff;
  box-shadow: 0 30px 80px rgba(0,0,0,.45), 0 0 0 1px rgba(0,0,0,.08); opacity: 0; }}
.card img {{ position: absolute; left: 0; top: 0; width: {CW}px; display: block; }}
.hl {{ position: absolute; left: 14px; height: 0; background: rgba(255, 214, 10, .45); mix-blend-mode: multiply; border-radius: 6px; transform-origin: 0 50%; }}
.box {{ position: absolute; left: 10px; width: {CW - 20}px; border: 5px solid {ACC}; border-radius: 16px; transform-origin: 50% 50%; opacity: 0; }}
#chips {{ position: absolute; left: {g["chips_l"]}px; top: {g["chips_t"]}px; width: {g["chips_w"]}px; display: flex; gap: 9px; flex-wrap: nowrap; }}
.chip {{ font: 700 23px "CJK"; color: {INK}; padding: 7px 14px; border-radius: 999px; background: rgba(16,20,34,.82);
  border: 2px solid rgba(255,255,255,.22); opacity: 0; white-space: nowrap; }}
.chip.star {{ color: #111; background: {GOLD}; border-color: {GOLD}; }}
#subs {{ position: absolute; left: 0; right: 0; top: 0; height: {Hc}px; pointer-events: none; }}
{cue_css}{prog["css"]}#mlabel {{ position: absolute; left: {g["mlabel_l"]}px; top: {g["mlabel_t"]}px; font: 700 30px "CJK"; color: {INK}; }}
.ml {{ position: absolute; left: 0; top: 0; white-space: nowrap; opacity: 0; }}
.ml b {{ font: italic 34px "Serif"; color: {GOLD}; margin-right: 14px; }}
#pz-dim {{ background: rgba(5,8,16,.72); opacity: 0; }}
#pz-box {{ position: absolute; left: {g["pz_l"]}px; top: {g["pz_t"]}px; width: {g["pz_w"]}px; padding: 26px 30px 30px; border-radius: 26px; background: #EFEFEC;
  box-shadow: 0 40px 120px rgba(0,0,0,.6), 0 0 0 6px {ACC}; transform-origin: 85% 10%; opacity: 0; }}
#pz-label {{ position: absolute; left: 0; top: -70px; font: 700 40px "CJK"; color: {GOLD}; opacity: 0; }}
#pz-img {{ display: block; width: {g["pz_w"] - 60}px; }}
#mbadge {{ position: absolute; left: {g["mbadge_l"]}px; top: {g["mbadge_t"]}px; padding: 4px 16px; border-radius: 10px; background: {ACC}; color: #fff; font: 700 28px "CJK"; opacity: 0; }}
#mtitle {{ position: absolute; left: 0; right: 0; top: {g["mtitle_t"]}px; display: flex; flex-direction: column; align-items: center; gap: 18px; opacity: 0; }}
#mtitle span {{ font: 700 {g["mtitle_fs"]}px "CJK"; color: #fff; padding: 18px 56px; border-radius: 24px; background: rgba(11,16,32,.82); border: 2px solid {GOLD}b3; text-shadow: 0 6px 30px rgba(0,0,0,.6); }}
#mtitle small {{ font: 400 34px "CJK"; color: {GOLD}; text-shadow: 0 2px 10px rgba(0,0,0,.9); }}
#mtag {{ position: absolute; {g["mtag_css"]} font: 400 24px "CJK"; color: rgba(236,238,242,.75); padding: 8px 18px;
  border: 1.5px solid rgba(236,238,242,.3); border-radius: 999px; opacity: 0; }}
#stamp {{ position: absolute; left: {g["stamp_l"]}px; top: {g["stamp_t"]}px; padding: 10px 30px; border: 7px solid {ACC}; color: {ACC}; font: 700 96px "CJK";
  border-radius: 18px; opacity: 0; background: rgba(255,255,255,.12); }}
#endcard {{ display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 0 60px; }}
#end-k {{ font: italic 46px "Serif"; color: {GOLD}; opacity: 0; }}
#end-m {{ margin-top: 26px; font: 700 {g["end_fs"]}px "CJK"; color: #fff; opacity: 0; }}
#end-s {{ margin-top: 30px; font: 400 34px "CJK"; color: rgba(236,238,242,.75); opacity: 0; }}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="{W}" data-height="{Hc}" data-duration="{TOTAL}">
  <div id="plate" class="full clip" data-start="0" data-duration="{TOTAL}" data-track-index="0"></div>

  <!-- body: talking head (split-screen + punch-ins). body + freeze + body2 share track 2 back to back -->
  <div id="face" class="wrap"><div id="face-zoom" class="wrap">
    {body_html}
  </div></div>
  <div id="cards" class="clip full" data-start="{r(H)}" data-duration="{r(B)}" data-track-index="4" style="pointer-events:none">
    {cards_html}
    <div id="chips">{chips_html}</div>
  </div>
  {pz_html}

  <!-- montage: highlights in a framed screen; own track (3) because it overlaps body2 during the zoom-through -->
  {m_html}

  <!-- outro + end card -->
  {o_html}
  {end_html}

  <div id="subs" class="clip" data-start="0" data-duration="{r(E)}" data-track-index="7"></div>
  {prog["html"]}
</div>
<script>
(function () {{
const D = {json.dumps(DATA, ensure_ascii=False)};
const tl = gsap.timeline({{ paused: true }});
const $ = (s) => document.querySelector(s);

// subtitles
const subs = $("#subs");
D.cues.forEach((c, i) => {{
  const el = document.createElement("div"); el.className = "cue"; el.id = "cue" + i;
  el.innerHTML = c.t; subs.appendChild(el);   // escaped, 【term】 -> <em> (vstudio.overlays.cue_html)
  tl.fromTo(el, {{ opacity: 0, y: 14 }}, {{ opacity: 1, y: 0, duration: 0.18, ease: "power2.out" }}, c.s);
  tl.to(el, {{ opacity: 0, duration: 0.12, ease: "none" }}, Math.max(c.s + 0.25, c.e - 0.12));
}});

// talking head: split-screen moves (clip + slide) and punch-ins
const FULL = "inset(0px 0px 0px 0px round 0px)";
tl.set("#face", {{ clipPath: FULL, x: 0, y: 0 }}, 0);
D.SPLITS.forEach(([s, e], i) => {{
  const prevEnd = i ? D.SPLITS[i - 1][1] : -1;
  if (s - prevEnd > 0.2) tl.to("#face", {{ clipPath: D.SPLIT, x: D.SPLIT_X, y: D.SPLIT_Y, duration: 0.7, ease: "power3.inOut" }}, s - 0.15);
  const next = D.SPLITS[i + 1];
  if (!next || next[0] - e > 0.2) tl.to("#face", {{ clipPath: FULL, x: 0, y: 0, duration: 0.7, ease: "power3.inOut" }}, e - 0.3);
}});
D.PUNCH.forEach(([s, e]) => {{
  tl.to("#face-zoom", {{ scale: 1.14, duration: 0.45, ease: "power2.out" }}, s);
  tl.to("#face-zoom", {{ scale: 1.0, duration: 0.5, ease: "power2.inOut" }}, e);
}});

// cards: 3D slide-in, scroll, highlights, box
D.CARDS.forEach((c) => {{
  const k = D.CW / c.w;
  const card = $("#" + c.id), scr = $("#" + c.id + "-s"), hls = $("#" + c.id + "-hls");
  tl.fromTo(card, {{ opacity: 0, x: 140, rotationY: -28, transformPerspective: 1400 }},
                  {{ opacity: 1, x: 0, rotationY: -6, duration: 0.75, ease: "power3.out" }}, c.s);
  tl.to(card, {{ rotationY: -2, y: -8, duration: Math.max(1, c.e - c.s - 1.2), ease: "sine.inOut" }}, c.s + 0.75);
  tl.to(card, {{ opacity: 0, x: 80, rotationY: 18, duration: 0.45, ease: "power2.in" }}, c.e - 0.45);
  tl.set(scr, {{ y: -c.scroll[0][1] * k }}, 0);
  c.scroll.slice(1).forEach(([t, y], j) => {{
    const t0 = c.scroll[j][0];
    tl.to(scr, {{ y: -y * k, duration: Math.min(1.2, Math.max(0.6, t - t0)), ease: "power2.inOut" }}, t - 0.2);
  }});
  (c.hl || []).forEach(([t, y0, y1, frac], j) => {{
    const h = document.createElement("div"); h.className = "hl"; h.id = c.id + "-hl" + j;
    h.style.top = (y0 * k - 6) + "px"; h.style.height = ((y1 - y0) * k + 12) + "px"; h.style.width = ((D.CW - 28) * frac) + "px";
    hls.appendChild(h);
    tl.fromTo(h, {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.5, ease: "power2.out" }}, t);
  }});
  if (c.box) {{
    const [t, y0, y1] = c.box, b = document.createElement("div"); b.className = "box"; b.id = c.id + "-box";
    b.style.top = (y0 * k - 10) + "px"; b.style.height = ((y1 - y0) * k + 20) + "px"; hls.appendChild(b);
    tl.fromTo(b, {{ opacity: 0, scale: 1.15 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)" }}, t);
  }}
}});
D.CHIPS.forEach(([t], i) => {{
  tl.fromTo("#chip" + i, {{ opacity: 0, y: 16, scale: 0.9 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.3, ease: "back.out(1.7)" }}, t);
}});
if (D.CHIPS.length) tl.to("#chips", {{ opacity: 0, duration: 0.35 }}, D.CHIP_END - 0.4);

// prompt hold: dim, fly the prompt out of the screenshot card, hold, fly back
if (D.HAS_HOLD) {{
  tl.fromTo("#pz-dim", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, D.T_HOLD);
  tl.fromTo("#pz-box", {{ opacity: 0, scale: 0.3, x: D.FLY[0], y: D.FLY[1] }}, {{ opacity: 1, scale: 1, x: 0, y: 0, duration: 0.45, ease: "power3.out" }}, D.T_HOLD);
  tl.fromTo("#pz-label", {{ opacity: 0, y: 10 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, D.T_HOLD + 0.35);
  tl.to("#pz-box", {{ opacity: 0, scale: 0.3, x: D.FLY[0], y: D.FLY[1], duration: 0.35, ease: "power2.in" }}, D.T_HOLD + D.HOLD - 0.38);
  tl.to("#pz-dim", {{ opacity: 0, duration: 0.3 }}, D.T_HOLD + D.HOLD - 0.3);
}}
if (D.HAS_M) {{
  // body -> montage: zoom through into the framed screen (body2 is still playing underneath)
  tl.to("#face", {{ scale: 1.35, opacity: 0, filter: "blur(10px)", transformOrigin: "50% 45%", duration: 0.7, ease: "power3.in" }}, D.M - 0.1);
  tl.fromTo("#screen", {{ scale: 1.25, opacity: 0 }}, {{ scale: D.SCR_IN, y: D.SCR_Y, opacity: 1, duration: 0.9, ease: "power3.out" }}, D.M + 0.1);
  tl.to("#screen", {{ scale: D.SCR_DRIFT, duration: Math.max(0.5, D.O - D.M - 1.5), ease: "sine.inOut" }}, D.M + 1.0);
  D.mlab.forEach((m) => {{
    tl.fromTo("#ml" + m.n, {{ opacity: 0, x: -24 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "power2.out" }}, m.s + 0.1);
    tl.to("#ml" + m.n, {{ opacity: 0, duration: 0.2 }}, m.e - 0.2);
  }});
  if ($("#mtag")) tl.fromTo("#mtag", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5 }}, D.M + 0.8);
  if ($("#mbadge")) tl.fromTo("#mbadge", {{ opacity: 0, x: -20 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "power2.out" }}, D.M + 0.6);
  if ($("#mtitle")) {{
    tl.fromTo("#mtitle", {{ opacity: 0, scale: 0.92 }}, {{ opacity: 1, scale: 1, duration: 0.45, ease: "back.out(1.6)" }}, D.M + D.TZ + 0.05);
    tl.to("#mtitle", {{ opacity: 0, y: -20, duration: 0.4, ease: "power2.in" }}, D.M + D.TZ + 1.95);
  }}
  // montage -> outro: frame shrinks away (montage clip runs TZ past O so it is alive while it leaves)
  tl.to("#screen", {{ scale: 0.6, opacity: 0, duration: 0.6, ease: "power3.in" }}, D.O - 0.45);
}}
if (D.HAS_O) {{
  tl.fromTo("#ow", {{ scale: 1.15, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: 0.6, ease: "power3.out" }}, D.O);
  if (D.OUTRO_PUNCH !== null) {{
    tl.to("#ow", {{ scale: 1.16, duration: 0.5, ease: "power2.out", transformOrigin: "50% 38%" }}, D.OUTRO_PUNCH);
    if ($("#stamp")) tl.fromTo("#stamp", {{ opacity: 0, scale: 2.2, rotation: -12 }}, {{ opacity: 1, scale: 1, rotation: -12, duration: 0.3, ease: "back.out(2)" }}, D.OUTRO_PUNCH + 0.9);
  }}
}}
if (D.HAS_END) {{
  tl.fromTo("#end-k", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, D.E + 0.15);
  tl.fromTo("#end-m", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.55, ease: "power2.out" }}, D.E + 0.45);
  tl.fromTo("#end-s", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5 }}, D.E + 1.0);
}}

// progress bar + chapters on a scrim (vstudio.overlays.hf_progress)
{prog["js"]}
window.__timelines = window.__timelines || {{}};
window.__timelines["main"] = tl;
}})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
