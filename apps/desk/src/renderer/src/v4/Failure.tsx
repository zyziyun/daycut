// A failed pilot (P0-3): the reason in her words (from the engine's failure code, never the raw error) and what
// to do next — 去登录 / 换 Codex 重试 / 重试. Used on the project page and in the inbox.
import { useState } from 'react';
import type { PilotFailure } from '../../../shared/v02';
import { providerName } from '../../../shared/aiRoutes';
import { has, t, tk, type MessageKey } from '../i18n';
import { stepOfStage } from '../lib/pipeline';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { go } from '../lib/router';
import { errText } from './msg';
import { openReport } from '../support/Support';
import { useUi } from './ui';

const AI = new Set(['ai-login', 'ai-quota', 'ai-timeout', 'ai-missing']);

const TOOL_NAMES: Record<string, string> = { node: 'Node.js', ffmpeg: 'ffmpeg', ffprobe: 'ffprobe', npx: 'Node.js (npx)' };

/** The reason in her words: the failure code from the engine, never the raw error. A step that failed on an external
 * tool names the tool and the fix; "Part of Reelfold didn't start" is only for the engine itself not starting. */
export function failureReason(f: PilotFailure): string {
  const provider = f.provider ? providerName(f.provider) : t('fail.providerAny');
  const p = f.params ?? {};
  const toolId = String(p.tool ?? f.tool ?? '');
  const tool = TOOL_NAMES[toolId] ?? toolId;
  const path = typeof p.path === 'string' && p.path ? tk('fail.at', { path: p.path }) : '';
  const key = `fail.reason.${f.code}`;
  let reason: string;
  const step = stepOfStage(f.stage);
  // the step in her words (「转写」), never the engine's stage id (「asr」)
  if (f.code === 'stage') reason = step ? tk(key, { stage: t(`hub.step.${step}` as MessageKey) }) : tk('fail.reason.unknown');
  else if ((f.code === 'tool-missing' || f.code === 'tool-broken') && !tool) reason = tk('fail.reason.unknown');
  else if (has(key)) reason = tk(key, { provider, tool, at: path, path: String(p.path ?? '') });
  else reason = tk('fail.reason.unknown'); // a code this desk has no words for yet
  const fix = String(p.fix ?? f.fix ?? '');
  if (!fix) return reason;
  const how = has(`fail.fix.${fix}`) ? tk(`fail.fix.${fix}`) : /\s/.test(fix) || fix.includes('/') ? tk('fail.fix.cmd', { fix }) : '';
  return how ? `${reason} ${how}` : reason;
}

/** The provider to offer for 「换 … 重试」: the other subscription CLI. */
export function otherProvider(f: PilotFailure): string {
  return f.provider === 'codex' ? 'claude-code' : 'codex';
}

export function FailureActions({ item, failure, primary = true, onDone }: { item: string; failure: PilotFailure; primary?: boolean; onDone?: () => void }) {
  const { client } = useEngine();
  const hist = useHistory();
  const inbox = useInbox();
  const ui = useUi();
  const [busy, setBusy] = useState(false);
  const ai = AI.has(failure.code);
  const other = otherProvider(failure);
  const retry = async (provider?: string) => {
    if (!client) return;
    setBusy(true);
    try {
      await client.retryPilot(item, provider ?? null);
      ui.toast(t('fail.retrying'));
      hist.reload();
      inbox.reload();
      onDone?.();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(false);
    }
  };
  const p = primary ? 'btn primary' : 'btn';
  return (
    <>
      {failure.code === 'ai-login' || failure.code === 'ai-missing' ? (
        <button className={p} onClick={() => go({ name: 'aiAccounts', focus: failure.provider ?? undefined })} data-testid="fail-login">
          {t('fail.login')}
        </button>
      ) : (
        <button className={p} disabled={busy} onClick={() => void retry(failure.provider ?? undefined)} data-testid="fail-retry">
          {t('fail.retry')}
        </button>
      )}
      {ai && (
        <button className="btn" disabled={busy} onClick={() => void retry(other)} data-testid="fail-retry-other">
          {t('fail.retryWith', { provider: providerName(other) })}
        </button>
      )}
      <button className="btn ghost" onClick={() => openReport({ kind: 'job', code: failure.code, message: failure.error || failure.code })} data-testid="fail-report">
        {t('sup.rp.report')}
      </button>
    </>
  );
}
