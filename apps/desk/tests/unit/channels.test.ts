// Publishing accounts: the login state the built-in browser reads from a page (URL + what the page shows - never
// a cookie), the account list, labels, the cleaned user agent, the agency-mode preference.
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { channelKey, listChannels, loginState, nextAccountLabel } from '../../src/shared/channels';
import { parseAdapter, type Adapter } from '../../src/shared/publish/adapterSchema';
import { cleanUserAgent } from '../../src/main/publish/ua';
import { agencyMode, setPrefs } from '../../src/renderer/src/lib/prefs';

const adapters: Record<string, Adapter> = {};
for (const f of fs.readdirSync(path.resolve(import.meta.dirname, '../../adapters'))) {
  const r = parseAdapter(JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, '../../adapters', f), 'utf8')));
  if (r.ok) adapters[r.adapter.id] = r.adapter;
}
const upload = { fileInput: true, loginForm: false };
const loginBox = { fileInput: false, loginForm: true };

describe('login state from what the built-in browser saw', () => {
  it('login pages observed in the 2026-10-06 probe (no session) read as signed out', () => {
    // final URLs recorded by scripts/publishProbe.cjs for each adapter's upload URL without a login
    const seen: [string, string][] = [
      ['bilibili', 'https://passport.bilibili.com/login'],
      ['tiktok', 'https://www.tiktok.com/login?redirect_url=https%3A%2F%2Fwww.tiktok.com%2Ftiktokstudio%2Fupload'],
      ['wechat-channels', 'https://channels.weixin.qq.com/login.html'],
      ['x-web', 'https://x.com/i/jf/onboarding/web?redirect_after_login=%2Fhome&mode=login'],
      ['xiaohongshu', 'https://creator.xiaohongshu.com/login?source=&redirectReason=401&lastUrl=%252Fpublish%252Fpublish'],
      ['youtube-studio', 'https://accounts.google.com/v3/signin/identifier?continue=https://www.youtube.com/signin'],
    ];
    for (const [id, url] of seen) expect(loginState(url, adapters[id], null), id).toBe('out');
  });

  it('a login box on the upload URL itself (抖音, Instagram) is signed out, never signed in by URL alone', () => {
    expect(loginState('https://creator.douyin.com/creator-micro/content/upload', adapters.douyin, null)).toBeNull();
    expect(loginState('https://creator.douyin.com/creator-micro/content/upload', adapters.douyin, loginBox)).toBe('out');
    expect(loginState('https://www.instagram.com/', adapters.instagram, loginBox)).toBe('out');
  });

  it('the upload form (file input, no login form) on a platform host is signed in', () => {
    expect(loginState('https://creator.douyin.com/creator-micro/content/upload', adapters.douyin, upload)).toBe('in');
    expect(loginState('https://studio.youtube.com/channel/UC1/videos/upload', adapters['youtube-studio'], upload)).toBe('in');
    expect(loginState('https://evil.example.com/upload', adapters.douyin, upload)).toBeNull(); // other hosts say nothing
    expect(loginState('http://creator.douyin.com/x', adapters.douyin, upload)).toBeNull();
    expect(loginState('not a url', adapters.douyin, upload)).toBeNull();
  });
});

describe('accounts list', () => {
  it('labels + prefs -> rows in adapter order, names default to the label', () => {
    const rows = listChannels({ tiktok: ['main'], xiaohongshu: ['main', 'main-2'] }, { [channelKey('xiaohongshu', 'main')]: { name: '@我', times: ['12:00'], login: { state: 'in', at: '2026-10-06T10:00:00Z' } } }, ['xiaohongshu', 'tiktok']);
    expect(rows.map((r) => `${r.adapterId}/${r.account}:${r.name}:${r.login.state}`)).toEqual(['xiaohongshu/main:@我:in', 'xiaohongshu/main-2:main-2:unknown', 'tiktok/main:main:unknown']);
    expect(rows[0].times).toEqual(['12:00']);
    expect(nextAccountLabel([])).toBe('main');
    expect(nextAccountLabel(['main', 'main-2'])).toBe('main-3');
  });
});

describe('user agent of the built-in publish browser', () => {
  it('drops only the app and Electron tokens; Chrome version, OS and engine stay real', () => {
    const ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) video-studio-desk/0.1.0 Chrome/152.0.7977.130 Electron/44.5.1 Safari/537.36';
    expect(cleanUserAgent(ua, ['video-studio-desk'])).toBe('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.7977.130 Safari/537.36');
    expect(cleanUserAgent(ua.replace('video-studio-desk/0.1.0', 'video-studio desk/0.1.0'), [])).not.toMatch(/desk|Electron/);
  });
});

describe('agency mode preference', () => {
  it('is off by default and follows settings', () => {
    expect(agencyMode()).toBe(false);
    setPrefs({ agencyMode: true });
    expect(agencyMode()).toBe(true);
    setPrefs({});
    expect(agencyMode()).toBe(false);
  });
});
