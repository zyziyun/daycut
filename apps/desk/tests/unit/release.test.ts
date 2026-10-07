// v0.2 release round: test hooks are ignored by packaged builds, AI status errors are codes (never engine text),
// fresh profiles route to what the page shows, pilot failure reasons are plain words.
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
import { describe, expect, it } from 'vitest';
import { devOnly, tempOnly } from '../../src/main/testHooks';
import { statusErrorCode } from '../../src/main/aiAccounts';
import { routesFromEngine } from '../../src/shared/aiRoutes';
import { setLang } from '../../src/renderer/src/i18n';
import { failureReason, otherProvider } from '../../src/renderer/src/v4/Failure';

describe('test hooks', () => {
  it('dev-only hooks are ignored when packaged', () => {
    const env = { DESK_AI_MOCK: '/tmp/x', DESK_PYTHON: '/tmp/evil' };
    expect(devOnly('DESK_AI_MOCK', env, false)).toBe('/tmp/x');
    expect(devOnly('DESK_AI_MOCK', env, true)).toBeUndefined();
    expect(devOnly('DESK_PYTHON', env, true)).toBeUndefined();
  });
  it('cache overrides must live in the temp dir when packaged', () => {
    const t = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-'));
    expect(tempOnly('C', { C: t }, true)).toBe(t);
    expect(tempOnly('C', { C: os.homedir() }, true)).toBeUndefined();
    expect(tempOnly('C', { C: os.homedir() }, false)).toBe(os.homedir());
    expect(tempOnly('C', { C: '' }, true)).toBe('');
    expect(tempOnly('C', {}, true)).toBeUndefined();
  });
});

describe('AI accounts', () => {
  it('status failures become codes', () => {
    expect(statusErrorCode("vstudio.llm auth failed (1): ModuleNotFoundError: No module named 'vstudio.llm'")).toBe('engine');
    expect(statusErrorCode('vstudio.llm auth timed out after 45 s')).toBe('timeout');
    expect(statusErrorCode('something else')).toBe('failed');
  });
  it('an engine with no route configured starts from Claude Code with Codex as fallback', () => {
    expect(routesFromEngine({ default: { provider: 'none' } }).default).toEqual({ provider: 'claude-code', model: null, fallback: ['codex'] });
    expect(routesFromEngine(null).default.provider).toBe('claude-code');
    expect(routesFromEngine({ default: { provider: 'codex', fallback: [] } }).default.provider).toBe('codex');
  });
});

describe('pilot failures', () => {
  it('are worded by code, never with the raw error', () => {
    setLang('en');
    const f = { state: 'failed' as const, code: 'ai-login' as const, provider: 'claude-code', error: 'claude CLI: 401 /Users/x', at: 1 };
    expect(failureReason(f)).toMatch(/Claude Code is signed out/);
    expect(failureReason(f)).not.toMatch(/401|Users/);
    expect(otherProvider(f)).toBe('codex');
    expect(otherProvider({ ...f, provider: 'codex' })).toBe('claude-code');
    setLang('fr');
    expect(failureReason(f)).not.toBe('fail.reason.ai-login');
    setLang('zh-CN');
    expect(failureReason({ ...f, code: 'unknown', provider: null })).toBe('制作时出了点问题，再试一次。');
    setLang('en');
  });
});
