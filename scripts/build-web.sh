#!/usr/bin/env bash
# Build the website and the docs into ONE static folder for the site Worker (apps/site/wrangler.jsonc, assets ./dist):
#   apps/site/dist/          <- reelfold.com/
#   apps/site/dist/docs/     <- reelfold.com/docs  (apps/docs/dist, built with base /docs)
# Usage: scripts/build-web.sh            (from the repo root; then: cd apps/site && npx -y wrangler@4 deploy)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
npm run build -w apps/site
npm run build -w apps/docs
rm -rf apps/site/dist/docs
mkdir -p apps/site/dist/docs
cp -R apps/docs/dist/. apps/site/dist/docs/
echo "build-web: apps/site/dist (site) + apps/site/dist/docs (docs) ready"
