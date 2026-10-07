"""The agent job-folder protocol ("reelfold.agent-job/1"): one folder per shot, the same for every runner.

    <episode>/work/ai/jobs/<shot>/
        job.json      {schema, id, episode, series, shot, runner, kind, spec {dur, aspect, action, camera, lines,
                       notes, faces, ref}, want ["video/mp4", "image/png"], deadline_s, created}
        brief.md      the shot in plain words (what to make, length, aspect, the series rules) - the agent's prompt
        inputs/       still.jpg (the storyboard frame), bible.yaml (cast, rules), ref.json (e.g. the HyperFrames
                      project + composition), anything the importer attached
        outputs/      the agent writes here: .mp4 / .mov / .webm, or .png / .jpg; optional result.json {files, notes}
        status.json   {state queued|running|done|failed|manual-waiting|stopped, progress 0..1, message, heartbeat
                       (epoch s, refreshed by Reelfold while the process lives; the agent may write progress /
                       message too), pid, started, finished, exit_code, code, error}
        log.txt       the runner's stdout + stderr

The QC gate: a run only counts when outputs/ holds at least one video (ffprobe: a video stream, duration > 0)
or image; what passes is copied into the episode's takes. Resume: a shot already made by the same runner is not
run again; every new attempt starts with an empty outputs/.
"""
import json
import os
import shutil
import subprocess
import time

import yaml

SCHEMA = "reelfold.agent-job/1"
VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
IMAGE = (".png", ".jpg", ".jpeg", ".webp")


def _atomic_json(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def status(job_dir):
    return read_json(os.path.join(job_dir, "status.json"), {}) or {}


def set_status(job_dir, **fields):
    """Merge ``fields`` into status.json (keeps what the agent wrote: progress / message)."""
    st = status(job_dir)
    st.update(fields)
    _atomic_json(os.path.join(job_dir, "status.json"), st)
    return st


def brief(shot, bible, runner, aspect, provider_note=""):
    lines = [f"# Shot {shot['no']}", "",
             f"Make one {aspect} shot, {float(shot.get('dur') or 2):.1f} s long.", ""]
    if shot.get("action"):
        lines += ["## What we see", shot["action"], ""]
    if shot.get("camera"):
        lines += ["## Camera", shot["camera"], ""]
    for ln in shot.get("lines") or []:
        lines += ["## Line", f"{ln.get('who') or ''}: {ln.get('text') or ''}".strip(": "), ""]
    if shot.get("notes"):
        lines += ["## Notes", shot["notes"], ""]
    rules = (bible or {}).get("rules") or {}
    if rules.get("always") or rules.get("never"):
        lines += ["## Series rules"] + [f"- Always: {r}" for r in rules.get("always") or []] + \
                 [f"- Never: {r}" for r in rules.get("never") or []] + [""]
    if provider_note:
        lines += ["## How", provider_note, ""]
    lines += ["## Deliver", "Write the finished file into `outputs/` (mp4, or png / jpg for a still). "
              "Nothing outside this folder. Optional: outputs/result.json {\"files\": [...], \"notes\": \"...\"}.",
              f"Runner: {runner}"]
    return "\n".join(lines) + "\n"


def prepare(job_dir, ep, shot, bible, runner, kind, aspect="9:16", deadline_s=1800, provider_note="", fresh=False):
    """Create (or refresh) the job folder -> job dict. ``fresh``: a new attempt - outputs/ is emptied (the takes of
    earlier attempts were already copied out) and status starts over."""
    if fresh:
        shutil.rmtree(os.path.join(job_dir, "outputs"), ignore_errors=True)
        try:
            os.remove(os.path.join(job_dir, "status.json"))
        except OSError:
            pass
    for d in ("inputs", "outputs"):
        os.makedirs(os.path.join(job_dir, d), exist_ok=True)
    spec = {k: shot.get(k) for k in ("dur", "action", "camera", "lines", "notes", "faces", "ref", "beat")}
    spec["aspect"] = aspect
    job = dict(schema=SCHEMA, id=f"{ep['id']}-{shot['no']}", episode=ep["id"], series=ep.get("series"),
               shot=shot["no"], runner=runner, kind=kind, spec=spec, want=["video/mp4", "image/png"],
               deadline_s=deadline_s, created=time.strftime("%Y-%m-%dT%H:%M:%S"))
    _atomic_json(os.path.join(job_dir, "job.json"), job)
    with open(os.path.join(job_dir, "brief.md"), "w", encoding="utf-8") as f:
        f.write(brief(shot, bible, runner, aspect, provider_note))
    if shot.get("still") and os.path.exists(shot["still"]):
        shutil.copyfile(shot["still"], os.path.join(job_dir, "inputs", "still" + os.path.splitext(shot["still"])[1]))
    with open(os.path.join(job_dir, "inputs", "bible.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(dict(cast=(bible or {}).get("cast") or [], rules=(bible or {}).get("rules") or {},
                            aspect=aspect), f, allow_unicode=True, sort_keys=False)
    if shot.get("ref"):
        _atomic_json(os.path.join(job_dir, "inputs", "ref.json"), shot["ref"])
    if not os.path.exists(os.path.join(job_dir, "status.json")):
        set_status(job_dir, state="queued", progress=0, message="")
    return dict(job, dir=job_dir, ref=shot.get("ref") or {})


def outputs(job_dir):
    """Media files the job produced: result.json's list first, then everything in outputs/ (sorted)."""
    out_dir = os.path.join(job_dir, "outputs")
    seen, files = set(), []
    res = read_json(os.path.join(out_dir, "result.json"), {}) or {}
    for f in res.get("files") or []:
        p = os.path.realpath(os.path.join(out_dir, str(f)))
        if p.startswith(os.path.realpath(out_dir) + os.sep) and os.path.isfile(p) and p not in seen:
            seen.add(p)
            files.append(p)
    if os.path.isdir(out_dir):
        for n in sorted(os.listdir(out_dir)):
            p = os.path.realpath(os.path.join(out_dir, n))
            if os.path.isfile(p) and p not in seen and n.lower().endswith(VIDEO + IMAGE):
                seen.add(p)
                files.append(p)
    return [f for f in files if f.lower().endswith(VIDEO + IMAGE)]


def probe_ok(path):
    """A video with a video stream and a duration > 0 (ffprobe), or a non-empty image. No ffprobe: size > 0."""
    try:
        if os.path.getsize(path) <= 0:
            return False
    except OSError:
        return False
    if path.lower().endswith(IMAGE):
        return True
    ff = shutil.which("ffprobe")
    if not ff:
        return True
    try:
        r = subprocess.run([ff, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type:format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=30)
        d = json.loads(r.stdout or "{}")
        return bool(d.get("streams")) and float((d.get("format") or {}).get("duration") or 0) > 0
    except (subprocess.SubprocessError, OSError, ValueError):
        return False


def qc(job_dir):
    """-> (ok, files, code)."""
    files = [f for f in outputs(job_dir) if probe_ok(f)]
    if not files:
        return False, [], "create.agent.qc-no-output"
    return True, files, None
