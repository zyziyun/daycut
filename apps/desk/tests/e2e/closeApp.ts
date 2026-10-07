// Close the app under test without the harness-only stall.
//
// Root cause (qa/BUGS.md BB-36): Playwright starts Electron with --inspect and closes it by evaluating `app.quit()`
// over that inspector connection, then waits for the evaluate to answer before it disconnects. The app quits in a few
// ms (before-quit -> will-quit -> quit -> exit), the answer never arrives, and Node's exit then waits for the attached
// debugger to disconnect (main thread polling in node::inspector). Under load the two wait on each other for
// 10-500 s: the e2e afterAll "timeout of 60000ms exceeded". Real users never run with a debugger attached.
//
// Here the quit is asked for without waiting on the quit itself, the app's own shutdown runs completely (all quit
// events, the engine is told to stop), and only the debugger wait that follows is cut.
import type { ElectronApplication } from '@playwright/test';

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const MARK = '__E2E_QUIT__';

export async function closeApp(app: ElectronApplication | undefined): Promise<void> {
  if (!app) return;
  const proc = app.process();
  if (proc.exitCode !== null || proc.signalCode !== null) return;
  const gone = new Promise<void>((r) => proc.once('exit', () => r()));
  const quitDone = new Promise<void>((r) => proc.stdout?.on('data', (d: Buffer) => d.toString().includes(MARK) && r()));
  await app
    .evaluate(({ app: a }, mark) => {
      a.once('quit', () => process.stdout.write(`${mark}\n`));
      setTimeout(() => a.quit(), 0); // answer this call first, then quit
    }, MARK)
    .catch(() => undefined);
  await Promise.race([quitDone, gone, sleep(15000)]);
  await Promise.race([gone, sleep(500)]); // without a debugger attached it would be gone by now
  if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL'); // only the debugger wait is left
  await Promise.race([gone, sleep(5000)]);
  await app.close().catch(() => undefined); // Playwright's bookkeeping (resolves at once: the process is gone)
}
