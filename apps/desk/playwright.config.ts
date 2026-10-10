import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: process.platform === 'win32' ? 150000 : 60000, // the Windows runner is several times slower (hidden windows, no GPU)
  workers: 1,
  reporter: 'list',
});
