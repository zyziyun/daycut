import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { defaultEnginePath, engineProcessEnv, extraBinDirs, utf8Env } from '../../src/main/engine';

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

describe('Windows engine environment', () => {
  it('finds the AI CLIs where Windows installers put them', () => {
    const dirs = extraBinDirs('win32', { APPDATA: 'C:\\Users\\李 雷\\AppData\\Roaming', LOCALAPPDATA: 'C:\\Users\\李 雷\\AppData\\Local' }, 'C:\\Users\\李 雷');
    expect(dirs).toEqual([
      'C:\\Users\\李 雷\\.local\\bin',
      'C:\\Users\\李 雷\\AppData\\Roaming\\npm',
      'C:\\Users\\李 雷\\AppData\\Local\\Microsoft\\WinGet\\Links',
      'C:\\Users\\李 雷\\scoop\\shims',
    ]);
    expect(extraBinDirs('win32', {}, 'C:\\Users\\me')[1]).toBe('C:\\Users\\me\\AppData\\Roaming\\npm');
    expect(extraBinDirs('darwin', {}, '/Users/me')).toContain('/opt/homebrew/bin');
  });

  it('runs Python in UTF-8 mode on Windows only', () => {
    expect(utf8Env('win32')).toEqual({ PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' });
    expect(utf8Env('darwin')).toEqual({});
    const env = engineProcessEnv({ env: { PYTHONUTF8: '0' } });
    expect(env.PYTHONUNBUFFERED).toBe('1');
    expect(env.PYTHONUTF8).toBe('0'); // an explicit setting wins
  });
});
