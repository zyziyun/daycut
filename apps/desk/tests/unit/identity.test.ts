import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { APP_NAME, applyIdentity, LEGACY_NAME, resolveIdentity } from '../../src/main/identity';

function appData(dirs: Record<string, string[]>) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'daycut-id-'));
  for (const [d, files] of Object.entries(dirs)) {
    fs.mkdirSync(path.join(root, d), { recursive: true });
    for (const f of files) fs.writeFileSync(path.join(root, d, f), '{}');
  }
  return root;
}

describe('identity across the video-studio desk -> Daycut rename', () => {
  it('an existing install keeps its folder and keychain name', () => {
    const root = appData({ [LEGACY_NAME]: ['settings.json', 'secrets.json'] });
    expect(resolveIdentity(root)).toEqual({ internalName: LEGACY_NAME, userData: path.join(root, LEGACY_NAME), legacy: true });
  });

  it('keeps the old profile even when an empty Daycut folder appeared', () => {
    const root = appData({ [LEGACY_NAME]: ['settings.json'], [APP_NAME]: [] });
    expect(resolveIdentity(root).legacy).toBe(true);
  });

  it('a fresh install is Daycut', () => {
    const root = appData({});
    expect(resolveIdentity(root)).toEqual({ internalName: APP_NAME, userData: path.join(root, APP_NAME), legacy: false });
  });

  it('once a Daycut profile exists it wins', () => {
    const root = appData({ [LEGACY_NAME]: ['settings.json'], [APP_NAME]: ['settings.json'] });
    expect(resolveIdentity(root).userData).toBe(path.join(root, APP_NAME));
  });

  it('DESK_USER_DATA (tests) overrides everything', () => {
    const root = appData({ [LEGACY_NAME]: ['settings.json'] });
    expect(resolveIdentity(root, '/tmp/x')).toEqual({ internalName: APP_NAME, userData: '/tmp/x', legacy: false });
  });

  it('a legacy install keeps its keychain name until ready, then app.getName() is Daycut', () => {
    const root = appData({ [LEGACY_NAME]: ['settings.json'] });
    let name = 'electron';
    const ready: (() => void)[] = [];
    const app = {
      getPath: () => root,
      setPath: () => undefined,
      setName: (n: string) => (name = n),
      setAppUserModelId: () => undefined,
      once: (ev: string, f: () => void) => ev === 'ready' && ready.push(f),
    } as unknown as Electron.App;
    expect(applyIdentity(app, '').legacy).toBe(true);
    expect(name).toBe(LEGACY_NAME); // the safeStorage key is read before 'ready'
    ready.forEach((f) => f());
    expect(name).toBe(APP_NAME);
  });
});
