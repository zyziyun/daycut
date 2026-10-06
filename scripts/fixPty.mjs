// node-pty 1.1.0 ships its macOS spawn-helper without the executable bit (posix_spawnp failed). Restore it after
// npm install. Optional dependency: nothing to do when node-pty is not installed.
import fs from 'node:fs';
import path from 'node:path';

const dir = path.resolve(import.meta.dirname, '..', 'node_modules', 'node-pty', 'prebuilds');
for (const arch of fs.existsSync(dir) ? fs.readdirSync(dir) : []) {
  const helper = path.join(dir, arch, 'spawn-helper');
  try {
    if (fs.existsSync(helper)) fs.chmodSync(helper, 0o755);
  } catch {
    /* read-only install: the app falls back to `script` */
  }
}
