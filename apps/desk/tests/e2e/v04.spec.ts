// v0.4 (window hidden, mock engine, isolated profile): composer -> AI plan card -> revise -> start (pilot) ->
// project; a fuye-like work folder -> the clip in the large player -> full screen (F / Esc) -> second-pass edit
// (trim + pop word + 让 AI 改) -> render -> undo; and every main screen in English and 简体中文 with no missing
// message keys and no clipped labels.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-v04-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');
const recording = path.join(tmp, '副业复盘_final.mp4');

function ffmpeg(args: string[]) {
  execFileSync('ffmpeg', ['-v', 'error', '-y', ...args]);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(path.join(fuye, 'final'), { recursive: true });
  // real (tiny) videos so the player can seek frame by frame
  const lavfi = (w: number, h: number) => ['-f', 'lavfi', '-i', `testsrc2=size=${w}x${h}:rate=30:duration=6`, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'];
  ffmpeg([...lavfi(240, 320), path.join(fuye, 'final', 'A_换圈子.mp4')]);
  ffmpeg([...lavfi(180, 320), path.join(fuye, 'final', 'A_换圈子_9x16.mp4')]);
  ffmpeg(['-i', path.join(fuye, 'final', 'A_换圈子.mp4'), '-frames:v', '1', path.join(fuye, 'final', 'A_换圈子_cover.jpg')]);
  fs.writeFileSync(
    path.join(fuye, 'final', 'post.md'),
    '# 发布文案\n\n## A_换圈子.mp4  ·  封面 A_换圈子_cover.jpg\n\n同一个行业待越久，思路越窄\n\n正文。\n\n#副业 #程序员\n',
  );
  const w = [['你在', 0.2, 0.6], ['副业', 0.6, 1.1], ['当中', 1.1, 1.5], ['其实', 2.4, 2.9], ['底气', 2.9, 3.5], ['很重要', 3.5, 4.4]];
  fs.writeFileSync(path.join(fuye, 'final', 'A_换圈子.mp4.asr.json'), JSON.stringify({ segments: [{ start: 0.2, end: 4.4, words: w.map(([word, start, end]) => ({ word, start, end })) }] }));
  fs.writeFileSync(path.join(fuye, 'PICKS.md'), '# PICKS\n\n## Edits inside the spans (creator should confirm)\n- **A** starts at 你在副业当中.\n');
  fs.writeFileSync(recording, 'not really a video');
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => sessionStorage.setItem('v4.pview', 'grid')); // All projects as the grid (the control room: autopilot.spec)
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);

test('Home (Ask me first): say it + a file -> sent -> the plan card in All projects -> revise -> start a pilot', async () => {
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 30000 });
  await page.evaluate(() => window.desk.setSettings({ autopilot: false }));
  await page.evaluate((f) => sessionStorage.setItem('v4.composer', JSON.stringify({ prompt: '', files: [f] })), recording);
  await hash('#/inbox');
  await hash('#/');
  await expect(page.getByTestId('composer-files')).toContainText('副业复盘_final.mp4');
  await page.getByTestId('composer-input').fill('把这条副业复盘剪成 4 条小红书切片，每条一分钟左右');
  await page.getByTestId('make-plan').click();
  await expect(page.getByTestId('composer-input')).toHaveValue(''); // Home is free for the next one at once
  await page.getByTestId('toast-action').first().click();
  await expect(page.getByTestId('hub-request')).toBeVisible({ timeout: 15000 });
  const facts = page.getByTestId('plan-facts');
  await expect(facts).toContainText(/4 clips|4 条/, { timeout: 30000 });
  await expect(page.getByTestId('plan-summary')).toContainText(/4 clips|4 条/); // no AI planned it: said in the UI language
  await expect(page.getByTestId('plan-decide')).toBeVisible(); // the last clip is short: one thing to decide
  await page.getByTestId('plan-revise').fill('只要 3 条');
  await page.getByTestId('plan-revise-send').click();
  await expect(facts).toContainText(/3 clips|3 条/, { timeout: 30000 });
  await page.getByTestId('plan-start').click();
  await expect(page.getByTestId('hub-project').getByTestId('hub-title')).toContainText('副业复盘', { timeout: 30000 });
  await page.evaluate(() => window.desk.setSettings({ autopilot: true }));
  await page.evaluate(() => sessionStorage.setItem('v4.pview', 'grid'));
  await page.getByTestId('nav-home').click();
  // the mock pilot takes ~0.4 s (DESK_MOCK_STEP 0.02): by the time Home renders it is either still Running or already
  // waiting for her in the Inbox lane ("第 1 条做好了") - both say the new project is going
  await expect(page.locator('[data-testid=live-lane], [data-testid=home-inbox]').filter({ hasText: '副业复盘' }).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('recent-prompts')).toContainText('副业复盘');
});

test('the inbox lists the folder’s edits to confirm; confirm with undo', async () => {
  await page.getByTestId('nav-inbox').click();
  const item = page.getByTestId('inbox-item').filter({ hasText: 'fuye' });
  await expect(item).toBeVisible({ timeout: 30000 });
  await item.click(); // the list on the left, the item on the right
  await page.getByTestId('inbox-preview').getByTestId('inbox-confirm').click();
  await expect(item).toHaveCount(0);
  await page.getByTestId('toast-undo').click();
  await expect(page.getByTestId('inbox-item').filter({ hasText: 'fuye' })).toBeVisible();
  expect(fs.existsSync(path.join(fuye, '.vstudio'))).toBe(false); // answers live in the desk, not in her folder
});

test('a fuye-like folder: large player, full screen with F / Esc, frame stepping, sizes, captions + safe area', async () => {
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('project-card').filter({ hasText: 'fuye' }).click();
  const card = page.getByTestId('clip-card');
  await expect(card).toHaveCount(1);
  await expect(page.getByTestId('post-copy')).toContainText('思路越窄');
  await card.click();
  const player = page.getByTestId('player');
  await expect(page.getByTestId('player-overlay')).toBeVisible();
  await page.waitForFunction(() => ((document.querySelector('[data-testid=player-video]') as HTMLVideoElement | null)?.readyState ?? 0) >= 1);
  // the overlay autoplays: K pauses wherever playback got to (0.02-0.12 s on a busy machine), so go to the first
  // frame before stepping - the timecodes below are absolute
  await page.keyboard.press('k');
  await expect.poll(() => page.evaluate(() => (document.querySelector('[data-testid=player-video]') as HTMLVideoElement).paused)).toBe(true);
  await page.keyboard.press('Home');
  await expect(page.getByTestId('timecode')).toContainText('00:00:00:00');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('timecode')).toContainText('00:00:00:02');
  await page.keyboard.press('Shift+ArrowRight');
  await expect(page.getByTestId('timecode')).toContainText('00:00:01:02');
  await page.keyboard.press('f');
  await expect(player).toHaveAttribute('data-full', '1');
  await page.keyboard.press('Escape');
  await expect(player).toHaveAttribute('data-full', '0');
  await page.getByTestId('size-9:16').click();
  await page.getByTestId('toggle-safe').click();
  await page.getByTestId('player-video').dblclick(); // double-click = full screen too
  await expect(player).toHaveAttribute('data-full', '1');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('player-overlay')).toHaveCount(0);
});

test('second-pass edit: trim, pop word (精确编辑 drawer), 让 AI 改 (chat), render, undo; 转成项目 happens on the first edit', async () => {
  const before = fs.statSync(path.join(fuye, 'final', 'A_换圈子.mp4')).mtimeMs;
  await page.getByTestId('clip-card').click({ button: 'right' });
  await page.getByTestId('menu-edit').click();
  await expect(page.getByTestId('editor')).toBeVisible();
  await expect(page.getByTestId('timeline').locator('.w')).toHaveCount(6);
  await expect(page.getByTestId('chat-panel')).toBeVisible(); // chat-first: the AI column is the default
  await page.getByTestId('toggle-precise').click(); // today's tabs live in the optional drawer
  await page.getByTestId('etab-captions').click();
  await expect(page.getByTestId('caps-note')).toContainText(/burned|烧进/); // flattened: explained, no dead controls
  await page.getByTestId('etab-trim').click();
  // seek to "其实" (2.4 s) by clicking its word, then start there
  await page.getByTestId('timeline').locator('.w[data-t="2.4"]').click();
  await page.getByTestId('trim-start-here').click();
  await expect(page.getByTestId('trim-range')).toContainText(/0:02\.4/);
  await expect(page.getByTestId('edit-step')).toHaveCount(1);
  expect(fs.existsSync(path.join(fuye, '.vstudio', 'work.json'))).toBe(true); // adopted transparently

  await page.getByTestId('etab-effects').click();
  await page.locator('[data-testid=fx-item][data-fx=pop-words]').click();
  await page.getByTestId('fxp-text').fill('底气');
  await page.getByTestId('timeline').locator('.w[data-t="2.9"]').click();
  await page.getByTestId('fx-add-playhead').click();
  await expect(page.getByTestId('fx-block')).toHaveCount(1);
  await expect(page.getByTestId('edit-step')).toHaveCount(2);

  await page.getByTestId('chat-input').fill('再紧凑一点');
  await page.getByTestId('chat-input').press('Enter');
  const done = page.getByTestId('applied-card'); // applied at once (ux/fewer-steps), with Undo and Before / after
  await expect(done).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('edit-step')).toHaveCount(3);
  await done.getByTestId('applied-compare').click(); // the clip as it was ...
  await expect(done.getByTestId('applied-compare')).toHaveAttribute('aria-pressed', 'true');
  await done.getByTestId('applied-compare').click(); // ... and back
  await done.getByTestId('applied-undo').click(); // the newest card: a plain undo
  await expect(page.getByTestId('edit-step')).toHaveCount(2);

  await page.getByTestId('render').click();
  await expect(page.getByTestId('render-state')).toContainText(/can’t re-render|不能重新导出/);
  await page.getByTestId('editor-undo').click();
  await expect(page.getByTestId('edit-step')).toHaveCount(1);
  await expect(page.getByTestId('fx-block')).toHaveCount(0);
  await page.getByTestId('editor-redo').click();
  await expect(page.getByTestId('fx-block')).toHaveCount(1);
  expect(fs.statSync(path.join(fuye, 'final', 'A_换圈子.mp4')).mtimeMs).toBe(before); // the original is never touched
  await hash(`#/p/${await page.evaluate(() => location.hash.split('/')[2])}/history`);
  await expect(page.getByTestId('history-tab')).toContainText(/2 edits|2 处修改/);
});

test('⌘K palette, ? shortcuts, drop target', async () => {
  await page.getByTestId('nav-home').click();
  await page.keyboard.press('ControlOrMeta+k');
  await expect(page.getByTestId('palette')).toBeVisible();
  await page.getByTestId('palette-input').fill('inbox');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('inbox')).toBeVisible();
  await page.keyboard.press('Shift+?');
  await expect(page.getByTestId('shortcuts')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('shortcuts')).toHaveCount(0);
});

test('publish board: the platform row lists only connected accounts (+ Add); the full platform list is on Accounts', async () => {
  await hash('#/publish');
  await expect(page.getByTestId('calendar')).toBeVisible({ timeout: 15000 });
  // no account yet: one question instead of a wall of platforms
  await expect(page.getByTestId('pb-onboarding').or(page.getByTestId('pub-week'))).toBeVisible({ timeout: 15000 });
  if (await page.getByTestId('pb-onboarding').isVisible()) {
    await expect(page.getByTestId('pb-ob-tile')).toHaveCount(8);
    await expect(page.getByTestId('pb-ob-continue')).toBeDisabled();
    await page.locator('[data-testid="pb-ob-tile"][data-pf="x"]').click();
    await page.locator('[data-testid="pb-ob-tile"][data-pf="xiaohongshu"]').click();
    await expect(page.getByTestId('pb-ob-continue')).toContainText('2');
    await page.getByTestId('pb-ob-continue').click();
    await expect(page.getByTestId('channels')).toBeVisible(); // step 2: sign in on Accounts
    await hash('#/publish');
  }
  const row = page.getByTestId('pub-platforms');
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row.locator('button[data-pf="x"]')).toBeVisible();
  await expect(row.locator('button[data-pf="xiaohongshu"]')).toBeVisible();
  await expect(row.locator('button[data-pf="kwai"]')).toHaveCount(0); // not connected: not on the board
  await row.locator('button[data-pf="x"]').click();
  await expect(row.locator('button[data-pf="x"]')).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => localStorage.getItem('pb.filter'))).toBe('x');
  await row.locator('button[data-pf="all"]').click();
  await expect(page.getByTestId('pb-add-platform')).toHaveAttribute('href', '#/publish/accounts');
});

const SCREENS = ['#/', '#/inbox', '#/projects', 'PROJECT', 'CLIP', '#/publish', '#/publish/accounts', '#/settings', '#/settings/ai', '#/settings/ai/jobs', '#/settings/accounts', '#/settings/advanced'];

for (const lang of ['en', 'zh-CN', 'fr'] as const) {
  test(`every main screen renders in ${lang}: no missing keys, no clipped labels`, async () => {
    await page.evaluate(async (l) => {
      localStorage.setItem('i18n.strict', '1');
      await window.desk.setSettings({ lang: l });
    }, lang);
    await hash('#/'); // the app sidebar (engine status) - Settings has its own sub-nav
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
    const ids = await page.evaluate(async () => {
      const info = await window.desk.engineInfo();
      const h = await (await fetch(info.baseUrl + '/api/history', { headers: { Authorization: `Bearer ${info.token}` } })).json();
      return (h.items as { id: string; name: string }[]).find((i) => i.name === 'fuye')?.id;
    });
    for (const s of SCREENS) {
      const h = s === 'PROJECT' ? `#/p/${ids}` : s === 'CLIP' ? `#/p/${ids}/clip/${encodeURIComponent('A_换圈子')}` : s;
      await hash(h);
      await page.waitForTimeout(900);
      const problems = await page.evaluate(() => {
        const out: string[] = [];
        const text = document.body.innerText;
        const missing = text.match(/⟦[^⟧]+⟧/g);
        if (missing) out.push(`missing: ${[...new Set(missing)].join(', ')}`);
        const rawKeys = text.match(/\b(?:home|plan|inbox|projects|project|clip|ai|player|editor|pub|palette|keys|status|nav|set|em|issue|focus)\.[a-zA-Z][\w.-]+\b/g);
        if (rawKeys) out.push(`raw keys: ${[...new Set(rawKeys)].join(', ')}`);
        for (const el of document.querySelectorAll<HTMLElement>('.btn, .chip, .nav .label, .st, .seg button, .tabs4 a, .tabs4 button, .vers button')) {
          if (!el.offsetParent || el.closest('.clamp1')) continue;
          if (el.scrollWidth > el.clientWidth + 1) out.push(`clipped: "${el.innerText.trim()}" (${el.scrollWidth} > ${el.clientWidth})`);
        }
        // no sideways scrolling: the page and its scroll areas fit the window (French runs ~25 % longer)
        for (const el of [document.scrollingElement as HTMLElement, ...document.querySelectorAll<HTMLElement>('.scroll, .pg, .agent, .cc')]) {
          if (el && el.offsetParent !== null && el.scrollWidth > el.clientWidth + 2) out.push(`overflow-x: ${el.className || el.tagName} (${el.scrollWidth} > ${el.clientWidth})`);
        }
        return out;
      });
      expect(problems, `${lang} ${h}`).toEqual([]);
    }
    await page.evaluate(() => localStorage.removeItem('i18n.strict'));
  });
}
