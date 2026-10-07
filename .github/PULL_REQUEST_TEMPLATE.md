## What and why

<!-- One change per PR. Link the issue: "Fixes #123". -->

## How I tested it

<!-- Commands you ran and on what footage. Engine changes: synthetic media in tests/. Visual changes: attach a still or contact sheet. -->

- [ ] `python3 -m pytest tests -q`
- [ ] `npm run lint && npm run test` (if `apps/desk` changed)
- [ ] `python3 scripts/check_skill.py`

## Checklist

- [ ] Commit messages follow `type(scope): summary` (see CONTRIBUTING.md)
- [ ] Platform values link a source and the date checked
- [ ] User-facing change noted under **Unreleased** in CHANGELOG.md
- [ ] Docs updated, or regenerated with `npm run gen -w apps/docs` (reference pages)
- [ ] No API keys, personal paths, transcripts or footage I don't have the rights to
