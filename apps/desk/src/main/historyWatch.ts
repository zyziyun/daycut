// Live history: watch the watched roots (fs.watch, recursive on macOS / Windows) and tell the renderer when a job
// folder's live status / work record / batch lock changes - the 进行中 lane updates without polling. Only
// notifications travel; nothing is read here.
import fs from 'node:fs';
import path from 'node:path';

const INTERESTING = /(^|[\\/])\.vstudio[\\/](status|work)\.json$|(^|[\\/])(run\.lock|project\.yaml|batch\.db)$|(^|[\\/])final[\\/]/;

export function isInteresting(rel: string): boolean {
  return INTERESTING.test(rel);
}

export class HistoryWatcher {
  private watchers = new Map<string, fs.FSWatcher>();
  private timer: NodeJS.Timeout | null = null;

  constructor(
    private notify: () => void,
    private debounceMs = 400,
    private watchImpl: typeof fs.watch = fs.watch,
  ) {}

  /** Replace the watched set (max 20 existing absolute folders). -> the folders actually watched. */
  set(roots: string[]): string[] {
    const want = new Set(
      roots
        .slice(0, 20)
        .map((r) => path.resolve(r))
        .filter((r) => {
          try {
            return fs.statSync(r).isDirectory();
          } catch {
            return false;
          }
        }),
    );
    for (const [r, w] of this.watchers) {
      if (!want.has(r)) {
        w.close();
        this.watchers.delete(r);
      }
    }
    for (const r of want) {
      if (this.watchers.has(r)) continue;
      try {
        const w = this.watchImpl(r, { recursive: true, persistent: false }, (_ev, file) => {
          if (file && isInteresting(String(file))) this.ping();
        });
        w.on('error', () => {
          w.close();
          this.watchers.delete(r);
        });
        this.watchers.set(r, w);
      } catch {
        /* unwatchable folder: the list still refreshes on engine events */
      }
    }
    return [...this.watchers.keys()];
  }

  private ping() {
    if (this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.notify();
    }, this.debounceMs);
  }

  close() {
    for (const w of this.watchers.values()) w.close();
    this.watchers.clear();
    if (this.timer) clearTimeout(this.timer);
  }
}
