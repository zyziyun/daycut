// Production build: renderer with Vite, main + preload with esbuild (CJS; the sandboxed preload must be CJS).
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { build as esbuild } from 'esbuild';
import { build as vite } from 'vite';

// BUILD_EDITION=mas: the Mac App Store (Lite) build, see src/shared/edition.ts
export const EDITION = process.env.BUILD_EDITION === 'mas' ? 'mas' : 'full';

export const mainOptions = (extra = {}) => ({
  entryPoints: { 'main/index': 'src/main/index.ts', 'preload/index': 'src/preload/index.ts' },
  outdir: 'out',
  outExtension: { '.js': '.cjs' },
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node22',
  external: ['electron', 'node-pty'],
  sourcemap: true,
  logLevel: 'info',
  define: { __REELFOLD_EDITION__: JSON.stringify(EDITION) },
  ...extra,
});

// run as a script (not imported by dev.mjs): compare URLs, so Windows paths (D:\...) match too
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await vite({ configFile: 'vite.config.ts', mode: 'production' });
  await esbuild(mainOptions({ minify: false }));
}
