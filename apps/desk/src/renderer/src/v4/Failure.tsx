// A failed pilot (P0-3): the reason in her words (from the engine's failure code, never the raw error) and what
// to do next — 去登录 / 换 Codex 重试 / 重试. Used on the project page and in the inbox.
import { useState } from 'react';
import type { PilotFailure } from '../../../shared/v02';
import { providerName } from '../../../shared/aiRoutes';
import { t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { go } from '../lib/router';
import { errText } from './msg';
import { useUi } from './ui';

const AI = new Set(['ai-login', 'ai-quota', 'ai-timeout', 'ai-missing']);

export function failureReason(f: PilotFailure): string {
  const provider = f.provider ? providerName(f.provider) : t('fail.providerAny');
  return tk(`fail.reason.${f.code}`, { provider });
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
    </>
  );
}
