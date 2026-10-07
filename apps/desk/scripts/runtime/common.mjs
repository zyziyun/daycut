// Shared helpers for the engine-runtime scripts (lock.mjs, bundle.mjs). Node >= 20, no dependencies.
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const LOCK_FILE = path.join(ROOT, 'packaging', 'runtime.lock.json');
export const CACHE = process.env.DESK_BUILD_CACHE || path.join(ROOT, 'build', '.cache');
// The engine (vstudio library, workflows, SKILL.md) is this monorepo's root: apps/desk -> ../.. ($VSTUDIO_ENGINE_SRC overrides).
export const ENGINE_ROOT = path.resolve(process.env.VSTUDIO_ENGINE_SRC || path.join(ROOT, '..', '..'));

/** Commit of the engine checkout (+ "-dirty" when lib/ workflows/ references/ or requirements.txt have local changes). */
export function engineCommit() {
  if (!fs.existsSync(path.join(ENGINE_ROOT, 'lib', 'vstudio'))) throw new Error(`no engine at ${ENGINE_ROOT} (expected lib/vstudio)`);
  const git = (args) => spawnSync('git', ['-C', ENGINE_ROOT, ...args], { encoding: 'utf8' });
  const head = git(['rev-parse', 'HEAD']);
  if (head.status !== 0) return 'unknown';
  const dirty = git(['status', '--porcelain', '--', 'lib', 'workflows', 'references', 'requirements.txt', 'SKILL.md']).stdout.trim();
  return head.stdout.trim() + (dirty ? '-dirty' : '');
}

export function readLock() {
  return JSON.parse(fs.readFileSync(LOCK_FILE, 'utf8'));
}

export function writeLock(lock) {
  fs.writeFileSync(LOCK_FILE, JSON.stringify(lock, null, 2) + '\n');
}

/** "darwin-arm64" | "darwin-x64" | "win32-x64": --target=..., $DESK_TARGET, else the host. */
export function targetFromArgs(argv = process.argv) {
  const a = argv.find((x) => x.startsWith('--target='));
  return (a && a.slice(9)) || process.env.DESK_TARGET || `${process.platform}-${process.arch}`;
}

export function arg(name, argv = process.argv) {
  const a = argv.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : undefined;
}

// Windows: always the system bsdtar (handles .zip and drive letters); Git Bash's GNU tar would read "C:" as a host
export const TAR = process.platform === 'win32' ? path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe') : 'tar';

export function log(...m) {
  console.log('[runtime]', ...m);
}

export function run(cmd, args, opts = {}) {
  if (!opts.quiet) log('$', cmd, args.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(' '));
  const r = spawnSync(cmd, args, { stdio: opts.capture ? ['ignore', 'pipe', 'inherit'] : 'inherit', encoding: 'utf8', ...opts });
  if (r.error) throw r.error;
  if (r.status !== 0 && !opts.allowFail) throw new Error(`${cmd} exited with ${r.status}`);
  return r.stdout;
}

export function sha256File(file) {
  const h = crypto.createHash('sha256');
  const fd = fs.openSync(file, 'r');
  const buf = Buffer.alloc(1 << 20);
  let n;
  while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0) h.update(buf.subarray(0, n));
  fs.closeSync(fd);
  return h.digest('hex');
}

/** Download url -> dest (cached by checksum); verifies sha256 when given. Returns dest. */
export async function download(url, dest, sha256) {
  if (fs.existsSync(dest) && (!sha256 || sha256File(dest) === sha256)) return dest;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  log('download', url);
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok || !res.body) throw new Error(`GET ${url}: ${res.status}`);
  const tmp = `${dest}.part`;
  const out = fs.createWriteStream(tmp);
  for await (const chunk of res.body) out.write(chunk);
  await new Promise((r, j) => out.end((e) => (e ? j(e) : r())));
  if (sha256) {
    const got = sha256File(tmp);
    if (got !== sha256) {
      fs.rmSync(tmp, { force: true });
      throw new Error(`checksum mismatch for ${url}\n  want ${sha256}\n  got  ${got}`);
    }
  }
  fs.renameSync(tmp, dest);
  return dest;
}

export function pbsUrl(lock, target) {
  const t = lock.targets[target];
  const { version, release, flavor } = lock.python;
  return `https://github.com/astral-sh/python-build-standalone/releases/download/${release}/cpython-${version}+${release}-${t.pbs}-${flavor}.tar.gz`;
}

export function micromambaUrl(lock, target) {
  return `https://github.com/mamba-org/micromamba-releases/releases/download/${lock.micromamba.version}/micromamba-${lock.targets[target].conda}`;
}

export async function micromamba(lock, target) {
  // micromamba runs on the build host; for cross-target locking only the host binary is needed.
  const host = `${process.platform}-${process.arch}`;
  const exe = path.join(CACHE, `micromamba-${lock.micromamba.version}-${host}${process.platform === 'win32' ? '.exe' : ''}`);
  await download(micromambaUrl(lock, host), exe, lock.micromamba.sha256[host]);
  fs.chmodSync(exe, 0o755);
  void target;
  return exe;
}

export function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}
