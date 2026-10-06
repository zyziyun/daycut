// Build the self-contained engine runtime for one target into build/runtime/<target>/:
//   python/   python-build-standalone + the pinned pip set (packaging/requirements/<target>.txt, hash-checked)
//   ffmpeg/   LGPL ffmpeg/ffprobe + only the shared libraries they load (packaging/ffmpeg/<target>.txt)
//   vstudio/  the video-studio repo at the commit pinned in packaging/runtime.lock.json
//   licenses/ licence texts + component lists for everything above (feeds THIRD_PARTY_LICENSES.md)
//   runtime.json  what was built (read by the app at startup and shown in Settings)
// Usage: node scripts/runtime/bundle.mjs [--target=darwin-arm64] [--skip=python,ffmpeg,vstudio]
// The pip step runs the target's own interpreter, so build on a host of the target's OS/arch (CI matrix does).
import fs from 'node:fs';
import path from 'node:path';
import { machoClosure, peClosure } from './binaries.mjs';
import { arg, CACHE, download, log, micromamba, pbsUrl, readLock, rmrf, ROOT, run, TAR, targetFromArgs } from './common.mjs';

const lock = readLock();
const target = targetFromArgs();
if (!lock.targets[target]) throw new Error(`unknown target ${target}; one of ${Object.keys(lock.targets).join(', ')}`);
const T = lock.targets[target];
const isWin = target.startsWith('win32');
const isMac = target.startsWith('darwin');
const OUT = path.join(ROOT, 'build', 'runtime', target);
const skip = new Set((arg('skip') ?? '').split(',').filter(Boolean));
const host = `${process.platform}-${process.arch}`;

fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.join(OUT, 'licenses'), { recursive: true });

const pyExe = () => (isWin ? path.join(OUT, 'python', 'python.exe') : path.join(OUT, 'python', 'bin', 'python3'));

// ------------------------------------------------------------------ python
async function buildPython() {
  if (host !== target) throw new Error(`python step must run on ${target} (host is ${host})`);
  rmrf(path.join(OUT, 'python'));
  const url = pbsUrl(lock, target);
  const tgz = await download(url, path.join(CACHE, path.basename(url)), lock.python.sha256[target]);
  run(TAR, ['-xzf', tgz, '-C', OUT]); // -> OUT/python
  const py = pyExe();
  const req = path.join(ROOT, 'packaging', 'requirements', `${target}.txt`);
  run(py, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '--no-deps',
    '--require-hashes', '--only-binary=:all:', '--no-compile', '-r', req],
  { env: { ...process.env, PIP_CACHE_DIR: path.join(CACHE, 'pip'), PYTHONNOUSERSITE: '1' } });
  // licence inventory before pip itself goes
  const inv = run(py, ['-c', INVENTORY_PY, path.join(OUT, 'licenses', 'python-packages')], { capture: true, quiet: true });
  fs.writeFileSync(path.join(OUT, 'licenses', 'python-packages.json'), inv);
  pruneSitePackages();
  run(py, ['-m', 'compileall', '-q', '-j', '0', '--invalidation-mode', 'unchecked-hash', path.join(OUT, 'python')], { stdio: ['ignore', 'ignore', 'ignore'], allowFail: true }); // a few template files are not valid py3
}

const INVENTORY_PY = String.raw`
import importlib.metadata as md, json, os, shutil, sys
out = sys.argv[1]; os.makedirs(out, exist_ok=True); rows = []
for d in sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower()):
    m = d.metadata; name = m["Name"]
    lic = m.get("License-Expression") or next((c.split(" :: ")[-1] for c in (m.get_all("Classifier") or []) if c.startswith("License ::")), None) or (m.get("License") or "").split("\n")[0][:80] or "?"
    files = [f for f in (d.files or []) if any(k in f.name.upper() for k in ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS"))]
    dst = os.path.join(out, name); copied = []
    for f in files:
        src = d.locate_file(f)
        if os.path.isfile(src):
            os.makedirs(dst, exist_ok=True); shutil.copyfile(src, os.path.join(dst, str(f).replace("/", "_"))); copied.append(str(f))
    rows.append(dict(name=name, version=d.version, license=lic, home=m.get("Home-page") or (m.get_all("Project-URL") or [""])[0], files=copied))
print(json.dumps(dict(python=sys.version, packages=rows), indent=1))
`;

function pruneSitePackages() {
  const pyRoot = path.join(OUT, 'python');
  const lib = isWin ? path.join(pyRoot, 'Lib') : path.join(pyRoot, 'lib', `python${lock.python.version.split('.').slice(0, 2).join('.')}`);
  const site = path.join(lib, 'site-packages');
  for (const p of ['pip', 'setuptools', '_distutils_hack']) rmrf(path.join(site, p));
  for (const e of fs.readdirSync(site)) if (/^(pip|setuptools)-.*\.dist-info$/.test(e)) rmrf(path.join(site, e));
  // stdlib parts the engine never uses
  for (const p of ['test', 'idlelib', 'turtledemo', 'tkinter', 'ensurepip', 'lib2to3', 'pydoc_data']) rmrf(path.join(lib, p));
  if (!isWin) {
    rmrf(path.join(pyRoot, 'include'));
    rmrf(path.join(pyRoot, 'share'));
    const bin = path.join(pyRoot, 'bin');
    for (const e of fs.readdirSync(bin)) if (!/^python3(\.\d+)?$/.test(e)) rmrf(path.join(bin, e));
    for (const tk of fs.readdirSync(path.join(pyRoot, 'lib'))) if (/^(tcl|tk|itcl|thread)\d/.test(tk) || /^lib(tcl|tk)/.test(tk)) rmrf(path.join(pyRoot, 'lib', tk));
  } else {
    rmrf(path.join(pyRoot, 'Scripts'));
    rmrf(path.join(pyRoot, 'include'));
    rmrf(path.join(pyRoot, 'tcl'));
  }
  // heavy test suites inside wheels
  walk(site, (p, ent) => {
    // C headers (mlx/include, numpy/_core/include, ...) are only for building extensions
    const drop = ent.name === '__pycache__' || ent.name === 'tests' || (ent.name === 'include' && path.dirname(p) !== site && !p.includes(`${path.sep}mlx${path.sep}`));
    if (ent.isDirectory() && drop) {
      rmrf(p);
      return false;
    }
    return true;
  });
}

function walk(dir, fn) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (fn(p, ent) !== false && ent.isDirectory() && !ent.isSymbolicLink()) walk(p, fn);
  }
}

// ------------------------------------------------------------------ ffmpeg (LGPL, conda-forge)
async function buildFfmpeg() {
  const mm = await micromamba(lock);
  const prefix = path.join(CACHE, `ffenv-${target}`);
  const explicit = path.join(ROOT, 'packaging', 'ffmpeg', `${target}.txt`);
  const stamp = path.join(prefix, '.lock-copy');
  if (!fs.existsSync(stamp) || fs.readFileSync(stamp, 'utf8') !== fs.readFileSync(explicit, 'utf8')) {
    rmrf(prefix);
    run(mm, ['create', '--yes', '--quiet', '--prefix', prefix, '--platform', T.conda, '--file', explicit],
      { env: { ...process.env, MAMBA_ROOT_PREFIX: path.join(CACHE, 'mamba'), CONDA_OVERRIDE_OSX: T.macosMin ?? '' } });
    fs.copyFileSync(explicit, stamp);
  }
  const dst = path.join(OUT, 'ffmpeg');
  rmrf(dst);
  let closure;
  if (isMac) {
    fs.mkdirSync(path.join(dst, 'bin'), { recursive: true });
    fs.mkdirSync(path.join(dst, 'lib'), { recursive: true });
    for (const b of ['ffmpeg', 'ffprobe']) fs.copyFileSync(path.join(prefix, 'bin', b), path.join(dst, 'bin', b));
    closure = machoClosure(prefix, ['bin/ffmpeg', 'bin/ffprobe']);
    for (const rel of closure) fs.copyFileSync(fs.realpathSync(path.join(prefix, rel)), path.join(dst, 'lib', path.basename(rel)));
    for (const b of ['ffmpeg', 'ffprobe']) fs.chmodSync(path.join(dst, 'bin', b), 0o755);
  } else {
    fs.mkdirSync(path.join(dst, 'bin'), { recursive: true });
    const bin = path.join(prefix, 'Library', 'bin');
    closure = peClosure(bin, ['ffmpeg.exe', 'ffprobe.exe']);
    for (const f of closure) fs.copyFileSync(path.join(bin, f), path.join(dst, 'bin', f));
    closure = closure.map((f) => `Library/bin/${f}`);
  }
  ffmpegLicenses(prefix, closure, isMac ? ['bin/ffmpeg', 'bin/ffprobe'] : []);
}

function ffmpegLicenses(prefix, files, extraRoots) {
  const want = new Set([...files, ...extraRoots].map((f) => f.replaceAll('\\', '/')));
  const metaDir = path.join(prefix, 'conda-meta');
  const rows = [];
  for (const f of fs.readdirSync(metaDir).filter((x) => x.endsWith('.json'))) {
    const m = JSON.parse(fs.readFileSync(path.join(metaDir, f), 'utf8'));
    const owned = (m.files ?? []).map((x) => x.replaceAll('\\', '/'));
    const used = owned.filter((x) => want.has(x));
    if (!used.length) continue;
    const licSrc = path.join(m.extracted_package_dir ?? path.join(CACHE, 'mamba', 'pkgs', f.replace(/\.json$/, '')), 'info', 'licenses');
    const licDst = path.join(OUT, 'licenses', 'ffmpeg', m.name);
    if (fs.existsSync(licSrc)) fs.cpSync(licSrc, licDst, { recursive: true });
    rows.push({ name: m.name, version: m.version, build: m.build, license: m.license, url: m.url, files: used.length });
  }
  rows.sort((a, b) => a.name.localeCompare(b.name));
  fs.writeFileSync(path.join(OUT, 'licenses', 'ffmpeg-components.json'), JSON.stringify(rows, null, 1) + '\n');
  // flag a component only if every alternative of its licence expression is (non-L)GPL
  const gpl = rows.filter((r) => (r.license ?? '').split(/\s+OR\s+/i).every((alt) => /(^|[^L])GPL/.test(alt)));
  if (gpl.length) log('WARNING: GPL-licensed components in the ffmpeg closure:', gpl.map((r) => `${r.name} (${r.license})`).join(', '));
}

// ------------------------------------------------------------------ vstudio (pinned commit)
async function buildVstudio() {
  const { commit, include, exclude } = lock.vstudio;
  const tgz = await download(`https://codeload.github.com/zyziyun/video-studio/tar.gz/${commit}`, path.join(CACHE, `video-studio-${commit}.tar.gz`));
  const tmp = path.join(CACHE, `vstudio-${commit}`);
  rmrf(tmp);
  fs.mkdirSync(tmp, { recursive: true });
  run(TAR, ['-xzf', tgz, '-C', tmp, '--strip-components=1']);
  const dst = path.join(OUT, 'vstudio');
  rmrf(dst);
  fs.mkdirSync(dst, { recursive: true });
  const drop = new Set(exclude);
  for (const e of include) {
    fs.cpSync(path.join(tmp, e), path.join(dst, e), { recursive: true, filter: (src) => !drop.has(path.basename(src)) });
  }
  fs.writeFileSync(path.join(dst, 'COMMIT'), commit + '\n');
  fs.copyFileSync(path.join(tmp, 'LICENSE'), path.join(OUT, 'licenses', 'video-studio-LICENSE.txt'));
}

// ------------------------------------------------------------------ checks
function verify() {
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => k.toUpperCase() !== 'PATH'));
  const sysPath = Object.entries(process.env).find(([k]) => k.toUpperCase() === 'PATH')?.[1] ?? '';
  Object.assign(env, { PYTHONPATH: path.join(OUT, 'vstudio', 'lib'), PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1',
    PATH: [path.join(OUT, 'ffmpeg', 'bin'), sysPath].join(path.delimiter), VSTUDIO_CACHE: path.join(CACHE, 'vstudio-cache-check') });
  const asr = isMac && target.endsWith('arm64') ? 'mlx_whisper' : 'faster_whisper';
  run(pyExe(), ['-c', `import numpy, scipy, cv2, mediapipe, soundfile, yaml, PIL, fontTools, openai, ${asr}, vstudio.batch, vstudio.media as m; ` +
    `import shutil; ff = m.ffmpeg_bin(); assert ff.startswith(${JSON.stringify(path.join(OUT, 'ffmpeg'))}), ff; print('ok', ff, '${asr}')`], { env });
  const enc = run(path.join(OUT, 'ffmpeg', 'bin', isWin ? 'ffmpeg.exe' : 'ffmpeg'), ['-hide_banner', '-encoders'], { capture: true });
  if (!enc.includes(T.h264)) throw new Error(`bundled ffmpeg lacks ${T.h264}`);
  if (/libx264|libx265/.test(enc)) throw new Error('bundled ffmpeg contains GPL encoders');
  if (isMac) checkMachO();
}

// Everything Mach-O must be either *.so / *.dylib or one of the known executables: the electron-builder
// signIgnore pattern (electron-builder.yml) skips every other file under runtime/ to keep signing fast.
function checkMachO() {
  const allowed = /(\.so|\.dylib)$|\/python\/bin\/python3\.\d+$|\/ffmpeg\/bin\/ff(mpeg|probe)$/;
  const bad = [];
  walk(OUT, (p, ent) => {
    if (ent.isFile() && !ent.isSymbolicLink() && !allowed.test(p)) {
      const fd = fs.openSync(p, 'r');
      const b = Buffer.alloc(4);
      fs.readSync(fd, b, 0, 4, 0);
      fs.closeSync(fd);
      const magic = b.readUInt32BE(0);
      if ([0xcffaedfe, 0xcefaedfe, 0xcafebabe, 0xfeedfacf, 0xfeedface].includes(magic) && !p.endsWith('.class')) bad.push(path.relative(OUT, p));
    }
    return true;
  });
  if (bad.length) throw new Error(`Mach-O files outside the signing pattern (update checkMachO + signIgnore):\n  ${bad.join('\n  ')}`);
}

function manifest() {
  const m = {
    target,
    python: lock.python.version,
    pbsRelease: lock.python.release,
    vstudioCommit: lock.vstudio.commit,
    ffmpeg: lock.ffmpeg.spec,
    h264Encoder: T.h264,
    asr: isMac && target.endsWith('arm64') ? 'mlx-whisper' : 'faster-whisper',
    builtAt: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(OUT, 'runtime.json'), JSON.stringify(m, null, 1) + '\n');
}

if (!skip.has('vstudio')) await buildVstudio();
if (!skip.has('python')) await buildPython();
if (!skip.has('ffmpeg')) await buildFfmpeg();
manifest();
if (!skip.has('verify')) verify();
log(`runtime ready: ${OUT}`);
