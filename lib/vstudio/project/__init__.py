"""vstudio.project - every workflow as a recipe the desk app (or an agent) can drive generically.

A **project** is a folder holding N items of one recipe (a single video is N=1); under the hood it is a
``vstudio.batch`` batch (``<project>/state/``): the same SQLite store, resource-class scheduler, shared caches
(one ASR per source, one character reference set per series), pilot, resume, budgets and circuit breaker.

    python -m vstudio.project recipes --json                       # every recipe manifest + capabilities
    python -m vstudio.project new --recipe talkinghead --dir P --input video=a.mp4 --input video=b.mp4
    python -m vstudio.project run --dir P --json-events            # stops at checkpoints (exit 7 = needs you)
    python -m vstudio.project checkpoint --dir P --json            # pending checkpoint payloads
    python -m vstudio.project checkpoint --dir P --id filler --item a --answer '{"approve": [3, 5]}'
    python -m vstudio.project resume --dir P                       # after a crash / Ctrl-C / an answer
    python -m vstudio.project status|show|preview|export|context|refresh --dir P --json
    python -m vstudio.project series new|show|list ...; inbox [--json] / inbox answer; calendar ...

Modules: manifests (recipe.yaml loading + JSON Schema validation), build (manifest -> vstudio.batch Recipe with
checkpoint gate stages), registry (the batch plugin that registers ``project:<id>`` recipes), gates (checkpoint
payload / answer helpers), core (Project: new / plan / run / checkpoint / status / preview / export / context /
refresh), home (projects registry, series), inbox, calendar, adapters/ (thin per-workflow stage adapters around the
existing workflow scripts and lib APIs). Docs: references/PROJECTS.md.
"""


def touch(d, recipe=None, title=None, outputs=None, **kw):
    """Register a job folder for the desk app and report its live status (see works.touch)."""
    from .works import touch as _touch
    return _touch(d, recipe=recipe, title=title, outputs=outputs, **kw)
