// Built-site checks (IMPLEMENTATION.md §6.6): run after `npm run build`.  node scripts/check-site.mjs
// - SEO: one <h1>, no skipped heading levels, <title> + description, absolute self-canonical, hreflang alternates
//   (en, zh-Hans, fr, es, x-default) that are reciprocal, JSON-LD parses, OG image exists.
// - Images: every <img> has alt, width and height.
// - Internal links: every href="/..." resolves to a built file, and every #fragment exists on the target page.
// - No /docs pages in this site (apps/docs is copied into dist/docs at deploy time); /docs/ links are not checked.
// - Privacy: no third-party scripts, stylesheets or fonts (no trackers, no Google Fonts).
// - 中文 headings: every CJK character in a serif element is in the Noto Serif SC subset (scripts/subset-zh-font.py).
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';

const DIST = 'dist';
const SITE = 'https://reelfold.com';
const files = [];
const walk = (d) => readdirSync(d).forEach((f) => {
  const p = join(d, f);
  statSync(p).isDirectory() ? walk(p) : p.endsWith('.html') && files.push(p);
});
walk(DIST);
// dist/docs (if a deploy already copied the docs site in) is not ours to check
for (let i = files.length - 1; i >= 0; i--) if (relative(DIST, files[i]).startsWith('docs')) files.splice(i, 1);

const errors = [];
const err = (f, m) => errors.push(`${relative(DIST, f)}: ${m}`);
const urlOf = (f) => '/' + relative(DIST, f).replace(/index\.html$/, '').replace(/\\/g, '/');
const isStub = (html) => /http-equiv="refresh"/.test(html);

const pages = new Map();
for (const f of files) pages.set(urlOf(f), { f, html: readFileSync(f, 'utf8') });

const resolve = (path) => {
  const p = path.split('#')[0].split('?')[0];
  const cands = [join(DIST, p), join(DIST, p, 'index.html'), join(DIST, p + '.html')];
  return cands.find((c) => existsSync(c) && statSync(c).isFile());
};
const ids = (html) => new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
const attr = (tag, name) => (tag.match(new RegExp(`\\s${name}="([^"]*)"`)) || [])[1];

let links = 0;
for (const [url, { f, html }] of pages) {
  if (isStub(html)) continue;
  const noindex = /<meta name="robots" content="noindex"/.test(html);
  const body = html.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '');

  // headings
  const hs = [...body.matchAll(/<h([1-6])[\s>]/g)].map((m) => +m[1]);
  if (hs.filter((h) => h === 1).length !== 1) err(f, `expected one <h1>, found ${hs.filter((h) => h === 1).length}`);
  hs.reduce((prev, h) => { if (h > prev + 1) err(f, `heading level skips h${prev} -> h${h}`); return h; }, 1);

  // title / description / canonical
  const title = (html.match(/<title>([^<]*)<\/title>/) || [])[1];
  if (!title) err(f, 'missing <title>');
  else if (!noindex && [...title].length > 110) err(f, `title too long (${[...title].length})`);
  if (!/<meta name="description" content="[^"]{20,}"/.test(html)) err(f, 'missing description');
  const canon = (html.match(/<link rel="canonical" href="([^"]+)"/) || [])[1];
  if (!canon?.startsWith(SITE + '/')) err(f, `canonical not absolute: ${canon}`);
  else if (!noindex && !url.endsWith('404.html') && canon !== SITE + url) err(f, `canonical ${canon} != ${SITE + url}`);
  if (!/<html lang="[a-zA-Z-]+"/.test(html)) err(f, 'missing <html lang>');

  // hreflang (indexable pages)
  if (!noindex) {
    const alts = [...html.matchAll(/<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"/g)].map((m) => [m[1], m[2]]);
    const langs = alts.map((a) => a[0]).sort().join(',');
    if (langs !== 'en,es,fr,x-default,zh-Hans') err(f, `hreflang set is ${langs}`);
    if (!alts.some(([, h]) => h === canon)) err(f, 'hreflang does not include self');
    for (const [, href] of alts) {
      const target = pages.get(href.replace(SITE, ''));
      if (!target) { err(f, `hreflang target missing: ${href}`); continue; }
      if (!target.html.includes(`href="${canon}"`)) err(f, `hreflang not reciprocal from ${href}`);
    }
    const og = (html.match(/<meta property="og:image" content="([^"]+)"/) || [])[1];
    if (!og || !existsSync(join(DIST, og.replace(SITE, '')))) err(f, `og:image missing: ${og}`);
  }

  // JSON-LD
  for (const m of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    try { JSON.parse(m[1]); } catch (e) { err(f, `JSON-LD does not parse: ${e.message}`); }
  }

  // images
  for (const m of body.matchAll(/<img\b[^>]*>/g)) {
    const tag = m[0];
    if (attr(tag, 'alt') === undefined) err(f, `img without alt: ${tag.slice(0, 80)}`);
    if (!attr(tag, 'width') || !attr(tag, 'height')) err(f, `img without width/height: ${tag.slice(0, 80)}`);
  }

  // third-party requests
  for (const m of html.matchAll(/<(script|link|img|source|iframe)\b[^>]*\s(src|href|srcset)="(https?:)?\/\/(?!reelfold\.com)[^"]*"[^>]*>/g)) {
    if (/rel="(canonical|alternate)"/.test(m[0]) || /<meta/.test(m[0])) continue;
    // Cloudflare Web Analytics (cookieless), only in builds with CF_BEACON_TOKEN
    if (/^<script\b[^>]*src="https:\/\/static\.cloudflareinsights\.com\/beacon\.min\.js"/.test(m[0])) continue;
    err(f, `third-party resource: ${m[0].slice(0, 100)}`);
  }
  if (/fonts\.googleapis|fonts\.gstatic|googletagmanager|google-analytics/.test(html)) err(f, 'third-party font/tracker');

  // internal links
  for (const m of body.matchAll(/<a\b[^>]*\shref="([^"]+)"/g)) {
    const href = m[1].replace(/&amp;/g, '&');
    if (/^(https?:|mailto:)/.test(href)) continue;
    if (href.startsWith('/docs/')) continue; // docs site (apps/docs), copied into dist/docs at deploy time
    links++;
    const [path, frag] = href.split('#');
    const target = path ? resolve(path) : f;
    if (!target) { err(f, `broken link ${href}`); continue; }
    if (path && !path.endsWith('/') && !path.includes('.')) err(f, `link without trailing slash: ${href}`);
    if (frag && !ids(readFileSync(target, 'utf8')).has(frag)) err(f, `missing anchor ${href}`);
  }
}

if (existsSync('src/pages/docs')) errors.push('src/pages/docs exists: /docs belongs to the docs site (apps/docs), copied into dist/docs at deploy');

// 中文 serif glyph coverage
const font = JSON.parse(readFileSync('src/data/zh-font.json', 'utf8'));
const have = new Set([...font.coreChars, ...font.extraChars]);
const CJK = /[　-〿㐀-䶿一-鿿＀-￯]/g;
const missing = new Set();
for (const [url, { html }] of pages) {
  if (!url.startsWith('/zh/') || isStub(html)) continue;
  const b = html.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '');
  for (const m of b.matchAll(/<(h1|h2|h3|summary|dd|b|th)\b[^>]*>([\s\S]*?)<\/\1>|<ul class="plats">([\s\S]*?)<\/ul>/g)) {
    for (const ch of (m[2] || m[3]).replace(/<[^>]+>/g, '').match(CJK) || []) if (!have.has(ch)) missing.add(ch);
  }
}
if (missing.size) errors.push(`zh serif subset is missing ${[...missing].join('')}: run python3 scripts/subset-zh-font.py and rebuild`);

if (errors.length) {
  console.error(errors.join('\n'));
  console.error(`\n${errors.length} problem(s).`);
  process.exit(1);
}
console.log(`site check ok (${pages.size} pages, ${links} internal links)`);
