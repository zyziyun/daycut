// Interactive dogfood helper: drive a running Reelfold (packaged or dev) over CDP, one command per call, with a
// timestamped log so every step can be timed afterwards.
//   node scripts/dogfood/cdp.mjs <port> <logdir> shot <name>
//   node scripts/dogfood/cdp.mjs <port> <logdir> click <testid|text:...> [note]
//   node scripts/dogfood/cdp.mjs <port> <logdir> type <testid> <text>
//   node scripts/dogfood/cdp.mjs <port> <logdir> drop <testid> <file...>
//   node scripts/dogfood/cdp.mjs <port> <logdir> eval <js>
//   node scripts/dogfood/cdp.mjs <port> <logdir> text            (visible text of the page)
//   node scripts/dogfood/cdp.mjs <port> <logdir> wait <testid|text:...> [timeoutS]
//   node scripts/dogfood/cdp.mjs <port> <logdir> note <text>
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const [port, logdir, cmd, ...args] = process.argv.slice(2);
fs.mkdirSync(logdir, { recursive: true });
const log = (m) => {
  const line = `${new Date().toISOString()} ${cmd} ${m}`;
  fs.appendFileSync(path.join(logdir, 'log.txt'), line + '\n');
  console.log(line);
};
if (cmd === 'note') {
  log(args.join(' '));
  process.exit(0);
}
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 15000 });
const page = browser.contexts().flatMap((c) => c.pages()).find((p) => /^(app:\/\/desk|http:\/\/localhost)/.test(p.url()));
if (!page) throw new Error('no app window');
const loc = (sel) => (sel.startsWith('text:') ? page.getByText(sel.slice(5), { exact: false }).first() : sel.startsWith('role:') ? page.getByRole('button', { name: sel.slice(5) }).first() : page.getByTestId(sel).first());
try {
  if (cmd === 'shot') {
    const f = path.join(logdir, `${args[0]}.png`);
    await page.screenshot({ path: f });
    log(`${f} ${page.url()}`);
  } else if (cmd === 'click') {
    await loc(args[0]).click({ timeout: 10000 });
    log(`${args[0]} ${args.slice(1).join(' ')}`);
  } else if (cmd === 'type') {
    await loc(args[0]).fill(args.slice(1).join(' '));
    log(`${args[0]}`);
  } else if (cmd === 'wait') {
    const t0 = Date.now();
    await loc(args[0]).waitFor({ state: 'visible', timeout: Number(args[1] ?? 60) * 1000 });
    log(`${args[0]} after ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  } else if (cmd === 'drop') {
    const box = await loc(args[0]).boundingBox();
    const cdp = await page.context().newCDPSession(page);
    const data = { items: [], files: args.slice(1), dragOperationsMask: 1 };
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    for (const type of ['dragEnter', 'dragOver', 'drop']) await cdp.send('Input.dispatchDragEvent', { type, x, y, data });
    log(`${args[0]} ${args.slice(1).join(' ')}`);
  } else if (cmd === 'eval') {
    const r = await page.evaluate(args.join(' '));
    console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 1));
  } else if (cmd === 'text') {
    console.log(await page.evaluate('document.body.innerText'));
  }
} finally {
  await browser.close().catch(() => undefined);
}
