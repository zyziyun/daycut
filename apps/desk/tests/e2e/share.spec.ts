// Runs the app with the Studio off (DESK_STUDIO=0): the pages before the Studio (2026-10 review step 7) stay
// supported behind its flag, and this spec covers them.
// Share for review, end to end on the real engine (this repo's lib/: window hidden, isolated profile, a work folder with two tiny clips and
// post copy): Project › Share for review → the dialog (clips, quality, footer, note) → the folder + zip exist; the
// page opens offline from file:// in a plain browser window with no network request, the reviewer approves one clip
// and asks for a change on the other, "Send my feedback" gives a code; Inbox › Import feedback turns it into two
// Inbox items; "Mark ready" makes the approved clip ready; the change opens the clip editor with the comment.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-share-'));
const watch = path.join(tmp, 'demos');
const work = path.join(watch, 'week12');
const CLIPS = ['A_hook', 'B_story'];
const SHOTS = process.env.SHARE_SHOTS ?? '';
const shot = async (p: Page, name: string) => {
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};
let folder = '';
let code = '';

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const fin = path.join(work, 'final');
  fs.mkdirSync(fin, { recursive: true });
  let md = '# Post copy\n\n';
  for (const [i, n] of CLIPS.entries()) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', `testsrc2=size=360x480:rate=25:duration=2`, '-f', 'lavfi', '-i', `sine=frequency=${440 + i * 220}:duration=2`, '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(fin, `${n}.mp4`)]);
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', path.join(fin, `${n}.mp4`), '-frames:v', '1', path.join(fin, `${n}_cover.jpg`)]);
    md += `## ${n}.mp4  ·  cover ${n}_cover.jpg\n\nTitle of ${n}\n\nThe caption body.\n\n#review\n\n`;
  }
  fs.writeFileSync(path.join(fin, 'post.md'), md);
  if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_STUDIO: '0', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => localStorage.setItem('i18n.strict', '1'));
  await expect.poll(async () => (await api<{ mode: string }>('/api/health')).mode, { timeout: 30000 }).toBe('real');
});

test.afterAll(async () => {
  await app?.close();
});

const api = <T,>(p: string) =>
  page.evaluate(async (u) => {
    const info = await window.desk.engineInfo();
    return (await fetch(info.baseUrl + u, { headers: { Authorization: `Bearer ${info.token}` } })).json();
  }, p) as Promise<T>;
const projectId = async () => {
  for (let i = 0; i < 60; i++) {
    const h = await api<{ items: { id: string; dir: string }[] }>('/api/history');
    const e = h.items.find((x) => x.dir === work);
    if (e) return e.id;
    await page.waitForTimeout(500);
  }
  throw new Error('project not found');
};

test('Share for review: dialog → folder + zip on disk', async () => {
  const id = await projectId();
  await page.evaluate((h) => (location.hash = h), `#/p/${id}`);
  await expect(page.getByTestId('clip-card')).toHaveCount(2, { timeout: 30000 });
  await page.getByTestId('share-open').click();
  const dlg = page.getByTestId('share-dialog');
  await expect(dlg).toBeVisible();
  await expect(dlg.getByTestId('share-clip')).toHaveCount(2, { timeout: 15000 });
  await expect(dlg.getByTestId('share-footer')).toBeChecked();
  await expect(dlg.getByTestId('share-privacy')).toHaveCount(0);
  await dlg.getByTestId('share-quality').locator('[data-v="small"]').click();
  await dlg.getByTestId('share-title').fill('Week 12 review');
  await dlg.getByTestId('share-note').fill('Please reply by Friday');
  await shot(page, '1-share-dialog');
  await expect(page.locator('body')).not.toContainText('⟦');
  await dlg.getByTestId('share-make').click();
  await expect(dlg.getByTestId('share-result')).toBeVisible({ timeout: 60000 });
  folder = (await dlg.getByTestId('share-folder').getAttribute('data-path'))!;
  const zip = (await dlg.getByTestId('share-zip').getAttribute('data-path'))!;
  await shot(page, '2-share-result');
  expect(folder.startsWith(path.join(work, 'review-links'))).toBe(true);
  for (const f of ['index.html', 'review.json', 'README.txt']) expect(fs.existsSync(path.join(folder, f))).toBe(true);
  expect(fs.statSync(zip).size).toBeGreaterThan(1000);
  const data = JSON.parse(fs.readFileSync(path.join(folder, 'review.json'), 'utf8'));
  expect(data.title).toBe('Week 12 review');
  expect(data.footer).toBe(true);
  expect(data.expiry_note).toBe('Please reply by Friday');
  expect(data.clips.map((c: { id: string }) => c.id)).toEqual(CLIPS);
  for (const c of data.clips) for (const v of c.versions) expect(fs.existsSync(path.join(folder, v.file))).toBe(true);
  expect(fs.readFileSync(path.join(folder, 'index.html'), 'utf8')).not.toContain(tmp);
  await dlg.getByTestId('share-finish').click();
  await expect(dlg).toHaveCount(0);
});

test('the page opens offline from file:// and gives a feedback code', async () => {
  const viewer = await electron.launch({ args: [path.resolve(import.meta.dirname, 'fixture/review-viewer.mjs')], env: { ...process.env, REVIEW_PAGE: path.join(folder, 'index.html') } });
  try {
    const p = await viewer.firstWindow();
    await p.setViewportSize({ width: 1280, height: 900 });
    await expect(p.getByTestId('clip')).toHaveCount(2);
    await expect(p.locator('h1')).toHaveText('Week 12 review');
    await expect(p.getByTestId('expiry')).toHaveText('Please reply by Friday');
    await expect(p.getByTestId('made-with')).toHaveAttribute('href', 'https://reelfold.com');
    // the preview plays from the folder
    const ready = await p.locator('video').first().evaluate((v: HTMLVideoElement) => new Promise<number>((res) => (v.readyState >= 1 ? res(v.duration) : v.addEventListener('loadedmetadata', () => res(v.duration)))));
    expect(ready).toBeGreaterThan(1.5);
    const [a, b] = [p.locator('[data-clip="A_hook"]'), p.locator('[data-clip="B_story"]')];
    await a.getByTestId('approve').click();
    await b.getByTestId('change').click();
    await b.locator('textarea').fill('0:01 the caption covers my face');
    await p.locator('#reviewer').fill('Mia');
    await shot(p, '3-review-page');
    await p.locator('#send').click();
    await expect(p.locator('#dlg')).toBeVisible();
    code = await p.locator('#code').inputValue();
    expect(code.startsWith('RFB1.')).toBe(true);
    await shot(p, '4-review-send');
    // answers survive a reload (kept in the page)
    await p.reload();
    await expect(p.locator('[data-clip="A_hook"]')).toHaveAttribute('data-decision', 'approve');
    const net = await viewer.evaluate(() => (globalThis as unknown as { __reviewNet: string[] }).__reviewNet);
    expect(net).toEqual([]);
  } finally {
    await viewer.close();
  }
});

test('Inbox › Import feedback → two items; Mark ready; the change opens in the editor', async () => {
  await page.evaluate(() => (location.hash = '#/inbox'));
  await page.getByTestId('feedback-import').click();
  const dlg = page.getByTestId('feedback-dialog');
  await dlg.getByTestId('feedback-text').fill(`Hi! Here is my feedback.\n\n${code}\n\nMia`);
  await shot(page, '5-import-feedback');
  await dlg.getByTestId('feedback-go').click();
  await expect(dlg).toHaveCount(0, { timeout: 60000 }); // the real engine pins the comment in the clip's chat
  const rows = page.locator('[data-testid="inbox-item"][data-kind^="feedback"]');
  await expect(rows).toHaveCount(2, { timeout: 30000 });
  await expect(page.locator('[data-testid="inbox-item"][data-kind="feedback-change"]')).toContainText('Mia asked for a change');
  await page.locator('[data-testid="inbox-item"][data-kind="feedback-approve"]').click();
  await expect(page.getByTestId('inbox-confirm')).toContainText('Mark ready');
  await shot(page, '6-inbox-feedback');
  await page.getByTestId('inbox-confirm').click();
  await expect(rows).toHaveCount(1, { timeout: 30000 });
  const id = await projectId();
  const clips = await api<{ clips: { id: string; state: string }[] }>(`/api/outputs/${id}`);
  expect(clips.clips.find((c) => c.id === 'A_hook')?.state).toBe('approved');
  // the change request: the editor opens with the comment pinned and in the clip's chat
  await page.locator('[data-testid="inbox-item"][data-kind="feedback-change"]').click();
  await page.getByTestId('inbox-open-editor').click();
  await expect(page.getByTestId('editor')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('body')).toContainText('0:01 the caption covers my face');
  await shot(page, '7-editor-pinned');
  const doc = await api<{ chat: { role: string; text: string }[] }>(`/api/outputs/${id}/${encodeURIComponent('B_story')}`);
  expect(doc.chat.some((t) => t.role === 'user' && t.text === 'Mia: 0:01 the caption covers my face')).toBe(true);
  await expect(page.locator('body')).not.toContainText('ce.reply.card');
  // re-importing the same code adds nothing
  const again = await page.evaluate(async (c) => {
    const info = await window.desk.engineInfo();
    return (await fetch(`${info.baseUrl}/api/feedback/import`, { method: 'POST', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ text: c }) })).json();
  }, code);
  expect(again.items).toBe(0);
});
