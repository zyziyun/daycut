// Runs the real assisted-fill code (plan + CDP executor + webContents.debugger) against a local fixture page in
// a hidden Electron window and prints the result as JSON. Used by cdp.spec.ts; never touches a real site.
import path from 'node:path';
import { app, BrowserWindow } from 'electron';
import { runFill } from '../../src/main/publish/cdpFill';
import { parseAdapter } from '../../src/shared/publish/adapterSchema';
import { planFill } from '../../src/shared/publish/fillPlan';
import tiktok from '../../adapters/tiktok.json';

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await win.loadFile(path.join(process.argv[process.argv.length - 2], 'upload.html'));
  const a = parseAdapter(tiktok);
  if (!a.ok) throw new Error(a.error);
  const steps = planFill(a.adapter, {
    videoPath: process.argv[process.argv.length - 1],
    copy: { title: '', description: '第一行\n第二行', tags: ['口播', '剪辑'] },
  }).map((s) => ({ ...s, timeoutMs: 5000 }));
  const dbg = win.webContents.debugger;
  dbg.attach('1.3');
  const results = await runFill((m, p) => dbg.sendCommand(m, p), steps);
  dbg.detach();
  const page = await win.webContents.executeJavaScript(
    `({ file: window.__fileName, caption: document.querySelector('.public-DraftEditor-content').innerText, clicked: window.__clicked, active: document.activeElement && document.activeElement.className, outline: document.querySelector('[data-e2e=post_video_button]').style.outline })`,
  );
  process.stdout.write('RESULT ' + JSON.stringify({ results, page }) + '\n');
  app.exit(0);
}).catch((e) => {
  process.stdout.write('ERROR ' + String(e) + '\n');
  app.exit(1);
});
