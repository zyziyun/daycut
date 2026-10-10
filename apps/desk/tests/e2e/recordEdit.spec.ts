// Record -> second pass -> pickup (ux/record/pickups) in the real app with the REAL engine sidecar (no mock engine),
// Chromium's fake camera / microphone, isolated temp profile, window hidden. The only fake is the transcriber
// (fixture/rec_words.py: the fake microphone only beeps). Flow:
//   - Share a screen too: the app's own picker lists what can be shared, a pick shares it (the 0.2.4 button did
//     nothing); with Screen Recording off (DESK_E2E_SCREEN=denied) it says how to turn it on, with the Settings button
//   - record a take, Stop -> lands in the clip editor with the transcript and the automatic cleanup
//   - delete words -> saved by itself
//   - select a word -> Add after -> the player becomes the camera -> record -> the pickup is spliced in, marked in the
//     transcript ("Pickup 1"), the player plays the spliced file
//   - the final render contains it (length = the edited timeline); Undo takes it out again
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-recedit-'));
const FIXTURE = path.join(import.meta.dirname, 'fixture');
const SHOTS = process.env.DESK_SHOTS_DIR ?? path.resolve(import.meta.dirname, '../../test-results/record-edit');
fs.mkdirSync(SHOTS, { recursive: true });
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });

async function launch(profile: string, extra: Record<string, string> = {}) {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    VSTUDIO_HOME: path.join(tmp, `vhome-${profile}`),
    VSTUDIO_BATCH_BENCH: path.join(tmp, 'bench.json'),
    VSTUDIO_DEFAULT_PERSONA: '1',
    VSTUDIO_LLM_PROVIDER: 'none',
    VSTUDIO_OUTPUT_TRANSCRIBER: `${path.join(FIXTURE, 'rec_words.py')}:words`,
    PYTHONPATH: '',
    DESK_ENGINE_MOCK: '',
    DESK_CREATE: '1',
    DESK_E2E_FAKE_MEDIA: '1',
    DESK_USER_DATA: path.join(tmp, `profile-${profile}`),
    DESK_HISTORY_WATCH: '',
    DESK_HIDE_WINDOW: '1',
    DESK_SHARED_CACHE: path.join(tmp, 'cache'),
    DESK_HF_HUB: '',
    DESK_SKIP_FIRST_RUN: '1',
    VITE_DEV_SERVER_URL: '',
    ...extra,
  };
  for (const k of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'VSTUDIO_PERSONA']) delete env[k];
  const app = await electron.launch({ args: [path.resolve(import.meta.dirname, '../..')], env: env as Record<string, string> });
  const page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    // speak freely, no 3-2-1, raw sound (the studio pass is tested in the engine)
    localStorage.setItem('rec.prefs', JSON.stringify({ script: false, countdown: false, studio: false }));
    await window.desk.setSettings({ lang: 'en' });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  return { app, page };
}

async function api<T>(page: Page, p: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ([u, b]) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + u, { method: b ? 'POST' : 'GET', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined });
      return r.json();
    },
    [p, body] as const,
  ) as Promise<T>;
}

const probe = (f: string) => Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], { encoding: 'utf8' }).trim());

test.describe.configure({ mode: 'serial' });

test.describe('screen sharing with Screen Recording off', () => {
  let app: ElectronApplication;
  let page: Page;
  test.afterAll(async () => closeApp(app));

  test('says how to turn it on, with the System Settings button (never a silent no-op)', async () => {
    ({ app, page } = await launch('denied', { DESK_E2E_SCREEN: 'denied' }));
    expect((await page.evaluate(() => window.desk.engineInfo())).mode).toBe('real');
    await page.evaluate(() => (location.hash = '#/create/record'));
    await page.getByTestId('create-rec-allow').click();
    await expect(page.getByTestId('create-rec-preview')).toBeVisible({ timeout: 20000 });
    await page.getByTestId('create-rec-screen').click();
    await page.getByTestId('rec-screen-toggle').click();
    const denied = page.getByTestId('rec-screen-denied');
    await expect(denied).toBeVisible();
    await expect(denied).toContainText('Screen & System Audio Recording');
    await expect(page.getByTestId('rec-screen-settings')).toContainText('Open System Settings');
    await expect(page.getByTestId('create-rec-screen')).not.toContainText('Sharing');
    await shot(page, 'R0-screen-denied');
  });
});

test.describe('record -> edit -> pickup', () => {
  let app: ElectronApplication;
  let page: Page;
  test.afterAll(async () => closeApp(app));

  test('share a screen: the picker lists it, a pick shares it', async () => {
    test.setTimeout(120000);
    ({ app, page } = await launch('main'));
    await page.evaluate(() => (location.hash = '#/create/record'));
    await page.getByTestId('create-rec-allow').click();
    await expect(page.getByTestId('create-rec-preview')).toBeVisible({ timeout: 20000 });
    await page.getByTestId('create-rec-screen').click();
    await page.getByTestId('rec-screen-toggle').click();
    await expect(page.getByTestId('rec-screen-source')).toHaveCount(1);
    await shot(page, 'R1-screen-picker');
    await page.getByTestId('rec-screen-source').click();
    await expect(page.getByTestId('create-rec-screen')).toContainText('Sharing', { timeout: 15000 });
    await page.getByTestId('create-rec-screen').click();
    await page.getByTestId('rec-screen-toggle').click();
    await expect(page.getByTestId('create-rec-screen')).not.toContainText('Sharing');
  });

  test('stop -> the clip editor with the transcript and the automatic cleanup', async () => {
    test.setTimeout(240000);
    await page.keyboard.press('Space');
    await expect(page.getByTestId('create-rec-live')).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(6500);
    await page.keyboard.press('Space');
    await expect(page.getByTestId('rec-preparing')).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId('editor')).toBeVisible({ timeout: 180000 });
    await expect(page.getByTestId('transcript-body')).toContainText('everyone', { timeout: 60000 });
    await expect(page.getByTestId('editor-finish')).toBeVisible();
    await expect(page.getByTestId('editor-finish')).toHaveClass(/primary/);
    await expect(page.getByTestId('editor-takes')).toBeVisible();
    // the "um" was cut automatically: a marker in the transcript + the card that brings it back
    await expect(page.getByTestId('auto-clean-card')).toBeVisible();
    await expect(page.getByTestId('cut-marker').first()).toContainText('um');
    await shot(page, 'R2-lands-in-editor');
  });

  test('delete words: saved by itself', async () => {
    const w = (i: number) => page.locator(`[data-testid="transcript-body"] .w[data-i="${i}"]`);
    await w(2).click();
    await page.keyboard.press('Alt+Shift+ArrowRight'); // + "we" (the bar above the words would catch a Shift-click)
    await page.keyboard.press('Delete');
    await expect(page.getByTestId('cut-status')).toHaveAttribute('data-state', 'saved', { timeout: 30000 });
    await expect(page.getByTestId('cut-marker')).toHaveCount(2); // "today we" collapsed to a marker (+ the um)
    await expect(page.locator('[data-testid="transcript-body"] .w', { hasText: 'today' })).toHaveCount(0);
  });

  test('a pickup after a word: recorded in place of the player, spliced in, marked, playing', async () => {
    test.setTimeout(240000);
    const before = await page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')?.currentSrc ?? '');
    const w = page.locator('[data-testid="transcript-body"] .w', { hasText: 'editing' });
    await w.click();
    await expect(page.getByTestId('selection-bar')).toBeVisible();
    await page.getByTestId('sel-add-after').click();
    await expect(page.getByTestId('pickup-stage')).toBeVisible();
    await expect(page.getByTestId('pickup-preview')).toBeVisible({ timeout: 20000 });
    await shot(page, 'R3-pickup-ready');
    await page.getByTestId('pickup-record').click();
    await expect(page.getByTestId('pickup-live')).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(3500);
    await shot(page, 'R4-pickup-recording');
    await page.getByTestId('pickup-stop').click();
    await expect(page.getByTestId('pickup-stage')).toHaveCount(0, { timeout: 180000 });
    await expect(page.getByTestId('pickup-error')).toHaveCount(0);
    const tag = page.getByTestId('pickup-tag');
    await expect(tag).toHaveText('Pickup 1', { timeout: 30000 });
    // the pickup's words come right after "editing", before "by"
    const ws = (await page.locator('[data-testid="transcript-body"] .w').allInnerTexts()).map((x) => x.trim());
    expect(ws.slice(ws.indexOf('editing'), ws.indexOf('editing') + 4)).toEqual(['editing', 'pickup', 'line', 'by']);
    await expect(page.locator('[data-testid="transcript-body"] .w.pk')).toHaveCount(2);
    // the player plays the spliced file now, and plays through the pickup
    await expect.poll(() => page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')?.currentSrc ?? ''), { timeout: 20000 }).not.toBe(before);
    const src = await page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')?.currentSrc ?? '');
    expect(decodeURIComponent(src)).toContain('pickups');
    await page.locator('[data-testid="transcript-body"] .w.pk').first().click();
    const t0 = await page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')!.currentTime);
    await page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')!.play());
    await expect.poll(() => page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')!.currentTime), { timeout: 10000 }).toBeGreaterThan(t0 + 0.3);
    await page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="editor-player"] video')!.pause());
    await shot(page, 'R5-pickup-spliced');
  });

  test('the export contains the pickup; Undo takes it out', async () => {
    test.setTimeout(240000);
    const m = /#\/p\/([^/]+)\/clip\/([^/?]+)/.exec(await page.evaluate(() => location.hash));
    expect(m).not.toBeNull();
    const [item, clip] = [m![1], decodeURIComponent(m![2])];
    const doc = await api<{ duration: number; words: { w: string }[]; pickups: { start: number; end: number }[]; cuts: { start: number; end: number }[] }>(page, `/api/outputs/${item}/${encodeURIComponent(clip)}`);
    expect(doc.pickups).toHaveLength(1);
    expect(doc.words.map((x) => x.w)).toContain('pickup');
    const r = await api<{ targets: { file: string }[] }>(page, `/api/outputs/${item}/${encodeURIComponent(clip)}/render`, { quality: 'final', targets: 'primary' });
    const file = r.targets[0].file;
    const kept = doc.duration - doc.cuts.reduce((s, c) => s + (c.end - c.start), 0);
    expect(Math.abs(probe(file) - kept)).toBeLessThan(0.3);
    expect(kept).toBeGreaterThan(doc.pickups[0].end - doc.pickups[0].start);
    await page.getByTestId('editor-undo').click();
    await expect(page.getByTestId('pickup-tag')).toHaveCount(0, { timeout: 20000 });
    await expect(page.locator('[data-testid="transcript-body"] .w.pk')).toHaveCount(0);
    await page.getByTestId('editor-redo').click();
    await expect(page.getByTestId('pickup-tag')).toHaveText('Pickup 1', { timeout: 20000 });
  });

  test('Takes: the visit\'s takes; Record another take goes back to the recorder with them', async () => {
    await page.getByTestId('editor-takes').click();
    await expect(page.getByTestId('editor-take')).toHaveCount(1);
    await page.getByTestId('editor-record-another').click();
    await expect(page.getByTestId('create-record')).toBeVisible();
    await expect(page.getByTestId('create-rec-take')).toHaveCount(1, { timeout: 10000 });
    await expect(page.getByTestId('rec-take-edit')).toBeVisible();
  });
});
