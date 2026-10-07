// Daycut app icons from the brand SVGs in packaging/brand (masters live in video-studio-app/brand/daycut).
//   node scripts/brand/icons.mjs
// Writes (committed, so packaging needs no SVG tooling):
//   packaging/resources/icon.icns        macOS (16/32 px slices from the simplified small mark, 64+ from the 1024 master)
//   packaging/resources/icon.ico         Windows 16-256 (16-32 from a larger-glyph variant so the split stays visible)
//   packaging/resources/icons/NxN.png    Linux set 16-512
//   packaging/resources/icon.png         1024 master (dev dock icon, Linux fallback)
//   packaging/resources/background.png   DMG window background (+ @2x)
// Needs rsvg-convert (brew install librsvg) and, for the .icns, macOS iconutil.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '../..');
const SRC = path.join(ROOT, 'packaging/brand');
const OUT = path.join(ROOT, 'packaging/resources');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'daycut-icons-'));

const MAC_MASTER = path.join(SRC, 'icon-macos-1024.svg');
const MAC_SMALL = path.join(SRC, 'icon-macos-small.svg');
const WIN = path.join(SRC, 'icon-windows-256.svg');
// Windows / Linux at 16-32 px: same tile, glyph scaled up ~35% (the 256 layout leaves the split 1-2 px tall)
const WIN_SMALL = path.join(tmp, 'icon-windows-small.svg');
fs.writeFileSync(WIN_SMALL, fs.readFileSync(WIN, 'utf8').replace('scale(0.3029)', 'scale(0.41)'));

function png(svg, size, out) {
  execFileSync('rsvg-convert', ['-w', String(size), '-h', String(size), '-o', out, svg]);
  return out;
}

fs.mkdirSync(path.join(OUT, 'icons'), { recursive: true });

// ---------------------------------------------------------------- macOS .icns
const iconset = path.join(tmp, 'icon.iconset');
fs.mkdirSync(iconset);
const slices = [
  ['icon_16x16.png', 16, MAC_SMALL],
  ['icon_16x16@2x.png', 32, MAC_SMALL],
  ['icon_32x32.png', 32, MAC_SMALL],
  ['icon_32x32@2x.png', 64, MAC_MASTER],
  ['icon_128x128.png', 128, MAC_MASTER],
  ['icon_128x128@2x.png', 256, MAC_MASTER],
  ['icon_256x256.png', 256, MAC_MASTER],
  ['icon_256x256@2x.png', 512, MAC_MASTER],
  ['icon_512x512.png', 512, MAC_MASTER],
  ['icon_512x512@2x.png', 1024, MAC_MASTER],
];
for (const [name, size, svg] of slices) png(svg, size, path.join(iconset, name));
if (process.platform === 'darwin') {
  execFileSync('iconutil', ['-c', 'icns', iconset, '-o', path.join(OUT, 'icon.icns')]);
} else {
  console.warn('[icons] not macOS: icon.icns left unchanged');
}
png(MAC_MASTER, 1024, path.join(OUT, 'icon.png'));

// ---------------------------------------------------------------- Windows .ico (PNG-compressed entries, Vista+)
const winSizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const entries = winSizes.map((s) => ({ s, data: fs.readFileSync(png(s <= 32 ? WIN_SMALL : WIN, s, path.join(tmp, `win-${s}.png`))) }));
const header = Buffer.alloc(6 + 16 * entries.length);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(entries.length, 4);
let offset = header.length;
entries.forEach(({ s, data }, i) => {
  const o = 6 + 16 * i;
  header.writeUInt8(s >= 256 ? 0 : s, o);
  header.writeUInt8(s >= 256 ? 0 : s, o + 1);
  header.writeUInt8(0, o + 2);
  header.writeUInt8(0, o + 3);
  header.writeUInt16LE(1, o + 4);
  header.writeUInt16LE(32, o + 6);
  header.writeUInt32LE(data.length, o + 8);
  header.writeUInt32LE(offset, o + 12);
  offset += data.length;
});
fs.writeFileSync(path.join(OUT, 'icon.ico'), Buffer.concat([header, ...entries.map((e) => e.data)]));

// ---------------------------------------------------------------- Linux png set
for (const s of [16, 24, 32, 48, 64, 128, 256, 512]) png(s <= 32 ? WIN_SMALL : WIN, s, path.join(OUT, 'icons', `${s}x${s}.png`));

// ---------------------------------------------------------------- DMG background (540x380 window, icons at 140/400 x 200)
const word = fs.readFileSync(path.join(SRC, 'wordmark-text-only-dark.svg'), 'utf8').replace(/^<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');
const dmg = `<svg xmlns="http://www.w3.org/2000/svg" width="540" height="380" viewBox="0 0 540 380">
<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22201D"/><stop offset="1" stop-color="#141311"/></linearGradient></defs>
<rect width="540" height="380" fill="url(#bg)"/>
<svg x="225" y="34" width="90" height="32" viewBox="0 0 692 246" opacity=".9">${word}</svg>
<g fill="none" stroke="#F2EDE6" stroke-opacity=".35" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M232 200 H304"/><path d="M294 190 L306 200 L294 210"/></g>
<text x="270" y="330" text-anchor="middle" font-family="-apple-system, Helvetica Neue, Arial" font-size="13" fill="#F2EDE6" fill-opacity=".55">Drag Daycut to Applications · 拖到「应用程序」</text>
</svg>`;
const dmgSvg = path.join(tmp, 'dmg.svg');
fs.writeFileSync(dmgSvg, dmg);
execFileSync('rsvg-convert', ['-w', '540', '-h', '380', '-o', path.join(OUT, 'background.png'), dmgSvg]);
execFileSync('rsvg-convert', ['-w', '1080', '-h', '760', '-o', path.join(OUT, 'background@2x.png'), dmgSvg]);

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`[icons] wrote ${path.relative(ROOT, OUT)}/{icon.icns,icon.ico,icon.png,icons/*,background*.png}`);
