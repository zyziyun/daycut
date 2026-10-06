"""vstudio.intake - natural language + any materials -> a plan of recipe projects (the desk app's "new batch").

The creator describes what she wants ("把后面对于自媒体的思考单独剪出来发小红书") and drops files / folders (video,
audio, photos, pdf / docx / pptx / md / srt). Intake inventories the materials, lets the routed model (task
``intake``) pick one or more recipes - mixed plans allowed - validates the result against the recipe manifests,
adds checkpoints and estimates, and creates the projects:

    python -m vstudio.intake analyze --inputs raw/ brief.pdf --json
    python -m vstudio.intake plan --prompt "把这节课切成 20 条竖屏" --inputs lesson.mp4 --json --out plan.json
    python -m vstudio.intake revise --plan plan.json --prompt "只要小红书" --in-place --json
    python -m vstudio.intake apply --plan plan.json [--out DIR] [--run] --json

Modules: inventory (walk + per-kind analyzers + cache), docs (text extraction), rules (phrase table, prompt
parsing, rule planner, focus matcher, rule revisions), plan (model call, validation, defaults, checkpoints,
estimates, summary, revise), estimate, apply (projects + series), cli. Docs: references/INTAKE.md.
"""
