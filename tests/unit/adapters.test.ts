import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadAdapters } from '../../src/main/publish/adapters';
import { adapterFor, basePlatform, hostAllowed, parseAdapter } from '../../src/shared/publish/adapterSchema';

const dir = path.resolve(__dirname, '../../adapters');
const raw = (f: string) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));

describe('adapter JSON schema', () => {
  it('every shipped adapter is valid', () => {
    const r = loadAdapters([dir]);
    expect(r.errors).toEqual([]);
    expect(r.adapters.map((a) => a.id).sort()).toEqual(['douyin', 'tiktok', 'xiaohongshu', 'youtube-studio']);
  });

  it('TikTok + YouTube are fillable (unverified), 小红书 + 抖音 are TODO placeholders', () => {
    const { adapters } = loadAdapters([dir]);
    const by = Object.fromEntries(adapters.map((a) => [a.id, a]));
    expect(by.tiktok.status).toBe('unverified');
    expect(by['youtube-studio'].status).toBe('unverified');
    expect(by.xiaohongshu.status).toBe('todo');
    expect(by.douyin.status).toBe('todo');
    for (const a of adapters) {
      expect(a.disclosure.zh.length).toBeGreaterThan(10);
      expect(a.disclosure.en.length).toBeGreaterThan(10);
    }
  });

  it('cannot express a click (strict schema)', () => {
    const a = raw('tiktok.json');
    expect(parseAdapter({ ...a, clickSelectors: ['button'] }).ok).toBe(false);
    expect(parseAdapter({ ...a, publishButton: { selectors: ['b'], click: true } }).ok).toBe(false);
    expect(parseAdapter({ ...a, fields: { ...a.fields, submit: { selectors: ['b'] } } }).ok).toBe(false);
  });

  it('rejects non-https pages and pages outside allowedHosts', () => {
    const a = raw('tiktok.json');
    expect(parseAdapter({ ...a, uploadUrl: 'http://www.tiktok.com/upload' }).ok).toBe(false);
    const r = parseAdapter({ ...a, uploadUrl: 'https://evil.example/upload' });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/allowedHosts/);
  });

  it('matches hosts and package platforms', () => {
    expect(hostAllowed('www.tiktok.com', ['*.tiktok.com'])).toBe(true);
    expect(hostAllowed('tiktok.com', ['*.tiktok.com'])).toBe(true);
    expect(hostAllowed('eviltiktok.com', ['*.tiktok.com'])).toBe(false);
    expect(basePlatform('tiktok-vertical')).toBe('tiktok');
    expect(basePlatform('youtube-shorts-vertical')).toBe('youtube-shorts');
    expect(basePlatform('xiaohongshu-full')).toBe('xiaohongshu');
    const { adapters } = loadAdapters([dir]);
    expect(adapterFor('youtube-shorts-vertical', adapters)?.id).toBe('youtube-studio');
    expect(adapterFor('youtube-horizontal', adapters)?.id).toBe('youtube-studio');
    expect(adapterFor('bilibili-horizontal', adapters)).toBeUndefined();
  });

  it('reports invalid files instead of half-using them', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'adp-'));
    fs.writeFileSync(path.join(tmp, 'bad.json'), JSON.stringify({ id: 'bad' }));
    fs.writeFileSync(path.join(tmp, 'tiktok.json'), JSON.stringify({ ...raw('tiktok.json'), status: 'verified', lastVerified: '2026-10-01' }));
    const r = loadAdapters([dir, tmp]);
    expect(r.errors.map((e) => path.basename(e.file))).toEqual(['bad.json']);
    expect(r.adapters.find((a) => a.id === 'tiktok')?.status).toBe('verified'); // local override wins
  });
});
