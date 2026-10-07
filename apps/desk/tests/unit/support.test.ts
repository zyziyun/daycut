// Feedback + problem reports: redaction (no media names, folders, transcripts, prompts, keys, e-mails; code paths
// shortened to ~), the report text, the prefilled GitHub URLs (bug_report.yml field ids, Discussions category,
// length cap), and the problem log (dedupe, dismiss, the opt-in sender only when installed and switched on).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { redact, redactClip } from '../../src/shared/redact';
import { diagnostics, discussionUrl, FEEDBACK_CATEGORY, feedbackBody, issueUrl, MAX_URL, okEmail, problemReport, titleOf, type SupportEnv } from '../../src/shared/support';
import { validateIpc } from '../../src/shared/ipc';
import { WEEK_WORDS } from '../../src/shared/weekPlan';

vi.mock('electron', () => ({ app: { getPath: () => os.tmpdir(), getVersion: () => '0.2.0', isPackaged: false } }));

const HOME = ['', 'Users', 'wendy'].join('/');
const env: SupportEnv = { app: '0.2.0', electron: '44.5.1', chrome: '140.0', node: '24.1', os: 'macOS 26.1', arch: 'arm64', packaged: true, lang: 'zh-CN', engine: 'real', home: HOME };

describe('redact', () => {
  it('shortens home, keeps code paths, hides her folders and media names', () => {
    const s = redact(
      `Error: ffmpeg failed on ${HOME}/Desktop/客户A/raw/婚礼_final.mp4\n    at run (/Applications/Reelfold.app/Contents/Resources/app.asar/out/main/index.cjs:12:5)\n    at x (${HOME}/Desktop/design-ml/video-studio/apps/desk/out/main/index.cjs:40:2)`,
      HOME,
    );
    expect(s).not.toContain('wendy');
    expect(s).not.toContain('客户A');
    expect(s).not.toContain('婚礼');
    expect(s).toContain('<path>.mp4');
    expect(s).toContain('/Applications/Reelfold.app/Contents/Resources/app.asar/out/main/index.cjs:12:5');
    expect(s).toContain('~/…/apps/desk/out/main/index.cjs:40:2');
    expect(s).not.toContain('design-ml');
  });

  it('bare media names, Windows homes, temp folders', () => {
    expect(redact('could not open IMG_2041.MOV and 访谈.wav')).toBe('could not open <file>.mov and <file>.wav');
    expect(redact('C:\\Users\\Wendy\\Videos\\a.mp4')).not.toContain('Wendy');
    expect(redact('/var/folders/xy/abc123/T/tmp.wav')).toBe('<tmp>');
  });

  it('keys, tokens, e-mails, URL queries', () => {
    const s = redact(
      `${'sk'}-ant-api03-abcdefghijklmnop ${'sk'}-proj-ABCDEFGHIJKLMNOPQRSTUV AIzaSyA1234567890abcdefghijklmnop ghp_abcdefghijklmnopqrstuvwxyz12 Bearer abc.def.ghi123456 api_key=hunter2hunter2 me@example.com https://api.x.com/v1?token=zzz&u=1 0123456789abcdef0123456789abcdef`,
    );
    for (const bad of ['abcdefghijklmnop', 'ABCDEFGHIJKLMNOPQRSTUV', 'AIzaSy', 'ghp_', 'abc.def', 'hunter2', 'me@example.com', 'token=zzz', '0123456789abcdef']) expect(s).not.toContain(bad);
    expect(s).toContain('https://api.x.com/v1?<redacted>');
  });

  it('prompts and transcript lines become <text>', () => {
    expect(redact('prompt: "Cut the pauses and filler words, add captions, export for TikTok and Shorts"')).toBe('prompt: "<text>"');
    expect(redact('ASR: 今天我们来聊一聊怎么把一节课剪成十条短视频')).toBe('ASR: <text>');
    expect(redact('第 1 条 failed')).toBe('第 1 条 failed'); // short engine words stay
  });

  it('does not eat ordinary text', () => {
    expect(redact('engine exited (1): and/or 3/4 done')).toBe('engine exited (1): and/or 3/4 done');
    expect(redactClip('a\nb\nc'.repeat(100), 20).length).toBeLessThanOrEqual(22);
  });
});

describe('report + URLs', () => {
  it('the report has versions, codes and the redacted stack, never the home folder', () => {
    const r = problemReport({ kind: 'sidecar', code: 'exit 1', message: 'engine exited (1)', stack: `Traceback\n  File "${HOME}/Desktop/footage/lesson3.mp4"` }, env, [
      { id: 'a', at: 0, kind: 'renderer', code: 'TypeError', message: 'x is undefined' },
    ]);
    expect(r).toContain('Reelfold 0.2.0 · macOS 26.1 arm64');
    expect(r).toContain('Electron 44.5.1');
    expect(r).toContain('Problem: sidecar · exit 1');
    expect(r).toContain('Earlier problems:');
    expect(r).not.toContain('wendy');
    expect(r).not.toContain('lesson3');
    expect(diagnostics(env)).not.toContain(HOME);
  });

  it('issue URL fills the bug_report.yml fields and stays under the limit', () => {
    const u = new URL(issueUrl({ title: 'Problem: x', got: 'it broke', logs: 'L'.repeat(20000), env }));
    expect(u.origin + u.pathname).toBe('https://github.com/zyziyun/reelfold/issues/new');
    expect(u.searchParams.get('template')).toBe('bug_report.yml');
    expect(u.searchParams.get('surface')).toBe('Mac app (Reelfold)');
    expect(u.searchParams.get('got')).toBe('it broke');
    expect(u.searchParams.get('version')).toBe('0.2.0');
    expect(u.searchParams.get('env')).toBe('macOS 26.1 arm64');
    expect(u.toString().length).toBeLessThanOrEqual(MAX_URL);
    expect(u.searchParams.get('logs')!.length).toBeGreaterThan(200);
  });

  it('discussion URL + body (email and diagnostics only when given)', () => {
    const u = new URL(discussionUrl({ title: titleOf('Love it\nmore', 'x'), body: feedbackBody({ what: 'Love it', kind: 'idea' }) }));
    expect(u.pathname).toBe('/zyziyun/reelfold/discussions/new');
    expect(u.searchParams.get('category')).toBe(FEEDBACK_CATEGORY);
    expect(u.searchParams.get('title')).toBe('Love it');
    expect(u.searchParams.get('body')).not.toContain('Reply to');
    expect(feedbackBody({ what: 'x', email: 'a@b.co', diag: 'D', kind: 'bug' })).toContain('Reply to: a@b.co');
    expect(okEmail('')).toBe(true);
    expect(okEmail('nope')).toBe(false);
    expect(titleOf('', 'Feedback')).toBe('Feedback');
  });

  it('IPC: support channels validate', () => {
    expect(validateIpc('support:setAuto', { on: true })).toEqual({ on: true });
    expect(() => validateIpc('support:report', { kind: 'main', code: 'x', message: 'y' })).toThrow(); // main records its own
    expect(() => validateIpc('support:dismiss', { id: '../x' })).toThrow();
    expect(validateIpc('support:env', undefined)).toBeUndefined();
  });

  it('week words route the Home request to a week plan', () => {
    for (const s of ['把这些做成这周要发的帖子', 'make a week of posts', "this week's posts please", 'les publications de cette semaine']) expect(WEEK_WORDS.test(s)).toBe(true);
    expect(WEEK_WORDS.test('cut the pauses')).toBe(false);
  });
});

describe('problem log', async () => {
  const { ProblemLog, setCrashSender } = await import('../../src/main/problems');
  const dir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'problems-'));

  it('records redacted, dedupes within a minute, persists, dismisses', () => {
    const d = dir();
    const seen: string[] = [];
    const log = new ProblemLog(d, (p) => seen.push(p.code));
    expect(log.record('sidecar', 'exit 1', `engine exited ${os.homedir()}/Desktop/x.mp4`)).not.toBeNull();
    expect(log.record('sidecar', 'exit 1', `engine exited ${os.homedir()}/Desktop/x.mp4`)).toBeNull();
    expect(seen).toEqual(['exit 1']);
    const again = new ProblemLog(d);
    expect(again.list()).toHaveLength(1);
    expect(again.list()[0].message).not.toContain(os.homedir());
    again.dismiss();
    expect(new ProblemLog(d).list()).toHaveLength(0);
    expect(new ProblemLog(d).recent()).toHaveLength(1);
  });

  it('sends automatically only with a sender AND the setting on', async () => {
    const send = vi.fn(async () => true);
    let on = false;
    const log = new ProblemLog(dir(), undefined, () => env, () => on);
    log.record('main', 'a', 'first');
    setCrashSender(send);
    log.record('main', 'b', 'second');
    await new Promise((r) => setTimeout(r, 10));
    expect(send).not.toHaveBeenCalled(); // off by default
    on = true;
    log.record('main', 'c', 'third');
    await new Promise((r) => setTimeout(r, 10));
    expect(send).toHaveBeenCalledTimes(1);
    expect((send.mock.calls[0] as unknown as [string])[0]).toContain('Problem: main · c');
    setCrashSender(null);
  });
});
