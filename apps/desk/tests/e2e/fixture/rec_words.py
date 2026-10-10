"""Test fixture (recordEdit e2e, real engine): the "transcriber" for Chromium's fake microphone (a beep, no speech):
words spread over the file, so the take, its automatic cleanup and the pickups have a transcript. A pickup (under an
edit folder's pickups/) says "pickup line"; the take says a short sentence with an "um"."""
import os
import subprocess

TAKE = ["hello", "everyone", "today", "we", "talk", "um", "about", "editing", "by", "text", "and", "pickups"]
PICK = ["pickup", "line"]


def _dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def words(path, language=None):
    d = _dur(path)
    ws = PICK if os.sep + "pickups" + os.sep in path else TAKE
    if d < 1.0:
        return []
    a, b = 0.3, max(0.6, d - 0.3)
    step = (b - a) / len(ws)
    return [dict(w=w, t=round(a + k * step, 3), te=round(a + k * step + step * 0.7, 3)) for k, w in enumerate(ws)]
