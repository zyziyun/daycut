// Transcript cuts of one clip (ux/text-edit §2.2, ux/fewer-steps): deleting words takes effect at once - the preview
// skips them straight away and they are saved to the engine by themselves a moment later (one step per burst of
// edits, in the background; AutoCommit below). Until then they are "drafts" here: word indices + tightened pauses,
// with their own undo / redo stack (⌘Z inside the burst), kept on this Mac per clip (localStorage) so leaving the
// clip, closing the window or restarting never loses them - the next open saves them.
import { useCallback, useEffect, useState } from 'react';
import { EMPTY_DRAFTS, type Drafts } from './transcript';

interface Stored {
  cur: Drafts;
  undo: Drafts[];
  redo: Drafts[];
}

const MAX = 100;
/** idle time after the last delete before the burst is saved as one step */
export const COMMIT_DELAY_MS = 1200;

export function draftKey(item: string, clip: string): string {
  return `ce.drafts.${item}/${clip}`;
}

export function loadDrafts(key: string, store: Pick<Storage, 'getItem'> = localStorage): Stored {
  try {
    const v = JSON.parse(store.getItem(key) ?? 'null') as Stored | null;
    if (v && v.cur && typeof v.cur.words === 'object' && Array.isArray(v.cur.gaps)) return { cur: v.cur, undo: v.undo ?? [], redo: v.redo ?? [] };
  } catch {
    /* a broken entry starts empty */
  }
  return { cur: EMPTY_DRAFTS, undo: [], redo: [] };
}

/** The drafts left after `done` went to the engine: what was deleted while that save ran stays. */
export function subtractDrafts(cur: Drafts, done: Drafts): Drafts {
  const words = Object.fromEntries(Object.entries(cur.words).filter(([i]) => !(i in done.words)));
  const gaps = cur.gaps.filter((g) => !done.gaps.includes(g));
  return { words, gaps };
}

export function draftsKey(d: Drafts): string {
  return JSON.stringify([Object.keys(d.words).map(Number).sort((a, b) => a - b), [...d.gaps].sort((a, b) => a - b)]);
}

type Action = { kind: 'set'; next: Drafts } | { kind: 'undo' } | { kind: 'redo' } | { kind: 'clear' } | { kind: 'committed'; done: Drafts };

/** The reducer behind useTextCuts (pure, unit-tested): set / undo / redo / clear / committed (a save went through:
 * those drafts are steps now, so ⌘Z goes to the engine's undo from here). */
export function step(s: Stored, a: Action): Stored {
  if (a.kind === 'set') return JSON.stringify(a.next) === JSON.stringify(s.cur) ? s : { cur: a.next, undo: [...s.undo, s.cur].slice(-MAX), redo: [] };
  if (a.kind === 'undo') return s.undo.length ? { cur: s.undo[s.undo.length - 1], undo: s.undo.slice(0, -1), redo: [...s.redo, s.cur] } : s;
  if (a.kind === 'redo') return s.redo.length ? { cur: s.redo[s.redo.length - 1], undo: [...s.undo, s.cur], redo: s.redo.slice(0, -1) } : s;
  if (a.kind === 'committed') return { cur: subtractDrafts(s.cur, a.done), undo: [], redo: [] };
  return { cur: EMPTY_DRAFTS, undo: [], redo: [] };
}

/** Writes the stored drafts of a clip (an unmounted editor whose last save finished: nothing to keep any more). */
export function storeCommitted(key: string, done: Drafts, store: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> = localStorage) {
  const s = step(loadDrafts(key, store), { kind: 'committed', done });
  if (!Object.keys(s.cur.words).length && !s.cur.gaps.length) store.removeItem(key);
  else store.setItem(key, JSON.stringify(s));
}

export function useTextCuts(key: string) {
  const [box, setBox] = useState<{ key: string; s: Stored }>(() => ({ key, s: loadDrafts(key) }));
  // another clip: its own drafts (never the previous clip's written under the new key)
  const s = box.key === key ? box.s : loadDrafts(key);
  useEffect(() => {
    if (box.key !== key) setBox({ key, s: loadDrafts(key) });
  }, [key, box.key]);
  useEffect(() => {
    if (box.key !== key) return;
    const v = box.s;
    const empty = !Object.keys(v.cur.words).length && !v.cur.gaps.length && !v.undo.length;
    if (empty) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify({ ...v, undo: v.undo.slice(-20), redo: v.redo.slice(-20) }));
  }, [box, key]);
  const apply = useCallback((a: Action) => setBox((b) => ({ key: b.key, s: step(b.s, a) })), []);
  const set = useCallback((f: (d: Drafts) => Drafts) => setBox((b) => ({ key: b.key, s: step(b.s, { kind: 'set', next: f(b.s.cur) }) })), []);
  const undo = useCallback(() => apply({ kind: 'undo' }), [apply]);
  const redo = useCallback(() => apply({ kind: 'redo' }), [apply]);
  const clear = useCallback(() => apply({ kind: 'clear' }), [apply]);
  const committed = useCallback((done: Drafts) => apply({ kind: 'committed', done }), [apply]);
  return { drafts: s.cur, set, undo, redo, clear, committed, canUndo: s.undo.length > 0, canRedo: s.redo.length > 0 };
}

interface Timers {
  set: (f: () => void, ms: number) => unknown;
  clear: (h: unknown) => void;
}

/**
 * Saves edits by itself (pure scheduling, unit-tested): every change re-arms one timer, so a burst of deletes becomes
 * ONE save after `delay` ms of quiet; one save runs at a time (what changes meanwhile is saved right after it); a
 * failed save is not retried by itself for the same edits (retry() or another edit does); flush() saves now (export,
 * ⌘↵, leaving the clip). `commit` resolves true when the engine took it (the caller removes those drafts before
 * resolving, so get() never hands the same edits out twice).
 */
export class AutoCommit<T> {
  private timer: unknown = null;
  private running: Promise<boolean> | null = null;
  private failed: string | null = null;
  private held = false;
  private dead = false;
  private timers: Timers;

  constructor(
    private o: {
      get: () => T;
      empty: (v: T) => boolean;
      key: (v: T) => string;
      commit: (v: T) => Promise<boolean>;
      delay: number;
      /** false: nothing to save now (e.g. less than a second would be left): wait for the next change */
      ready?: (v: T) => boolean;
      timers?: Timers;
    },
  ) {
    this.timers = o.timers ?? { set: (f, ms) => setTimeout(f, ms), clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) };
  }

  get busy(): boolean {
    return this.running != null;
  }

  /** The edits changed: (re)arm the save. */
  changed() {
    if (this.dead) return;
    this.cancel();
    const v = this.o.get();
    if (this.o.empty(v) || this.o.key(v) === this.failed) return;
    this.timer = this.timers.set(() => {
      this.timer = null;
      void this.tick();
    }, this.o.delay);
  }

  /** A selection drag (or anything else that is mid-gesture): no save until released. */
  hold(on: boolean) {
    this.held = on;
    if (!on) this.changed();
  }

  /** Save now; resolves true when nothing is left unsaved. */
  async flush(): Promise<boolean> {
    this.cancel();
    if (this.running) await this.running.catch(() => false);
    const v = this.o.get();
    if (this.o.empty(v)) return true;
    if (this.o.ready && !this.o.ready(v)) return false;
    return this.run(v, true);
  }

  /** The error's Retry. */
  retry(): Promise<boolean> {
    this.failed = null;
    return this.flush();
  }

  dispose() {
    this.cancel();
    this.dead = true;
  }

  private cancel() {
    if (this.timer != null) this.timers.clear(this.timer);
    this.timer = null;
  }

  private async tick() {
    if (this.dead || this.held || this.running) return; // a running save re-arms when it ends
    const v = this.o.get();
    if (this.o.empty(v) || this.o.key(v) === this.failed || (this.o.ready && !this.o.ready(v))) return;
    await this.run(v, false);
  }

  private async run(v: T, explicit: boolean): Promise<boolean> {
    const p = this.o.commit(v).catch(() => false);
    this.running = p;
    const ok = await p;
    this.running = null;
    this.failed = ok ? null : this.o.key(v);
    if (ok && !this.dead) {
      const rest = this.o.get();
      if (!this.o.empty(rest)) {
        if (explicit) return this.flush();
        this.changed();
      }
    }
    return ok;
  }
}
