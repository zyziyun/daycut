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
const shots = [
  ['home-en-desktop', '/', 1440, 900, 1],
  ['home-en-mobile', '/', 390, 844, 1],
  ['home-zh-desktop', '/zh/', 1440, 900, 1],
  ['home-zh-mobile', '/zh/', 390, 844, 1],
  ['privacy-mobile', '/privacy', 390, 844, 1],
];
const browser = await chromium.launch({ channel: 'chrome' });
for (const [name, path, width, height, dpr] of shots) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: dpr });
  await page.goto(base + path, { waitUntil: 'networkidle' });
  // Force lazy images to load before the full-page capture.
  await page.evaluate(async () => {
    document.querySelectorAll('img[loading=lazy]').forEach((i) => (i.loading = 'eager'));
    await Promise.all([...document.images].map((i) => i.complete || new Promise((r) => (i.onload = i.onerror = r))));
  });
  await page.screenshot({ path: `screenshots/${name}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(name, 'horizontal overflow px:', overflow);
  await page.close();
}
await browser.close();
