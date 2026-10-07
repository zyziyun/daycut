// Create page (mock engine = fake video services, nothing is ever spent; window hidden; isolated profile):
// one sentence -> plan -> bible -> 2 scripts -> storyboard -> change a shot's service -> animatic -> spend sheet
// (cancel = nothing runs; confirm) -> Making -> pick takes -> Ready -> assemble -> open in the normal editor ->
// send the versions to Publish; the recorder with Chromium's fake camera / mic -> a talking-head project; and with
// the flag off: no Create nav item, #/create lands on Home. CREATE_SHOTS=<dir> also saves a screenshot per screen.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const SHOTS = process.env.CREATE_SHOTS || '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-create-'));

async function launch(extra: Record<string, string>, profile: string) {
  const app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_MOCK_STEP: '0.02',
      DESK_USER_DATA: path.join(tmp, profile),
      VSTUDIO_HOME: path.join(tmp, `vhome-${profile}`),
      DESK_HISTORY_WATCH: path.join(tmp, 'none'),
      DESK_HIDE_WINDOW: '1',
      DESK_SHARED_CACHE: path.join(tmp, 'cache'),
      DESK_HF_HUB: '',
      DESK_SKIP_FIRST_RUN: '1',
      VITE_DEV_SERVER_URL: '',
      ...extra,
    },
  });
  const page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  return { app, page };
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

test.describe.configure({ mode: 'serial' });

test.describe('Create on', () => {
  let app: ElectronApplication;
  let page: Page;
  const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);

  test.beforeAll(async () => {
    ({ app, page } = await launch({ DESK_CREATE: '1', DESK_E2E_FAKE_MEDIA: '1' }, 'on'));
    // the mockups are light: screenshots in notebook-light
    await page.evaluate(() => window.desk.setSettings({ theme: 'notebook-light' }));
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
  });

  test.afterAll(async () => {
    await app?.close();
  });

  test('nav shows Create; first run offers the sample', async () => {
    await expect(page.getByTestId('nav-create')).toBeVisible({ timeout: 30000 });
    await page.getByTestId('nav-create').click();
    await expect(page.getByTestId('create-home')).toBeVisible();
    await expect(page.getByTestId('create-formats').locator('button')).toHaveCount(6);
    await expect(page.getByTestId('create-sample')).toBeVisible();
    await shot(page, 'C03-first-run');
  });

  test('one sentence -> plan -> bible -> write 2 scripts', async () => {
    await page.getByTestId('create-prompt').fill('3-episode comedy sketch about a robot barista who takes orders literally, Chinese + English');
    await page.getByTestId('create-budget').locator('select').selectOption('300');
    await page.getByTestId('create-plan').click();
    await expect(page.getByTestId('create-series')).toBeVisible({ timeout: 60000 });
    await expect(page.getByTestId('create-cast-member').first()).toBeVisible();
    await expect(page.getByTestId('create-idea')).toHaveCount(4);
    await shot(page, 'C04-bible');
    await page.getByTestId('create-write-scripts').click();
    await expect(page.getByTestId('create-episode')).toBeVisible({ timeout: 60000 });
    await expect(page.getByTestId('create-shot').first()).toBeVisible();
  });

  test('storyboard: change a shot, animatic, spend sheet (cancel = nothing runs, then confirm)', async () => {
    const total = page.getByTestId('create-plan-panel').locator('.cr-total .big');
    const before = await total.textContent();
    const shots = page.getByTestId('create-shot');
    const n = await shots.count();
    // a shot without faces -> Kling (pricier than the cheapest): the cost changes
    let changed = false;
    for (let i = 0; i < n && !changed; i++) {
      const s = shots.nth(i);
      const chip = s.locator('.cr-src');
      if (!(await chip.textContent())?.includes('Veo')) continue;
      await chip.click();
      await expect(page.getByTestId('create-source-popover')).toBeVisible();
      await shot(page, 'C05-storyboard-popover');
      await page.getByTestId('create-source-popover').locator('[data-source="cloud:kling-mcp/kling-video-v3_0_omni"]').click();
      changed = true;
    }
    expect(changed).toBe(true);
    await expect(total).not.toHaveText(before ?? '', { timeout: 10000 });
    // the next free step first
    const primary = page.getByTestId('create-primary');
    await expect(primary).toBeVisible();
    for (let i = 0; i < 3; i++) {
      await expect(primary).toBeEnabled({ timeout: 30000 });
      const label = (await primary.textContent()) ?? '';
      if (/final/i.test(label)) break;
      await primary.click(); // storyboard frames / animatic: free steps on this Mac
      await expect(primary).not.toHaveText(label, { timeout: 30000 });
    }
    await expect(primary).toContainText(/final/i, { timeout: 30000 });
    await shot(page, 'C05-storyboard');
    await primary.click();
    const sheet = page.getByTestId('create-spend-sheet');
    await expect(sheet).toBeVisible();
    await expect(page.getByTestId('create-sheet-line').first()).toBeVisible();
    await shot(page, 'C06-spend-confirm');
    await page.getByTestId('create-sheet-cancel').click();
    await expect(sheet).toBeHidden();
    const runs = await page.evaluate(async () => {
      const i = await window.desk.engineInfo();
      const r = await fetch(`${i.baseUrl}/api/create/runs`, { headers: { Authorization: `Bearer ${i.token}` } });
      return (await r.json()) as { rows: unknown[] };
    });
    expect(runs.rows).toEqual([]); // cancel: nothing was made, nothing spent
    await primary.click();
    await expect(sheet).toBeVisible();
    await expect(page.getByTestId('create-spend-confirm')).toBeEnabled({ timeout: 10000 });
    await page.getByTestId('create-spend-confirm').click();
    await expect(page.getByTestId('create-making')).toBeVisible({ timeout: 30000 });
  });

  test('making -> pick takes -> ready -> assemble -> editor -> publish', async () => {
    await expect(page.getByTestId('create-pick-takes')).toBeVisible({ timeout: 90000 });
    await shot(page, 'C07-making');
    await page.getByTestId('create-pick-takes').click();
    await expect(page.getByTestId('create-takes')).toBeVisible();
    // every shot with more than one take and none picked yet: use its first take
    for (let k = 0; k < 30; k++) {
      const open = page.getByTestId('create-take-shot').filter({ hasNot: page.locator('[data-testid="create-take-use"]:disabled') });
      if (!(await open.count())) break;
      await open.first().getByTestId('create-take-use').first().click();
      await page.waitForTimeout(300);
    }
    const ep = await page.evaluate(() => location.hash);
    const sid = ep.match(/#\/create\/e\/(.+)-e\d+/)?.[1];
    await hash(`#/create/s/${sid}/ready`);
    await expect(page.getByTestId('create-ready')).toBeVisible({ timeout: 30000 });
    await page.getByTestId('create-assemble').click();
    await expect(page.getByTestId('create-open-editor')).toBeVisible({ timeout: 120000 });
    await expect(page.getByTestId('create-languages')).toBeVisible();
    await shot(page, 'C10-ready');
    await page.getByTestId('create-send-publish').click();
    await expect(page.getByTestId('create-sent')).toBeVisible({ timeout: 30000 });
    await page.getByTestId('create-open-editor').click();
    await expect(page.getByTestId('editor')).toBeVisible({ timeout: 30000 });
    await hash('#/publish');
    await expect(page.getByTestId('calendar')).toBeVisible();
  });

  test('the inbox and the home list know the series', async () => {
    await hash('#/create');
    await expect(page.getByTestId('create-series-card').first()).toBeVisible({ timeout: 30000 });
    await shot(page, 'C01-home');
  });

  test('sample series opens on its storyboard', async () => {
    await page.getByTestId('create-open-sample').click();
    await expect(page.getByTestId('create-episode')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('create-shot')).toHaveCount(18);
    await shot(page, 'C05-sample-storyboard');
  });

  test('settings › video generation', async () => {
    await hash('#/settings/video');
    await expect(page.getByTestId('create-settings')).toBeVisible();
    await expect(page.getByTestId('create-svc-kling-mcp')).toBeVisible();
    await shot(page, 'C12-settings-video');
    await hash('#/settings');
    await expect(page.getByTestId('settings-create')).toBeVisible();
  });

  test('recorder: fake camera + mic -> record, retake, stop -> a talking-head project', async () => {
    await hash('#/create/record');
    await expect(page.getByTestId('create-record')).toBeVisible();
    await page.getByTestId('create-rec-script').fill('So my side hustle made 312 last month.\nMy day job made more.\nBut here is what nobody tells you.');
    await page.getByTestId('create-rec-edit').click();
    await page.getByTestId('create-rec-allow').click();
    await expect(page.getByTestId('create-rec-preview')).toBeVisible({ timeout: 20000 });
    await page.getByTestId('create-rec-start').click();
    await expect(page.getByTestId('create-rec-live')).toBeVisible();
    await page.waitForTimeout(2200);
    await page.getByTestId('create-rec-retake').click();
    await page.waitForTimeout(1600);
    await shot(page, 'C08-record');
    await page.getByTestId('create-rec-stop').click();
    await expect(page.getByTestId('create-rec-result')).toBeVisible({ timeout: 120000 });
    await page.getByTestId('create-rec-open').click();
    await expect(page.getByTestId('project-title')).toBeVisible({ timeout: 30000 });
  });
  test('简体中文 + dark: every Create screen has its copy (no missing keys)', async () => {
    await page.evaluate(() => localStorage.setItem('i18n.strict', '1'));
    await page.evaluate(() => window.desk.setSettings({ lang: 'zh-CN' }));
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    const screens: [string, string][] = [['#/create', 'C02-home-zh']];
    const ids = await page.evaluate(async () => {
      const i = await window.desk.engineInfo();
      const r = await fetch(`${i.baseUrl}/api/create/series`, { headers: { Authorization: `Bearer ${i.token}` } });
      return ((await r.json()) as { series: { id: string; sample: boolean }[] }).series;
    });
    const sample = ids.find((x) => x.sample)?.id ?? ids[0].id;
    screens.push([`#/create/s/${sample}`, 'C04-bible-zh'], [`#/create/s/${ids[ids.length - 1].id}/making`, 'C07-making-zh'], ['#/settings/video', 'C12-settings-zh']);
    for (const [h, name] of screens) {
      await hash(h);
      await page.waitForTimeout(600);
      await expect(page.locator('main')).not.toContainText('⟦');
      await shot(page, name);
    }
    await page.evaluate(() => window.desk.setSettings({ theme: 'studio-dark', lang: 'en' }));
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await hash(`#/create/s/${sample}/episodes`);
    await page.getByTestId('create-episode-row').first().click();
    await expect(page.getByTestId('create-shot').first()).toBeVisible();
    await expect(page.locator('main')).not.toContainText('⟦');
    await shot(page, 'C11-storyboard-dark');
    await page.evaluate(() => localStorage.removeItem('i18n.strict'));
  });
});

test.describe('Create off', () => {
  test('no Create nav item, #/create lands on Home, no create calls', async () => {
    const { app, page } = await launch({ DESK_CREATE: '0' }, 'off');
    try {
      await expect(page.getByTestId('home')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('nav-create')).toHaveCount(0);
      await page.evaluate(() => (location.hash = '#/create/s/x/bible'));
      await expect(page.getByTestId('home')).toBeVisible();
      await expect(page.getByTestId('create-home')).toHaveCount(0);
      await page.evaluate(() => (location.hash = '#/settings'));
      await expect(page.getByTestId('settings-create')).toBeVisible();
      await expect(page.getByTestId('settings-video-link')).toHaveCount(0);
      const roots = await page.evaluate(async () => {
        const i = await window.desk.engineInfo();
        const r = await fetch(`${i.baseUrl}/api/roots`, { headers: { Authorization: `Bearer ${i.token}` } });
        return (await r.json()) as string[];
      });
      expect(roots.some((r) => r.includes('create-mock'))).toBe(false);
    } finally {
      await app.close();
    }
  });
});
