// What Settings says first: the one thing that most needs her (engine down > demo mode > AI not working > missing
// downloads > a signed-out publishing account), with one action. Also the sub-nav status dots.
import { useEffect } from 'react';
import { pill, providerName } from '../../../shared/aiRoutes';
import { useAssets } from '../components/assets';
import { t, tk } from '../i18n';
import { refreshStatus, rowOf, useAi } from '../lib/ai';
import { useEngine } from '../lib/engine';
import { go } from '../lib/router';
import { adapterName, useChannels } from '../v4/Channels';
import type { Dot } from './registry';

export interface Status {
  tone: 'ok' | 'warn' | 'error';
  title: string;
  body: string;
  action?: { label: string; run: () => void };
}

let checked = false;
/** The AI status without the slow round-trip (the AI page itself checks for real). */
function useAiStatus() {
  const ai = useAi();
  useEffect(() => {
    if (!checked && !ai.status) {
      checked = true;
      void refreshStatus({ probe: false }).catch(() => undefined);
    }
  }, [ai.status]);
  return ai;
}

/** AI sign-in asked from elsewhere in Settings (the status line): the AI section opens its sheet. */
export let pendingSignIn: 'claude-code' | 'codex' | null = null;
export function takePendingSignIn() {
  const p = pendingSignIn;
  pendingSignIn = null;
  return p;
}

const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);

export function useStatus(): Status {
  const { info, error } = useEngine();
  const { status, routes } = useAiStatus();
  const assets = useAssets();
  const { adapters, channels } = useChannels();
  if (error) return { tone: 'error', title: t('s2.st.engineDown'), body: t('s2.st.engineDownBody'), action: { label: t('s2.st.restart'), run: () => void window.desk.restartEngine().catch(() => undefined) } };
  if (info?.mode === 'mock') return { tone: 'warn', title: t('s2.st.demo'), body: t('s2.st.demoBody'), action: { label: t('s2.st.demoFix'), run: () => (location.hash = '#/settings/advanced') } };
  const def = routes?.routes.default.provider;
  if (status && def === 'none') return { tone: 'warn', title: t('s2.st.aiNone'), body: t('s2.st.aiNoneBody'), action: { label: t('s2.st.aiNoneFix'), run: () => (location.hash = '#/settings/ai') } };
  const row = def ? rowOf(status, def) : undefined;
  if (status && def && row && !row.ready) {
    const name = providerName(def);
    const cli = def === 'claude-code' || def === 'codex';
    return {
      tone: 'warn',
      title: t('s2.st.ai', { name }),
      body: t('s2.st.aiBody', { name, state: tk(pill(row).key).toLowerCase() }),
      action: {
        label: cli ? t('s2.st.aiFix', { name }) : t('s2.st.aiNoneFix'),
        run: () => {
          if (cli) pendingSignIn = def;
          location.hash = '#/settings/ai';
        },
      },
    };
  }
  const missing = assets?.bundled ? assets.groups.filter((g) => g.required && !g.installed && !g.queued && !g.progress) : [];
  if (missing.length)
    return {
      tone: 'warn',
      title: t('s2.st.downloads'),
      body: t('s2.st.downloadsBody', { size: mb(missing.reduce((a, g) => a + g.bytes, 0)) }),
      action: { label: t('s2.st.downloadsFix'), run: () => void window.desk.assets.install(missing.map((g) => g.id)) },
    };
  const out = channels.find((c) => c.login.state === 'out');
  if (out) {
    const a = adapters.find((x) => x.id === out.adapterId);
    const name = a ? adapterShort(a) : out.adapterId;
    return { tone: 'ok', title: t('s2.st.ready'), body: t('s2.st.signedOut', { name }), action: { label: t('s2.st.signIn', { name }), run: () => signInChannel(out.adapterId, out.account) } };
  }
  return { tone: 'ok', title: t('s2.st.ready'), body: t('s2.st.readyBody') };
}

/** "Douyin" rather than "Douyin creator center" */
export function adapterShort(a: Parameters<typeof adapterName>[0]): string {
  return tk(`pf.${a.packagePlatforms[0]}`) || adapterName(a);
}

/** Sign in happens in the built-in browser on 发布 → 账号 (the page needs room for it): ask it to open there. */
export function signInChannel(adapterId: string, account: string) {
  try {
    sessionStorage.setItem('ch.login', JSON.stringify({ adapterId, account }));
  } catch {
    /* private mode: she presses Sign in there */
  }
  go({ name: 'channels' });
}

export function useAiDot(): Dot {
  const { status, routes } = useAiStatus();
  const def = routes?.routes.default.provider;
  if (!status || !def) return null;
  if (def === 'none') return 'warn';
  const row = rowOf(status, def);
  return row ? (row.ready ? 'ok' : 'warn') : null;
}

export function useAccountsDot(): Dot {
  const { channels } = useChannels();
  if (!channels.length) return null;
  return channels.some((c) => c.login.state === 'out') ? 'warn' : channels.every((c) => c.login.state === 'in') ? 'ok' : null;
}

export function useAdvancedDot(): Dot {
  const { info, error } = useEngine();
  const assets = useAssets();
  if (error) return 'error';
  if (info?.mode === 'mock') return 'warn';
  if (assets?.bundled && assets.groups.some((g) => g.required && !g.installed)) return 'warn';
  return null;
}
