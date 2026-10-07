"""Calendar / publish queue primitives (no auto-posting: the creator presses publish on the platform).

``$VSTUDIO_HOME/calendar.json``:
    accounts: [{id, platform, name, times ["12:00", "19:00"], per_day 1, days [0..6] (Mon=0)}]
    posts:    [{id, account, platform, at "YYYY-MM-DDTHH:MM", state planned|approved|scheduled|posted|skipped,
                project, item, files {video, cover, post}, title, url, history [{state, at}]}]

    add_account(id, platform, name, times, per_day, days)
    plan(project, accounts, start)    exported items of a project -> the next free slots (planned / approved)
    set_state(post_id, state, at, url)
    listing(start, end, account)      -> posts + gaps (days of an account's cadence with nothing planned)
"""
import datetime as DT
import os
import time

from vstudio.batch.clients import home
from vstudio.batch.util import read_json, slug, write_json

STATES = ("planned", "approved", "scheduled", "posted", "skipped")
FLOW = {"planned": {"approved", "skipped", "planned"}, "approved": {"scheduled", "planned", "skipped", "posted"},
        "scheduled": {"posted", "approved", "skipped"}, "posted": {"posted"}, "skipped": {"planned"}}


class CalendarError(ValueError):
    pass


def path():
    return os.path.join(home(), "calendar.json")


def load():
    d = read_json(path(), {}) or {}
    d.setdefault("accounts", [])
    d.setdefault("posts", [])
    return d


def save(d):
    write_json(path(), d)
    return d


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def add_account(aid, platform, name=None, times=None, per_day=None, days=None):
    from vstudio import platform as P
    P.profile(platform)
    d = load()
    d["accounts"] = [a for a in d["accounts"] if a["id"] != aid]
    times = list(times or ["19:00"])
    acc = dict(id=slug(aid), platform=platform, name=name or aid, times=times,
               per_day=int(per_day or len(times)), days=sorted(int(x) for x in (days if days is not None else range(7))))
    d["accounts"].append(acc)
    save(d)
    return acc


def _slots(acc, start, n_days=120):
    day = start.date()
    for _ in range(n_days):
        if day.weekday() in acc["days"]:
            for t in acc["times"][:acc["per_day"]]:
                hh, mm = (int(x) for x in t.split(":"))
                at = DT.datetime(day.year, day.month, day.day, hh, mm)
                if at >= start:
                    yield at.strftime("%Y-%m-%dT%H:%M")
        day += DT.timedelta(days=1)


def plan(project_dir, accounts=None, start=None):
    """Every exported item of the project (``<project>/exports/manifest.json``) not yet on the calendar ->
    one post per account whose platform matches the export, in the next free slot. The state is ``approved``
    when the item passed its publish checkpoint (it was exported), else ``planned``."""
    man = read_json(os.path.join(os.path.abspath(project_dir), "exports", "manifest.json"))
    if not man:
        raise CalendarError(f"{project_dir}: no exports/manifest.json - run `project export` first")
    d = load()
    accs = [a for a in d["accounts"] if not accounts or a["id"] in accounts]
    if not accs:
        raise CalendarError("no accounts - `calendar account add` first")
    start = DT.datetime.fromisoformat(start) if start else DT.datetime.now()
    taken = {(p["account"], p["at"]) for p in d["posts"] if p["state"] != "skipped"}
    have = {(p["account"], p["project"], p["item"]) for p in d["posts"]}
    added = []
    for acc in accs:
        plat = acc["platform"].split(":")[0]
        slots = (s for s in _slots(acc, start) if (acc["id"], s) not in taken)
        for e in man.get("items") or []:
            if e.get("kind") not in (None, "video") or (e.get("platform") or "").split(":")[0] != plat:
                continue
            if (acc["id"], man["project"], e["item"]) in have:
                continue
            at = next(slots, None)
            if at is None:
                break
            post = dict(id=f"{acc['id']}-{len(d['posts']) + len(added) + 1:04d}", account=acc["id"],
                        platform=acc["platform"], at=at, state="approved", project=man["project"], item=e["item"],
                        files=dict(video=e.get("file"), cover=e.get("cover"), post=e.get("post")),
                        title=e.get("title"), url=None, history=[dict(state="approved", at=_stamp())])
            added.append(post)
            taken.add((acc["id"], at))
            have.add((acc["id"], man["project"], e["item"]))
    d["posts"] += added
    save(d)
    return dict(ok=True, added=added, n=len(added))


def add_post(account, at, project=None, item=None, title=None, state="planned"):
    d = load()
    acc = next((a for a in d["accounts"] if a["id"] == account), None)
    if not acc:
        raise CalendarError(f"unknown account {account}")
    if state not in STATES:
        raise CalendarError(f"state must be one of {STATES}")
    post = dict(id=f"{account}-{len(d['posts']) + 1:04d}", account=account, platform=acc["platform"], at=at,
                state=state, project=project, item=item, files={}, title=title, url=None,
                history=[dict(state=state, at=_stamp())])
    d["posts"].append(post)
    save(d)
    return post


def set_state(post_id, state, at=None, url=None):
    if state not in STATES:
        raise CalendarError(f"state must be one of {STATES}")
    d = load()
    p = next((x for x in d["posts"] if x["id"] == post_id), None)
    if not p:
        raise CalendarError(f"unknown post {post_id}")
    if state not in FLOW[p["state"]]:
        raise CalendarError(f"{post_id}: {p['state']} -> {state} not allowed")
    p["state"] = state
    if at:
        p["at"] = at
    if url:
        p["url"] = url
    p["history"].append(dict(state=state, at=_stamp()))
    save(d)
    return p


def listing(start=None, end=None, account=None):
    d = load()
    s = DT.datetime.fromisoformat(start) if start else DT.datetime.now().replace(hour=0, minute=0, second=0,
                                                                                microsecond=0)
    e = DT.datetime.fromisoformat(end) if end else s + DT.timedelta(days=14)
    posts = [p for p in d["posts"] if (not account or p["account"] == account)
             and s <= DT.datetime.fromisoformat(p["at"]) < e]
    posts.sort(key=lambda p: p["at"])
    gaps = []
    for acc in d["accounts"]:
        if account and acc["id"] != account:
            continue
        day = s.date()
        while day < e.date():
            if day.weekday() in acc["days"]:
                n = sum(1 for p in posts if p["account"] == acc["id"] and p["state"] != "skipped"
                        and p["at"].startswith(day.isoformat()))
                if n < acc["per_day"]:
                    gaps.append(dict(account=acc["id"], day=day.isoformat(), missing=acc["per_day"] - n))
            day += DT.timedelta(days=1)
    counts = {}
    for p in posts:
        counts[p["state"]] = counts.get(p["state"], 0) + 1
    from vstudio import messages as MSG                # code + params per state (references/MESSAGES.md)
    posts = [dict(p, state_info=MSG.state("post-state", p["state"])) for p in posts]
    return dict(start=s.isoformat(), end=e.isoformat(), accounts=d["accounts"], posts=posts, gaps=gaps, counts=counts,
                states={k: MSG.state("post-state", k) for k in STATES})
