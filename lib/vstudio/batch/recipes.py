"""Recipe registry: a recipe = how a spec expands into jobs + the stage DAG every job runs.

    from vstudio.batch.recipes import Recipe, Stage, register

    register(Recipe(
        name="my-recipe",
        description="...",
        expand=lambda spec: [dict(item="a", params={...}), ...],     # spec -> job items (before variants)
        stages=[
            Stage("probe", "io", fn=probe, shared=True, params=lambda job, spec: {"src": job["params"]["source"]}),
            Stage("render", "cpu-render", fn=render, deps=("probe",), units=lambda job, spec: job["params"]["_dur"]),
        ]))

A stage function gets a ``Ctx`` (job, spec, dir to write into, outputs of its deps) and returns a JSON-able
dict of outputs; ``files`` (paths) are checked for existence on resume, ``digest`` (optional) feeds the keys of
downstream stages, ``cost_usd`` is booked against the budget. Stages must be idempotent: the scheduler wipes
``ctx.dir`` before each attempt and re-runs a stage only when its input key changed or its outputs vanished.

Built-in recipes (``vstudio.batch.stages``): ``longform-slices``, ``talkinghead-clips``; ``vstudio.batch.lfsplit``:
``longform-split``. Others plug in with
``plugins: [my_module]`` in the batch spec (the module calls ``register`` on import).
"""
import importlib
import os
from dataclasses import dataclass, field
from typing import Callable

REGISTRY = {}
DRAIN_STAGES = ("verify", "qc", "preview")


class Ctx:
    """What a stage function sees. ``inputs[dep]`` = that dep's output dict (``{}`` when it was skipped)."""

    def __init__(self, job, spec, dir, inputs, batch_dir):
        self.job, self.spec, self.dir, self.inputs, self.batch_dir = job, spec, dir, inputs, batch_dir
        self.params = job["params"]
        self.logs = []

    def path(self, *names):
        return os.path.join(self.dir, *names)

    def log(self, msg):
        self.logs.append(str(msg))


def _zero(job, spec):
    return 0.0


def _one(job, spec):
    return 1.0


def _empty(job, spec):
    return {}


def _yes(job, spec):
    return True


@dataclass
class Stage:
    name: str
    resource: object                     # "cpu-render" | callable(job, spec) -> str
    fn: Callable
    deps: tuple = ()
    shared: bool = False                 # outputs keyed by input hash in cache/, reused by every job with that key
    params: Callable = _empty            # (job, spec) -> dict: everything that changes the output (key input)
    units: Callable = _one               # (job, spec) -> float work units (media seconds) for the bench table
    cost: Callable = _zero               # (job, spec) -> estimated USD (API stages)
    enabled: Callable = _yes             # (job, spec) -> bool; disabled stages count as done ("skipped")
    version: int = 1                     # bump to invalidate old outputs
    retries: int = 2                     # transient-error retries (deterministic errors never retry)
    paid: bool = False                   # paid generation: never auto-resubmitted, even on transient errors
    purge: tuple = ()                    # glob patterns of regenerable outputs deleted by `clean`
    drain: object = None                 # cheap post-render stage that still runs for an already-started job
                                         # while the batch is paused (None: the name is in DRAIN_STAGES)

    def drains(self):
        return self.name in DRAIN_STAGES if self.drain is None else bool(self.drain)

    def resource_of(self, job, spec):
        return self.resource(job, spec) if callable(self.resource) else self.resource


@dataclass
class Recipe:
    name: str
    stages: list
    expand: Callable                     # spec -> [{"item": id, "params": {...}}]
    description: str = ""
    defaults: dict = field(default_factory=dict)
    label: str = ""                      # short UI name ("Lecture -> vertical slices")
    inputs: list = field(default_factory=list)   # [{key, label, kind file|dir|files|text|rects, required, accept, help}]
    row_keys: list = field(default_factory=list)  # job-row keys the recipe reads (beyond id / range / title ...)

    def meta(self):
        """JSON-able description for UIs (``recipes --json``): name, label, description, the inputs it needs,
        its job-row keys and its stage DAG."""
        return dict(name=self.name, label=self.label or self.name, description=self.description,
                    inputs=[dict(i) for i in self.inputs], row_keys=list(self.row_keys),
                    stages=[dict(name=s.name, deps=list(s.deps), shared=s.shared,
                                 resource=s.resource if isinstance(s.resource, str) else "dynamic")
                            for s in self.order()])

    def stage(self, name):
        return next(s for s in self.stages if s.name == name)

    def order(self):
        """Stages in dependency order (validated)."""
        names = {s.name for s in self.stages}
        done, out = set(), []
        pending = list(self.stages)
        while pending:
            progressed = False
            for s in list(pending):
                missing = [d for d in s.deps if d not in names]
                if missing:
                    raise ValueError(f"recipe {self.name}: stage {s.name} depends on unknown {missing}")
                if all(d in done for d in s.deps):
                    out.append(s)
                    done.add(s.name)
                    pending.remove(s)
                    progressed = True
            if not progressed:
                raise ValueError(f"recipe {self.name}: dependency cycle among {[s.name for s in pending]}")
        return out


def register(recipe):
    recipe.order()
    REGISTRY[recipe.name] = recipe
    return recipe


def load_plugins(plugins):
    for p in plugins or ():
        importlib.import_module(p)


def get(name, plugins=()):
    load_plugins(plugins)
    if name not in REGISTRY:
        from . import stages  # noqa: F401  (registers the built-in recipes)
    if name not in REGISTRY:
        raise KeyError(f"unknown recipe {name!r}; known: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]


def names(plugins=()):
    load_plugins(plugins)
    from . import stages  # noqa: F401
    return sorted(REGISTRY)
