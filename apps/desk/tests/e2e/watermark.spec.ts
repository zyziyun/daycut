// Watermark, end to end on the real engine (this repo's lib/: window hidden, isolated profile + VSTUDIO_HOME, a work
// folder with one tiny 9:16 clip): Settings › Watermark renders in en / 简体中文 / Français with no missing message;
// typing a handle sets it up (and turns "Add to every video" on), the engine-drawn previews change, Generate makes a
// logo, the corner / size / opacity apply at once and survive a reload, a logo file can be picked; then the clip's
// Export card shows the watermark switch on, the final render carries the mark in the chosen corner, and with the
// switch off the next export is clean.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-wm-'));
const watch = path.join(tmp, 'demos');
const work = path.join(watch, 'wmclips');
const vhome = path.join(tmp, 'vhome');
const CLIP = 'A_hello';
const W = 360;
const H = 640;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const fin = path.join(work, 'final');
  fs.mkdirSync(fin, { recursive: true });
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', `testsrc2=size=${W}x${H}:rate=25:duration=2`, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(fin, `${CLIP}.mp4`)]);
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: vhome, DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => localStorage.setItem('i18n.strict', '1'));
  await expect.poll(async () => (await api<{ mode: string }>('/api/health')).mode, { timeout: 30000 }).toBe('real');
});

test.afterAll(async () => {
  await closeApp(app);
});

const api = <T,>(p: string) =>
  page.evaluate(async (u) => {
    const info = await window.desk.engineInfo();
    return (await fetch(info.baseUrl + u, { headers: { Authorization: `Bearer ${info.token}` } })).json();
  }, p) as Promise<T>;
const saved = () => JSON.parse(fs.readFileSync(path.join(vhome, 'watermark.json'), 'utf8'));
const noMissing = async () => expect(await page.evaluate(() => document.body.innerText.match(/⟦[^⟧]+⟧|\bwm\.[a-zA-Z][\w.-]+/g))).toBeNull();
const previewV = () => page.getByTestId('wm-preview-v').getAttribute('src');

test('Settings › Watermark: not set up, then a handle, a generated logo, placement; persists', async () => {
  await page.evaluate(() => (location.hash = '#/settings/watermark'));
  await expect(page.getByTestId('settings-watermark')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('snav-watermark')).toHaveAttribute('aria-current', 'page');
  await expect(page.getByTestId('wm-preview-v')).toHaveAttribute('src', /^data:image\/jpeg;base64,/);
  await expect(page.getByTestId('wm-default')).not.toBeChecked();
  expect(fs.existsSync(path.join(vhome, 'watermark.json'))).toBe(false); // nothing until she sets it up
  await noMissing();
  const blank = await previewV();

  await page.getByTestId('wm-text').fill('@reelfold');
  await page.getByTestId('wm-text').press('Enter');
  await expect.poll(() => saved().text).toBe('@reelfold');
  expect(saved().default).toBe(true); // set up -> on by default, shown as on
  await expect(page.getByTestId('wm-default')).toBeChecked();
  await expect.poll(previewV).not.toBe(blank);
  await expect(page.getByTestId('wm-platforms').locator('button').first()).toHaveAttribute('data-testid', 'wm-pf-youtube'); // international first

  const textPreview = await previewV();
  await page.getByTestId('wm-generate').click();
  await expect.poll(() => saved().kind).toBe('generate');
  await page.getByTestId('wm-style-monogram').click();
  await expect.poll(() => saved().style).toBe('monogram');
  await expect.poll(previewV).not.toBe(textPreview);

  await page.getByTestId('wm-pos-top-left').click();
  await expect.poll(() => saved().position).toBe('top-left');
  await page.getByTestId('wm-size').fill('0.4');
  await expect.poll(() => saved().size).toBe(0.4);
  await page.getByTestId('wm-opacity').fill('1');
  await expect.poll(() => saved().opacity).toBe(1);
  await page.getByTestId('wm-pf-douyin').click();
  await expect.poll(() => saved().platforms).toEqual({ douyin: false });
  await expect(page.getByTestId('wm-pf-douyin')).toHaveAttribute('aria-pressed', 'false');
  await page.getByTestId('wm-pf-douyin').click();
  await expect.poll(() => saved().platforms).toEqual({ douyin: true });

  await expect(page.locator('[data-testid=toast].err')).toHaveCount(0); // no failed save / preview on the way
  if (process.env.WM_SHOTS) await page.screenshot({ path: path.join(process.env.WM_SHOTS, 'settings-watermark.png'), fullPage: true });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('wm-pos-top-left')).toHaveAttribute('aria-checked', 'true', { timeout: 30000 });
  await expect(page.getByTestId('wm-text')).toHaveValue('@reelfold');
  await expect(page.getByTestId('wm-style-monogram')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('wm-default')).toBeChecked();
});

test('a logo file can be picked; every language has every message', async () => {
  const logo = path.join(tmp, 'logo.png');
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red@0.8:s=200x100,format=rgba', '-frames:v', '1', logo]);
  await app.evaluate(({ dialog }, p) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [p] })) as typeof dialog.showOpenDialog;
  }, logo);
  await page.getByTestId('wm-kind-image').click();
  await expect(page.getByTestId('wm-drop')).toBeVisible();
  await page.getByTestId('wm-choose').click();
  await expect(page.getByTestId('wm-drop')).toContainText(/logo-[0-9a-f]+\.png/);
  await expect.poll(() => saved().kind).toBe('image');
  expect(fs.existsSync(saved().image)).toBe(true);
  expect(saved().image.startsWith(vhome)).toBe(true); // copied in, her file stays where it was
  await page.getByTestId('wm-kind-generate').click(); // back to the generated logo for the export
  await expect.poll(() => saved().kind).toBe('generate');
  for (const l of ['zh-CN', 'fr', 'en'] as const) {
    await page.evaluate((x) => window.desk.setSettings({ lang: x }), l);
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await expect(page.getByTestId('settings-watermark')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('snav-watermark')).toContainText(l === 'zh-CN' ? '水印' : l === 'fr' ? 'Filigrane' : 'Watermark');
    await noMissing();
  }
});

/** Mean absolute difference between the source clip and a render at 1 s: the top-left band (top fifth, left half)
 * and the bottom-right one. */
function diffQuarters(render: string): { tl: number; br: number } {
  const gray = (f: string) => execFileSync('ffmpeg', ['-v', 'error', '-ss', '1', '-i', f, '-frames:v', '1', '-s', `${W}x${H}`, '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], { maxBuffer: 1 << 24 });
  const a = gray(path.join(work, 'final', `${CLIP}.mp4`));
  const b = gray(render);
  const q = (x0: number, y0: number) => {
    let s = 0;
    let n = 0;
    for (let y = y0; y < y0 + H / 5; y++) for (let x = x0; x < x0 + W / 2; x++, n++) s += Math.abs(a[y * W + x] - b[y * W + x]);
    return s / n;
  };
  return { tl: q(0, 0), br: q(W / 2, (H * 4) / 5) };
}

function finalRender(): string {
  const out = path.join(work, '.vstudio', 'outputs');
  for (const d of fs.readdirSync(out)) {
    const f = path.join(out, d, 'renders', 'primary.final.mp4');
    if (fs.existsSync(f)) return f;
  }
  throw new Error('no final render');
}

async function exportOnce(wm: boolean) {
  const before = await page.getByTestId('card-export').count();
  await page.getByTestId('editor-export').click();
  await expect(page.getByTestId('card-export')).toHaveCount(before + 1);
  const ex = page.getByTestId('card-export').last(); // a new card each time; earlier ones stay in the conversation
  await expect(ex).toBeVisible();
  const row = ex.getByTestId('export-wm');
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row).toHaveAttribute('data-on', '1'); // her default
  if (!wm) await ex.getByTestId('export-wm-toggle').uncheck();
  await expect(row).toHaveAttribute('data-on', wm ? '1' : '0');
  if (process.env.WM_SHOTS) await ex.screenshot({ path: path.join(process.env.WM_SHOTS, `export-card-${wm ? 'on' : 'off'}.png`) });
  await ex.getByTestId('export-go').click();
  await expect(ex.locator('[data-testid=export-row][data-done="1"]')).toHaveCount(1, { timeout: 120000 });
  await ex.getByRole('button', { name: /Done|完成|Terminé/ }).click();
}

test('Export: the final render carries the mark by default, and not when switched off', async () => {
  let id = '';
  for (let i = 0; i < 60 && !id; i++) {
    const h = await api<{ items: { id: string; dir: string }[] }>('/api/history');
    id = h.items.find((x) => x.dir === work)?.id ?? '';
    if (!id) await page.waitForTimeout(500);
  }
  expect(id).toMatch(/^[0-9a-f]{12}$/);
  await page.evaluate((h) => (location.hash = h), `#/p/${id}/clip/${encodeURIComponent(CLIP)}`);
  await expect(page.getByTestId('chat-panel')).toBeVisible({ timeout: 30000 });

  await exportOnce(true);
  const on = diffQuarters(finalRender());
  expect(on.tl).toBeGreaterThan(6); // the generated logo, top-left, full opacity
  expect(on.tl).toBeGreaterThan(on.br * 4);

  await exportOnce(false);
  const off = diffQuarters(finalRender());
  expect(off.tl).toBeLessThan(4);
});
