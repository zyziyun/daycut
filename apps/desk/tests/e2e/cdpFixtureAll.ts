// Runs the real assisted-fill code (copyForPlatform + planFill + the CDP executor over webContents.debugger) for
// every fillable adapter against a local mock of its upload form (tests/e2e/fixture/mocks/<adapter>.html) in
// hidden Electron windows; optionally screenshots each filled mock. Prints RESULT {adapterId: {results, page}}.
//   electron fixtureAll.cjs <mocksDir> <video> <cover> <post.md> <title> <screenshotDir | ->
import fs from 'node:fs';
import path from 'node:path';
import { app, BrowserWindow } from 'electron';
import { runFill } from '../../src/main/publish/cdpFill';
import { parseAdapter, type Adapter } from '../../src/shared/publish/adapterSchema';
import { planFill } from '../../src/shared/publish/fillPlan';
import { copyForPlatform } from '../../src/shared/publish/postCopy';
import bilibili from '../../adapters/bilibili.json';
import instagram from '../../adapters/instagram.json';
import tiktok from '../../adapters/tiktok.json';
import wechat from '../../adapters/wechat-channels.json';
import x from '../../adapters/x.json';
import youtube from '../../adapters/youtube-studio.json';
import xiaohongshu from '../../adapters/xiaohongshu.json';
import douyin from '../../adapters/douyin.json';
import { CAPTURE_JS } from '../../src/main/publish/capture';

const [mocks, video, cover, postMd, title, shotArg] = process.argv.slice(-6);
const shots = shotArg === '-' ? '' : shotArg;
const MOCK: Record<string, string> = { bilibili: 'bilibili', instagram: 'instagram', tiktok: 'tiktok', 'wechat-channels': 'wechat-channels', 'x-web': 'x', 'youtube-studio': 'youtube-studio', xiaohongshu: 'xiaohongshu', douyin: 'douyin' };

app.on('window-all-closed', () => undefined);
app.whenReady().then(async () => {
  app.dock?.hide();
  const md = fs.readFileSync(postMd, 'utf8');
  const out: Record<string, unknown> = {};
  for (const raw of [bilibili, instagram, tiktok, wechat, x, youtube, xiaohongshu, douyin]) {
    const r = parseAdapter(raw);
    if (!r.ok) throw new Error(r.error);
    const a: Adapter = r.adapter;
    const win = new BrowserWindow({ show: false, width: 1200, height: 800, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
    await win.loadFile(path.join(mocks, `${MOCK[a.id]}.html`));
    const copy = copyForPlatform(md, title, a.fields.title !== null);
    const steps = planFill(a, { videoPath: video, coverPath: cover, copy }).map((s) => ({ ...s, timeoutMs: Math.min(s.timeoutMs, 4000) }));
    const dbg = win.webContents.debugger;
    dbg.attach('1.3');
    const sent: string[] = [];
    const results = await runFill((m, p) => (sent.push(m), dbg.sendCommand(m, p)), steps);
    dbg.detach();
    const page = await win.webContents.executeJavaScript('window.__state()');
    // the developer "Capture this page" snapshot of the filled page (what a creator would send to tune selectors)
    if (a.id === 'xiaohongshu' || a.id === 'douyin') page.capture = ((await win.webContents.executeJavaScriptInIsolatedWorld(1003, [{ code: CAPTURE_JS }])) as { html: string }).html;
    if (shots) fs.writeFileSync(path.join(shots, `mock-${a.id}.png`), (await win.webContents.capturePage()).toPNG());
    out[a.id] = { results, page, methods: [...new Set(sent)] };
    win.destroy();
  }
  process.stdout.write('RESULT ' + JSON.stringify(out) + '\n');
  app.exit(0);
}).catch((e) => {
  process.stdout.write('ERROR ' + String(e?.stack ?? e) + '\n');
  app.exit(1);
});
