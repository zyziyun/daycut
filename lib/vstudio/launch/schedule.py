"""A posting schedule proposal for a launch kit, and (on request) the posts on the publish calendar.

    from vstudio.launch import schedule as SC
    rows = SC.propose(cfg, kit)                 # [{at, platform, lang, kind demo|clip, feature, video, cover, copy}]
    SC.write(rows, "kit/schedule")              # schedule.json + SCHEDULE.md
    SC.apply(rows, accounts={"x": "my-x"})      # vstudio.project.pubcal posts, state "planned" (never posts)

Launch day: the demo on every platform. Then one feature clip per weekday, on every clip platform. Each platform
gets the render that fits it (canvas and language: international platforms English, Chinese platforms Chinese
when it was rendered) and its own slot time (``schedule.slots``, local time). Platforms are ordered international
first, then Chinese. Nothing is posted: the calendar holds "planned" rows the creator approves and posts herself.
"""
import datetime as DT
import json
import os

from vstudio import platform as PF

from . import config as C

SLOTS = {"x": "09:00", "linkedin": "08:30", "youtube": "10:00", "youtube-shorts": "12:00", "tiktok": "18:00",
         "instagram": "18:30", "xiaohongshu": "20:00", "douyin": "20:30", "bilibili": "19:30"}
PREFER = {"demo": {"h": ("16:9", "1:1", "9:16"), "v": ("9:16", "1:1", "16:9")},
          "clip": {"h": ("1:1", "16:9", "9:16"), "v": ("9:16", "1:1", "16:9")}}


def _orient(platform):
    p = PF.profile(platform, use_persona=False)
    return "v" if p.h > p.w else "h"


def pick(platform, kind, have, langs):
    """have: {(lang, aspect): path} -> (lang, aspect) best for this platform, or None."""
    base = platform.split(":")[0]
    intl = base in PF.INTL_PLATFORMS
    order = ["en", "zh"] if intl else ["zh", "en"]
    for lang in [x for x in order if x in langs]:
        for asp in PREFER[kind][_orient(platform)]:
            if (lang, asp) in have:
                return lang, asp
    return None


def _start(cfg):
    s = (cfg.get("schedule") or {}).get("start")
    if s:
        return DT.date.fromisoformat(str(s))
    d = DT.date.today() + DT.timedelta(days=1)
    while d.weekday() != 1:                       # next Tuesday: a common launch day
        d += DT.timedelta(days=1)
    return d


def _weekdays(start):
    d = start
    while True:
        if d.weekday() < 5:
            yield d
        d += DT.timedelta(days=1)


def propose(cfg, kit):
    """kit: {"demo": {(lang, aspect): path}, "clips": {feature: {(lang, aspect): path}}, "covers": {path: cover},
    "copy": {("launch"|feature, platform, lang): copy path}}."""
    slots = dict(SLOTS, **((cfg.get("schedule") or {}).get("slots") or {}))
    plats = PF.ordered(list(cfg["platforms"]))
    langs = cfg["languages"]
    days = _weekdays(_start(cfg))
    rows = []

    def add(day, pl, kind, fid, have):
        sel = pick(pl, kind, have, langs)
        if not sel:
            return
        video = have[sel]
        rows.append(dict(at=f"{day.isoformat()}T{slots.get(pl.split(':')[0], '12:00')}", platform=pl, lang=sel[0],
                         aspect=sel[1], kind=kind, feature=fid, video=video, cover=(kit.get("covers") or {}).get(video),
                         copy=(kit.get("copy") or {}).get((fid or "launch", pl, sel[0]))))

    day0 = next(days)
    for pl in plats:
        add(day0, pl, "demo", None, kit.get("demo") or {})
    for fid in C.cut_features(cfg, "clips"):
        day = next(days)
        for pl in plats:
            add(day, pl, "clip", fid, (kit.get("clips") or {}).get(fid) or {})
    rows.sort(key=lambda r: (r["at"][:10], plats.index(r["platform"]), r["at"]))
    return rows


def write(rows, out_dir, product=None):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schedule.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    L = [f"# Posting schedule proposal{(': ' + product) if product else ''}", "",
         "A proposal, not a booking: nothing is posted. Times are local. Move rows freely; "
         "`python -m vstudio.launch schedule CONFIG --apply` puts them on the publish calendar as planned posts.", "",
         "| When | Platform | What | Lang | Canvas | Video |", "|---|---|---|---|---|---|"]
    for r in rows:
        what = "demo" if r["kind"] == "demo" else f"clip: {r['feature']}"
        L.append(f"| {r['at'].replace('T', ' ')} | {r['platform']} | {what} | {r['lang']} | {r['aspect']} | "
                 f"`{os.path.basename(r['video'])}` |")
    with open(os.path.join(out_dir, "SCHEDULE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return os.path.join(out_dir, "schedule.json")


def apply(rows, accounts, project=None):
    """Add every row whose platform has an account (``{platform: account id}``) to the publish calendar as a
    planned post. Rows without an account are returned as skipped (listed, never guessed)."""
    from vstudio.project import pubcal
    added, skipped = [], []
    for r in rows:
        acc = accounts.get(r["platform"]) or accounts.get(r["platform"].split(":")[0])
        if not acc:
            skipped.append(r)
            continue
        title = f"{'demo' if r['kind'] == 'demo' else r['feature']} ({r['lang']}, {r['aspect']})"
        added.append(pubcal.add_post(acc, r["at"], project=project, item=r.get("feature") or "demo", title=title))
    return dict(added=added, skipped=skipped)
