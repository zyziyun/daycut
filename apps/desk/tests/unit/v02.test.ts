import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { cleanupPathOk } from '../../src/main/cleanupPolicy';
import { SecretStore, type Crypto } from '../../src/main/secrets';
import { EngineClient } from '../../src/shared/engineClient';
import { IPC_CHANNELS, validateIpc } from '../../src/shared/ipc';
import { ReviewTimer } from '../../src/shared/reviewTimer';
import { acceptedSegments, joinWords, median, nudgeEdge, overlaps, setEdge, snapToWord, WEEKLY_COLUMNS, wordsIn, type ReviewedSegment, type Word } from '../../src/shared/v02';

const words: Word[] = [
  { w: '今天', t: 0.4, te: 0.8 },
  { w: '讲', t: 0.9, te: 1.1 },
  { w: 'RAG', t: 1.2, te: 1.6 },
  { w: '切块', t: 2.4, te: 2.9 },
  { w: '策略', t: 3.0, te: 3.5 },
  { w: '重排', t: 5.0, te: 5.6 },
];

describe('v0.2 IPC schemas', () => {
  it('has a schema for every new channel', () => {
    for (const c of ['firstRun:complete', 'secrets:status', 'secrets:set', 'secrets:clear', 'persona:import', 'persona:clear', 'file:saveText', 'dialog:openFiles']) {
      expect(IPC_CHANNELS).toContain(c);
    }
  });

  it('validates keys without echoing them back', () => {
    expect(validateIpc('secrets:set', { name: 'anthropic', value: 'test-key-0123456789' })).toEqual({ name: 'anthropic', value: 'test-key-0123456789' });
    expect(() => validateIpc('secrets:set', { name: 'aws', value: 'test-key-0123456789' })).toThrow();
    expect(() => validateIpc('secrets:set', { name: 'openai', value: 'has space inside' })).toThrow();
    expect(() => validateIpc('secrets:set', { name: 'openai', value: 'short' })).toThrow();
    expect(() => validateIpc('secrets:set', { name: 'openai', value: 'x'.repeat(401) })).toThrow();
    expect(() => validateIpc('secrets:clear', { name: 'openai', extra: 1 })).toThrow();
  });

  it('validates platforms, persona paths and export names', () => {
    expect(validateIpc('firstRun:complete', { defaultPlatforms: ['xiaohongshu:full', 'tiktok'] }).defaultPlatforms).toHaveLength(2);
    expect(() => validateIpc('firstRun:complete', { defaultPlatforms: [] })).toThrow();
    expect(() => validateIpc('firstRun:complete', { defaultPlatforms: ['Tik Tok'] })).toThrow();
    expect(() => validateIpc('settings:set', { defaultPlatforms: ['$(rm)'] })).toThrow();
    expect(validateIpc('settings:set', { cleanupDays: 30 })).toEqual({ cleanupDays: 30 });
    expect(() => validateIpc('settings:set', { cleanupDays: 1000 })).toThrow();
    expect(validateIpc('persona:import', { path: '/Users/me/persona.local.yaml' }).path).toContain('persona');
    expect(() => validateIpc('persona:import', { path: '/etc/passwd' })).toThrow();
    expect(() => validateIpc('persona:import', { path: 'persona.yaml' })).toThrow();
    expect(validateIpc('file:saveText', { defaultName: 'weekly_metrics.csv', text: 'a,b' }).defaultName).toBe('weekly_metrics.csv');
    expect(() => validateIpc('file:saveText', { defaultName: '../../.zshrc', text: '' })).toThrow();
    expect(() => validateIpc('file:saveText', { defaultName: 'x.sh', text: '' })).toThrow();
    expect(() => validateIpc('dialog:openFile', { kind: 'any' })).toThrow();
    expect(validateIpc('dialog:openFile', { kind: 'persona' })).toEqual({ kind: 'persona' });
  });
});

describe('ReviewTimer', () => {
  it('counts active time and stops at the idle cutoff', () => {
    const tm = new ReviewTimer(0, { idleCutoffS: 30 });
    tm.activity(10_000);
    expect(tm.seconds(20_000)).toBe(20);
    // no input for 5 minutes: only 30 s after the last activity count
    expect(tm.seconds(320_000)).toBe(40);
    tm.activity(330_000);
    expect(tm.seconds(335_000)).toBe(45);
  });

  it('ignores hidden / unfocused time', () => {
    const tm = new ReviewTimer(0, { idleCutoffS: 60 });
    tm.setVisible(false, 5_000);
    tm.activity(30_000);
    expect(tm.seconds(40_000)).toBe(5);
    tm.setVisible(true, 40_000);
    tm.setFocused(false, 50_000);
    expect(tm.seconds(90_000)).toBe(15);
    expect(tm.isIdle(90_000)).toBe(true);
  });

  it('a playing video keeps the clock running without input', () => {
    const tm = new ReviewTimer(0, { idleCutoffS: 10 });
    tm.setPlaying(true, 0);
    expect(tm.seconds(60_000)).toBe(60);
    tm.setPlaying(false, 60_000);
    expect(tm.seconds(120_000)).toBe(70);
  });

  it('take() reports increments for timing stop events', () => {
    const tm = new ReviewTimer(0, { idleCutoffS: 60 });
    expect(tm.take(12_000)).toBe(12);
    expect(tm.take(15_000)).toBe(3);
    expect(tm.take(15_000)).toBe(0);
  });
});

describe('segment helpers', () => {
  it('snaps to word edges', () => {
    expect(snapToWord(1.0, words, 'start')).toBe(0.9);
    expect(snapToWord(1.0, words, 'end')).toBe(1.1);
    expect(snapToWord(4.4, words, 'start')).toBe(5.0);
    expect(snapToWord(7, [], 'end')).toBe(7);
  });

  it('nudges to the previous / next edge', () => {
    expect(nudgeEdge(1.2, words, 'start', 1)).toBe(2.4);
    expect(nudgeEdge(1.2, words, 'start', -1)).toBe(0.9);
    expect(nudgeEdge(0.4, words, 'start', -1)).toBe(0.4);
    expect(nudgeEdge(3.5, words, 'end', -1)).toBe(2.9);
  });

  it('sets edges with a minimum length', () => {
    const seg = { id: 's001', start: 0.4, end: 5.6, title: 't' };
    expect(setEdge(seg, 'start', 2.5, words).start).toBe(2.4);
    expect(setEdge(seg, 'start', 5.0, words).start).toBe(0.4); // would be < 3 s
    expect(setEdge(seg, 'end', 3.4, words).end).toBe(3.5);
  });

  it('collects accepted segments in time order and flags overlaps', () => {
    const segs: ReviewedSegment[] = [
      { id: 'b', start: 10, end: 20, title: ' B ', accepted: true },
      { id: 'a', start: 0, end: 12, title: 'A', accepted: true },
      { id: 'c', start: 30, end: 40, title: 'C', accepted: false },
      { id: 'd', start: 50, end: 60, title: '   ', accepted: true },
    ];
    expect(acceptedSegments(segs).map((s) => s.id)).toEqual(['a', 'b']);
    expect(acceptedSegments(segs)[1].title).toBe('B');
    expect('accepted' in acceptedSegments(segs)[0]).toBe(false);
    expect([...overlaps(segs)].sort()).toEqual(['a', 'b']);
  });

  it('finds words in a range and joins them', () => {
    expect(wordsIn(words, 0.9, 2.9).map((w) => w.w)).toEqual(['讲', 'RAG', '切块']);
    expect(joinWords([{ w: 'top', t: 0, te: 1 }, { w: 'k', t: 1, te: 2 }, { w: '检索', t: 2, te: 3 }])).toBe('top k检索');
    expect(median([3, 1, 2])).toBe(2);
    expect(median([])).toBeNull();
  });

  it('weekly columns match the gtm weekly metrics sheet (header kept in tests/fixtures)', () => {
    const f = path.resolve(import.meta.dirname, '../fixtures/weekly_metrics.csv');
    expect(fs.readFileSync(f, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/)[0].split(',')).toEqual([...WEEKLY_COLUMNS]);
  });
});

describe('SecretStore', () => {
  const crypto = (available = true, backend = 'keychain'): Crypto => ({
    isEncryptionAvailable: () => available,
    encryptString: (s) => Buffer.from([...s].reverse().join(''), 'utf8'),
    decryptString: (b) => [...b.toString('utf8')].reverse().join(''),
    getSelectedStorageBackend: () => backend,
  });

  it('stores only ciphertext and exposes presence, not values', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-sec-'));
    const s = new SecretStore(dir, crypto());
    expect(s.status()).toEqual({ backend: 'keychain', keys: { anthropic: false, openai: false, deepseek: false, qwen: false, kimi: false, glm: false, openrouter: false, minimax: false, gemini: false, ark: false, kling: false } });
    const st = s.set('anthropic', 'test-key-abcdef');
    expect(st.keys.anthropic).toBe(true);
    expect(JSON.stringify(st)).not.toContain('test-key-abcdef');
    expect(fs.readFileSync(path.join(dir, 'secrets.json'), 'utf8')).not.toContain('test-key-abcdef');
    expect(s.env()).toEqual({ ANTHROPIC_API_KEY: 'test-key-abcdef' });
    s.clear('anthropic');
    expect(s.env()).toEqual({});
  });

  it('refuses to store without a keychain', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-sec-'));
    expect(() => new SecretStore(dir, crypto(false)).set('openai', 'test-key-abcdef')).toThrow(/keychain/);
    expect(() => new SecretStore(dir, crypto(true, 'basic_text'), 'linux').set('openai', 'test-key-abcdef')).toThrow(/keychain/);
  });
});

describe('cleanup policy', () => {
  const home = '/Users/me';
  it('only trashes media files / folders deep enough, never home or top folders', () => {
    expect(cleanupPathOk('/Users/me/Movies/raw/rec.mp4', false, home)).toBe(true);
    expect(cleanupPathOk('/Users/me/Movies/raw', true, home)).toBe(true);
    expect(cleanupPathOk('/Users/me', true, home)).toBe(false);
    expect(cleanupPathOk('/Users/me/Desktop', true, home)).toBe(false);
    expect(cleanupPathOk('/Users/me/notes.txt', false, home)).toBe(false);
    expect(cleanupPathOk('/Users/me/Movies/../.ssh/id.mp4', false, home)).toBe(false);
    expect(cleanupPathOk('relative.mp4', false, home)).toBe(false);
  });
  it('Windows paths: drive letters, any case, known folders, UNC shares', () => {
    const w = path.win32;
    const h = 'C:\\Users\\Me';
    expect(cleanupPathOk('C:\\Users\\Me\\Videos\\raw\\录屏 1.mp4', false, h, w)).toBe(true);
    expect(cleanupPathOk('D:\\素材\\2026\\rec.mov', false, h, w)).toBe(true);
    expect(cleanupPathOk('D:\\素材\\2026', true, h, w)).toBe(true);
    expect(cleanupPathOk('c:\\users\\me', true, h, w)).toBe(false);
    expect(cleanupPathOk('C:\\Users\\Me\\videos', true, h, w)).toBe(false);
    expect(cleanupPathOk('C:\\Users\\Me\\OneDrive\\', true, h, w)).toBe(false);
    expect(cleanupPathOk('C:\\Users', true, h, w)).toBe(false);
    expect(cleanupPathOk('D:\\rec.mp4', false, h, w)).toBe(false);
    expect(cleanupPathOk('\\\\nas\\share', true, h, w)).toBe(false);
    expect(cleanupPathOk('\\\\nas\\share\\raw\\a.mp4', false, h, w)).toBe(true);
    expect(cleanupPathOk('C:\\Users\\Me\\Videos\\..\\x.mp4', false, h, w)).toBe(false);
  });
});

describe('EngineClient v0.2 routes', () => {
  const BASE = 'app://desk';
  const f = () => vi.fn(async (_u: string, _i?: RequestInit) => new Response('{"ok":true}', { status: 200 }));

  it('builds the expected URLs and bodies', async () => {
    const fetch = f();
    const c = new EngineClient(BASE, 't'.repeat(48), fetch);
    await c.editJob('abcdefabcdef', 's001', { op: 'caption', cue: 2, text: '改好的字幕' });
    await c.timing('abcdefabcdef', { job: 's001', event: 'stop', what: 'review', active_s: 12.5 });
    await c.metrics({ client: 'acme' });
    await c.planToBatch('0123456789ab', { name: 'b', segments: [], platforms: ['tiktok'] });
    const calls = fetch.mock.calls.map(([u, i]) => [u.replace(BASE, ''), i?.method, i?.body ? JSON.parse(String(i.body)) : null]);
    expect(calls).toEqual([
      ['/api/batches/abcdefabcdef/jobs/s001/edit', 'POST', { op: 'caption', cue: 2, text: '改好的字幕' }],
      ['/api/batches/abcdefabcdef/timing', 'POST', { job: 's001', event: 'stop', what: 'review', active_s: 12.5 }],
      ['/api/metrics?client=acme', 'GET', null],
      ['/api/plans/0123456789ab/batch', 'POST', { name: 'b', segments: [], platforms: ['tiktok'] }],
    ]);
  });

  it('rejects bad ids before any request', async () => {
    const fetch = f();
    const c = new EngineClient(BASE, 't'.repeat(48), fetch);
    await expect(async () => c.client('../etc')).rejects.toThrow();
    await expect(async () => c.plan('zzz')).rejects.toThrow();
    await expect(async () => c.timing('abcdefabcdef', { job: '../x', event: 'start', what: 'review' })).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
});
