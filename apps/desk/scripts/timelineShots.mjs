/* global location, document, window */
// The clip editor's player scrubber + timeline (ux/chat-edit/C/build/timeline) from the real build, window hidden,
// mock engine. A CUDA explainer clip (9:16, no transcript yet) and a fuye clip (3:4, with words), dark + light.
//   node scripts/timelineShots.mjs --data /tmp/tldemo --out <dir> [--lang zh-CN|en] [--only cuda-dark,...]
// --data: a folder holding (cloned) 06-cuda-explainer and fuye demo folders; nothing outside the temp profile is
// written except the thumbnail / peak caches in the temp profile.
import { _electron as electron } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const data = path.resolve(arg('data', '/tmp/tldemo'));
const out = path.resolve(arg('out', '/tmp/tl-shots'));
const lang = arg('lang', 'zh-CN');
const only = (arg('only', '') || '').split(',').filter(Boolean);
fs.mkdirSync(out, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tl-shots-'));
const profile = path.join(tmp, 'profile');
fs.mkdirSync(profile, { recursive: true });
const settings = (theme) => fs.writeFileSync(path.join(profile, 'settings.json'), JSON.stringify({ lang, theme, accent: 'teal', accounts: {}, firstRunDone: true, cleanupMigrated: true }));
settings('studio-dark');

const app = await electron.launch({
  args: [path.resolve(import.meta.dirname, '..')],
  env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_ASR_STEP: '1', DESK_USER_DATA: profile, VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: data, DESK_HIDE_WINDOW: '1', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
});
const page = await app.firstWindow();
await page.setViewportSize({ width: 1440, height: 900 });
await page.waitForURL(/^app:\/\/desk\//);
await page.waitForSelector('[data-testid=engine-status]');

const find = (re) =>
  page.evaluate(async (src) => {
    const info = await window.desk.engineInfo();
    const H = { headers: { Authorization: `Bearer ${info.token}` } };
    for (let i = 0; i < 60; i++) {
      const h = await (await fetch(info.baseUrl + '/api/history', H)).json();
      const it = (h.items ?? []).find((x) => new RegExp(src).test(x.name ?? x.dir ?? ''));
      if (it) {
        const cl = await (await fetch(`${info.baseUrl}/api/outputs/${it.id}`, H)).json();
        return { id: it.id, clips: (cl.clips ?? []).map((c) => c.id) };
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    return null;
  }, re.source);

const cuda = await find(/cuda/);
const fuye = await find(/fuye/);
if (!cuda || !fuye) throw new Error('need 06-cuda-explainer and fuye under --data');
console.log('cuda clips', cuda.clips.join(', '), '· fuye clips', fuye.clips.slice(0, 4).join(', '));
const long = await find(/longtalk/).catch(() => null);
const cudaClip = cuda.clips.find((c) => /douyin/.test(c)) ?? cuda.clips[0];
const fuyeClip = fuye.clips.find((c) => /换圈子/.test(c)) ?? fuye.clips[0];

const open = async (it, clip, theme) => {
  await page.evaluate(async (th) => {
    sessionStorage.removeItem('v4.tlzoom2');
    await window.desk.setSettings({ theme: th });
  }, theme);
  await page.evaluate((h) => (location.hash = h), `#/p/${it.id}/clip/${encodeURIComponent(clip)}`);
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await page.waitForSelector('[data-testid=chat-panel]', { timeout: 60000 });
  await page.waitForFunction(() => (document.querySelector('[data-testid=player-video]')?.readyState ?? 0) >= 2, null, { timeout: 30000 });
  await page.waitForSelector('[data-testid=tl-film][data-ready="1"]', { timeout: Number(process.env.TL_WAIT || 120000) }).catch(() => console.log('  (filmstrip not ready)'));
};
const seek = async (t) => {
  await page.evaluate((x) => { const v = document.querySelector('[data-testid=player-video]'); if (v) v.currentTime = x; }, t);
  await page.waitForTimeout(400);
  if (process.env.TL_DEBUG) console.log('  seek', t, await page.evaluate(() => [document.querySelector('[data-testid=player-video]').currentTime, document.querySelector('[data-testid=timecode]').textContent, [...document.querySelectorAll('[data-testid=tl-film] > i')].slice(0, 2).map((e) => e.style.backgroundImage.slice(0, 60))]));
};
const shot = async (name, fn) => {
  if (only.length && !only.includes(name)) return;
  try {
    await fn();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(out, `${name}.png`) });
    console.log('shot', name);
  } catch (e) {
    console.log('FAILED', name, e.message.split('\n')[0]);
    await page.screenshot({ path: path.join(out, `${name}.FAILED.png`) }).catch(() => undefined);
  }
};
const hoverScrub = async (f) => {
  const b = await page.locator('[data-testid=scrub]').boundingBox();
  await page.mouse.move(b.x + b.width * f, b.y + b.height / 2);
};

const say = async (txt) => {
  await page.fill('[data-testid=chat-input]', txt);
  await page.press('[data-testid=chat-input]', 'Enter');
};

for (const theme of ['studio-dark', 'notebook-light']) {
  const tn = theme === 'studio-dark' ? 'dark' : 'light';
  await shot(`cuda-${tn}`, async () => {
    await open(cuda, cudaClip, theme);
    await seek(23.4);
    await hoverScrub(0.62);
  });
  await shot(`cuda-${tn}-transcribed`, async () => {
    await open(cuda, cudaClip, theme);
    const b = page.getByTestId('tl-transcribe');
    if (await b.count()) {
      await b.click();
      await page.waitForSelector('[data-testid=tl-words] .w', { timeout: 120000 });
    }
    await seek(41);
  });
  await shot(`fuye-${tn}`, async () => {
    await open(fuye, fuyeClip, theme);
    await seek(31.2);
    await hoverScrub(0.3);
  });
  await shot(`fuye-${tn}-effects`, async () => {
    await open(fuye, fuyeClip, theme);
    await say('把「思路」弹出来');
    await page.waitForSelector('[data-testid=change-apply]', { timeout: 30000 });
    await page.click('[data-testid=change-apply]');
    await page.waitForSelector('[data-testid=applied-line]', { timeout: 30000 });
    await say('加进度条，结尾淡出');
    await page.waitForSelector('[data-testid=change-card]', { timeout: 30000 });
    await seek(31.4);
  });
  if (long) {
    await shot(`long-${tn}`, async () => {
      const t0 = Date.now();
      await open(long, long.clips[0], theme);
      console.log('  long strip ready in', Date.now() - t0, 'ms');
      await seek(371);
    });
    await shot(`long-${tn}-zoomed`, async () => {
      await open(long, long.clips[0], theme);
      await seek(371);
      for (let i = 0; i < 6; i++) await page.click('[data-testid=tl-zoom-in]');
      const n = await page.evaluate(() => [document.querySelectorAll('[data-testid=tl-film] > i').length, document.querySelectorAll('[data-testid=tl-words] .w').length]);
      console.log('  zoomed DOM: tiles', n[0], 'words', n[1]);
    });
  }
  await shot(`fuye-${tn}-zoomed`, async () => {
    await open(fuye, fuyeClip, theme);
    await seek(14);
    await page.click('[data-testid=tl-zoom-in]');
    await page.click('[data-testid=tl-zoom-in]');
    const wl = await page.locator('[data-testid=tl-words]').boundingBox();
    const vb = await page.locator('[data-testid=tl-view]').boundingBox();
    const lane = { x: vb.x, y: wl.y, height: wl.height };
    await page.mouse.move(lane.x + 200, lane.y + lane.height / 2);
    await page.mouse.down();
    await page.mouse.move(lane.x + 420, lane.y + lane.height / 2, { steps: 8 });
    await page.mouse.up();
    await page.mouse.move(lane.x + 600, lane.y - 160);
    if (process.env.TL_DEBUG) console.log('  selection chip', await page.locator('[data-testid=ctx-sel]').count(), await page.locator('[data-testid=tl-selection]').count(), lane);
  });
}
await app.close();
