// The Mac App Store (Lite) build: what it can do, which AI providers it offers, how picked folders are kept, and the
// requests the in-app HTML renderer accepts. The default (no BUILD_EDITION) is the full edition.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { availableProviders, defaultChoice, normalizeRoutes, providerAllowed, routesFromEngine } from '../../src/shared/aiRoutes';
import { capsFor, CAPS, EDITION, editionFrom } from '../../src/shared/edition';
import { AccessStore, commonFolder, inside } from '../../src/main/access';
import { parseJob } from '../../src/main/htmlRender';

const lite = capsFor('mas');

describe('edition', () => {
  it('is the full edition unless built with BUILD_EDITION=mas', () => {
    expect(EDITION).toBe('full');
    expect(CAPS).toEqual(capsFor('full'));
    expect(editionFrom('mas')).toBe('mas');
    expect(editionFrom('MAS')).toBe('full');
    expect(editionFrom(undefined)).toBe('full');
  });
  it('Lite has no CLI logins, updater, usage counts, Chromium download or arbitrary folders', () => {
    expect(lite).toEqual({ cliLogins: false, anyFolder: false, autoUpdate: false, usageCounts: false, chromiumDownload: false });
  });
});

describe('AI providers per edition', () => {
  it('Lite offers API keys and local models only', () => {
    const ids = availableProviders(lite);
    expect(ids).not.toContain('claude-code');
    expect(ids).not.toContain('codex');
    expect(ids).toEqual(expect.arrayContaining(['anthropic', 'openai', 'deepseek', 'ollama', 'lmstudio']));
    expect(availableProviders(capsFor('full'))).toContain('claude-code');
    expect(providerAllowed('codex', lite)).toBe(false);
    expect(providerAllowed('none', lite)).toBe(true);
  });
  it('a fresh Lite profile routes to the API, then a local model - never a CLI', () => {
    expect(defaultChoice(lite)).toEqual({ provider: 'anthropic', model: null, fallback: ['openai', 'ollama'] });
    expect(routesFromEngine(null, lite).default.provider).toBe('anthropic');
    // a persona that names Claude Code (copied from the full version) falls back to the Lite default
    const r = routesFromEngine({ default: { provider: 'claude-code', fallback: ['codex', 'openai'] }, intake: { provider: 'codex', source: 'persona llm.tasks.intake' } }, lite);
    expect(r.default.provider).toBe('anthropic');
    expect(r.tasks.plan).toBeUndefined();
    const keep = routesFromEngine({ default: { provider: 'deepseek', fallback: ['codex', 'ollama'] } }, lite);
    expect(keep.default).toEqual({ provider: 'deepseek', model: null, fallback: ['ollama'] });
  });
  it('the full edition still defaults to the subscription CLIs', () => {
    expect(routesFromEngine(null, capsFor('full')).default).toEqual({ provider: 'claude-code', model: null, fallback: ['codex'] });
    expect(normalizeRoutes({ default: { provider: 'codex', fallback: [] }, tasks: {} }).default.provider).toBe('codex');
  });
});

describe('picked folders (security-scoped bookmarks)', () => {
  const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-access-'));
  it('commonFolder / inside', () => {
    expect(commonFolder(['/home/me/Movies/x.mp4', '/home/me/Movies/y.mov'], '/')).toBe('/home/me/Movies');
    expect(commonFolder(['/home/me/Movies/x.mp4', '/home/me/Desktop/s/y.mov'], '/')).toBe('/home/me');
    expect(commonFolder(['/home/me/Shoot/.'], '/')).toBe('/home/me/Shoot');
    expect(commonFolder([], '/')).toBeNull();
    expect(inside('/a/b/c', '/a/b', '/')).toBe(true);
    expect(inside('/a/bc', '/a/b', '/')).toBe(false);
    expect(inside('/a/b/', '/a/b', '/')).toBe(true);
  });
  it('keeps bookmarks, starts them at launch, stops them on quit', () => {
    const dir = tmp();
    const started: string[] = [];
    const stopped: string[] = [];
    const api = { start: (b: string) => (started.push(b), () => stopped.push(b)) };
    const a = new AccessStore(dir, api, true);
    a.add(['/Volumes/Shoot/day1', '/home/me/Movies/x.mp4'], ['Ym0x', undefined]);
    expect(a.paths()).toEqual(['/Volumes/Shoot/day1']); // a pick without a bookmark is not remembered
    expect(a.covers('/Volumes/Shoot/day1/a.mov')).toBe(true);
    expect(a.covers('/Volumes/Shoot/day2/a.mov')).toBe(false);
    expect(a.covers('/x/container/file', ['/x/container'])).toBe(true);
    const b = new AccessStore(dir, api, true);
    expect(b.restore()).toEqual(['/Volumes/Shoot/day1']);
    expect(started).toEqual(['Ym0x', 'Ym0x']);
    b.stopAll();
    expect(stopped).toEqual(['Ym0x']);
    b.remove('/Volumes/Shoot/day1');
    expect(new AccessStore(dir, api, true).paths()).toEqual([]);
  });
  it('a bookmark that no longer resolves is skipped', () => {
    const dir = tmp();
    fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ grants: [{ path: '/gone', bookmark: 'eA==', at: '' }] }));
    const s = new AccessStore(dir, { start: () => { throw new Error('stale'); } }, true);
    expect(s.restore()).toEqual([]);
  });
  it('the full edition reads anything and stores nothing', () => {
    const dir = tmp();
    const s = new AccessStore(dir, {}, false);
    s.add(['/a'], ['Ym0x']);
    expect(s.covers('/anything')).toBe(true);
    expect(fs.existsSync(path.join(dir, 'access.json'))).toBe(false);
  });
});

describe('in-app HTML render requests', () => {
  const ok = (f: string) => f.startsWith('/c/');
  it('accepts a local page and a PNG next to it', () => {
    expect(parseJob({ file: '/c/p/cover.html', out: '/c/p/cover.png', width: 1080, height: 1920, scale: 2 }, ok)).toEqual({ file: '/c/p/cover.html', out: '/c/p/cover.png', width: 1080, height: 1920, scale: 2, wait: 500, transparent: false });
  });
  it('rejects pages it may not read, odd sizes and other file types', () => {
    expect(parseJob({ file: '/etc/x.html', out: '/c/x.png', width: 10, height: 10 }, ok)).toMatch(/not readable/);
    expect(parseJob({ file: '/c/x.svg', out: '/c/x.png', width: 10, height: 10 }, ok)).toMatch(/\.html/);
    expect(parseJob({ file: '/c/x.html', out: '/tmp/x.png', width: 10, height: 10 }, ok)).toMatch(/next to the page/);
    expect(parseJob({ file: '/c/x.html', out: '/c/x.png', width: 0, height: 10 }, ok)).toMatch(/width/);
    expect(parseJob({ file: '/c/x.html', out: '/c/x.png', width: 10, height: 10, scale: 9 }, ok)).toMatch(/scale/);
    expect(parseJob('x', ok)).toMatch(/JSON/);
  });
});
