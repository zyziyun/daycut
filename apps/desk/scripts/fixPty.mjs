// node-pty 1.1.0 ships its macOS spawn-helper without the executable bit (posix_spawnp failed). Restore it after
// npm install. Optional dependency: nothing to do when node-pty is not installed.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

// npm workspaces hoist node-pty to the monorepo's node_modules: resolve it instead of assuming apps/desk/node_modules
let dir = '';
try {
  dir = path.join(path.dirname(createRequire(import.meta.url).resolve('node-pty/package.json')), 'prebuilds');
} catch {
  /* not installed */
}
for (const arch of dir && fs.existsSync(dir) ? fs.readdirSync(dir) : []) {
  const helper = path.join(dir, arch, 'spawn-helper');
  try {
    if (fs.existsSync(helper)) fs.chmodSync(helper, 0o755);
  } catch {
    /* read-only install: the app falls back to `script` */
  }
}
