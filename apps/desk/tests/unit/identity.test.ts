import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { APP_ID, APP_NAME, appDataOverride, applyIdentity, LEGACY_NAMES, migrateProfile, MIGRATION_FILE, readMigration, resolveIdentity } from '../../src/main/identity';
import { SecretStore, type Crypto } from '../../src/main/secrets';

const [DAYCUT, VSDESK] = LEGACY_NAMES;
/** a path as it appears inside a JSON string (Windows backslashes are escaped) */
const json = (p: string) => JSON.stringify(p).slice(1, -1);

function appData(dirs: Record<string, string[]>) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-id-'));
  for (const [d, files] of Object.entries(dirs)) {
    fs.mkdirSync(path.join(root, d), { recursive: true });
    for (const f of files) fs.writeFileSync(path.join(root, d, f), '{}');
  }
  return root;
}

function fakeApp(root: string) {
  const s = { name: 'electron', userData: '', ready: [] as (() => void)[] };
  const app = {
    getPath: () => root,
    setPath: (_k: string, v: string) => (s.userData = v),
    setName: (n: string) => (s.name = n),
    setAppUserModelId: () => undefined,
    once: (ev: string, f: () => void) => ev === 'ready' && s.ready.push(f),
  } as unknown as Electron.App;
  return { app, s };
}

describe('identity: Reelfold, migrating old profiles once', () => {
  it('names', () => {
    expect(APP_NAME).toBe('Reelfold');
    expect(APP_ID).toBe('app.reelfold.desk');
    expect(LEGACY_NAMES).toEqual(['Daycut', 'video-studio desk']);
  });

  it('a fresh install is Reelfold', () => {
    const root = appData({});
    expect(resolveIdentity(root)).toEqual({ internalName: APP_NAME, userData: path.join(root, APP_NAME), migrated: false });
  });

  it('a video-studio desk profile is migrated into Reelfold and keeps its keychain name', () => {
    const root = appData({ [VSDESK]: ['settings.json', 'secrets.json'] });
    expect(resolveIdentity(root)).toEqual({ internalName: VSDESK, userData: path.join(root, APP_NAME), migrateFrom: path.join(root, VSDESK), migrated: true });
  });

  it('with both old profiles, the newest one wins', () => {
    const root = appData({ [VSDESK]: ['settings.json'], [DAYCUT]: ['settings.json'] });
    const old = Date.now() / 1000 - 3600;
    fs.utimesSync(path.join(root, DAYCUT, 'settings.json'), old, old);
    expect(resolveIdentity(root).migrateFrom).toBe(path.join(root, VSDESK));
    fs.utimesSync(path.join(root, VSDESK, 'settings.json'), old - 10, old - 10);
    expect(resolveIdentity(root).migrateFrom).toBe(path.join(root, DAYCUT));
  });

  it('an empty old folder is not a profile', () => {
    const root = appData({ [VSDESK]: [] });
    expect(resolveIdentity(root).migrateFrom).toBeUndefined();
  });

  it('a Reelfold profile wins; its migration record keeps the old keychain name', () => {
    const root = appData({ [VSDESK]: ['settings.json'], [APP_NAME]: ['settings.json'] });
    expect(resolveIdentity(root)).toEqual({ internalName: APP_NAME, userData: path.join(root, APP_NAME), migrated: false });
    fs.writeFileSync(path.join(root, APP_NAME, MIGRATION_FILE), JSON.stringify({ from: 'x', safeStorageName: VSDESK, at: 'now' }));
    expect(resolveIdentity(root)).toEqual({ internalName: VSDESK, userData: path.join(root, APP_NAME), migrated: true });
  });

  it('DESK_USER_DATA (tests) overrides everything', () => {
    const root = appData({ [VSDESK]: ['settings.json'] });
    expect(resolveIdentity(root, '/tmp/x')).toEqual({ internalName: APP_NAME, userData: '/tmp/x', migrated: false });
  });

  it('DESK_APP_DATA is honoured by a packaged build only inside the temp dir', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-ad-'));
    expect(appDataOverride({ DESK_APP_DATA: tmp, DESK_LEGACY_NAMES: 'A|B' }, true)).toEqual({ appData: tmp, legacyNames: ['A', 'B'] });
    expect(appDataOverride({ DESK_APP_DATA: os.homedir() }, true)).toEqual({});
    expect(appDataOverride({ DESK_APP_DATA: os.homedir() }, false)).toEqual({ appData: os.homedir() });
    expect(appDataOverride({}, false)).toEqual({});
  });
});

describe('migrateProfile', () => {
  function oldProfile() {
    const root = appData({});
    const from = path.join(root, VSDESK);
    const w = (rel: string, body: string) => {
      fs.mkdirSync(path.dirname(path.join(from, rel)), { recursive: true });
      fs.writeFileSync(path.join(from, rel), body);
    };
    w('settings.json', JSON.stringify({ lang: 'zh-CN', accounts: [{ id: 'a' }], firstRunDone: true }));
    w('secrets.json', JSON.stringify({ openai: 'Y2lwaGVy' }));
    w('llm-routes.json', '{"routes":{}}');
    w('assets/installed.json', JSON.stringify({ chromium: { root: path.join(from, 'assets/chromium/1') }, core: { root: '/elsewhere/cache' } }));
    w('assets/chromium/1/chrome', 'binary');
    w('engine-data/v02/projects.json', JSON.stringify([{ dir: path.join(from, 'engine-data/outputs/p1') }]));
    w('engine-data/strips/abc/strip.json', JSON.stringify({ png: path.join(from, 'engine-data/strips/abc/0.png') }));
    w('Partitions/douyin-main/Cookies', 'sqlite');
    w('Cache/Cache_Data/x', 'cache');
    w('Code Cache/js/y', 'cache');
    fs.symlinkSync('Mac-123', path.join(from, 'SingletonLock'));
    return { root, from, to: path.join(root, APP_NAME) };
  }

  it('copies everything but caches and locks, rewrites paths, records the keychain name, leaves the old folder alone', () => {
    const { from, to } = oldProfile();
    const before = fs.readdirSync(from).sort();
    expect(migrateProfile(from, to, VSDESK)).toBe(true);
    expect(fs.readdirSync(from).sort()).toEqual(before);
    expect(fs.readFileSync(path.join(from, 'assets/installed.json'), 'utf8')).toContain(json(from)); // old folder untouched
    expect(JSON.parse(fs.readFileSync(path.join(to, 'settings.json'), 'utf8')).accounts).toEqual([{ id: 'a' }]);
    expect(fs.readFileSync(path.join(to, 'secrets.json'), 'utf8')).toContain('Y2lwaGVy');
    expect(fs.readFileSync(path.join(to, 'Partitions/douyin-main/Cookies'), 'utf8')).toBe('sqlite');
    expect(fs.readFileSync(path.join(to, 'assets/chromium/1/chrome'), 'utf8')).toBe('binary');
    const inst = JSON.parse(fs.readFileSync(path.join(to, 'assets/installed.json'), 'utf8'));
    expect(inst.chromium.root).toBe(path.join(to, 'assets/chromium/1'));
    expect(inst.core.root).toBe('/elsewhere/cache');
    expect(fs.readFileSync(path.join(to, 'engine-data/v02/projects.json'), 'utf8')).toContain(json(path.join(to, 'engine-data/outputs/p1')));
    expect(fs.readFileSync(path.join(to, 'engine-data/strips/abc/strip.json'), 'utf8')).not.toContain(json(from));
    for (const skipped of ['Cache', 'Code Cache', 'SingletonLock']) expect(fs.existsSync(path.join(to, skipped))).toBe(false);
    expect(readMigration(to)).toMatchObject({ from, safeStorageName: VSDESK });
    expect(fs.readdirSync(path.dirname(to)).filter((d) => d.includes('.migrating-'))).toEqual([]);
  });

  it('applyIdentity migrates once, then keeps using the copy with the old keychain name', () => {
    const { root, to } = oldProfile();
    const logs: string[] = [];
    const a = fakeApp(root);
    const id = applyIdentity(a.app, '', (s) => logs.push(s));
    expect(id).toMatchObject({ internalName: VSDESK, userData: to, migrated: true });
    expect(a.s.name).toBe(VSDESK); // safeStorage reads the key name before 'ready'
    expect(a.s.userData).toBe(to);
    a.s.ready.forEach((f) => f());
    expect(a.s.name).toBe(APP_NAME);
    expect(logs.join('\n')).toMatch(/copied the profile/);
    // second launch: no copy, same keychain name
    fs.writeFileSync(path.join(to, 'settings.json'), JSON.stringify({ lang: 'en' }));
    const b = fakeApp(root);
    const logs2: string[] = [];
    const id2 = applyIdentity(b.app, '', (s) => logs2.push(s));
    expect(id2).toMatchObject({ internalName: VSDESK, userData: to, migrated: true });
    expect(id2.migrateFrom).toBeUndefined();
    expect(logs2).toEqual([]);
    expect(JSON.parse(fs.readFileSync(path.join(to, 'settings.json'), 'utf8')).lang).toBe('en');
  });

  // chmod cannot make a folder unwritable on Windows
  it.skipIf(process.platform === 'win32')('a failed copy runs on the old profile in place instead of starting empty', () => {
    const { root, from } = oldProfile();
    fs.writeFileSync(path.join(root, APP_NAME + '.blocker'), '');
    const a = fakeApp(root);
    // make the target's parent unwritable for the staging folder
    fs.chmodSync(root, 0o555);
    try {
      const id = applyIdentity(a.app, '', () => undefined);
      expect(id.userData).toBe(from);
      expect(a.s.userData).toBe(from);
      expect(a.s.name).toBe(VSDESK);
    } finally {
      fs.chmodSync(root, 0o755);
    }
  });
});

describe('secrets after a migration', () => {
  const crypto = (key: string): Crypto => ({
    isEncryptionAvailable: () => true,
    encryptString: (s) => Buffer.from(`${key}:${s}`),
    decryptString: (b) => {
      const [k, ...rest] = b.toString().split(':');
      if (k !== key) throw new Error('Error while decrypting the ciphertext provided to safeStorage.decryptString.');
      return rest.join(':');
    },
  });

  it('keys encrypted under the old keychain item still decrypt with that item; under another they show as not set', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-sec-'));
    new SecretStore(dir, crypto('video-studio desk')).set('openai', 'test-key-123');
    const same = new SecretStore(dir, crypto('video-studio desk'));
    expect(same.status().keys.openai).toBe(true);
    expect(same.env().OPENAI_API_KEY).toBe('test-key-123');
    const other = new SecretStore(dir, crypto('Reelfold'));
    expect(other.status().keys.openai).toBe(false); // the UI asks for it again
    expect(other.env().OPENAI_API_KEY).toBeUndefined();
    other.set('openai', 'test-key-new');
    expect(other.env().OPENAI_API_KEY).toBe('test-key-new');
  });
});
