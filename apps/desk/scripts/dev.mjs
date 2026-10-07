// npm run dev: Vite dev server (renderer, HMR) + esbuild watch (main, preload) + Electron, restarted when
// main/preload change. A previous dev run of this repo that is still alive (port 5173 / its Electron) is stopped
// first through the pidfile it recorded (scripts/devLock.mjs) instead of failing with "Port 5173 is already in use".
// On macOS Electron runs from a cached Daycut.app copy so the menu bar / Dock / About say Daycut (scripts/devApp.mjs).
import { spawn } from 'node:child_process';
import path from 'node:path';
import { context } from 'esbuild';
import electronPath from 'electron';
import { createServer } from 'vite';
import { mainOptions } from './build.mjs';
import { devElectronBinary } from './devApp.mjs';
import { clearPidfile, pidfilePath, processGroup, takeOver, writePidfile } from './devLock.mjs';

const root = path.resolve(import.meta.dirname, '..');
const pidfile = pidfilePath(root);
const electronBin = devElectronBinary({ root, electronPath });
const { port } = await takeOver({ root, port: 5173, file: pidfile });
writePidfile(pidfile, { pid: process.pid, pgid: processGroup(process.pid), port, root, startedBy: 'dev.mjs' });

const server = await createServer({ configFile: 'vite.config.ts', mode: 'development', server: { port, strictPort: true } });
await server.listen();
const url = server.resolvedUrls.local[0].replace(/\/$/, '');
console.log(`[dev] renderer at ${url}`);

let child = null;
let restarting = false;
function launch() {
  child = spawn(electronBin, ['.'], {
    stdio: 'inherit',
    env: { ...process.env, VITE_DEV_SERVER_URL: url },
  });
  child.on('exit', (code) => {
    if (!restarting) {
      clearPidfile(pidfile);
      void server.close();
      process.exit(code ?? 0);
    }
  });
}

let quitting = false;
let ctx = null;
function quit(sig) {
  if (quitting) return;
  quitting = true;
  restarting = true; // the child's exit must not re-launch it
  clearPidfile(pidfile);
  try {
    child?.kill('SIGTERM');
  } catch {
    /* gone */
  }
  void Promise.allSettled([server.close(), ctx?.dispose()]).finally(() => process.exit(sig === 'SIGINT' ? 130 : 143));
  setTimeout(() => process.exit(1), 3000).unref();
}
process.on('SIGINT', () => quit('SIGINT'));
process.on('SIGTERM', () => quit('SIGTERM'));
process.on('exit', () => clearPidfile(pidfile));

ctx = await context(
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
