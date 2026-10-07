import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

// Renderer only; main + preload are bundled by scripts/build.mjs (esbuild).
export default defineConfig({
  root: resolve(import.meta.dirname, 'src/renderer'),
  base: './',
  plugins: [react()],
  // Settings shows the app version (package.json) without an IPC round-trip
  // and which edition this is (BUILD_EDITION=mas: the Mac App Store build, src/shared/edition.ts)
  define: {
    __APP_VERSION__: JSON.stringify((JSON.parse(readFileSync(resolve(import.meta.dirname, 'package.json'), 'utf8')) as { version: string }).version),
    __REELFOLD_EDITION__: JSON.stringify(process.env.BUILD_EDITION === 'mas' ? 'mas' : 'full'),
  },
  server: { port: 5173, strictPort: true, host: 'localhost' },
  build: {
    outDir: resolve(import.meta.dirname, 'out/renderer'),
    emptyOutDir: true,
    target: 'chrome140',
    sourcemap: true,
  },
});
