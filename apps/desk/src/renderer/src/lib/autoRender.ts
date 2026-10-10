// Every change to a clip (a cut in the transcript, its cover, caption style or text, an effect) re-renders it in the
// background, so what goes out is what she sees: no 「重新导出」. Bursts coalesce (one render after the last change; a change
// while one runs = one more render after it, never a queue), and the progress is there to see.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { OutputDoc } from '../../../shared/v04';
import { useEngine } from './engine';

export type RenderPhase = 'idle' | 'waiting' | 'running' | 'done' | 'failed';
export interface RenderState {
  phase: RenderPhase;
  /** 0..1 over every target of the render */
  progress: number;
  error?: string;
}

/** The clip's edit as it stands (every step, undone or not): when it changes, the clip is rendered again. */
export function editKey(d: Pick<OutputDoc, 'steps' | 'undo' | 'redo'>): string {
  return JSON.stringify([(d.steps ?? []).map((x) => [x.id, !!x.reverted]), d.undo ?? 0, d.redo ?? 0]);
}

/** Every target already has a final render of this edit: nothing to do. */
export function upToDate(d: Pick<OutputDoc, 'renders' | 'exports'>): boolean {
  const fresh = new Set((d.renders ?? []).filter((r) => r.fresh && !r.simulated && (r.quality ?? 'final') === 'final').map((r) => r.target));
  return renderTargets(d).every((tg) => fresh.has(tg));
}

/** The render's targets: the clip itself and every version it has. */
export function renderTargets(d: Pick<OutputDoc, 'exports'>): string[] {
  return ['primary', ...new Set((d.exports ?? []).map((x) => x.target))];
}

export interface RenderEvent {
  job?: string;
  event?: string;
  target?: string;
  stage?: string;
  progress?: number;
  error?: string;
}

const STAGES = ['canvas', 'timeline', 'audio', 'final'];

/** One background render at a time per clip: request() after a change (debounced), events in, state out. */
export class RenderQueue {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private job: string | null = null;
  private starting = false;
  private again = false;
  private n = 1;
  private done = new Set<string>();
  private cur = 0;
  state: RenderState = { phase: 'idle', progress: 0 };

  constructor(
    private o: {
      start: () => Promise<{ job: string; targets: number } | null>;
      onState: (s: RenderState) => void;
      delay?: number;
      setTimer?: (f: () => void, ms: number) => ReturnType<typeof setTimeout>;
      clearTimer?: (t: ReturnType<typeof setTimeout>) => void;
    },
  ) {}

  private set(s: RenderState) {
    this.state = s;
    this.o.onState(s);
  }

  get busy(): boolean {
    return this.job != null || this.starting;
  }

  /** a change: render after `delay` of quiet; while a render runs, once more after it */
  request() {
    if (this.busy) {
      this.again = true;
      return;
    }
    const clear = this.o.clearTimer ?? clearTimeout;
    const set = this.o.setTimer ?? setTimeout;
    if (this.timer) clear(this.timer);
    this.set({ phase: 'waiting', progress: 0 });
    this.timer = set(() => {
      this.timer = null;
      void this.run();
    }, this.o.delay ?? 2500);
  }

  private async run() {
    this.starting = true;
    this.again = false;
    this.done = new Set();
    this.cur = 0;
    this.set({ phase: 'running', progress: 0.02 });
    try {
      const r = await this.o.start();
      if (!r) return this.set({ phase: 'idle', progress: 0 });
      this.job = r.job;
      this.n = Math.max(1, r.targets);
    } catch (e) {
      this.set({ phase: 'failed', progress: 0, error: (e as Error).message });
    } finally {
      this.starting = false;
    }
  }

  event(e: RenderEvent) {
    if (!this.job || e.job !== this.job) return;
    if (e.event === 'target-start') this.cur = 0.03;
    else if (e.event === 'stage-done') this.cur = e.progress ?? (STAGES.indexOf(e.stage ?? '') + 1) / STAGES.length;
    else if (e.event === 'target-done' && e.target) {
      this.done.add(e.target);
      this.cur = 0;
    }
    const end = e.event === 'render-done' || e.event === 'failed' || e.event === 'stopped';
    if (!end) return this.set({ phase: 'running', progress: Math.min(0.99, (this.done.size + this.cur) / this.n) });
    this.job = null;
    if (this.again) {
      this.again = false;
      return this.request();
    }
    this.set(e.event === 'render-done' ? { phase: 'done', progress: 1 } : e.event === 'failed' ? { phase: 'failed', progress: 0, error: e.error } : { phase: 'idle', progress: 0 });
  }

  dispose() {
    if (this.timer) (this.o.clearTimer ?? clearTimeout)(this.timer);
    this.timer = null;
  }
}

/** The clip re-renders by itself after a change (not on open: an older edit renders when she changes something). */
export function useAutoRender(item: string, clip: string, doc: OutputDoc | null, flush?: () => Promise<boolean>) {
  const { client, subscribe } = useEngine();
  const [state, setState] = useState<RenderState>({ phase: 'idle', progress: 0 });
  const docRef = useRef(doc);
  docRef.current = doc;
  const q = useMemo(
    () =>
      new RenderQueue({
        onState: setState,
        start: async () => {
          const d = docRef.current;
          // the desk's own editor (no video engine) cannot re-encode: its Export says so, nothing runs by itself
          if (!client || !d || d.engine !== 'real' || d.caps.export === false || upToDate(d)) return null;
          if (flush && !(await flush())) return null; // the transcript's last deletes belong in it
          const targets = renderTargets(d);
          const r = await client.exportOutput(item, clip, targets);
          return { job: r.job, targets: targets.length };
        },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, item, clip],
  );
  useEffect(() => () => q.dispose(), [q]);
  useEffect(() => subscribe((e) => (e.type === 'output-render' && e.item === item && e.clip === clip ? q.event(e as RenderEvent) : undefined)), [subscribe, item, clip, q]);
  const key = doc ? editKey(doc) : null;
  const seen = useRef<{ clip: string; key: string } | null>(null);
  useEffect(() => {
    if (!key) return;
    const id = `${item}/${clip}`;
    if (seen.current?.clip !== id) {
      seen.current = { clip: id, key }; // the clip as she opened it
      return;
    }
    if (seen.current.key === key) return;
    seen.current = { clip: id, key };
    q.request();
  }, [key, item, clip, q]);
  // "Updated" fades after a while
  useEffect(() => {
    if (state.phase !== 'done') return;
    const tm = window.setTimeout(() => setState((s) => (s.phase === 'done' ? { phase: 'idle', progress: 0 } : s)), 6000);
    return () => window.clearTimeout(tm);
  }, [state.phase]);
  const now = useCallback(() => q.request(), [q]);
  return { state, now };
}
