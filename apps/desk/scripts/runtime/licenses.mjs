// Regenerate THIRD_PARTY_LICENSES.md from the pins: Python packages (packaging/requirements/*.txt, licences from
// PyPI metadata), ffmpeg + its libraries (packaging/ffmpeg/*.json, conda-forge licence fields), first-run assets
// (packaging/assets.json) and the npm runtime dependencies. The licence *texts* ship inside the app under
// resources/runtime/licenses (collected by bundle.mjs) and Electron's LICENSES.chromium.html.
//   node scripts/runtime/licenses.mjs
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { CACHE, readLock, ROOT } from './common.mjs';

// node_modules may be hoisted to the monorepo root (npm workspaces)
const pkgOf = (n) => JSON.parse(fs.readFileSync(createRequire(path.join(ROOT, 'package.json')).resolve(`${n}/package.json`), 'utf8'));

const lock = readLock();
const targets = Object.keys(lock.targets);
const pkgJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));

async function pypiLicence(name, version) {
  const f = path.join(CACHE, 'pypi', `${name}-${version}.json`);
  let d;
  if (fs.existsSync(f)) d = JSON.parse(fs.readFileSync(f, 'utf8'));
  else {
    const r = await fetch(`https://pypi.org/pypi/${name}/${version}/json`);
    d = r.ok ? (await r.json()).info : {};
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, JSON.stringify({ license_expression: d.license_expression, license: d.license, classifiers: d.classifiers, home_page: d.home_page, project_urls: d.project_urls }));
  }
  const cls = (d.classifiers ?? []).filter((c) => c.startsWith('License ::')).map((c) => c.split(' :: ').pop());
  const lic = d.license_expression || (cls.length ? cls.join(' / ') : (d.license ?? '').split('\n')[0].slice(0, 60)) || 'see package';
  const url = d.project_urls?.Source || d.project_urls?.Homepage || d.home_page || `https://pypi.org/project/${name}/`;
  return { lic, url };
}

const py = new Map();
for (const t of targets) {
  const txt = fs.readFileSync(path.join(ROOT, 'packaging', 'requirements', `${t}.txt`), 'utf8');
  for (const m of txt.matchAll(/^([A-Za-z0-9_.-]+)==([^\s;\\]+)/gm)) {
    const k = `${m[1]}==${m[2]}`;
    if (!py.has(k)) py.set(k, { name: m[1], version: m[2], targets: [] });
    py.get(k).targets.push(t);
  }
}
const pyRows = [];
for (const p of [...py.values()].sort((a, b) => a.name.localeCompare(b.name))) {
  const { lic, url } = await pypiLicence(p.name, p.version);
  pyRows.push(`| ${p.name} | ${p.version} | ${lic.replaceAll('|', '/')} | ${p.targets.length === targets.length ? 'all' : p.targets.join(', ')} | ${url} |`);
}

const ff = new Map();
for (const t of targets) {
  for (const p of JSON.parse(fs.readFileSync(path.join(ROOT, 'packaging', 'ffmpeg', `${t}.json`), 'utf8'))) {
    const k = `${p.name}`;
    if (!ff.has(k)) ff.set(k, { ...p, targets: [] });
    ff.get(k).targets.push(t);
  }
}
const ffRows = [...ff.values()]
  .sort((a, b) => a.name.localeCompare(b.name))
  .map((p) => `| ${p.name} | ${p.version} | ${p.license ?? '?'} | ${p.targets.length === targets.length ? 'all' : p.targets.join(', ')} | https://github.com/conda-forge/${p.name.replace(/^lib(?=(zlib|ffi|iconv|intl|glib|xml2))/, '')}-feedstock |`);

const assets = JSON.parse(fs.readFileSync(path.join(ROOT, 'packaging', 'assets.json'), 'utf8'));
const assetRows = assets.groups.map((g) => `| ${g.id} | ${(g.targets ?? ['all']).join(', ')} | ${g.licence} | ${new URL(g.files[0].url).host} |`);

// npm code that ships: runtime + optional dependencies with their whole dependency closure (electron-updater's
// builder-util-runtime, js-yaml, semver, lazy-val …; node-pty's native addon, unpacked from the asar), plus the
// devDependencies the renderer bundle inlines (Vite bundles them into out/renderer).
const BUNDLED_DEV = ['react', 'react-dom', 'scheduler', '@xterm/xterm'];
const licenceOf = (p) => (typeof p.license === 'string' ? p.license : p.license?.type) ?? (p.licenses ?? []).map((l) => l.type ?? l).join(' OR ') ?? '?';
function closure(names) {
  const seen = new Map();
  const visit = (name, from) => {
    let file;
    try {
      file = createRequire(path.join(from, 'package.json')).resolve(`${name}/package.json`);
    } catch {
      return; // optional dependency not installed on this platform
    }
    const p = JSON.parse(fs.readFileSync(file, 'utf8'));
    const key = `${p.name}@${p.version}`;
    if (seen.has(key)) return;
    seen.set(key, { name: p.name, version: p.version, license: licenceOf(p) || '?', repo: typeof p.repository === 'string' ? p.repository : p.repository?.url });
    for (const d of Object.keys(p.dependencies ?? {})) visit(d, path.dirname(file));
  };
  for (const n of names) visit(n, ROOT);
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}
const repoUrl = (r, name) => {
  if (!r) return `https://www.npmjs.com/package/${name}`;
  const u = r
    .replace(/^git\+/, '')
    .replace(/^(ssh:\/\/)?git@github\.com[:/]/, 'https://github.com/')
    .replace(/^git:\/\//, 'https://')
    .replace(/^github:/, 'https://github.com/')
    .replace(/\.git$/, '');
  return /^[\w.-]+\/[\w.-]+$/.test(u) ? `https://github.com/${u}` : u;
};
const npmRows = closure([...Object.keys(pkgJson.dependencies ?? {}), ...Object.keys(pkgJson.optionalDependencies ?? {}), ...BUNDLED_DEV])
  .filter((p) => p.name !== 'react' && p.name !== 'react-dom')
  .map((p) => `| ${p.name} | ${p.version} | ${p.license} | ${repoUrl(p.repo, p.name)} |`);
const electronVersion = pkgOf('electron').version;

const md = `# Third-party software in Daycut

Daycut (built on the open-source Daycut engine, the \`vstudio\` library in this repository) is distributed with, or downloads on first run, the components below. Each keeps its own
licence. Licence texts ship inside the app: \`resources/runtime/licenses/\` (Python packages, ffmpeg and its
libraries, video-studio), \`LICENSES.chromium.html\` and \`LICENSE.electron.txt\` next to the executable (Electron /
Chromium / Node.js). This file is generated by \`scripts/runtime/licenses.mjs\` from the pins in \`packaging/\`.

## Application shell

| Component | Version | Licence | Source |
|---|---|---|---|
| Electron (incl. Chromium, Node.js, V8, ffmpeg-for-media-playback) | ${electronVersion} | MIT; Chromium BSD-3-Clause + third-party (LICENSES.chromium.html) | https://github.com/electron/electron |
| React, React DOM | ${pkgOf('react').version} | MIT | https://github.com/facebook/react |
${npmRows.join('\n')}

The in-app login terminal uses node-pty (native addon, shipped unpacked next to the asar) and xterm.js (bundled into
the renderer). Auto-update uses electron-updater and the dependencies listed above.

### Brand

The Daycut wordmark is drawn from outlines of the Inter typeface (Rasmus Andersson, https://github.com/rsms/inter),
SIL Open Font License 1.1 (https://openfontlicense.org). Inter itself is not shipped as a font file.

## Engine runtime (bundled)

| Component | Version | Licence | Source |
|---|---|---|---|
| CPython (python-build-standalone ${lock.python.release}) | ${lock.python.version} | PSF-2.0 (CPython); build scripts BSD-3-Clause; bundled OpenSSL Apache-2.0, SQLite public domain, libffi MIT, zlib Zlib, xz 0BSD, bzip2 bzip2-1.0.6, mpdecimal BSD-2-Clause, libedit/ncurses BSD/MIT | https://github.com/astral-sh/python-build-standalone |
| Daycut engine (vstudio library + workflows) | same repository (monorepo root) | MIT | ${lock.vstudio.repo.replace(/\.git$/, '')} |

### FFmpeg (LGPL build)

The bundled \`ffmpeg\`/\`ffprobe\` are the conda-forge **LGPL** build of FFmpeg ${lock.ffmpeg.spec.split('=')[1]}
(configured \`--disable-gpl --enable-version3 --enable-shared\`, i.e. LGPL-3.0-or-later as a whole; no libx264/libx265).
FFmpeg and its libraries are dynamically linked shared libraries in \`resources/runtime/ffmpeg/\` and can be replaced
by the user. Corresponding source: FFmpeg ${lock.ffmpeg.spec.split('=')[1]} — ${lock.ffmpeg.source}; build recipe and
patches — ${lock.ffmpeg.recipe}; every library below — its conda-forge feedstock (recipe + upstream source URL and
checksum in \`recipe/meta.yaml\`). On request we will provide the exact sources for three years from distribution.
H.264 encoding uses the operating system (VideoToolbox / Media Foundation) or OpenH264 (BSD-2-Clause, built from
source; note that Cisco's patent licence covers only Cisco's own binaries).

Packages in the locked ffmpeg environments (only the libraries ffmpeg actually loads are shipped; the per-build list
is \`resources/runtime/licenses/ffmpeg-components.json\`):

| Package | Version | Licence | Targets | Source |
|---|---|---|---|---|
${ffRows.join('\n')}

Dual-licensed components are used under their non-GPL option: FreeType under the FreeType License (FTL), GMP under
LGPL-3.0-or-later, D-Bus under AFL-2.1. \`scripts/runtime/bundle.mjs\` warns if a GPL-only library ever enters the
ffmpeg closure and fails if libx264/libx265 appear.

### Python packages

Hash-locked in \`packaging/requirements/<target>.txt\`.

| Package | Version | Licence | Targets | Source |
|---|---|---|---|---|
${pyRows.join('\n')}

## Downloaded on first run (not in the installer)

Fetched from the upstream URLs pinned in \`packaging/assets.json\` into the app data folder and verified by sha256.

| Asset group | Targets | Licence | Host |
|---|---|---|---|
${assetRows.join('\n')}

Fonts: Noto Sans SC / Noto Serif SC (notofonts/noto-cjk), STIX Two Text (google/fonts), JetBrains Mono — all SIL Open
Font License 1.1 (https://openfontlicense.org). MediaPipe models (face landmarker, selfie segmenter, selfie multiclass
segmenter) — Apache-2.0, Google. Whisper large-v3-turbo weights — MIT, OpenAI (MLX conversion: mlx-community;
CTranslate2 conversion: dropbox-dash / Mobius Labs). Chromium snapshot builds — BSD-3-Clause and third-party licences.

## Not bundled

The optional RVM matting engine used by the engine's cover workflow is GPL-3.0 and is never shipped with the app.
`;
fs.writeFileSync(path.join(ROOT, 'THIRD_PARTY_LICENSES.md'), md);
console.log(`THIRD_PARTY_LICENSES.md: ${pyRows.length} python packages, ${ffRows.length} ffmpeg packages, ${assetRows.length} asset groups`);
