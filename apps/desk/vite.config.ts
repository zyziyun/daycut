import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

// Renderer only; main + preload are bundled by scripts/build.mjs (esbuild).
export default defineConfig({
  root: resolve(import.meta.dirname, 'src/renderer'),
  base: './',
  plugins: [react()],
  server: { port: 5173, strictPort: true, host: 'localhost' },
  build: {
    outDir: resolve(import.meta.dirname, 'out/renderer'),
    emptyOutDir: true,
    target: 'chrome140',
    sourcemap: true,
  },
});
