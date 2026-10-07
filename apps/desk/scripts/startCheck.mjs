// Start the built app (npm run build) headless with the mock engine and an isolated profile, print what the main
// process says for a while, then stop it. A quick "does it even start here?" check for a new platform / CI runner:
//   node scripts/startCheck.mjs [seconds=45]
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const secs = Number(process.argv[2] || 45);
const electron = createRequire(import.meta.url)('electron');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-start-'));
const profile = path.join(dir, 'profile');
const env = {
  ...process.env,
  DESK_ENGINE_MOCK: '1',
  DESK_USER_DATA: profile,
  VSTUDIO_HOME: path.join(dir, 'vhome'),
  DESK_SHARED_CACHE: path.join(dir, 'cache'),
  DESK_HF_HUB: '',
  DESK_HIDE_WINDOW: '1',
  DESK_SKIP_FIRST_RUN: '1',
  DESK_HISTORY_WATCH: '',
  VITE_DEV_SERVER_URL: '',
  ELECTRON_ENABLE_LOGGING: '1',
};
// 1) does Electron run JS here at all? a three-line app that prints and quits
const mini = path.join(dir, 'mini');
fs.mkdirSync(mini);
fs.writeFileSync(path.join(mini, 'package.json'), JSON.stringify({ name: 'mini', main: 'main.js' }));
fs.writeFileSync(path.join(mini, 'main.js'), "const { app } = require('electron'); console.log('mini: main ran', process.versions.electron); app.whenReady().then(() => { console.log('mini: ready'); app.quit(); });");
const m = spawnSync(electron, [mini, '--enable-logging=stderr'], { encoding: 'utf8', timeout: 30000, windowsHide: true, env: { ...process.env, ELECTRON_ENABLE_LOGGING: '1' } });
console.log(`[start-check] minimal app: status ${m.status} signal ${m.signal} error ${m.error?.message ?? '-'}\n${(m.stdout || '').slice(-2000)}\n${(m.stderr || '').slice(-3000)}`);

const t0 = Date.now();
const stamp = () => `+${((Date.now() - t0) / 1000).toFixed(1)}s`;
console.log(`[start-check] ${electron} ${ROOT} (profile ${profile})`);
const p = spawn(electron, [ROOT, '--enable-logging=stderr'], { env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
p.stdout.on('data', (b) => process.stdout.write(`${stamp()} [out] ${b}`));
p.stderr.on('data', (b) => process.stdout.write(`${stamp()} [err] ${b}`));
p.on('error', (e) => console.log(`${stamp()} spawn error: ${e.message}`));
p.on('exit', (code, sig) => console.log(`${stamp()} exited: code ${code} signal ${sig}`));
setTimeout(() => {
  console.log(`${stamp()} still running: ${p.exitCode === null && p.signalCode === null}`);
  try {
    console.log('profile:', fs.readdirSync(profile).join(', '));
    console.log(fs.readFileSync(path.join(profile, 'logs', 'main.log'), 'utf8'));
  } catch (e) {
    console.log(`(profile: ${e.message})`);
  }
  p.kill();
  setTimeout(() => process.exit(0), 2000);
}, secs * 1000);
