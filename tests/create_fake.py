"""Fake Create services for tests (the engine tests and the desk's test engine; never part of the product or the
packaged app): a deterministic fake video provider that never touches the network, writes a short coloured clip
(ffmpeg) or a placeholder file and counts every submit (tests assert zero resubmits), and a fake AI that answers the
Create prompts from each format's own outline.

    install(**overrides)   every provider -> FakeProvider, the AI -> fake_ask, fast small masters, no ASR
    uninstall()            the real ones back
    real_ai()              keep the fake services but let the real (monkeypatched) vstudio.llm answer

    FakeProvider(info, fail={"u07"}, timeout={"u09"}, quote_factor=1.0, balance=1240)
"""
import inspect
import os
import re
import shutil
import subprocess
import threading
import time

from vstudio.create import formats as F
from vstudio.create.providers.base import Provider, SubmitTimeout

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


_UNSET = object()


class FakeProvider(Provider):
    poll_every = 0.05                     # jobs.py polls a provider every ``poll_every`` s

    def __init__(self, base_info, fail=(), timeout=(), reject=(), quote_factor=None, balance=_UNSET, delay=0.0,
                 pending_polls=0):
        self.info = dict(base_info, fake=True)
        if balance is _UNSET:
            balance = 1240 if base_info.get("id") == "kling-mcp" else None
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
        from vstudio.create import costs
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
        self.tasks[tid] = dict(unit=job.unit, dur=job.duration or 2, polls=0,
                               takes=int((job.extra or {}).get("fake_takes") or 1))
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
        return {"status": "done", "urls": [f"fake://{task_id}"] * t["takes"], "raw": {}}

    def download(self, url, path):
        tid = url.split("://", 1)[1]
        dur = (self.tasks.get(tid) or {}).get("dur") or 2
        return fake_clip(path, min(float(dur), 3.0), COLORS.get(self.id, "0x777777"))


# --------------------------------------------------------------------------- the fake AI
def rule_episode(fmt, bible, idea, lang):
    """Two shots per beat (a wide set-up + a closer reaction / line); repeated beats get a text card."""
    zh = str(lang).startswith("zh")
    cast = [c["id"] for c in bible.get("cast") or []] or ["A"]
    beats = []
    title = idea.get("title") or ""
    for i, b in enumerate(F.expand_beats(fmt, lang)):
        a = cast[i % len(cast)]
        other = cast[(i + 1) % len(cast)]
        line = (f"{b['label']}：{title}" if zh else f"{b['label']}: {title}")
        shots = [dict(camera="wide" if not zh else "全景", faces=[] if i % 3 == 0 else [a, other][:1 + (i % 2)],
                      action=(f"{b['label']} — {idea.get('logline') or title}"), dur=2.0, card=None, line=None)]
        if b.get("n"):
            shots.append(dict(camera="insert", faces=[], action=b["label"], dur=1.5, card=f"*{title}", line=None))
        else:
            shots.append(dict(camera="close" if not zh else "近景", faces=[a], action=line, dur=2.0, card=None,
                              line=line))
        beats.append(dict(beat=b["label"], lines=[dict(who=a, text=line)], shots=shots))
    return dict(beats=beats)


def _revised(bible, text):
    rules = {k: list(v) for k, v in (bible.get("rules") or {}).items()}
    key = "never" if re.match(r"^\s*(never|don'?t|no\b|不要|别|禁止|不能)", text, re.I) else "always"
    rules.setdefault(key, []).append(text)
    return dict(engine=bible.get("engine") or "", cast=[dict(c) for c in bible.get("cast") or []],
                always=rules.get("always") or [], never=rules.get("never") or [])


def _answer(fn, L):
    from vstudio.create import bible as BI
    if fn == "plan_series":
        d = BI.rules_draft(L["prompt"], L["f"], L["lang"], L["info"])
        return dict(format=L["f"]["id"], name=d["name"], engine=d["engine"], cast=d["cast"], always=d["always"],
                    never=d["never"], ideas=d["ideas"])
    if fn == "revise_bible":
        return _revised(L["bible"], L["text"])
    if fn == "more_ideas":
        return dict(ideas=BI.rule_ideas(L["f"], L["s"].get("name") or "", L["n"], start=len(L["have"]) + 1,
                                        lang=L["lang"]))
    if fn == "write":
        return rule_episode(L["fmt"], L["bible"], L["idea"], L["lang"])
    return None                                       # translate: lines stay as they are


ASKED = []                                            # every fake AI call (function name) - tests read it


def fake_ask(system, prompt, schema, **kw):
    """Answers like a model would, from the format's own outline (the caller's own data, read off its frame)."""
    for fr in inspect.stack()[1:]:
        mod = fr.frame.f_globals.get("__name__", "")
        if mod.startswith("vstudio.create.") and fr.function in ("plan_series", "revise_bible", "more_ideas", "write",
                                                                 "translate"):
            ASKED.append(fr.function)
            return _answer(fr.function, fr.frame.f_locals)
    return None


_saved = {}


def install(**overrides):
    """Fake services + fake AI + fast small masters + no ASR, in this process."""
    from vstudio.create import ai, handoff, jobs, providers as PR, record
    if not _saved:
        _saved.update(ask=ai.ask, provider=ai.provider, build_job=jobs.build_job,
                      transcript_words=record.transcript_words, master=(handoff.CANVAS, handoff.FPS, handoff.GRAIN))
    PR.set_fake(FakeProvider, **overrides)
    ai.ask = fake_ask
    ai.provider = lambda: "fake-ai"

    def build_job(ep, bible, unit):
        job = _saved["build_job"](ep, bible, unit)
        if unit.get("hard"):                         # a hard shot comes back with two takes to pick from
            job.extra = dict(job.extra or {}, fake_takes=2)
        return job
    jobs.build_job = build_job
    record.transcript_words = lambda *a, **k: None
    handoff.CANVAS, handoff.FPS, handoff.GRAIN = (360, 640), 24, 0


def real_ai():
    """The fake services stay; the AI is vstudio.llm again (tests monkeypatch ``llm.complete`` / ``llm.route``)."""
    from vstudio.create import ai
    if _saved:
        ai.ask, ai.provider = _saved["ask"], _saved["provider"]


def uninstall():
    from vstudio.create import ai, handoff, jobs, providers as PR, record
    PR.set_fake(None)
    if _saved:
        ai.ask, ai.provider = _saved["ask"], _saved["provider"]
        jobs.build_job = _saved["build_job"]
        record.transcript_words = _saved["transcript_words"]
        handoff.CANVAS, handoff.FPS, handoff.GRAIN = _saved["master"]
        _saved.clear()
