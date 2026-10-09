// Create plugins (client side): the client maps the plugin / import / make calls to /api/create/*, keys and sources
// are validated before anything is sent, swatches for plugin / agent shots, the command-line splitter, the plan
// progress step and the plan job deadline.
import { describe, expect, it } from 'vitest';
import { PLUGIN_KEY_RE, SOURCE_RE, swatch, type CreateClient, type CreateJob } from '../../src/shared/create';
import { EngineClient } from '../../src/shared/engineClient';
import { splitCommand } from '../../src/renderer/src/create/settings/PluginsCard';
import { JobError, lastStep, waitJob } from '../../src/renderer/src/create/api';

function fakeFetch(reply: unknown = { ok: true }, status = 200) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const f = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(reply), { status });
  };
  return { f, calls };
}

describe('CreateClient plugins', () => {
  it('maps plugin, import and make calls', async () => {
    const { f, calls } = fakeFetch({ job: 'abcdefabcdef' });
    const c = new EngineClient('app://desk', 'tok', f).create;
    await c.plugins('zh');
    await c.setPlugin('agent-runner:claude-code', { enabled: false });
    await c.importBoard('/Users/me/boards/teaser', { lang: 'en' });
    await c.sniffBoard('/Users/me/shots.csv');
    await c.importBoardInto('fp-e04', '/Users/me/shots.csv');
    await c.make('fp-e04', { lanes: 3, only: ['01'] });
    await c.plan({ format: 'series-ad', budget_cny: 60, mode: 'template' });
    expect(calls.map((x) => `${x.init?.method} ${x.url.replace('app://desk', '')}`)).toEqual([
      'GET /api/create/plugins?lang=zh',
      'POST /api/create/plugins/agent-runner:claude-code',
      'POST /api/create/import',
      'POST /api/create/import/sniff',
      'POST /api/create/episodes/fp-e04/import-board',
      'POST /api/create/episodes/fp-e04/make',
      'POST /api/create/plan',
    ]);
    expect(JSON.parse(String(calls[5].init?.body))).toEqual({ lanes: 3, only: ['01'] });
    expect(JSON.parse(String(calls[6].init?.body)).mode).toBe('template');
    expect(() => c.setPlugin('../etc', { enabled: true })).toThrow();
  });

  it('validates keys and sources like the engine', () => {
    expect(PLUGIN_KEY_RE.test('importer:hyperframes')).toBe(true);
    expect(PLUGIN_KEY_RE.test('shot-provider:Bad')).toBe(false);
    expect(PLUGIN_KEY_RE.test('script:x')).toBe(false);
    expect(SOURCE_RE.test('agent:claude-code')).toBe(true);
    expect(SOURCE_RE.test('plugin:hyperframes')).toBe(true);
    expect(SOURCE_RE.test('agent:../x')).toBe(false);
    expect(swatch('plugin', 'hyperframes')).toBe('plugin');
    expect(swatch('agent', 'codex')).toBe('agent');
  });

  it('splits a command line without a shell', () => {
    expect(splitCommand(`mytool --in {job_dir} --title "two words" 'x y'`)).toEqual(['mytool', '--in', '{job_dir}', '--title', 'two words', 'x y']);
    expect(splitCommand('   ')).toEqual([]);
  });
});

describe('plan progress', () => {
  const job = (state: CreateJob['state'], events: Record<string, unknown>[] = []): CreateJob => ({ id: 'abcdefabcdef', kind: 'plan', state, result: null, error: null, events });

  it('lastStep picks the newest create.step', () => {
    expect(lastStep(job('running'))).toBeNull();
    const j = job('running', [
      { event: 'create.step', step: 'read' },
      { event: 'create.progress', stage: 'x' },
      { event: 'create.step', step: 'fallback', from: 'claude-code', to: 'codex' },
    ]);
    expect(lastStep(j)?.step).toBe('fallback');
  });

  it('waitJob gives up at its deadline instead of spinning forever', async () => {
    const c = { job: async () => job('running') } as unknown as CreateClient;
    await expect(waitJob(c, 'abcdefabcdef', undefined, 5, 30)).rejects.toBeInstanceOf(JobError);
    try {
      await waitJob(c, 'abcdefabcdef', undefined, 5, 30);
    } catch (e) {
      expect((e as JobError).msg.code).toBe('create.job-timeout');
    }
  });
});
