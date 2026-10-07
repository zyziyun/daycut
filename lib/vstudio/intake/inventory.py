"""`intake analyze`: inventory any mix of files / folders -> a compact material summary (cached per file).

    from vstudio.intake import inventory as I
    inv = I.analyze(["raw/", "brief.pdf"], asr="sample")     # dict (kind vstudio.intake.analysis)

Per file kind:
  video   probe (duration, size, orientation, fps, hdr, audio), speech from a short ASR sample (2-3 windows of
          20 s, or the whole track with ``asr="full"``), cheap visual heuristics on 6 frames: faces per frame
          (``vstudio.face``), talking head / multi-person / screen share / burned-in captions; filename hints
          (zoom / meet / screen recording / final export)
  audio   probe + speech sample (podcast vs music)
  image   size, EXIF capture time + coarse location (1 decimal), faces on a sample of up to 12 images
  text    pdf / docx / pptx / md / txt / srt / vtt via ``docs.analyze`` (title, headings, 300-char excerpt, shape:
          script / slides / outline / notes / article / subtitles, URLs found - never fetched)
Folders are walked recursively (hidden files, VCS / dependency folders and symlinks skipped; ``MAX_FILES``,
``MAX_DEPTH``); photos / clips of one folder are summarised as a group. Every file gets a content hash
(``qhash``: sha1 of size + three 1 MiB windows - fast on multi-GB recordings) and its facts are cached under
``$VSTUDIO_CACHE/intake/`` by that hash + the analyzer version, so a second analyze / plan is instant.
Nothing is written next to the inputs (inputs are treated as read-only).
"""
import hashlib
import json
import os
import re
import statistics
import subprocess
import tempfile
import time

from . import docs as D
from ..oscompat import relpath as _relpath

VERSION = 3
MAX_FILES = 2000
MAX_DEPTH = 8
HEAVY_VIDEOS = 40          # videos beyond this get probe facts only (no ASR / faces)
FACE_IMAGES = 12
SAMPLE_S = 20.0
FULL_ASR_MAX_S = 3 * 3600  # never transcribe more than this per file in "full" mode
SKIP_DIRS = {".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".cache", "state", "exports"}

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".3gp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff", ".aif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".dng"}

CALL_NAME = re.compile(r"zoom|meet|teams|webex|腾讯会议|飞书会议|会议|recording|\bGMT\d|\b(PDT|PST|EST|EDT|CST)\b|播客|podcast|访谈|interview",
                       re.I)
SCREEN_NAME = re.compile(r"screen ?recording|屏幕录制|录屏|screencast|obs", re.I)
FINAL_NAME = re.compile(r"final|成片|导出|export|发布版|定稿|_v\d+$|master", re.I)
LECTURE_NAME = re.compile(r"课|lecture|class|course|培训|讲座|webinar|直播|livestream|workshop|分享会", re.I)

# test hooks: replaced by the golden tests (no ASR / mediapipe / ffmpeg needed there)
TRANSCRIBE = None           # fn(wav_path, language) -> transcript dict (vstudio.asr shape)
FACES = None                # fn(bgr image) -> [area_frac ...]


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    if ext in D.DOC_EXT:
        return "text"
    return "other"


def qhash(path, win=1 << 20):
    """Content hash that stays fast on huge files: size + head / middle / tail windows."""
    st = os.stat(path)
    h = hashlib.sha1(str(st.st_size).encode())
    with open(path, "rb") as f:
        if st.st_size <= 3 * win:
            h.update(f.read())
        else:
            for off in (0, st.st_size // 2 - win // 2, st.st_size - win):
                f.seek(off)
                h.update(f.read(win))
    return h.hexdigest()


# --------------------------------------------------------------------------- walk
def walk(inputs, max_files=MAX_FILES, max_depth=MAX_DEPTH):
    """-> (files [(abs path, root it came from)], notes)."""
    out, notes, seen = [], [], set()
    for raw in inputs:
        p = os.path.abspath(os.path.expanduser(str(raw)))
        if not os.path.exists(p):
            notes.append(f"missing input: {raw}")
            continue
        if os.path.isfile(p):
            if p not in seen:
                seen.add(p)
                out.append((p, None))
            continue
        base_depth = p.rstrip(os.sep).count(os.sep)
        for d, dirs, files in os.walk(p, followlinks=False):
            depth = d.rstrip(os.sep).count(os.sep) - base_depth
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in SKIP_DIRS and depth < max_depth
                             and not os.path.islink(os.path.join(d, x)))
            for fn in sorted(files):
                if fn.startswith(".") or fn.endswith((".asr.json", ".part", ".tmp")):
                    continue
                fp = os.path.join(d, fn)
                if os.path.islink(fp) or fp in seen:
                    continue
                if len(out) >= max_files:
                    notes.append(f"stopped at {max_files} files (MAX_FILES) under {raw}")
                    return out, notes
                seen.add(fp)
                out.append((fp, p))
    return out, notes


# --------------------------------------------------------------------------- media helpers
def _ffmpeg():
    from vstudio import media
    return media.ffmpeg_bin() if hasattr(media, "ffmpeg_bin") else "ffmpeg"


def _frames(src, dur, n=6, width=640):
    import cv2
    import numpy as np
    out = []
    for k in range(n):
        t = dur * (0.08 + 0.84 * k / max(1, n - 1)) if dur > 0 else 0
        try:
            r = subprocess.run([_ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                                "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                               capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            continue
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR) if r.stdout else None
        if img is not None:
            out.append((t, img))
    return out


_LM = {}


def _face_areas(img):
    if FACES is not None:
        return FACES(img)
    import numpy as np
    from vstudio import face
    if "lm" not in _LM:
        _LM["lm"] = face.landmarker(num_faces=6)
    h, w = img.shape[:2]
    return sorted((float(np.ptp(f["pts"][:, 0]) * np.ptp(f["pts"][:, 1]) / (w * h)) for f in face.detect(_LM["lm"], img)),
                  reverse=True)


def frame_stats(img):
    """Per-frame numbers the heuristics use: faces, edge density, saturation, flatness, caption-band scores
    (bright text pixels touching a dark outline / shadow, per mille, in the lower, middle and top bands)."""
    import cv2
    import numpy as np
    h, w = img.shape[:2]
    try:
        areas = _face_areas(img)
    except Exception:  # noqa: BLE001 - no mediapipe / model: faces unknown
        areas = None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = float((cv2.Canny(g, 80, 160) > 0).mean())
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bright = ((V > 200) & (S < 70)) | ((V > 200) & (H > 18) & (H < 35) & (S > 120))
    dark = cv2.dilate((V < 70).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    stroke = bright & dark

    def band(a, b):
        return float(stroke[int(a * h):int(b * h), int(.1 * w):int(.9 * w)].mean()) * 1000

    flat = float((np.abs(cv2.Laplacian(g, cv2.CV_32F)) < 2).mean())
    return dict(faces=None if areas is None else len([a for a in areas if a >= 0.002]),
                face_area=None if not areas else round(areas[0], 4), edges=round(edges, 4), sat=round(float(S.mean()), 1),
                flat=round(flat, 3), cap_low=round(band(.72, .96), 2), cap_mid=round(band(.55, .75), 2),
                cap_top=round(band(.04, .30), 2))


def visual_facts(stats, w, h):
    """Aggregate frame stats -> {faces_median, talking_head, multi_person, screen_share, burned_captions, ...}."""
    if not stats:
        return {}
    med = lambda k: statistics.median([s[k] for s in stats if s.get(k) is not None] or [0])  # noqa: E731
    out = dict(frames=len(stats))
    screen = med("sat") < 30 and med("flat") > 0.62
    out["screen_share"] = bool(screen)
    face_known = [s for s in stats if s.get("faces") is not None]
    if face_known:
        counts = [s["faces"] for s in face_known]
        one = sum(1 for c in counts if c == 1) / len(counts)
        many = sum(1 for c in counts if c >= 2) / len(counts)
        area = statistics.median([s["face_area"] or 0 for s in face_known])
        out.update(faces_median=statistics.median(counts), face_area=round(area, 4),
                   talking_head=bool(one >= 0.6 and area >= 0.01 and not screen),
                   multi_person=bool(many >= 0.5))
        if screen and any(c >= 1 for c in counts):
            out["screen_with_faces"] = True
    low = [s["cap_low"] for s in stats]
    mid = [s["cap_mid"] for s in stats]
    other = lambda s, k: max([s[x] for x in ("cap_low", "cap_mid", "cap_top") if x != k])  # noqa: E731
    best = "cap_low" if statistics.median(low) >= statistics.median(mid) else "cap_mid"
    hits = sum(1 for s in stats if s[best] >= 6 and s[best] >= 5 * max(other(s, best), 0.6))
    out["burned_captions"] = bool(not screen and hits >= max(2, 0.5 * len(stats)))
    if out["burned_captions"]:
        out["caption_band"] = "lower" if best == "cap_low" else "middle"
    out["caption_score"] = round(statistics.median([s[best] for s in stats]), 1)
    return out


def _wav_sample(src, dst, start, dur):
    cmd = [_ffmpeg(), "-v", "error", "-y"]
    if start:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", src]
    if dur:
        cmd += ["-t", f"{dur:.2f}"]
    cmd += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst]
    subprocess.run(cmd, capture_output=True, check=True, timeout=max(120, int((dur or 3600) * 0.2)))
    return dst


def _transcribe(wav, language=None, words=True):
    """words=False: sentence timing only (the sample passes: no word alignment, which costs a JIT compile + DTW)."""
    if TRANSCRIBE is not None:
        return TRANSCRIBE(wav, language)
    from vstudio import asr
    return asr.transcribe(wav, language=language, cache=False, word_timestamps=words)


def _rms_speechiness(wav):
    """No ASR available: share of 30 ms frames above a voice-ish RMS floor (0..1), as a weak hint."""
    import wave

    import numpy as np
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    if not len(x):
        return 0.0
    n = 480
    fr = x[: len(x) // n * n].reshape(-1, n)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    return float((rms > 0.01).mean())


def sentences_of(tr, max_len=22.0):
    """Transcript -> [{t, te, text}] (whisper segments, long ones kept whole; compact for the planner)."""
    out = []
    for s in tr.get("segments") or []:
        txt = (s.get("text") or "").strip()
        if txt:
            out.append(dict(t=round(float(s["start"]), 2), te=round(float(s["end"]), 2), text=txt))
    return out


def speech_facts(src, dur, has_audio, mode, cache_root, key, language=None):
    """mode: off | sample | full. -> facts; a full transcript goes to ``<cache>/<key>.transcript.json``."""
    if not has_audio:
        return dict(speech=False, speech_basis="no audio track")
    if mode == "off":
        return dict(speech=None, speech_basis="not checked (--asr off)")
    out = {}
    with tempfile.TemporaryDirectory(prefix="vstudio-intake-") as tmp:
        try:
            if mode == "full" and dur <= FULL_ASR_MAX_S:
                wav = _wav_sample(src, os.path.join(tmp, "full.wav"), 0, None)
                tr = _transcribe(wav, language)
                sents = sentences_of(tr)
                tp = os.path.join(cache_root, f"{key}.transcript.json")
                with open(tp, "w", encoding="utf-8") as f:
                    json.dump(dict(source_qhash=key.split(".")[0], language=tr.get("language"), sentences=sents), f,
                              ensure_ascii=False)
                spoken = sum(s["te"] - s["t"] for s in sents)
                text = "".join(s["text"] for s in sents)
                out.update(speech=bool(sents and spoken > min(10.0, dur * 0.2)), speech_basis="asr full",
                           transcript=tp, sentences=len(sents), speech_s=round(spoken, 1),
                           chars_per_min=round(len(text) / max(dur / 60, 0.1)), language=tr.get("language"),
                           excerpt=D.excerpt(text, 160))
                return out
            fracs = [0.5] if dur <= 180 else [0.15, 0.5, 0.85]       # one sample says enough about a short clip
            texts, langs, words = [], [], 0
            for k, fr in enumerate(fracs):
                ln = min(SAMPLE_S, dur) if dur > 0 else SAMPLE_S
                st = max(0.0, dur * fr - ln / 2) if dur > ln else 0.0
                wav = _wav_sample(src, os.path.join(tmp, f"s{k}.wav"), st, ln)
                tr = _transcribe(wav, language, words=False)
                language = language or tr.get("language")          # detected once, then reused for the next samples
                t = "".join((s.get("text") or "") for s in tr.get("segments") or []).strip()
                words += len(tr.get("words") or []) or len(t)
                if t:
                    texts.append(t)
                langs.append(tr.get("language"))
            joined = " / ".join(texts)
            out.update(speech=bool(texts) and len(re.sub(r"\W", "", joined)) >= 6 * len(fracs) / 3,
                       speech_basis=f"asr sample {len(fracs)}x{int(SAMPLE_S)}s",
                       excerpt=D.excerpt(joined, 160), language=next((x for x in langs if x), None))
        except Exception as e:  # noqa: BLE001 - no ASR backend: fall back to loudness
            try:
                wav = _wav_sample(src, os.path.join(tmp, "e.wav"), max(0.0, dur / 2 - 15), min(30.0, dur or 30))
                sp = _rms_speechiness(wav)
                out.update(speech=None, speech_basis=f"asr unavailable ({type(e).__name__}); voice-ish energy {sp:.0%}",
                           energy=round(sp, 2))
            except Exception as e2:  # noqa: BLE001
                out.update(speech=None, speech_basis=f"not checked ({type(e2).__name__})")
    return out


# --------------------------------------------------------------------------- per kind
def _orientation(w, h):
    if not w or not h:
        return None
    r = w / h
    return "vertical" if r < 0.9 else "horizontal" if r > 1.1 else "square"


def analyze_video(path, mode="sample", heavy=True, cache_root=None, key=None, kind="video", language=None):
    from vstudio import media
    try:
        p = media.probe(path)
    except Exception as e:  # noqa: BLE001
        return dict(note=f"probe failed: {type(e).__name__}: {str(e)[:120]}")
    dur = float(p.get("duration") or 0)
    w, h = p.get("display_w") or p.get("w"), p.get("display_h") or p.get("h")
    out = dict(duration=round(dur, 1), has_audio=bool(p.get("has_audio")))
    if kind == "video":
        out.update(width=w, height=h, orientation=_orientation(w, h), fps=round(float(p.get("fps") or 0), 2),
                   hdr=bool(p.get("hdr")))
        if not p.get("has_video"):
            out["note"] = "no video stream"
    name = os.path.basename(path)
    hints = [k for k, rx in (("call", CALL_NAME), ("screen-recording", SCREEN_NAME), ("final-export", FINAL_NAME),
                             ("lecture", LECTURE_NAME)) if rx.search(os.path.splitext(name)[0])]
    if hints:
        out["name_hints"] = hints
    if not heavy:
        out["note"] = (out.get("note", "") + " probe only (heavy-analysis limit)").strip()
        return out
    out.update(speech_facts(path, dur, out["has_audio"], mode, cache_root, key, language))
    if kind == "video" and p.get("has_video"):
        try:
            stats = [frame_stats(img) for _, img in _frames(path, dur)]
            out.update(visual_facts(stats, w, h))
        except ImportError as e:
            out["note"] = f"visual heuristics skipped ({e})"
    return out


def _exif(path):
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return {}
    try:
        with Image.open(path) as im:
            out = dict(width=im.width, height=im.height)
            ex = im.getexif()
            if not ex:
                return out
            tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
            try:
                sub = ex.get_ifd(0x8769)
                tags.update({ExifTags.TAGS.get(k, k): v for k, v in sub.items()})
            except Exception:  # noqa: BLE001
                pass
            t = tags.get("DateTimeOriginal") or tags.get("DateTime")
            if t:
                out["taken"] = str(t).replace(":", "-", 2)
            try:
                gps = ex.get_ifd(0x8825)
                if gps and 2 in gps and 4 in gps:
                    def deg(v):
                        return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                    lat, lon = deg(gps[2]), deg(gps[4])
                    lat = -lat if gps.get(1) == "S" else lat
                    lon = -lon if gps.get(3) == "W" else lon
                    out["gps"] = [round(lat, 1), round(lon, 1)]       # coarse (~10 km): enough to group a trip
            except Exception:  # noqa: BLE001
                pass
            return out
    except Exception as e:  # noqa: BLE001
        return dict(note=f"image unreadable ({type(e).__name__})")


def analyze_image(path, faces=False):
    out = _exif(path)
    if out.get("width"):
        out["orientation"] = _orientation(out["width"], out["height"])
    if faces:
        try:
            import cv2
            img = cv2.imread(path)
            if img is not None:
                if max(img.shape[:2]) > 960:
                    s = 960 / max(img.shape[:2])
                    img = cv2.resize(img, None, fx=s, fy=s)
                out["faces"] = len([a for a in _face_areas(img) if a >= 0.002])
        except Exception:  # noqa: BLE001
            pass
    return out


# --------------------------------------------------------------------------- cache
def cache_root():
    from vstudio.config import cache_dir
    return cache_dir("intake")


def _cache_get(root, key):
    p = os.path.join(root, f"{key}.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_put(root, key, facts):
    p = os.path.join(root, f"{key}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False)
    os.replace(tmp, p)


# --------------------------------------------------------------------------- public
def analyze(inputs, asr="sample", use_cache=True, language=None, max_files=MAX_FILES, echo=None):
    """-> analysis dict. asr: off | sample | full | auto (auto = sample; ``plan`` upgrades a video to full when the
    request selects content inside it)."""
    t0 = time.time()
    asr = "sample" if asr in (None, "auto") else asr
    root = cache_root()
    files, notes = walk(inputs, max_files=max_files)
    out_files, n_heavy, n_face_imgs = [], 0, 0
    for k, (fp, base) in enumerate(files):
        kind = kind_of(fp)
        st = os.stat(fp)
        rel = _relpath(fp, base) if base else os.path.basename(fp)
        entry = dict(id=f"f{k + 1}", path=fp, rel=rel, kind=kind, size=st.st_size)
        if kind == "other":
            entry["note"] = "not a media / text file (ignored)"
            out_files.append(entry)
            continue
        h = qhash(fp)
        entry["qhash"] = h[:16]
        mode = asr if kind in ("video", "audio") else "-"
        heavy = True
        if kind == "video":
            n_heavy += 1
            heavy = n_heavy <= HEAVY_VIDEOS
        faces = False
        if kind == "image":
            faces = n_face_imgs < FACE_IMAGES
            n_face_imgs += 1
        key = f"{h[:24]}.v{VERSION}.{kind}.{mode}.{'h' if heavy else 'l'}{'.f' if faces else ''}"
        facts = _cache_get(root, key) if use_cache else None
        if facts is not None and facts.get("transcript") and not os.path.exists(facts["transcript"]):
            facts = None
        cached = facts is not None
        if facts is None:
            if echo:
                echo(f"intake: analyzing {rel}")
            if kind in ("video", "audio"):
                facts = analyze_video(fp, mode, heavy, root, key, kind, language)
            elif kind == "image":
                facts = analyze_image(fp, faces)
            else:
                facts = D.analyze(fp)
            if not facts.get("note", "").startswith(("probe failed", "text extraction failed")):
                _cache_put(root, key, facts)
        entry.update(facts)
        entry["cached"] = cached
        out_files.append(entry)
    groups = _groups(out_files, files)
    tot = dict(videos=0, video_s=0.0, audio=0, audio_s=0.0, images=0, texts=0, other=0)
    for f in out_files:
        if f["kind"] == "video":
            tot["videos"] += 1
            tot["video_s"] += f.get("duration") or 0
        elif f["kind"] == "audio":
            tot["audio"] += 1
            tot["audio_s"] += f.get("duration") or 0
        elif f["kind"] == "image":
            tot["images"] += 1
        elif f["kind"] == "text":
            tot["texts"] += 1
        else:
            tot["other"] += 1
    tot["video_s"], tot["audio_s"] = round(tot["video_s"], 1), round(tot["audio_s"], 1)
    urls = []
    for f in out_files:
        for u in f.get("urls") or []:
            if u not in urls:
                urls.append(u)
    for f in out_files:
        if f.get("note") and ("not installed" in f["note"]):
            notes.append(f"{f['rel']}: {f['note']}")
    digest = hashlib.sha1(json.dumps(sorted((f["path"], f.get("qhash")) for f in out_files)).encode()).hexdigest()[:16]
    return dict(version=VERSION, kind="vstudio.intake.analysis", inputs=[os.path.abspath(os.path.expanduser(str(i)))
                                                                         for i in inputs],
                digest=digest, asr=asr, created=time.strftime("%Y-%m-%dT%H:%M:%S"), seconds=round(time.time() - t0, 1),
                totals=tot, files=out_files, groups=groups, urls=urls[:40], notes=notes)


def _groups(out_files, files):
    """Photos / clips that share a folder -> one group (the planner sees a set, not 300 lines)."""
    by = {}
    walked = {fp for fp, base in files if base}
    for f in out_files:
        if f["kind"] in ("image", "video") and f["path"] in walked:
            by.setdefault((os.path.dirname(f["path"]), f["kind"]), []).append(f)
    out = []
    for (d, kind), fs in sorted(by.items()):
        if len(fs) < 3:
            continue
        g = dict(id=f"g{len(out) + 1}", kind="photo-set" if kind == "image" else "clip-set", folder=d,
                 files=[f["id"] for f in fs], n=len(fs))
        if kind == "image":
            ts = sorted(f["taken"] for f in fs if f.get("taken"))
            if ts:
                g["taken"] = [ts[0], ts[-1]]
            g["with_gps"] = sum(1 for f in fs if f.get("gps"))
            fc = [f["faces"] for f in fs if f.get("faces") is not None]
            if fc:
                g["faces_share"] = round(sum(1 for c in fc if c) / len(fc), 2)
            g["orientation"] = statistics.mode([f.get("orientation") or "?" for f in fs])
        else:
            g["duration"] = round(sum(f.get("duration") or 0 for f in fs), 1)
            sp = [f.get("speech") for f in fs if f.get("speech") is not None]
            if sp:
                g["speech_share"] = round(sum(1 for s in sp if s) / len(sp), 2)
        out.append(g)
    return out


# --------------------------------------------------------------------------- compact view (for the planner / UI)
def material_role(f):
    """One-word role guess per file (the rule planner's input): call, screen-recording, talking-head, finished-edit,
    lecture, footage, podcast-audio, music, photo, script, slides, doc, subtitles, notes."""
    k = f["kind"]
    hints = set(f.get("name_hints") or [])
    if k == "video":
        dur = f.get("duration") or 0
        if f.get("multi_person") or ("call" in hints and f.get("speech") is not False):
            return "call"
        if f.get("screen_share") or "screen-recording" in hints:
            return "lecture" if (dur >= 900 or "lecture" in hints) and f.get("speech") is not False else "screen-recording"
        if f.get("speech") is False:
            return "footage"
        if f.get("burned_captions") or ("final-export" in hints and f.get("speech")):
            return "finished-edit"
        if f.get("talking_head"):
            return "lecture" if dur >= 1500 else "talking-head"
        if f.get("speech"):
            return "lecture" if dur >= 900 else "talking-head"
        return "footage"
    if k == "audio":
        if f.get("speech") is False:
            return "music"
        return "podcast-audio" if (f.get("duration") or 0) >= 300 else "voice"
    if k == "image":
        return "photo"
    if k == "text":
        sh = f.get("shape")
        return {"script": "script", "slides": "slides", "subtitles": "subtitles", "notes": "notes",
                "outline": "notes"}.get(sh, "doc")
    return "other"


def compact(analysis, max_files=60):
    """The analysis without paths' noise: what the LLM planner and the app's summary card read."""
    fs = []
    grouped = {fid for g in analysis.get("groups") or [] for fid in g["files"]}
    for f in analysis["files"]:
        if f["kind"] == "other":
            continue
        if f["id"] in grouped and f["kind"] == "image":
            continue
        c = dict(id=f["id"], file=f["rel"], kind=f["kind"], role=material_role(f))
        for k in ("duration", "orientation", "width", "height", "speech", "language", "talking_head", "multi_person",
                  "faces_median", "screen_share", "burned_captions", "name_hints", "speech_s", "sentences", "shape",
                  "pages", "slides", "chars", "title", "headings", "episodes", "excerpt", "taken", "note"):
            v = f.get(k)
            if v not in (None, [], "", {}):
                c[k] = v
        fs.append(c)
    return dict(totals=analysis["totals"], files=fs[:max_files], more_files=max(0, len(fs) - max_files),
                groups=analysis.get("groups") or [], urls=(analysis.get("urls") or [])[:10],
                notes=analysis.get("notes") or [])


def load_transcript(f):
    tp = f.get("transcript")
    if not tp or not os.path.exists(tp):
        return None
    with open(tp, encoding="utf-8") as fh:
        return json.load(fh)
