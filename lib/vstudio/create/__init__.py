"""vstudio.create - the Create page engine ("series studio"): formats -> series bible -> episode scripts ->
storyboard -> per-shot routing (cheapest-first) -> estimate + spend gate -> generation (fake / Kling MCP / MiniMax
Hailuo / Veo / 即梦 assisted) -> takes -> hand-off into the normal editor, languages and calendar. Plus the
recorder ingest (teleprompter recordings -> a talking-head project).

    python -m vstudio.create formats --json
    python -m vstudio.create plan --prompt "5-episode series ad for my matcha brand" --json
    python -m vstudio.create estimate EID --stage finals --json
    python -m vstudio.create run EID --stage finals --estimate ID --confirm CODE --max-cny 68 --json

Safety contract (costs.py / jobs.py): nothing is ever submitted to a paid service without an estimate, a
matching confirm code that has not expired, a max amount, the series budget and the monthly cap; a paid submit
is never retried (a timeout is recorded as ``unknown-charge`` and the user decides). Keys come from the
environment only (the desk puts them there from the OS keychain); they are never written to any file here.
Docs: references/CREATE.md.
"""
SCHEMA_VERSION = 1

__all__ = ["SCHEMA_VERSION"]
