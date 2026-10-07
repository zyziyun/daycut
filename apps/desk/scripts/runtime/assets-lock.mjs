// Generate packaging/assets.json: the large assets the app downloads on first run (not shipped in the installer),
// each with a pinned URL, size and sha256. Small files are downloaded and hashed here; Hugging Face LFS files use
// the LFS sha256 from the API (no 1.6 GB download needed). Chromium zips are downloaded once to hash them.
//   node scripts/runtime/assets-lock.mjs [--skip-chromium]
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { CACHE, download, log, ROOT, sha256File } from './common.mjs';

const PINS = {
  notoCjk: 'f8d157532fbfaeda587e826d4cd5b21a49186f7c',
  googleFonts: '7085eb89a950e85db5b166b7a58d414544b4140c',
  jetbrainsMono: '19371302b95d218af43299bce79ddbddd0bc364d',
  mlxWhisper: { repo: 'mlx-community/whisper-large-v3-turbo', rev: 'a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb' },
  fasterWhisper: { repo: 'dropbox-dash/faster-whisper-large-v3-turbo', rev: '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf' },
  chromium: { 'darwin-arm64': ['Mac_Arm', 1712143, 'chrome-mac.zip'], 'darwin-x64': ['Mac', 1712146, 'chrome-mac.zip'], 'win32-x64': ['Win_x64', 1712024, 'chrome-win.zip'] },
};
const skipChromium = process.argv.includes('--skip-chromium');
const prev = (() => {
  try {
    return JSON.parse(fs.readFileSync(path.join(ROOT, 'packaging', 'assets.json'), 'utf8'));
  } catch {
    return null;
  }
})();

async function hashUrl(url) {
  const f = path.join(CACHE, 'assets', crypto.createHash('sha1').update(url).digest('hex'));
  await download(url, f);
  return { sha256: sha256File(f), size: fs.statSync(f).size };
}

async function file(url, dest) {
  return { url, dest, ...(await hashUrl(url)) };
}

async function hf({ repo, rev }, dir, names) {
  const tree = await (await fetch(`https://huggingface.co/api/models/${repo}/tree/${rev}`)).json();
  const out = [];
  for (const name of names) {
    const ent = tree.find((x) => x.path === name);
    if (!ent) throw new Error(`${repo}@${rev} has no ${name}`);
    const url = `https://huggingface.co/${repo}/resolve/${rev}/${name}`;
    out.push(ent.lfs ? { url, dest: `${dir}/${name}`, sha256: ent.lfs.oid, size: ent.size } : await file(url, `${dir}/${name}`));
  }
  return out;
}

const raw = (repo, sha, p) => `https://raw.githubusercontent.com/${repo}/${sha}/${p}`;
const fonts = [
  ['notofonts/noto-cjk', PINS.notoCjk, 'Sans/SubsetOTF/SC/NotoSansSC-Regular.otf', 'NotoSansSC-Regular.otf'],
  ['notofonts/noto-cjk', PINS.notoCjk, 'Sans/SubsetOTF/SC/NotoSansSC-Bold.otf', 'NotoSansSC-Bold.otf'],
  ['notofonts/noto-cjk', PINS.notoCjk, 'Serif/SubsetOTF/SC/NotoSerifSC-Regular.otf', 'NotoSerifSC-Regular.otf'],
  ['notofonts/noto-cjk', PINS.notoCjk, 'Serif/SubsetOTF/SC/NotoSerifSC-Bold.otf', 'NotoSerifSC-Bold.otf'],
  ['google/fonts', PINS.googleFonts, 'ofl/stixtwotext/STIXTwoText%5Bwght%5D.ttf', 'STIXTwoText-Regular.ttf'],
  ['google/fonts', PINS.googleFonts, 'ofl/stixtwotext/STIXTwoText-Italic%5Bwght%5D.ttf', 'STIXTwoText-Italic.ttf'],
  ['JetBrains/JetBrainsMono', PINS.jetbrainsMono, 'fonts/ttf/JetBrainsMono-Regular.ttf', 'JetBrainsMono-Regular.ttf'],
  ['JetBrains/JetBrainsMono', PINS.jetbrainsMono, 'fonts/ttf/JetBrainsMono-Bold.ttf', 'JetBrainsMono-Bold.ttf'],
];
const MP = 'https://storage.googleapis.com/mediapipe-models';
const models = [
  [`${MP}/face_landmarker/face_landmarker/float16/1/face_landmarker.task`, 'face_landmarker.task'],
  [`${MP}/image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite`, 'selfie_segmenter.tflite'],
  [`${MP}/image_segmenter/selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite`, 'selfie_multiclass_256x256.tflite'],
];

const groups = [];
log('fonts + models');
groups.push({
  id: 'core',
  required: true,
  root: 'vstudio-cache',
  licence: 'Fonts: SIL OFL 1.1 (Noto CJK, STIX Two, JetBrains Mono). Models: Apache-2.0 (Google MediaPipe).',
  files: [
    ...(await Promise.all(fonts.map(([r, s, p, n]) => file(raw(r, s, p), `fonts/${n}`)))),
    ...(await Promise.all(models.map(([u, n]) => file(u, `models/${n}`)))),
  ],
});
log('whisper');
groups.push({
  id: 'asr-mlx',
  required: true,
  targets: ['darwin-arm64'],
  root: 'models/whisper-large-v3-turbo-mlx',
  env: { VSTUDIO_WHISPER_MLX: '' },
  licence: 'OpenAI Whisper large-v3-turbo weights, MIT (MLX conversion by mlx-community).',
  files: await hf(PINS.mlxWhisper, '.', ['config.json', 'weights.safetensors']),
});
groups.push({
  id: 'asr-ct2',
  required: true,
  targets: ['darwin-x64', 'win32-x64'],
  root: 'models/whisper-large-v3-turbo-ct2',
  env: { VSTUDIO_WHISPER_FW: '' },
  licence: 'OpenAI Whisper large-v3-turbo weights, MIT (CTranslate2 conversion).',
  files: await hf(PINS.fasterWhisper, '.', ['config.json', 'model.bin', 'preprocessor_config.json', 'tokenizer.json', 'vocabulary.json']),
});
for (const [target, [dir, rev, zip]] of Object.entries(PINS.chromium)) {
  const url = `https://storage.googleapis.com/chromium-browser-snapshots/${dir}/${rev}/${zip}`;
  const old = prev?.groups.find((g) => g.id === `chromium-${target}`)?.files[0];
  let f;
  if (old?.url === url) f = old;
  else if (skipChromium) continue;
  else {
    log('chromium', target, url);
    f = { url, dest: zip, ...(await hashUrl(url)) };
  }
  groups.push({
    id: `chromium-${target}`,
    required: false,
    targets: [target],
    root: `chromium/${rev}`,
    extract: true,
    env: { CHROME: target.startsWith('win32') ? 'chrome-win/chrome.exe' : 'chrome-mac/Chromium.app/Contents/MacOS/Chromium' },
    licence: 'Chromium, BSD-3-Clause and third-party licences (chrome://credits). Used for HTML covers/slides and HyperFrames.',
    files: [f],
  });
}

const out = { $comment: 'Generated by scripts/runtime/assets-lock.mjs. Downloaded on first run into the app data dir; every file is sha256-checked.', groups };
fs.writeFileSync(path.join(ROOT, 'packaging', 'assets.json'), JSON.stringify(out, null, 1) + '\n');
log('wrote packaging/assets.json', groups.map((g) => `${g.id}:${(g.files.reduce((a, f) => a + f.size, 0) / 1e6).toFixed(0)}MB`).join(' '));
