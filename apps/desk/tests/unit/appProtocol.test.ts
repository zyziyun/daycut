import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { resolveAppFile } from '../../src/main/appProtocol';

describe('app:// file resolution', () => {
  const root = '/app/out/renderer';
  it('serves renderer files and falls back to index for routes', () => {
    expect(resolveAppFile(root, '/')).toBe('index');
    expect(resolveAppFile(root, '/assets/index-abc.js')).toBe(path.join(root, 'assets/index-abc.js'));
    expect(resolveAppFile(root, '/projects')).toBe('index');
  });
  it('refuses traversal with either separator, encoded or not', () => {
    for (const p of ['/../secrets.json', '/assets/%2e%2e/%2e%2e/x.js', '/..%5C..%5Cwindows%5Cwin.ini', '/assets\\..\\..\\x.js', '/%00.js', '/C:/x.js', '/%E0%A4%A.js'])
      expect(resolveAppFile(root, p), p).toBeNull();
  });
  it('stays inside the root on Windows paths too', () => {
    const w = 'C:\\Program Files\\Reelfold\\resources\\app.asar\\out\\renderer';
    expect(resolveAppFile(w, '/..%5C..%5Cx.js', path.win32)).toBeNull();
    expect(resolveAppFile(w, '/assets/a.js', path.win32)).toBe(path.win32.join(w, 'assets', 'a.js'));
  });
  it('does not serve other file types', () => {
    expect(resolveAppFile(root, '/main.cjs')).toBe('index');
  });
});
