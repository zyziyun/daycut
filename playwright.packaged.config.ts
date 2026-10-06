import { defineConfig } from '@playwright/test';

// Runs against the packaged app (npm run dist:mac:unsigned first). DESK_APP_PATH overrides the location.
export default defineConfig({
  testDir: 'tests/packaged',
  timeout: 120000,
  workers: 1,
  reporter: 'list',
});
