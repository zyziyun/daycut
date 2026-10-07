// Test / development hooks read from the environment. A packaged (signed) Daycut must not let another local
// process steer it into running other code or loading other files through them, so:
//   - devOnly(): ignored in packaged builds (commands for the login terminal, another Python / runtime, another
//     asset manifest);
//   - tempOnly(): packaged builds accept only a folder inside the system temp dir (the packaged tests' isolated
//     caches), never a user / system folder.
// index.ts calls setPackaged(app.isPackaged) first thing (this module stays free of electron for unit tests).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let packagedBuild = false;
export function setPackaged(p: boolean) {
  packagedBuild = p;
}
export function isPackagedBuild() {
  return packagedBuild;
}

export type DevOnlyHook = 'DESK_AI_MOCK' | 'DESK_PYTHON' | 'DESK_RUNTIME_DIR' | 'DESK_ASSETS_MANIFEST';

export function devOnly(name: DevOnlyHook, env: NodeJS.ProcessEnv = process.env, packaged = packagedBuild): string | undefined {
  return packaged ? undefined : env[name] || undefined;
}

const real = (p: string) => {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
};

/** '' stays '' (an explicit "none"); a packaged build drops anything outside the temp dir. */
export function tempOnly(name: string, env: NodeJS.ProcessEnv = process.env, packaged = packagedBuild, tmp = os.tmpdir()): string | undefined {
  const v = env[name];
  if (v === undefined || v === '' || !packaged) return v;
  const rel = path.relative(real(tmp), real(v));
  return rel && !rel.startsWith('..') && !path.isAbsolute(rel) ? v : undefined;
}
