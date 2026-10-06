// Runs the real assisted fill (B站 adapter plan + CDP executor) against a local fixture page whose fields live in an
// open shadow root, in a hidden Electron window; prints the result as JSON. Used by cdp.spec.ts; no real site.
import path from 'node:path';
import { app, BrowserWindow } from 'electron';
import { runFill } from '../../src/main/publish/cdpFill';
import { parseAdapter } from '../../src/shared/publish/adapterSchema';
import { planFill } from '../../src/shared/publish/fillPlan';
import bilibili from '../../adapters/bilibili.json';

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  const [dir, video, cover] = process.argv.slice(-3);
  await win.loadFile(path.join(dir, 'shadow-upload.html'));
  const a = parseAdapter(bilibili);
  if (!a.ok) throw new Error(a.error);
  const steps = planFill(a.adapter, {
    videoPath: video,
    coverPath: cover,
    copy: { title: '第 1 集：批量剪口播', description: '第一行\n第二行', tags: ['口播', '剪辑', 'AI'] },
  }).map((s) => ({ ...s, timeoutMs: 5000 }));
  const dbg = win.webContents.debugger;
  dbg.attach('1.3');
  const results = await runFill((m, p) => dbg.sendCommand(m, p), steps);
  dbg.detach();
  const page = await win.webContents.executeJavaScript('window.__read()');
  process.stdout.write('RESULT ' + JSON.stringify({ results, page }) + '\n');
  app.exit(0);
}).catch((e) => {
  process.stdout.write('ERROR ' + String(e) + '\n');
  app.exit(1);
});
