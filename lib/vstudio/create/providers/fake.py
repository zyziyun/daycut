"""A deterministic fake provider for tests and the desk's mock mode: never touches the network, writes a short
coloured clip (ffmpeg testsrc) or a placeholder file, counts every submit (tests assert zero resubmits).

    FakeProvider("kling-mcp", fail={"u07"}, timeout={"u09"}, quote_factor=1.0, balance=1240)
"""
import os
import shutil
import subprocess
import threading
import time

from .base import Provider, SubmitTimeout

COLORS = {"kling-mcp": "0x0F7A6C", "minimax": "0xC2603A", "veo": "0x2F6AA6", "seedance-ark": "0x3D8FB0",
          "jimeng": "0x3D8FB0", "local-rapidmlx": "0x7C6BB0", "local-comfyui": "0x7C6BB0"}

SUBMITS = []            # every (provider, unit) submitted in this process - tests read it
_lock = threading.Lock()


def reset():
    with _lock:
        SUBMITS.clear()


def fake_clip(path, seconds=2.0, color="0x0F7A6C", size="180x320"):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    ff = shutil.which("ffmpeg")
    if ff:
        try:
            subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"color=c={color}:s={size}:r=24:d={max(0.5, float(seconds)):.2f}",
                            "-f", "lavfi", "-i", f"sine=frequency=330:duration={max(0.5, float(seconds)):.2f}",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                            "-c:a", "aac", path], check=True, timeout=60, capture_output=True)
            return path
        except (subprocess.SubprocessError, OSError):
            pass
    with open(path, "wb") as f:
        f.write(b"fake video")
    return path


class FakeProvider(Provider):
    def __init__(self, base_info, fail=(), timeout=(), reject=(), quote_factor=None, balance=None, delay=0.0,
                 pending_polls=0):
        self.info = dict(base_info, fake=True)
        self.fail, self.timeout, self.reject = set(fail), set(timeout), set(reject)
        self.quote_factor, self._balance, self.delay = quote_factor, balance, delay
        self.pending_polls = pending_polls
        self.tasks = {}
        self.submits = []

    def status(self):
        return dict(ready=True, code="create.provider.ready", params=dict(fake=True), balance=self._balance)

    def balance(self):
        return self._balance

    def quote(self, job):
        if self.quote_factor is None:
            return None
        from .. import costs
        p = costs.price_job(self.id, job.model, job.duration, job.resolution, kind=job.kind)
        return None if p["cny"] is None else round(p["cny"] * self.quote_factor, 2)

    def submit(self, job):
        with _lock:
            SUBMITS.append((self.id, job.unit))
        self.submits.append(job.unit)
        if self.delay:
            time.sleep(self.delay)
        if job.unit in self.timeout:
            raise SubmitTimeout("fake: no answer after the request was sent")
        if job.unit in self.reject:
            raise RuntimeError("fake: the service rejected the request (not charged)")
        tid = f"fake-{self.id}-{job.unit}-{len(self.submits)}"
        self.tasks[tid] = dict(unit=job.unit, dur=job.duration or 2, polls=0)
        return tid

    def poll(self, task_id):
        t = self.tasks.get(task_id)
        if not t:
            return {"status": "failed", "urls": [], "raw": {"error": "unknown task"}}
        t["polls"] += 1
        if t["polls"] <= self.pending_polls:
            return {"status": "pending", "urls": [], "raw": {}}
        if t["unit"] in self.fail:
            return {"status": "failed", "urls": [], "raw": {"error": "fake failure"}}
        return {"status": "done", "urls": [f"fake://{task_id}"], "raw": {}}

    def download(self, url, path):
        tid = url.split("://", 1)[1]
        dur = (self.tasks.get(tid) or {}).get("dur") or 2
        return fake_clip(path, min(float(dur), 3.0), COLORS.get(self.id, "0x777777"))
