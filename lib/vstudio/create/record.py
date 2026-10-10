"""Recorder ingest (SPEC §1.6): a recorder session folder -> best take per line -> studio sound -> a talking-head
project, one shot's take, or (target ``assembled``) just the cleaned file the desk starts an autopilot request with.

    <recordings>/<ts>-<slug>/session.json   {id, slug, created, script [lines], tracks {camera|mic|screen:
                                             {file, start_ms, mime}}, series?, episode?, shot?}
                             camera.webm mic.webm screen.webm?   (1 s chunks appended while recording)
                             (session.json studio: false = keep the raw sound, no studio-sound pass)
                             takes.json      [{t (s from the start), kind line|retake, line}]
                             recording.lock  (while live; left behind = the app quit mid-take -> recover())

Best take per line: every 'line' / 'retake' mark starts an attempt of that line, the next mark ends it; the LAST
attempt of each line is kept (a retake = "say it again"). With a transcript (real mode) an attempt without words
falls back to the previous one and the cut is tightened to the first / last word.
"""
import glob
import os
import shutil
import subprocess

from . import store
from .i18n import CreateError

TRACKS = ("camera", "mic", "screen")


def _ff():
    ff = shutil.which("ffmpeg")
    if not ff:
        raise CreateError("bad-input", field="ffmpeg", missing=True)
    return ff


def _run(args, timeout=1800):
    # never her stdin (like media.run's -nostdin): ffmpeg on Windows stalls on an inherited pipe nobody writes to (the
    # desk engine's own stdin), a take that never finishes
    subprocess.run(args, check=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def need_session(d):
    d = os.path.abspath(d)
    root = os.path.realpath(store.recordings_root())
    extra = [os.path.realpath(p) for p in (os.environ.get("VSTUDIO_RECORDINGS_EXTRA") or "").split(os.pathsep) if p]
    real = os.path.realpath(d)
    if not any(real == r or real.startswith(r + os.sep) for r in [root] + extra):
        raise CreateError("bad-input", field="session_dir")
    if not os.path.exists(os.path.join(d, "session.json")):
        raise CreateError("not-found", status=404, what="recording", id=os.path.basename(d))
    return d


def duration(path):
    try:
        from vstudio import media
        return float(media.duration(path))
    except Exception:  # noqa: BLE001
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True)
        try:
            return float(out.stdout.strip())
        except ValueError:
            return 0.0


def remux(path):
    """A crash-cut WebM (no cues / duration) -> the same file rewritten with -c copy (seekable)."""
    tmp = path + ".fix.webm"
    try:
        _run([_ff(), "-v", "error", "-y", "-i", path, "-c", "copy", "-cues_to_front", "1", tmp], timeout=600)
        os.replace(tmp, path)
        return True
    except (subprocess.SubprocessError, OSError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def recover(root=None):
    """Sessions left with recording.lock (the app quit while recording): remux every track, drop the lock."""
    root = root or store.recordings_root()
    out = []
    for lock in sorted(glob.glob(os.path.join(root, "*", "recording.lock"))):
        d = os.path.dirname(lock)
        fixed = [t for t in TRACKS if os.path.exists(os.path.join(d, f"{t}.webm")) and
                 remux(os.path.join(d, f"{t}.webm"))]
        os.remove(lock)
        out.append(dict(dir=d, id=os.path.basename(d), tracks=fixed))
    return out


def attempts(marks, total, n_lines):
    """marks [{t, kind, line}] -> {line: [(start, end), ...]} in recording order."""
    ms = sorted([m for m in marks if m.get("kind") in ("line", "retake") and isinstance(m.get("line"), int)],
                key=lambda m: float(m["t"]))
    out = {}
    if not ms:
        return {0: [(0.0, total)]} if total else {}
    if float(ms[0]["t"]) > 0.5:
        out.setdefault(0, []).append((0.0, float(ms[0]["t"])))
    for i, m in enumerate(ms):
        a = float(m["t"])
        b = float(ms[i + 1]["t"]) if i + 1 < len(ms) else total
        if b - a >= 0.3 and 0 <= m["line"] < max(n_lines, 1):
            out.setdefault(m["line"], []).append((a, b))
    return out


def pick_best(atts, words=None):
    """The last attempt of each line; with words, the last one that has speech, tightened to its words."""
    edl = []
    for line in sorted(atts):
        cands = list(atts[line])
        chosen = cands[-1]
        if words is not None:
            spoken = [(a, b, [w for w in words if a <= w["start"] < b]) for a, b in cands]
            with_words = [x for x in spoken if x[2]]
            if with_words:
                a, b, ws = with_words[-1]
                chosen = (max(a, ws[0]["start"] - 0.15), min(b, ws[-1]["end"] + 0.25))
        edl.append(dict(line=line, start=round(chosen[0], 3), end=round(chosen[1], 3), attempts=len(cands)))
    return edl


def mux(d, sess, out):
    tracks = sess.get("tracks") or {}
    cam = os.path.join(d, (tracks.get("camera") or {}).get("file") or "camera.webm")
    mic = os.path.join(d, (tracks.get("mic") or {}).get("file") or "mic.webm")
    if not os.path.exists(cam):
        raise CreateError("not-found", status=404, what="camera track", id=os.path.basename(d))
    args = [_ff(), "-v", "error", "-y", "-i", cam]
    has_mic = os.path.exists(mic) and os.path.getsize(mic) > 0
    if has_mic:
        off = ((tracks.get("mic") or {}).get("start_ms", 0) - (tracks.get("camera") or {}).get("start_ms", 0)) / 1000
        args += ["-itsoffset", f"{off:.3f}", "-i", mic, "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args += ["-map", "0:v:0", "-map", "0:a?"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-ar", "48000", out]
    _run(args)
    return out


def cut(src, edl, out, studio=True):
    work = os.path.join(os.path.dirname(out), "segments")
    os.makedirs(work, exist_ok=True)
    parts = []
    for i, e in enumerate(edl):
        p = os.path.join(work, f"seg{i:03d}.mp4")
        _run([_ff(), "-v", "error", "-y", "-ss", f"{e['start']:.3f}", "-to", f"{e['end']:.3f}", "-i", src,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-ar", "48000", p])
        parts.append(p)
    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    joined = os.path.join(work, "joined.mp4")
    _run([_ff(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    if studio:                                 # local denoise + dereverb + voice EQ, -16 LUFS (vstudio.studiosound)
        from vstudio import studiosound
        studiosound.enhance(joined, out, "standard", lufs=-16.0)
    else:
        shutil.copy2(joined, out)
    return out


def transcript_words(path, language=None):
    """mlx-whisper (or the configured ASR) -> [{word, start, end}] or None when no ASR is available."""
    try:
        from vstudio import asr
        tr = asr.transcribe(path, language=language)
        # asr.words_of -> [{w, t, te}] (not whisper's word / start / end)
        return [dict(word=w.get("w"), start=float(w["t"]), end=float(w["te"]))
                for w in asr.words_of(tr) if w.get("t") is not None]
    except Exception:  # noqa: BLE001  (no ASR installed: the marks alone decide)
        return None


def ingest(session_dir, target="project:talkinghead", series=None, on_event=None, run=False):
    d = need_session(session_dir)
    if os.path.exists(os.path.join(d, "recording.lock")):
        recover(os.path.dirname(d))
    sess = store.read_json(os.path.join(d, "session.json"), {}) or {}
    marks = store.read_json(os.path.join(d, "takes.json"), []) or []
    lines = [str(x) for x in sess.get("script") or []]

    def ev(stage, **kw):
        if on_event:
            on_event(dict(event="create.progress", stage=stage, session=os.path.basename(d), **kw))
    ev("mux")
    work = os.path.join(d, "work")
    os.makedirs(work, exist_ok=True)
    take = mux(d, sess, os.path.join(work, "take_1.mp4"))
    total = duration(take)
    ev("transcribe")
    words = transcript_words(take, sess.get("language"))
    atts = attempts(marks, total, len(lines))
    edl = pick_best(atts, words)
    if not edl:
        edl = [dict(line=0, start=0.0, end=round(total, 3), attempts=1)]
    ev("clean")
    out = cut(take, edl, os.path.join(d, "assembled.mp4"), studio=sess.get("studio", True) is not False)
    res = dict(ok=True, session=os.path.basename(d), dir=d, assembled=out, duration=round(duration(out), 2),
               lines=[dict(e, text=lines[e["line"]] if e["line"] < len(lines) else "") for e in edl],
               retakes=sum(1 for m in marks if m.get("kind") == "retake"), transcript=words is not None)
    if str(target).startswith("shot:"):
        eid, no = target[5:].split("/")
        from . import jobs
        dst = os.path.join(work, f"{store.need_shot(no)}_rec.mp4")
        shutil.copy2(out, dst)
        res["imported"] = jobs.import_takes(store.need_eid(eid), [dst])["imported"]
    elif target == "assembled":
        pass                                   # only the cleaned file: the desk hands it to an autopilot request
    else:
        from vstudio.project.core import Project
        name = sess.get("title") or sess.get("slug") or os.path.basename(d)
        pdir = os.path.join(d, "project")
        ser = None
        if series:
            try:
                from vstudio.project import home as H
                H.load_series(series)
                ser = series
            except Exception:  # noqa: BLE001  (a Create series outside $VSTUDIO_HOME: no series link)
                ser = None
        p = Project.create(pdir, recipe="talkinghead", name=name, inputs={"video": [out]}, series=ser,
                           exist_ok=True, write_agent_files=False)
        res["project_dir"] = p.dir
        if run:
            ev("pilot")
    store.write_json(os.path.join(d, "ingest.json"), res)
    ev("done")
    return res
