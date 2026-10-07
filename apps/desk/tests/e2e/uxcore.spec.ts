// Home + Inbox + how the pages connect (ux/home-redesign) and text-based editing (ux/text-edit), window hidden,
// mock engine (desk implementation), isolated profile:
//   Home busy (Inbox top 3 + n more, Running only while running, Going out today, editable platform chip, no AI chip)
//   Home quiet (All clear + Continue) and first run (six starting points), en / zh / dark
//   Inbox: list + preview, plain-language options (no paths / raw numbers), Confirm -> auto-advance + Undo, ↑ ↓ / E
//   Review all in a row: the editor's triage bar + the pinned question, Skip / Next / ← Inbox
//   ⌘K jumps to clips / posts / settings, ⌘[ goes back
//   Transcript: select words -> Delete -> pending (struck, still there) -> the preview skips them -> ⌘↵ -> one step +
//   the cut card in the chat -> Undo; filler chips; split presets ⌘1 / ⌘3 persist across a reload, divider reset
// Screenshots of every state go to test-results/uxcore (compared by eye with ux/home-redesign + ux/text-edit).
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
let fuyeId = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-ux-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');
const SHOTS = process.env.DESK_SHOTS_DIR ?? path.resolve(import.meta.dirname, '../../test-results/uxcore');
fs.mkdirSync(SHOTS, { recursive: true });

const PICKS = `# PICKS: 多元副业复盘_final.mp4 → 4 条小红书切片

| # | Source span | Len | Title (小红书 units) | Why | Opening line (hook) |
|---|---|---|---|---|---|
| A 换圈子 | 7:30.6 – 8:55.5 | 1:24 | 同一个行业待越久，思路越窄 (13) | x | y |
| B 自媒体 | 8:56.3 – 10:10.8 | 1:13 | 再小的博主，也是博主 (10) | x | y |
| C 底气 | 5:01.4–5:05.3 + 5:10.9–5:16.3 + 10:11.4 – 10:53 | 0:50 | 副业给我的不是钱，是底气 (12) | x | y |
| D 反哺主业 | 5:19.3 – 6:03.2 | 0:43 | 带学员求职，反而帮我面试不挂 (14) | x | y |

## Edits inside the spans (creator should confirm)
- **A** starts at 你在副业当中, skipping 「这也是挺丰富人生的一个事情」, which only makes sense after the previous segment.
- **B** drops 「还有一个点就是」 before 我做自媒体.
- **C** drops the hedge 「或者说也可能是因为程序员这个工作确实在近十年还是OK的」 (5:05.6–5:10.9) and 「另外的话就是」 before 10:11.
- **D** starts at 年初面试 instead of 「比如说做career coach，我能够了解到非常多的东西」. That gives a stronger opening, but the clip is 43 s, 2 s under the 45 s floor. To restore the softer opener, change the D start to 316.72 in \`work/make_src.py\`.
`;

/** A talking-head transcript: sentences, fillers (嗯 / 那个 / 就是) and pauses over 0.6 s. */
const SPEECH = [
  '你在 副业 当中 ， 其实 是 能够 深度 地 链接到 很多 不同 类型 的 人 的 。',
  '嗯 这些 人 ， 其实 不是 你 在 正职 当中 能够 遇到 的 。',
  '你 会 发现 ， 你 在 同一个 行业 待得 越久 ， 你 认识 的 人 、 你 的 思路 ， 都会 局限于 这个 行业 。',
  '去给 Lakeside City College ， 去给 人家 去做 那个 career coach 的 宣讲 的 时候 ， 我 就跟 这个 机构 的 co-founder 去进行了 一些 聊天 。',
  '就是 他们 是 怎么样 通过 在 海外 读书 ， 然后 回国 去 创业 ， 创立 他们 自己 的 品牌 。',
];

function words(): { word: string; start: number; end: number }[] {
  const out: { word: string; start: number; end: number }[] = [];
  let t = 0.3;
  SPEECH.forEach((s, k) => {
    for (const w of s.split(' ')) {
      if (w === '，' || w === '。' || w === '、') {
        if (out.length) out[out.length - 1].word += w;
        continue;
      }
      const d = Math.max(0.22, Math.min(0.55, w.length * 0.12));
      out.push({ word: w, start: Math.round(t * 100) / 100, end: Math.round((t + d) * 100) / 100 });
      t += d + 0.04;
    }
    t += k === 0 ? 0.9 : k === 2 ? 1.6 : 0.35; // a 0.9 s pause, then a new paragraph after 1.6 s
  });
  return out;
}

function ffmpeg(args: string[]) {
  execFileSync('ffmpeg', ['-v', 'error', '-y', ...args]);
}

function fakeBatch(dir: string, name: string) {
  fs.mkdirSync(path.join(dir, 'jobs', 'ep02', 'qc'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'jobs', 'ep02', 'qc', 'qc.json'), JSON.stringify({ checks: [{ name: 'lost-words', ok: false, value: 1, reason: "lost: '我们' @19.01s" }] }));
  const py = `
import json, sqlite3, sys
con = sqlite3.connect(sys.argv[1] + '/batch.db')
con.executescript("""CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE jobs (id TEXT PRIMARY KEY, ord INTEGER, state TEXT, qc TEXT, review TEXT, created REAL, updated REAL);
CREATE TABLE deliveries (n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, client TEXT);""")
con.execute("INSERT INTO meta VALUES ('spec', ?)", (json.dumps(dict(name=sys.argv[2], recipe='longform-split')),))
con.execute("INSERT INTO jobs VALUES ('ep01', 0, 'done', 'green', NULL, 1, 2)")
con.execute("INSERT INTO jobs VALUES ('ep02', 1, 'done', 'red', NULL, 1, 2)")
con.commit()
`;
  execFileSync('python3', ['-c', py, dir, name]);
}

/** An external run writing its heartbeat (vstudio.batch.livestatus): shows under Running. */
function heartbeat(dir: string, rec: Record<string, unknown> = {}) {
  fs.mkdirSync(path.join(dir, '.vstudio'), { recursive: true });
  const now = Date.now() / 1000;
  fs.writeFileSync(path.join(dir, '.vstudio', 'status.json'), JSON.stringify({ status: 'running', stage: 'render', progress: 0.42, message: 'Cutting clip 3 of 6', eta: 360, started: now - 90, heartbeat: now, pid: process.pid, host: os.hostname(), updated_by: 'workflow', ...rec }));
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(path.join(fuye, 'final'), { recursive: true });
  const W = words();
  const dur = Math.ceil(W[W.length - 1].end + 1);
  const lavfi = (w: number, h: number, d: number) => ['-f', 'lavfi', '-i', `testsrc2=size=${w}x${h}:rate=30:duration=${d}`, '-f', 'lavfi', '-i', `sine=frequency=330:duration=${d}`, '-shortest', '-vf', 'hue=s=0.35', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'];
  const clips = ['A_换圈子', 'B_自媒体', 'C_底气', 'D_反哺主业'];
  for (const c of clips) {
    ffmpeg([...lavfi(240, 320, c.startsWith('A') ? dur : 8), path.join(fuye, 'final', `${c}.mp4`)]);
    ffmpeg(['-i', path.join(fuye, 'final', `${c}.mp4`), '-ss', '1', '-frames:v', '1', path.join(fuye, 'final', `${c}_cover.jpg`)]);
  }
  ffmpeg([...lavfi(180, 320, dur), path.join(fuye, 'final', 'A_换圈子_9x16.mp4')]);
  fs.writeFileSync(path.join(fuye, 'final', 'A_换圈子.mp4.asr.json'), JSON.stringify({ segments: [{ start: W[0].start, end: W[W.length - 1].end, words: W }] }));
  const bw = [{ word: '我做', start: 0.4, end: 0.8 }, { word: '自媒体', start: 0.8, end: 1.4 }, { word: '嘛', start: 1.4, end: 1.6 }];
  fs.writeFileSync(path.join(fuye, 'final', 'B_自媒体.mp4.asr.json'), JSON.stringify({ segments: [{ start: 0.4, end: 1.6, words: bw }] }));
  fs.writeFileSync(
    path.join(fuye, 'final', 'post.md'),
    clips.map((c, i) => `## ${c}.mp4  ·  封面 ${c}_cover.jpg\n\n${['同一个行业待越久，思路越窄', '再小的博主，也是博主', '副业给我的不是钱，是底气', '带学员求职，反而帮我面试不挂'][i]}\n\n正文。\n\n#副业\n`).join('\n'),
  );
  fs.writeFileSync(path.join(fuye, 'PICKS.md'), PICKS);
  fakeBatch(path.join(watch, 'rag'), 'rag');
  // ep01 of rag was made by our pipeline: its captions are ours (a caption-only fix is possible)
  const exp = path.join(watch, 'rag', 'jobs', 'ep01', 'export', 'out');
  fs.mkdirSync(exp, { recursive: true });
  ffmpeg([...lavfi(240, 320, 6), path.join(exp, 'xiaohongshu-vertical.mp4')]);
  fs.writeFileSync(path.join(watch, 'rag', 'jobs', 'ep01', 'export', 'manifest.json'), JSON.stringify({ exports: [{ platform: 'xiaohongshu', orientation: 'vertical', file: 'xiaohongshu-vertical.mp4', w: 240, h: 320, fps: 30, duration: 6 }] }));
  const rw = [{ word: '可能', start: 0.3, end: 0.7 }, { word: '都是', start: 0.7, end: 1.0 }, { word: '疏图同归', start: 1.0, end: 1.8 }, { word: '的。', start: 1.8, end: 2.0 }];
  fs.writeFileSync(path.join(exp, 'xiaohongshu-vertical.mp4.asr.json'), JSON.stringify({ segments: [{ start: 0.3, end: 2.0, words: rw }] }));
  fs.mkdirSync(path.join(watch, 'rag', 'jobs', 'ep01', 'compose'), { recursive: true });
  fs.writeFileSync(path.join(watch, 'rag', 'jobs', 'ep01', 'compose', 'cues.json'), JSON.stringify({ cues: [{ i: 0, start: 0.3, end: 2.0, text: '可能都是疏图同归的。' }] }));
  const live = path.join(watch, 'AI short');
  fs.mkdirSync(path.join(live, 'final'), { recursive: true });
  fs.writeFileSync(path.join(live, 'REPORT.md'), '# AI short\n');
  heartbeat(live, { message: 'Making shots 4 of 12' });
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.setSettings({ lang: 'en', theme: 'notebook-light', defaultPlatforms: ['xiaohongshu', 'douyin', 'tiktok', 'youtube', 'bilibili'] });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
  fuyeId = await api<string>(async (base, auth) => {
    for (let i = 0; i < 60; i++) {
      const h = await (await fetch(base + '/api/history', { headers: auth })).json();
      const it = (h.items as { id: string; name: string }[]).find((x) => x.name === 'fuye');
      if (it) return it.id;
      await new Promise((r) => setTimeout(r, 500));
    }
    return '';
  });
  expect(fuyeId).toMatch(/^[0-9a-f]{12}$/);
  // today's posts: two out already, two still to go
  const d = new Date();
  const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  await page.evaluate(
    async ([item, today]) => {
      const info = await window.desk.engineInfo();
      const post = async (body: unknown, url = '/api/calendar') =>
        (await fetch(info.baseUrl + url, { method: 'POST', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
      const rows = [
        ['A_换圈子', '09:00', 'xiaohongshu', 'posted'],
        ['B_自媒体', '12:30', 'douyin', 'posted'],
        ['C_底气', '18:00', 'xiaohongshu', 'planned'],
        ['D_反哺主业', '20:00', 'douyin', 'planned'],
      ];
      for (const [clip, time, platform, state] of rows) {
        const r = await post({ item, clip, at: `${today}T${time}`, platform });
        if (state === 'posted') await post({ state: 'posted' }, `/api/calendar/${r.id}`);
      }
    },
    [fuyeId, day],
  );
});

test.afterAll(async () => {
  await app?.close();
});

/** The engine's HTTP API from the test process (the page's CSP forbids building functions from strings). */
async function api<T>(fn: (base: string, auth: Record<string, string>) => Promise<T>): Promise<T> {
  const info = await page.evaluate(() => window.desk.engineInfo());
  return fn(info.baseUrl, { Authorization: `Bearer ${info.token}` });
}

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const shot = async (name: string) => {
  await page.waitForTimeout(260); // cards fade in over 180 ms
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};

async function setLook(lang: 'en' | 'zh-CN' | 'fr', theme: 'notebook-light' | 'studio-dark' = 'notebook-light') {
  await page.evaluate(async ([l, th]) => {
    await window.desk.setSettings({ lang: l, theme: th as 'notebook-light' | 'studio-dark' });
  }, [lang, theme] as const);
  await hash('#/');
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
}

async function noMissingKeys() {
  const text = await page.evaluate(() => document.body.innerText);
  expect(text.match(/⟦[^⟧]+⟧/g) ?? []).toEqual([]);
  expect(text.match(/\b(te|inbox|home|pin|triage)\.[a-zA-Z][\w.-]+/g) ?? []).toEqual([]);
}

test('Home busy: the Inbox top 3 + n more, Running, Going out today, the platform chip; no AI chip', async () => {
  await hash('#/');
  const inbox = page.getByTestId('home-inbox');
  await expect(inbox).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('home-inbox-row').first()).toBeVisible();
  const n = await page.getByTestId('home-inbox-row').count();
  expect(n).toBeGreaterThanOrEqual(2);
  expect(n).toBeLessThanOrEqual(3);
  // the Inbox badge says the same number as Home
  const badge = await page.getByTestId('inbox-badge').innerText();
  await expect(page.getByTestId('home-inbox-count')).toContainText(new RegExp(`^${badge} `));
  await expect(page.getByTestId('live-lane')).toContainText('AI short', { timeout: 15000 });
  await expect(page.getByTestId('home-today').getByTestId('home-post')).toHaveCount(4);
  await expect(page.getByTestId('home-all-clear')).toHaveCount(0);
  await expect(page.getByTestId('composer-provider-chip')).toHaveCount(0); // where AI runs lives in Settings now
  await expect(page.getByTestId('composer-platforms')).toContainText('Xiaohongshu, Douyin +3');
  await expect(page.getByTestId('home-idea').first()).toBeVisible();
  await expect(page.locator('.btn.primary:visible')).toHaveCount(0); // Make a plan lights up once there is something to plan
  await noMissingKeys();
  await shot('A1-home-busy');
  // the platform chip is editable and remembered
  await page.getByTestId('composer-platforms').click();
  await expect(page.getByTestId('platform-popover')).toBeVisible();
  await page.getByTestId('platform-popover').locator('button[data-pf="bilibili"]').click();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('composer-platforms')).toContainText('Xiaohongshu, Douyin +2');
  expect((await page.evaluate(() => window.desk.getSettings())).defaultPlatforms).not.toContain('bilibili');
  // the paperclip opens Add files / Add folder and the menu stays open (the opening click must not close it)
  await page.getByTestId('composer-attach').click();
  await expect(page.getByTestId('add-files')).toBeVisible();
  await expect(page.getByTestId('add-folder')).toBeVisible();
  await page.waitForTimeout(200);
  await expect(page.getByTestId('add-files')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.mouse.click(5, 5);
  // typing: Make a plan becomes the one filled button, ⌘↵ shown
  await page.getByTestId('composer-input').fill('Cut this recording into 3 Douyin clips');
  await expect(page.getByTestId('make-plan')).toHaveClass(/primary/);
  await shot('A4-home-typing');
  await page.getByTestId('composer-input').fill('');
});

test('Inbox: list + preview, plain choices, confirm -> next one + Undo, ↑ ↓', async () => {
  await page.getByTestId('nav-inbox').click();
  await expect(page.getByTestId('inbox-list')).toBeVisible({ timeout: 30000 });
  const row = page.getByTestId('inbox-item').filter({ hasText: 'fuye' });
  await row.click();
  const pv = page.getByTestId('inbox-preview');
  await expect(pv).toHaveAttribute('data-kind', 'confirm');
  const opts = pv.getByTestId('inbox-option');
  await expect(opts).toHaveCount(4);
  const text = await pv.innerText();
  expect(text).not.toMatch(/\.py|316\.72|`|work\//); // never the engine's notes to itself
  await expect(opts.nth(3)).toContainText('Which opening?');
  await expect(opts.nth(3).getByTestId('inbox-choice').first()).toContainText('Keep softer opener');
  await expect(opts.nth(3).getByTestId('inbox-choice').first()).toContainText('Recommended');
  await expect(pv.getByTestId('crumb-project')).toHaveText('fuye');
  await expect(pv.getByTestId('cut-preview-video')).toHaveAttribute('src', /A_/);
  await expect(pv.getByTestId('cut-before')).toBeDisabled(); // the source recording is not in the folder
  await opts.nth(1).click(); // the preview follows the option (clip B, 3 s around the cut)
  await expect(pv.getByTestId('cut-preview-video')).toHaveAttribute('src', /B_/);
  await expect(pv.getByTestId('crumb-clip')).toContainText('Clip B');
  // the bar seeks: a click near the end moves the playhead there and it stays (no snap back to the 6 s window)
  const bar = pv.getByTestId('cut-preview-bar');
  await expect.poll(async () => Number(await bar.getAttribute('aria-valuemax'))).toBeGreaterThan(0);
  const bb = (await bar.boundingBox())!;
  await page.mouse.click(bb.x + bb.width * 0.9, bb.y + bb.height / 2);
  const max = Number(await bar.getAttribute('aria-valuemax'));
  await expect.poll(async () => Number(await bar.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(Math.floor(max * 0.8));
  await noMissingKeys();
  await shot('I1-inbox');
  const total = await page.getByTestId('inbox-item').count();
  await pv.getByTestId('inbox-confirm').click();
  await expect(page.getByTestId('inbox-item')).toHaveCount(total - 1);
  await expect(page.getByTestId('inbox-item').filter({ hasText: 'fuye' }).filter({ hasText: /Confirm/ })).toHaveCount(0);
  await expect(page.locator('.ux-irow.on')).toHaveCount(1); // auto-advance: the next item is open
  await shot('I2-inbox-next-item');
  await page.getByTestId('toast-undo').click();
  await expect(page.getByTestId('inbox-item')).toHaveCount(total);
  // keyboard: ↓ moves, Enter on a confirm item answers it (undo again)
  await page.getByTestId('inbox-item').first().click();
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('.ux-irow.on')).toHaveAttribute('data-key', await page.getByTestId('inbox-item').nth(1).getAttribute('data-key') ?? '');
  expect(fs.existsSync(path.join(fuye, '.vstudio'))).toBe(false); // answers live in the desk, not in her folder
});

test('Review all in a row: the triage bar, the pinned question in the editor; Skip, Next, ← Inbox', async () => {
  await page.getByTestId('nav-inbox').click();
  await page.getByTestId('inbox-item').first().click();
  await page.getByTestId('inbox-triage').click();
  const bar = page.getByTestId('triage-bar');
  await expect(bar).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('triage-count')).toHaveText('1 of 2');
  // an item without a clip stays in the Inbox, with the bar on top
  await expect(page.getByTestId('inbox-preview')).toHaveAttribute('data-kind', 'review');
  await page.getByTestId('triage-skip').click();
  await expect(page.getByTestId('triage-count')).toHaveText('2 of 2');
  await expect(page.getByTestId('editor')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('pinned-question')).toBeVisible();
  await expect(page.getByTestId('pinned-question').getByTestId('inbox-option')).toHaveCount(4);
  await expect(page.getByTestId('editor-breadcrumb')).toContainText('fuye');
  await noMissingKeys();
  await shot('I3-editor-from-inbox');
  await page.getByTestId('triage-back').click();
  await expect(page.getByTestId('inbox')).toBeVisible();
  await expect(page.getByTestId('triage-bar')).toHaveCount(0);
});

test('⌘K jumps to clips, posts and settings; ⌘[ goes back', async () => {
  await hash('#/');
  await page.keyboard.press('Meta+k');
  await page.getByTestId('palette-input').fill('AI accounts');
  await expect(page.getByTestId('palette-item').first()).toContainText(/AI accounts/);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/settings\/ai/);
  await page.keyboard.press('Meta+[');
  await expect(page.getByTestId('home')).toBeVisible();
  await page.keyboard.press('Meta+k');
  await page.getByTestId('palette-input').fill('底气');
  await expect(page.getByTestId('palette-item').filter({ hasText: '底气' }).first()).toBeVisible({ timeout: 15000 });
  await shot('K1-palette');
  await page.getByTestId('palette-item').filter({ hasText: '副业给我的不是钱' }).first().click();
  await expect(page).toHaveURL(/#\/(publish\?post=|p\/)/);
});

test('transcript: select -> Delete -> pending + skipped in preview -> ⌘↵ = one step + the cut card -> Undo', async () => {
  await hash(`#/p/${fuyeId}/clip/${encodeURIComponent('A_换圈子')}`);
  await expect(page.getByTestId('transcript-body')).toBeVisible({ timeout: 30000 }); // talking-head: Transcript first
  await expect(page.getByTestId('lower-pane')).toHaveAttribute('data-tab', 'transcript');
  const w = (i: number) => page.locator(`[data-testid=transcript-body] .w[data-i="${i}"]`);
  await expect(w(0)).toHaveText('你在');
  // the fillers chip knows 嗯 / 那个 / 就是
  await expect(page.getByTestId('marks-filler')).toContainText('3');
  // the chat offers the same without the model: fillers -> pending cuts
  await expect(page.getByTestId('sug-fillers')).toContainText('Remove 3 filler words');
  await shot('T1-balanced');
  await page.getByTestId('sug-fillers').click();
  await expect(page.getByTestId('pending-bar')).toContainText('3 cuts pending');
  await page.getByTestId('pending-discard').click();
  // select 去给 Lakeside City College， (a drag across words) and press Delete
  const start = (await page.evaluate(() => [...document.querySelectorAll('[data-testid=transcript-body] .w')].findIndex((e) => e.textContent?.startsWith('去给'))));
  const a = await w(start).boundingBox();
  const b = await w(start + 3).boundingBox();
  await page.mouse.move(a!.x + 3, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width - 3, b!.y + b!.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByTestId('selection-bar')).toBeVisible();
  await expect(page.getByTestId('selection-bar')).toContainText('4 words');
  await page.keyboard.press('Delete');
  await expect(w(start)).toHaveClass(/\bp\b/); // pending: struck through, still there
  await expect(page.getByTestId('pending-bar')).toContainText('1 cut pending');
  await expect(page.getByTestId('editor-length')).toContainText('→');
  await expect(page.locator('.btn.primary:visible')).toHaveCount(1); // Apply cuts is the one filled button
  await expect(page.getByTestId('pending-apply')).toHaveClass(/primary/);
  // the preview skips it: play from just before, the playhead jumps over the cut
  const cutStart = await page.evaluate((i) => {
    const el = document.querySelector(`[data-testid=transcript-body] .w[data-i="${i}"]`);
    return el ? i : -1;
  }, start);
  expect(cutStart).toBe(start);
  const t0 = words()[start].start;
  const t1 = words()[start + 3].end;
  await page.evaluate((x) => {
    const v = document.querySelector('[data-testid=player-video]') as HTMLVideoElement;
    v.currentTime = x;
    void v.play();
  }, t0 - 0.6);
  await expect(page.getByTestId('skip-flash')).toBeVisible({ timeout: 5000 });
  // past the cut and still playing (never stuck on the cut's last frame), the flash goes away
  await expect.poll(() => page.evaluate(() => (document.querySelector('[data-testid=player-video]') as HTMLVideoElement).currentTime), { timeout: 5000 }).toBeGreaterThan(t1 + 0.4);
  await expect(page.getByTestId('skip-flash')).toHaveCount(0, { timeout: 3000 });
  await page.evaluate((x) => {
    const v = document.querySelector('[data-testid=player-video]') as HTMLVideoElement;
    v.currentTime = x;
    void v.play();
  }, t0 - 0.6);
  await expect(page.getByTestId('skip-flash')).toBeVisible({ timeout: 5000 });
  await page.evaluate(() => (document.querySelector('[data-testid=player-video]') as HTMLVideoElement).pause());
  await shot('T3-selected-pending');
  // the same pending cut on the timeline tab
  await page.getByTestId('tab-timeline').click();
  await expect(page.getByTestId('tl-pending')).toHaveCount(1);
  await shot('T4-timeline-pending');
  await page.getByTestId('tab-transcript').click();
  // ⌘↵ applies: ONE step, the card in the chat, a cut marker in the transcript
  const before = await api<number>(async (base, auth) => {
    const h = await (await fetch(`${base}/api/history`, { headers: auth })).json();
    const id = (h.items as { id: string; name: string }[]).find((x) => x.name === 'fuye')!.id;
    return (await (await fetch(`${base}/api/outputs/${id}/${encodeURIComponent('A_换圈子')}`, { headers: auth })).json()).steps.length;
  });
  await page.getByTestId('transcript-body').focus();
  await page.keyboard.press('Meta+Enter');
  await expect(page.getByTestId('cut-card')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('cut-card')).toContainText('Cut 1 phrase');
  await expect(page.getByTestId('cut-card')).toContainText('Lakeside City College');
  await expect(page.getByTestId('cut-marker')).toHaveCount(1);
  await expect(page.getByTestId('pending-bar')).toHaveCount(0);
  const after = await api<number>(async (base, auth) => {
    const h = await (await fetch(`${base}/api/history`, { headers: auth })).json();
    const id = (h.items as { id: string; name: string }[]).find((x) => x.name === 'fuye')!.id;
    return (await (await fetch(`${base}/api/outputs/${id}/${encodeURIComponent('A_换圈子')}`, { headers: auth })).json()).steps.length;
  });
  expect(after).toBe(before + 1);
  await noMissingKeys();
  await shot('T5-applied');
  // fillers: remove all from the chip menu -> pending
  await page.getByTestId('marks-filler').click();
  await expect(page.getByTestId('marks-menu-filler')).toBeVisible();
  await shot('T2-fillers-menu');
  await page.getByTestId('marks-remove-all').click();
  await expect(page.getByTestId('pending-bar')).toContainText(/3 cuts pending/);
  await page.getByTestId('pending-discard').click();
  await expect(page.getByTestId('pending-bar')).toHaveCount(0);
  // Undo in the card = the whole batch back
  await page.getByTestId('cut-card-undo').click();
  await expect(page.getByTestId('cut-marker')).toHaveCount(0, { timeout: 15000 });
  await expect(w(start)).not.toHaveClass(/\bp\b/);
});

test('fix a word in the captions (E): caption only, a teal underline, not a cut', async () => {
  const rag = await api<string>(async (base, auth) => {
    const h = await (await fetch(base + '/api/history', { headers: auth })).json();
    return (h.items as { id: string; name: string }[]).find((x) => x.name === 'rag')!.id;
  });
  await hash(`#/p/${rag}/clip/ep01`);
  const body = page.getByTestId('transcript-body');
  await expect(body).toBeVisible({ timeout: 30000 });
  await body.locator('.w[data-i="2"]').click();
  await page.keyboard.press('e');
  const pop = page.getByTestId('fix-popover');
  await expect(pop).toBeVisible();
  await expect(pop).toContainText('疏图同归');
  await page.getByTestId('fix-input').fill('殊途同归');
  await shot('T8-fixword');
  await page.getByTestId('fix-input').press('Enter');
  await expect(pop).toHaveCount(0);
  await expect(body.locator('.w[data-i="2"]')).toHaveText('殊途同归');
  await expect(body.locator('.w[data-i="2"]')).toHaveClass(/\bfx\b/);
  await expect(body.locator('.w.p')).toHaveCount(0); // not a cut
  const doc = await api<{ captions: { text: string }[]; cuts: unknown[] }>(async (base, auth) => (await fetch(`${base}/api/outputs/${rag}/ep01`, { headers: auth })).json());
  expect(doc.captions[0].text).toBe('可能都是殊途同归的。');
  expect(doc.cuts).toEqual([]);
});

test('split presets: ⌘3 / ⌘1 / ⌘2, drag + double-click reset, saved across a reload; ⌘\\ folds the chat', async () => {
  const stageH = () => page.locator('.ce-stage').evaluate((el) => el.getBoundingClientRect().height);
  const mainH = () => page.locator('.ce-split3').evaluate((el) => el.getBoundingClientRect().height);
  await page.locator('.ce-top').click();
  await page.keyboard.press('Meta+3');
  await expect.poll(async () => (await stageH()) / (await mainH())).toBeLessThan(0.4);
  await expect(page.getByTestId('preset-edit')).toHaveAttribute('aria-pressed', 'true');
  await shot('T6-editfocus');
  await page.keyboard.press('Meta+1');
  await expect.poll(async () => (await stageH()) / (await mainH())).toBeGreaterThan(0.6);
  await page.keyboard.press('Meta+\\');
  await expect(page.getByTestId('chat-panel')).toHaveAttribute('data-collapsed', '1');
  await shot('T7-playerfocus');
  await page.keyboard.press('Meta+\\');
  await page.keyboard.press('Meta+3');
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('editor')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('preset-edit')).toHaveAttribute('aria-pressed', 'true');
  expect((await stageH()) / (await mainH())).toBeLessThan(0.4);
  // drag the divider down a little, then double-click: balanced again
  const d = (await page.getByTestId('split-divider').boundingBox())!;
  await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2);
  await page.mouse.down();
  await page.mouse.move(d.x + d.width / 2, d.y + 120, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByTestId('preset-edit')).toHaveAttribute('aria-pressed', 'false');
  await page.getByTestId('split-divider').dblclick();
  await expect(page.getByTestId('preset-balanced')).toHaveAttribute('aria-pressed', 'true');
  expect(Math.abs((await stageH()) / (await mainH()) - 0.5)).toBeLessThan(0.05);
});

test('zh-CN + dark: Home, Inbox, the transcript', async () => {
  await setLook('zh-CN');
  await hash('#/');
  await expect(page.getByTestId('home-inbox')).toBeVisible({ timeout: 30000 });
  await noMissingKeys();
  await shot('A5-home-busy-zh');
  await page.getByTestId('nav-inbox').click();
  await page.getByTestId('inbox-item').filter({ hasText: 'fuye' }).click();
  await expect(page.getByTestId('inbox-option').nth(3)).toContainText('用哪个开头');
  await noMissingKeys();
  await shot('I1-inbox-zh');
  await hash(`#/p/${fuyeId}/clip/${encodeURIComponent('A_换圈子')}`);
  await expect(page.getByTestId('transcript-body')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('marks-filler').click();
  await page.getByTestId('marks-remove-all').click();
  await shot('T3-zh-pending');
  await page.getByTestId('pending-discard').click();
  await setLook('en', 'studio-dark');
  await hash('#/');
  await expect(page.getByTestId('home-inbox')).toBeVisible({ timeout: 30000 });
  await shot('A6-home-busy-dark');
  await hash(`#/p/${fuyeId}/clip/${encodeURIComponent('A_换圈子')}`);
  await expect(page.getByTestId('transcript-body')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('marks-filler').click();
  await page.getByTestId('marks-remove-all').click();
  await shot('T3-dark-pending');
  await page.getByTestId('pending-discard').click();
  await setLook('fr');
  await hash('#/');
  await expect(page.getByTestId('home-inbox')).toBeVisible({ timeout: 30000 });
  await noMissingKeys();
  await page.getByTestId('nav-inbox').click();
  await expect(page.getByTestId('inbox-list')).toBeVisible();
  await noMissingKeys();
  await setLook('en');
});

test('Home quiet: All clear + Continue once nothing runs and nothing needs her', async () => {
  // answer everything, stop the run
  heartbeat(path.join(watch, 'AI short'), { status: 'done', heartbeat: Date.now() / 1000, pid: 999999 });
  await api(async (base, auth) => {
    const d = await (await fetch(`${base}/api/inbox`, { headers: auth })).json();
    const keys = (d.items as { key: string }[]).map((x) => x.key);
    if (keys.length) await fetch(`${base}/api/inbox/answer`, { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ keys }) });
    return keys.length;
  });
  await hash('#/inbox');
  await hash('#/');
  await expect(page.getByTestId('home-all-clear')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('live-lane')).toHaveCount(0);
  await expect(page.getByTestId('home-inbox')).toHaveCount(0);
  await expect(page.getByTestId('home-continue').getByTestId('project-card').first()).toBeVisible();
  await noMissingKeys();
  await shot('A2-home-quiet');
});

test('first run: no projects yet -> six starting points', async () => {
  const empty = path.join(tmp, 'empty');
  fs.mkdirSync(empty, { recursive: true });
  const app2 = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_SEED: '0', DESK_USER_DATA: path.join(tmp, 'profile2'), VSTUDIO_HOME: path.join(tmp, 'vhome2'), DESK_HISTORY_WATCH: empty, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  try {
    const p2 = await app2.firstWindow();
    await p2.setViewportSize({ width: 1440, height: 900 });
    await p2.waitForURL(/^app:\/\/desk\//);
    await p2.evaluate(async () => {
      await window.desk.setSettings({ lang: 'en', theme: 'notebook-light' });
    });
    await p2.reload();
    await expect(p2.getByTestId('home-starts')).toBeVisible({ timeout: 30000 });
    await expect(p2.getByTestId('home-start')).toHaveCount(6);
    await expect(p2.locator('.ux-hello h1')).toHaveText('What do you want to make?');
    await p2.getByTestId('home-start').nth(1).click();
    await expect(p2.getByTestId('composer-input')).not.toHaveValue('');
    await p2.getByTestId('composer-input').fill('');
    await p2.screenshot({ path: path.join(SHOTS, 'A3-home-first-run.png') });
  } finally {
    await app2.close();
  }
});
