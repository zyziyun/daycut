// Live history: only job-relevant file changes ping the renderer (debounced), watchers follow the root list.
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { HistoryWatcher, isInteresting } from '../../src/main/historyWatch';

describe('history watcher', () => {
  it('filters to live-status / record / batch files', () => {
    expect(isInteresting('fuye/.vstudio/status.json')).toBe(true);
    expect(isInteresting('fuye/.vstudio/work.json')).toBe(true);
    expect(isInteresting('batch-rag/run.lock')).toBe(true);
    expect(isInteresting('01-th/final/xhs.mp4')).toBe(true);
    expect(isInteresting('fuye/work/probe/p_620.jpg')).toBe(false);
    expect(isInteresting('batch-rag/cache/asr/x.json')).toBe(false);
  });

  it('debounces pings and replaces the watched set', async () => {
    const a = fs.mkdtempSync(path.join(os.tmpdir(), 'hw-a-'));
    const b = fs.mkdtempSync(path.join(os.tmpdir(), 'hw-b-'));
    const cbs = new Map<string, (ev: string, f: string) => void>();
    const closed: string[] = [];
    const fake = ((root: string, _o: unknown, cb: (ev: string, f: string) => void) => {
      cbs.set(root, cb);
      const w = new EventEmitter() as EventEmitter & { close(): void };
      w.close = () => closed.push(root);
      return w;
    }) as unknown as typeof fs.watch;
    const notify = vi.fn();
    const hw = new HistoryWatcher(notify, 20, fake);
    expect(hw.set([a, b, path.join(a, 'missing')])).toEqual([a, b]);
    cbs.get(a)!('change', 'job/.vstudio/status.json');
    cbs.get(a)!('change', 'job/.vstudio/status.json');
    cbs.get(b)!('change', 'x/work/tmp.wav');
    await new Promise((r) => setTimeout(r, 60));
    expect(notify).toHaveBeenCalledTimes(1);
    expect(hw.set([b])).toEqual([b]);
    expect(closed).toEqual([a]);
    hw.close();
  });
});
