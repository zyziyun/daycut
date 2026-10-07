// The engine runtime shipped inside the app (resources/runtime, built by scripts/runtime/bundle.mjs): a relocatable
// Python with the pinned pip set, an LGPL ffmpeg and the video-studio library at a pinned commit.
import fs from 'node:fs';
import path from 'node:path';
import { devOnly } from './testHooks';

export interface RuntimeManifest {
  target: string;
  python: string;
  vstudioCommit: string;
  ffmpeg: string;
  h264Encoder: string;
  asr: string;
  builtAt: string;
}

export interface BundledRuntime {
  root: string;
  python: string;
  ffmpegBin: string;
  vstudio: string;
  manifest: RuntimeManifest;
}

/** resources/runtime when packaged; in development only when DESK_RUNTIME_DIR points at a built runtime. */
export function findBundledRuntime(resourcesDir: string, isPackaged: boolean, env = process.env): BundledRuntime | null {
  const root = devOnly('DESK_RUNTIME_DIR', env, isPackaged) || (isPackaged ? path.join(resourcesDir, 'runtime') : '');
  if (!root) return null;
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(root, 'runtime.json'), 'utf8')) as RuntimeManifest;
    const win = manifest.target.startsWith('win32');
    const python = win ? path.join(root, 'python', 'python.exe') : path.join(root, 'python', 'bin', 'python3');
    const rt = { root, python, ffmpegBin: path.join(root, 'ffmpeg', 'bin'), vstudio: path.join(root, 'vstudio'), manifest };
    return fs.existsSync(python) && fs.existsSync(path.join(rt.vstudio, 'lib', 'vstudio')) ? rt : null;
  } catch {
    return null;
  }
}

/**
 * Extra environment for an engine that runs on the bundled runtime. The engine (video-studio >= eedca6c) owns the
 * H.264 encoder choice and the ffmpeg location: VSTUDIO_H264_ENCODER picks the encoder for every encode (with a
 * libx264 fallback when the encoder does not work on this machine) and VSTUDIO_FFMPEG / VSTUDIO_FFPROBE point it
 * at the bundled LGPL binaries. DESK_H264_ENCODER is still honoured as an override.
 */
export function runtimeEnv(rt: BundledRuntime, env = process.env) {
  const exe = rt.manifest.target.startsWith('win32') ? '.exe' : '';
  return {
    env: {
      PYTHONNOUSERSITE: '1', // never mix in the user's own site-packages
      PYTHONDONTWRITEBYTECODE: '1', // the app bundle is read-only (and signed)
      VSTUDIO_H264_ENCODER: env.VSTUDIO_H264_ENCODER || env.DESK_H264_ENCODER || rt.manifest.h264Encoder,
      VSTUDIO_FFMPEG: path.join(rt.ffmpegBin, `ffmpeg${exe}`),
      VSTUDIO_FFPROBE: path.join(rt.ffmpegBin, `ffprobe${exe}`),
    },
    path: [rt.ffmpegBin],
  };
}

/** Set PATH (whatever its case on Windows) to `dirs` + the old value. */
export function prependPath(env: NodeJS.ProcessEnv, dirs: string[]): NodeJS.ProcessEnv {
  const key = Object.keys(env).find((k) => k.toUpperCase() === 'PATH') ?? 'PATH';
  const old = env[key] ?? '';
  const out = { ...env };
  for (const k of Object.keys(out)) if (k.toUpperCase() === 'PATH') delete out[k];
  out[key] = [...dirs.filter(Boolean), old].filter(Boolean).join(path.delimiter);
  return out;
}
