// The chat-first clip editor (ux/CHAT_EDIT.md, direction C), window hidden, mock engine (desk implementation: no
// model, no network), isolated profile. In English and 简体中文: a request -> a draft change card -> adjust it in the
// effect card -> before / after on the player -> apply -> a second card -> undo the OLDER card only (the later one
// stays) -> the conversation survives a reload; slash commands open cards without the model; the export card shows
// progress per version; the AI-unavailable card; ⌘K, hold C, Esc; one filled button; no missing message keys.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
let item = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-chat-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');

function ffmpeg(args: string[]) {
  execFileSync('ffmpeg', ['-v', 'error', '-y', ...args]);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(path.join(fuye, 'final'), { recursive: true });
  const lavfi = (w: number, h: number) => ['-f', 'lavfi', '-i', `testsrc2=size=${w}x${h}:rate=30:duration=6`, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'];
  const w = [['你在', 0.2, 0.6], ['副业', 0.6, 1.1], ['当中', 1.1, 1.5], ['其实', 2.4, 2.9], ['底气', 2.9, 3.5], ['很重要', 3.5, 4.4]];
  for (const c of ['A_换圈子', 'B_底气']) {
    ffmpeg([...lavfi(240, 320), path.join(fuye, 'final', `${c}.mp4`)]);
    fs.writeFileSync(path.join(fuye, 'final', `${c}.mp4.asr.json`), JSON.stringify({ segments: [{ start: 0.2, end: 4.4, words: w.map(([word, start, end]) => ({ word, start, end })) }] }));
  }
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_EXPORT_STEP: '0.4', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
  item = await page.evaluate(async () => {
    const info = await window.desk.engineInfo();
    for (let i = 0; i < 60; i++) {
      const h = await (await fetch(info.baseUrl + '/api/history', { headers: { Authorization: `Bearer ${info.token}` } })).json();
      const it = (h.items as { id: string; name: string }[]).find((x) => x.name === 'fuye');
      if (it) return it.id;
      await new Promise((r) => setTimeout(r, 500));
    }
    return '';
  });
  expect(item).toMatch(/^[0-9a-f]{12}$/);
});

test.afterAll(async () => {
  await app?.close();
});

const api = (clip: string) =>
  page.evaluate(
    async ([i, c]) => {
      const info = await window.desk.engineInfo();
      return (await fetch(`${info.baseUrl}/api/outputs/${i}/${encodeURIComponent(c)}`, { headers: { Authorization: `Bearer ${info.token}` } })).json();
    },
    [item, clip],
  );

async function openEditor(lang: 'en' | 'zh-CN', clip: string) {
  await page.evaluate(async (l) => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.setSettings({ lang: l });
  }, lang);
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate((h) => (location.hash = h), `#/p/${item}/clip/${encodeURIComponent(clip)}`);
  await expect(page.getByTestId('chat-panel')).toBeVisible({ timeout: 30000 });
}

async function say(s: string) {
  await page.getByTestId('chat-input').fill(s);
  await page.getByTestId('chat-input').press('Enter');
}

async function noMissingKeys() {
  const text = await page.evaluate(() => document.body.innerText);
  expect(text.match(/⟦[^⟧]+⟧/g) ?? []).toEqual([]);
  expect(text.match(/\bce\.[a-zA-Z][\w.-]+/g) ?? []).toEqual([]);
}

const L = {
  en: { pop: 'Pop “底气” when she says it', speed: '1.1x speed', vague: 'Give it more breathing room', trim: '/trim', caps: '/captions' },
  'zh-CN': { pop: '把「底气」弹出来', speed: '1.1倍速', vague: '让节奏更有呼吸感', trim: '/裁剪', caps: '/字幕' },
} as const;

for (const [lang, clip] of [['en', 'A_换圈子'], ['zh-CN', 'B_底气']] as const) {
  const s = L[lang];

  test(`${lang}: request -> draft card -> adjust in the effect card -> compare -> apply -> undo the older card only`, async () => {
    await openEditor(lang, clip);
    // empty state: suggestions from THIS clip (its pause and its words), Export is the one filled button
    await expect(page.getByTestId('chat-empty')).toBeVisible();
    await expect(page.getByTestId('sug-pauses')).toBeVisible();
    await expect(page.getByTestId('sug-pop')).toBeVisible();
    await expect(page.getByTestId('editor-export')).toHaveClass(/primary/);
    await noMissingKeys();

    await say(s.pop);
    const card = page.getByTestId('change-card');
    await expect(card).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('tl-marker-draft').first()).toBeVisible(); // amber on the timeline
    await expect(page.getByTestId('editor-export')).not.toHaveClass(/primary/); // 应用 is now the one filled button
    await expect(page.getByTestId('change-apply')).toHaveClass(/primary/);
    await expect(page.locator('.btn.primary:visible')).toHaveCount(1);
    await expect(page.getByTestId('chat-cost')).toContainText(/\$0\.00/);

    // adjust: the effect card, colour + when it shows; Done returns to the change set
    await card.getByTestId('change-adjust').first().click();
    const fx = page.getByTestId('card-effect');
    await expect(fx).toBeVisible();
    await fx.getByTestId('fx-colour-E5484D').click();
    await expect(fx.getByTestId('fx-span')).toContainText('0:02.9');
    await fx.getByTestId('card-apply').click();
    await expect(card).toBeVisible();

    // before / after on the player itself, nothing applied yet
    await card.getByTestId('change-compare').click();
    await expect(page.getByTestId('compare-wipe')).toBeVisible();
    expect((await api(clip)).undo).toBe(0);
    await card.getByTestId('change-compare').click();
    await expect(page.getByTestId('compare-wipe')).toHaveCount(0);

    await card.getByTestId('change-apply').click();
    await expect(page.getByTestId('applied-line')).toHaveCount(1);
    await expect(page.getByTestId('editor-export')).toHaveClass(/primary/);
    let d = await api(clip);
    expect(d.effects.map((e: { params: { text: string; color: string } }) => [e.params.text, e.params.color])).toEqual([['底气', '#E5484D']]);

    // a second card, then undo the FIRST one only: the speed change stays
    await say(s.speed);
    await expect(page.getByTestId('change-card')).toBeVisible({ timeout: 15000 });
    await page.keyboard.press('Meta+Enter'); // ⌘↵ applies the newest draft
    await expect(page.getByTestId('applied-line')).toHaveCount(2);
    await page.getByTestId('applied-line').first().getByTestId('applied-undo').click();
    await expect(page.getByTestId('reverted-line')).toHaveCount(1);
    await expect(page.getByTestId('applied-line')).toHaveCount(1);
    d = await api(clip);
    expect(d.effects).toEqual([]);
    expect(d.speed).toBe(1.1);
    expect(d.steps.length).toBe(3); // pop, speed, revert(pop)

    // hold C: the original
    await page.getByTestId('editor-title').click();
    await page.keyboard.down('c');
    await expect(page.getByTestId('player-badge')).toBeVisible();
    await page.keyboard.up('c');
    await expect(page.getByTestId('player-badge')).toHaveCount(0);

    // the conversation is stored with the clip: a reload rebuilds it
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await expect(page.getByTestId('chat-panel')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('chat-me')).toHaveCount(2);
    await expect(page.getByTestId('reverted-line')).toHaveCount(1);
    await page.getByTestId('reverted-restore').click(); // the reverted card comes back
    await expect(page.getByTestId('applied-line')).toHaveCount(2);
    await noMissingKeys();
  });

  test(`${lang}: slash commands open cards without the model; ⌘K; Esc`, async () => {
    await page.getByTestId('editor-title').click();
    await page.keyboard.press('Meta+k');
    await expect(page.getByTestId('chat-input')).toBeFocused();
    await expect(page.getByTestId('palette')).toHaveCount(0);
    await page.keyboard.type('/');
    await expect(page.getByTestId('slash-menu').locator('button')).toHaveCount(5);
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('slash-menu')).toHaveCount(0);

    const before = (await api(clip)).steps.length;
    await say(s.trim);
    const trim = page.getByTestId('card-trim');
    await expect(trim).toBeVisible();
    await expect(page.getByTestId('chat-thinking')).toHaveCount(0); // no model round-trip
    await expect(trim.getByTestId('trim-pause')).toHaveCount(1);
    await trim.getByTestId('card-apply').click();
    await expect(page.getByTestId('card-trim')).toHaveCount(0);
    const d = await api(clip);
    expect(d.steps.length).toBe(before + 1);
    expect(d.cuts.length).toBe(1);

    await say(s.caps);
    await expect(page.getByTestId('caps-burned')).toBeVisible(); // flattened: add only, explained
    await page.keyboard.press('Escape'); // Esc closes the open card
    await expect(page.getByTestId('discarded-line')).toHaveCount(1);
    await noMissingKeys();
  });

  test(`${lang}: the export card shows progress per version`, async () => {
    await page.getByTestId('editor-export').click();
    const ex = page.getByTestId('card-export');
    await expect(ex).toBeVisible();
    await expect(ex.getByTestId('export-go')).toHaveClass(/primary/);
    await ex.getByTestId('pf-douyin').click();
    await ex.getByTestId('export-go').click();
    await expect(ex.getByTestId('export-row')).toHaveCount(2);
    await expect(ex.getByTestId('export-stop')).toBeVisible();
    await expect(ex.locator('[data-testid=export-row][data-done="1"]')).toHaveCount(2, { timeout: 20000 });
    await expect(ex.getByTestId('export-state')).toContainText(/re-encode|重新编码/);
    expect((await api(clip)).exports.map((e: { target: string }) => e.target)).toContain('douyin:vertical');
  });

  test(`${lang}: no model -> the fallback card, tools still work`, async () => {
    await say(s.vague);
    const off = page.getByTestId('card-offline');
    await expect(off).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('model-chip-off')).toBeVisible();
    await expect(off.getByTestId('off-connect')).toHaveClass(/primary/);
    await off.getByTestId('off-phrase').first().click(); // "speed 1.1×" is understood without a model
    await expect(page.getByTestId('change-card')).toBeVisible({ timeout: 15000 });
    await page.getByTestId('change-discard').click();
    await expect(page.getByTestId('discarded-line').last()).toBeVisible();
    await noMissingKeys();
    await page.evaluate(() => localStorage.removeItem('i18n.strict'));
  });
}

test('an answered request whose turn never shows up stops the spinner and says so (no endless 「正在看」)', async () => {
  test.setTimeout(60000);
  await openEditor('en', 'A_换圈子');
  // the engine answers /ask but its turn is not in the clip's conversation (the P0-2 failure mode)
  await page.route('**/ask', async (route) => {
    const resp = await route.fetch();
    const j = await resp.json();
    await route.fulfill({ response: resp, json: { ...j, turn: 't99-dead' } });
  });
  await say('1.1x speed');
  await expect(page.getByTestId('chat-thinking')).toBeVisible();
  await expect(page.getByTestId('chat-lost')).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId('chat-thinking')).toHaveCount(0);
  await expect(page.getByTestId('chat-lost-retry')).toBeVisible();
  await page.unroute('**/ask');
  await page.evaluate(() => localStorage.removeItem('i18n.strict'));
});
