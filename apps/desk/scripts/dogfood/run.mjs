/* global window, document, location -- page functions run in the app over CDP */
// "First 10 minutes" dogfood, automated: a packaged Reelfold on a FRESH profile (temp HOME / userData / VSTUDIO_HOME,
// no Claude Code / Codex on PATH, no API keys, a mock keychain so nothing touches the real one), driven over CDP like a
// person would: wizard -> continue without AI -> Home -> Try with a sample -> plan -> Start -> review in the Inbox ->
// approve -> the files per platform -> the Publish page. Every step is timed and screenshotted.
//   node scripts/dogfood/run.mjs [--app <path to the Reelfold binary>] [--out <dir>] [--port 47392]
// Writes <out>/timings.json and <out>/NN-*.png; prints a table. Real engine, real ASR, real render: expect minutes.
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const APP = arg('app', path.join(ROOT, 'dist', 'mac-arm64', 'Reelfold.app', 'Contents', 'MacOS', 'Reelfold'));
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-dogfood-'));
const OUT = arg('out', path.join(work, 'shots'));
const PORT = Number(arg('port', '47392'));
fs.mkdirSync(OUT, { recursive: true });
for (const d of ['home', 'ud']) fs.mkdirSync(path.join(work, d), { recursive: true });

const t0 = Date.now();
const steps = [];
let last = t0;
let n = 0;
const sec = (ms) => Math.round(ms / 100) / 10;
function mark(name, kind, extra = {}) {
  const now = Date.now();
  steps.push({ name, kind, at: sec(now - t0), took: sec(now - last), ...extra });
  console.log(`${String(sec(now - t0)).padStart(7)} s  +${String(sec(now - last)).padStart(6)} s  ${kind.padEnd(6)} ${name}`);
  last = now;
}

const env = {
  HOME: path.join(work, 'home'),
  USER: process.env.USER ?? 'me',
  LOGNAME: process.env.USER ?? 'me',
  TMPDIR: os.tmpdir() + path.sep,
  LANG: 'en_US.UTF-8',
  PATH: '/usr/bin:/bin:/usr/sbin:/sbin', // no claude / codex / brew: a new Mac
  VSTUDIO_HOME: path.join(work, 'home', '.config', 'vstudio'),
  DESK_USER_DATA: path.join(work, 'ud'),
  DESK_DISABLE_UPDATES: '1',
};
const proc = spawn(APP, ['--use-mock-keychain', `--remote-debugging-port=${PORT}`], { env, stdio: 'ignore' });
let browser;
for (let i = 0; i < 120 && !browser; i++) {
  try {
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`, { timeout: 2000 });
  } catch {
    await new Promise((r) => setTimeout(r, 250));
  }
}
if (!browser) throw new Error('no CDP endpoint (port taken?)');
let page;
for (let i = 0; i < 200 && !page; i++) {
  page = browser.contexts().flatMap((c) => c.pages()).find((p) => p.url().startsWith('app://desk/'));
  if (!page) await new Promise((r) => setTimeout(r, 100));
}
const shot = (name) => page.screenshot({ path: path.join(OUT, `${String(++n).padStart(2, '0')}-${name}.png`) });
const id = (x) => page.getByTestId(x);
const api = (p) =>
  page.evaluate(async (u) => {
    const i = await window.desk.engineInfo();
    return (await fetch(i.baseUrl + u, { headers: { Authorization: `Bearer ${i.token}` } })).json();
  }, p);

try {
  await id('first-run').waitFor({ timeout: 60000 });
  mark('app open, wizard shown', 'wait');
  await shot('welcome');
  await id('fr-next').click();
  await id('fr-ai').waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid=fr-sub-state]')].every((e) => !/checking|unknown/.test(e.dataset.state ?? '')), null, { timeout: 30000 });
  await shot('ai');
  mark('welcome -> AI (status checked)', 'active');
  await id('fr-next').click(); // "Continue without AI"
  await shot('platforms');
  await id('fr-next').click(); // finish
  await id('home').waitFor();
  await shot('home');
  mark('AI (no AI) -> platforms -> Home', 'active');
  const dl = await page.evaluate(() => window.desk.assets.status());
  await id('home-sample').click();
  mark('Try with a sample clicked', 'active', { downloadsDone: dl.groups.filter((g) => g.required).every((g) => g.installed) });
  await shot('sample-clicked');
  await page.waitForFunction(() => window.desk.assets.status().then((s) => s.groups.filter((g) => g.required).every((g) => g.installed)), null, { timeout: 900000, polling: 1000 });
  mark('required downloads done (background)', 'wait');
  await id('plan-start').waitFor({ timeout: 900000 });
  await shot('plan');
  mark('plan ready', 'wait', { summary: await id('plan-summary').textContent() });
  await id('plan-start').click();
  await id('project').waitFor({ timeout: 60000 });
  await shot('project-running');
  mark('Start -> project page', 'active');
  // the run: until the clip has its files and the review-before-publish item is in the Inbox
  const projId = (await page.evaluate(() => location.hash)).split('/')[2];
  let clipAt = null;
  for (let i = 0; i < 1800; i++) {
    const c = await api(`/api/outputs/${projId}`).catch(() => null);
    const files = c?.clips?.[0]?.files ?? [];
    if (files.length && !clipAt) {
      clipAt = Date.now();
      await page.reload();
      await id('project').waitFor();
      await shot('clip-ready');
      mark('first clip ready to watch', 'wait', { files: files.map((f) => f.platform) });
    }
    const ib = await api('/api/inbox').catch(() => null);
    if (clipAt && ib?.items?.some((x) => x.kind === 'publish')) break;
    if (i % 30 === 0 && !clipAt) await shot(`running-${i / 30}`);
    await new Promise((r) => setTimeout(r, 1000));
  }
  await id('nav-inbox').click();
  await id('inbox-preview').waitFor();
  await shot('inbox-review');
  mark('Inbox: review before publishing', 'active');
  await page.getByRole('button', { name: /continue/i }).click();
  for (let i = 0; i < 600; i++) {
    const h = await api('/api/history');
    const it = h.items.find((x) => x.id === projId);
    if (it?.live?.state === 'done' || (it?.status === 'done' && it?.live?.state !== 'running' && it?.live?.state !== 'waiting')) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  mark('approved -> project done', 'wait');
  await page.evaluate((p) => (location.hash = `#/p/${p}`), projId);
  await id('project').waitFor();
  await shot('project-done');
  const clips = await api(`/api/outputs/${projId}`);
  const files = clips.clips.flatMap((c) => c.files.map((f) => ({ platform: f.platform, w: f.w, h: f.h, duration: f.duration, path: f.path })));
  mark('export files listed', 'active', { files });
  await id('nav-publish').click();
  await page.waitForTimeout(1500);
  await shot('publish');
  mark('Publish page (accounts: sign-in is hers)', 'active');
} catch (e) {
  mark(`FAILED: ${e.message.split('\n')[0]}`, 'error');
  await shot('failed').catch(() => undefined);
} finally {
  const total = sec(Date.now() - t0);
  const active = sec(steps.filter((s) => s.kind === 'active').reduce((a, s) => a + s.took * 1000, 0));
  const doc = { app: APP, profile: work, total, active, waiting: sec(total * 1000 - active * 1000), steps, load: os.loadavg() };
  fs.writeFileSync(path.join(OUT, 'timings.json'), JSON.stringify(doc, null, 1));
  console.log(`total ${total} s · active ${active} s · load ${os.loadavg().map((x) => x.toFixed(0)).join('/')} · ${OUT}`);
  await browser.close().catch(() => undefined);
  proc.kill('SIGTERM');
}
