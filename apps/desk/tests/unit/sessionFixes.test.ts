// Found making a real promo in Reelfold 0.2.1 (fix/aigc-session-bugs): an author checkpoint read "Write your part"
// with a "☑ 1 0" row, the Review tab said "Nothing to review" next to "Needs you", an agent's live status never showed,
// "Claude Code did not answer" hid why it fell back, a broken Homebrew node read "Part of Reelfold didn't start", and
// a re-registered project only appeared after navigating away and back.
import { afterEach, describe, expect, it } from 'vitest';
import type { InboxItem } from '../../src/shared/v04';
import type { LiveStatus, PilotFailure } from '../../src/shared/v02';
import { fallbackNotice } from '../../src/shared/aiRoutes';
import { setLang, t } from '../../src/renderer/src/i18n';
import { authorHelp, authorTitle, inboxSub, inboxTitle } from '../../src/renderer/src/lib/inboxView';
import { agoText, liveLine, liveMeta, pendingFor, STALE_S } from '../../src/renderer/src/lib/liveStatus';
import { stampChanged } from '../../src/renderer/src/lib/history';
import { failureReason } from '../../src/renderer/src/v4/Failure';

afterEach(() => setLang('en'));

const author: InboxItem = {
  key: 'a'.repeat(16),
  kind: 'author',
  group: 'other',
  project: { id: 'p1', name: 'AIGC 评测', kind: 'project' },
  code: 'checkpoint.author',
  params: { n: 0 },
  text: '保留片段',
  options: [],
  source: 'engine',
  labels: { zh: '保留片段', en: 'Keep spans' },
  author: {
    labels: { zh: '确认保留内容', en: 'Check what’s kept' },
    recipe: 'promo-recut',
    checkpoint: 'keep',
    state: 'drafted',
    can_draft: true,
    review: {
      kind: 'keep-spans',
      by: 'ai',
      summary: { code: 'draft.keep', params: { kept: 580, total: 764, cuts: ['the unfinished opening', 'the joke detour', 'the Hedra part'], n: 3 } },
      segments: [],
      kept_s: 580,
      total_s: 764,
    },
    file: '/home/me/.config/vstudio/projects/dfab/01-AIGC/items/AIGC/promo.config.yaml',
    exists: true,
  },
};

describe('author checkpoints in the Inbox', () => {
  it('read as plain words: the step, what to do, what the draft keeps - never the file, YAML or raw seconds', () => {
    expect(inboxTitle(author)).toBe('Check what’s kept');
    expect(authorTitle(author)).toBe('Check what’s kept');
    expect(authorHelp(author)).toMatch(/Crossed-out sentences are cut/);
    expect(inboxSub(author)).toBe('Keeps 9:40 of 12:44 — cuts the unfinished opening, the joke detour, the Hedra part');
    for (const s of [inboxTitle(author), authorHelp(author), inboxSub(author)]) expect(s).not.toMatch(/yaml|cut\.body|promo\.config|\//i);
    setLang('zh-CN');
    expect(inboxTitle(author)).toBe('确认保留内容');
    expect(inboxSub(author)).toMatch(/^保留 12:44 里的 9:40——剪掉/);
  });
  it('a step nothing is drafted for says so (and the generic title when the desk has none for it)', () => {
    const bare = { ...author, labels: null, text: null, author: { ...author.author!, recipe: 'x', checkpoint: 'y', labels: {}, state: 'template' as const, review: null } };
    expect(inboxTitle(bare)).toBe(t('draft.titleAny'));
    expect(authorHelp(bare)).toBe(t('draft.lead.none'));
    expect(inboxSub(bare)).toBe(t('draft.lead.none'));
    expect(inboxSub({ ...bare, author: { ...bare.author, drafting: true } })).toBe(t('draft.drafting'));
  });
});

describe('the Review tab lists what waits besides clip reviews', () => {
  it('checkpoints of this project, not reviews / failures / other projects', () => {
    const review = { ...author, key: 'b'.repeat(16), kind: 'review', group: 'review' as const, author: null };
    const other = { ...author, key: 'c'.repeat(16), project: { id: 'p2', name: 'x' } };
    const failed = { ...author, key: 'd'.repeat(16), kind: 'failed', group: 'failed' as const };
    expect(pendingFor([author, review, other, failed], 'p1').map((x) => x.key)).toEqual([author.key]);
  });
});

describe("an agent's live status on the project page", () => {
  const now = 1_000_000;
  const live = (o: Partial<LiveStatus>): LiveStatus => ({ state: 'running', status: 'running', needs_you: false, heartbeat: now - 12, ...o });
  it('shows the message, the step, progress and how fresh it is', () => {
    const l = liveLine(live({ message: 'Rendering the promo', stage: 'render', progress: 0.42 }), now)!;
    expect(l).toMatchObject({ message: 'Rendering the promo', stage: 'render', pct: 42, stale: false });
    expect(liveMeta(l)).toBe('Step: render · 42% · updated 12 s ago');
    expect(liveLine(live({ progress: 87 }), now)!.pct).toBe(87); // a percentage works too
  });
  it('says when the heartbeat went quiet, and nothing when there is nothing live', () => {
    const l = liveLine(live({ message: 'x', heartbeat: now - STALE_S - 300 }), now)!;
    expect(l.stale).toBe(true);
    expect(liveMeta(l)).toBe('no update for 7 min');
    expect(liveLine(live({ state: 'done', message: 'x' }), now)).toBeNull();
    expect(liveLine(live({}), now)).toBeNull();
    expect(liveLine(null, now)).toBeNull();
    expect(agoText(7200)).toBe('2 h');
  });
});

describe('why another AI answered', () => {
  it('a timeout names the limit, a skip says it was skipped', () => {
    const fb = { from: 'claude-code', to: 'codex', code: 'timeout', error: 'claude CLI timed out after 90.0 s' };
    expect(fallbackNotice(fb)).toMatchObject({ key: 'aiacc.fb.timeout', seconds: 90 });
    expect(t('aiacc.fb.timeout', { from: 'Claude Code', to: 'Codex', seconds: 90 })).toBe('Claude Code didn’t answer within 90 s, so Codex was used this time');
    expect(fallbackNotice({ ...fb, error: 'claude-code: timed out on a call a few minutes ago', cached: true })!.key).toBe('aiacc.fb.skipped');
    expect(fallbackNotice({ ...fb, code: 'rate-limited' })!.key).toBe('aiacc.fb.limited');
    expect(fallbackNotice({ ...fb, code: 'failed', error: 'x' })!.key).toBe('aiacc.fb.failed');
    expect(fallbackNotice({ ...fb, code: 'auth-expired' })!.key).toBe('aiacc.fb.expired');
  });
});

describe('a failed step names the tool and the fix', () => {
  const f = (o: Partial<PilotFailure>): PilotFailure => ({ state: 'failed', code: 'unknown', provider: null, error: 'x', at: 1, ...o });
  it('tool codes from the engine', () => {
    expect(failureReason(f({ code: 'tool-node', tool: 'node', fix: 'brew-reinstall-node' }))).toBe(
      'Rendering needs Node.js, and the Node.js on this Mac didn’t run. To fix it, run “brew reinstall node” in Terminal, then try again.',
    );
    expect(failureReason(f({ code: 'tool-broken', params: { tool: 'node', path: '/opt/homebrew/bin/node', fix: 'brew reinstall node' } }))).toBe(
      'Node.js on this Mac didn’t run (/opt/homebrew/bin/node). To fix it: brew reinstall node',
    );
    expect(failureReason(f({ code: 'tool-missing', params: { tool: 'ffmpeg' } }))).toBe('ffmpeg isn’t installed on this Mac.');
    expect(failureReason(f({ code: 'stage', stage: 'render' }))).toMatch(/“render” step/);
    expect(failureReason(f({ code: 'tool-something-new' }))).toBe(t('fail.reason.unknown'));
    setLang('zh-CN');
    expect(failureReason(f({ code: 'tool-ffmpeg', tool: 'ffmpeg', fix: 'install-ffmpeg' }))).toMatch(/ffmpeg.*brew install ffmpeg/);
  });
  it('"Part of Reelfold didn\'t start" only for the engine not starting', () => {
    expect(failureReason(f({ code: 'engine' }))).toMatch(/didn’t start/);
    expect(failureReason(f({ code: 'tool-node', tool: 'node' }))).not.toMatch(/didn’t start/);
  });
});

describe('All projects follows the registry', () => {
  it('reloads when the stamp moves (not on the first one)', () => {
    expect(stampChanged(null, 'a')).toEqual({ reload: false, stamp: 'a' });
    expect(stampChanged('a', 'a')).toEqual({ reload: false, stamp: 'a' });
    expect(stampChanged('a', 'b')).toEqual({ reload: true, stamp: 'b' });
    expect(stampChanged('a', undefined)).toEqual({ reload: false, stamp: 'a' });
  });
});
