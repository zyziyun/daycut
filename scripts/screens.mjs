/* global location, document */
// Screenshots of every main screen with real data, window hidden (never shown): for design review against
// ux/mockups. Usage: node scripts/screens.mjs --data /tmp/vsdemo --out /tmp/shots [--lang en|zh-CN] [--mock]
//   --data   a folder of (cloned, read-only) demo projects to watch; nothing outside the temp profile is written
//   --only   comma list of shot names
import { _electron as electron } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const data = path.resolve(arg('data', '/tmp/vsdemo'));
const out = path.resolve(arg('out', '/tmp/vsdesk-shots'));
const lang = arg('lang', 'en');
const only = (arg('only', '') || '').split(',').filter(Boolean);
const mock = process.argv.includes('--mock');
fs.mkdirSync(out, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-shots-'));
fs.mkdirSync(path.join(tmp, 'profile'), { recursive: true });
fs.writeFileSync(path.join(tmp, 'profile', 'settings.json'), JSON.stringify({ lang, theme: arg('theme', 'studio-dark'), accent: arg('accent', 'teal'), accounts: {}, firstRunDone: true, cleanupMigrated: true, defaultPlatforms: ['xiaohongshu:vertical', 'douyin'] }));

const app = await electron.launch({
  args: [path.resolve(import.meta.dirname, '..')],
  env: {
    ...process.env,
    ...(mock ? { DESK_ENGINE_MOCK: '1' } : {}),
    DESK_USER_DATA: path.join(tmp, 'profile'),
    VSTUDIO_HOME: path.join(tmp, 'vhome'),
    DESK_HISTORY_WATCH: data,
    DESK_HIDE_WINDOW: '1',
    DESK_SKIP_FIRST_RUN: '1',
    VITE_DEV_SERVER_URL: '',
  },
});
const page = await app.firstWindow();
await page.setViewportSize({ width: 1440, height: 900 });
await page.waitForURL(/^app:\/\/desk\//);
const shot = async (name, fn) => {
  if (only.length && !only.includes(name)) return;
  try {
    await fn();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(out, `${name}.png`) });
    console.log('shot', name);
  } catch (e) {
    console.log('FAILED', name, e.message.split('\n')[0]);
  }
};
const goto = (h) => page.evaluate((x) => (location.hash = x), h);
await page.waitForSelector('[data-testid=engine-status]');
await page.waitForFunction(() => !/Starting|正在启动/.test(document.querySelector('[data-testid=engine-status]')?.textContent ?? ''), null, { timeout: 60000 });

const projects = async () => {
  await goto('#/projects');
  await page.waitForSelector('[data-testid=project-card]', { timeout: 60000 });
  return page.$$eval('[data-testid=project-card]', (els) => els.map((e) => ({ href: e.getAttribute('href'), text: e.textContent })));
};

await shot('01-home', async () => {
  await goto('#/');
  await page.waitForSelector('[data-testid=live-lane]', { timeout: 60000 });
});
const list = await projects();
const fuye = list.find((p) => /fuye|副业/.test(p.text ?? ''))?.href;
const rag = list.find((p) => /rag|RAG/.test(p.text ?? ''))?.href;
await shot('02-plan', async () => {
  const video = path.join(data, 'fuye', 'final', 'v2', 'A_换圈子.mp4');
  await page.evaluate(
    ([f, p]) => sessionStorage.setItem('v4.composer', JSON.stringify({ prompt: p, files: [f] })),
    [fs.existsSync(video) ? video : path.join(data, 'fuye', 'final', 'A_换圈子.mp4'), lang === 'en' ? 'Cut this into 3 Xiaohongshu clips, about a minute each' : '把这条剪成 3 条小红书切片，每条一分钟左右'],
  );
  await goto('#/projects');
  await goto('#/');
  await page.click('[data-testid=make-plan]');
  await page.waitForSelector('[data-testid=plan-facts]', { timeout: 240000 });
});
await shot('03-inbox', async () => {
  await page.evaluate(() => sessionStorage.removeItem('v4.composer'));
  await goto('#/inbox');
  await page.waitForSelector('[data-testid=inbox-item], [data-testid=empty]', { timeout: 30000 });
});
await shot('04-projects', async () => {
  await goto('#/projects');
  await page.waitForSelector('[data-testid=project-card]');
  await page.waitForTimeout(2500);
});
if (fuye) {
  await shot('05-fuye', async () => {
    await goto(fuye);
    await page.waitForSelector('[data-testid=clip-card]', { timeout: 30000 });
    await page.waitForTimeout(1500);
  });
  await shot('05b-player', async () => {
    await page.click('[data-testid=clip-card]');
    await page.waitForSelector('[data-testid=player-overlay]');
    await page.waitForTimeout(1500);
  });
  await shot('06-editor', async () => {
    await page.keyboard.press('Escape');
    const clip = await page.$eval('[data-testid=clip-card]', (e) => e.getAttribute('data-clip'));
    await goto(`${fuye}/clip/${encodeURIComponent(clip)}`);
    await page.waitForSelector('[data-testid=timeline]', { timeout: 30000 });
    await page.click('[data-testid=etab-effects]');
    await page.waitForTimeout(2000);
  });
}
if (rag) {
  await shot('07-rag', async () => {
    await goto(rag);
    await page.waitForSelector('[data-testid=clip-card]', { timeout: 30000 });
    await page.waitForTimeout(2000);
  });
  await shot('08-review', async () => {
    await goto(`${rag}/focus`);
    await page.waitForSelector('[data-testid=focus]');
    await page.waitForTimeout(3000);
  });
}
await shot('09-publish', async () => {
  await goto('#/publish');
  await page.waitForSelector('[data-testid=calendar]');
  await page.waitForTimeout(2500);
});
await shot('10-settings', async () => {
  await goto('#/settings');
  await page.waitForTimeout(1000);
});
await app.close();
fs.rmSync(tmp, { recursive: true, force: true });
