// Regressions from the 2026-10 bug bash (qa/BUGS.md).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { EngineProcess } from '../../src/main/engine';
import { slotBounds } from '../../src/renderer/src/lib/slotBounds';
import { bucket, withInbox } from '../../src/renderer/src/lib/status';
import type { HistoryItem } from '../../src/shared/v02';

function fakeEngine(body: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bb-engine-'));
  fs.writeFileSync(path.join(dir, 'server.py'), body);
  return dir;
}

describe('BB-01 engine crash after start is reported (not a silent "Ready")', () => {
  const base = { python: 'python3', dataDir: os.tmpdir(), allowedOrigins: ['app://desk'] };
  it('calls onDied when the engine dies on its own', async () => {
    const engineDir = fakeEngine('import json,sys,time\nprint(json.dumps({"ready": True, "port": 1, "mode": "real"}), flush=True)\ntime.sleep(0.3)\nsys.exit(3)\n');
    let crashed = '';
    const e = new EngineProcess({ ...base, engineDir, onDied: (d) => (crashed = d) });
    const info = await e.start(10000);
    expect(info.mode).toBe('real');
    await new Promise((r) => setTimeout(r, 1500));
    expect(crashed).toMatch(/engine exited \(3\)/);
    expect(e.info).toBeNull();
  });
  it('does not call onDied for stop()', async () => {
    const engineDir = fakeEngine('import json,time\nprint(json.dumps({"ready": True, "port": 1, "mode": "real"}), flush=True)\ntime.sleep(30)\n');
    let crashed = false;
    const e = new EngineProcess({ ...base, engineDir, onDied: () => (crashed = true) });
    await e.start(10000);
    await e.stop();
    await new Promise((r) => setTimeout(r, 300));
    expect(crashed).toBe(false);
  });
});

describe('BB-10 embedded browser bounds are clipped to the window', () => {
  const view = { width: 1440, height: 900 };
  it('a slot scrolled above the top never gives a negative y', () => {
    const b = slotBounds({ left: 300, top: -120, right: 1400, bottom: 600 }, view);
    expect(b).toEqual({ x: 300, y: 0, width: 1100, height: 600 });
  });
  it('a slot entirely off screen hides the browser', () => {
    expect(slotBounds({ left: 300, top: -700, right: 1400, bottom: -10 }, view)).toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });
  it('is clipped at the right / bottom edges too', () => {
    expect(slotBounds({ left: 1000, top: 800, right: 1600, bottom: 1200 }, view)).toEqual({ x: 1000, y: 800, width: 440, height: 100 });
  });
});

describe('BB-08 All projects counts a project with an Inbox decision as "needs you"', () => {
  const item = { id: 'a', kind: 'work', status: 'done', counts: null, live: null, updated: 0 } as unknown as HistoryItem;
  it('done + decision -> you', () => {
    expect(withInbox('done', true)).toBe('you');
    expect(bucket(item, true)).toBe('you');
    expect(bucket(item, false)).toBe('done');
  });
  it('errors and running stay what they are', () => {
    expect(withInbox('error', true)).toBe('error');
    expect(withInbox('run', true)).toBe('run');
  });
});

describe('mock-in-product: test switches need a throw-away profile in a packaged build', async () => {
  const { testSwitch } = await import('../../src/main/testHooks');
  const tmp = os.tmpdir();
  it('dev builds honour them as set', () => {
    expect(testSwitch('DESK_ENGINE_MOCK', { DESK_ENGINE_MOCK: '1' }, false, tmp)).toBe(true);
    expect(testSwitch('DESK_ENGINE_MOCK', {}, false, tmp)).toBe(false);
  });
  it('a packaged build ignores them for a real profile', () => {
    expect(testSwitch('DESK_ENGINE_MOCK', { DESK_ENGINE_MOCK: '1' }, true, tmp)).toBe(false);
    expect(testSwitch('DESK_SKIP_FIRST_RUN', { DESK_SKIP_FIRST_RUN: '1', DESK_USER_DATA: path.join(os.homedir(), 'Library') }, true, tmp)).toBe(false);
  });
  it('a packaged build honours them for a temp test profile (the packaged tests)', () => {
    const ud = fs.mkdtempSync(path.join(tmp, 'bb-prof-'));
    expect(testSwitch('DESK_HIDE_WINDOW', { DESK_HIDE_WINDOW: '1', DESK_USER_DATA: ud }, true, tmp)).toBe(true);
  });
});

describe('BB-13 media through a symlinked folder is served, a symlink out of a root is not', async () => {
  const { allowedMedia } = await import('../../src/main/media');
  const P = path.posix;
  const roots = ['/private/tmp/p/engine-data'];
  it('asked as /tmp/... but really /private/tmp/... (the timeline sprite was a 403)', () => {
    expect(allowedMedia('/tmp/p/engine-data/strips/a/sprite.jpg', '/private/tmp/p/engine-data/strips/a/sprite.jpg', roots, P)).toBe(true);
  });
  it('a link inside a root that points elsewhere is refused', () => {
    expect(allowedMedia('/private/tmp/p/engine-data/x.jpg', '/Users/me/secret.jpg', roots, P)).toBe(false);
  });
  it('the asked path is still checked for shape', () => {
    expect(allowedMedia('/tmp/p/../p/engine-data/a.jpg', '/private/tmp/p/engine-data/a.jpg', roots, P)).toBe(false);
    expect(allowedMedia('/tmp/p/engine-data/a.txt', '/private/tmp/p/engine-data/a.txt', roots, P)).toBe(false);
  });
});

describe('BB-19 a fresh install routes every AI job to the AI the page shows (not six jobs to rules)', async () => {
  const { routesFromEngine } = await import('../../src/shared/aiRoutes');
  // `python -m vstudio.llm route --json` with nothing configured (no persona / config / desk routes)
  const none = { provider: 'none', model: null, source: 'legacy-auto' };
  const unconfigured = Object.fromEntries(['segment_plan', 'proofread', 'glossary', 'copy', 'script', 'planner', 'intake', 'output_edit', 'default'].map((k) => [k, none]));
  it('no task is pinned to "none"', () => {
    const r = routesFromEngine(unconfigured);
    expect(r.default.provider).toBe('claude-code');
    expect(r.tasks).toEqual({});
  });
  it('a task the persona really routes elsewhere is kept', () => {
    const r = routesFromEngine({ ...unconfigured, proofread: { provider: 'ollama', model: 'qwen3:8b', source: 'persona llm.tasks.proofread' } });
    expect(Object.values(r.tasks)).toEqual([{ provider: 'ollama', model: 'qwen3:8b', fallback: [] }]);
  });
  it('a task inherited from the persona default is not a task route', () => {
    const def = { provider: 'codex', model: null, source: 'persona llm.default' };
    const r = routesFromEngine({ default: def, copy: def, intake: def });
    expect(r.default.provider).toBe('codex');
    expect(r.tasks).toEqual({});
  });
});

describe('i18n: effect parameters without a label read as words, not snake_case ids', async () => {
  const { humanizeParam } = await import('../../src/renderer/src/v4/msg');
  it('music_lufs -> Music lufs', () => {
    expect(humanizeParam('music_lufs')).toBe('Music lufs');
    expect(humanizeParam('in-dur')).toBe('In dur');
    expect(humanizeParam('')).toBe('');
  });
});
