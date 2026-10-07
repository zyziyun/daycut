/* global location, window */
// The publish flow on a REAL project with the real engine, window hidden, temporary profile: 打包发布 (chosen
// clips x every platform) -> confirm the code -> calendar slots -> mark one item posted -> calendar. Screenshots +
// manifest summary to --out. No platform page is opened, nothing is posted.
//   node scripts/publishFlow.mjs --data /tmp/vs-pubtest/demos --project fuye --out <dir> [--clips A_换圈子,B_自媒体]
import { _electron as electron } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const data = path.resolve(arg('data', '/tmp/vs-pubtest/demos'));
const project = arg('project', 'fuye');
const out = path.resolve(arg('out', '/tmp/vsdesk-flow'));
const only = (arg('clips', '') || '').split(',').filter(Boolean);
fs.mkdirSync(out, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-flow-'));
fs.mkdirSync(path.join(tmp, 'profile'), { recursive: true });
fs.writeFileSync(path.join(tmp, 'profile', 'settings.json'), JSON.stringify({ lang: arg('lang', 'zh-CN'), theme: 'studio-dark', accounts: { douyin: ['main'] }, channels: { 'douyin/main': { name: '@测试抖音号', times: ['12:30'] } }, firstRunDone: true, cleanupMigrated: true }));
const log = [];
const note = (s) => (log.push(s), console.log(s));

const app = await electron.launch({
  args: [path.resolve(import.meta.dirname, '..')],
  env: { ...process.env, DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: data, DESK_HIDE_WINDOW: '1', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
});
const page = await app.firstWindow();
await page.setViewportSize({ width: 1440, height: 900 });
await page.waitForURL(/^app:\/\/desk\//);
const shot = (n) => page.screenshot({ path: path.join(out, `${n}.png`) });
const api = (pathname, body) =>
  page.evaluate(
    async ({ pathname, body }) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + pathname, { method: body === undefined ? 'GET' : 'POST', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
      return r.json();
    },
    { pathname, body },
  );
try {
  await page.getByTestId('home').waitFor({ timeout: 60000 });
  note(`engine: ${JSON.stringify(await page.evaluate(() => window.desk.engineInfo().then((i) => i.mode)))}`);
  await page.evaluate(() => (location.hash = '#/projects'));
  const card = page.locator('a[data-testid="project-card"]').filter({ hasText: project }).first();
  await card.waitFor({ timeout: 60000 });
  const item = (await card.getAttribute('href')).match(/#\/p\/([0-9a-f]{12})/)[1];
  note(`project ${project} = ${item}`);
  await page.evaluate((i) => (location.hash = `#/b/${i}/publish`), item);
  const pkg = page.getByTestId('pkg-card');
  await pkg.waitFor({ timeout: 60000 });
  await page.getByTestId('pkg-clip').first().waitFor({ timeout: 60000 });
  const clips = await page.getByTestId('pkg-clip').allTextContents();
  note(`clips offered: ${clips.join(' | ')}`);
  if (only.length) {
    for (const row of await page.getByTestId('pkg-clip').all()) {
      const txt = await row.textContent();
      const want = only.some((c) => txt.includes(c)) || (await row.evaluate(() => false));
      const box = row.locator('input');
      if ((await box.isChecked()) !== want) await box.click();
    }
  }
  for (const b of await pkg.getByTestId('pkg-platform').all()) if ((await b.getAttribute('aria-pressed')) !== 'true') await b.click();
  await shot('1-package-card');
  const t0 = Date.now();
  await page.getByTestId('pkg-go').click();
  await page.getByTestId('pub-review-list').waitFor({ timeout: 300000 });
  note(`packaged in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  const man = await api(`/api/batches/${item}/package`);
  fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(man, null, 1));
  note(`manifest: ${man.manifest.items.length} items, code ${man.manifest.confirmation_code}, verify ${man.verify.ok}, dir ${man.dir}`);
  for (const i of man.manifest.items) note(`  ${i.platform.padEnd(26)} ${i.job.padEnd(10)} ${i.date} ${i.time} ${Object.keys(i.files).join('+')} · ${(i.checks || []).map((c) => c.code + (c.n !== undefined ? ` ${c.n}/${c.max}` : c.want ? ` want ${c.want} got ${c.got}` : '')).join(', ')}`);
  await shot('2-packaged');
  await page.getByTestId('pub-review-list').click();
  await page.waitForTimeout(300);
  await shot('3-confirm-list');
  await page.getByTestId('pub-confirm-ok').click();
  await page.getByText(/已排进日历|on the calendar/).waitFor({ timeout: 60000 });
  note(`confirm: ${await page.getByText(/已排进日历|on the calendar/).first().textContent()}`);
  await page.locator('button.tab[data-adapter="douyin"]').click();
  const it = page.locator('[data-testid="pub-item"][data-platform^="douyin"]').first();
  await it.click();
  await page.waitForTimeout(500);
  await shot('4-douyin-item');
  await page.getByTestId('pub-mark-posted').click();
  await page.getByTestId('pub-posted-ok').click();
  await page.getByText(/日历也同步了|also on the calendar/).waitFor({ timeout: 30000 });
  note('mark posted: ok');
  const cal = await api('/api/calendar');
  const mine = cal.posts.filter((p) => p.item === item);
  note(`calendar: ${mine.length} posts for the project; posted: ${mine.filter((p) => p.state === 'posted').map((p) => `${p.platform}/${p.clip}`).join(', ')}`);
  await page.evaluate(() => (location.hash = '#/publish'));
  await page.getByTestId('calendar').waitFor();
  await page.waitForTimeout(800);
  await shot('5-calendar');
  // the fill is refused without a confirmed login: try it on 抖音 (todo adapter) and TikTok (no account) -> reasons
  const fillTodo = await page.evaluate(
    ({ item, code, job, platform }) => window.desk.publish.fill({ batchId: item, code, job, platform, adapterId: 'douyin', account: 'main' }),
    { item, code: man.manifest.confirmation_code, job: mine[0]?.clip ?? man.manifest.items[0].job, platform: man.manifest.items.find((i) => i.platform.startsWith('douyin')).platform },
  );
  note(`fill on 抖音 (adapter todo): ${JSON.stringify(fillTodo)}`);
} catch (e) {
  note(`FAILED: ${e.message.split('\n')[0]}`);
  await shot('error').catch(() => undefined);
} finally {
  fs.writeFileSync(path.join(out, 'flow.log'), log.join('\n') + '\n');
  await app.close();
}
