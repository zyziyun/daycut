// Click-everything smoke (qa/BUGS.md): visit every screen and click every safe control on it, one at a time, then
// fail on console errors, uncaught page errors / rejections and IPC validation errors in the main process. Catches
// the "small bugs in real use" class (a scrub bar that throws, a menu that closes on open, an IPC payload the schema
// refuses, a raw key on screen) before a person does.
//
// Window hidden, mock engine (the test harness's fake; never reachable in the product), isolated profile, OS side
// effects stubbed (file dialogs, Finder, the default browser, notifications). Controls that change the world
// (delete, publish, render, export, sign in, apply…) are skipped by label; everything else is clicked, then Escape.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-smoke-'));
const watch = path.join(tmp, 'demos');
const work = path.join(watch, 'talk');
let app: ElectronApplication;
let page: Page;
const problems: string[] = [];
let where = 'start';

/** Labels / test ids of controls that would publish, delete, spend, render, sign in or leave the app. */
const UNSAFE =
  /delete|remove|trash|publish|post now|send|sign ?(in|out)|log ?(in|out)|connect|reset|uninstall|forget|discard|render|export|regenerate|approve|confirm|accept|download|quit|rebuild|fill|re-?run|retry|archive|clear|hide|apply|generate|record|pilot|stop|restart|make a plan|plan it|schedule|calendar|tidy|package|deliver|import|choose|browse|add (files|a folder|account)|删除|移除|发布|发送|登录|退出|重置|清空|下载|导出|渲染|重新|开始|确认|应用|生成|排期|打包|交付|导入/i;
const CONTROLS = 'button, [role=button], [role=tab], [role=menuitem], [role=switch], [role=checkbox], [role=radio], a[href^="#"], summary, select';
// console noise that is not a bug of the app (media the mock engine does not have, Chromium autoplay notes)
const BENIGN = /Failed to load resource: the server responded with a status of 404|net::ERR_ABORTED|play\(\) request was interrupted|The play\(\) request|Autofocus processing was blocked/;

function ffmpeg(args: string[]) {
  execFileSync('ffmpeg', ['-v', 'error', '-y', ...args]);
}

function fixture() {
  fs.mkdirSync(path.join(work, 'final'), { recursive: true });
  const lavfi = (d: number) => ['-f', 'lavfi', '-i', `testsrc2=size=240x320:rate=30:duration=${d}`, '-f', 'lavfi', '-i', `sine=frequency=330:duration=${d}`, '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'];
  const clips = ['A_opening', 'B_middle'];
  for (const c of clips) {
    ffmpeg([...lavfi(6), path.join(work, 'final', `${c}.mp4`)]);
    ffmpeg(['-i', path.join(work, 'final', `${c}.mp4`), '-ss', '1', '-frames:v', '1', path.join(work, 'final', `${c}_cover.jpg`)]);
  }
  const words = ['so', 'today', 'um', 'we', 'cut', 'this', 'talk', 'into', 'clips'].map((w, i) => ({ word: w, start: 0.3 + i * 0.5, end: 0.7 + i * 0.5 }));
  fs.writeFileSync(path.join(work, 'final', 'A_opening.mp4.asr.json'), JSON.stringify({ segments: [{ start: 0.3, end: 4.7, words }] }));
  fs.writeFileSync(path.join(work, 'final', 'post.md'), clips.map((c) => `## ${c}.mp4  ·  封面 ${c}_cover.jpg\n\n${c} title\n\nBody.\n\n#tag\n`).join('\n'));
  fs.writeFileSync(
    path.join(work, 'PICKS.md'),
    '# PICKS\n\n| # | Source span | Len | Title | Why | Opening line |\n|---|---|---|---|---|---|\n| A opening | 0:00 – 0:06 | 0:06 | Opening | x | y |\n| B middle | 0:06 – 0:12 | 0:06 | Middle | x | y |\n\n## Edits inside the spans (creator should confirm)\n- **A** drops 「um」 before we cut.\n',
  );
}

test.describe.configure({ mode: 'serial' });
test.setTimeout(240_000);

test.beforeAll(async () => {
  fixture();
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', DESK_CREATE: '1', DESK_DISABLE_UPDATES: '1', VITE_DEV_SERVER_URL: '' },
  });
  // nothing may reach the desktop: dialogs, Finder, the default browser, notifications
  await app.evaluate(({ dialog, shell, Notification }) => {
    dialog.showOpenDialog = (async () => ({ canceled: true, filePaths: [] })) as typeof dialog.showOpenDialog;
    dialog.showSaveDialog = (async () => ({ canceled: true, filePath: '' })) as typeof dialog.showSaveDialog;
    dialog.showMessageBox = (async () => ({ response: 0, checkboxChecked: false })) as typeof dialog.showMessageBox;
    shell.openExternal = async () => undefined;
    shell.openPath = async () => '';
    shell.showItemInFolder = () => undefined;
    Notification.prototype.show = () => undefined;
  });
  const mainOut = (d: Buffer) => {
    for (const l of d.toString().split('\n')) if (/IpcValidationError|invalid \S+ payload|Error occurred in handler/.test(l)) problems.push(`[main @ ${where}] ${l.trim().slice(0, 300)}`);
  };
  app.process().stdout?.on('data', mainOut);
  app.process().stderr?.on('data', mainOut);
  page = await app.firstWindow();
  page.on('console', (m) => {
    if (m.type() === 'error' && !BENIGN.test(m.text())) problems.push(`[console @ ${where}] ${m.text().slice(0, 300)}`);
  });
  page.on('pageerror', (e) => problems.push(`[pageerror @ ${where}] ${e.message.slice(0, 300)}`));
  // an engine call the UI makes that the engine refuses (4xx / 5xx) is a dead control or a dead link
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/') && r.status() >= 400 && !/\/(strip|thumb|frame|media)\b/.test(u.pathname)) problems.push(`[http ${r.status()} @ ${where}] ${r.request().method()} ${u.pathname}`);
  });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => sessionStorage.setItem('v4.pview', 'grid')); // All projects as the grid (the control room: autopilot.spec)
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.getByTestId('engine-status')).toHaveAttribute('data-mode', 'mock', { timeout: 30000 });
});

test.afterAll(async () => {
  await closeApp(app);
});

async function ids(): Promise<{ batch: string; work: string }> {
  return page.evaluate(async () => {
    const info = await window.desk.engineInfo();
    const h = await (await fetch(info.baseUrl + '/api/history', { headers: { Authorization: `Bearer ${info.token}` } })).json();
    const items = h.items as { id: string; name: string; kind: string }[];
    return { batch: items.find((i) => i.name === 'demo-course')?.id ?? '', work: items.find((i) => i.kind === 'work')?.id ?? '' };
  });
}

type Ctl = { key: string; label: string };

async function visible(): Promise<Ctl[]> {
  return page.$$eval(CONTROLS, (els) =>
    els
      .filter((e) => {
        const r = e.getBoundingClientRect();
        const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && !e.closest('[aria-hidden=true]') && !(e as HTMLButtonElement).disabled;
      })
      .map((e) => {
        const label = (e.getAttribute('aria-label') || e.getAttribute('title') || (e as HTMLElement).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60);
        return { key: `${e.getAttribute('data-testid') ?? ''}|${label}|${e.getAttribute('href') ?? ''}`, label };
      }),
  );
}

async function go(route: string) {
  await page.evaluate((r) => {
    location.hash = r;
  }, route);
  await page.waitForTimeout(500);
}

/** Click every safe control of a route once (fresh page state each time), then Escape. */
async function clickEverything(route: string, max = 60) {
  where = route;
  await go(route);
  await page.waitForTimeout(600);
  const all = await visible();
  const seen = new Set<string>();
  let clicked = 0;
  for (const c of all.slice(0, max)) {
    if (seen.has(c.key) || UNSAFE.test(c.key)) continue;
    seen.add(c.key);
    await go(route);
    const now = await visible();
    const i = now.findIndex((x) => x.key === c.key);
    if (i < 0) continue;
    where = `${route} → ${c.label || c.key}`;
    const loc = page.locator(CONTROLS).filter({ visible: true });
    await loc
      .nth(i)
      .click({ timeout: 2000 })
      .then(() => clicked++)
      .catch(() => undefined); // covered / moved: not what this test is about
    await page.waitForTimeout(250);
    await page.keyboard.press('Escape').catch(() => undefined);
  }
  where = route;
  return clicked;
}

/** Right-click every card the route shows (context menus open and stay open). */
async function rightClickCards(route: string, sel: string) {
  where = `${route} (right-click)`;
  await go(route);
  const n = Math.min(await page.locator(sel).count(), 3);
  for (let i = 0; i < n; i++) {
    await page.locator(sel).nth(i).click({ button: 'right' });
    await page.waitForTimeout(250);
    await expect(page.locator('.ctx').first(), `a context menu on ${sel} #${i}`).toBeVisible();
    await page.keyboard.press('Escape');
  }
}

function expectClean(screen: string) {
  const mine = problems.splice(0);
  expect(mine, `console / page / IPC errors on ${screen}`).toEqual([]);
}

test('Home, Inbox, All projects', async () => {
  for (const r of ['#/', '#/inbox', '#/projects']) expect(await clickEverything(r)).toBeGreaterThan(3);
  await rightClickCards('#/projects', '[data-testid=project-card]');
  expectClean('Home / Inbox / All projects');
});

test('project pages (batch + work) and their tabs', async () => {
  const { batch, work: w } = await ids();
  expect(batch).toBeTruthy();
  expect(w).toBeTruthy();
  for (const id of [batch, w]) for (const tab of ['', '/history', '/files']) await clickEverything(`#/p/${id}${tab}`, 30);
  await clickEverything(`#/p/${batch}/review`, 30);
  await clickEverything(`#/p/${w}/review`, 30); // a work has no Review tab: the link falls back to the clips
  await rightClickCards(`#/p/${w}`, '[data-testid=clip-card]');
  expectClean('project pages');
});

test('clip editor: transcript, timeline, chat', async () => {
  const { work: w } = await ids();
  const route = `#/p/${w}/clip/A_opening`;
  await go(route);
  await expect(page.getByTestId('player-play')).toBeVisible({ timeout: 20000 });
  await clickEverything(route, 80);
  // the scrub bar and the timeline take a click anywhere
  where = `${route} scrub`;
  for (const sel of ['[data-testid=scrub]', '[data-testid=tl-ruler]']) {
    const b = page.locator(sel).first();
    if (await b.isVisible().catch(() => false)) {
      const box = (await b.boundingBox())!;
      await page.mouse.click(box.x + box.width * 0.6, box.y + box.height / 2);
    }
  }
  // BB-12: Export opens its card even when the AI column is folded (a window under 1280 px folds it by itself)
  await page.setViewportSize({ width: 1200, height: 800 });
  await go(route);
  await expect(page.getByTestId('player-play')).toBeVisible({ timeout: 20000 });
  await page.getByTestId('editor-export').click();
  await expect(page.getByTestId('export-go')).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  expectClean('clip editor');
});

test('Publish: week, month, data, accounts', async () => {
  for (const r of ['#/publish', '#/publish/accounts', '#/metrics']) await clickEverything(r, 50);
  expectClean('Publish');
});

test('Settings: every section', async () => {
  for (const s of ['general', 'ai', 'video', 'accounts', 'advanced']) await clickEverything(`#/settings/${s}`, 50);
  expectClean('Settings');
});

test('Create', async () => {
  await clickEverything('#/create', 40);
  expectClean('Create');
});

test('the same screens at 1280 in French and light theme render without errors', async () => {
  await page.evaluate(() => window.desk.setSettings({ lang: 'fr', theme: 'notebook-light' }));
  await page.reload();
  await page.setViewportSize({ width: 1280, height: 800 });
  for (const r of ['#/', '#/inbox', '#/projects', '#/publish', '#/settings/general', '#/create']) {
    where = `fr ${r}`;
    await go(r);
    await page.waitForTimeout(400);
    // no raw i18n key (a.b.c) as visible text
    const raw = await page.evaluate(() => [...document.querySelectorAll('main *')].filter((e) => !e.children.length && /^[a-z][a-zA-Z0-9]+(\.[a-zA-Z0-9:-]+){1,4}$/.test((e as HTMLElement).innerText?.trim() ?? '')).map((e) => (e as HTMLElement).innerText.trim()));
    expect(raw, `raw i18n keys on ${r}`).toEqual([]);
  }
  expectClean('fr / light');
});
