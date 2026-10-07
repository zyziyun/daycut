// Open Graph / Twitter images, 1200x630 per language, rendered from the site design (paper, serif, app print).
//   node scripts/og.mjs        -> public/og/{en,zh,fr,es}.png   (committed; re-run when the hero copy changes)
// Uses the installed Google Chrome through Playwright (no browser download) and the self-hosted fonts in public/fonts.
// Needs Node 23.6+ (imports the TypeScript dictionaries directly) and ImageMagick (`magick`) to shrink the PNGs.
import { createRequire } from 'node:module';
import { execSync, execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { en } from '../src/i18n/en.ts';
import { zh } from '../src/i18n/zh.ts';
import { fr } from '../src/i18n/fr.ts';
import { es } from '../src/i18n/es.ts';

let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  ({ chromium } = createRequire(execSync('npm root -g').toString().trim() + '/')('playwright'));
}

const ROOT = resolve(import.meta.dirname, '..');
const F = (f) => `file://${join(ROOT, 'public/fonts', f)}`;
const zhFont = JSON.parse(readFileSync(join(ROOT, 'src/data/zh-font.json'), 'utf8'));
const symbol = readFileSync(join(ROOT, 'assets/brand/symbol-on-light.svg'), 'utf8');
const OUT = join(ROOT, 'public/og');
mkdirSync(OUT, { recursive: true });

const page = (lang, c) => {
  const zhl = lang === 'zh';
  const shot = `file://${join(ROOT, 'src/assets/app', zhl ? 'home-zh.png' : 'home-en.png')}`;
  return `<!doctype html><html lang="${lang}"><head><meta charset="utf-8"><style>
@font-face{font-family:IS;src:url(${F('instrument-serif-latin-400-normal.woff2')})}
@font-face{font-family:IS;font-style:italic;src:url(${F('instrument-serif-latin-400-italic.woff2')})}
@font-face{font-family:Inter;font-weight:100 900;src:url(${F('inter-latin-wght-normal.woff2')})}
@font-face{font-family:NS;font-weight:600;src:url(${F(zhFont.core)}),url(${F(zhFont.extra)})}
*{box-sizing:border-box}html,body{margin:0}
body{width:1200px;height:630px;overflow:hidden;background:#F4F0E8;color:#1C1A17;font-family:Inter,'PingFang SC',sans-serif;position:relative}
.logo{position:absolute;left:72px;top:60px;display:flex;align-items:center;gap:12px;font:600 26px/1 Inter,'PingFang SC',sans-serif}
.logo svg{width:44px;height:auto}
.eyebrow{position:absolute;left:72px;top:150px;width:540px;font:500 13px/1.4 Inter,'PingFang SC';letter-spacing:.1em;text-transform:uppercase;color:#6B6359}
h1{position:absolute;left:68px;top:188px;margin:0;width:540px;font:400 ${lang === 'en' ? 100 : 74}px/.98 IS,serif;letter-spacing:-.025em}
h1 em{font-style:italic}
.zh h1{font:600 84px/1.18 NS,'Songti SC',serif;letter-spacing:.02em}
.zh h1 em{font-style:normal;color:#0A7266}
.fine{position:absolute;left:72px;bottom:58px;font:400 18px/1.4 Inter,'PingFang SC';color:#4F4943}
.fine b{color:#0A7266;font-weight:600}
.print{position:absolute;left:640px;top:120px;width:760px;background:#FBF9F5;padding:16px;box-shadow:0 30px 60px -30px rgba(60,40,10,.3),0 0 0 1px rgba(28,26,23,.07)}
.print img{display:block;width:100%;border:1px solid rgba(28,26,23,.13)}
</style></head><body class="${zhl ? 'zh' : ''}">
<div class="logo">${symbol.replace(/<svg /, '<svg aria-hidden="true" ')}${zhl ? '千剪' : 'Reelfold'}</div>
<div class="eyebrow">${c.hero.eyebrow}</div>
<h1>${c.hero.h1a}<br><em>${c.hero.h1b}</em></h1>
<div class="fine"><b>MIT</b> · github.com/zyziyun/reelfold</div>
<div class="print"><img src="${shot}"></div>
</body></html>`;
};

const browser = await chromium.launch({ channel: 'chrome' });
const p = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
for (const [lang, c] of Object.entries({ en, zh, fr, es })) {
  const tmp = join(OUT, `.${lang}.html`);
  writeFileSync(tmp, page(lang, c));
  await p.goto(`file://${tmp}`);
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(300);
  const png = join(OUT, `${lang}.png`);
  await p.screenshot({ path: png });
  execFileSync('magick', [png, '-colors', '256', '-define', 'png:compression-level=9', png]);
  execFileSync('rm', [tmp]);
  console.log(png, (readFileSync(png).length / 1024).toFixed(0) + ' KB');
}
await browser.close();
