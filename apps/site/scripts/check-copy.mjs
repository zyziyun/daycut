// Copy rules: no em-dashes, no hype words (最 / 第一 / 100% / best / ultimate ...). Scans the built HTML text.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const banned = [
  [/—|―/g, 'em-dash'],
  [/最/g, '最'],
  [/第一/g, '第一'],
  [/100\s?%/g, '100%'],
  [/首个|唯一|顶级|极致|颠覆|爆款|保证/g, 'hype (zh)'],
  [/\b(best|ultimate|revolutionary|guaranteed?|world-class|game-chang\w*|10x|unmatched|seamless(ly)?)\b/gi, 'hype (en)'],
];
const files = [];
const walk = (d) => readdirSync(d).forEach((f) => {
  const p = join(d, f);
  statSync(p).isDirectory() ? walk(p) : p.endsWith('.html') && files.push(p);
});
walk('dist');
// dist/docs (the docs site, copied in at deploy time) has its own copy rules
for (let i = files.length - 1; i >= 0; i--) if (files[i].startsWith('dist/docs/')) files.splice(i, 1);
let bad = 0;
for (const f of files) {
  const text = readFileSync(f, 'utf8').replace(/<style[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, ' ');
  for (const [re, name] of banned) {
    for (const m of text.matchAll(re)) {
      bad++;
      console.log(`${f}: ${name}: …${text.slice(Math.max(0, m.index - 30), m.index + 30).replace(/\s+/g, ' ')}…`);
    }
  }
}
if (bad) { console.error(`\n${bad} copy-rule violation(s).`); process.exit(1); }
console.log(`copy check ok (${files.length} pages)`);
