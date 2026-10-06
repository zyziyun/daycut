// First-run assets (fonts, MediaPipe models, Whisper weights, Chromium): resumable (HTTP Range), sha256-verified, one
// group at a time in the background, with throttled progress callbacks. No Electron imports (unit-tested under Node).
//
// Locations are stable and shared: a group may have its own root (the fonts + models group lives in the engine's own
// cache, ~/.cache/video-studio, which the CLI skill uses too) and reuse folders that may already hold the exact files
// (the Hugging Face cache for Whisper). What is installed where is kept in <dir>/installed.json, so a restart only
// stats files - it never re-downloads or re-hashes.
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { groupsFor, safeRel, type AssetGroup, type AssetManifest, type AssetsStatusMsg } from '../shared/assets';

const MARKER = '.installed.json';
const RECORD = 'installed.json';

interface InstallRecord {
  root: string;
  sha256: string[];
  at: string;
  reused?: boolean;
}

export interface AssetManagerOpts {
  manifest: AssetManifest;
  dir: string;
  target?: string;
  onChange?: (s: AssetsStatusMsg) => void;
  /** the queue ran dry (every requested group installed, failed or cancelled) */
  onIdle?: (s: AssetsStatusMsg) => void;
  /** diagnostics (main process log file); never throws */
  log?: (msg: string) => void;
  fetchImpl?: typeof fetch;
  /** group id -> absolute root instead of <dir>/<group.root> (e.g. core -> the shared engine cache). Shared roots are
   * never wiped: files are added / replaced one by one. */
  roots?: Record<string, string>;
  /** Hugging Face hub folder (default $HF_HOME/hub or ~/.cache/huggingface/hub): groups whose files come from
   * huggingface.co are reused from its snapshots when the exact files are already there */
  hfHub?: string | null;
}

/**
 * Background download queue. `install(ids)` only enqueues and never throws: groups download one at a time while the
 * app keeps working; more groups can be queued while one is running; `cancel()` stops the current one and clears the
 * queue (`cancel(id)` drops one group). Nothing here touches windows, the engine or the app lifecycle.
 */
export class AssetManager {
  private groups: AssetGroup[];
  private progress = new Map<string, { received: number; total: number; file: string }>();
  private errors = new Map<string, string>();
  private queue: string[] = [];
  private current: { id: string; abort: AbortController } | null = null;
  private running: Promise<void> | null = null;
  private lastEmit = 0;
  private envAtStart: string;
  private record: Record<string, InstallRecord> = {};
  private scanning: Promise<void> | null = null;
  constructor(private o: AssetManagerOpts) {
    this.groups = groupsFor(o.manifest, o.target ?? `${process.platform}-${process.arch}`);
    try {
      this.record = JSON.parse(fs.readFileSync(path.join(o.dir, RECORD), 'utf8')) as Record<string, InstallRecord>;
    } catch {
      this.record = {};
    }
    this.envAtStart = JSON.stringify(this.env());
  }

  /** Where the group is installed (its record), else where it would be downloaded to. */
  root(g: AssetGroup) {
    const r = this.record[g.id];
    return r && this.recordOk(g, r) ? r.root : this.target(g);
  }

  /** Download destination of a group. */
  private target(g: AssetGroup) {
    return this.o.roots?.[g.id] ?? path.join(this.o.dir, safeRel(g.root));
  }

  private shared(g: AssetGroup) {
    return Boolean(this.o.roots?.[g.id]);
  }

  /** Cheap check (stat only): the record matches the manifest and every file is still there with its size. */
  private recordOk(g: AssetGroup, r: InstallRecord) {
    if (!g.files.every((f) => r.sha256.includes(f.sha256))) return false;
    if (g.extract) return fs.existsSync(r.root);
    return g.files.every((f) => {
      try {
        return fs.statSync(path.join(r.root, safeRel(f.dest))).size === f.size;
      } catch {
        return false;
      }
    });
  }

  installed(g: AssetGroup): boolean {
    const r = this.record[g.id];
    if (r && this.recordOk(g, r)) return true;
    try {
      // installs from before installed.json: a marker inside a private root
      const m = JSON.parse(fs.readFileSync(path.join(this.o.dir, safeRel(g.root), MARKER), 'utf8')) as { sha256: string[] };
      return g.files.every((f) => m.sha256.includes(f.sha256));
    } catch {
      return false;
    }
  }

  private saveRecord(g: AssetGroup, root: string, reused = false) {
    this.record[g.id] = { root, sha256: g.files.map((f) => f.sha256), at: new Date().toISOString(), ...(reused ? { reused } : {}) };
    fs.mkdirSync(this.o.dir, { recursive: true });
    const tmp = path.join(this.o.dir, `${RECORD}.tmp`);
    fs.writeFileSync(tmp, JSON.stringify(this.record, null, 1));
    fs.renameSync(tmp, path.join(this.o.dir, RECORD));
  }

  /** Folders that may already hold a group's exact files: its own target and Hugging Face snapshots. */
  private candidates(g: AssetGroup): string[] {
    const out = [this.target(g)];
    const hub = this.o.hfHub === undefined ? defaultHfHub() : this.o.hfHub;
    const m = g.files[0] && /^https:\/\/huggingface\.co\/([^/]+)\/([^/]+)\/resolve\//.exec(g.files[0].url);
    if (hub && m) {
      const snaps = path.join(hub, `models--${m[1]}--${m[2]}`, 'snapshots');
      try {
        for (const d of fs.readdirSync(snaps)) out.push(path.join(snaps, d));
      } catch {
        /* not in the cache */
      }
    }
    return out;
  }

  /** A file already on disk with the right content? Content-addressed blobs (HF cache: the blob name is its sha256)
   * are trusted by name; anything else is hashed once. */
  private async fileOk(file: string, f: { size: number; sha256: string }): Promise<boolean> {
    try {
      if (fs.statSync(file).size !== f.size) return false;
      if (path.basename(fs.realpathSync(file)) === f.sha256) return true;
      return (await sha256(file)) === f.sha256;
    } catch {
      return false;
    }
  }

  /**
   * Look for groups that are already on disk (the shared engine cache filled by the CLI's install.sh, the Hugging
   * Face cache) and record them as installed - nothing is copied or downloaded. Runs once in the background at start.
   */
  scan(): Promise<void> {
    this.scanning ??= (async () => {
      for (const g of this.groups) {
        if (g.extract || this.installed(g)) continue;
        for (const dir of this.candidates(g)) {
          if (!g.files.every((f) => fs.existsSync(path.join(dir, safeRel(f.dest))))) continue;
          let ok = true;
          for (const f of g.files) if (!(ok = await this.fileOk(path.join(dir, safeRel(f.dest)), f))) break;
          if (ok) {
            this.saveRecord(g, dir, dir !== this.target(g));
            this.o.log?.(`[assets] ${g.id} already on disk: ${dir}`);
            this.emit(true);
            break;
          }
        }
      }
    })().catch((e) => this.o.log?.(`[assets] scan failed: ${(e as Error)?.message ?? e}`));
    return this.scanning;
  }

  /** Engine env for installed groups (absolute paths). */
  env(): Record<string, string> {
    const env: Record<string, string> = {};
    for (const g of this.groups) {
      if (!g.env || !this.installed(g)) continue;
      const root = this.root(g);
      for (const [k, v] of Object.entries(g.env)) env[k] = v ? path.join(root, safeRel(v)) : root;
    }
    return env;
  }

  markEngineStarted() {
    this.envAtStart = JSON.stringify(this.env());
  }

  get busy(): boolean {
    return this.current !== null || this.queue.length > 0;
  }

  status(): AssetsStatusMsg {
    return {
      dir: this.o.dir,
      busy: this.busy,
      restartNeeded: JSON.stringify(this.env()) !== this.envAtStart,
      groups: this.groups.map((g) => ({
        id: g.id,
        required: g.required,
        installed: this.installed(g),
        bytes: g.files.reduce((a, f) => a + f.size, 0),
        licence: g.licence,
        progress: this.progress.get(g.id),
        queued: this.queue.includes(g.id) || undefined,
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
    try {
      this.o.onChange?.(this.status());
    } catch (e) {
      this.o.log?.(`[assets] onChange failed: ${(e as Error).message}`);
    }
  }

  /** Cancel the running group and everything queued, or only `id`. */
  cancel(id?: string) {
    this.o.log?.(`[assets] cancel ${id ?? 'all'}`);
    if (id && this.queue.includes(id)) {
      this.queue = this.queue.filter((x) => x !== id);
      this.emit(true);
      return;
    }
    if (!id) this.queue = [];
    if (this.current && (!id || this.current.id === id)) this.current.abort.abort();
    this.emit(true);
  }

  /** Queue groups (default: the missing required ones) and return at once; the promise resolves when the queue is
   * empty again. Already installed / queued / running groups are skipped. */
  install(ids?: string[]): Promise<AssetsStatusMsg> {
    const want = ids?.length ? this.groups.filter((g) => ids.includes(g.id)) : this.groups.filter((g) => g.required);
    this.o.log?.(`[assets] queue ${want.map((g) => g.id).join(', ') || '-'} (asked: ${ids?.join(', ') || 'required'})`);
    for (const g of want) {
      if (this.installed(g) || this.queue.includes(g.id) || this.current?.id === g.id) continue;
      this.errors.delete(g.id);
      this.queue.push(g.id);
    }
    this.emit(true);
    if (!this.running && this.queue.length) {
      this.running = this.drain().finally(() => {
        this.running = null;
      });
    }
    return (this.running ?? Promise.resolve()).then(() => this.status());
  }

  /** Resolves when nothing is queued or running. */
  idle(): Promise<void> {
    return this.running ?? Promise.resolve();
  }

  private async drain() {
    await this.scan(); // never download what is already on disk
    while (this.queue.length) {
      const id = this.queue.shift()!;
      const g = this.groups.find((x) => x.id === id);
      if (!g || this.installed(g)) continue;
      const abort = new AbortController();
      this.current = { id, abort };
      this.emit(true);
      try {
        await this.installGroup(g, abort.signal);
        this.o.log?.(`[assets] ${id} installed`);
      } catch (e) {
        const msg = abort.signal.aborted ? 'cancelled' : (e as Error)?.message ?? String(e);
        this.errors.set(id, msg);
        this.o.log?.(`[assets] ${id} failed: ${msg}`);
      } finally {
        this.progress.delete(id);
        this.current = null;
        this.emit(true);
      }
    }
    try {
      this.o.onIdle?.(this.status());
    } catch (e) {
      this.o.log?.(`[assets] onIdle failed: ${(e as Error).message}`);
    }
  }

  private async installGroup(g: AssetGroup, signal: AbortSignal) {
    const root = this.target(g);
    const staging = path.join(this.o.dir, '.downloads', g.id); // .part files survive restarts (resume)
    fs.mkdirSync(staging, { recursive: true });
    const total = g.files.reduce((a, f) => a + f.size, 0);
    let done = 0;
    const verified: { file: string; dest: string }[] = [];
    for (const f of g.files) {
      const rel = safeRel(f.dest);
      if (!g.extract && (await this.fileOk(path.join(root, rel), f))) {
        done += f.size; // already in place (e.g. a font the CLI installed): keep it
        continue;
      }
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
    // only now touch the real folder: a failed or cancelled download never leaves a half-installed group. A private
    // extract root is replaced as a whole; a shared root (the engine cache) only gets the verified files.
    if (g.extract && !this.shared(g)) fs.rmSync(root, { recursive: true, force: true });
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
    this.saveRecord(g, root);
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
    // a write error (disk full, folder removed) must reject this download, never surface as an uncaught 'error'
    let failed: Error | null = null;
    const onError = (e: Error) => {
      failed = e;
      out.emit('drain');
    };
    out.on('error', onError);
    let n = have;
    try {
      for await (const chunk of res.body as unknown as AsyncIterable<Uint8Array>) {
        if (failed) throw failed;
        if (!out.write(chunk)) await new Promise<void>((r) => out.once('drain', () => r()));
        if (failed) throw failed;
        n += chunk.length;
        if (n > size) throw new Error('download larger than expected');
        onBytes(n);
      }
    } finally {
      await new Promise<void>((r) => (out.destroyed ? r() : out.end(() => r())));
    }
    if (failed) throw failed;
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

/** The Hugging Face hub cache the Python side uses ($HF_HUB_CACHE, $HF_HOME/hub, ~/.cache/huggingface/hub). */
export function defaultHfHub(env = process.env): string {
  if (env.HF_HUB_CACHE) return env.HF_HUB_CACHE;
  return path.join(env.HF_HOME || path.join(os.homedir(), '.cache', 'huggingface'), 'hub');
}

/** The engine's own cache (vstudio config.CACHE): $VSTUDIO_CACHE, else ~/.cache/video-studio. Shared with the CLI. */
export function sharedEngineCache(env = process.env): string {
  return env.VSTUDIO_CACHE || path.join(os.homedir(), '.cache', 'video-studio');
}
