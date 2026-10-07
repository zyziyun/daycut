/* global location, document, window */
// The 8 states of the chat-first editor (ux/chat-edit/C) from the real build, window hidden (never shown), desk
// implementation (mock engine: no model, no network). Usage:
//   node scripts/chatShots.mjs --data /tmp/cedemo --out <dir> [--lang en|zh-CN] [--only 01-empty,02-changes]
// --data: a folder holding a (cloned) fuye demo project; nothing outside the temp profile is written.
import { _electron as electron } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const data = path.resolve(arg('data', '/tmp/cedemo'));
const out = path.resolve(arg('out', '/tmp/ce-shots'));
const lang = arg('lang', 'en');
const only = (arg('only', '') || '').split(',').filter(Boolean);
const zh = lang === 'zh-CN';
fs.mkdirSync(out, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ce-shots-'));
const profile = path.join(tmp, 'profile');
fs.mkdirSync(profile, { recursive: true });
fs.writeFileSync(path.join(profile, 'settings.json'), JSON.stringify({ lang, theme: 'studio-dark', accent: 'teal', accounts: {}, firstRunDone: true, cleanupMigrated: true }));

const app = await electron.launch({
  args: [path.resolve(import.meta.dirname, '..')],
  env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_EXPORT_STEP: '2.5', DESK_USER_DATA: profile, VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: data, DESK_HIDE_WINDOW: '1', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
});
const page = await app.firstWindow();
await page.setViewportSize({ width: 1440, height: 900 });
await page.waitForURL(/^app:\/\/desk\//);
const goto = (h) => page.evaluate((x) => (location.hash = x), h);
await page.waitForSelector('[data-testid=engine-status]');

// the fuye project + clip A
const id = await page.evaluate(async () => {
  const info = await window.desk.engineInfo();
  for (let i = 0; i < 60; i++) {
    const h = await (await fetch(info.baseUrl + '/api/history', { headers: { Authorization: `Bearer ${info.token}` } })).json();
    const it = (h.items ?? []).find((x) => /fuye/.test(x.name ?? x.dir ?? ''));
    if (it) return it.id;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return null;
});
if (!id) throw new Error('no fuye project under --data');
const clip = 'A_换圈子';
const editor = `#/p/${id}/clip/${encodeURIComponent(clip)}`;

const resetClip = () => {
  // a fresh conversation + edit doc for each state (the desk keeps them in the temp profile)
  for (const f of walk(profile)) if (/[/\\]outputs[/\\][0-9a-f]{16}\.json$/.test(f)) fs.rmSync(f);
};
function* walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) yield* walk(p);
    else yield p;
  }
}
const open = async () => {
  resetClip();
  await goto('#/');
  await goto(editor);
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await page.waitForSelector('[data-testid=chat-panel]', { timeout: 60000 });
  await page.waitForFunction(() => ((document.querySelector('[data-testid=player-video]')?.readyState ?? 0) >= 2), null, { timeout: 30000 });
};
const say = async (s) => {
  await page.fill('[data-testid=chat-input]', s);
  await page.press('[data-testid=chat-input]', 'Enter');
};
const seek = (t) => page.evaluate((x) => { const v = document.querySelector('[data-testid=player-video]'); if (v) v.currentTime = x; }, t);
/** drag across the words lane from a to b seconds (a selection = context for the chat) */
const select = async (a, b) => {
  const lane = await page.locator('[data-testid=tl-words]').boundingBox();
  const D = await page.evaluate(() => document.querySelector('[data-testid=player-video]')?.duration || 83);
  const x = (t) => lane.x + (t / D) * lane.width;
  await page.mouse.move(x(a), lane.y + lane.height / 2);
  await page.mouse.down();
  await page.mouse.move(x(b), lane.y + lane.height / 2, { steps: 10 });
  await page.mouse.up();
  await page.waitForSelector('[data-testid=ctx-sel]');
};
const shot = async (name, fn) => {
  if (only.length && !only.includes(name)) return;
  try {
    await open();
    await fn();
    await page.waitForTimeout(900);
    await page.screenshot({ path: path.join(out, `${name}.png`) });
    console.log('shot', name);
  } catch (e) {
    console.log('FAILED', name, e.message.split('\n')[0]);
    await page.screenshot({ path: path.join(out, `${name}.FAILED.png`) }).catch(() => undefined);
  }
};
const speedThenTighter = async () => {
  await say(zh ? '加速一点，1.1倍速' : 'Speed it up a little, 1.1x');
  await page.waitForSelector('[data-testid=change-apply]', { timeout: 30000 });
  await page.click('[data-testid=change-apply]');
  await page.waitForSelector('[data-testid=applied-line]', { timeout: 30000 });
  await say(zh ? '把「思路」弹出来，加进度条，结尾淡出' : 'Pop “思路” when she says it, add a progress bar, and fade out at the end');
  await page.waitForSelector('[data-testid=change-card]', { timeout: 30000 });
};

await shot('01-empty', async () => {
  await seek(12);
  await page.waitForSelector('[data-testid=chat-empty]');
});
await shot('02-changes', async () => {
  await speedThenTighter();
  await seek(31.2);
});
await shot('03-effect', async () => {
  await speedThenTighter();
  const rows = page.locator('[data-testid=change-row]');
  const n = await rows.count();
  for (let i = 0; i < n; i++) {
    if (/思路/.test(await rows.nth(i).innerText())) {
      await rows.nth(i).locator('[data-testid=change-adjust]').click();
      break;
    }
  }
  await page.waitForSelector('[data-testid=card-effect]');
  await seek(31.4);
});
await shot('04-captions', async () => {
  await seek(12);
  await select(12, 24);
  await page.fill('[data-testid=chat-input]', zh ? '/字幕' : '/captions');
  await page.press('[data-testid=chat-input]', 'Enter');
  await page.waitForSelector('[data-testid=card-captions]', { timeout: 30000 });
});
await shot('05-trim', async () => {
  await page.fill('[data-testid=chat-input]', zh ? '/裁剪' : '/trim');
  await page.press('[data-testid=chat-input]', 'Enter');
  await page.waitForSelector('[data-testid=card-trim]', { timeout: 30000 });
  await seek(0.8);
});
await shot('06-export', async () => {
  await speedThenTighter();
  await page.click('[data-testid=change-apply]');
  await page.waitForSelector('[data-testid=applied-line] >> nth=1', { timeout: 30000 });
  await page.click('[data-testid=editor-export]');
  await page.waitForSelector('[data-testid=card-export]', { timeout: 30000 });
  await page.click('[data-testid=pf-douyin]');
  await page.click('[data-testid=pf-wechat-channels]');
  await page.click('[data-testid=export-go]');
  await page.waitForSelector('[data-testid=export-row][data-done="1"]', { timeout: 60000 });
  await seek(31.2);
});
await shot('07-selection', async () => {
  await say(zh ? '1.1倍速' : '1.1x speed');
  await page.waitForSelector('[data-testid=change-apply]', { timeout: 30000 });
  await page.click('[data-testid=change-apply]');
  await page.waitForSelector('[data-testid=applied-line]');
  await select(12, 18);
  await page.focus('[data-testid=chat-input]');
  await page.keyboard.type('/');
  await page.waitForSelector('[data-testid=slash-menu]');
});
await shot('08-offline', async () => {
  await say(zh ? '让节奏更有呼吸感' : 'Give it more breathing room');
  await page.waitForSelector('[data-testid=card-offline]', { timeout: 30000 });
  await seek(31.2);
});
await app.close();
