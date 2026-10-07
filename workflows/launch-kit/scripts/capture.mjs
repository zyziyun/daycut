#!/usr/bin/env node
/* global window, document, location, getComputedStyle */
// capture.mjs - record crisp, scripted interaction clips of your own app (Electron or a web URL) for a launch video.
//
//   node capture.mjs --shots shots.yaml|json --out DIR [--electron APP_DIR [--env K=V ...] [--env-json env.json]]
//                    [--url URL] [--size 1440x900] [--scale 2] [--fps 30] [--only id,id] [--format jpeg|png]
//
// Targets: --electron APP_DIR (Playwright _electron.launch; the window is driven hidden: Chromium keeps painting a
// hidden BrowserWindow, so the screencast still gets frames and nothing covers your screen) or --url URL (system
// Chrome via channel "chrome", else Playwright's bundled Chromium). --env K=V adds / overrides an env var of the
// Electron process (K= sets it empty); --env-json reads {K: V} JSON (null removes K from the inherited env).
//
// Recording: CDP Page.startScreencast (jpeg q95, or png) at size x scale device pixels (1440x900 @2 -> 2880x1800);
// frames arrive with their own timestamps when something repaints, and are laid onto a constant-fps timeline
// (each frame held until the next) -> H.264 yuv420p, crf 16, +faststart. A smooth fake cursor (arrow + click ripple)
// is injected with DOM / CSSOM only (works under strict CSPs: no inline <style>, no style attributes); every pointer
// move is eased; typing is per character with a human, jittered delay.
//
// Shot list (YAML or JSON):
//   shots:
//     - id: home-plan                # file name
//       title: Say it once           # for the storyboard
//       caption: One sentence in     # short kinetic caption (EN)
//       setup: [ ...actions ]        # run before recording starts (not recorded); `eval` allowed here only
//       actions: [ ...actions ]      # recorded
//       hold_after: 1.5              # seconds kept after the last action
// Actions (one key names the action; `pause` (ms, default 250) waits after it):
//   goto: "#/inbox" | URL            click: SEL          dblclick: SEL        hover: SEL      move: SEL
//   type: SEL, text: "...", clear: true, cps: 14        press: Enter [, on: SEL]
//   wait: ms                         waitFor: SEL [, timeout: ms, state: visible|hidden|attached]
//   scroll: SEL, dy: 400             focus: SEL (a region of interest, no click)      still: true (the poster frame)
//   drag: SEL, to: SEL               (press on one element, glide, release on another: text / range selection)
//   eval: "js in the page"   electron: "js in the main process ({app, BrowserWindow} in scope)"   sh: "shell command"
//                                    (these three in setup only; sh runs on this machine with the app's env, must exit 0)
// SEL: a Playwright selector; "testid=x" -> [data-testid="x"]. Optional on any SEL action: has_text, nth, at
// ([fx, fy] point inside the box, 0..1), timeout. "${NAME}" (upper case) in any string is replaced by that env var (--env /
// --env-json / the shell), so shot lists hold no machine-specific paths.
//
// Output DIR: <id>.mp4, <id>.png (still: the `still` action's moment, else the last frame) and shots.json:
//   {size: [W, H], scale, fps, shots: [{id, title, caption, file, still, w, h, duration,
//     focus: [{t, x, y, w, h, kind: click|type|focus}]}]}      (focus boxes normalised 0..1, t = seconds into the clip)
// Any action that fails or times out exits non-zero with the shot id and selector; nothing is skipped silently.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';

// ------------------------------------------------------------------ args
const argv = process.argv.slice(2);
const opt = (k, d) => {
  const i = argv.indexOf(`--${k}`);
  return i >= 0 ? argv[i + 1] : d;
};
const many = (k) => argv.flatMap((a, i) => (a === `--${k}` ? [argv[i + 1]] : []));
const die = (m) => {
  console.error(`capture: ${m}`);
  process.exit(1);
};
if (argv.includes('--help') || !opt('shots') || !opt('out')) {
  console.log(fs.readFileSync(new URL(import.meta.url), 'utf8').split('\n').filter((l) => l.startsWith('//')).map((l) => l.slice(3)).join('\n'));
  process.exit(argv.includes('--help') ? 0 : 1);
}
const [W, H] = (opt('size', '1440x900').match(/^(\d+)x(\d+)$/) ?? die('--size WxH')).slice(1).map(Number);
const SCALE = Number(opt('scale', '2'));
const FPS = Number(opt('fps', '30'));
const FORMAT = opt('format', 'jpeg');
const OUT = path.resolve(opt('out'));
const only = (opt('only', '') || '').split(',').filter(Boolean);
const electronDir = opt('electron');
const url = opt('url');
if (!!electronDir === !!url) die('pass exactly one of --electron APP_DIR or --url URL');

// ------------------------------------------------------------------ deps (resolved from here, then the cwd)
const reqs = [createRequire(import.meta.url), createRequire(path.join(process.cwd(), 'noop.js'))];
const load = async (names, why) => {
  for (const n of names)
    for (const r of reqs) {
      try {
        const m = await import(r.resolve(n));
        return m.default ? { ...m.default, ...m } : m; // CommonJS packages arrive as {default}
      } catch {
        /* next */
      }
    }
  die(`${why}: install one of ${names.join(' / ')} (npm i -D ${names[0]})`);
};
const pw = await load(['playwright', 'playwright-core', '@playwright/test'], 'Playwright is required');
const readShots = async (file) => {
  const txt = fs.readFileSync(file, 'utf8');
  if (/\.json$/i.test(file)) return JSON.parse(txt);
  const y = await load(['yaml', 'js-yaml'], 'a YAML parser is required for .yaml shot lists (or use JSON)');
  return (y.parse ?? y.load ?? y.default?.parse ?? y.default?.load)(txt);
};
if (spawnSync('ffmpeg', ['-version']).status !== 0) die('ffmpeg is required on PATH');

// ------------------------------------------------------------------ env + shot list
const env = { ...process.env };
for (const f of many('env-json')) for (const [k, v] of Object.entries(JSON.parse(fs.readFileSync(f, 'utf8')))) v === null ? delete env[k] : (env[k] = String(v));
for (const kv of many('env')) {
  const i = kv.indexOf('=');
  if (i < 1) die(`--env ${kv}: K=V`);
  env[kv.slice(0, i)] = kv.slice(i + 1);
}
const subst = (v) =>
  typeof v === 'string'
    ? v.replace(/\$\{([A-Z][A-Z0-9_]*)\}/g, (_, k) => env[k] ?? die(`\${${k}} in the shot list: no such env var`))
    : Array.isArray(v)
      ? v.map(subst)
      : v && typeof v === 'object'
        ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, subst(x)]))
        : v;
const doc = subst(await readShots(path.resolve(opt('shots'))));
const shots = (doc?.shots ?? []).filter((s) => !only.length || only.includes(s.id));
if (!shots.length) die('no shots (shots: [...] in the shot list, or --only matched nothing)');
for (const s of shots) if (!/^[a-z0-9][a-z0-9_-]*$/i.test(s.id ?? '')) die(`shot id "${s.id}": letters, digits, - and _ only`);
fs.mkdirSync(OUT, { recursive: true });

// ------------------------------------------------------------------ launch
let app = null;
let browser = null;
let page;
if (electronDir) {
  env.DESK_HIDE_WINDOW ??= '1'; // Reelfold's own "never show the window" hook; harmless for other apps
  app = await pw._electron.launch({ args: [path.resolve(electronDir)], env });
  page = await app.firstWindow();
  await app.evaluate(({ BrowserWindow }, [w, h]) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.webContents.setBackgroundThrottling(false);
    win.setContentSize(w, h);
  }, [W, H]);
} else {
  try {
    browser = await pw.chromium.launch({ channel: 'chrome', headless: true });
  } catch {
    browser = await pw.chromium.launch({ headless: true });
  }
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: SCALE });
  page = await ctx.newPage();
  await page.goto(url);
}
const cdp = await page.context().newCDPSession(page);
await cdp.send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: SCALE, mobile: false });
await page.addInitScript(cursorScript);
await page.evaluate(cursorScript).catch(() => undefined);

// ------------------------------------------------------------------ the fake cursor (CSSOM only: CSP-safe)
function cursorScript() {
  if (window.__capCursor) return;
  const make = () => {
    if (!document.body || document.getElementById('__cap_cursor')) return;
    const NS = 'http://www.w3.org/2000/svg';
    const c = document.createElement('div');
    c.id = '__cap_cursor';
    Object.assign(c.style, { position: 'fixed', left: '0px', top: '0px', width: '26px', height: '26px', zIndex: '2147483647', pointerEvents: 'none', transform: 'translate(-200px,-200px)', willChange: 'transform', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.45))' });
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '26');
    svg.setAttribute('height', '26');
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', 'M3 2 L3 19.5 L7.6 15.4 L10.6 22 L13.6 20.7 L10.7 14.2 L17 14.2 Z');
    p.setAttribute('fill', '#ffffff');
    p.setAttribute('stroke', '#111111');
    p.setAttribute('stroke-width', '1.4');
    p.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(p);
    c.appendChild(svg);
    document.body.appendChild(c);
    window.__capCursor = c;
  };
  window.__capCursor = null;
  const pos = { x: -200, y: -200 };
  const place = (x, y) => {
    pos.x = x;
    pos.y = y;
    make();
    const c = document.getElementById('__cap_cursor');
    if (c) c.style.transform = `translate(${x - 3}px,${y - 2}px)`;
  };
  window.addEventListener('mousemove', (e) => place(e.clientX, e.clientY), true);
  window.addEventListener(
    'mousedown',
    (e) => {
      const r = document.createElement('div');
      Object.assign(r.style, { position: 'fixed', left: `${e.clientX - 22}px`, top: `${e.clientY - 22}px`, width: '44px', height: '44px', borderRadius: '50%', border: '2px solid rgba(255,255,255,.9)', background: 'rgba(255,255,255,.18)', zIndex: '2147483646', pointerEvents: 'none' });
      document.body.appendChild(r);
      r.animate([{ transform: 'scale(.3)', opacity: 1 }, { transform: 'scale(1.25)', opacity: 0 }], { duration: 520, easing: 'cubic-bezier(.2,.7,.3,1)' }).onfinish = () => r.remove();
      const c = document.getElementById('__cap_cursor');
      c?.animate([{ scale: '1' }, { scale: '.86' }, { scale: '1' }], { duration: 220 });
    },
    true,
  );
  new MutationObserver(() => !document.getElementById('__cap_cursor') && document.body && place(pos.x, pos.y)).observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState !== 'loading') make();
  else document.addEventListener('DOMContentLoaded', make);
}

// ------------------------------------------------------------------ recording
const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'capture-'));
let rec = null; // {dir, frames: [{file, ts}], t0}
let frameNo = 0;
cdp.on('Page.screencastFrame', async (f) => {
  cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => undefined);
  if (!rec) return;
  const file = path.join(rec.dir, `f${String(frameNo++).padStart(6, '0')}.${FORMAT === 'png' ? 'png' : 'jpg'}`);
  fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
  rec.frames.push({ file, ts: f.metadata.timestamp ?? Date.now() / 1000 });
});
const now = () => Date.now() / 1000;
async function startRec(id) {
  const dir = path.join(tmpRoot, id);
  fs.mkdirSync(dir, { recursive: true });
  rec = { dir, frames: [], t0: now() };
  await cdp.send('Page.startScreencast', { format: FORMAT, ...(FORMAT === 'png' ? {} : { quality: 95 }), maxWidth: W * SCALE, maxHeight: H * SCALE, everyNthFrame: 1 });
  // nudge one repaint so the clip starts with a frame even on a static page
  await page.evaluate(() => document.getElementById('__cap_cursor')?.animate([{ opacity: 1 }, { opacity: 0.999 }], { duration: 60 }));
  await page.waitForTimeout(120);
  rec.t0 = rec.frames[0]?.ts ?? rec.t0;
}
async function stopRec(outFile) {
  const end = now();
  await cdp.send('Page.stopScreencast');
  const { frames, dir, t0 } = rec;
  if (!frames.length) throw new Error('the screencast produced no frames (is the window painting?)');
  const gaps = frames.slice(1).map((f, i) => f.ts - frames[i].ts);
  rec.stats = { frames: frames.length, maxGap: Math.max(0, ...gaps) };
  // constant fps: output frame k shows the newest frame whose timestamp <= t0 + k / fps
  const n = Math.max(1, Math.round((end - t0) * FPS));
  const list = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const t = t0 + k / FPS;
    while (j + 1 < frames.length && frames[j + 1].ts <= t) j++;
    list.push(frames[j].file);
  }
  const txt = path.join(dir, 'list.txt');
  fs.writeFileSync(txt, list.map((f) => `file '${f}'\nduration ${(1 / FPS).toFixed(6)}`).join('\n') + `\nfile '${list.at(-1)}'\n`);
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', txt, '-vf', `fps=${FPS},scale=${W * SCALE}:${H * SCALE}:flags=lanczos,format=yuv420p`, '-r', String(FPS), '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-movflags', '+faststart', outFile], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error(`ffmpeg failed for ${outFile}`);
  fs.rmSync(dir, { recursive: true, force: true });
  const { stats } = rec;
  rec = null;
  console.log(`  ${stats.frames} screencast frames (repaints) in ${(end - t0).toFixed(1)} s, longest still gap ${stats.maxGap.toFixed(2)} s`);
  return n / FPS;
}

// ------------------------------------------------------------------ actions
const sleep = (ms) => page.waitForTimeout(ms);
const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2);
const mouse = { x: W * 0.62, y: H * 0.72 };
async function glide(x, y, ms) {
  const d = Math.hypot(x - mouse.x, y - mouse.y);
  const dur = ms ?? Math.min(900, Math.max(260, d * 0.9));
  const steps = Math.max(8, Math.round(dur / 16));
  const [x0, y0] = [mouse.x, mouse.y];
  // a slight arc reads as a hand, not a robot
  const bend = Math.min(60, d * 0.12) * (x > x0 ? 1 : -1);
  for (let i = 1; i <= steps; i++) {
    const u = ease(i / steps);
    const arc = Math.sin(Math.PI * u) * bend;
    await page.mouse.move(x0 + (x - x0) * u, y0 + (y - y0) * u - arc * 0.35);
    await sleep(dur / steps);
  }
  mouse.x = x;
  mouse.y = y;
}
const selOf = (s) => (typeof s === 'string' ? s.replace(/^testid=(.+)$/, '[data-testid="$1"]') : s);
function locate(a, key) {
  let l = page.locator(selOf(a[key]));
  if (a.has_text) l = l.filter({ hasText: a.has_text });
  return a.nth != null ? l.nth(a.nth) : l.first();
}
async function boxOf(l, a, timeout) {
  await l.waitFor({ state: 'visible', timeout });
  await l.scrollIntoViewIfNeeded({ timeout }).catch(() => undefined);
  const b = await l.boundingBox({ timeout });
  if (!b) throw new Error('no bounding box (not rendered)');
  const [fx, fy] = a.at ?? [0.5, 0.5];
  return { b, x: b.x + b.width * fx, y: b.y + b.height * fy };
}
const norm = (b) => ({ x: +(b.x / W).toFixed(4), y: +(b.y / H).toFixed(4), w: +(b.width / W).toFixed(4), h: +(b.height / H).toFixed(4) });

async function run(a, ctx) {
  const key = Object.keys(a).find((k) => !['pause', 'timeout', 'text', 'has_text', 'nth', 'at', 'clear', 'cps', 'dy', 'state', 'on', 'still', 'to'].includes(k)) ?? (a.still ? 'still' : null);
  const timeout = a.timeout ?? 15000;
  const mark = (b, kind) => ctx.focus?.push({ t: +(now() - ctx.t0()).toFixed(2), ...norm(b), kind });
  const what = `${key} ${typeof a[key] === 'string' ? a[key] : JSON.stringify(a[key])}${a.has_text ? ` (has_text "${a.has_text}")` : ''}`;
  try {
    switch (key) {
      case 'goto':
        if (a.goto.startsWith('#')) await page.evaluate((h) => (location.hash = h), a.goto);
        else await page.goto(a.goto);
        break;
      case 'click':
      case 'dblclick':
      case 'hover':
      case 'move':
      case 'focus': {
        const l = locate(a, key);
        const { b, x, y } = await boxOf(l, a, timeout);
        if (key === 'focus') {
          mark(b, 'focus');
          break;
        }
        await glide(x, y);
        if (key === 'click' || key === 'dblclick') {
          await sleep(90);
          mark(b, 'click');
          await page.mouse.click(x, y, { clickCount: key === 'dblclick' ? 2 : 1, delay: 70 });
        }
        break;
      }
      case 'type': {
        const l = locate(a, key);
        const { b, x, y } = await boxOf(l, a, timeout);
        await glide(x, y);
        await sleep(80);
        await page.mouse.click(x, y, { delay: 60 });
        if (a.clear) {
          await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
          await page.keyboard.press('Backspace');
        }
        mark(b, 'type');
        const per = 1000 / (a.cps ?? 14);
        for (const ch of String(a.text ?? '')) {
          await page.keyboard.type(ch);
          await sleep(per * (0.55 + Math.random() * 0.9) + (/[ ,.]/.test(ch) ? per * 0.6 : 0));
        }
        break;
      }
      case 'drag': {
        const from = await boxOf(locate(a, key), a, timeout);
        const to = await boxOf(locate({ to: a.to }, 'to'), {}, timeout);
        await glide(from.x, from.y);
        mark(from.b, 'click');
        await page.mouse.down();
        await glide(to.x, to.y, 700);
        await page.mouse.up();
        break;
      }
      case 'press':
        if (a.on) await locate({ ...a, on: a.on }, 'on').press(a.press, { timeout });
        else await page.keyboard.press(a.press);
        break;
      case 'wait':
        await sleep(Number(a.wait));
        break;
      case 'waitFor':
        await locate(a, key).waitFor({ state: a.state ?? 'visible', timeout: a.timeout ?? 30000 });
        break;
      case 'scroll': {
        const { x, y } = await boxOf(locate(a, key), a, timeout);
        await glide(x, y);
        const dy = a.dy ?? 400;
        for (let i = 0; i < 20; i++) {
          await page.mouse.wheel(0, dy / 20);
          await sleep(22);
        }
        break;
      }
      case 'still':
        ctx.still = await page.screenshot({ type: 'png' });
        break;
      case 'eval':
      case 'electron':
      case 'sh':
        if (!ctx.setup) throw new Error(`${key} is allowed in setup only`);
        if (key === 'sh') {
          const r = spawnSync('/bin/sh', ['-c', a.sh], { env, stdio: ['ignore', 'inherit', 'inherit'], timeout: a.timeout ?? 600000 });
          if (r.status !== 0) throw new Error(`exit ${r.status ?? r.signal}`);
        } else if (key === 'eval') await page.evaluate(a.eval);
        else if (!app) throw new Error('electron: needs --electron');
        else await app.evaluate(new Function('m', `const {app, BrowserWindow} = m; return (async () => { ${a.electron} })();`));
        break;
      default:
        throw new Error(`unknown action ${JSON.stringify(a)}`);
    }
  } catch (e) {
    throw new Error(`shot "${ctx.id}": ${what}: ${String(e.message ?? e).split('\n')[0]}`, { cause: e });
  }
  await sleep(a.pause ?? 250);
}

// ------------------------------------------------------------------ shots
const manifest = { size: [W, H], scale: SCALE, fps: FPS, shots: [] };
const manifestPath = path.join(OUT, 'shots.json');
let code = 0;
try {
  for (const s of shots) {
    console.log(`shot ${s.id}: setup`);
    const ctx = { id: s.id, setup: true, focus: null, t0: () => rec?.t0 ?? now(), still: null };
    for (const a of s.setup ?? []) await run(a, ctx);
    // park the cursor where the first action will pull it from, before the clip starts
    await page.mouse.move(mouse.x, mouse.y);
    await page.evaluate(() => document.getElementById('__cap_cursor') || window.dispatchEvent(new Event('resize')));
    Object.assign(ctx, { setup: false, focus: [] });
    await startRec(s.id);
    for (const a of s.actions ?? []) await run(a, ctx);
    await sleep(Math.round((s.hold_after ?? 1) * 1000));
    const still = ctx.still ?? (await page.screenshot({ type: 'png' }));
    const file = `${s.id}.mp4`;
    const duration = await stopRec(path.join(OUT, file));
    fs.writeFileSync(path.join(OUT, `${s.id}.png`), still);
    manifest.shots.push({ id: s.id, title: s.title ?? s.id, caption: s.caption ?? '', file, still: `${s.id}.png`, w: W * SCALE, h: H * SCALE, duration: +duration.toFixed(2), focus: ctx.focus });
    console.log(`shot ${s.id}: ${duration.toFixed(1)} s, ${ctx.focus.length} focus boxes`);
  }
} catch (e) {
  console.error(`capture: ${e.message}`);
  if (app) await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.webContents.capturePage().then((i) => i.toPNG().toString('base64'))).then((b) => b && fs.writeFileSync(path.join(OUT, '_failed.png'), Buffer.from(b, 'base64'))).catch(() => undefined);
  code = 1;
} finally {
  if (manifest.shots.length) {
    // merge with an existing manifest so --only re-records one shot without losing the others
    const prev = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : null;
    if (prev?.shots && only.length) manifest.shots = [...prev.shots.filter((x) => !manifest.shots.some((y) => y.id === x.id)), ...manifest.shots];
    const order = (doc.shots ?? []).map((x) => x.id);
    manifest.shots.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  }
  await app?.close().catch(() => undefined);
  await browser?.close().catch(() => undefined);
  fs.rmSync(tmpRoot, { recursive: true, force: true });
}
process.exit(code);
