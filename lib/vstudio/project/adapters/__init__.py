"""Thin per-workflow stage adapters. Signatures:

    stage fn       fn(env: build.Env) -> outputs dict (``files``, optional ``digest`` / ``cost_usd``)
    payload        payload(env, cp) -> {options, default, previews, digest?, skip?, ...}
    apply          apply(a: core.AnswerCtx) -> {params: {...}, project_params: {...}, digest?}
    collect        collect(project, job_row, stage_rows) -> [{platform, orientation, kind, file, cover, post}]

Adapters call the existing workflow scripts (subprocess, unchanged) or the lib APIs; they never re-implement a
workflow. ``common`` holds the shared ones (author / publish / filler / hook / cover checkpoints, batch exports).
"""
