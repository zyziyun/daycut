// Render the Open Graph images (1200x630) for the docs: node scripts/og.mjs  -> public/og/og-{en,zh}.png
// Uses the system Chrome through playwright-core and the same self-hosted fonts as the site.
import { chromium } from 'playwright-core';
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('..', import.meta.url));
const b64 = (p) => readFileSync(p).toString('base64');
const serif = b64(require.resolve('@fontsource-variable/newsreader/files/newsreader-latin-opsz-normal.woff2'));
const serifI = b64(require.resolve('@fontsource-variable/newsreader/files/newsreader-latin-opsz-italic.woff2'));
const inter = b64(require.resolve('@fontsource-variable/inter/files/inter-latin-wght-normal.woff2'));
const zh = b64(`${root}src/assets/fonts/noto-serif-sc-sub.woff2`);
const logo = readFileSync(`${root}src/assets/wordmark-on-light.svg`, 'utf8');

const copy = {
  en: { k: 'Documentation', h: 'One recording.<br><em>Every cut.</em>', s: 'Install the Mac app or the Claude Code skill, and turn one recording into every clip for every platform.' },
  zh: { k: '使用文档', h: '一条素材，<br><em>千条成片。</em>', s: '安装 Mac 版或 Claude Code 技能，一条素材剪成各个平台的成片。' },
};
const html = (c, lang) => `<!doctype html><html lang="${lang}"><style>
@font-face{font-family:IS;font-weight:200 800;src:url(data:font/woff2;base64,${serif})}
@font-face{font-family:IS;font-style:italic;font-weight:200 800;src:url(data:font/woff2;base64,${serifI})}
@font-face{font-family:Inter;src:url(data:font/woff2;base64,${inter});font-weight:100 900}
@font-face{font-family:ZH;src:url(data:font/woff2;base64,${zh});font-weight:700}
body{margin:0;width:1200px;height:630px;background:#F4F0E8;color:#1C1A17;font-family:Inter,sans-serif;position:relative;overflow:hidden}
.logo{position:absolute;left:80px;top:72px;width:220px}.logo svg{width:100%;height:auto}
.k{position:absolute;left:80px;top:190px;font:500 18px/1 Inter;letter-spacing:.14em;text-transform:uppercase;color:#6B6359;display:flex;gap:14px;align-items:center}
.k:before{content:"";width:34px;height:1px;background:#6B6359}
h1{position:absolute;left:76px;top:226px;margin:0;font:400 96px/1.04 IS,serif;letter-spacing:-.022em}
h1 em{font-style:italic}
.zh h1{font:700 88px/1.2 ZH,serif;letter-spacing:.02em}.zh h1 em{font-style:normal;color:#0A7266}.zh .k{letter-spacing:.3em}
p{position:absolute;left:80px;bottom:70px;margin:0;width:640px;font:400 23px/1.5 Inter,"PingFang SC",sans-serif;color:#4F4943}
.u{position:absolute;right:80px;bottom:72px;font:500 20px/1 Inter;color:#0A7266}
.cards{position:absolute;right:-40px;top:120px;width:420px;height:420px}
.cards div{position:absolute;width:210px;height:280px;background:#FBF9F5;border:1px solid rgba(28,26,23,.13);box-shadow:0 30px 50px -30px rgba(60,40,10,.35);left:120px;top:40px;transform-origin:50% 120%}
</style><body class="${lang}"><div class="logo">${logo}</div>
<div class="cards"><div style="transform:rotate(-16deg)"></div><div style="transform:rotate(-6deg)"></div><div style="transform:rotate(5deg);background:#0A7266;border-color:#0A7266"></div></div>
<div class="k">${c.k}</div><h1>${c.h}</h1><p>${c.s}</p><div class="u">reelfold.com/docs</div></body></html>`;

mkdirSync(`${root}public/og`, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
for (const [lang, c] of Object.entries(copy)) {
  await page.setContent(html(c, lang), { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${root}public/og/og-${lang}.png` });
  console.log(`public/og/og-${lang}.png`);
}
await browser.close();
