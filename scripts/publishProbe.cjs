/* eslint-disable @typescript-eslint/no-require-imports */
// Publish-page reachability probe (manual tool, not part of the test suite; it opens the real platform sites).
// For every adapter: a hidden window in a TEMPORARY in-memory partition (no `persist:`; nothing is kept), load the
// upload URL, wait, record the final URL / title / HTTP status / "unsupported browser" wording, screenshot it.
// Nothing is typed, nothing is clicked, no login. Runs twice: Electron's default user agent and the publish
// browser's cleaned one (the same Chrome version without the app / Electron tokens, see src/main/publish/ua.ts).
//   npx electron scripts/publishProbe.cjs <outDir> [adapterId,...]
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { app, BrowserWindow, session } = require('electron');

app.setName('vsdesk-publish-probe');
app.on('window-all-closed', () => undefined); // keep running between probes
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-probe-')));
const out = path.resolve(process.argv[2] || '/tmp/vsdesk-probe');
const only = (process.argv[3] || '').split(',').filter(Boolean);
fs.mkdirSync(out, { recursive: true });
const adir = path.join(__dirname, '..', 'adapters');
const adapters = fs
  .readdirSync(adir)
  .filter((f) => f.endsWith('.json'))
  .map((f) => JSON.parse(fs.readFileSync(path.join(adir, f), 'utf8')))
  .filter((a) => !only.length || only.includes(a.id));

// same rule as src/main/publish/ua.ts cleanUserAgent (tested in tests/unit/channels.test.ts)
function cleanUa(ua) {
  return ua
    .replace(/\s+Electron\/\S+/g, '')
    .replace(/(\(KHTML, like Gecko\))[^()]*?(?=\s+Chrome\/)/, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

const BLOCK_WORDS = /unsupported browser|browser (is|isn't|is not) supported|not supported in this browser|update your browser|浏览器版本过低|不支持.*浏览器|请使用.*浏览器|switch to a supported browser|This browser or app may not be secure/i;
const LOGIN_WORDS = /log ?in|sign ?in|登录|扫码|login|passport|accounts\.google/i;
const log = (l) => fs.appendFileSync(path.join(out, 'probe.log'), l + '\n');
process.on('uncaughtException', (e) => log(`ERROR ${e && e.stack}`));
process.on('unhandledRejection', (e) => log(`ERROR ${e && e.stack}`));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function probe(a, mode) {
  const ses = session.fromPartition(`probe-${a.id}-${mode}-${Date.now()}`); // no persist: -> in memory only
  ses.setPermissionRequestHandler((_w, _p, cb) => cb(false));
  ses.on('will-download', (e) => e.preventDefault());
  const ua = mode === 'electron' ? ses.getUserAgent() : cleanUa(ses.getUserAgent());
  ses.setUserAgent(ua);
  const win = new BrowserWindow({ show: false, width: 1440, height: 900, webPreferences: { session: ses, sandbox: true, contextIsolation: true, nodeIntegration: false } });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-prevent-unload', (e) => e.preventDefault());
  const redirects = [];
  let status = null;
  win.webContents.on('did-redirect-navigation', (_e, url) => redirects.push(url));
  win.webContents.on('did-navigate', (_e, url, code) => {
    redirects.push(url);
    status = code;
  });
  let loadError = null;
  try {
    await Promise.race([win.loadURL(a.uploadUrl), sleep(40000)]);
  } catch (e) {
    loadError = String(e.message || e).slice(0, 200);
  }
  await sleep(9000); // SPA redirects to the login page happen after load
  const wc = win.webContents;
  let text = '';
  let hasFile = false;
  try {
    text = await wc.executeJavaScript('document.body ? document.body.innerText.slice(0, 4000) : ""', true);
    hasFile = await wc.executeJavaScript('!!document.querySelector("input[type=file]")', true);
  } catch {
    /* page gone */
  }
  const img = await wc.capturePage();
  const file = path.join(out, `${a.id}-${mode}.png`);
  fs.writeFileSync(file, img.toPNG());
  const finalUrl = wc.getURL();
  const r = {
    id: a.id,
    mode,
    ua,
    uploadUrl: a.uploadUrl,
    finalUrl,
    status,
    title: wc.getTitle(),
    loadError,
    redirects: [...new Set(redirects)].slice(0, 8),
    login: LOGIN_WORDS.test(new URL(finalUrl || a.uploadUrl).pathname + ' ' + new URL(finalUrl || a.uploadUrl).hostname) || LOGIN_WORDS.test(text.slice(0, 600)),
    blockedText: (text.match(BLOCK_WORDS) || [null])[0],
    fileInput: hasFile,
    textSample: text.replace(/\s+/g, ' ').slice(0, 300),
    screenshot: file,
  };
  win.destroy();
  await ses.clearStorageData().catch(() => undefined);
  return r;
}

app.whenReady().then(async () => {
  app.dock?.hide();
  const results = [];
  for (const a of adapters) {
    for (const mode of ['electron', 'clean']) {
      try {
        const r = await probe(a, mode);
        results.push(r);
        log(`PROBE ${JSON.stringify(r)}`);
      } catch (e) {
        results.push({ id: a.id, mode, error: String(e) });
        log(`PROBE ${JSON.stringify({ id: a.id, mode, error: String(e) })}`);
      }
    }
  }
  fs.writeFileSync(path.join(out, 'probe.json'), JSON.stringify(results, null, 1));
  app.exit(0);
});
