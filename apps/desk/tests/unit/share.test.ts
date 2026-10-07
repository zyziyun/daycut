// Share for review (desk): the client routes (ids validated before any request, coded refusals), the Inbox words
// for imported feedback, and every locale carrying the share / feedback copy.
import { describe, expect, it, vi } from 'vitest';
import { EngineClient, EngineError } from '../../src/shared/engineClient';
import type { InboxItem } from '../../src/shared/v04';
import { LANGS, LOCALES, setLang } from '../../src/renderer/src/i18n';
import { inboxTitle } from '../../src/renderer/src/lib/inboxView';
import { shareEn } from '../../src/renderer/src/i18n/locales/share';

const BASE = 'http://127.0.0.1:43123';
const TOKEN = 'tok'.repeat(20);
const ok = (body: unknown, status = 200) => vi.fn(async (_u: string, _i?: RequestInit) => new Response(JSON.stringify(body), { status }));

describe('share client', () => {
  it('calls the share routes with the item id and body', async () => {
    const f = ok({ ok: true, job: 'abcdef012345', total: 3 });
    const c = new EngineClient(BASE, TOKEN, f);
    await c.share('abcdefabcdef', { clips: ['A'], quality: 'small', footer: false, ack: true });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe(`${BASE}/api/share/abcdefabcdef`);
    expect(JSON.parse(String(init!.body))).toEqual({ clips: ['A'], quality: 'small', footer: false, ack: true });
    await c.shareOptions('abcdefabcdef');
    expect(f.mock.calls[1][0]).toBe(`${BASE}/api/share/abcdefabcdef`);
    await c.shareJob('abcdef012345');
    expect(f.mock.calls[2][0]).toBe(`${BASE}/api/share-jobs/abcdef012345`);
    await c.importFeedback('RFB1.xyz');
    expect(f.mock.calls[3][0]).toBe(`${BASE}/api/feedback/import`);
    expect(JSON.parse(String(f.mock.calls[3][1]!.body))).toEqual({ text: 'RFB1.xyz' });
  });

  it('refuses bad ids before any request and keeps refusal codes', async () => {
    const f = ok({});
    const c = new EngineClient(BASE, TOKEN, f);
    expect(() => c.shareOptions('../x')).toThrow(EngineError);
    expect(() => c.shareJob('nope')).toThrow(EngineError);
    expect(f).not.toHaveBeenCalled();
    const c2 = new EngineClient(BASE, TOKEN, ok({ error: 'not Reelfold', code: 'bad-feedback', message_zh: '不是' }, 400));
    await expect(c2.importFeedback('hello')).rejects.toMatchObject({ status: 400, code: 'bad-feedback', messageZh: '不是' });
  });
});

describe('feedback in the Inbox', () => {
  const item = (who: string, kind = 'feedback-change'): InboxItem => ({
    key: '0123456789abcdef',
    kind,
    group: 'choose',
    project: { id: 'abcdefabcdef', name: 'Week 12' },
    code: kind === 'feedback-change' ? 'inbox.feedbackChange' : 'inbox.feedbackApproved',
    params: { who, clip: 'Three habits' },
    text: 'shorter intro',
    source: 'feedback',
  });
  it('names the reviewer and the clip, with a fallback when the reviewer left no name', () => {
    setLang('en');
    expect(inboxTitle(item('Mia'))).toBe('Mia asked for a change in “Three habits”');
    expect(inboxTitle(item('', 'feedback-approve'))).toBe('Reviewer approved “Three habits”');
    setLang('zh-CN');
    expect(inboxTitle(item('Mia'))).toBe('Mia 希望修改「Three habits」');
    setLang('en');
  });
  it('every locale has the share copy', () => {
    for (const l of LANGS) {
      const m = LOCALES[l].messages as Record<string, string>;
      for (const k of Object.keys(shareEn)) expect(m[k], `${l} ${k}`).toBeTruthy();
    }
  });
});
