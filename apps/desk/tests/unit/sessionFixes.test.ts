// Found making a real promo in Reelfold 0.2.1 (fix/aigc-session-bugs): an author checkpoint read "Write your part"
// with a "☑ 1 0" row, the Review tab said "Nothing to review" next to "Needs you", an agent's live status never showed,
// "Claude Code did not answer" hid why it fell back, a broken Homebrew node read "Part of Reelfold didn't start", and
// a re-registered project only appeared after navigating away and back.
import { afterEach, describe, expect, it } from 'vitest';
import type { InboxItem } from '../../src/shared/v04';
import type { LiveStatus, PilotFailure } from '../../src/shared/v02';
import { fallbackNotice } from '../../src/shared/aiRoutes';
import { setLang, t } from '../../src/renderer/src/i18n';
import { authorHelp, authorTitle, inboxSub, inboxTitle, shortPath } from '../../src/renderer/src/lib/inboxView';
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
    labels: { zh: '保留片段', en: 'Keep spans' },
    help: { zh: '在 promo.config.yaml 写 cut.body / cut.outro（原片秒数）', en: 'Write cut.body / cut.outro KEEP spans (raw seconds) in promo.config.yaml' },
    file: '/Users/x/.config/vstudio/projects/dfab/01-AIGC/items/AIGC/promo.config.yaml',
    exists: true,
    template: null,
    doc: '/Applications/Reelfold.app/Contents/Resources/runtime/vstudio/workflows/promo-recut/WORKFLOW.md',
    preview: 'talk: inputs/talk.mp4\ncut:\n  body: []',
    more: false,
    preview_of: 'file',
  },
};

describe('author checkpoints in the Inbox', () => {
  it('read as the checkpoint label + help + file, never "Write your part" or a raw option index', () => {
    expect(inboxTitle(author)).toBe('Keep spans');
    expect(authorTitle(author)).toBe('Keep spans');
    expect(authorHelp(author)).toMatch(/KEEP spans/);
    expect(inboxSub(author)).toBe('promo.config.yaml');
    expect(shortPath(author.author!.file)).toBe('…/items/AIGC/promo.config.yaml');
    setLang('zh-CN');
    expect(inboxTitle(author)).toBe('保留片段');
    expect(authorHelp(author)).toMatch(/原片秒数/);
  });
  it('fall back to the help line and the generic title when the engine gave none', () => {
    const bare = { ...author, labels: null, text: null, author: { ...author.author!, labels: {}, help: {} } };
    expect(inboxTitle(bare)).toBe(t('checkpoint.author'));
    expect(authorHelp(bare)).toBe(t('inbox.author.lead'));
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
