# CI / CD

Everything ships from GitHub Actions; nobody deploys or builds a release by hand.

| Workflow | Runs on | Does |
|---|---|---|
| `deploy-web.yml` (Deploy web) | PRs and pushes to `main` touching the site, docs or the docs generator inputs; `release: published`; manual | Regenerates the docs reference pages from the engine, builds site + docs (`scripts/build-web.sh`), runs the site + docs checks and `check_skill`. On `main` / a published release / a manual run it then deploys to the Cloudflare Worker `reelfold-site` (reelfold.com) and smoke-tests `/`, `/zh/`, `/docs/`. PRs never deploy. |
| `desk-release.yml` (Desk release) | tag `v*`; manual (dry run by default) | Builds, signs, notarizes, staples and verifies the macOS arm64 app with `apps/desk/scripts/release-mac.sh`, then creates / updates a **draft** GitHub Release with the DMG, zip, blockmap, `latest-mac.yml` and release notes. Never publishes. |
| `site.yml`, `engine.yml`, `desk-ci.yml` | PRs and pushes | Checks only (site build, engine pytest, desk lint / unit / e2e). |

The website's download buttons follow the releases by themselves: the site build asks the GitHub API whether a
published release with a `.dmg` exists (`apps/site/src/lib/releaseStatus.ts`), and publishing a release triggers a
redeploy. Until the first release is published, the buttons say "Star on GitHub" / "Build from source".

## One-time setup (the maintainer, on her Mac)

Secrets are pasted at the `gh` prompt or piped from a file; they never go into a chat, a commit or a shell history.
`gh auth status` must show you logged in to github.com with the `repo` scope. Check what is set (names only) with
`gh secret list --repo zyziyun/reelfold`.

### 1. Cloudflare (website deploys)

1. dash.cloudflare.com → *My Profile* → *API Tokens* → **Create Token** → template **Edit Cloudflare Workers** →
   *Use template*.
   - Account Resources: *Include* → your account.
   - Zone Resources: *Include* → *Specific zone* → `reelfold.com`.
   - *Continue to summary* → *Create Token*, copy the token (shown once).
2. Account ID: dash.cloudflare.com → *Workers & Pages* → right column *Account ID* (or `npx wrangler whoami`).
3. Store both:
   ```bash
   gh secret set CLOUDFLARE_API_TOKEN --repo zyziyun/reelfold     # paste the token at the prompt
   gh secret set CLOUDFLARE_ACCOUNT_ID --repo zyziyun/reelfold    # paste the account ID
   ```
4. Test: GitHub → Actions → *Deploy web* → *Run workflow* (branch `main`). The *Deploy to Cloudflare* job should end
   with three `ok` smoke-test lines. If wrangler reports an authentication error about the custom domains, edit the
   token and add *Zone → DNS → Edit* for `reelfold.com`.

Until both secrets exist, the deploy job is skipped with a "Deploy skipped: missing secrets" warning; the build and
checks still run.

### 2. Apple (signed + notarized desk releases)

**Developer ID certificate (.p12)**

1. Keychain Access → *login* → *My Certificates* → right-click **Developer ID Application: <name> (<TEAMID>)** (the
   private key must be listed under it) → *Export…* → format *Personal Information Exchange (.p12)* → save as
   `cert.p12` → choose a strong password.
2. Store it:
   ```bash
   base64 -i cert.p12 | gh secret set MAC_CERT_P12_BASE64 --repo zyziyun/reelfold
   gh secret set MAC_CERT_PASSWORD --repo zyziyun/reelfold       # paste the .p12 password
   ```

**App Store Connect API key (notarization)**

1. appstoreconnect.apple.com → *Users and Access* → *Integrations* → *App Store Connect API* → *Team Keys* → **+**
   (the first time, the Account Holder has to click *Request Access*). Name `reelfold-notary`, access **Developer** →
   *Generate*.
2. Note the **Issuer ID** (above the table) and the **Key ID** (in the row), then *Download* the `AuthKey_<KEYID>.p8`
   (possible only once).
3. Store them:
   ```bash
   base64 -i AuthKey_XXXXXXXXXX.p8 | gh secret set APPLE_API_KEY_P8_BASE64 --repo zyziyun/reelfold
   gh secret set APPLE_API_KEY_ID --repo zyziyun/reelfold         # paste the Key ID
   gh secret set APPLE_API_ISSUER_ID --repo zyziyun/reelfold      # paste the Issuer ID
   ```

**Then delete the local copies**: `rm cert.p12 AuthKey_*.p8` (and empty the Trash if they went there). The
certificate stays in your keychain; a lost `.p8` is replaced by revoking the key and generating a new one.

Test without releasing: Actions → *Desk release* → *Run workflow* with *dry run* ticked. It builds, signs, notarizes
and verifies, and keeps the DMG as a workflow artifact (about 45 minutes, longer on the first run while the runtime
cache fills). Without the five secrets it stops in its first step and names the missing ones.

The local `npm run release:mac` keeps using the keychain identity and the `vstudio-notary` notarytool profile; it
switches to the API key only when `APPLE_API_KEY` (path to the `.p8`), `APPLE_API_KEY_ID` and `APPLE_API_ISSUER` are
all set (`DRY_RUN=1` checks either mode without building).

### 3. Optional: approve each website deploy

GitHub → *Settings* → *Environments* → `production` (created by the first deploy run) → *Required reviewers* → add
yourself. Every deploy then waits for a click on *Review deployments*. Leave it off for fully automatic deploys.

## How to release a new desk version

```bash
npm run version:bump -- 0.2.1                  # repo root: sets apps/desk/package.json (+ lock) to 0.2.1, no tag
git commit -am "chore(desk): release v0.2.1"
git push origin main
git tag v0.2.1 && git push origin v0.2.1       # starts Desk release
```

1. Optional, before tagging: write the notes in `apps/desk/release-notes/v0.2.1.md` (or a `## 0.2.1` section in
   `apps/desk/CHANGELOG.md`). Otherwise they are generated from the `feat` / `fix` / `perf` commits since the last tag.
2. Wait for *Desk release* (~45 min). A tag that does not match `apps/desk/package.json` fails at once.
3. GitHub → *Releases* → the draft `v0.2.1`: download the DMG, try it, edit the notes, **Publish release**.
4. Publishing starts *Deploy web*: a few minutes later reelfold.com shows "Download for macOS" (first release), and
   installed apps pick the update up within 6 hours.

A failed run can be re-run from the Actions page; a re-run on the same tag replaces the files in the draft. A
published release is never modified: bump the version instead.

## Auto-publish later (optional)

To skip the manual Publish click, in `.github/workflows/desk-release.yml` → *Create / update the DRAFT GitHub Release*:
drop `--draft` from `gh release create` and add `gh release edit "$TAG" --draft=false` after the update branch.
A release published by the workflow's own token does **not** trigger other workflows, so also add `actions: write` to
the job's permissions and a final step `gh workflow run deploy-web.yml --ref main` to refresh the website.

## Windows

The *windows* job in `desk-release.yml` is an experimental, unsigned build that only runs on a manual run with
*windows* ticked, never blocks the macOS release and is never attached to a release. Shipping it needs Windows code
signing (`apps/desk/docs/RELEASING.md` §3) and an upload step like the macOS one.
