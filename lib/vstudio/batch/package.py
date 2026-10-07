"""``package``: approved jobs -> per-platform publish folders + a posting schedule + a manifest whose hash is
the confirmation code. Nothing is uploaded (F0): a human posts from the folders, or a later uploader takes the
manifest; the code identifies exactly this list (any change to files, order, dates -> a new code).

<batch>/package/
  <platform>-<orientation>/<NNN>_<job>/video.mp4 cover.jpg post.md    (hard links: no extra space)
  schedule.csv      date,time,platform,job,title,file,sha256  (per_day posts per platform per day)
  manifest.json     {batch, schedule, items[...], confirmation_code}
  CONFIRM.txt       the code + the item count, to quote when confirming the posting batch
"""
import csv
import datetime as dt
import os
import shutil

from vstudio import media

from .api import verify_manifest  # noqa: F401  (public: recompute the confirmation code of a manifest)
from .store import Store
from .util import read_json, sha1_json, sha256_file, write_json
from ..oscompat import relpath as _relpath

DEFAULT_TIMES = ["12:00", "19:00", "21:00"]


def _schedule_opts(spec, per_day=None, start=None, times=None):
    s = dict(spec.get("schedule") or {})
    per_day = int(per_day or s.get("per_day") or 1)
    start = start or s.get("start")
    if start is None:
        start = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    times = list(times or s.get("times") or DEFAULT_TIMES)
    while len(times) < per_day:
        times.append(times[-1])
    return per_day, str(start), times[:per_day]


def package(batch_dir, out=None, per_day=None, start=None, times=None, include_packaged=True):
    store = Store(batch_dir)
    try:
        spec = store.spec
        per_day, start, times = _schedule_opts(spec, per_day, start, times)
        pdir = os.path.abspath(out or os.path.join(store.dir, "package"))
        states = ("approved", "packaged") if include_packaged else ("approved",)
        jobs = store.jobs(states)
        if not jobs:
            raise ValueError("no approved jobs to package (review --apply decisions.json first)")
        old = {}                                   # a re-package after `clean` links from the previous package
        om = read_json(os.path.join(pdir, "manifest.json"), {}) or {}
        for it in om.get("items") or []:
            old[(it["job"], it["platform"])] = {k: os.path.join(pdir, v) for k, v in it["files"].items()}
        final, pdir = pdir, pdir + ".tmp"
        shutil.rmtree(pdir, ignore_errors=True)
        os.makedirs(pdir)
        d0 = dt.date.fromisoformat(start)
        items, counters = [], {}
        for j in jobs:
            ex = ((store.stage(j["id"], "export") or {}).get("out") or {}).get("exports") or []
            if not ex:
                raise ValueError(f"{j['id']}: no exports (run it first)")
            p = j["params"] or {}
            for e in ex:
                key = f"{e['platform']}-{e['orientation']}"
                k = counters.get(key, 0)
                counters[key] = k + 1
                prev = old.get((j["id"], key), {})
                src_v = e["file"] if os.path.exists(e["file"]) else prev.get("video")
                if not src_v or not os.path.exists(src_v):
                    raise FileNotFoundError(f"{j['id']}: {e['file']} is gone (cleaned?) - re-run the job")
                folder = os.path.join(pdir, key, f"{k + 1:03d}_{j['id']}")
                os.makedirs(folder)
                vid = media.link_or_copy(src_v, os.path.join(folder, "video.mp4"))
                files = {"video": _relpath(vid, pdir)}
                for name, src in (("cover", e.get("cover") or prev.get("cover")), ("post", e.get("post") or prev.get("post"))):
                    if src and os.path.exists(src):
                        dst = media.link_or_copy(src, os.path.join(folder, "cover.jpg" if name == "cover" else "post.md"))
                        files[name] = _relpath(dst, pdir)
                day, slot = divmod(k, per_day)
                items.append(dict(job=j["id"], platform=key, title=p.get("title") or "", date=(d0 + dt.timedelta(days=day))
                                  .isoformat(), time=times[slot], files=files, sha256=sha256_file(vid),
                                  bytes=os.path.getsize(vid), duration=e.get("duration")))
        items.sort(key=lambda x: (x["date"], x["time"], x["platform"], x["job"]))
        sched = dict(per_day=per_day, start=start, times=times)
        code = sha1_json(dict(batch=spec.get("name"), schedule=sched, items=items))[:12]
        man = dict(batch=spec.get("name"), schedule=sched, items=items, confirmation_code=code,
                   note="F0: nothing is uploaded. Confirm this exact list by quoting the code; any change -> new code.")
        write_json(os.path.join(pdir, "manifest.json"), man)
        with open(os.path.join(pdir, "schedule.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "time", "platform", "job", "title", "file", "sha256"])
            for it in items:
                w.writerow([it["date"], it["time"], it["platform"], it["job"], it["title"], it["files"]["video"],
                            it["sha256"]])
        with open(os.path.join(pdir, "CONFIRM.txt"), "w", encoding="utf-8") as f:
            f.write(f"confirmation code: {code}\nitems: {len(items)} posts, {len(jobs)} jobs, "
                    f"{per_day}/day/platform from {start}\n")
        shutil.rmtree(final, ignore_errors=True)
        os.replace(pdir, final)
        pdir = final
        for j in jobs:
            store.set_job(j["id"], state="packaged")
        store.set_meta("package", dict(code=code, dir=pdir, items=len(items)))
        store.log("package", f"{len(items)} posts, code {code}")
        return dict(dir=pdir, code=code, items=len(items), jobs=len(jobs), manifest=os.path.join(pdir, "manifest.json"))
    finally:
        store.close()
