// npm run dev: Vite dev server (renderer, HMR) + esbuild watch (main, preload) + Electron, restarted when
// main/preload change.
import { spawn } from 'node:child_process';
import { context } from 'esbuild';
import electronPath from 'electron';
import { createServer } from 'vite';
import { mainOptions } from './build.mjs';

const server = await createServer({ configFile: 'vite.config.ts', mode: 'development' });
await server.listen();
const url = server.resolvedUrls.local[0].replace(/\/$/, '');
console.log(`[dev] renderer at ${url}`);

let child = null;
let restarting = false;
function launch() {
  child = spawn(electronPath, ['.'], {
    stdio: 'inherit',
    env: { ...process.env, VITE_DEV_SERVER_URL: url },
  });
  child.on('exit', (code) => {
    if (!restarting) {
      void server.close();
      process.exit(code ?? 0);
    }
  });
}

const ctx = await context(
  mainOptions({
    logLevel: 'warning',
    plugins: [
      {
        name: 'restart-electron',
        setup(b) {
          b.onEnd((r) => {
            if (r.errors.length) return;
            if (child) {
              restarting = true;
              child.once('exit', () => {
                restarting = false;
                launch();
              });
              child.kill();
            } else {
              launch();
            }
          });
        },
      },
    ],
  }),
);
await ctx.watch();
