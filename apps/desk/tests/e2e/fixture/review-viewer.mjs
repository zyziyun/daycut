// Opens a shared review page (file://) in a plain Electron window for tests/e2e/share.spec.ts: every request that
// is not file: / blob: / data: is cancelled and recorded (the page must work offline and phone nowhere).
import { app, BrowserWindow, session } from 'electron';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

// a fresh profile per run: the page keeps answers in localStorage, keyed by the (deterministic) share id
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'review-viewer-')));

const net = [];
globalThis.__reviewNet = net;
app.whenReady().then(() => {
  session.defaultSession.webRequest.onBeforeRequest((d, cb) => {
    if (/^(file|blob|data|devtools|chrome-extension):/.test(d.url)) return cb({});
    net.push(d.url);
    cb({ cancel: true });
  });
  const w = new BrowserWindow({ show: process.env.REVIEW_SHOW === '1', width: 1280, height: 900, webPreferences: { sandbox: true } });
  void w.loadFile(process.env.REVIEW_PAGE);
});
app.on('window-all-closed', () => app.quit());
