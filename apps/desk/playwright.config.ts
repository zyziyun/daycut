import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: process.platform === 'win32' ? 150000 : 60000, // the Windows runner is several times slower (hidden windows, no GPU)
  expect: { timeout: process.platform === 'win32' ? 15000 : 5000 }, // the same for an assertion's default wait
  workers: 1,
  reporter: 'list',
});
