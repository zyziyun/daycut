"""The vstudio.batch plugin of projects: importing it registers one batch recipe per manifest (and per engine
variant): ``project:<id>`` or ``project:<id>@<batch recipe>``. A project's batch spec lists
``plugins: [vstudio.project.registry]``, so ``vstudio.batch`` (run / status / review / job edit / deliver / metrics)
works on ``<project>/state`` unchanged."""
from vstudio.batch import recipes as RC

from . import build as B
from . import manifests as M


def register_all():
    names = []
    for m in M.all_manifests().values():
        for batch in B.variants(m):
            name = B.recipe_name(m, batch)
            if name not in RC.REGISTRY:
                RC.register(B.build(m, batch))
            names.append(name)
    return names


register_all()
