// Internal link check for the built docs: every href/src under /docs/ must resolve to a file in dist/, and every
// #fragment on a docs page must exist as an id on the target page. Run after `npm run build`:
//   node scripts/check-links.mjs        (exit 1 on broken links)
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative, dirname, posix } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = fileURLToPath(new URL('../dist', import.meta.url));
const BASE = '/docs';
const files = [];
(function walk(d) {
  for (const f of readdirSync(d)) {
    const p = join(d, f);
    if (statSync(p).isDirectory()) walk(p);
    else if (p.endsWith('.html')) files.push(p);
  }
})(dist);

const idCache = new Map();
const idsOf = (file) => {
  if (!idCache.has(file)) {
    const html = readFileSync(file, 'utf8');
    idCache.set(file, new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])));
  }
  return idCache.get(file);
};
const resolveFile = (path) => {
  let p = decodeURIComponent(path.slice(BASE.length)) || '/';
  const cands = p.endsWith('/') ? [join(dist, p, 'index.html')] : [join(dist, p), join(dist, p, 'index.html'), join(dist, p + '.html')];
  return cands.find((c) => existsSync(c) && statSync(c).isFile());
};

const broken = [];
let checked = 0;
for (const file of files) {
  if (file.endsWith('404.html')) continue; // the 404 page's language links are relative to the missing URL
  const html = readFileSync(file, 'utf8').replace(/<(code|pre)\b[\s\S]*?<\/\1>/g, '');
  const pagePath = BASE + '/' + relative(dist, dirname(file)).split('\\').join('/') + '/';
  for (const m of html.matchAll(/\s(?:href|src)="([^"]+)"/g)) {
    let url = m[1].replace(/&amp;/g, '&');
    if (/^(https?:|mailto:|data:|javascript:)/.test(url)) {
      if (!url.startsWith('https://reelfold.com/docs')) continue;
      url = url.replace('https://reelfold.com', '');
    }
    if (url.startsWith('#')) url = pagePath + url;
    else if (!url.startsWith('/')) url = posix.normalize(posix.join(pagePath, url));
    if (!url.startsWith(BASE)) continue; // the main site (reelfold.com/, /zh/) is checked by apps/site
    const [path, frag] = url.split('#');
    checked++;
    const target = resolveFile(path.split('?')[0]);
    if (!target) broken.push(`${relative(dist, file)} -> ${url} (no such page)`);
    else if (frag && target.endsWith('.html') && !idsOf(target).has(decodeURIComponent(frag)))
      broken.push(`${relative(dist, file)} -> ${url} (no #${frag})`);
  }
}
const uniq = [...new Set(broken)];
console.log(`checked ${checked} internal links in ${files.length} pages: ${uniq.length} broken`);
uniq.slice(0, 200).forEach((b) => console.log('  ' + b));
process.exit(uniq.length ? 1 : 0);
