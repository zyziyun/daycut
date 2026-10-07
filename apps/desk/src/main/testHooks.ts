// Test / development hooks read from the environment. A packaged (signed) Reelfold must not let another local
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

export type DevOnlyHook = 'DESK_AI_MOCK' | 'DESK_PYTHON' | 'DESK_RUNTIME_DIR' | 'DESK_ASSETS_MANIFEST' | 'REELFOLD_USAGE_BASE';

export function devOnly(name: DevOnlyHook, env: NodeJS.ProcessEnv = process.env, packaged = packagedBuild): string | undefined {
  return packaged ? undefined : env[name] || undefined;
}

const real = (p: string) => {
  try {
    return fs.realpathSync.native(p); // .native: Windows 8.3 short names (RUNNER~1) become the long ones on both sides
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

/** Test switches (test engine, skip first run, hidden window, no PTY, no update checks). Dev builds: as set. A packaged
 * build honours them only for a throw-away test profile (DESK_USER_DATA inside the temp dir, as the packaged tests
 * use): an end user's Reelfold can never be switched into a hidden window by an environment variable. The test
 * engine (DESK_ENGINE_MOCK) is never started by a packaged build, whatever the profile: it is a test fixture under
 * engine/tests, which the app does not ship, and the packaged tests run the real bundled engine. */
export type TestSwitch = 'DESK_ENGINE_MOCK' | 'DESK_SKIP_FIRST_RUN' | 'DESK_HIDE_WINDOW' | 'DESK_NO_PTY' | 'DESK_DISABLE_UPDATES';

export function testSwitch(name: TestSwitch, env: NodeJS.ProcessEnv = process.env, packaged = packagedBuild, tmp = os.tmpdir()): boolean {
  if (env[name] !== '1') return false;
  if (!packaged) return true;
  if (name === 'DESK_ENGINE_MOCK') return false;
  return !!env.DESK_USER_DATA && tempOnly('DESK_USER_DATA', env, true, tmp) !== undefined;
}
