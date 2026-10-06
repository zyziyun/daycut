// Production build: renderer with Vite, main + preload with esbuild (CJS; the sandboxed preload must be CJS).
import { build as esbuild } from 'esbuild';
import { build as vite } from 'vite';

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
  ...extra,
});

if (import.meta.url === `file://${process.argv[1]}`) {
  await vite({ configFile: 'vite.config.ts', mode: 'production' });
  await esbuild(mainOptions({ minify: false }));
}
