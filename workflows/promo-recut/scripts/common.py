"""Shared helpers for the promo-recut scripts: project config, paths, ffmpeg, whisper, time maps.

Every path in the project config is relative to the folder that holds the config file
(the "project dir"). Nothing here knows about any particular video.
"""
import json
import os
import shutil
import subprocess
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from vstudio.config import persona  # noqa: E402


# ---------------------------------------------------------------- config
class Project:
    def __init__(self, config_path):
        self.config_path = os.path.abspath(config_path)
        self.dir = os.path.dirname(self.config_path)
        self.cfg = load_config(self.config_path)
        self.work = self.p(self.cfg.get("work_dir", "work"))
        os.makedirs(self.work, exist_ok=True)

    def p(self, rel):
        """Absolute path for a config-relative path (absolute paths pass through)."""
        return rel if os.path.isabs(rel) else os.path.join(self.dir, rel)

    def w(self, name):
        return os.path.join(self.work, name)

    def get(self, dotted, default=None):
        cur = self.cfg
        for k in dotted.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur


def load_config(path):
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml
        return yaml.safe_load(txt) or {}
    return json.loads(txt)


def P(dotted, default=None):
    """persona lookup with a safe default, e.g. P('audio.loudness_lufs', -14)."""
    cur = persona()
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# ---------------------------------------------------------------- ffmpeg
def run(cmd):
    print("+", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "")
    subprocess.run([str(c) for c in cmd], check=True)


def need(tool):
    if not shutil.which(tool):
        sys.exit(f"'{tool}' not found on PATH")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def extract_wav(src, dst, sr=16000):
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", dst])


def read_wav(path):
    import wave
    import numpy as np
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        x = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    return x, sr


# ---------------------------------------------------------------- whisper
def transcribe(audio_path, language=None, model=None):
    """Word-timestamped transcript in openai-whisper JSON shape: {"segments": [{"words": [{word,start,end}]}]}.
    mlx_whisper (Apple Silicon) if importable, else faster_whisper."""
    language = language or P("creator.language", "zh")
    try:
        import mlx_whisper
        res = mlx_whisper.transcribe(audio_path, path_or_hf_repo=model or "mlx-community/whisper-large-v3-turbo",
                                     language=language, word_timestamps=True,
                                     condition_on_previous_text=False)
        return {"language": language, "text": res.get("text", ""),
                "segments": [{"start": s["start"], "end": s["end"], "text": s["text"],
                              "words": [{"word": w["word"], "start": w["start"], "end": w["end"],
                                         "probability": w.get("probability")} for w in s.get("words", [])]}
                             for s in res["segments"]]}
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("No whisper backend: pip install mlx-whisper (Apple Silicon) or faster-whisper")
    m = WhisperModel(model or "large-v3", compute_type="auto")
    segs, _ = m.transcribe(audio_path, language=language, word_timestamps=True, condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append({"start": s.start, "end": s.end, "text": s.text,
                    "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                              for w in (s.words or [])]})
    return {"language": language, "text": "".join(s["text"] for s in out), "segments": out}


def words_of(transcript):
    return [dict(w) for s in transcript["segments"] for w in s.get("words", [])]


# ---------------------------------------------------------------- time maps
def raw2cut(t, segmap):
    """raw recording second -> second in the cut file. segmap = [[raw_start, raw_end, cut_base], ...]."""
    for s, e, base in segmap:
        if t < s:
            return base
        if t <= e:
            return base + (t - s)
    s, e, base = segmap[-1]
    return base + (e - s)


def link_or_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        if os.path.getsize(dst) == os.path.getsize(src) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst
