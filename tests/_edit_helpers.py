"""Fake recipe ``test-edit-ops`` (the v0.2 fake stages + a cleanup stage that honours the row ``cuts``) and a fake
proofread LLM that counts its calls - for tests/test_edit_ops.py. No media, no network."""
import json
import os
import re

import _v02_helpers as V
from vstudio.batch import stages as ST
from vstudio.batch.recipes import Recipe, Stage, register
from vstudio.batch.util import write_json

CALLS = []          # one entry per LLM call: the caption lines it was sent


def fake_llm(system, prompt, model):
    """Proofread LLM: fixes every "RM" to "LLM"; records the caption lines of each call."""
    lines = [ln for ln in prompt.split("\n") if re.match(r"^\d+: ", ln)]
    CALLS.append(lines)
    fixes = []
    for ln in lines:
        i, _, text = ln.partition(": ")
        text = re.sub(r" \[(heard|unsure):.*$", "", text)
        if "RM" in text:
            fixes.append({"i": int(i), "from": "RM", "to": "LLM", "why": "sound-alike"})
    return json.dumps({"fixes": fixes}), {"input": 10, "output": 5}


def cleanup(ctx):
    p = ctx.params
    a, b = p.get("range") or [0, 60]
    from vstudio.batch.lfsplit import _cuts, _subtract
    ranges = _subtract(float(a), float(b), [c[:2] for c in _cuts(p.get("cuts"))])
    path = write_json(ctx.path("ranges.json"), ranges)
    V._log(ctx, "cleanup")
    return dict(ranges=ranges, files=[path])


def compose(ctx):
    out = V.compose(ctx)
    out["ranges"] = ctx.inputs["cleanup"]["ranges"]
    return out


register(Recipe(
    name="test-edit-ops", expand=V.expand, description="fake speech stages + a cleanup stage with row cuts",
    stages=[
        Stage("probe", "io", V.probe, shared=True, params=lambda j, s: dict(src=j["params"].get("source"))),
        Stage("asr", "asr", V.asr, deps=("probe",), shared=True,
              params=lambda j, s: dict(src=j["params"].get("source"), w=j["params"].get("words"))),
        Stage("cleanup", "cpu", cleanup, deps=("asr",),
              params=ST.cleanup_params("range", "cleanup_profile", optional=("cuts",))),
        Stage("compose", "cpu-render", compose, deps=("cleanup",),
              params=lambda j, s: dict(hook=j["params"].get("hook"), cues=j["params"].get("cues"))),
        Stage("proofread", "cpu", V.proofread, deps=("compose",), params=ST._proofread_params),
        Stage("export", "cpu-render", V.export, deps=("compose", "proofread"),
              params=lambda j, s: dict({k: j["params"].get(k) for k in ("platforms", "cover", "notes")},
                                       **({"caption_overrides": j["params"]["caption_overrides"]}
                                          if j["params"].get("caption_overrides") else {}))),
        Stage("qc", "cpu", V.qc, deps=("export",), params=lambda j, s: dict(title=j["params"].get("title"))),
        Stage("preview", "cpu", V.preview, deps=("export",)),
    ]))


def calls(batch_dir):
    return V.calls(batch_dir)


__all__ = ["fake_llm", "CALLS", "calls", "os"]
