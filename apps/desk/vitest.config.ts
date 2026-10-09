import { defineConfig } from 'vitest/config';

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify('0.0.0-test') },
  test: {
    include: ['tests/unit/**/*.test.ts'],
    environment: 'node',
    // a test's first dynamic import transforms a large part of the renderer; on a busy machine that alone can take
    // longer than vitest's 5 s default
    testTimeout: 30000,
  },
});
