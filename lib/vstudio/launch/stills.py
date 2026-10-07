"""Launch stills: Product Hunt gallery (1270x760), an Open Graph / social card (1200x630), one per language.

    from vstudio.launch import stills as ST
    ST.make_all(cfg, shots, "kit/stills")     # -> [paths]: ph-gallery-1-hero.png, ph-gallery-2-<feature>.png ..., og-1200x630.png

Each still is HTML in the brand theme (paper, ink, one accent, the brand fonts) around a real product shot (the
capture's still), rendered at 2x by headless Chrome (vstudio.render.html_to_png) and resampled to the exact size
the platform asks for, so text stays crisp. Gallery 1 is the hero: logo, one-liner, a short description and up to
three facts (``gallery.facts``: only numbers the creator can stand behind).
"""
import html
import os

from PIL import Image

from vstudio import render as R
from vstudio import theme as TH

from . import brand as B
from . import config as C

PH = (1270, 760)
OG = (1200, 630)


def _e(s):
    return html.escape(s or "", quote=True)


def emph(s):
    """'Review only what 【gets flagged】' -> escaped HTML with the term in the accent colour."""
    out, i = "", 0
    s = s or ""
    while i < len(s):
        j = s.find("【", i)
        if j < 0:
            out += _e(s[i:])
            break
        k = s.find("】", j)
        k = len(s) if k < 0 else k
        out += _e(s[i:j]) + f"<span class='ac'>{_e(s[j + 1:k])}</span>"
        i = k + 1
    return out


def _page(cfg, lang, size, body, extra_css, assets_dir, text):
    T = B.theme(cfg)
    faces = B.stage_fonts(cfg, os.path.join(assets_dir, "fonts"), text, [lang])
    W, H = size
    disp, txt = B.families(faces, lang, "display"), B.families(faces, lang, "text")
    return f"""<!doctype html><html lang="{'zh-CN' if lang == 'zh' else 'en'}"><head><meta charset="utf-8"><style>
{TH.css_vars(T)}
{B.font_css(faces, url_prefix="assets/fonts/")}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{background:var(--paper);color:var(--ink);font-family:{txt};position:relative}}
.k{{position:absolute;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-size:16px}}
h1{{position:absolute;font-family:{disp};font-weight:560;letter-spacing:-.015em;line-height:1.1}}
.ac{{color:var(--accent)}}
.shot{{position:absolute;border-radius:14px;overflow:hidden;background:var(--card);
 box-shadow:0 18px 50px rgba(30,27,24,.16),0 0 0 1px rgba(30,27,24,.08)}}
.shot img{{width:100%;display:block}}
.note{{position:absolute;font-size:14px;color:var(--ink2)}}
{extra_css}
</style></head><body>{body}</body></html>"""


def _render(page_html, out, size, workdir):
    os.makedirs(workdir, exist_ok=True)
    src = os.path.join(workdir, os.path.splitext(os.path.basename(out))[0] + ".html")
    with open(src, "w", encoding="utf-8") as f:
        f.write(page_html)
    big = out[:-4] + ".2x.png"
    R.html_to_png(src, big, size=size, scale=2, wait=1500, use_persona=False, fonts=False)
    with Image.open(big) as im:
        im.convert("RGB").resize(size, Image.LANCZOS).save(out, optimize=True)
    os.remove(big)
    return out


def _img(path, workdir):
    """Copy a shot still next to the HTML (Chrome reads file:// relative to the page)."""
    import shutil
    d = os.path.join(workdir, "assets", "img")
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.basename(path))
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(path):
        shutil.copy2(path, dst)
    return "assets/img/" + os.path.basename(path)


def hero(cfg, lang, out, workdir, size=PH):
    p, g = cfg["product"], cfg.get("gallery") or {}
    b = cfg.get("brand") or {}
    logo = _img(b["logo"], workdir) if b.get("logo") else None
    mark = _img(b["mark"], workdir) if b.get("mark") else None
    head = C.text(g.get("headline"), lang) or C.text(p.get("one_liner"), lang)
    sub = C.text(g.get("sub"), lang) or C.text(p.get("description"), lang)
    facts = g.get("facts") or []
    foot = C.text(g.get("foot"), lang)
    W, H = size
    body = f'<img class="wm" src="{logo}">' if logo else f'<div class="wmt">{_e(p["name"])}</div>'
    body += "<div class='col'>"
    body += f"<h1 class='hh'>{emph(head)}</h1>"
    body += f"<div class='sub'>{_e(sub)}</div>" if sub else ""
    if facts:
        body += "<div class='stats'>" + "".join(
            f"<div class='s'><b>{_e(C.text(f.get('value'), lang))}</b><i>{_e(C.text(f.get('label'), lang))}</i></div>"
            for f in facts[:3]) + "</div>"
    body += "</div>"
    body += f'<img class="ic" src="{mark}">' if mark and not logo else ""
    body += f"<div class='foot'>{_e(foot)}</div>" if foot else ""
    css = f""".col{{position:absolute;left:80px;right:80px;top:130px;bottom:84px;display:flex;flex-direction:column;
 align-items:flex-start;justify-content:center}}
.wm{{position:absolute;left:80px;top:64px;height:58px}}
.wmt{{position:absolute;left:80px;top:60px;font-size:48px;font-weight:700}}
.ic{{position:absolute;right:80px;top:56px;width:92px;height:92px}}
.hh{{position:static;margin:0;font-size:{56 if W > 1240 else 52}px}}
.sub{{margin-top:22px;max-width:{W - 220}px;font-size:23px;line-height:1.42;color:var(--ink2)}}
.stats{{margin-top:{44 if H > 700 else 30}px;display:flex;gap:24px;align-self:stretch}}
.s{{flex:1;background:var(--card);border-radius:14px;padding:24px 26px;box-shadow:0 0 0 1px rgba(30,27,24,.08)}}
.s b{{display:block;font-size:42px;font-weight:700;letter-spacing:-.02em;color:var(--accent)}}
.s i{{font-style:normal;font-size:18px;color:var(--ink2);line-height:1.35;display:block;margin-top:6px}}
.foot{{position:absolute;left:82px;bottom:42px;font-size:18px;color:var(--ink2)}}"""
    text = "".join([head, sub, foot, p["name"]] + [C.text(f.get(k), lang) for f in facts for k in ("value", "label")])
    return _render(_page(cfg, lang, size, body, css, workdir, text), out, size, workdir)


def feature_still(cfg, shot, feat, lang, out, workdir, size=PH):
    g = cfg.get("gallery") or {}
    W, H = size
    kick = C.text(feat.get("kicker"), lang)
    head = C.text(feat.get("headline"), lang) or C.text(feat.get("caption"), lang)
    if feat.get("still_at") is not None and shot.get("kind") == "video":
        from vstudio import media
        os.makedirs(os.path.join(workdir, "assets", "img"), exist_ok=True)
        grab = os.path.join(workdir, "assets", "img", f"{shot['id']}-{float(feat['still_at']):.2f}.png")
        media.grab_frame(shot["file"], float(feat["still_at"]), grab)
        img = "assets/img/" + os.path.basename(grab)
    else:
        img = _img(shot.get("still") or shot["file"], workdir)
    note = C.text(g.get("note"), lang)
    top = 150 if W > 1240 else 140
    box_w, vis = W - 160, H - top
    disp_h = box_w * float(shot.get("h") or 9) / float(shot.get("w") or 16)
    foc = (shot.get("focus") or [None])[0]
    cy = (foc["y"] + foc.get("h", 0) / 2) if foc else 0.0
    shift = max(0.0, min(disp_h - vis, cy * disp_h - vis / 2)) if disp_h > vis else 0.0
    body = (f"<div class='k' style='left:80px;top:44px'>{_e(kick)}</div>"
            f"<h1 style='left:80px;right:80px;top:72px;font-size:40px'>{emph(head)}</h1>"
            + (f"<div class='note' style='right:84px;top:48px'>{_e(note)}</div>" if note else "")
            + f"<div class='shot' style='left:80px;right:80px;top:{top}px;height:{H - top + 40}px'>"
            f"<img src='{img}' style='margin-top:{-shift:.0f}px'></div>")
    text = kick + head + note
    return _render(_page(cfg, lang, size, body, "", workdir, text), out, size, workdir)


def og(cfg, shots, lang, out, workdir, size=OG):
    p, g = cfg["product"], cfg.get("gallery") or {}
    b = cfg.get("brand") or {}
    logo = _img(b["logo"], workdir) if b.get("logo") else None
    head = C.text(g.get("headline"), lang) or C.text(p.get("one_liner"), lang)
    site = (p.get("site") or "").replace("https://", "").replace("http://", "").rstrip("/")
    ids = C.cut_features(cfg, "gallery")
    shot = None
    if ids:
        feat = C.feature(cfg, ids[0])
        shot = shots.get(feat.get("shot") or feat["id"])
    img = _img(shot.get("still") or shot["file"], workdir) if shot else None
    body = ((f'<img src="{logo}" style="position:absolute;left:72px;top:64px;height:52px">' if logo else
             f"<div style='position:absolute;left:72px;top:60px;font-size:44px;font-weight:700'>{_e(p['name'])}</div>")
            + f"<h1 style='left:72px;top:170px;width:560px;font-size:58px'>{emph(head)}</h1>"
            + (f"<div style='position:absolute;left:74px;bottom:64px;font-size:24px;font-weight:600;color:var(--accent)'>"
               f"{_e(site)}</div>" if site else "")
            + (f"<div class='shot' style='left:680px;top:80px;width:760px;height:475px'><img src='{img}'></div>"
               if img else ""))
    return _render(_page(cfg, lang, size, body, "", workdir, head + site + p["name"]), out, size, workdir)


def make_all(cfg, shots, out_dir, langs=None):
    """Hero + one still per gallery feature + OG, for each language in ``gallery.langs`` (default: the first)."""
    g = cfg.get("gallery") or {}
    langs = langs or g.get("langs") or [cfg["languages"][0]]
    work = os.path.join(out_dir, "_src")
    made = []
    for lang in langs:
        sfx = "" if lang == langs[0] else f"-{lang}"
        made.append(hero(cfg, lang, os.path.join(out_dir, f"ph-gallery-1-hero{sfx}.png"), work))
        for i, fid in enumerate(C.cut_features(cfg, "gallery"), start=2):
            feat = C.feature(cfg, fid)
            shot = shots[feat.get("shot") or fid]
            made.append(feature_still(cfg, shot, feat, lang, os.path.join(out_dir, f"ph-gallery-{i}-{fid}{sfx}.png"),
                                      work))
        made.append(og(cfg, shots, lang, os.path.join(out_dir, f"og-1200x630{sfx}.png"), work))
    return made
