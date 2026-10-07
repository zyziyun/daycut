import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { defaultEnginePath } from '../../src/main/engine';

describe('defaultEnginePath (monorepo)', () => {
  it('dev: apps/desk finds the engine at the repo root (../..)', () => {
    const appPath = path.resolve(import.meta.dirname, '../..'); // apps/desk
    const saved = process.env.VSTUDIO_ENGINE_PATH;
    delete process.env.VSTUDIO_ENGINE_PATH;
    try {
      expect(defaultEnginePath(appPath)).toBe(path.resolve(appPath, '..', '..'));
    } finally {
      if (saved !== undefined) process.env.VSTUDIO_ENGINE_PATH = saved;
    }
  });

  it('settings / bundled runtime still win, and the old sibling layout still works', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'enginepath-'));
    const mk = (p: string) => (fs.mkdirSync(path.join(p, 'lib', 'vstudio'), { recursive: true }), p);
    const preferred = mk(path.join(tmp, 'mine'));
    const sibling = mk(path.join(tmp, 'video-studio'));
    const oldApp = path.join(tmp, 'video-studio-desk');
    fs.mkdirSync(oldApp);
    expect(defaultEnginePath(oldApp, preferred)).toBe(preferred);
    const saved = process.env.VSTUDIO_ENGINE_PATH;
    delete process.env.VSTUDIO_ENGINE_PATH;
    try {
      expect(defaultEnginePath(oldApp)).toBe(sibling);
    } finally {
      if (saved !== undefined) process.env.VSTUDIO_ENGINE_PATH = saved;
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });
});
