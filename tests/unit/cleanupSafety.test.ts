// Source-recording safety: the 30-day default is gone (settings migrate to "never" once), and a cleanup is only
// ever offered as a dialog that lists every file; sources outside the batch folder are listed as kept.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ dialog: {}, safeStorage: {}, shell: {} }));

describe('cleanup safety', () => {
  it('settings: default never; an old profile with 30 days is reset once, a later choice stays', async () => {
    const { SettingsStore } = await import('../../src/main/settings');
    const fresh = fs.mkdtempSync(path.join(os.tmpdir(), 'set-'));
    expect(new SettingsStore(fresh).get().cleanupDays).toBe(0);
    const old = fs.mkdtempSync(path.join(os.tmpdir(), 'set-'));
    fs.writeFileSync(path.join(old, 'settings.json'), JSON.stringify({ lang: 'zh', cleanupDays: 30, firstRunDone: true }));
    const s = new SettingsStore(old);
    expect(s.get().cleanupDays).toBe(0);
    expect(JSON.parse(fs.readFileSync(path.join(old, 'settings.json'), 'utf8')).cleanupMigrated).toBe(true);
    s.set({ cleanupDays: 14 });
    expect(new SettingsStore(old).get().cleanupDays).toBe(14);
  });

  it('the confirmation lists every file, its size, and the kept outside recordings', async () => {
    const { cleanupDialogText } = await import('../../src/main/v02');
    const txt = cleanupDialogText({ batch: 'abcdefabcdef', paths: ['/w/batch-a/src/raw.mp4'], outside: ['/Users/me/Movies/lecture.mov'] }, { '/w/batch-a/src/raw.mp4': 2_500_000 }, 'zh');
    expect(txt.message).toContain('1 个原始素材');
    expect(txt.detail).toContain('/w/batch-a/src/raw.mp4  (2.5 MB)');
    expect(txt.detail).toContain('不会删除');
    expect(txt.detail).toContain('/Users/me/Movies/lecture.mov');
    expect(txt.buttons[0]).toBe('取消');
  });
});
