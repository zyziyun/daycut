// Record yourself: the recorder's plain logic (prefs, the big button, keys, the prompter's pace, takes), pause-aware
// recording time, and the main side (studio flag in session.json, a deleted take goes to the Trash, screen picker).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ shell: { trashItem: vi.fn() }, systemPreferences: {}, desktopCapturer: {} }));

import { blockReason, chosenTake, DEFAULT_PREFS, keyAction, lineSeconds, mainAction, parsePrefs, scriptLines, scriptSeconds, scrollStep, slugOf, WPM, type Take } from '../../src/renderer/src/create/record/recModel';
import { recordedSeconds, screenFailure } from '../../src/renderer/src/create/record/useRecorder';
import { Recorder, screenAccess, ScreenPick, toScreenSources } from '../../src/main/recorder';
import { validateIpc } from '../../src/shared/ipc';

describe('recorder model', () => {
  it('prefs: defaults, saved values, and junk falls back', () => {
    expect(parsePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(parsePrefs('not json')).toEqual(DEFAULT_PREFS);
    expect(parsePrefs('[1]')).toEqual(DEFAULT_PREFS);
    expect(parsePrefs(JSON.stringify({ speed: 'fast', size: 'l', studio: false, script: false }))).toMatchObject({ speed: 'fast', size: 'l', studio: false, script: false, countdown: true });
    expect(parsePrefs(JSON.stringify({ speed: 'warp', size: 7, studio: 'yes' }))).toMatchObject({ speed: 'normal', size: 'm', studio: true });
  });

  it('script lines and how long they take', () => {
    expect(scriptLines(' One.\n\n  Two. \n')).toEqual(['One.', 'Two.']);
    expect(lineSeconds('one two three four five six seven')).toBeCloseTo(3, 0);
    expect(lineSeconds('one two three four five six seven', WPM.fast)).toBeLessThan(lineSeconds('one two three four five six seven', WPM.slow));
    expect(scriptSeconds(['a', 'b'])).toBe(Math.round(2 * lineSeconds('a')));
  });

  it('the big button: why it cannot start, and what it does in each phase', () => {
    expect(blockReason({ phase: 'off', useScript: true, lines: 3, busy: false })).toBe('no-camera');
    expect(blockReason({ phase: 'ready', useScript: true, lines: 0, busy: false })).toBe('no-script');
    expect(blockReason({ phase: 'ready', useScript: false, lines: 0, busy: false })).toBeNull(); // speak freely: no script needed
    expect(blockReason({ phase: 'ready', useScript: true, lines: 2, busy: true })).toBe('busy');
    expect(blockReason({ phase: 'ready', useScript: true, lines: 2, busy: false })).toBeNull();
    expect(mainAction('ready', true)).toBe('countdown');
    expect(mainAction('ready', false)).toBe('start');
    expect(mainAction('countdown', true)).toBe('cancel');
    expect(mainAction('recording', true)).toBe('stop');
    expect(mainAction('paused', true)).toBe('stop');
    expect(mainAction('stopping', true)).toBeNull();
    expect(mainAction('off', true)).toBeNull();
  });

  it('keys: Space / P / ⌘R / arrows, never while typing', () => {
    expect(keyAction({ key: ' ' })).toBe('main');
    expect(keyAction({ key: 'p' })).toBe('pause');
    expect(keyAction({ key: 'r', metaKey: true })).toBe('retake');
    expect(keyAction({ key: 'R', ctrlKey: true })).toBe('retake');
    expect(keyAction({ key: 'r' })).toBeNull();
    expect(keyAction({ key: 'p', metaKey: true })).toBeNull();
    expect(keyAction({ key: 'ArrowDown' })).toBe('next');
    expect(keyAction({ key: 'ArrowUp' })).toBe('prev');
    expect(keyAction({ key: ' ', tag: 'TEXTAREA' })).toBeNull();
    expect(keyAction({ key: ' ', tag: 'INPUT' })).toBeNull();
    expect(keyAction({ key: ' ', editable: true })).toBeNull();
  });

  it('the prompter advances line by line and stops at the end', () => {
    const lines = ['one two', 'three four'];
    const d = lineSeconds('one two');
    expect(scrollStep({ lines, cur: 0, progress: 0, dt: d / 2, wpm: WPM.normal })).toEqual({ cur: 0, progress: 0.5, advanced: false });
    expect(scrollStep({ lines, cur: 0, progress: 0.9, dt: d, wpm: WPM.normal })).toEqual({ cur: 1, progress: 0, advanced: true });
    expect(scrollStep({ lines, cur: 1, progress: 0.9, dt: d, wpm: WPM.normal })).toEqual({ cur: 1, progress: 1, advanced: false });
    expect(scrollStep({ lines: [], cur: 0, progress: 0, dt: 1, wpm: WPM.normal })).toEqual({ cur: 0, progress: 0, advanced: false });
  });

  it('the take Finish uses, and session slugs', () => {
    const tk = (id: string): Take => ({ id, dir: `/r/${id}`, n: 1, secs: 3, lines: 0, total: 0, retakes: 0, thumb: null });
    expect(chosenTake([], null)).toBeNull();
    expect(chosenTake([tk('b'), tk('a')], 'a')?.id).toBe('a');
    expect(chosenTake([tk('b'), tk('a')], 'gone')?.id).toBe('b');
    expect(slugOf('Ep 4: Side Hustle!')).toBe('ep-4-side-hustle');
    expect(slugOf('副业')).toBe('recording');
    expect(slugOf('x'.repeat(60))).toHaveLength(40);
  });

  it('recording time leaves out pauses', () => {
    expect(recordedSeconds({ t0: 0, pausedMs: 0, pausedAt: null }, 5000)).toBe(5);
    expect(recordedSeconds({ t0: 0, pausedMs: 2000, pausedAt: null }, 5000)).toBe(3);
    expect(recordedSeconds({ t0: 0, pausedMs: 1000, pausedAt: 4000 }, 9000)).toBe(3); // paused since 4 s
  });
});

describe('recorder main side', () => {
  const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'rec-unit-'));

  it('writes the Studio sound choice into session.json (default on)', () => {
    const r = new Recorder(tmp());
    const a = r.begin({ slug: 'a', script: [], tracks: ['camera', 'mic'], studio: false });
    expect(JSON.parse(fs.readFileSync(path.join(a.dir, 'session.json'), 'utf8')).studio).toBe(false);
    const b = r.begin({ slug: 'b', script: ['x'], tracks: ['camera'] });
    expect(JSON.parse(fs.readFileSync(path.join(b.dir, 'session.json'), 'utf8')).studio).toBe(true);
  });

  it('a deleted take goes to the Trash; never a live one or one outside the recordings', async () => {
    const root = tmp();
    const r = new Recorder(root);
    const s = r.begin({ slug: 'take', script: [], tracks: ['camera'] });
    const trash = vi.fn(async () => undefined);
    await expect(r.discard({ sessionId: s.sessionId }, trash)).rejects.toThrow('rec.live');
    r.end({ sessionId: s.sessionId });
    await r.discard({ sessionId: s.sessionId }, trash);
    expect(trash).toHaveBeenCalledWith(s.dir);
    await expect(r.discard({ sessionId: '20261006-120000-nope' }, trash)).rejects.toThrow('rec.no-session');
    expect(() => validateIpc('rec:discard', { sessionId: '../x' })).toThrow();
    expect(validateIpc('rec:discard', { sessionId: s.sessionId })).toEqual({ sessionId: s.sessionId });
    expect(validateIpc('rec:begin', { slug: 'a', script: [], tracks: ['camera'], studio: false })).toMatchObject({ studio: false });
  });

  it('screen picker: one armed pick per share, expiring; screens first; never our own window', () => {
    const p = new ScreenPick(1000);
    expect(p.take(0)).toBeNull();
    p.arm('screen:1:0', 0);
    expect(p.take(500)).toBe('screen:1:0');
    expect(p.take(600)).toBeNull(); // used once
    p.arm('window:9:0', 0);
    expect(p.take(1500)).toBeNull(); // expired
    const img = (empty: boolean) => ({ isEmpty: () => empty, toDataURL: () => 'data:image/png;base64,AA' }) as unknown as Electron.NativeImage;
    const rows = toScreenSources(
      [
        { id: 'window:5:0', name: 'Keynote', thumbnail: img(false) },
        { id: 'window:7:0', name: 'Reelfold', thumbnail: img(false) },
        { id: 'screen:1:0', name: 'Built-in Display', thumbnail: img(true) },
      ],
      ['window:7:0'],
    );
    expect(rows.map((r) => [r.id, r.kind, r.thumb])).toEqual([
      ['screen:1:0', 'screen', ''],
      ['window:5:0', 'window', 'data:image/png;base64,AA'],
    ]);
  });

  it('Screen Recording access: macOS asks; Windows / Linux need none; failures are never silent', () => {
    expect(screenAccess('granted', 'darwin')).toBe('granted');
    expect(screenAccess('denied', 'darwin')).toBe('denied');
    expect(screenAccess('not-determined', 'darwin')).toBe('denied');
    expect(screenAccess('unknown', 'win32')).toBe('granted');
    expect(screenFailure(Object.assign(new Error('Permission denied by system'), { name: 'NotAllowedError' }))).toBe('denied');
    expect(screenFailure(Object.assign(new Error('Timeout starting video source'), { name: 'AbortError' }))).toEqual({ error: 'Timeout starting video source' });
    expect(validateIpc('rec:screenPick', { id: 'screen:1:0' })).toEqual({ id: 'screen:1:0' });
    expect(() => validateIpc('rec:screenPick', { id: '' })).toThrow();
  });
});
