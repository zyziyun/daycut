import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { getVersion: () => '0.1.0' }, dialog: {}, Menu: {}, nativeImage: {}, shell: {} }));

import { aboutCredits, aboutText, displayName } from '../../src/main/appMenu';
import { aboutEn, aboutFr, aboutZh } from '../../src/renderer/src/i18n/locales/about';
import { en } from '../../src/renderer/src/i18n/locales/en';
import { zhCN } from '../../src/renderer/src/i18n/locales/zh-CN';
// @ts-expect-error -- plain .mjs build script
import { devAppStamp, devPlistEdits } from '../../scripts/devApp.mjs';

const versions = { electron: '44.5.1', chrome: '152.0.7977.130', node: '24.11.0' };

describe('About panel copy', () => {
  it('en: name, version, open-source repo, runtime versions, licences, copyright', () => {
    const a = aboutText('en', '1.2.3', versions);
    expect(a['about.heading']).toBe('Daycut · Version 1.2.3');
    expect(a['about.openSource']).toBe('Open source: github.com/zyziyun/daycut');
    expect(a['about.runtime']).toBe('Electron 44.5.1 · Chromium 152 · Node.js 24');
    expect(a['about.licences']).toBe('Third-party Licences');
    expect(a['about.copyright']).toBe('Copyright © 2026 zyziyun');
    expect(a['about.menu']).toBe('About Daycut');
    expect(a['about.repo']).toBe('Daycut on GitHub');
  });

  it('zh-CN and fr', () => {
    const zh = aboutText('zh-CN', '1.2.3', versions);
    expect(zh['about.heading']).toBe('日剪 Daycut · 版本 1.2.3');
    expect(zh['about.openSource']).toBe('开源地址：github.com/zyziyun/daycut');
    expect(zh['about.menu']).toBe('关于 日剪 Daycut');
    const fr = aboutText('fr', '1.2.3', versions);
    expect(fr['about.heading']).toBe('Daycut · Version 1.2.3');
    expect(fr['about.openSource']).toBe('Open source : github.com/zyziyun/daycut');
    expect(fr['about.licences']).toBe('Licences tierces');
    expect(fr['about.menu']).toBe('À propos de Daycut');
    expect(aboutText('de', '1.2.3', versions)['about.menu']).toBe('About Daycut'); // unknown -> en
  });

  it('credits: repo, versions, where the licences are; no old engine / repo name', () => {
    const c = aboutCredits('en', '0.1.0', versions);
    expect(c.split('\n')).toEqual(['Open source: github.com/zyziyun/daycut', '', 'Electron 44.5.1 · Chromium 152 · Node.js 24', 'Licences: Help → Third-party Licences']);
    for (const lang of ['en', 'zh-CN', 'fr']) {
      const all = Object.values(aboutText(lang, '0.1.0', versions)).join('\n') + aboutCredits(lang, '0.1.0', versions);
      expect(all).not.toMatch(/video-studio|zyziyun\/video-studio/);
    }
    expect(displayName('en')).toBe('Daycut');
    expect(displayName('zh-CN')).toBe('日剪 Daycut');
  });

  it('every locale has every key, and the renderer locales carry them', () => {
    const keys = Object.keys(aboutEn).sort();
    expect(Object.keys(aboutZh).sort()).toEqual(keys);
    expect(Object.keys(aboutFr).sort()).toEqual(keys);
    for (const k of keys) {
      expect(en).toHaveProperty(k);
      expect(zhCN).toHaveProperty(k);
    }
  });
});

describe('dev Daycut.app copy', () => {
  it('is named Daycut with its own bundle id and the Daycut icon', () => {
    expect(devPlistEdits()).toEqual({ CFBundleName: 'Daycut', CFBundleDisplayName: 'Daycut', CFBundleIdentifier: 'com.vstudio.desk.dev', CFBundleIconFile: 'daycut.icns' });
  });

  it('is rebuilt when the Electron version or the icon changes', () => {
    const icon = Buffer.from('icns');
    const s = devAppStamp({ electronVersion: '44.5.1', iconBytes: icon });
    expect(devAppStamp({ electronVersion: '44.5.1', iconBytes: icon })).toBe(s);
    expect(devAppStamp({ electronVersion: '44.6.0', iconBytes: icon })).not.toBe(s);
    expect(devAppStamp({ electronVersion: '44.5.1', iconBytes: Buffer.from('other') })).not.toBe(s);
  });
});
