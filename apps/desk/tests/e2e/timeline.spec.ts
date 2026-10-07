// The clip editor's scrub bar + timeline, window hidden, mock engine (desk implementation, mock 「听一遍」), isolated
// profile: click the scrub bar to seek (hover shows a frame + the time), click the timeline to seek, drag the playhead,
// zoom (+ / Fit / ⌘+ / ⌘0) with the ruler and the view following, the filmstrip + waveform from the engine's sprite /
// peaks, 「听一遍这条片子」 -> words appear, drag across words -> the selection chip in the composer, keyboard.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
let item = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-tl-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');
const DUR = 8;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(path.join(fuye, 'final'), { recursive: true });
  const make = (name: string, w: number, h: number) =>
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', `testsrc2=size=${w}x${h}:rate=30:duration=${DUR}`, '-f', 'lavfi', '-i', `sine=frequency=330:duration=${DUR}`, '-shortest', '-c:v', 'libx264', '-g', '15', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(fuye, 'final', name)]);
  make('A_换圈子.mp4', 240, 320); // 3:4 with a transcript
  make('B_底气.mp4', 180, 320); // 9:16, nothing heard yet
  const w = [['你在', 0.2, 0.6], ['副业', 0.6, 1.1], ['当中', 1.1, 1.5], ['其实', 2.4, 2.9], ['底气', 2.9, 3.5], ['很重要', 3.5, 4.4], ['所以', 5.0, 5.4], ['要换', 5.4, 5.9], ['圈子', 5.9, 6.6]];
  fs.writeFileSync(path.join(fuye, 'final', 'A_换圈子.mp4.asr.json'), JSON.stringify({ segments: [{ start: 0.2, end: 6.6, words: w.map(([word, start, end]) => ({ word, start, end })) }] }));
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_MOCK_ASR_STEP: '0.5', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
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
  await closeApp(app);
});

async function open(clip: string, lang: 'en' | 'zh-CN' = 'zh-CN') {
  await page.evaluate(async (l) => {
    localStorage.setItem('i18n.strict', '1');
    sessionStorage.removeItem('v4.tlzoom2');
    localStorage.setItem('ce.layout', JSON.stringify({ tab: 'timeline' })); // this file is about the timeline tab
    await window.desk.setSettings({ lang: l });
  }, lang);
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate((h) => (location.hash = h), `#/p/${item}/clip/${encodeURIComponent(clip)}`);
  await expect(page.getByTestId('chat-panel')).toBeVisible({ timeout: 30000 });
  await page.waitForFunction(() => ((document.querySelector('[data-testid=player-video]') as HTMLVideoElement | null)?.readyState ?? 0) >= 2);
  await expect(page.getByTestId('tl-film')).toHaveAttribute('data-ready', '1', { timeout: 30000 });
}

const now = () => page.evaluate(() => (document.querySelector('[data-testid=player-video]') as HTMLVideoElement).currentTime);
const near = (t: number, tol = 0.25) => expect.poll(async () => Math.abs((await now()) - t), { timeout: 5000 }).toBeLessThanOrEqual(tol);
/** client x of time t on the timeline (the scrolling content starts at the view's left edge) */
const tlX = async (t: number) => {
  const v = await page.getByTestId('tl-view').boundingBox();
  const { pps, scroll } = await page.getByTestId('tl-view').evaluate((el) => ({ pps: Number(el.getAttribute('data-pps')), scroll: el.scrollLeft }));
  return v!.x + t * pps - scroll;
};

test('scrub bar: hover shows a frame + the time, click seeks, drag scrubs; keys', async () => {
  await open('A_换圈子');
  const bar = page.getByTestId('scrub');
  const b = (await bar.boundingBox())!;
  expect(b.width).toBeGreaterThan(600); // full width under the video, not a short bar
  await page.mouse.move(b.x + b.width * 0.25, b.y + b.height / 2);
  const tag = page.getByTestId('scrub-tag');
  await expect(tag).toBeVisible();
  await expect(tag).toContainText('0:02');
  await expect(tag.locator('.pv')).toHaveCount(1); // the frame preview from the sprite sheet
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height / 2);
  await near(DUR * 0.5);
  // drag from 50 % to 75 %
  await page.mouse.move(b.x + b.width * 0.5, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.75, b.y + b.height / 2, { steps: 6 });
  await page.mouse.up();
  await near(DUR * 0.75);
  // the timeline's playhead follows
  const ph = (await page.getByTestId('tl-playhead').boundingBox())!;
  expect(Math.abs(ph.x + ph.width / 2 - (await tlX(DUR * 0.75)))).toBeLessThan(4);
  // keys: Home / End, → one frame, Shift+← one second
  await page.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => undefined);
  await page.keyboard.press('Home');
  await near(0, 0.05);
  await page.keyboard.press('ArrowRight');
  await near(1 / 30, 0.02);
  await page.keyboard.press('End');
  await near(DUR, 0.1);
  await page.keyboard.press('Shift+ArrowLeft');
  await near(DUR - 1, 0.1);
});

test('timeline: click a lane to seek, drag the playhead, ruler, lanes never overlap their labels', async () => {
  await open('A_换圈子');
  const film = (await page.getByTestId('tl-film').boundingBox())!;
  await page.mouse.click(await tlX(1.5), film.y + film.height / 2);
  await near(1.5);
  // the gutter labels sit left of every lane
  const gutter = (await page.locator('.tl2-gutter').boundingBox())!;
  const view = (await page.getByTestId('tl-view').boundingBox())!;
  expect(gutter.x + gutter.width).toBeLessThanOrEqual(view.x + 1);
  await expect(page.locator('.tl2-gutter')).toContainText('画面');
  await expect(page.locator('.tl2-gutter')).toContainText('逐字稿');
  // filmstrip tiles and the waveform canvas are there; ruler has labelled ticks
  expect(await page.locator('[data-testid=tl-film] > i').count()).toBeGreaterThan(5);
  await expect(page.locator('[data-testid=tl-wave] canvas')).toHaveCount(1);
  expect(await page.locator('[data-testid=tl-ruler] .mj').count()).toBeGreaterThan(2);
  // drag the playhead knob to 6 s
  const ph = (await page.getByTestId('tl-playhead').boundingBox())!;
  await page.mouse.move(ph.x + ph.width / 2, ph.y + 6);
  await page.mouse.down();
  await page.mouse.move(await tlX(6), ph.y + 6, { steps: 8 });
  await page.mouse.up();
  await near(6);
  // dragging on the ruler scrubs too
  const r = (await page.getByTestId('tl-ruler').boundingBox())!;
  await page.mouse.move(await tlX(2), r.y + r.height / 2);
  await page.mouse.down();
  await page.mouse.move(await tlX(3), r.y + r.height / 2, { steps: 5 });
  await page.mouse.up();
  await near(3);
});

test('zoom: + doubles, Fit returns, ⌘+ / ⌘0, the view scrolls and seeking still lands', async () => {
  await open('A_换圈子');
  const view = page.getByTestId('tl-view');
  const pps = async () => Number(await view.getAttribute('data-pps'));
  const fit = await pps();
  await expect(page.getByTestId('tl-fit')).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('tl-zoom-in').click();
  await expect.poll(pps).toBeCloseTo(fit * 2, 1);
  await page.getByTestId('tl-zoom-in').click();
  await expect.poll(pps).toBeCloseTo(Math.min(400, fit * 4), 1); // capped at 400 px/s
  expect(await view.evaluate((el) => el.scrollWidth > el.clientWidth + 10)).toBe(true);
  // seeking by clicking still maps px -> time at this zoom
  const film = (await page.getByTestId('tl-film').boundingBox())!;
  const x = Math.min(film.x + film.width - 20, await tlX(await now() + 0.5));
  const want = await view.evaluate((el, cx) => (cx - el.getBoundingClientRect().left + el.scrollLeft) / Number(el.getAttribute('data-pps')), x);
  await page.mouse.click(x, film.y + film.height / 2);
  await near(want, 0.1);
  await page.getByTestId('tl-fit').click();
  await expect.poll(pps).toBeCloseTo(fit, 2);
  // keyboard zoom (focus outside the composer)
  await page.mouse.click(film.x + 5, film.y + film.height / 2);
  await page.keyboard.press('Meta+=');
  await expect.poll(pps).toBeCloseTo(fit * 2, 1);
  await page.keyboard.press('Meta+0');
  await expect.poll(pps).toBeCloseTo(fit, 2);
});

test('「听一遍这条片子」 on a clip without a transcript: words appear at their times', async () => {
  await open('B_底气');
  await expect(page.locator('[data-testid=tl-words] .w')).toHaveCount(0);
  const btn = page.getByTestId('tl-transcribe');
  await expect(btn).toBeVisible();
  await expect(btn).toContainText('听一遍这条片子');
  await btn.click();
  await expect(page.locator('[data-testid=tl-words] .w').first()).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId('tl-transcribe')).toHaveCount(0);
  // the words are kept: a reload still has them
  await open('B_底气');
  expect(await page.locator('[data-testid=tl-words] .w').count()).toBeGreaterThan(3);
});

test('drag across words -> a selection on the timeline + the chip in the composer', async () => {
  await open('A_换圈子', 'en');
  const lane = (await page.getByTestId('tl-words').boundingBox())!;
  await page.mouse.move(await tlX(0.7), lane.y + lane.height / 2);
  await page.mouse.down();
  await page.mouse.move(await tlX(3.2), lane.y + lane.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByTestId('tl-selection')).toBeVisible();
  await expect(page.getByTestId('ctx-sel')).toBeVisible();
  await expect(page.getByTestId('ctx-sel')).toContainText('0:00.6');
  await expect(page.getByTestId('ctx-sel')).toContainText('0:03.5'); // snapped outward to whole words
  const text = await page.evaluate(() => document.body.innerText);
  expect(text.match(/\btl\.[a-zA-Z][\w.-]+/g) ?? []).toEqual([]);
});
