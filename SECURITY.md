# Security policy

## Supported versions

Reelfold is pre-1.0. Security fixes go into `main` and the latest release only.

| Version | Supported |
|---|---|
| latest release / `main` | yes |
| anything older | no, please update |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

1. Use GitHub's private reporting: the repository's **Security** tab → **Report a vulnerability**
   ([direct link](https://github.com/zyziyun/reelfold/security/advisories/new)).
2. If that button is not available, open an issue that says only "I have a security report, how can I send it
   privately?", with no details, and the maintainer will set up a private channel.

Include what you can: the affected part (Mac app, engine / skill, website), the version or commit, steps to
reproduce, and the impact you expect. A proof of concept is welcome; please don't include anyone's real footage,
transcripts or keys.

What to expect: an acknowledgement within 7 days, an assessment and plan within 30 days, and credit in the release
notes if you want it. This is a one-maintainer project, so please allow some time before public disclosure; we will
agree a date with you.

## Scope

In scope, for example:

- The Mac app (`apps/desk`): IPC and preload boundaries, the local engine server and its token, stored API keys and
  logins, the `app://` and media protocols, the assisted-publish browser views, auto-update.
- The engine and Claude Code skill (`lib/`, `workflows/`, `scripts/`): command injection through file names or
  model output, path traversal, unsafe deserialisation.
- The release pipeline and anything that could ship a tampered build.

Out of scope: problems in third-party services or models Reelfold talks to (report those upstream), attacks that
need an already compromised Mac, and social-engineering reports.

## How Reelfold handles your data

Transcription and rendering run on your Mac. AI steps call the provider you choose (your Claude Code or Codex login,
your own API key, or a local model); what each step sends is listed in
[references/PROVIDERS.md](references/PROVIDERS.md). Reelfold never publishes for you: it fills in the upload page
and you press publish.
