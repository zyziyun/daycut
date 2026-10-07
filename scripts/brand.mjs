// Daycut favicon set + Open Graph image from the brand SVGs in assets/brand (masters: video-studio-app/brand/daycut).
//   node scripts/brand.mjs
// Writes (committed): public/favicon.svg, public/favicon.ico (16/32/48), public/apple-touch-icon.png (180),
// public/icon-192.png, public/icon-512.png, public/site.webmanifest, public/img/og.png (1200x630).
// Needs rsvg-convert + magick (Homebrew) and Playwright with the installed Google Chrome (as scripts/screenshot.mjs).
import { execFileSync, execSync } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const A = path.join(ROOT, 'assets/brand');
const P = path.join(ROOT, 'public');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'daycut-site-'));
const read = (f) => fs.readFileSync(path.join(A, f), 'utf8');
const inner = (svg) => svg.replace(/^<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');

// rounded tile from the Windows icon; small sizes get a bigger glyph so the split stays visible at 16 px
const tile = read('icon-windows-256.svg');
const tileSmall = tile.replace('scale(0.3029)', 'scale(0.41)');
// iOS masks the corners itself: full-bleed square, no transparency
const square = tile
  .replace(/<path d="M54\.00,8\.00[^"]*" fill="url\(#bg13\)"\/>/, '<rect width="256" height="256" fill="url(#bg13)"/>')
  .replace(/<path d="M54\.05,8\.75[^>]*\/>/, '')
  .replace('scale(0.3029)', 'scale(0.34)');

fs.writeFileSync(path.join(P, 'favicon.svg'), tileSmall);
const png = (svg, size, out) => {
  const f = path.join(tmp, `${path.basename(out)}.svg`);
  fs.writeFileSync(f, svg);
  execFileSync('rsvg-convert', ['-w', String(size), '-h', String(size), '-o', out, f]);
  return out;
};
const ico = [16, 32, 48].map((s) => png(tileSmall, s, path.join(tmp, `f${s}.png`)));
execFileSync('magick', [...ico, path.join(P, 'favicon.ico')]);
png(square, 180, path.join(P, 'apple-touch-icon.png'));
png(tile, 192, path.join(P, 'icon-192.png'));
png(tile, 512, path.join(P, 'icon-512.png'));
fs.writeFileSync(
  path.join(P, 'site.webmanifest'),
  JSON.stringify(
    {
      name: 'Daycut',
      short_name: 'Daycut',
      icons: [
        { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
      ],
      theme_color: '#FAF6EE',
      background_color: '#FAF6EE',
      display: 'browser',
    },
    null,
    2,
  ) + '\n',
);

// ---------------------------------------------------------------- Open Graph 1200x630
const font = path.join(A, 'InterVariable.woff2');
const html = `<!doctype html><meta charset="utf-8"><style>
@font-face { font-family: Inter; src: url('file://${font}') format('woff2'); font-weight: 100 900; }
html, body { margin: 0; width: 1200px; height: 630px; }
body { background: radial-gradient(120% 120% at 15% 10%, #2C2926 0%, #181614 70%); color: #F2EDE6;
  font-family: Inter, 'PingFang SC', -apple-system, sans-serif; display: flex; align-items: center; box-sizing: border-box; padding: 0 88px; gap: 72px; }
.sym { width: 300px; flex: none; }
.sym svg { width: 300px; height: auto; display: block; }
.copy { flex: 1; }
.name { display: flex; align-items: center; gap: 18px; }
.name svg { height: 64px; width: auto; }
.name .zh { font-size: 34px; color: #A39C94; letter-spacing: .12em; font-weight: 500; margin-top: -4px; }
h1 { font-size: 54px; line-height: 1.12; letter-spacing: -0.02em; font-weight: 650; margin: 44px 0 0; }
h1 em { font-style: normal; color: #2DD4BF; }
p { margin: 30px 0 0; font-size: 22px; color: #A39C94; letter-spacing: 0; }
</style>
<div class="sym">${read('symbol-on-dark.svg')}</div>
<div class="copy">
  <div class="name"><svg viewBox="32 32 630 187">${inner(read('wordmark-text-only-dark.svg'))}</svg><span class="zh">日剪</span></div>
  <h1>Turn one recording into <em>a month of short videos</em></h1>
  <p>Built on the open-source video-studio engine</p>
</div>`;
const htmlFile = path.join(tmp, 'og.html');
fs.writeFileSync(htmlFile, html);
let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  ({ chromium } = createRequire(execSync('npm root -g').toString().trim() + '/')('playwright'));
}
const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
await page.goto('file://' + htmlFile);
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: path.join(P, 'img/og.png') });
await browser.close();

fs.rmSync(tmp, { recursive: true, force: true });
console.log('brand assets written to public/');
