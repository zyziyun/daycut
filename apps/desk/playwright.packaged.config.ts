import { defineConfig } from '@playwright/test';

// Runs against the packaged app (npm run dist:mac:unsigned first). DESK_APP_PATH overrides the location.
// DESK_EDITION=mas: the sandboxed Mac App Store (Lite) build (npm run mas:local) - only tests/packaged/mas.spec.ts,
// whose profiles live inside the app's container (a sandboxed app cannot use the system temp dir).
const mas = process.env.DESK_EDITION === 'mas';
export default defineConfig({
  testDir: 'tests/packaged',
  ...(mas ? { testMatch: 'mas.spec.ts' } : { testIgnore: 'mas.spec.ts' }),
  timeout: 120000,
  workers: 1,
  reporter: 'list',
});
