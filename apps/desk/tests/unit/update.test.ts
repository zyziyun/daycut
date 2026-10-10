// The in-app update: the state machine main/updater.ts feeds with electron-updater's events, release notes as text,
// when the one-time card shows ("Later" lasts for this launch), and the restart-with-projects-running rules.
import { describe, expect, it } from 'vitest';
import { errorKey, noteToText, notesText, reduceUpdate, restartPlan, restartWhenDoneDue, shouldCheck, shouldShowCard, type UpdateEvent, type UpdateStateMsg } from '../../src/shared/update';

const idle: UpdateStateMsg = { state: 'idle', current: '0.2.4' };
const run = (s: UpdateStateMsg, ...evs: UpdateEvent[]) => evs.reduce(reduceUpdate, s);

describe('reduceUpdate', () => {
  it('check -> available -> downloading -> ready, keeping version, notes and the running version', () => {
    const s1 = run(idle, { type: 'checking' });
    expect(s1).toEqual({ state: 'checking', current: '0.2.4', checkedAt: undefined });
    const s2 = run(s1, { type: 'available', version: '0.2.5', notes: 'Faster cuts', at: 1000 });
    expect(s2).toMatchObject({ state: 'available', version: '0.2.5', notes: 'Faster cuts', percent: 0, checkedAt: 1000, current: '0.2.4' });
    const s3 = run(s2, { type: 'progress', percent: 41.6 });
    expect(s3).toMatchObject({ state: 'downloading', version: '0.2.5', percent: 42, notes: 'Faster cuts' });
    const s4 = run(s3, { type: 'downloaded', version: '0.2.5', at: 2000 });
    expect(s4).toMatchObject({ state: 'ready', version: '0.2.5', percent: 100, notes: 'Faster cuts', current: '0.2.4' });
  });
  it('up to date records when it was checked', () => {
    expect(run(idle, { type: 'checking' }, { type: 'none', at: 5 })).toEqual({ state: 'none', current: '0.2.4', checkedAt: 5 });
  });
  it('progress is clamped and rounded', () => {
    expect(run({ ...idle, state: 'available', version: '1' }, { type: 'progress', percent: 140 }).percent).toBe(100);
    expect(run({ ...idle, state: 'available', version: '1' }, { type: 'progress', percent: Number.NaN }).percent).toBe(0);
  });
  it('a failed check says "check" (offline), a failed download says "download" and keeps the version', () => {
    const c = run(idle, { type: 'checking' }, { type: 'error', message: 'net::ERR_INTERNET_DISCONNECTED\n  at …', at: 9 });
    expect(c).toMatchObject({ state: 'error', errorStage: 'check', error: 'net::ERR_INTERNET_DISCONNECTED', checkedAt: 9 });
    expect(c.version).toBeUndefined();
    const d = run(idle, { type: 'available', version: '0.2.5', at: 1 }, { type: 'progress', percent: 10 }, { type: 'error', message: 'sha512 checksum mismatch', at: 2 });
    expect(d).toMatchObject({ state: 'error', errorStage: 'download', version: '0.2.5', error: 'sha512 checksum mismatch' });
  });
  it('a ready update stays ready through a re-check of the same version', () => {
    const r = run(idle, { type: 'downloaded', version: '0.2.5', notes: 'n', at: 1 });
    expect(run(r, { type: 'checking' }, { type: 'available', version: '0.2.5', at: 2 }, { type: 'progress', percent: 3 })).toEqual(r);
    expect(run(r, { type: 'none', at: 3 })).toEqual({ ...r, checkedAt: 3 });
  });
  it('an error once ready is the installer failing: "install", version kept', () => {
    const r = run(idle, { type: 'downloaded', version: '0.2.5', at: 1 });
    expect(run(r, { type: 'error', message: 'Code signature did not pass validation', at: 2 })).toMatchObject({ state: 'error', errorStage: 'install', version: '0.2.5' });
    expect(run(r, { type: 'install-failed', message: 'Reelfold did not restart within 60 s' })).toMatchObject({ state: 'error', errorStage: 'install', version: '0.2.5' });
  });
  it('disabled (Mac App Store / store builds / development) never changes', () => {
    const off: UpdateStateMsg = { state: 'disabled', current: '0.2.4' };
    expect(run(off, { type: 'checking' }, { type: 'available', version: '9', at: 1 }, { type: 'downloaded', version: '9' })).toBe(off);
  });
});

describe('shouldCheck', () => {
  it('launch / periodic checks skip while busy and once an update is ready', () => {
    expect(shouldCheck(idle, false)).toBe(true);
    expect(shouldCheck({ state: 'none' }, false)).toBe(true);
    expect(shouldCheck({ state: 'error' }, false)).toBe(true);
    for (const state of ['disabled', 'checking', 'downloading', 'ready', 'available'] as const) expect(shouldCheck({ state }, false)).toBe(false);
  });
  it('a check she asks for also retries an offered update, never during a download or once ready', () => {
    expect(shouldCheck({ state: 'available' }, true)).toBe(true);
    expect(shouldCheck({ state: 'error', errorStage: 'download' }, true)).toBe(true);
    expect(shouldCheck({ state: 'downloading' }, true)).toBe(false);
    expect(shouldCheck({ state: 'ready' }, true)).toBe(false);
  });
});

describe('release notes as text', () => {
  it("GitHub's release body (HTML) becomes headings, bullets and text; no markup survives", () => {
    const html =
      '<h2>Reelfold 0.2.5 · 千剪 0.2.5</h2>\n<p>Autopilot, faster.</p>\n<h3>Highlights</h3>\n<ul>\n<li><strong>Update prompt</strong>: restart in one click</li>\n<li>Fixes &amp; more &lt;3 &#39;ok&#39;</li>\n</ul><script>alert(1)</script>';
    const txt = noteToText(html);
    expect(txt).toBe("Reelfold 0.2.5 · 千剪 0.2.5\nAutopilot, faster.\n\nHighlights\n• Update prompt: restart in one click\n• Fixes & more <3 'ok'");
    expect(txt).not.toMatch(/<[a-z/]|alert/i);
  });
  it('Markdown (a generic feed) loses its markup too', () => {
    expect(noteToText('## Reelfold 0.2.5\n\n- **Faster** cuts\n- See [the docs](https://x.y)\n')).toBe('Reelfold 0.2.5\n• Faster cuts\n• See the docs');
  });
  it('a full changelog (one entry per version) and nothing at all', () => {
    expect(notesText([{ version: '0.2.6', note: '<p>B</p>' }, { version: '0.2.5', note: null }])).toBe('0.2.6\nB\n\n0.2.5');
    expect(notesText(null)).toBe('');
    expect(notesText('x'.repeat(50), 10)).toBe('xxxxxxxxxx\n…');
  });
});

describe('the prompt', () => {
  const ready: UpdateStateMsg = { state: 'ready', version: '0.2.5' };
  it('the card shows once per version per launch, not after "Later"', () => {
    expect(shouldShowCard(ready, new Set(), new Set())).toBe(true);
    expect(shouldShowCard(ready, new Set(), new Set(['0.2.5']))).toBe(false);
    expect(shouldShowCard(ready, new Set(['0.2.5']), new Set())).toBe(false);
    expect(shouldShowCard({ state: 'ready', version: '0.2.6' }, new Set(['0.2.5']), new Set(['0.2.5']))).toBe(true); // a newer one asks again
    expect(shouldShowCard({ state: 'downloading', version: '0.2.5' }, new Set(), new Set())).toBe(false);
    expect(shouldShowCard(null, new Set(), new Set())).toBe(false);
  });
  it('restart: at once with nothing running, otherwise ask', () => {
    expect(restartPlan(0)).toBe('now');
    expect(restartPlan(2)).toBe('ask');
  });
  it('"Restart when done" fires when the last project finishes and the update is still ready', () => {
    expect(restartWhenDoneDue(true, 1, ready)).toBe(false);
    expect(restartWhenDoneDue(true, 0, ready)).toBe(true);
    expect(restartWhenDoneDue(false, 0, ready)).toBe(false);
    expect(restartWhenDoneDue(true, 0, { state: 'error', errorStage: 'install' })).toBe(false);
  });
  it('errors map to plain words by stage', () => {
    expect(errorKey('check')).toBe('upd.err.check');
    expect(errorKey('download')).toBe('upd.err.download');
    expect(errorKey('install')).toBe('upd.err.install');
    expect(errorKey(undefined)).toBe('upd.err.check');
  });
});
