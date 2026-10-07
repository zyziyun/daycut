// Plan progress + failure (Create home): what the engine is doing right now ("Writing the series bible with Claude
// Code… 12 s"), and when no AI answered a plain reason with Retry, "Start from the template" (labelled: no AI, the
// format's own outline) and a way to set AI up. Never a silent swap, never a spinner without an end.
import { useEffect, useState } from 'react';
import type { Msg } from '../../../shared/create';
import { has, t, tk } from '../i18n';
import { href } from '../lib/router';

const NAMES: Record<string, string> = { 'claude-code': 'Claude Code', codex: 'Codex', anthropic: 'Claude API', openai: 'OpenAI', gemini: 'Gemini', ollama: 'Ollama' };
export const aiName = (p: unknown) => (typeof p === 'string' && p ? (NAMES[p] ?? p) : 'AI');

export function stepText(step: Record<string, unknown> | null): string {
  const s = String(step?.step ?? 'start');
  if (s === 'bible') return t('create.planjob.step.bible', { provider: aiName(step?.provider) });
  if (s === 'fallback') return t('create.planjob.step.fallback', { from: aiName(step?.from), to: aiName(step?.to) });
  if (s === 'ideas') return t('create.planjob.step.ideas');
  if (s === 'template') return t('create.planjob.step.template');
  if (s === 'read') return t('create.planjob.step.read');
  return t('create.planjob.step.start');
}

export function PlanProgress({ step, since }: { step: Record<string, unknown> | null; since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const tm = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tm);
  }, []);
  const secs = Math.max(0, Math.round((now - since) / 1000));
  return (
    <div className="cr-plan-progress" role="status" aria-live="polite" data-testid="create-plan-step" data-step={String(step?.step ?? 'start')}>
      <span className="cr-dot-spin" aria-hidden />
      <span>{stepText(step)}</span>
      <span className="muted num">{t('create.planjob.elapsed', { n: secs })}</span>
    </div>
  );
}

export function planErrorText(m: Msg): string {
  const p = (m.params ?? {}) as Record<string, unknown>;
  if (m.code === 'create.ai-failed') {
    const reason = String(p.reason ?? 'failed');
    const key = `create.planjob.fail.${reason}`;
    const vars = { provider: aiName(p.provider), seconds: Number(p.seconds ?? 0) };
    return has(key) ? tk(key, vars) : t('create.planjob.fail.failed', vars);
  }
  if (m.code === 'create.job-timeout') return t('create.planjob.fail.stopped', { seconds: Number(p.seconds ?? 0) });
  return has(m.code) ? tk(m.code, p as Record<string, string | number>) : t('create.planjob.fail.failed', { provider: 'AI', seconds: 0 });
}

export function PlanError({ msg, onRetry, onTemplate, busy }: { msg: Msg; onRetry: () => void; onTemplate: () => void; busy: boolean }) {
  const reason = String((msg.params as Record<string, unknown> | undefined)?.reason ?? '');
  const setup = ['not-set-up', 'auth-expired', 'not-logged-in', 'not-installed', 'key-missing'].includes(reason);
  return (
    <div className="cr-plan-fail" role="alert" data-testid="create-plan-error" data-reason={reason || msg.code}>
      <div className="t1">{planErrorText(msg)}</div>
      <div className="t2 muted">{t('create.planjob.fail.hint')}</div>
      <div className="row">
        {reason !== 'not-set-up' && (
          <button className="btn primary" disabled={busy} onClick={onRetry} data-testid="create-plan-retry">
            {t('create.planjob.retry')}
          </button>
        )}
        {setup && (
          <a className="btn" href={href({ name: 'aiAccounts' })} data-testid="create-plan-setup-ai">
            {t('create.planjob.setupAi')}
          </a>
        )}
        <button className="btn" disabled={busy} onClick={onTemplate} data-testid="create-plan-template" title={t('create.planjob.templateNote')}>
          {t('create.planjob.template')}
        </button>
      </div>
      <div className="t3 muted">{t('create.planjob.templateNote')}</div>
    </div>
  );
}
