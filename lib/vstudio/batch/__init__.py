"""vstudio.batch - batch video production (Fleet F0): plan -> estimate -> run -> review -> package.

    python -m vstudio.batch plan batch.yaml            # spec + job list -> jobs (+ variants) in batch-<name>/batch.db
    python -m vstudio.batch estimate                   # time / storage / API cost; `run` refuses over budget
    python -m vstudio.batch run --pilot 3              # 3 jobs end to end, then stop for review
    python -m vstudio.batch run --confirm-pilot        # the rest (resumable after a crash: just run again)
    python -m vstudio.batch status                     # terminal table
    python -m vstudio.batch review                     # review/index.html + review/decisions_needed.md
    python -m vstudio.batch review --apply decisions.json
    python -m vstudio.batch package --per-day 2        # publish folders + schedule.csv + confirmation code
    python -m vstudio.batch clean                      # drop regenerable intermediates of finished jobs

Modules: spec (spec / job rows / variants), planner (file | claude stub), recipes (registry, Stage, Recipe,
Ctx), stages (built-in recipes longform-slices, talkinghead-clips), lfsplit (recipe longform-split: the
longform-to-short split layout per job, privacy excludes), store (SQLite WAL), run (scheduler:
resource classes, resume, retries, circuit breaker, pilot), estimate (bench table, budget), qc (gates),
review (HTML grid, decisions), package (publish folders, schedule, manifest hash), hygiene (clean, du).
api (JSON views for UIs: recipes, review items, job detail, verify_manifest), lengthfit (max_len variants, length
suggestions).
Docs: references/BATCH.md, workflows/batch/WORKFLOW.md.
"""


def verify_manifest(manifest):
    """Recompute a package manifest's confirmation code -> dict(ok, code, stored, items, reason)."""
    from .api import verify_manifest as _v
    return _v(manifest)
