// Screenshots of built pages for review: node scripts/shots.mjs [baseUrl] [outDir] path1 path2 ...
// Uses the system Chrome through playwright-core (no browser download).
import { chromium } from 'playwright-core';
const [base = 'http://localhost:4321', out = '/tmp/rf-docs-shots', ...paths] = process.argv.slice(2);
const list = paths.length ? paths : ['/docs/', '/docs/zh/'];
const browser = await chromium.launch({ channel: 'chrome' });
for (const theme of ['light']) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: theme });
  const page = await ctx.newPage();
  for (const p of list) {
    await page.goto(base + p, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    const name = p.replace(/^\/docs\/?/, '').replace(/\/$/, '').replace(/\//g, '_') || 'home';
    await page.screenshot({ path: `${out}/${name}.png`, fullPage: process.env.FULL === '1' });
    console.log(`${out}/${name}.png`);
  }
}
await browser.close();
