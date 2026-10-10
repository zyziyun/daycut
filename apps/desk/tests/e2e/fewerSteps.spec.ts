// Fewer steps (ux/fewer-steps) in the real app with the REAL engine sidecar (no mock engine), isolated temp profile,
// window hidden. A talking-head project (fixture/real_project.py: synthetic tone-burst talk + the engine tests' fake
// transcriber, the only fakes; the made clip opens with the pipeline's own words) runs on autopilot to the end
// (rules decide, no AI account), then in its clip editor:
//   - delete words in the transcript -> the preview skips them at once -> saved by itself (no Apply) -> Export right
//     away renders a file without them
//   - "磨个皮?" in the chat -> real skin smoothing applied at once with Undo and Before / after; Undo restores; the
//     clip renders with it
//   - the decisions the AI made on the clip are shown as made, with Undo / Change: keeping a word the AI kept as a cut
//     answers that decision in her name and the clip is re-made shorter
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
let project = '';
let id = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-fewer-'));
const REPO = path.resolve(import.meta.dirname, '../../../..');
const FIXTURE = path.join(import.meta.dirname, 'fixture');
const SHOTS = process.env.DESK_SHOTS_DIR ?? path.resolve(import.meta.dirname, '../../test-results/fewer-steps');
fs.mkdirSync(SHOTS, { recursive: true });
const engineEnv = {
  VSTUDIO_HOME: path.join(tmp, 'vhome'),
  VSTUDIO_BATCH_BENCH: path.join(tmp, 'bench.json'),
  VSTUDIO_DEFAULT_PERSONA: '1',
  VSTUDIO_TEST_TRUTH: path.join(tmp, 'truth.json'),
  VSTUDIO_LLM_PROVIDER: 'none',
  ...Object.fromEntries(['SEGMENT_PLAN', 'PROOFREAD', 'GLOSSARY', 'COPY', 'SCRIPT', 'PLANNER', 'INTAKE', 'OUTPUT_EDIT'].map((t) => [`VSTUDIO_LLM_${t}_PROVIDER`, 'none'])),
};

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  test.setTimeout(300000);
  const env: NodeJS.ProcessEnv = { ...process.env, ...engineEnv, PYTHONPATH: path.join(REPO, 'lib') };
  for (const k of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'VSTUDIO_PERSONA']) delete env[k];
  const out = execFileSync(process.env.DESK_PYTHON || 'python3', [path.join(FIXTURE, 'real_project.py'), tmp, '--autopilot'], { env, encoding: 'utf8' });
  const fx = JSON.parse(out.trim().split('\n').pop()!) as { dir: string; status: string };
  expect(fx.status).toBe('done');
  project = fx.dir;
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...env, PYTHONPATH: '', DESK_ENGINE_MOCK: '', DESK_USER_DATA: path.join(tmp, 'profile'), DESK_HISTORY_WATCH: '', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.setSettings({ lang: 'en' });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  expect((await page.evaluate(() => window.desk.engineInfo())).mode).toBe('real');
  await expect
    .poll(async () => (await api<{ items: { id: string; dir: string }[] }>('/api/history')).items.find((i) => fs.realpathSync(i.dir) === fs.realpathSync(project))?.id ?? '', { timeout: 60000 })
    .not.toBe('');
  id = (await api<{ items: { id: string; dir: string }[] }>('/api/history')).items.find((i) => fs.realpathSync(i.dir) === fs.realpathSync(project))!.id;
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const shot = (name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
async function api<T>(p: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ([u, b]) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + u, { method: b ? 'POST' : 'GET', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined });
      return r.json();
    },
    [p, body] as const,
  ) as Promise<T>;
}
type Doc = { cuts: unknown[]; steps: { id: string }[]; effects: { effect: string }[]; renders: { file: string; quality?: string; fresh?: boolean; target: string }[]; duration: number };
const clipDoc = () => api<Doc>(`/api/outputs/${id}/talk`);
const dur = (f: string) => Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], { encoding: 'utf8' }).trim());
const exportFile = () => path.join(project, 'state', 'jobs', 'talk', 'export', 'exports', 'xiaohongshu-full.mp4');

async function openClip() {
  await hash(`#/p/${id}/clip/talk`);
  await expect(page.getByTestId('editor')).toBeVisible({ timeout: 60000 });
  await page.getByTestId('tab-transcript').click();
  // the words are there on open: the pipeline's transcript mapped through the clip's cuts (nobody listened again)
  await expect(page.locator('[data-testid=transcript-body] .w').first()).toBeVisible({ timeout: 60000 });
  await expect(page.getByTestId('transcript-listen')).toHaveCount(0);
}

/** Export the primary version from the chat's export card; -> the rendered file */
async function exportNow(): Promise<string> {
  await page.getByTestId('editor-export').click();
  const ex = page.getByTestId('card-export').last();
  await expect(ex).toBeVisible();
  await ex.getByTestId('export-go').click();
  await expect(ex.locator('[data-testid=export-row][data-done="1"]').first()).toBeVisible({ timeout: 240000 });
  const d = await clipDoc();
  const r = d.renders.filter((x) => x.target === 'primary' && x.fresh && (x.quality ?? 'final') === 'final');
  expect(r.length).toBeGreaterThan(0);
  return r[r.length - 1].file;
}

test('transcript: delete -> skipped at once -> saved by itself (no Apply) -> Export right away has the cut', async () => {
  test.setTimeout(300000);
  await openClip();
  const w = (i: number) => page.locator(`[data-testid=transcript-body] .w[data-i="${i}"]`);
  const idx = (re: string) => page.evaluate((r) => Number([...document.querySelectorAll('[data-testid=transcript-body] .w')].find((e) => new RegExp(r).test(e.textContent ?? ''))?.getAttribute('data-i') ?? -1), re);
  const i0 = await idx('^第二');
  const i1 = await idx('例子');
  expect(i0).toBeGreaterThan(0);
  expect(i1).toBeGreaterThan(i0);
  const full = dur(exportFile());
  // 第二 个 例子: drag across, Delete
  const a = await w(i0).boundingBox();
  const b = await w(i1).boundingBox();
  await page.mouse.move(a!.x + 3, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width - 3, b!.y + b!.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByTestId("selection-bar")).toContainText(" words");
  await page.keyboard.press('Delete');
  await expect(page.getByTestId('editor-length')).toContainText('→'); // effective at once
  await expect(page.getByTestId('pending-apply')).toHaveCount(0);
  // Export straight away (the save has not even fired yet): it saves first, then renders with the cut
  const f = await exportNow();
  const d = await clipDoc();
  expect(d.cuts.length).toBe(1);
  expect(d.steps.length).toBe(1);
  expect(dur(f)).toBeLessThan(full - 0.5); // the deleted words (~0.8 s and more) are not in the file
  await expect(page.getByTestId('cut-card')).toContainText('第二');
  await shot('F1-transcript-saved');
});

test('chat: "磨个皮?" applies real skin smoothing at once, with Undo and Before / after; the clip renders with it', async () => {
  test.setTimeout(300000);
  await page.getByTestId('chat-input').fill('磨个皮?');
  await page.getByTestId('chat-input').press('Enter');
  const card = page.getByTestId('applied-card');
  await expect(card).toBeVisible({ timeout: 120000 });
  await expect(card).toContainText(/Skin smoothing/);
  await expect(page.getByTestId('change-card')).toHaveCount(0); // no Apply step
  let d = await clipDoc();
  expect(d.effects.map((e) => e.effect)).toEqual(['portrait-retouch']);
  // Before / after: the live player cannot draw skin smoothing, so the clip is rendered once and played as "After"
  await card.getByTestId('applied-compare').click();
  await expect(card.getByTestId('applied-compare')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('player-badge')).toHaveText('After', { timeout: 240000 });
  await shot('F2-ai-applied');
  await card.getByTestId('applied-compare').click();
  await expect(page.getByTestId('player-badge')).toHaveCount(0);
  // Undo restores; ⇧⌘Z puts it back
  await card.getByTestId('applied-undo').click();
  await expect(page.getByTestId('undone-line')).toHaveCount(1, { timeout: 30000 });
  d = await clipDoc();
  expect(d.effects).toEqual([]);
  await page.getByTestId('editor-title').click();
  await page.keyboard.press('ControlOrMeta+Shift+z');
  await expect.poll(async () => (await clipDoc()).effects.map((e) => e.effect), { timeout: 30000 }).toEqual(['portrait-retouch']);
  // renders: the frame pass runs the face tracker on every frame (no face in this synthetic talk: frames pass through)
  const f = await exportNow();
  expect(dur(f)).toBeGreaterThan(5);
});

test('the AI’s calls on the clip are shown as made, with Undo / Change; changing one re-makes the clip', async () => {
  test.setTimeout(300000);
  await openClip();
  const card = page.getByTestId('decided-card');
  await expect(card).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('pinned-question')).toHaveCount(0); // nothing to confirm
  const filler = card.locator('[data-testid=decided-row][data-kind=filler]');
  await expect(filler).toHaveCount(1);
  await expect(filler).toHaveAttribute('data-cut', '0');
  await expect(filler).toContainText('Kept “然后”');
  await expect(card.locator('[data-testid=decided-row][data-kind=opening]')).toContainText('No cold open');
  await shot('F3-decided');
  // play: the word is found in the clip's transcript
  await filler.getByTestId('decided-play').click();
  const before = dur(exportFile());
  await filler.getByTestId('decided-flip').click(); // "Cut it"
  await expect(card).toContainText('Re-making the clip');
  await expect(filler).toHaveAttribute('data-cut', '1');
  const ap = await api<{ decisions: { checkpoint: string }[] }>(`/api/autopilot/${id}`);
  expect(ap.decisions.map((x) => x.checkpoint)).not.toContain('filler'); // hers now
  await expect
    .poll(async () => (await api<{ items: { id: string; live?: { state?: string } }[] }>('/api/history')).items.find((i) => i.id === id)?.live?.state, { timeout: 240000, intervals: [2000] })
    .toBe('done');
  // 然后 is gone (while the clip is re-made its export can be missing for a moment: a slow runner polls into that)
  await expect.poll(() => (fs.existsSync(exportFile()) ? dur(exportFile()) : Infinity), { timeout: 60000 }).toBeLessThan(before - 0.2);
  await shot('F4-decided-changed');
});
