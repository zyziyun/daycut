import { describe, expect, it } from 'vitest';
import { editKey, RenderQueue, renderTargets, upToDate, type RenderState } from '../../src/renderer/src/lib/autoRender';

function harness() {
  const timers: (() => void)[] = [];
  const states: RenderState[] = [];
  let jobs = 0;
  const q = new RenderQueue({
    onState: (s) => states.push(s),
    start: async () => ({ job: `j${++jobs}`, targets: 2 }),
    setTimer: (f) => (timers.push(f), timers.length as unknown as ReturnType<typeof setTimeout>),
    clearTimer: (t) => (timers[(t as unknown as number) - 1] = () => undefined),
  });
  const fire = async () => {
    const f = timers.splice(0).pop();
    f?.();
    await Promise.resolve();
    await Promise.resolve();
  };
  return { q, states, fire, jobs: () => jobs, last: () => states[states.length - 1] };
}

describe('RenderQueue', () => {
  it('a burst of changes = one render after the quiet', async () => {
    const h = harness();
    h.q.request();
    h.q.request();
    h.q.request();
    expect(h.last().phase).toBe('waiting');
    await h.fire();
    expect(h.jobs()).toBe(1);
    expect(h.last().phase).toBe('running');
  });
  it('progress over every target, done at the end', async () => {
    const h = harness();
    h.q.request();
    await h.fire();
    h.q.event({ job: 'j1', event: 'target-start', target: 'primary' });
    h.q.event({ job: 'j1', event: 'stage-done', target: 'primary', stage: 'timeline', progress: 0.5 });
    expect(h.last().progress).toBeCloseTo(0.25);
    h.q.event({ job: 'j1', event: 'target-done', target: 'primary' });
    h.q.event({ job: 'other', event: 'render-done' }); // another clip's render is not ours
    expect(h.last().phase).toBe('running');
    h.q.event({ job: 'j1', event: 'target-done', target: 'douyin:vertical' });
    h.q.event({ job: 'j1', event: 'render-done' });
    expect(h.last()).toEqual({ phase: 'done', progress: 1 });
  });
  it('a change while it renders = exactly one more render after it', async () => {
    const h = harness();
    h.q.request();
    await h.fire();
    h.q.request();
    h.q.request();
    expect(h.jobs()).toBe(1);
    h.q.event({ job: 'j1', event: 'render-done' });
    expect(h.last().phase).toBe('waiting');
    await h.fire();
    expect(h.jobs()).toBe(2);
    h.q.event({ job: 'j2', event: 'render-done' });
    expect(h.last().phase).toBe('done');
  });
  it('a failed render says so', async () => {
    const h = harness();
    h.q.request();
    await h.fire();
    h.q.event({ job: 'j1', event: 'failed', error: 'render exited 1' });
    expect(h.last()).toMatchObject({ phase: 'failed', error: 'render exited 1' });
  });
});

describe('what to render', () => {
  const doc = { steps: [{ id: 's1', reverted: false, describe: [] }], undo: 1, redo: 0, exports: [{ target: 'douyin:vertical' }], renders: [] as { target: string; fresh?: boolean; quality?: string; file: string; simulated?: boolean }[] };
  it('every version of the clip', () => expect(renderTargets(doc)).toEqual(['primary', 'douyin:vertical']));
  it('any step (or undo) changes the edit key', () => {
    expect(editKey(doc)).not.toBe(editKey({ ...doc, undo: 0, redo: 1 }));
    expect(editKey(doc)).not.toBe(editKey({ ...doc, steps: [...doc.steps, { id: 's2', reverted: false, describe: [] }] }));
  });
  it('up to date only when every version has a fresh final render', () => {
    expect(upToDate(doc)).toBe(false);
    const r = [{ target: 'primary', fresh: true, file: 'a' }];
    expect(upToDate({ ...doc, renders: r })).toBe(false);
    expect(upToDate({ ...doc, renders: [...r, { target: 'douyin:vertical', fresh: true, quality: 'final', file: 'b' }] })).toBe(true);
    expect(upToDate({ ...doc, renders: [...r, { target: 'douyin:vertical', fresh: true, quality: 'preview', file: 'b' }] })).toBe(false);
  });
});
