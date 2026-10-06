// AI accounts & models: settings -> engine routes file, persona routes -> initial choices, the fallback notice,
// env stripping for login terminals, status pills, IPC validation, the terminal backends and the engine call.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { effective, fallbackNotice, normalizeRoutes, pill, routesFile, routesFromEngine, stripEnv, type AiRoutes } from '../../src/shared/aiRoutes';
import { validateIpc } from '../../src/shared/ipc';
import { routesFilePath, runLlm, writeRoutesFile } from '../../src/main/aiAccounts';
import { scriptCommand, startTerminal } from '../../src/main/terminal';
import { setLang, t } from '../../src/renderer/src/i18n';

const persona = {
  default: { provider: 'claude-code', model: null, fallback: ['codex'] },
  segment_plan: { provider: 'claude-code', fallback: ['codex'] },
  proofread: { provider: 'claude-code', fallback: ['codex'] },
  glossary: { provider: 'claude-code', fallback: ['codex'] },
  copy: { provider: 'claude-code', fallback: ['codex'] },
  intake: { provider: 'claude-code', fallback: ['codex'] },
  output_edit: { provider: 'claude-code', fallback: ['codex'] },
};

describe('routes', () => {
  it('the persona routes are the starting values (tasks equal to the default follow it)', () => {
    const r = routesFromEngine(persona);
    expect(r.default).toEqual({ provider: 'claude-code', model: null, fallback: ['codex'] });
    expect(r.tasks).toEqual({});
    const r2 = routesFromEngine({ ...persona, proofread: { provider: 'ollama', model: 'qwen3:8b', fallback: [] } });
    expect(r2.tasks.proofread).toEqual({ provider: 'ollama', model: 'qwen3:8b', fallback: [] });
    expect(routesFromEngine(null).default.provider).toBe('claude-code');
  });

  it('settings -> engine routes file: every task explicit (the persona must not win over "same as default")', () => {
    const r: AiRoutes = { default: { provider: 'codex', fallback: ['claude-code'] }, tasks: { edit: { provider: 'ollama', model: 'qwen3:8b', fallback: [] } } };
    const f = routesFile(r);
    expect(f.default).toEqual({ provider: 'codex', fallback: ['claude-code'] });
    expect(f.tasks.output_edit).toEqual({ provider: 'ollama', model: 'qwen3:8b' });
    for (const k of ['intake', 'segment_plan', 'proofread', 'glossary', 'copy', 'script', 'planner']) expect(f.tasks[k]).toEqual(f.default);
    expect(effective(r, 'copy').provider).toBe('codex');
  });

  it('normalizes untrusted routes: no duplicate / self fallbacks, max 4, a default is required', () => {
    const r = normalizeRoutes({ default: { provider: 'codex', fallback: ['codex', 'claude-code', 'claude-code', 'bogus'] }, tasks: { copy: { provider: 'nope', fallback: [] } } });
    expect(r.default.fallback).toEqual(['claude-code']);
    expect(r.tasks).toEqual({});
    expect(() => normalizeRoutes({ tasks: {} })).toThrow();
  });

  it('writes and removes the routes file', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-routes-'));
    writeRoutesFile(dir, { default: { provider: 'codex', fallback: [] }, tasks: {} });
    expect(JSON.parse(fs.readFileSync(routesFilePath(dir), 'utf8')).tasks.output_edit.provider).toBe('codex');
    writeRoutesFile(dir, null);
    expect(fs.existsSync(routesFilePath(dir))).toBe(false);
  });
});

describe('fallback notice', () => {
  afterEach(() => setLang('en'));
  it('says which provider failed, who answered, and offers the login', () => {
    const n = fallbackNotice({ from: 'claude-code', to: 'codex', code: 'auth-expired' })!;
    expect(n).toMatchObject({ key: 'aiacc.fb.expired', from: 'Claude Code', to: 'Codex', provider: 'claude-code', login: true });
    setLang('zh-CN');
    expect(t(n.key, { from: n.from, to: n.to })).toBe('Claude Code 登录已过期，这次用了 Codex');
    expect(t('aiacc.fb.login')).toBe('去登录');
    setLang('en');
    expect(t(n.key, { from: n.from, to: n.to })).toBe('Claude Code login expired, so Codex was used this time');
    expect(fallbackNotice({ from: 'deepseek', to: 'codex', code: 'key-missing' })).toMatchObject({ key: 'aiacc.fb.failed', login: false });
    expect(fallbackNotice({ from: 'codex', to: 'codex', code: 'failed' })).toBeNull();
    expect(fallbackNotice(null)).toBeNull();
  });

  it('status pills', () => {
    expect(pill({ provider: 'claude-code', kind: 'subscription-cli', state: 'expired', ready: false })).toEqual({ tone: 'bad', key: 'aiacc.st.expired' });
    expect(pill({ provider: 'ollama', kind: 'local', state: 'server-down', ready: false }).key).toBe('aiacc.st.localDown');
    expect(pill(undefined).key).toBe('aiacc.st.checking');
  });
});

describe('login terminal', () => {
  it('runs without API keys / base URLs ("X_*" = every X_ variable)', () => {
    const env = { PATH: '/bin', HOME: '/h', ANTHROPIC_API_KEY: 'k', ANTHROPIC_AUTH_TOKEN: 't', ANTHROPIC_BASE_URL: 'u', OPENAI_API_KEY: 'o', OPENAI_ORG_ID: 'x', CODEX_API_KEY: 'c' };
    expect(Object.keys(stripEnv(env, ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL'])).sort()).toEqual(['CODEX_API_KEY', 'HOME', 'OPENAI_API_KEY', 'OPENAI_ORG_ID', 'PATH']);
    expect(Object.keys(stripEnv(env, ['OPENAI_*', 'CODEX_API_KEY'])).sort()).toEqual(['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'HOME', 'PATH']);
  });

  it('IPC: only claude-code / codex, only login / logout; the page cannot pass a command', () => {
    expect(validateIpc('ai:terminal', { provider: 'codex', action: 'login', cols: 80, rows: 24 })).toBeTruthy();
    expect(() => validateIpc('ai:terminal', { provider: 'deepseek', action: 'login', cols: 80, rows: 24 })).toThrow();
    expect(() => validateIpc('ai:terminal', { provider: 'codex', action: 'login', cols: 80, rows: 24, command: ['/bin/sh'] })).toThrow();
    expect(() => validateIpc('term:input', { id: 'not-an-id', data: 'x' })).toThrow();
    expect(validateIpc('ai:setRoutes', { routes: { default: { provider: 'codex', fallback: ['claude-code'] }, tasks: { edit: { provider: 'ollama', model: 'qwen3:8b', fallback: [] } } } })).toBeTruthy();
    expect(() => validateIpc('ai:setRoutes', { routes: { default: { provider: 'rm -rf', fallback: [] }, tasks: {} } })).toThrow();
  });

  const run = (cmd: string[], noPty: boolean, python?: string) =>
    new Promise<{ out: string; code: number | null; backend: string }>((resolve) => {
      const prev = process.env.DESK_NO_PTY;
      if (noPty) process.env.DESK_NO_PTY = '1';
      let out = '';
      const s = startTerminal(cmd, { PATH: '/usr/bin:/bin', HOME: os.homedir() }, { cols: 80, rows: 24 }, { onData: (d) => (out += d), onExit: (code) => setTimeout(() => resolve({ out, code, backend: s.backend }), 50) }, os.tmpdir(), python);
      if (prev === undefined) delete process.env.DESK_NO_PTY;
    });

  it.runIf(process.platform !== 'win32')('runs a command in a terminal and reports its exit', async () => {
    const r = await run(['/bin/sh', '-c', 'printf "sign in\\n"; exit 3'], false);
    expect(r.out).toContain('sign in');
    expect(r.code).toBe(3);
  });

  it.runIf(process.platform !== 'win32')('without node-pty: a PTY through Python (input reaches the CLI, exit code kept)', async () => {
    const py = ['/opt/homebrew/bin/python3', '/usr/bin/python3'].find((p) => fs.existsSync(p))!;
    const r = await new Promise<{ out: string; code: number | null; backend: string }>((resolve) => {
      process.env.DESK_NO_PTY = '1';
      let out = '';
      const s = startTerminal(['/bin/sh', '-c', 'if [ -t 0 ]; then echo tty; fi; printf "code: "; read c; echo "got $c"; exit 4'], { PATH: '/usr/bin:/bin' }, { cols: 80, rows: 24 }, {
        onData: (d) => {
          out += d;
          if (out.includes('code: ') && !out.includes('got')) s.write('abc\r');
        },
        onExit: (code) => resolve({ out, code, backend: s.backend }),
      }, os.tmpdir(), py);
      delete process.env.DESK_NO_PTY;
    });
    expect(r.backend).toBe('python');
    expect(r.out).toContain('tty');
    expect(r.out).toContain('got abc');
    expect(r.code).toBe(4);
  });

  it.runIf(process.platform === 'darwin')('the last resort is `script`', async () => {
    expect(scriptCommand(['claude', 'auth', 'login'], 'darwin')).toEqual(['/usr/bin/script', '-q', '/dev/null', 'claude', 'auth', 'login']);
  });
});

describe('engine call', () => {
  it('python -m vstudio.llm ... -> JSON; the routes file can be hidden (persona values)', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-py-'));
    const py = path.join(dir, 'python');
    fs.writeFileSync(py, '#!/bin/sh\nprintf \'{"args": "%s", "routes": "%s"}\' "$*" "$VSTUDIO_LLM_ROUTES_FILE"\n', { mode: 0o755 });
    const r = (await runLlm({ python: py, env: { PATH: '/bin', VSTUDIO_LLM_ROUTES_FILE: '/x.json' } }, ['route', '--json'], 5000, '')) as { args: string; routes: string };
    expect(r.args).toBe('-m vstudio.llm route --json');
    expect(r.routes).toBe('');
    const r2 = (await runLlm({ python: py, env: { PATH: '/bin', VSTUDIO_LLM_ROUTES_FILE: '/x.json' } }, ['auth', 'status'], 5000)) as { routes: string };
    expect(r2.routes).toBe('/x.json');
  });
});
