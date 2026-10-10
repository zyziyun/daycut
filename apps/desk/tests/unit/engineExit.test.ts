// An engine that exits on its own is reported with what ended it (0.2.3 reported "exit null · engine exited (null)"
// for an engine killed by SIGUSR1); an engine stopped on purpose (restart / quit / update-restart) is never reported.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { describeExit, EngineProcess, type EngineExit } from '../../src/main/engine';

describe('describeExit', () => {
  it('names the signal instead of "exit null"', () => {
    expect(describeExit({ code: null, signal: 'SIGUSR1' })).toEqual({ code: 'signal SIGUSR1', message: 'engine was ended by SIGUSR1 from outside the app', crash: true });
  });
  it('a non-zero code is a crash', () => {
    expect(describeExit({ code: 3, signal: null })).toMatchObject({ code: 'exit 3', crash: true });
  });
  it('a clean exit 0 (asked to stop from outside) is not a crash', () => {
    expect(describeExit({ code: 0, signal: null })).toMatchObject({ code: 'exit 0', crash: false });
  });
});

function fakeEngine(body: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'exit-engine-'));
  fs.writeFileSync(path.join(dir, 'server.py'), body);
  return dir;
}

const READY = 'import json,time\nprint(json.dumps({"ready": True, "port": 1, "mode": "real"}), flush=True)\n';
const base = { python: process.platform === 'win32' ? 'python' : 'python3', dataDir: os.tmpdir(), allowedOrigins: ['app://desk'] };

describe('EngineProcess exit reporting', { timeout: 20000 }, () => {
  it.skipIf(process.platform === 'win32')('an engine ended by a signal reports the signal', async () => {
    let got: EngineExit | null = null;
    const e = new EngineProcess({ ...base, engineDir: fakeEngine(`${READY}import os,signal\ntime.sleep(0.3)\nos.kill(os.getpid(), signal.SIGUSR1)\ntime.sleep(30)\n`), onCrash: (x) => (got = x) });
    await e.start(10000);
    await expect.poll(() => got, { timeout: 10000 }).toEqual({ code: null, signal: 'SIGUSR1' });
  });
  it('stop() (quit, restart, update-restart) never reports', async () => {
    let got: EngineExit | null = null;
    const e = new EngineProcess({ ...base, engineDir: fakeEngine(`${READY}time.sleep(30)\n`), onCrash: (x) => (got = x) });
    await e.start(10000);
    await e.stop();
    await new Promise((r) => setTimeout(r, 300));
    expect(got).toBeNull();
  });
});
