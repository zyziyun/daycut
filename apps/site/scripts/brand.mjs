// Reelfold favicon set + Open Graph image from the brand files in assets/brand
// (masters: brand/round3/reelfold in the private design repo; social preview: gtm/launch/social-preview-1280x640.png).
//   node scripts/brand.mjs
// Writes (committed): public/favicon.svg, public/favicon.ico (16/32/48), public/apple-touch-icon.png (180),
// public/icon-192.png, public/icon-512.png, public/site.webmanifest.
// Needs rsvg-convert + magick (Homebrew).
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const A = path.join(ROOT, 'assets/brand');
const P = path.join(ROOT, 'public');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-site-'));
const read = (f) => fs.readFileSync(path.join(A, f), 'utf8');

// Rounded dark tile from the Windows icon. Small sizes get a bigger glyph so the cards stay readable at 16 px.
const tile = read('icon-windows-256.svg');
const GLYPH = /scale\(0\.3029\)/;
if (!GLYPH.test(tile)) throw new Error('icon-windows-256.svg: glyph transform not found; update GLYPH');
const tileSmall = tile.replace(GLYPH, 'scale(0.40)');
// iOS masks the corners itself: full-bleed square, no transparency
const bgFill = tile.match(/<path d="M54\.00,8\.00[^"]*" fill="(url\(#[^)]+\))"\/>/);
if (!bgFill) throw new Error('icon-windows-256.svg: tile background path not found');
const square = tile
  .replace(bgFill[0], `<rect width="256" height="256" fill="${bgFill[1]}"/>`)
  .replace(/<path d="M54\.05,8\.75[^>]*\/>/, '')
  .replace(GLYPH, 'scale(0.36)');

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
      name: 'Reelfold',
      short_name: 'Reelfold',
      icons: [
        { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
      ],
      theme_color: '#F4F0E8',
      background_color: '#F4F0E8',
      display: 'browser',
    },
    null,
    2,
  ) + '\n',
);

// Open Graph images (1200x630 per language) are made by scripts/og.mjs from the site design.

fs.rmSync(tmp, { recursive: true, force: true });
console.log('brand assets written to public/');
