// Project archive: the 已归档 tab (counts, dimmed cards with their date and Restore, search / type inside it), the
// archive flow (undo = restore, a running project refused before asking the engine), the restore flow, the client's
// routes, and the words in every language.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HistoryDoc, HistoryItem } from '../../src/shared/v02';
import { EngineClient } from '../../src/shared/engineClient';
import { LOCALES, setLang, t } from '../../src/renderer/src/i18n';
import { activeItems } from '../../src/renderer/src/lib/inboxView';
import { archiveEn } from '../../src/renderer/src/i18n/locales/archive';
import { archivedLine, archiveFlow, isRunning, noMatchText, restoreFlow, shownProjects } from '../../src/renderer/src/lib/archive';

const hist = vi.hoisted(() => ({ value: null as unknown }));
vi.mock('../../src/renderer/src/lib/history', () => ({ useHistory: () => hist.value }));
vi.mock('../../src/renderer/src/lib/engine', () => ({
  useEngine: () => ({ client: null, subscribe: () => () => undefined }),
  useLoad: () => ({ data: { watch: [] }, error: null, loading: false, reload: () => undefined, setData: () => undefined }),
}));
vi.mock('../../src/renderer/src/lib/prefs', async (orig) => ({ ...(await orig<object>()), useAgencyMode: () => false }));
vi.mock('../../src/renderer/src/lib/inbox', () => ({ useInbox: () => ({ items: [], all: [] }) }));
vi.mock('../../src/renderer/src/v4/ui', () => ({ useUi: () => ({ toast: () => undefined, menu: () => undefined, setPrefill: () => undefined }) }));

function item(id: string, over: Partial<HistoryItem> = {}): HistoryItem {
  return {
    kind: 'project',
    type: 'talkinghead',
    id,
    dir: `/Users/me/v/${id}`,
    name: id,
    recipe: 'talkinghead',
    client: null,
    created: 1,
    updated: 1_780_000_000,
    counts: { total: 2, green: 2, red: 0, approved: 0, done: 2, failed: 0 },
    status: 'done',
    thumb: null,
    sources: ['engine'],
    opened: false,
    openable: true,
    ...over,
  };
}
const doc = (items: HistoryItem[], archived?: number | boolean): HistoryDoc => ({ items, watch: [], at: 1, archived });

describe('which cards a tab shows', () => {
  const live = [item('promo-a', { type: 'promo' }), item('vlog-b', { type: 'vlog', status: 'in-progress' })];
  const arch = [item('old-promo', { type: 'promo', archived: true, archived_at: 1_780_000_000 }), item('wrong-vlog', { type: 'vlog', archived: true })];
  const base = { q: '', type: '', bucketOf: (i: HistoryItem) => (i.status === 'done' ? 'done' : 'running') };

  it('Archived reads the archived list, the other tabs the live one', () => {
    expect(shownProjects(live, arch, { ...base, f: 'all' }).map((i) => i.id)).toEqual(['promo-a', 'vlog-b']);
    expect(shownProjects(live, arch, { ...base, f: 'done' }).map((i) => i.id)).toEqual(['promo-a']);
    expect(shownProjects(live, arch, { ...base, f: 'archived' }).map((i) => i.id)).toEqual(['old-promo', 'wrong-vlog']);
  });

  it('search and type work inside Archived', () => {
    expect(shownProjects(live, arch, { ...base, f: 'archived', q: 'WRONG' }).map((i) => i.id)).toEqual(['wrong-vlog']);
    expect(shownProjects(live, arch, { ...base, f: 'archived', type: 'promo' }).map((i) => i.id)).toEqual(['old-promo']);
    expect(shownProjects(live, arch, { ...base, f: 'archived', q: 'promo', type: 'vlog' })).toEqual([]);
  });

  it('the archived date line', () => {
    setLang('en');
    expect(archivedLine({ archived_at: 1_780_000_000 })).toMatch(/^Archived \w+ \d+$/);
    expect(archivedLine({ archived_at: null })).toBe('Archived');
    setLang('zh-CN');
    expect(archivedLine({ archived_at: 1_780_000_000 })).toMatch(/归档$/);
    setLang('en');
  });
});

describe('archive / restore flows', () => {
  const fake = () => {
    const calls: [string, string[]][] = [];
    return {
      calls,
      archiveHistory: vi.fn(async (d: string[]) => void calls.push(['archive', d])),
      restoreHistory: vi.fn(async (d: string[]) => void calls.push(['restore', d])),
    };
  };
  const toasts = () => {
    const out: { text: string; opts?: { undo?: () => unknown; error?: boolean } }[] = [];
    return { out, toast: (text: string, opts?: { undo?: () => unknown; error?: boolean }) => void out.push({ text, opts }) };
  };
  beforeEach(() => setLang('en'));

  it('archives in one request, toasts 「Archived N」 with an undo that restores', async () => {
    const c = fake();
    const ui = toasts();
    const reload = vi.fn();
    const ok = await archiveFlow(c, ui, [item('a'), item('b')], reload);
    expect(ok).toBe(true);
    expect(c.calls).toEqual([['archive', ['/Users/me/v/a', '/Users/me/v/b']]]);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(ui.out[0].text).toBe('Archived 2 projects Nothing was deleted — find it under Archived.');
    expect(ui.out[0].opts?.error).toBeFalsy();
    await ui.out[0].opts!.undo!();
    expect(c.calls[1]).toEqual(['restore', ['/Users/me/v/a', '/Users/me/v/b']]);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it('a running project is refused before the engine is asked; nothing archived', async () => {
    const c = fake();
    const ui = toasts();
    const running = item('rendering', { live: { state: 'running', status: 'running', needs_you: false } as HistoryItem['live'] });
    expect(isRunning(running)).toBe(true);
    expect(isRunning(item('p', { pilot: { started: 1, provider: null } }))).toBe(true);
    expect(isRunning(item('w', { live: { state: 'waiting', status: 'waiting', needs_you: true } as HistoryItem['live'] }))).toBe(false);
    expect(await archiveFlow(c, ui, [item('a'), running], vi.fn())).toBe(false);
    expect(c.calls).toEqual([]);
    expect(ui.out[0]).toMatchObject({ text: '“rendering” is still running. Wait until it finishes (or stop it), then archive it.', opts: { error: true } });
  });

  it('the engine refusing (a run started meanwhile) shows its message', async () => {
    const c = fake();
    c.archiveHistory.mockRejectedValueOnce(new Error('still running: x'));
    const ui = toasts();
    expect(await archiveFlow(c, ui, [item('x')], vi.fn())).toBe(false);
    expect(ui.out[0]).toMatchObject({ text: 'still running: x', opts: { error: true } });
  });

  it('restores, toasts 「Restored N」 with an undo that archives again', async () => {
    const c = fake();
    const ui = toasts();
    expect(await restoreFlow(c, ui, [item('old', { archived: true })], vi.fn())).toBe(true);
    expect(c.calls).toEqual([['restore', ['/Users/me/v/old']]]);
    expect(ui.out[0].text).toBe('Restored 1 project');
    await ui.out[0].opts!.undo!();
    expect(c.calls[1]).toEqual(['archive', ['/Users/me/v/old']]);
  });
});

describe('the empty state of a filter', () => {
  afterEach(() => setLang('en'));

  it('without search text: what is missing, per filter', () => {
    setLang('en');
    expect(noMatchText({ f: 'running', q: '', type: '' })).toBe('No running projects');
    expect(noMatchText({ f: 'you', q: '  ', type: '' })).toBe('Nothing needs you right now');
    expect(noMatchText({ f: 'done', q: '', type: '' })).toBe('No finished projects yet');
    expect(noMatchText({ f: 'failed', q: '', type: '' })).toBe('No failed projects');
    expect(noMatchText({ f: 'archived', q: '', type: 'promo' })).toBe('No archived projects match these filters');
    expect(noMatchText({ f: 'all', q: '', type: 'batch' })).toBe('No “Batch” projects');
    for (const f of ['all', 'running', 'you', 'done', 'failed', 'archived'] as const) expect(noMatchText({ f, q: '', type: '' })).not.toMatch(/type\.|projects\./);
  });

  it('with search text: the query, whatever the filter', () => {
    setLang('en');
    expect(noMatchText({ f: 'running', q: 'promo ', type: '' })).toBe('Nothing matches “promo”.');
    setLang('zh-CN');
    expect(noMatchText({ f: 'running', q: '', type: '' })).toBe('没有运行中的项目');
    expect(noMatchText({ f: 'all', q: '口播', type: '' })).toBe('没有找到「口播」。');
    setLang('fr');
    expect(noMatchText({ f: 'running', q: '', type: '' })).toBe('Aucun projet en cours');
    expect(noMatchText({ f: 'done', q: 'x', type: '' })).toMatch(/^Aucun résultat pour «\s?x\s?»\.$/u);
  });

  it('every locale has every empty-state string', () => {
    for (const l of Object.values(LOCALES))
      for (const f of ['all', 'running', 'you', 'done', 'failed', 'archived', 'type']) expect(l.messages[`projects.none.${f}` as keyof typeof l.messages]).toBeTruthy();
  });
});

describe('the inbox and archived projects', () => {
  const x = (key: string, archived?: boolean) => ({ key, archived }) as unknown as import('../../src/shared/v04').InboxItem;

  it('an archived project\'s items leave the Inbox / Home / badge / triage list; restored ones come back', () => {
    expect(activeItems([x('a'), x('b', true), x('c')]).map((i) => i.key)).toEqual(['a', 'c']);
    expect(activeItems([x('a'), x('b'), x('c')]).map((i) => i.key)).toEqual(['a', 'b', 'c']);
  });
});

describe('the Projects page', () => {
  const store = new Map<string, string>();
  beforeEach(() => {
    setLang('en');
    store.clear();
    store.set('v4.pview', 'grid'); // the grid view (the control room is the other one)
    vi.stubGlobal('sessionStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v) });
  });
  afterEach(() => vi.unstubAllGlobals());

  const render = async () => {
    const { Projects } = await import('../../src/renderer/src/v4/Projects');
    return renderToStaticMarkup(createElement(Projects));
  };

  it('the Archived tab is last in the filter row, with the count the list reports', async () => {
    hist.value = { data: doc([item('a'), item('b')], 3), archived: null, reload: () => undefined, wantArchived: () => undefined, live: [] };
    const html = await render();
    const tabs = [...html.matchAll(/data-v="(\w+)"[^>]*>([^<]*)</g)].map((m) => [m[1], m[2]]);
    expect(tabs.at(-1)).toEqual(['archived', 'Archived 3']);
    expect(html.match(/data-testid="project-card"/g)).toHaveLength(2);
    expect(html).not.toContain('archived-card');
  });

  it('no Archived tab while nothing is archived', async () => {
    hist.value = { data: doc([item('a')], 0), archived: null, reload: () => undefined, wantArchived: () => undefined, live: [] };
    expect(await render()).not.toContain('data-v="archived"');
  });

  it('in Archived: dimmed cards with the archived date and Restore; they still link to the project', async () => {
    store.set('v4.pf', 'archived');
    const arch = [item('old-cut', { archived: true, archived_at: 1_780_000_000 }), item('legacy', { archived: true, archived_at: null })];
    hist.value = { data: doc([item('a')], 2), archived: doc(arch, true), reload: () => undefined, wantArchived: () => undefined, live: [] };
    const html = await render();
    expect(html).toContain('class="pgrid archived"');
    expect(html.match(/class="pcard-wrap archived"/g)).toHaveLength(2);
    expect(html.match(/data-testid="project-restore"/g)).toHaveLength(2);
    expect(html).toMatch(/Archived \w+ \d+/);
    expect(html).toContain('href="#/p/old-cut"');
    expect(html).toContain('Archived 2');
    expect(html).not.toContain('/v/a"'); // the live project is not in this tab
  });

  it('Running with no running project and no search: says so (never 「Nothing matches “type.”」)', async () => {
    store.set('v4.pf', 'running');
    hist.value = { data: doc([item('a'), item('b')], 0), archived: null, reload: () => undefined, wantArchived: () => undefined, live: [] };
    const html = await render();
    expect(html).toContain('No running projects');
    expect(html).not.toContain('type.');
    expect(html).not.toContain('Nothing matches');
  });

  it('in Archived with nothing archived: a calm empty state', async () => {
    store.set('v4.pf', 'archived');
    hist.value = { data: doc([item('a')], 0), archived: doc([], true), reload: () => undefined, wantArchived: () => undefined, live: [] };
    expect(await render()).toContain(t('projects.archivedEmpty'));
  });
});

describe('client + words', () => {
  it('archive / restore post dirs[]; the archived list asks archived=1', async () => {
    const f = vi.fn(async (_u: string, _i?: RequestInit) => new Response('{"items":[],"watch":[],"at":1,"archived":true}', { status: 200 }));
    const c = new EngineClient('app://desk', 'tok'.repeat(20), f);
    await c.archiveHistory(['/a', '/b']);
    await c.restoreHistory(['/a']);
    await c.history({ archived: true, q: 'x' });
    expect(f.mock.calls.map(([u, i]) => [u.replace('app://desk', ''), i?.method, i?.body ?? null])).toEqual([
      ['/api/history/archive', 'POST', JSON.stringify({ dirs: ['/a', '/b'] })],
      ['/api/history/restore', 'POST', JSON.stringify({ dirs: ['/a'] })],
      ['/api/history?archived=1&q=x', 'GET', null],
    ]);
  });

  it('every language has the archive words (归档 / 恢复 / Archiver)', () => {
    for (const lang of Object.keys(LOCALES) as (keyof typeof LOCALES)[]) {
      for (const k of Object.keys(archiveEn)) expect(LOCALES[lang].messages[k as keyof typeof archiveEn], `${lang} ${k}`).toBeTruthy();
    }
    expect([LOCALES['zh-CN'].messages['projects.archive'], LOCALES['zh-CN'].messages['projects.restore']]).toEqual(['归档', '恢复']);
    expect(LOCALES.fr.messages['projects.archive']).toBe('Archiver');
    expect(LOCALES['zh-CN'].messages['projects.f.archived']).toBe('已归档 {n}');
  });
});
