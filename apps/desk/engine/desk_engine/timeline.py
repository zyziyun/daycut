"""The clip editor's timeline media: a filmstrip sprite sheet + real audio peaks per output file (ffmpeg, made once
and cached in ``<DESK_DATA_DIR>/strips/<key>/``, never in the creator's folder), and 「听一遍这条片子」 — the
transcription of an output that has no transcript yet.

  GET  /api/outputs/<item>/<clip>/strip       -> {sprite, tile [w, h], cols, rows, n, interval, peaks, peaks_rate,
                                                  duration, has_audio}  (blocks while it is made: seconds)
  POST /api/outputs/<item>/<clip>/transcribe  -> {state: running | done, words?}; progress as ``output-transcribe``
  GET  /api/outputs/<item>/<clip>/transcribe  -> {state: idle | running | done | failed, error?, words?}

Transcription runs the engine's ``vstudio.asr.transcribe`` (cached by the engine as usual) in the engine's Python;
without the engine it fails and says so. The words are kept in ``<DESK_DATA_DIR>/transcripts/<key>.json`` (ASR
shape), which ``outputs._base`` reads first, so ``show`` returns them from then on.
"""
import array
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time

from .common import read_json, write_json

VERSION = 2
MAX_TILES = 240
TILE_H = 96
COLS = 12


def _ffmpeg():
    for p in (os.environ.get("DESK_FFMPEG"), shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    return None


def _key(path, extra=""):
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.realpath(path)}\0{st.st_mtime}\0{st.st_size}\0{VERSION}\0{extra}".encode()).hexdigest()[:20]


def transcript_path(data_dir, path):
    """Where the desk keeps a clip file's transcript (ASR shape) -> path (keyed by the file's identity)."""
    try:
        k = _key(path, "asr")
    except OSError:
        return None
    return os.path.join(data_dir, "transcripts", f"{k}.json")


def plan(duration, w, h):
    """Tile layout for a file: ~1 thumbnail per 0.5 s on short clips, at most MAX_TILES on long ones."""
    duration = max(0.1, float(duration or 0))
    interval = max(0.5, duration / MAX_TILES)
    n = max(1, min(MAX_TILES, int(math.ceil(duration / interval))))
    ar = (w / h) if w and h else 9 / 16
    tw = max(16, int(round(TILE_H * ar / 2)) * 2)
    rows = int(math.ceil(n / COLS))
    return dict(interval=round(interval, 4), n=n, tile=[tw, TILE_H], cols=COLS, rows=rows)


def peaks_from_pcm(samples, rate, per_sec):
    """16-bit mono samples -> peak per bucket (0..1, gently compressed so speech reads at a small height)."""
    step = max(1, int(rate / per_sec))
    out = []
    for i in range(0, len(samples), step):
        ch = samples[i:i + step]
        if not ch:
            break
        out.append(max(max(ch), -min(ch)))
    if not out:
        return []
    srt = sorted(out)
    ref = srt[min(len(srt) - 1, int(len(srt) * 0.995))] or max(srt) or 1
    return [round(min(1.0, (v / ref)) ** 0.7, 3) for v in out]


class Strips:
    def __init__(self, data_dir, outputs, history, bus=None):
        self.data_dir, self.outputs, self.history, self.bus = data_dir, outputs, history, bus
        self.dir = os.path.join(data_dir, "strips")
        self._locks = {}
        self._lock = threading.Lock()
        self._asr = {}                     # (item, clip) -> {state, error, words, at}

    # ---------------------------------------------------------------- routing
    def route(self, method, item, clip, verb):
        if verb == "strip" and method == "GET":
            return self.strip(item, clip)
        if verb == "transcribe" and method == "POST":
            return self.transcribe(item, clip)
        if verb == "transcribe" and method == "GET":
            return self.transcribe_state(item, clip)
        return None

    def _file(self, item, clip):
        _e, c = self.outputs._clip(item, clip)
        f = (c.get("files") or [None])[0]
        if not f or not f.get("path") or not os.path.exists(f["path"]):
            raise KeyError(f"clip {clip} has no file")
        return f

    # ---------------------------------------------------------------- filmstrip + peaks
    def strip(self, item, clip):
        f = self._file(item, clip)
        doc = self.build(f["path"], f.get("duration"), f.get("w"), f.get("h"))
        self.history.allow_media([doc["sprite"]] if doc.get("sprite") else [])
        return doc

    def build(self, path, duration=None, w=None, h=None):
        k = _key(path)
        with self._lock:
            lk = self._locks.setdefault(k, threading.Lock())
        with lk:
            d = os.path.join(self.dir, k)
            meta = read_json(os.path.join(d, "strip.json"), None)
            if isinstance(meta, dict) and meta.get("v") == VERSION and (not meta.get("sprite") or os.path.exists(meta["sprite"])):
                return meta
            from .outputs import probe
            info = probe(path) or {}
            duration = float(duration or info.get("duration") or 0)
            w, h = w or info.get("w"), h or info.get("h")
            p = plan(duration, w, h)
            os.makedirs(d, exist_ok=True)
            res = {}
            th = [threading.Thread(target=lambda: res.__setitem__("sprite", self._sprite(path, d, p, duration)), daemon=True),
                  threading.Thread(target=lambda: res.__setitem__("peaks", self._peaks(path, duration)), daemon=True)]
            for t in th:
                t.start()
            for t in th:
                t.join()
            peaks, rate = res.get("peaks") or ([], 0)
            meta = dict(p, v=VERSION, sprite=res.get("sprite"), duration=round(duration, 3), peaks=peaks,
                        peaks_rate=rate, has_audio=bool(peaks), w=w, h=h)
            write_json(os.path.join(d, "strip.json"), meta)
            return meta

    def _sprite(self, path, d, p, duration):
        ff = _ffmpeg()
        if not ff or not duration:
            return None
        out = os.path.join(d, "sprite.jpg")
        tw, tht = p["tile"]
        cmd = [ff, "-v", "error", "-y"]
        if duration > 600:
            cmd += ["-skip_frame", "nokey"]           # long outputs: keyframes are close enough at >= 2.5 s a tile
        cmd += ["-i", path, "-an", "-sn", "-dn", "-vf",
                f"fps=1/{p['interval']}:round=down,scale={tw}:{tht}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{tht},tile={p['cols']}x{p['rows']}", "-frames:v", "1", "-q:v", "5", out]
        try:
            subprocess.run(cmd, capture_output=True, timeout=600, stdin=subprocess.DEVNULL, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        return out if os.path.exists(out) else None

    def _peaks(self, path, duration):
        ff = _ffmpeg()
        if not ff:
            return [], 0
        per_sec = 50 if duration <= 300 else max(4, int(24000 / max(1, duration)))
        rate = 8000
        try:
            r = subprocess.run([ff, "-v", "error", "-i", path, "-vn", "-sn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                               capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return [], 0
        a = array.array("h")
        a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
        return peaks_from_pcm(a, rate, per_sec), per_sec

    # ---------------------------------------------------------------- transcription
    def transcribe_state(self, item, clip):
        st = self._asr.get((item, clip))
        return dict(st) if st else dict(state="idle")

    def transcribe(self, item, clip):
        cur = self._asr.get((item, clip))
        if cur and cur["state"] == "running":
            return dict(cur)
        f = self._file(item, clip)
        dest = transcript_path(self.data_dir, f["path"])
        st = dict(state="running", at=time.time())
        self._asr[(item, clip)] = st
        self._emit(item, clip, st)
        threading.Thread(target=self._run_asr, args=(item, clip, f, dest), daemon=True).start()
        return dict(st)

    def _emit(self, item, clip, st):
        if self.bus:
            self.bus.publish("output-transcribe", item=item, clip=clip, state=st["state"],
                             **({"error": st["error"]} if st.get("error") else {}),
                             **({"words": st["words"]} if st.get("words") is not None else {}))

    def _run_asr(self, item, clip, f, dest):
        try:
            words = self._words(f)
            if not words:
                raise RuntimeError("no speech heard")
            write_json(dest, dict(words=words, file=f["path"], at=time.time(), by="engine"))
            st = dict(state="done", words=len(words), at=time.time())
        except Exception as e:  # noqa: BLE001
            st = dict(state="failed", error=str(e)[:300], at=time.time())
        self._asr[(item, clip)] = st
        self._emit(item, clip, st)

    def _words(self, f):
        return self._engine_words(f["path"])

    def _engine_words(self, path):
        r = self.outputs.runner
        if r is None:
            raise RuntimeError("transcribing needs the video engine, which is not running")
        code = ("import json,sys\nfrom vstudio import asr\ntr=asr.transcribe(sys.argv[1])\n"
                "segs=[dict(s, words=asr.join_subwords(s.get('words') or [])) for s in tr['segments']]\n"
                "print(json.dumps(asr.words_of(dict(segments=segs)), ensure_ascii=False))")
        p = subprocess.run([r.python, "-c", code, path], capture_output=True, text=True, timeout=3600,
                           env=r.env, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or "transcription failed").strip().splitlines()[-1][:300])
        line = (p.stdout or "").strip().splitlines()[-1] if (p.stdout or "").strip() else "[]"
        return [dict(w=str(w["w"]), t=round(float(w["t"]), 3), te=round(float(w["te"]), 3)) for w in json.loads(line)]


_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(txt):
    out = []
    for block in re.split(r"\n\s*\n", txt.replace("\r", "")):
        m = _TS.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(block[m.end():].strip().splitlines()).strip()
        if text:
            out.append((a, b, text))
    return out


def tokens(text):
    """Latin words stay whole; CJK runs become 2-character words (roughly how whisper splits Chinese)."""
    out = []
    for part in re.findall(r"[A-Za-z0-9_.+#-]+|[㐀-鿿]+", text):
        if re.match(r"[㐀-鿿]", part):
            out += [part[i:i + 2] for i in range(0, len(part), 2)]
        else:
            out.append(part)
    return out
