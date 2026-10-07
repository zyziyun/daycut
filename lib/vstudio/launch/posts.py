"""Post copy for a launch kit: per platform, in every language, through the shared post-copy engine.

    from vstudio.launch import posts as CP
    res = CP.make_all(cfg, kit, "kit/copy")     # -> {"launch": {platform: {lang: text}}, "clips": {...}, "warnings": [...]}

The launch post is the config's ``post`` block (the post.json shape vstudio.publish understands:
``{en: {title, hook, body, tags, links, by_platform: {x: {hook, body}}}, zh: {...}}``; ``by_platform`` = a
hand-written version for one platform, e.g. a tighter X post); each feature clip uses ``features[].post`` or, when that
is missing, its caption as the hook plus the product line. ``vstudio.publish.platform_post`` lays each one out per
platform (title fields, hashtag caps, 小红书 / B站 conventions, X weighted 280) and ``vstudio.platform.check_text``
reports what is still over a limit. Platforms are listed international first, then Chinese
(``vstudio.platform.ordered``). Without a ``post`` block the copy is written by the routed model
(``vstudio.publish.generate_copy``, llm task ``copy``); no model routed = a visible error, never invented text.
"""
import json
import os

from vstudio import platform as PF
from vstudio import publish as PB

from . import config as C

PH_TAGLINE_MAX, PH_DESC_MAX = 60, 260
CLIP_PLATFORMS = ("x", "linkedin", "youtube-shorts", "tiktok", "instagram", "xiaohongshu", "douyin", "bilibili")


def ordered(platforms):
    return PF.ordered(list(platforms))


def _post_for(block, use_persona_tags=False):
    post = json.loads(json.dumps(block))
    post.setdefault("use_persona_tags", use_persona_tags)
    for lang in C.LANGS:
        b = post.get(lang)
        if isinstance(b, dict) and isinstance(b.get("links"), dict):
            b["links"] = list(b["links"].items())
    return post


def clip_post(cfg, feat):
    """A feature clip's post.json: features[].post, else the caption as hook + the product one-liner + site."""
    if feat.get("post"):
        return _post_for(feat["post"])
    p = cfg["product"]
    base = cfg.get("post") or {}
    out = {}
    for lang in cfg["languages"]:
        b = base.get(lang) or {}
        name = p["name"] + (f"（{p['name_zh']}）" if lang == "zh" and p.get("name_zh") else "")
        cap = C.plain(C.text(feat.get("caption"), lang))
        out[lang] = dict(title=(f"{name}: {cap}" if lang == "en" else f"{name}｜{cap}"), hook=cap,
                         body=[f"{name}: {C.text(p.get('one_liner'), lang)}" if lang == "en" else
                               f"{name}：{C.text(p.get('one_liner'), lang)}"],
                         tags=list(b.get("tags") or []), links=b.get("links"))
    return _post_for(out)


def _llm_post(cfg, platform, lang, source):
    r = PB.generate_copy(platform, source, lang=lang)
    if not r:
        raise RuntimeError("no post block in the config and no model routed for the llm task 'copy': write "
                           "post: {en: {...}, zh: {...}} in launch.config.yaml or route a model (python -m vstudio.llm)")
    return r["text"]


def source_text(cfg):
    p = cfg["product"]
    lines = [f"{p['name']}: {C.text(p.get('one_liner'), 'en')}", C.text(p.get("description"), "en"),
             p.get("site", "")]
    lines += [f"- {C.plain(C.text(f.get('caption'), 'en'))}" for f in cfg["features"]]
    return "\n".join(x for x in lines if x)


def render_post(post, platform, lang):
    warns = []
    prof = PF.profile(platform, use_persona=False)
    if not PF.link_policy(prof).get("clickable"):        # a dead link in the text: point to the profile instead
        post = json.loads(json.dumps(post))
        for k in [None] + list(C.LANGS):
            b = post if k is None else post.get(k)
            if isinstance(b, dict) and b.get("links"):
                b["links"] = []
    base = platform.split(":")[0]
    b = post.get(lang) if isinstance(post.get(lang), dict) else None
    if b and isinstance((b.get("by_platform") or {}).get(base), dict):
        post = json.loads(json.dumps(post))           # a hand-written version for this platform wins
        post[lang].update(post[lang].pop("by_platform")[base])
        b = post[lang]
    if b and b.get("title") and b.get("hook") and not PB.check_title(b["title"], base)[0] \
            and PB.check_title(b["hook"], base)[0]:
        post = json.loads(json.dumps(post))           # "Name: caption" too long here: the caption alone
        post[lang]["title"] = post[lang]["hook"]
    text, c = PB.platform_post(post, platform, lang=lang, warn=warns.append)
    warns += PF.check_text(prof, title=None if platform.split(":")[0] in PB.NO_TITLE else c.get("title"), body=text,
                           tags=c.get("tags"))
    return text, c.get("title"), sorted(set(warns))


def producthunt(cfg):
    ph = cfg.get("producthunt") or {}
    p = cfg["product"]
    tag = C.text(ph.get("tagline"), "en") or C.text(p.get("one_liner"), "en")
    desc = C.text(ph.get("description"), "en") or C.text(p.get("description"), "en")
    warns = []
    if len(tag) > PH_TAGLINE_MAX:
        warns.append(f"Product Hunt tagline {len(tag)}/{PH_TAGLINE_MAX}")
    if len(desc) > PH_DESC_MAX:
        warns.append(f"Product Hunt description {len(desc)}/{PH_DESC_MAX} (the preview shows the first 260)")
    return dict(name=p["name"], tagline=tag, description=desc, topics=ph.get("topics") or [],
                first_comment=C.text(ph.get("first_comment"), "en"), warnings=warns)


def make_all(cfg, out_dir, kit=None):
    """Write copy/<platform>.<lang>.md (launch post), copy/clips/<feature>/<platform>.<lang>.md, COPY.md (one page
    to read and paste from) and copy.json. ``kit``: {video key: path} to name the media next to each post."""
    os.makedirs(out_dir, exist_ok=True)
    plats = ordered(cfg["platforms"])
    langs = cfg["languages"]
    res = dict(launch={}, clips={}, warnings=[], producthunt=producthunt(cfg))
    post = _post_for(cfg["post"]) if cfg.get("post") else None
    for pl in plats:
        for lang in langs:
            if post:
                text, title, w = render_post(post, pl, lang)
            else:
                text, title, w = _llm_post(cfg, pl, lang, source_text(cfg)), None, []
            res["launch"].setdefault(pl, {})[lang] = dict(text=text, title=title, warnings=w)
            res["warnings"] += [f"launch/{pl}/{lang}: {x}" for x in w]
            with open(os.path.join(out_dir, f"{pl.replace(':', '-')}.{lang}.md"), "w", encoding="utf-8") as f:
                f.write(text)
    clip_pl = [pl for pl in plats if pl.split(":")[0] in CLIP_PLATFORMS]
    for fid in C.cut_features(cfg, "clips"):
        feat = C.feature(cfg, fid)
        cp = clip_post(cfg, feat)
        d = os.path.join(out_dir, "clips", fid)
        os.makedirs(d, exist_ok=True)
        for pl in clip_pl:
            for lang in langs:
                text, title, w = render_post(cp, pl, lang)
                res["clips"].setdefault(fid, {}).setdefault(pl, {})[lang] = dict(text=text, title=title, warnings=w)
                res["warnings"] += [f"clips/{fid}/{pl}/{lang}: {x}" for x in w]
                with open(os.path.join(d, f"{pl.replace(':', '-')}.{lang}.md"), "w", encoding="utf-8") as f:
                    f.write(text)
    res["warnings"] += res["producthunt"]["warnings"]
    with open(os.path.join(out_dir, "copy.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "COPY.md"), "w", encoding="utf-8") as f:
        f.write(page(cfg, res, kit or {}))
    return res


def _lang_note(pl, lang):
    intl = pl.split(":")[0] in PF.INTL_PLATFORMS
    return "recommended" if (lang == "en") == intl else "alternative"


def page(cfg, res, kit):
    p = cfg["product"]
    L = [f"# Post copy: {p['name']} {p.get('version', '')}".rstrip(), "",
         "Drafts only. Nothing here has been posted. Read each block, edit it, and post it yourself.", ""]
    ph = res["producthunt"]
    L += ["## Product Hunt", "", f"- **Name:** {ph['name']}", f"- **Tagline ({len(ph['tagline'])}/60):** {ph['tagline']}",
          f"- **Description ({len(ph['description'])}/260):** {ph['description']}"]
    if ph["topics"]:
        L.append(f"- **Topics:** {', '.join(ph['topics'])}")
    if kit.get("gallery"):
        L.append(f"- **Gallery:** {', '.join(os.path.basename(x) for x in kit['gallery'])}")
    if kit.get("demo"):
        L.append(f"- **Video:** {os.path.basename(kit['demo'])} (upload to YouTube first; PH takes a YouTube link)")
    if ph["first_comment"]:
        L += ["", "**First comment:**", "", "> " + ph["first_comment"].replace("\n", "\n> ")]
    L += ["", "## Launch post (the demo video)", ""]
    for pl, by in res["launch"].items():
        media = (kit.get("demo_for") or {}).get(pl)
        L.append(f"### {PF.profile(pl, use_persona=False).label}" + (f" · `{os.path.basename(media)}`" if media else ""))
        for lang, d in by.items():
            L += ["", f"**{lang.upper()}** ({_lang_note(pl, lang)})"
                  + (f" · title: {d['title']}" if d.get("title") else ""), "", "```", d["text"].rstrip(), "```"]
            L += [f"- check: {w}" for w in d["warnings"]]
        L.append("")
    L += ["## Feature clips", ""]
    for fid, by_pl in res["clips"].items():
        L.append(f"### {fid}")
        for pl, by in by_pl.items():
            media = (kit.get("clip_for") or {}).get((fid, pl))
            for lang, d in by.items():
                if _lang_note(pl, lang) != "recommended":
                    continue
                L += ["", f"**{PF.profile(pl, use_persona=False).label} · {lang.upper()}**" + (f" · `{os.path.basename(media)}`" if media else ""),
                      "", "```", d["text"].rstrip(), "```"]
                L += [f"- check: {w}" for w in d["warnings"]]
        L.append("")
    L.append("Every platform also has the other language in copy/ (`<platform>.<lang>.md`).")
    return "\n".join(L) + "\n"
