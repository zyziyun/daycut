import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { isAllowedMediaPath, mediaUrl, pathFromMediaUrl } from '../../src/main/media';
import { buildCsp, isAppUrl, isLocalEngineRequest, isSafeExternal } from '../../src/main/security';
import { buildReply } from '../../src/shared/cleanupReply';

describe('cleanup reply from transcript toggles', () => {
  it('approves cut confirm edits and keeps un-cut auto edits', () => {
    expect(
      buildReply([
        { id: 1, action: 'auto', cut: true },
        { id: 2, action: 'confirm', cut: true },
        { id: 3, action: 'confirm', cut: false },
        { id: 4, action: 'auto', cut: false },
        { id: 5, action: 'confirm', cut: true },
        { id: 6, action: 'keep', cut: false },
      ]),
    ).toBe('确认 2,5 / 保留 4');
    expect(buildReply([{ id: 1, action: 'auto', cut: true }])).toBe('');
  });
});

describe('security helpers', () => {
  it('builds a strict production CSP', () => {
    const csp = buildCsp({ dev: false });
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("script-src 'self';");
    expect(csp).not.toContain('unsafe-eval');
    // the engine is app://desk/api: same origin, no port, nothing on 127.0.0.1
    expect(csp).toContain("connect-src 'self';");
    expect(csp).not.toContain('127.0.0.1');
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("frame-src 'none'");
  });

  it('dev CSP only adds what Vite needs', () => {
    const csp = buildCsp({ dev: true, devServerUrl: 'http://localhost:5173' });
    expect(csp).toContain('ws://localhost:5173');
    expect(csp).toContain("connect-src 'self' app://desk ws://localhost:5173");
    expect(csp).not.toContain('unsafe-eval');
  });

  it('classifies URLs', () => {
    expect(isAppUrl('app://desk/index.html', 'app://desk')).toBe(true);
    expect(isAppUrl('https://www.tiktok.com', 'app://desk')).toBe(false);
    expect(isSafeExternal('https://example.com')).toBe(true);
    expect(isSafeExternal('file:///etc/passwd')).toBe(false);
    expect(isSafeExternal('javascript:alert(1)')).toBe(false);
    expect(isLocalEngineRequest('http://127.0.0.1:4321/api/batches')).toBe(true);
    expect(isLocalEngineRequest('http://localhost:9/x')).toBe(true);
    expect(isLocalEngineRequest('https://www.tiktok.com/')).toBe(false);
  });
});

describe('media protocol allowlist', () => {
  const roots = ['/Users/me/batch-a', '/Users/me/batch-a/package'];
  it('allows media inside roots only', () => {
    expect(isAllowedMediaPath('/Users/me/batch-a/jobs/s1/sheet.jpg', roots, path.posix)).toBe(true);
    expect(isAllowedMediaPath('/Users/me/batch-a/../secret.mp4', roots, path.posix)).toBe(false);
    expect(isAllowedMediaPath('/Users/me/batch-ab/x.mp4', roots, path.posix)).toBe(false);
    expect(isAllowedMediaPath('/Users/me/batch-a/batch.db', roots, path.posix)).toBe(false);
    expect(isAllowedMediaPath('relative/x.mp4', roots, path.posix)).toBe(false);
  });
  it('Windows: drive letters in any case, no climbing, no sibling prefix', () => {
    const w = ['C:\\Users\\Me\\batch-a', 'D:\\素材'];
    expect(isAllowedMediaPath('c:\\users\\me\\batch-a\\jobs\\s1\\预览 1.mp4', w, path.win32)).toBe(true);
    expect(isAllowedMediaPath('D:\\素材\\a.mov', w, path.win32)).toBe(true);
    expect(isAllowedMediaPath('C:\\Users\\Me\\batch-ab\\x.mp4', w, path.win32)).toBe(false);
    expect(isAllowedMediaPath('C:\\Users\\Me\\batch-a\\..\\x.mp4', w, path.win32)).toBe(false);
    expect(isAllowedMediaPath('E:\\素材\\a.mov', w, path.win32)).toBe(false);
  });
  it('round-trips URLs', () => {
    const p = '/Users/me/batch-a/jobs/s 1/预览.mp4';
    expect(pathFromMediaUrl(mediaUrl(p))).toBe(p);
    const w = 'C:\\Users\\李 雷\\batch #1\\预览.mp4';
    expect(pathFromMediaUrl(mediaUrl(w))).toBe(w);
    expect(pathFromMediaUrl('https://x/y')).toBeNull();
  });
});
