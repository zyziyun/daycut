// Mac App Store (Lite) build: the App Sandbox only lets the app read what the user picked. A pick in an open panel
// grants access for this launch; a security-scoped bookmark (Electron `securityScopedBookmarks`, MAS builds only)
// keeps it across launches. This store remembers one bookmark per picked file / folder in <userData>/access.json and
// starts accessing all of them at launch, before the engine sidecar starts. The engine (a child process with the
// inherited sandbox) then reads the same files - also files granted after it started: the sandbox extension a
// startAccessingSecurityScopedResource() call consumes belongs to the sandbox the parent and its children share
// (checked on macOS 26: docs/MAS.md "Sandbox checks").
// The full edition never uses this store: `active` is false and every call is a no-op.
import fs from 'node:fs';
import path from 'node:path';

export interface Grant {
  path: string;
  /** base64 security-scoped bookmark */
  bookmark: string;
  at: string;
}

export interface AccessApi {
  /** Electron app.startAccessingSecurityScopedResource (MAS builds only): -> the stop function */
  start?: (bookmark: string) => (() => void) | unknown;
}

/** `p` is `root` or inside it (both absolute; compared on path segments, case-sensitive). */
export function inside(p: string, root: string, sep = path.sep): boolean {
  const a = p.replace(/[\\/]+$/, '');
  const r = root.replace(/[\\/]+$/, '');
  return a === r || a.startsWith(r + sep);
}

export class AccessStore {
  private grants: Grant[] = [];
  private stops = new Map<string, () => void>();
  private readonly file: string;

  constructor(
    userData: string,
    private api: AccessApi,
    readonly active: boolean,
    private log: (m: string) => void = () => {},
  ) {
    this.file = path.join(userData, 'access.json');
    if (!active) return;
    try {
      const d = JSON.parse(fs.readFileSync(this.file, 'utf8')) as { grants?: Grant[] };
      this.grants = (d.grants ?? []).filter((g) => typeof g?.path === 'string' && typeof g?.bookmark === 'string' && g.bookmark);
    } catch {
      /* first launch */
    }
  }

  /** Start accessing every remembered bookmark (at launch). -> paths that resolved. */
  restore(): string[] {
    if (!this.active) return [];
    const ok: string[] = [];
    for (const g of this.grants) if (this.begin(g)) ok.push(g.path);
    this.log(`[access] ${ok.length}/${this.grants.length} remembered folders / files available`);
    return ok;
  }

  private begin(g: Grant): boolean {
    if (this.stops.has(g.path)) return true;
    try {
      const stop = this.api.start?.(g.bookmark);
      if (typeof stop === 'function') this.stops.set(g.path, stop as () => void);
      return true;
    } catch (e) {
      this.log(`[access] a bookmark no longer resolves (${(e as Error).message})`);
      return false;
    }
  }

  /** An open panel returned these paths and bookmarks (same order): remember + start accessing them. */
  add(paths: string[], bookmarks: (string | undefined)[] | undefined) {
    if (!this.active) return;
    let changed = false;
    paths.forEach((p, i) => {
      const bookmark = bookmarks?.[i];
      if (!bookmark) return;
      const g: Grant = { path: path.resolve(p), bookmark, at: new Date().toISOString() };
      this.stops.get(g.path)?.();
      this.stops.delete(g.path);
      this.grants = [...this.grants.filter((x) => x.path !== g.path), g];
      this.begin(g);
      changed = true;
    });
    if (changed) this.save();
  }

  /** Forget a grant (the user removed the watched folder). */
  remove(p: string) {
    if (!this.active) return;
    const r = path.resolve(p);
    this.stops.get(r)?.();
    this.stops.delete(r);
    const before = this.grants.length;
    this.grants = this.grants.filter((g) => g.path !== r);
    if (this.grants.length !== before) this.save();
  }

  /** The full edition reads anything; the Lite build only what is under a grant (or the app's own container). */
  covers(p: string, own: string[] = []): boolean {
    if (!this.active) return true;
    const r = path.resolve(p);
    return own.some((o) => inside(r, o)) || this.grants.some((g) => inside(r, g.path));
  }

  paths(): string[] {
    return this.grants.map((g) => g.path);
  }

  stopAll() {
    for (const stop of this.stops.values()) {
      try {
        stop();
      } catch {
        /* quitting */
      }
    }
    this.stops.clear();
  }

  private save() {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      const tmp = this.file + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify({ grants: this.grants }, null, 1));
      fs.renameSync(tmp, this.file);
    } catch (e) {
      this.log(`[access] could not save: ${(e as Error).message}`);
    }
  }
}

/** The folder to ask for so every one of `paths` is covered (their deepest common folder). */
export function commonFolder(paths: string[], sep = path.sep): string | null {
  if (!paths.length) return null;
  const parts = paths.map((p) => p.split(sep));
  const first = parts[0];
  let n = 0;
  while (n < first.length - 1 && parts.every((x) => x.length - 1 > n && x[n] === first[n])) n++;
  const out = first.slice(0, n).join(sep);
  return out || sep;
}
