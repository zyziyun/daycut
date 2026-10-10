// Strict i18n over every main screen, in en / zh-CN / fr, with the REAL engine sidecar (no mock engine) and real
// projects (fixture/real_project.py: a tiny synthetic talk + the engine tests' fake transcriber, the only fakes):
// one parked at a question mid-run (live status, Inbox), one made on autopilot (the AI's decisions, a clip, a post).
// The 2026-10 review found engine words on screen; every screen fails on:
//   - a missing key (⟦key⟧ in strict mode) or a raw key ("pb.ws.title_too_long")
//   - the engine's own status words ("0/1 jobs", "done: 3 jobs", "checkpoint: publish") and step ids ("s003:export",
//     "talk:asr", 「asr」), job ids as clip names ("第 talk 条"), "Xiaohongshu · vertical"
//   - in Chinese: English words that are not names (brands, platforms, file types) or her own content
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-i18n-'));
const REPO = path.resolve(import.meta.dirname, '../../../..');
const FIXTURE = path.join(import.meta.dirname, 'fixture/real_project.py');
const SHOTS = process.env.I18N_SHOTS || path.join(tmp, 'shots');
const engineEnv = {
  VSTUDIO_HOME: path.join(tmp, 'vhome'),
  VSTUDIO_BATCH_BENCH: path.join(tmp, 'bench.json'),
  VSTUDIO_DEFAULT_PERSONA: '1',
  VSTUDIO_LLM_PROVIDER: 'none',
  ...Object.fromEntries(['SEGMENT_PLAN', 'PROOFREAD', 'GLOSSARY', 'COPY', 'SCRIPT', 'PLANNER', 'INTAKE', 'OUTPUT_EDIT'].map((t) => [`VSTUDIO_LLM_${t}_PROVIDER`, 'none'])),
};
type Fx = { dir: string; items: string[]; status: string; pending: string[][] };
let parked: Fx;
let made: Fx;
const ids: Record<string, string> = {};

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  test.setTimeout(420000);
  fs.mkdirSync(SHOTS, { recursive: true });
  const env: NodeJS.ProcessEnv = { ...process.env, ...engineEnv, PYTHONPATH: path.join(REPO, 'lib') };
  for (const k of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'VSTUDIO_PERSONA']) delete env[k];
  const fx = (root: string, ...args: string[]) => {
    fs.mkdirSync(root, { recursive: true });
    const out = execFileSync(process.env.DESK_PYTHON || 'python3', [FIXTURE, root, ...args], { env: { ...env, VSTUDIO_TEST_TRUTH: path.join(root, 'truth.json') }, encoding: 'utf8' });
    return JSON.parse(out.trim().split('\n').pop()!) as Fx;
  };
  parked = fx(path.join(tmp, 'parked'), '--pilot'); // waits for her at the filler question, the 2nd clip unmade
  made = fx(path.join(tmp, 'made'), '--autopilot'); // made to the end, the AI's (rules') decisions logged
  expect(parked.pending.length).toBeGreaterThan(0);
  expect(made.status).toBe('done');
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...env, VSTUDIO_TEST_TRUTH: path.join(tmp, 'parked', 'truth.json'), PYTHONPATH: '', DESK_ENGINE_MOCK: '', DESK_USER_DATA: path.join(tmp, 'profile'), DESK_HISTORY_WATCH: '', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  expect((await page.evaluate(() => window.desk.engineInfo())).mode).toBe('real');
  await page.evaluate(() => window.desk.publish.addAccount('xiaohongshu', 'main'));
  await expect.poll(async () => (await api<{ items: { dir: string }[] }>('/api/history')).items.length, { timeout: 30000 }).toBeGreaterThanOrEqual(2);
  const hist = await api<{ items: { id: string; dir: string }[] }>('/api/history');
  for (const [k, f] of [['parked', parked], ['made', made]] as const) ids[k] = hist.items.find((i) => fs.realpathSync(i.dir) === fs.realpathSync(f.dir))!.id;
  // a post of the made clip with her own 小红书 title, too long: the board's "title too long" warning
  const clips = await api<{ clips: { id: string }[] }>(`/api/outputs/${ids.made}`);
  const at = new Date(Date.now() + 86400_000);
  at.setHours(20, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, '0');
  const when = `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T20:00`;
  const r = await api<{ ids: string[] }>('/api/calendar/many', { posts: [{ item: ids.made, clip: clips.clips[0].id, platform: 'xiaohongshu', at: when }] });
  await api(`/api/calendar/${r.ids[0]}`, { platform_title: '一条录像变成一周的内容一条录像变成一周的内容一条' });
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const api = <T,>(p: string, body?: unknown) =>
  page.evaluate(
    async ([u, b]) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + u, { method: b ? 'POST' : 'GET', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined });
      return r.json();
    },
    [p, body] as const,
  ) as Promise<T>;

/** Names that stay as they are in every language (brands, platforms, AI tools, file types, keys). */
const NAMES = [
  'Reelfold', 'Studio', 'YouTube', 'Shorts', 'TikTok', 'Instagram', 'Reels', 'Threads', 'Facebook', 'LinkedIn', 'Pinterest', 'Snapchat', 'Reddit', 'Dailymotion', 'Kwai', 'RedNote',
  'AI', 'Claude', 'Code', 'Codex', 'ChatGPT', 'OpenAI', 'Gemini', 'Ollama', 'API', 'Whisper', 'MLX', 'ffmpeg', 'Node', 'macOS', 'Mac', 'Windows', 'GitHub', 'MIT',
  'mp4', 'mov', 'jpg', 'png', 'srt', 'vtt', 'zip', 'JSON', 'CSV', 'Markdown', 'XML', 'EDL', 'OTIO', 'Premiere', 'Final', 'Cut', 'Pro', 'HyperFrames', 'Veo', 'Seedance', 'MiniMax', 'DeepSeek', 'Kimi', 'Anthropic',
  'Esc', 'Enter', 'Tab', 'Shift', 'Cmd', 'Ctrl', 'Alt', 'Delete', 'Backspace', 'Space', 'OK', 'URL', 'LUFS', 'HDR', 'CC0', 'Max', 'Plus',
];

async function scan(lang: string, content: string[]) {
  return page.evaluate(
    ([lang, names, content]) => {
      const out: string[] = [];
      const all = document.body.innerText;
      const missing = all.match(/⟦[^⟧]+⟧/g);
      if (missing) out.push(`missing: ${[...new Set(missing)].join(', ')}`);
      const rawKeys = all.match(/\b(?:home|plan|inbox|projects|project|clip|ai|ap|hub|live|ct|pb|pl|pub|fail|checkpoint|player|editor|ce|te|palette|keys|status|nav|set|em|issue|focus|rec|create|draft|st|ci|vs)\.[a-zA-Z][\w-]*(?:\.[\w-]+)*\b/g);
      if (rawKeys) out.push(`raw keys: ${[...new Set(rawKeys)].join(', ')}`);
      // the visible words of the UI itself: her content (titles, names, prompts, captions, file names) is skipped
      const skip = '[lang]:not(html), .clamp1, .clamp2, kbd, code, pre, input, textarea, video, [data-content], .ce-chat, .chat, .tp, [data-testid="transcript"], [data-testid="player"]';
      const texts: string[] = [];
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const el = n.parentElement;
        if (!el || !el.offsetParent || el.closest(skip)) continue;
        let s = n.textContent ?? '';
        for (const c of content) if (c) s = s.split(c).join(' ');
        if (s.trim()) texts.push(s);
      }
      const ui = texts.join('\n');
      const engine = ui.match(/\b\d+\/\d+ jobs?\b|\b(?:done|failed|paused): \d+ jobs?\b|\bcheckpoint: |\bjobs?\b|\bs\d{3}\b|\b[a-z][\w-]*:(?:asr|extract|cleanup|apply|compose|export|verify|qc|preview|probe|geometry|cut|render|captions?)\b|「(?:asr|cleanup|compose|export|verify|qc|preview|probe|apply|extract)」|\b(?:vertical|horizontal)\b/g);
      if (engine) out.push(`engine words: ${[...new Set(engine)].join(', ')}`);
      if (/第 ?[a-z][\w-]* ?条/.test(ui)) out.push(`job id as a clip: ${ui.match(/第 ?[a-z][\w-]* ?条/)![0]}`);
      if (lang === 'zh-CN') {
        const bad = new Set<string>();
        for (const s of texts) {
          for (const m of s.matchAll(/[A-Za-z][A-Za-z’'-]{2,}/g)) {
            if (names.includes(m[0])) continue;
            bad.add(`${m[0]} 〔${s.slice(Math.max(0, m.index! - 12), m.index! + m[0].length + 12).replace(/\s+/g, ' ').trim()}〕`);
          }
        }
        if (bad.size) out.push(`English in zh: ${[...bad].slice(0, 12).join(' | ')}`);
      }
      return out;
    },
    [lang, NAMES, content] as const,
  );
}

for (const lang of ['en', 'zh-CN', 'fr'] as const) {
  test(`${lang}: every main screen in words — no raw keys, engine ids or step ids${lang === 'zh-CN' ? ', no English' : ''}`, async () => {
    test.setTimeout(240000);
    await page.evaluate(async (l) => {
      localStorage.setItem('i18n.strict', '1');
      await window.desk.setSettings({ lang: l });
    }, lang);
    await hash('#/'); // the app sidebar (engine status) - Settings has its own sub-nav
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
    // her content may be in any language: the project / clip names, the made clip's own titles and post text
    const content = new Set<string>(['Short talk', 'talk', 'talk2', ...parked.items, ...made.items]);
    for (const id of Object.values(ids)) {
      const d = await api<{ clips: { id: string; title: string; post?: { title: string; body: string; tags: string[] } | null }[] }>(`/api/outputs/${id}`);
      for (const c of d.clips) for (const x of [c.id, c.title, c.post?.title, c.post?.body, ...(c.post?.tags ?? [])]) if (x) content.add(x);
    }
    const madeClip = (await api<{ clips: { id: string }[] }>(`/api/outputs/${ids.made}`)).clips[0].id;
    // the Studio is the app (2026-10 review step 7): its list, its filters, a parked video, a made one, a project's
    // details; then the Calendar, Create and Settings
    const screens: [string, string][] = [
      ['studio', '#/studio'],
      ['studio-needs-you', '#/studio?f=you'],
      ['studio-in-progress', '#/studio?f=run'],
      ['studio-parked', `#/studio/${ids.parked}/talk`],
      ['studio-made', `#/studio/${ids.made}/${encodeURIComponent(madeClip)}`],
      ['details-parked', `#/p/${ids.parked}/clips`],
      ['details-made', `#/p/${ids.made}/clips`],
      ['publish', '#/publish'],
      ['create', '#/create'],
      ['settings', '#/settings'],
    ];
    const problems: string[] = [];
    for (const [name, h] of screens) {
      if (h === 'GRID') {
        await page.evaluate(() => sessionStorage.setItem('v4.pview', 'grid'));
        await hash('#/home');
        await hash('#/projects');
      } else {
        await page.evaluate(() => sessionStorage.setItem('v4.pview', 'live'));
        await hash(h);
      }
      await page.waitForTimeout(1200);
      if (name === 'publish') {
        const tomorrow = new Date(Date.now() + 86400_000);
        if (tomorrow.getDay() === 1) await page.getByTestId('pb-next').click();
        await expect(page.getByTestId('pb-warn').first()).toBeVisible({ timeout: 15000 });
      }
      if (name === 'studio-needs-you') await expect(page.locator('[data-testid=studio-group-you] [data-testid=studio-row]').first()).toBeVisible({ timeout: 30000 });
      await page.screenshot({ path: path.join(SHOTS, `${lang}-${name}.png`) });
      for (const p of await scan(lang, [...content])) problems.push(`${name}: ${p}`);
    }
    expect(problems, lang).toEqual([]);
    await page.evaluate(() => localStorage.removeItem('i18n.strict'));
  });
}
