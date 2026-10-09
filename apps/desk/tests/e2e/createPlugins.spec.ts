// Create plugins end to end (mock engine = fake video services; isolated profile; window hidden; the file picker is
// stubbed in the main process): Import board on Create home with the HyperFrames fixture -> the episode's storyboard
// (3 shots, 2 set to HyperFrames); Settings › Video generation lists the plugins and turns a folder plugin on;
// Storyboard › Import board with a CSV shot list routed to that (fake) agent -> Make -> 3 takes via 2 lanes.
// Also: the Create home platform chip lists international platforms first.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-cplug-'));
const FIX = path.resolve(import.meta.dirname, '../../../../tests/fixtures/plugins/hyperframes-tiny');
const PLUGS = path.join(tmp, 'plugins');
const hasFfmpeg = (() => {
  try {
    execFileSync('ffmpeg', ['-version'], { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
})();

function fakeAgent() {
  const d = path.join(PLUGS, 'fake-agent');
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(
    path.join(d, 'plugin.yaml'),
    'id: fake-agent\nkind: agent-runner\nname: Fake agent\nversion: 0.1.0\napi: 1\ncommand: [./agent, "{job_dir}"]\npermissions: [write-job, "exec:agent"]\ncost: {kind: local}\nconcurrency: 2\ntimeout_s: 60\n',
  );
  fs.writeFileSync(path.join(d, 'agent'), '#!/bin/sh\nsleep 0.3\nffmpeg -v error -y -f lavfi -i color=c=blue:s=64x112:d=0.3 -pix_fmt yuv420p "$1/outputs/take.mp4"\n', { mode: 0o755 });
}

const SHOTS = process.env.CREATE_SHOTS || '';
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

async function pickNext(app: ElectronApplication, file: string) {
  await app.evaluate(({ dialog }, f) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [f] })) as unknown as typeof dialog.showOpenDialog;
  }, file);
}

test.describe.configure({ mode: 'serial' });

test.describe('Create plugins', () => {
  let app: ElectronApplication;
  let page: Page;
  let epHash = '';
  const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);

  test.beforeAll(async () => {
    fakeAgent();
    app = await electron.launch({
      args: [path.resolve(import.meta.dirname, '../..')],
      env: {
        ...process.env,
        DESK_ENGINE_MOCK: '1',
        DESK_MOCK_STEP: '0.02',
        DESK_USER_DATA: path.join(tmp, 'profile'),
        VSTUDIO_HOME: path.join(tmp, 'vhome'),
        VSTUDIO_PLUGINS_PATH: PLUGS,
        DESK_HISTORY_WATCH: path.join(tmp, 'none'),
        DESK_HIDE_WINDOW: '1',
        DESK_SHARED_CACHE: path.join(tmp, 'cache'),
        DESK_HF_HUB: '',
        DESK_SKIP_FIRST_RUN: '1',
        DESK_CREATE: '1',
        DESK_E2E_FAKE_MEDIA: '1',
        VITE_DEV_SERVER_URL: '',
      },
    });
    page = await app.firstWindow();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForURL(/^app:\/\/desk\//);
    page.on('dialog', (d) => void d.accept());
  });

  test.afterAll(async () => {
    await app?.close();
  });

  test('home: platforms international first, Import board with a HyperFrames project', async () => {
    await expect(page.getByTestId('nav-create')).toBeVisible({ timeout: 30000 });
    await hash('#/create');
    await expect(page.getByTestId('create-home')).toBeVisible();
    await expect(page.getByTestId('create-platforms')).toContainText(/YouTube[^,]*, TikTok \+2/);
    await pickNext(app, FIX);
    await page.getByTestId('create-import-board').click();
    await expect(page.getByTestId('create-episode')).toBeVisible({ timeout: 60000 });
    await expect(page.getByTestId('create-shot')).toHaveCount(3);
    await expect(page.getByTestId('create-episode').locator('.cr-sw.sw-plugin').first()).toBeVisible();
    await expect(page.getByTestId('create-primary')).toContainText(/2/);
    await shot(page, 'P01-imported-hyperframes');
    epHash = await page.evaluate(() => location.hash);
  });

  test('settings lists plugins; a folder plugin starts off and turns on', async () => {
    await hash('#/settings/video');
    const card = page.getByTestId('create-plugins');
    await expect(card).toBeVisible({ timeout: 30000 });
    await expect(card.locator('[data-key="importer:hyperframes"]')).toHaveAttribute('data-enabled', '1');
    const fake = card.locator('[data-key="agent-runner:fake-agent"]');
    await expect(fake).toHaveAttribute('data-enabled', '0');
    await fake.getByTestId('create-plugin-toggle').click();
    await expect(fake).toHaveAttribute('data-enabled', '1', { timeout: 15000 });
    await shot(page, 'P02-settings-plugins');
  });

  test('storyboard: import a CSV shot list for the agent, then Make in lanes', async () => {
    test.skip(!hasFfmpeg, 'ffmpeg not installed');
    await hash(epHash);
    await expect(page.getByTestId('create-episode')).toBeVisible({ timeout: 30000 });
    const csv = path.join(tmp, 'shots.csv');
    fs.writeFileSync(csv, 'shot,duration,action,source\n1,2,Cup,agent:fake-agent\n2,2,Pour,agent:fake-agent\n3,2,Sip,agent:fake-agent\n');
    await pickNext(app, csv);
    await page.getByTestId('create-storyboard-import').click();
    await expect(page.getByTestId('create-episode').locator('.cr-sw.sw-agent')).toHaveCount(3, { timeout: 60000 });
    const primary = page.getByTestId('create-primary');
    await expect(primary).toContainText(/3/);
    await primary.click();
    await expect(page.getByTestId('create-make-status')).toHaveAttribute('data-state', 'done', { timeout: 90000 });
    await expect(page.getByTestId('create-make-status')).toContainText('3');
    await shot(page, 'P03-made-by-agents');
  });

  test('plan: no AI answered -> a clear reason, Retry, Set up AI, Start from the template', async () => {
    // the engine's answer when Claude Code's login expired and Codex did not answer either (sidecar tests run it for
    // real); here the two calls are stubbed in the page's fetch (the engine is the app's own app://desk/api route,
    // which Playwright's network routing does not see) so the screen can be checked
    await page.evaluate(() => {
      const job = 'abcdefabcdef';
      const w = window as unknown as { fetch: typeof fetch; __realFetch?: typeof fetch };
      const real = (w.__realFetch = w.fetch);
      const json = (o: unknown) => new Response(JSON.stringify(o), { status: 200, headers: { 'content-type': 'application/json' } });
      w.fetch = async (input, init) => {
        const p = new URL(String(input)).pathname;
        if (p.endsWith('/api/create/plan')) return json({ job, kind: 'plan' });
        if (p.endsWith(`/api/create/jobs/${job}`))
          return json({ id: job, kind: 'plan', state: 'error', result: null, events: [{ event: 'create.step', step: 'bible', provider: 'claude-code' }], error: { code: 'create.ai-failed', params: { reason: 'auth-expired', provider: 'claude-code', seconds: 91 } } });
        return real(input, init);
      };
    });
    await hash('#/create');
    await page.getByTestId('create-fmt-series-ad').click();
    await page.getByTestId('create-plan').click();
    const err = page.getByTestId('create-plan-error');
    await expect(err).toBeVisible({ timeout: 15000 });
    await expect(err).toHaveAttribute('data-reason', 'auth-expired');
    await expect(err).toContainText('Claude Code');
    await expect(page.getByTestId('create-plan-retry')).toBeVisible();
    await expect(page.getByTestId('create-plan-setup-ai')).toBeVisible();
    await shot(page, 'P04-plan-error');
    await page.evaluate(() => {
      const w = window as unknown as { fetch: typeof fetch; __realFetch?: typeof fetch };
      if (w.__realFetch) w.fetch = w.__realFetch;
    });
    await page.getByTestId('create-plan-template').click();
    await expect(page.getByTestId('create-series')).toBeVisible({ timeout: 60000 });
  });
});
