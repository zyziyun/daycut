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
