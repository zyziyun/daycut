// The plan card's "things for you to decide" follow the UI language: the composer sends it with the plan request
// (and a revision), and each line carries the language the planner wrote it in, not a hard-coded zh-CN.
import { describe, expect, it, vi } from 'vitest';
import { EngineClient } from '../../src/shared/engineClient';
import type { IntakePlan } from '../../src/shared/v04';

const BASE = 'http://127.0.0.1:43123';
const TOKEN = 'tok'.repeat(20);

function client() {
  const f = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ id: 'abcdefabcdef' }), { status: 200 }));
  return { f, c: new EngineClient(BASE, TOKEN, f), body: (i = 0) => JSON.parse(String(f.mock.calls[i][1]!.body)) };
}

describe('plan requests carry the UI language', () => {
  for (const lang of ['en', 'zh-CN', 'fr']) {
    it(`startIntake / reviseIntake (${lang})`, async () => {
      const { c, body } = client();
      await c.startIntake('Cut this talk into vertical clips for TikTok and Xiaohongshu', ['/x/talk.mp4'], undefined, lang);
      expect(body(0)).toMatchObject({ lang, inputs: ['/x/talk.mp4'] });
      await c.reviseIntake('abcdefabcdef', 'only TikTok', lang);
      expect(body(1)).toEqual({ prompt: 'only TikTok', lang });
    });
  }

  it('no lang: the body has none (the planner follows the request)', async () => {
    const { c, body } = client();
    await c.startIntake('x', []);
    expect(body(0)).not.toHaveProperty('lang');
  });
});

describe('decideLines', () => {
  const plan = (ui_lang?: IntakePlan['ui_lang']) =>
    ({
      questions: [
        { id: 'q1', text: 'Qui est l’hôte ?' },
        { id: 'q2', text: '要遮谁的脸？', code: 'intake.question.mask-faces' },
      ],
      risks: ['Source courte', { code: 'intake.risk.unsupported-platform', params: { platforms: 'Snapchat' }, message: 'x' }],
      ui_lang,
    }) as unknown as IntakePlan;

  it('free text carries the plan language; coded lines are worded by the UI', async () => {
    const { decideLines } = await import('../../src/renderer/src/v4/PlanCard');
    const lines = decideLines(plan('fr'));
    expect(lines.map((l) => l.lang)).toEqual(['fr', undefined, 'fr', undefined]);
    expect(lines[0].text).toBe('Qui est l’hôte ?');
    expect(decideLines(plan('zh'))[0].lang).toBe('zh-CN');
    expect(decideLines(plan('en'))[0].lang).toBe('en');
  });

  it('an older plan (no ui_lang) is not forced to zh-CN', async () => {
    const { decideLines } = await import('../../src/renderer/src/v4/PlanCard');
    expect(decideLines(plan()).every((l) => l.lang === undefined)).toBe(true);
  });
});
