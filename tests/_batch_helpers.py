"""Test helpers for vstudio.batch: a fake recipe (no media, controllable timing / failures / crashes), a fake
transcriber for the real recipes, and synthetic media. Imported by tests/test_batch*.py and, as a spec
``plugins`` entry, by the `run` subprocess in the crash test (PYTHONPATH includes tests/)."""
import json
import os
import subprocess
import threading
import time

import numpy as np

from vstudio import audio
from vstudio.batch.recipes import Recipe, Stage, register
from vstudio.batch.run import TransientError

LOCK = threading.Lock()
STATE = dict(active={}, peak={}, calls=[])


def _log_call(ctx, name):
    path = os.path.join(ctx.batch_dir, "calls.log")
    with LOCK, open(path, "a") as f:
        f.write(f"{ctx.job['id']} {name}\n")
        f.flush()


def _ctl(ctx):
    return (ctx.spec.get("test") or {})


def _maybe_crash(ctx, name):
    c = os.environ.get("VSTUDIO_TEST_CRASH_AT", "")
    if c == f"{ctx.job['id']}:{name}":
        os._exit(9)


def make_stage_fn(name, res):
    def fn(ctx):
        _maybe_crash(ctx, name)
        ctl = _ctl(ctx)
        with LOCK:
            STATE["active"][res] = STATE["active"].get(res, 0) + 1
            STATE["peak"][res] = max(STATE["peak"].get(res, 0), STATE["active"][res])
        try:
            time.sleep(float(ctl.get("sleep", {}).get(name, 0.0)) +
                       float(ctl.get("sleep_job", {}).get(f"{ctx.job['id']}:{name}", 0.0)))
            fail = ctl.get("fail", {}).get(f"{ctx.job['id']}:{name}")
            if fail == "always":
                raise ValueError(f"deterministic failure in {name}")
            if fail == "once":
                marker = os.path.join(ctx.batch_dir, f"failed-once-{ctx.job['id']}-{name}")
                if not os.path.exists(marker):
                    open(marker, "w").close()
                    raise TransientError("HTTP 429 rate limited")
            out = os.path.join(ctx.dir, f"{name}.txt")
            with open(out, "w") as f:
                f.write(f"{ctx.job['id']} {name} {json.dumps(ctx.params.get('x'))}")
            res_out = dict(files=[out], value=ctx.params.get("x"))
            if name == "qc":
                red = ctx.params.get("red")
                res_out.update(status="red" if red else "green", reasons=["forced red"] if red else [], warnings=[],
                               sample=False)
            if name == "big":
                with open(os.path.join(ctx.dir, "big.bin"), "wb") as f:
                    f.write(b"\0" * 200000)
                res_out["files"].append(os.path.join(ctx.dir, "big.bin"))
            _log_call(ctx, name)                     # logged on completion: "calls" = finished executions
            return res_out
        finally:
            with LOCK:
                STATE["active"][res] -= 1
    return fn


def _units(job, spec):
    return float(job["params"].get("_dur") or 10.0)


def fake_expand(spec, rows):
    from vstudio.batch import spec as S
    return [dict(item=r["id"], params=dict(S.with_defaults(spec, r), _dur=float(r.get("dur", 10.0)),
                                           source=r.get("source") or (spec.get("inputs") or {}).get("source", "src-a")))
            for r in rows]


register(Recipe(
    name="test-fake", expand=fake_expand, description="fake stages for scheduler tests",
    stages=[
        Stage("probe", "io", make_stage_fn("probe", "io"), shared=True,
              params=lambda j, s: dict(src=j["params"]["source"]), units=lambda j, s: 1.0),
        Stage("asr", "asr", make_stage_fn("asr", "asr"), deps=("probe",), shared=True,
              params=lambda j, s: dict(src=j["params"]["source"]), units=_units),
        Stage("render", "cpu-render", make_stage_fn("render", "cpu-render"), deps=("asr",),
              params=lambda j, s: dict(x=j["params"].get("x")), units=_units),
        Stage("big", "cpu-render", make_stage_fn("big", "cpu-render"), deps=("render",), units=_units,
              purge=("*.bin",)),
        Stage("qc", "cpu", make_stage_fn("qc", "cpu"), deps=("big",),
              params=lambda j, s: dict(red=j["params"].get("red")), units=_units),
    ]))


def calls(batch_dir):
    p = os.path.join(batch_dir, "calls.log")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [tuple(ln.split()) for ln in f if ln.strip()]


# --------------------------------------------------------------------------- real-recipe helpers
FPS = 30


def synth_speech(words, sr=48000, lead=0.4, gap=0.12, seed=1):
    """[(text, dur)] -> (mono float32, truth words [{w, t, te}], freq table). Each word = a tone burst."""
    rng = np.random.default_rng(seed)
    t, ev, truth = lead, [], []
    for k, (text, dur) in enumerate(words):
        f = 300 + 37 * k
        ev.append((t, t + dur, f))
        truth.append(dict(w=text, t=round(t - 0.02, 3), te=round(t + dur - 0.02, 3), f=f))
        t += dur + gap
    n = int((t + 0.4) * sr)
    x = (3e-4 * rng.standard_normal(n)).astype(np.float32)
    ramp = int(0.008 * sr)
    for a, b, f in ev:
        i0, i1 = int(a * sr), int(b * sr)
        y = 0.25 * np.sin(2 * np.pi * f * np.arange(i1 - i0) / sr)
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp))
        y[:ramp] *= r
        y[-ramp:] *= r[::-1]
        x[i0:i1] += y.astype(np.float32)
    return x, truth, n / sr


def make_video(path, x, sr, dur, size="360x640", black=None):
    wav = path + ".wav"
    audio.write_wav(wav, np.stack([x, x], 1), sr)
    vf = "geq=lum='40+mod(N*7+X+Y\\,160)':cb=128:cr=128"
    if black:
        vf += f",drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,{black[0]},{black[1]})'"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"nullsrc=s={size}:r={FPS}", "-i", wav,
                    "-t", f"{dur:.3f}", "-vf", vf, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
                    "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", path], check=True)
    os.remove(wav)
    return path


def fake_transcriber(path, language=None, prompt=None):
    """Truth words for the source recording (env VSTUDIO_TEST_TRUTH); for a cleaned output, the words its
    cleanup sidecar says survived (out time) - i.e. a perfect ASR."""
    side = os.path.splitext(path)[0] + ".cleanup.json"
    if os.path.exists(side):
        with open(side, encoding="utf-8") as f:
            return [dict(w=w["w"], t=w["t"], te=w["te"]) for w in json.load(f)["words"]]
    with open(os.environ["VSTUDIO_TEST_TRUTH"], encoding="utf-8") as f:
        words = json.load(f)
    return dict(language="zh", segments=[dict(start=words[0]["t"], end=words[-1]["te"],
                                              text="".join(w["w"] for w in words),
                                              words=[dict(word=w["w"], start=w["t"], end=w["te"]) for w in words])])
