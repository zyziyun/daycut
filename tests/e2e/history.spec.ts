// History: past work in a watched folder shows up on the Batches page without an import; search filters it;
// "remove from list" hides it and leaves the files alone. Mock engine, isolated profile and registries.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-history-'));
const watch = path.join(tmp, 'demos');

function fakeBatch(dir: string, name: string, delivered: boolean) {
  fs.mkdirSync(path.join(dir, 'jobs', 'ep01', 'preview'), { recursive: true });
  const py = `
import json, sqlite3, sys
con = sqlite3.connect(sys.argv[1] + '/batch.db')
con.executescript("""CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE jobs (id TEXT PRIMARY KEY, ord INTEGER, state TEXT, qc TEXT, review TEXT, created REAL, updated REAL);
CREATE TABLE deliveries (n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, client TEXT);""")
con.execute("INSERT INTO meta VALUES ('spec', ?)", (json.dumps(dict(name=sys.argv[2], recipe='longform-split')),))
con.execute("INSERT INTO jobs VALUES ('ep01', 0, 'done', 'green', NULL, 1, 2)")
if sys.argv[3] == '1':
    con.execute("INSERT INTO deliveries(ts, client) VALUES (1, '自己的账号')")
con.commit()
`;
  execFileSync('python3', ['-c', py, dir, name, delivered ? '1' : '0']);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fakeBatch(path.join(watch, 'batch-rag'), 'rag', true);
  fakeBatch(path.join(watch, 'client-a', 'batch-promo'), 'promo', false);
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await app?.close();
});

test('history lists past work from a watched folder, search, remove from list keeps files', async () => {
  const rows = page.getByTestId('history-row');
  await expect(rows).toHaveCount(2, { timeout: 30000 });
  await expect(page.getByTestId('history')).toContainText('rag');
  await expect(page.getByTestId('history')).toContainText('自己的账号');
  await page.getByTestId('history-search').fill('promo');
  await expect(rows).toHaveCount(1);
  page.once('dialog', (d) => void d.accept());
  await rows.first().getByTestId('history-hide').click();
  await page.getByTestId('history-search').fill('');
  await expect(rows).toHaveCount(1);
  expect(fs.existsSync(path.join(watch, 'client-a', 'batch-promo', 'batch.db'))).toBe(true);
});
