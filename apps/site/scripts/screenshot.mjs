// Full-page screenshots of the built site using the locally installed Google Chrome (no browser download).
// Mobile shots use DPR 1: Chrome cannot capture images taller than 16384 device px in one go.
// Usage: npm run build && npm run preview (in another shell), then: node scripts/screenshot.mjs [baseUrl]
// Needs Playwright: a local devDependency or a global install (`npm i -g playwright`); no browser download needed.
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  const globalRoot = execSync('npm root -g').toString().trim();
  ({ chromium } = createRequire(globalRoot + '/')('playwright'));
}
const base = process.argv[2] || 'http://localhost:4321';
const only = process.argv[3] ? new RegExp(process.argv[3]) : null;
const shots = [];
for (const [l, path] of [['en', '/'], ['zh', '/zh/'], ['fr', '/fr/'], ['es', '/es/']]) {
  shots.push([`home-${l}-1440`, path, 1440, 900, 1], [`home-${l}-390`, path, 390, 844, 1]);
}
for (const path of ['/podcast-clips/', '/zh/course-slicing/', '/fr/compare/descript/', '/es/platforms/', '/zh/platforms/']) {
  const n = path.replace(/^\/|\/$/g, '').replace(/\//g, '-');
  shots.push([`${n}-1440`, path, 1440, 900, 1], [`${n}-390`, path, 390, 844, 1]);
}
shots.push(['privacy-390', '/privacy/', 390, 844, 1]);
const browser = await chromium.launch({ channel: 'chrome' });
for (const [name, path, width, height, dpr] of shots) {
  if (only && !only.test(name)) continue;
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: dpr });
  await page.goto(base + path, { waitUntil: 'networkidle' });
  // Force lazy images to load before the full-page capture.
  await page.evaluate(async () => {
    document.querySelectorAll('img[loading=lazy]').forEach((i) => (i.loading = 'eager'));
    await Promise.all([...document.images].map((i) => i.complete || new Promise((r) => (i.onload = i.onerror = r))));
    // decode before capture, or large AVIFs can still paint black in the full-page shot
    await Promise.all([...document.images].map((i) => i.decode().catch(() => {})));
    document.querySelectorAll('.reveal').forEach((x) => x.classList.add('in'));
    await document.fonts.ready;
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `screenshots/${name}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(name, 'horizontal overflow px:', overflow);
  await page.close();
}
await browser.close();
