// 「这周的素材 → 一周的帖子」 + Send feedback + Report this problem, window hidden, mock engine, isolated profile.
//   - Home: files in the composer -> "Make this week's posts" -> plan card (clips, platforms, when to post) -> her
//     words change the rule (and the clip count) -> Make (refused on the demo engine, in words) -> once the run's
//     clips are on disk: progress -> "Your week is ready" -> Publish shows the week as dashed cards with ONE primary
//     "Schedule n posts" -> written as one step, undo removes them
//   - a run that fails (its desk-pilot.* record): plain reason on the board + Report this problem (redacted text,
//     must be read, opens a prefilled issue); Put away
//   - Help › Send feedback…, Settings › Help and diagnostics, the Inbox empty-state link: a prefilled Discussion /
//     Issue opens in the browser (stubbed here); "Send crash reports automatically" is off and unavailable
//   - a renderer error -> the problem bar -> Report this problem
// E2E_LANG=zh-CN runs the same flow in Chinese; SHOTS_DIR=<folder> saves screenshots of every step.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const LANG = process.env.E2E_LANG || 'en';
const SHOTS = process.env.SHOTS_DIR || '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-wp-'));
const src = path.join(tmp, 'this-week');

test.describe.configure({ mode: 'serial' });

const shot = async (name: string) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOTS, `${LANG}-${name}.png`) });
};
const api = <T,>(p: string, body?: unknown) =>
  page.evaluate(
    async ([u, b]) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + u, {
        method: b === undefined ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' },
        body: b === undefined ? undefined : JSON.stringify(b),
      });
      return r.json();
    },
    [p, body] as const,
  ) as Promise<T>;
type Plan = { id: string; state: string; want: number; preview: { drafts: { at: string; platform: string }[]; left?: number } | null; scheduled: string[] };
const opened = () => app.evaluate(() => (globalThis as unknown as { __opened: string[] }).__opened.slice());

test.beforeAll(async () => {
  for (const d of [src]) {
    fs.mkdirSync(d, { recursive: true });
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=3', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(d, 'monday.mp4')]);
  }
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.05', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: path.join(tmp, 'none'), DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  // never open a real browser: record the URLs instead
  await app.evaluate(({ shell }) => {
    (globalThis as unknown as { __opened: string[] }).__opened = [];
    shell.openExternal = async (u: string) => void (globalThis as unknown as { __opened: string[] }).__opened.push(u);
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async (lang) => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.setSettings({ lang: lang as 'en' });
    for (const a of ['xiaohongshu', 'douyin']) await window.desk.publish.addAccount(a, 'main');
    await window.desk.publish.updateChannel('xiaohongshu', 'main', { name: '@me', times: ['21:00'] });
  }, LANG);
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await app?.close();
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);

test('Inbox empty state + Help menu: Send feedback opens a prefilled Discussion, never sends', async () => {
  await hash('#/inbox');
  await expect(page.getByTestId('feedback-link')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('feedback-link').click();
  const sheet = page.getByTestId('feedback-sheet');
  await expect(sheet).toBeVisible();
  await expect(page.getByTestId('feedback-open')).toBeDisabled(); // nothing written yet
  await page.getByTestId('feedback-what').fill('The week board is great.\nCould it also post on Sundays?');
  await page.getByTestId('feedback-email').fill('not-an-email');
  await expect(page.getByTestId('feedback-open')).toBeDisabled();
  await page.getByTestId('feedback-email').fill('');
  await page.getByTestId('feedback-diag').check();
  await expect(page.getByTestId('feedback-diag-text')).toContainText('Electron');
  await expect(page.getByTestId('feedback-diag-text')).not.toContainText(os.homedir());
  await shot('feedback');
  await page.getByTestId('feedback-open').click();
  await expect(sheet).toHaveCount(0);
  const u = new URL((await opened()).at(-1)!);
  expect(u.pathname).toBe('/zyziyun/reelfold/discussions/new');
  expect(u.searchParams.get('title')).toBe('The week board is great.');
  expect(u.searchParams.get('body')).toContain('Could it also post on Sundays?');
  expect(u.searchParams.get('body')).toContain('Diagnostics');
  expect(u.searchParams.get('body')).not.toContain(os.homedir());
  // the Help menu item opens the same form ("Something broke" -> the bug template)
  await app.evaluate(({ Menu }) => {
    const help = Menu.getApplicationMenu()!.items.find((i) => i.role === 'help' || /help|帮助|aide/i.test(i.label))!;
    help.submenu!.items.at(-1)!.click();
  });
  await expect(sheet).toBeVisible();
  await page.getByTestId('feedback-kind-bug').click();
  await page.getByTestId('feedback-what').fill('Export froze at 90%');
  await page.getByTestId('feedback-open').click();
  const b = new URL((await opened()).at(-1)!);
  expect(b.pathname).toBe('/zyziyun/reelfold/issues/new');
  expect(b.searchParams.get('template')).toBe('bug_report.yml');
  expect(b.searchParams.get('got')).toContain('Export froze at 90%');
});

test('Settings › Help and diagnostics: Send feedback + crash reports off (no endpoint in this version)', async () => {
  await hash('#/settings/advanced');
  await page.getByTestId('adv-diag').locator('button').first().click();
  await expect(page.getByTestId('settings-feedback')).toBeVisible();
  await expect(page.getByTestId('crash-auto')).not.toBeChecked();
  await expect(page.getByTestId('crash-auto')).toBeDisabled();
  await shot('settings-help');
  await page.getByTestId('settings-feedback').click();
  await expect(page.getByTestId('feedback-sheet')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('feedback-sheet')).toHaveCount(0);
});

test('Home: dropped footage -> Make this week’s posts -> the plan, when to post, in her words', async () => {
  await hash('#/');
  await page.evaluate((f) => sessionStorage.setItem('v4.composer', JSON.stringify({ prompt: '', files: [f] })), src);
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('home-week')).toBeVisible({ timeout: 30000 });
  await shot('home-chip');
  await page.getByTestId('home-week').click();
  const card = page.getByTestId('weekplan');
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute('data-state', 'ready', { timeout: 30000 });
  await expect(page.getByTestId('composer-files')).toHaveCount(0); // the files went to the week plan
  // default rule: each account's usual time (Xiaohongshu 21:00), else the platform's (Douyin 18:00)
  await expect(page.getByTestId('weekplan-rules').locator('li')).toHaveCount(2);
  await expect(page.getByTestId('weekplan-rules')).toContainText('21:00');
  await expect(page.getByTestId('weekplan-rules')).toContainText('18:00');
  await expect(page.getByTestId('weekplan-facts')).toContainText('7');
  await shot('home-plan');
  // she says it in words: weekdays at 8pm -> 5 clips, both platforms at 20:00
  await page.getByTestId('weekplan-words').fill('weekdays 8pm');
  await page.getByTestId('weekplan-words-go').click();
  await expect(card).toHaveAttribute('data-state', 'ready', { timeout: 30000 });
  await expect(page.getByTestId('weekplan-rules')).not.toContainText('21:00');
  await expect(page.getByTestId('weekplan-rules').locator('li').first()).toContainText('20:00');
  await expect(page.getByTestId('weekplan-facts')).toContainText('5');
  // words that say nothing are refused, the plan stays
  await page.getByTestId('weekplan-words').fill('blah');
  await page.getByTestId('weekplan-words-go').click();
  await expect(page.getByTestId('weekplan-miss')).toBeVisible();
  await page.getByTestId('weekplan-words').fill('weekdays 8pm');
});

// The demo engine has no vstudio.project, so "Make" is refused in words; the steps after it are driven by what a real
// `vstudio.project run` leaves on disk (a project folder with its clips / a failed run's desk-pilot.* record),
// written here in the engine's own formats. Everything from there on is the real desk code.
const DATA = path.join(tmp, 'profile', 'engine-data');
const VHOME = path.join(tmp, 'vhome');
function registerProject(dir: string, name: string) {
  const reg = path.join(VHOME, 'projects.json');
  const rows = fs.existsSync(reg) ? JSON.parse(fs.readFileSync(reg, 'utf8')) : [];
  rows.push({ dir, name, recipe: 'longform-to-short', series: null, client: null, created: new Date().toISOString().slice(0, 19), kind: 'work' });
  fs.mkdirSync(VHOME, { recursive: true });
  fs.writeFileSync(reg, JSON.stringify(rows));
  fs.mkdirSync(path.join(dir, '.vstudio'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.vstudio', 'work.json'), JSON.stringify({ kind: 'work', title: name, recipe: 'longform-to-short', type: 'slices', outputs: [], covers: [], posts: [], sheets: [], notes: [], sources: [] }));
}
function madeClips(dir: string, n: number) {
  const fin = path.join(dir, 'final');
  fs.mkdirSync(fin, { recursive: true });
  let md = '# 发布文案\n\n';
  for (let k = 1; k <= n; k++) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', path.join(fin, `0${k}_clip.mp4`)]);
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', path.join(fin, `0${k}_clip.mp4`), '-frames:v', '1', path.join(fin, `0${k}_clip_cover.jpg`)]);
    md += `## 0${k}_clip.mp4  ·  封面 0${k}_clip_cover.jpg\n\n第 ${k} 条\n\n正文。\n\n#一周更新\n\n`;
  }
  fs.writeFileSync(path.join(fin, 'post.md'), md);
  fs.writeFileSync(path.join(dir, '.vstudio', 'status.json'), JSON.stringify({ status: 'done', stage: 'done', progress: 1, heartbeat: Date.now() / 1000, finished: Date.now() / 1000 }));
}
function setPlan(id: string, patch: Record<string, unknown>) {
  const f = path.join(DATA, 'weekplans', `${id}.json`);
  const rec = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {};
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify({ ...rec, ...patch }));
}

test('Make on the demo engine: the button says why it is off, and the engine refuses too (no pretend run)', async () => {
  await expect(page.getByTestId('weekplan-run')).toBeDisabled();
  await expect(page.getByTestId('weekplan-needs-engine')).toBeVisible();
  const wp = (await api<{ plans: Plan[] }>('/api/weekplan')).plans[0];
  const r = await api<{ error?: string }>(`/api/weekplan/${wp.id}/run`, {});
  expect(r.error).toContain('needs the Reelfold engine');
  expect((await api<Plan>(`/api/weekplan/${wp.id}`)).state).toBe('ready');
});

test('the clips are made -> her OK -> the week is ready -> Publish shows it dashed with ONE primary -> Schedule + undo', async () => {
  const wp = (await api<{ plans: Plan[] }>('/api/weekplan')).plans[0];
  const dir = path.join(VHOME, 'projects', wp.id, '01-this-week');
  registerProject(dir, 'this-week · 3 条切片');
  setPlan(wp.id, { state: 'making', projects: [{ dir, name: 'this-week · 3 条切片', recipe: 'longform-to-short' }], progress: 0.4 });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  const card = page.getByTestId('weekplan');
  await expect(card).toHaveAttribute('data-state', 'making', { timeout: 30000 });
  await shot('home-making');
  // the run parks at the publish check (never automatic): the week waits for her OK
  fs.writeFileSync(path.join(dir, '.vstudio', 'status.json'), JSON.stringify({ status: 'waiting', stage: 'publish', progress: 0.9, needs_you: true, heartbeat: Date.now() / 1000 }));
  await expect(card).toHaveAttribute('data-state', 'review', { timeout: 30000 });
  await expect(page.getByTestId('weekplan-review')).toBeVisible();
  await shot('home-review');
  // approved in the review: the run finishes with every clip
  madeClips(dir, 3);
  await expect(card).toHaveAttribute('data-state', 'preview', { timeout: 60000 });
  await shot('home-ready');
  const now = (await api<{ plans: Plan[] }>('/api/weekplan')).plans[0];
  expect(now.state).toBe('preview');
  const n = now.preview!.drafts.length;
  expect(n).toBeGreaterThan(0);
  expect(now.preview!.drafts.every((d) => d.at.endsWith('T20:00'))).toBe(true); // her words: weekdays 8pm
  expect(new Set(now.preview!.drafts.map((d) => new Date(`${d.at.slice(0, 10)}T12:00`).getDay())).has(0)).toBe(false);
  await page.getByTestId('weekplan-see').click();
  await expect(page.getByTestId('pub-week')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('pb-nl')).toHaveAttribute('data-week', '1');
  await expect(page.getByTestId('pb-proposed').first()).toBeVisible();
  await expect(page.getByTestId('pub-confirm')).toHaveCount(0); // the week's Schedule is the only primary
  await expect(page.locator('.pb .btn.primary:visible')).toHaveCount(1);
  await expect(page.getByTestId('pb-nl-apply')).toContainText(String(n));
  expect((await api<{ posts: unknown[] }>('/api/calendar')).posts).toHaveLength(0); // a preview writes nothing
  await shot('publish-preview');
  await page.getByTestId('pb-nl-apply').click();
  await expect(page.getByTestId('pb-proposed')).toHaveCount(0);
  await expect.poll(async () => (await api<{ posts: unknown[] }>('/api/calendar')).posts.length).toBe(n);
  await expect(page.getByTestId('pub-post').first()).toBeVisible();
  await shot('publish-scheduled');
  expect((await api<{ plans: Plan[] }>('/api/weekplan')).plans).toHaveLength(0);
  await page.getByTestId('toast-undo').last().click();
  await expect.poll(async () => (await api<{ posts: unknown[] }>('/api/calendar')).posts.length).toBe(0);
  await expect(page.getByTestId('pub-post')).toHaveCount(0); // the board follows the undo
});

test('a run that fails: the reason in plain words, Report this problem (read first), Put away', async () => {
  const id = 'f00dfeed0001';
  const dir = path.join(VHOME, 'projects', id, '01-broken');
  registerProject(dir, 'broken · 7 条切片');
  // what pilot.spawn records when `vstudio.project run` exits 5
  fs.writeFileSync(path.join(dir, 'desk-pilot.log'), JSON.stringify({ ok: false, error: 'plan-segments failed (exit 5): ffmpeg: moov atom not found', type: 'ProjectError' }) + '\n');
  fs.writeFileSync(path.join(dir, 'desk-pilot.json'), JSON.stringify({ pid: null, started: Date.now() / 1000, offset: 0, exit: 5, finished: Date.now() / 1000, provider: null }));
  setPlan(id, { id, intake: '000000000000', text: '', words: 'x', rule: null, platforms: ['xiaohongshu'], times: {}, start: null, today: null, inputs: 1, want: 7, state: 'making', created: Date.now() / 1000, projects: [{ dir, name: 'broken', recipe: 'longform-to-short' }], preview: null, scheduled: [], error: null });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  const card = page.getByTestId('weekplan');
  await expect(card).toHaveAttribute('data-state', 'failed', { timeout: 30000 }); // shown on the board too
  await expect(page.getByTestId('weekplan-reason')).not.toBeEmpty();
  await shot('publish-failed');
  await page.getByTestId('weekplan-report').click();
  const sheet = page.getByTestId('report-sheet');
  await expect(sheet).toBeVisible();
  await expect(page.getByTestId('report-text')).toContainText('Problem: job · media');
  await expect(page.getByTestId('report-text')).toContainText('Electron');
  await expect(page.getByTestId('report-text')).not.toContainText(os.homedir());
  await expect(page.getByTestId('report-open')).toBeDisabled(); // read it first
  await shot('report');
  await page.getByTestId('report-read').check();
  await page.getByTestId('report-open').click();
  const u = new URL((await opened()).at(-1)!);
  expect(u.pathname).toBe('/zyziyun/reelfold/issues/new');
  expect(u.searchParams.get('template')).toBe('bug_report.yml');
  expect(u.searchParams.get('logs')).toContain('Problem: job · media');
  expect(u.toString()).not.toContain(encodeURIComponent(os.homedir()));
  await page.getByTestId('weekplan-dismiss').click();
  await expect(card).toHaveCount(0);
  expect((await api<Plan>(`/api/weekplan/${id}`)).state).toBe('dismissed');
});

test('a renderer error -> the problem bar -> Report this problem (redacted)', async () => {
  await page.evaluate((home) => setTimeout(() => {
    throw new Error(`boom while reading ${home}/Desktop/secret-client/wedding.mp4`);
  }), os.homedir());
  const bar = page.getByTestId('problem-bar');
  await expect(bar).toBeVisible({ timeout: 10000 });
  await expect(bar).toHaveAttribute('data-kind', 'renderer');
  await shot('problem-bar');
  await page.getByTestId('problem-report').click();
  await expect(page.getByTestId('report-text')).toContainText('Problem: renderer');
  await expect(page.getByTestId('report-text')).not.toContainText('secret-client');
  await expect(page.getByTestId('report-text')).not.toContainText('wedding');
  await expect(page.getByTestId('report-text')).toContainText('<path>.mp4');
  await page.keyboard.press('Escape');
  await expect(bar).toBeVisible();
  await page.getByTestId('problem-dismiss').click();
  await expect(bar).toHaveCount(0);
});
