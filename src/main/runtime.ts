// The engine runtime shipped inside the app (resources/runtime, built by scripts/runtime/bundle.mjs): a relocatable
// Python with the pinned pip set, an LGPL ffmpeg and the video-studio library at a pinned commit.
import fs from 'node:fs';
import path from 'node:path';

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
  const root = env.DESK_RUNTIME_DIR || (isPackaged ? path.join(resourcesDir, 'runtime') : '');
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

/** Extra environment for an engine that runs on the bundled runtime. */
export function runtimeEnv(rt: BundledRuntime, shimDir: string, env = process.env) {
  return {
    env: {
      PYTHONNOUSERSITE: '1', // never mix in the user's own site-packages
      PYTHONDONTWRITEBYTECODE: '1', // the app bundle is read-only (and signed)
      DESK_H264_ENCODER: env.DESK_H264_ENCODER ?? rt.manifest.h264Encoder,
    },
    path: [rt.ffmpegBin],
    pythonPath: [shimDir], // sitecustomize: libx264 -> platform encoder
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
