"""Lesson-clips / interview-qa adapters: the publish review shows every rendered clip (``out/report.json`` of
``vstudio.clipkit``) with its firstpass result."""
import os

from vstudio.batch.util import read_json

from . import common as C
from ..build import file_sha


def _report(env):
    return read_json(os.path.join(env.item_dir, "out", "report.json"), {}) or {}


def publish_payload(env, cp):
    pay = C.publish_payload(env, cp)
    rep = _report(env)
    exports, previews, reds, warns = [], [], [], []
    for clip in rep.get("clips") or []:
        crep = read_json(os.path.join(env.item_dir, "out", clip["id"], "report.json"), {}) or {}
        for e in crep.get("exports") or []:
            exports.append(dict(platform=e.get("platform"), orientation=e.get("orientation"), file=e.get("file"),
                                cover=e.get("cover"), post=e.get("post"), duration=e.get("duration"), clip=clip["id"]))
            previews.append(dict(kind="video", path=e.get("file"), platform=e.get("platform"), clip=clip["id"]))
        for f in crep.get("firstpass") or []:
            reds += [f"{clip['id']}: {x}" for x in f.get("red") or []]
            warns += [f"{clip['id']}: {x}" for x in f.get("warn") or []]
        reds += [f"{clip['id']}: {x}" for x in clip.get("red") or []]
        warns += [f"{clip['id']}: {w}" for w in clip.get("warnings") or []]
    status = "red" if reds else ("green" if exports else None)
    pay.update(exports=exports, previews=previews + list(pay.get("previews") or []),
               qc=dict(status=status, reasons=reds, warnings=warns[:30]),
               default=dict(approve=True) if exports and not reds else None)
    pay["options"] = [dict(file=x["path"], sha=file_sha(x["path"])) for x in pay["previews"] if x.get("path")]
    return pay


def collect(project, job, rows):
    """Every clip's exports (``clip`` = the point / pair id, so the project export names them apart) + the
    manifest's ``outputs.files`` (tracks, notes)."""
    item_dir = job["params"]["_item_dir"]
    rep = read_json(os.path.join(item_dir, "out", "report.json"), {}) or {}
    out = []
    for clip in rep.get("clips") or []:
        crep = read_json(os.path.join(item_dir, "out", clip["id"], "report.json"), {}) or {}
        for e in crep.get("exports") or []:
            out.append(dict(platform=e.get("platform"), orientation=e.get("orientation"), kind="video",
                            file=e.get("file"), cover=e.get("cover"), post=e.get("post"),
                            duration=e.get("duration"), clip=clip["id"]))
    return out + C.collect_files(project, job, rows)
