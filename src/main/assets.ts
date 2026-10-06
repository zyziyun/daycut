// Downloads the large first-run assets into the app data dir: resumable (HTTP Range), sha256-verified, one group
// at a time, with throttled progress callbacks. No Electron imports so it can be unit-tested under Node.
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { groupsFor, safeRel, type AssetGroup, type AssetManifest, type AssetsStatusMsg } from '../shared/assets';

const MARKER = '.installed.json';

export interface AssetManagerOpts {
  manifest: AssetManifest;
  dir: string;
  target?: string;
  onChange?: (s: AssetsStatusMsg) => void;
  fetchImpl?: typeof fetch;
}

export class AssetManager {
  private groups: AssetGroup[];
  private progress = new Map<string, { received: number; total: number; file: string }>();
  private errors = new Map<string, string>();
  private abort: AbortController | null = null;
  private lastEmit = 0;
  private envAtStart: string;
  constructor(private o: AssetManagerOpts) {
    this.groups = groupsFor(o.manifest, o.target ?? `${process.platform}-${process.arch}`);
    this.envAtStart = JSON.stringify(this.env());
  }

  root(g: AssetGroup) {
    return path.join(this.o.dir, safeRel(g.root));
  }

  installed(g: AssetGroup): boolean {
    try {
      const m = JSON.parse(fs.readFileSync(path.join(this.root(g), MARKER), 'utf8')) as { sha256: string[] };
      return g.files.every((f) => m.sha256.includes(f.sha256));
    } catch {
      return false;
    }
  }

  /** Engine env for installed groups (absolute paths). */
  env(): Record<string, string> {
    const env: Record<string, string> = {};
    for (const g of this.groups) {
      if (!g.env || !this.installed(g)) continue;
      for (const [k, v] of Object.entries(g.env)) env[k] = v ? path.join(this.root(g), safeRel(v)) : this.root(g);
    }
    return env;
  }

  markEngineStarted() {
    this.envAtStart = JSON.stringify(this.env());
  }

  status(): AssetsStatusMsg {
    return {
      dir: this.o.dir,
      busy: this.abort !== null,
      restartNeeded: JSON.stringify(this.env()) !== this.envAtStart,
      groups: this.groups.map((g) => ({
        id: g.id,
        required: g.required,
        installed: this.installed(g),
        bytes: g.files.reduce((a, f) => a + f.size, 0),
        licence: g.licence,
        progress: this.progress.get(g.id),
        error: this.errors.get(g.id),
      })),
    };
  }

  missingRequired(): string[] {
    return this.groups.filter((g) => g.required && !this.installed(g)).map((g) => g.id);
  }

  private emit(force = false) {
    const now = Date.now();
    if (!force && now - this.lastEmit < 150) return;
    this.lastEmit = now;
    this.o.onChange?.(this.status());
  }

  cancel() {
    this.abort?.abort();
  }

  /** Install the given groups (default: missing required ones). Resolves when done; errors are per group. */
  async install(ids?: string[]): Promise<AssetsStatusMsg> {
    if (this.abort) throw new Error('a download is already running');
    const want = ids?.length ? this.groups.filter((g) => ids.includes(g.id)) : this.groups.filter((g) => g.required);
    this.abort = new AbortController();
    try {
      for (const g of want) {
        if (this.installed(g)) continue;
        this.errors.delete(g.id);
        try {
          await this.installGroup(g, this.abort.signal);
        } catch (e) {
          this.errors.set(g.id, this.abort.signal.aborted ? 'cancelled' : (e as Error).message);
          if (this.abort.signal.aborted) break;
        } finally {
          this.progress.delete(g.id);
        }
      }
    } finally {
      this.abort = null;
      this.emit(true);
    }
    return this.status();
  }

  private async installGroup(g: AssetGroup, signal: AbortSignal) {
    const root = this.root(g);
    const staging = path.join(this.o.dir, '.downloads', g.id);
    fs.mkdirSync(staging, { recursive: true });
    const total = g.files.reduce((a, f) => a + f.size, 0);
    let done = 0;
    const verified: { file: string; dest: string }[] = [];
    for (const f of g.files) {
      const rel = safeRel(f.dest);
      const part = path.join(staging, `${f.sha256}.part`);
      await this.fetchTo(f.url, part, f.size, signal, (n) => {
        this.progress.set(g.id, { received: done + n, total, file: path.basename(rel) });
        this.emit();
      });
      const got = await sha256(part);
      if (got !== f.sha256) {
        fs.rmSync(part, { force: true });
        throw new Error(`checksum mismatch for ${path.basename(rel)} (download corrupted or changed upstream)`);
      }
      done += f.size;
      verified.push({ file: part, dest: rel });
    }
    // only now touch the real folder: a failed or cancelled download never leaves a half-installed group
    fs.rmSync(root, { recursive: true, force: true });
    fs.mkdirSync(root, { recursive: true });
    for (const v of verified) {
      if (g.extract) {
        await extract(v.file, root);
        fs.rmSync(v.file, { force: true });
      } else {
        const dst = path.join(root, v.dest);
        fs.mkdirSync(path.dirname(dst), { recursive: true });
        fs.renameSync(v.file, dst);
      }
    }
    fs.writeFileSync(path.join(root, MARKER), JSON.stringify({ sha256: g.files.map((f) => f.sha256), at: new Date().toISOString() }));
    fs.rmSync(staging, { recursive: true, force: true });
  }

  private async fetchTo(url: string, file: string, size: number, signal: AbortSignal, onBytes: (n: number) => void) {
    let have = fs.existsSync(file) ? fs.statSync(file).size : 0;
    if (have > size) {
      fs.rmSync(file);
      have = 0;
    }
    if (have === size) return onBytes(have);
    const f = this.o.fetchImpl ?? fetch;
    const res = await f(url, { signal, redirect: 'follow', headers: have ? { Range: `bytes=${have}-` } : {} });
    if (!res.ok || !res.body) throw new Error(`download failed: HTTP ${res.status} for ${new URL(url).host}`);
    if (have && res.status !== 206) have = 0; // server ignored the range: start over
    const out = fs.createWriteStream(file, { flags: have ? 'a' : 'w' });
    let n = have;
    try {
      for await (const chunk of res.body as unknown as AsyncIterable<Uint8Array>) {
        if (!out.write(chunk)) await new Promise<void>((r) => out.once('drain', () => r()));
        n += chunk.length;
        if (n > size) throw new Error('download larger than expected');
        onBytes(n);
      }
    } finally {
      await new Promise<void>((r) => out.end(() => r()));
    }
    if (n !== size) throw new Error(`incomplete download (${n} of ${size} bytes)`);
  }
}

export function sha256(file: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    fs.createReadStream(file)
      .on('data', (d) => h.update(d))
      .on('error', reject)
      .on('end', () => resolve(h.digest('hex')));
  });
}

function extract(zip: string, dir: string): Promise<void> {
  // ditto keeps macOS bundle symlinks + permissions; Windows 10+ ships bsdtar as tar.exe (reads zip)
  const tar = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe');
  const [cmd, args] = process.platform === 'darwin' ? ['ditto', ['-x', '-k', zip, dir]] : [tar, ['-xf', zip, '-C', dir]];
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: 'ignore' });
    p.on('error', reject);
    p.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`))));
  });
}
