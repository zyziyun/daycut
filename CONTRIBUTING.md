# Contributing to Reelfold

Thanks for helping. Reelfold is MIT-licensed and lives in one repository: the engine and Claude Code skill at the
root, the Mac app in `apps/desk`, the website in `apps/site` and the docs in `apps/docs`. Bug reports, platform
profiles, effects, translations and docs fixes are all welcome, and small pull requests are the easiest to merge.

The full guide, with the repo layout and how to add an effect or a platform, is on the docs site:
**[reelfold.com/docs/contributing](https://reelfold.com/docs/contributing/)**. This file is the short version.

## Ways to help

- **Try it on your own footage** and [open a bug report](https://github.com/zyziyun/reelfold/issues/new/choose) for
  whatever breaks. Say what you asked for, what you got, and attach a still or a short clip only if you have the
  rights to share it.
- **Pick a starter issue**: look for [`good first issue`](https://github.com/zyziyun/reelfold/labels/good%20first%20issue)
  and [`help wanted`](https://github.com/zyziyun/reelfold/labels/help%20wanted).
- **Add or fix a platform profile** (sizes, safe zones, caption limits, loudness): use the
  [platform request](https://github.com/zyziyun/reelfold/issues/new?template=platform_request.yml) form, then follow
  [the platform steps](https://reelfold.com/docs/contributing/#add-or-fix-a-platform-profile).
- **Translate** the docs, the website or the app. Partial translations are fine; untranslated pages fall back to English.
- **Ask or share** in [Discussions](https://github.com/zyziyun/reelfold/discussions).

## Set up

You need macOS on Apple Silicon for the app, Node 22+, Python 3.10+ and `ffmpeg`. The engine and its tests also run
on Linux.

```bash
git clone https://github.com/zyziyun/reelfold && cd reelfold
./install.sh && npm install
npm run desk          # the Mac app, with its engine running from this checkout's lib/
```

## Before you push

```bash
python3 -m pytest tests -q          # engine tests, synthetic media only
npm run lint && npm run test        # Mac app: eslint + tsc, vitest + engine bridge tests (if you touched apps/desk)
python3 scripts/check_skill.py      # repo checks: skill frontmatter, no personal paths, no secrets
```

`check_skill.py` must pass. It fails on absolute personal paths (`/Users/<name>/`), anything shaped like a committed
secret, and decorative emoji in the skill playbooks.

## Commit messages

One line in English, [Conventional Commits](https://www.conventionalcommits.org/) style, 72 characters at most:

```
type(scope): summary in the imperative, lower case, no period
```

- **type**: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`
- **scope** (optional): the area you touched, e.g. `engine`, `desk`, `site`, `docs`, `readme`, `skill`, `ci`, or a
  workflow / module name such as `talkinghead`, `platform`, `cleanup`
- Add a blank line and a body only when the why is not obvious from the diff.

Examples from the history:

```
feat(docs): add starlight docs site served at reelfold.com/docs
fix(docs): give docs home pages distinct titles
test(desk): clear DESK_PYTHON so first-run e2e uses the fake runtime
ci(desk): build signed, notarized mac release drafts on tags
```

## Pull requests

- One change per PR. Say what you tested and on what footage (synthetic media in `tests/` for anything the engine does).
- For a platform value, link the source and the date you checked it. Platforms change their UI often.
- For a visual change, attach a still or a contact sheet.
- Never commit API keys, personal paths, transcripts or footage you don't have the rights to. Your
  `persona.local.yaml` is git-ignored for this reason.
- If the change is user-facing, add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).

By contributing, you agree that your contribution is licensed under the [MIT licence](LICENSE) of the project, and you
agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through [SECURITY.md](SECURITY.md),
not public issues.
