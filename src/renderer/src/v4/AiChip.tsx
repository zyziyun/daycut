// Provider chip with a dropdown (quick switcher) for one AI task, the "answered by" tag, and the fallback notice
// ("Claude Code login expired, so Codex was used this time · Log in"). Switching is explicit and saved.
import type { MouseEvent } from 'react';
import { ChevronDown, Cpu } from 'lucide-react';
import { effective, fallbackNotice, pill, PROVIDER_IDS, PROVIDERS, providerName, type AiTask, type FallbackInfo, type ProviderId } from '../../../shared/aiRoutes';
import { t, tk } from '../i18n';
import { refreshStatus, rowOf, switchProvider, useAi } from '../lib/ai';
import { go } from '../lib/router';
import { useUi, type MenuItem } from './ui';

export function ProviderChip({ task, testId }: { task: AiTask; testId?: string }) {
  const { routes, status } = useAi();
  const ui = useUi();
  if (!routes) return null;
  const cur = effective(routes.routes, task);
  const own = Boolean(routes.routes.tasks[task]);
  const open = (e: MouseEvent) => {
    e.stopPropagation(); // the menu closes on the next window click
    if (!status) void refreshStatus({ probe: false });
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const items: MenuItem[] = PROVIDER_IDS.filter((p) => {
      const row = rowOf(status, p);
      // offer what can work here: the current choice, ready providers, and the subscription CLIs (they can log in)
      return p === cur.provider || !row || row.ready || PROVIDERS[p].kind === 'subscription-cli';
    }).map((p) => {
      const row = rowOf(status, p);
      const st = row ? tk(pill(row).key) : '';
      return {
        label: `${p === cur.provider ? '✓ ' : ''}${providerName(p)}${st ? ` · ${st}` : ''}`,
        run: () => void switchProvider(task, p as ProviderId),
        testId: `chip-pick-${p}`,
      };
    });
    items.push({ label: '', run: () => {}, sep: true });
    if (own) items.push({ label: t('aiacc.followDefault'), run: () => void switchProvider(task, null), testId: 'chip-follow-default' });
    items.push({ label: t('aiacc.manage'), run: () => go({ name: 'aiAccounts' }), testId: 'chip-manage' });
    ui.menu({ clientX: r.left, clientY: r.bottom + 4 }, items);
  };
  const row = rowOf(status, cur.provider);
  const tone = row ? pill(row).tone : 'off';
  return (
    <button className="chip" style={{ height: 24, padding: '0 8px' }} onClick={open} data-tip={t('aiacc.chipTip')} aria-label={t('aiacc.chipTip')} data-testid={testId ?? 'provider-chip'} data-provider={cur.provider}>
      <Cpu className="ico" style={{ width: 12, height: 12 }} />
      <span className="clamp1" style={{ maxWidth: 120 }}>{t('aiacc.chip', { name: cur.provider === 'none' ? t('aiacc.name.rules') : providerName(cur.provider) })}</span>
      {(tone === 'bad' || tone === 'warn') && <i className="dot" style={{ background: 'var(--danger)' }} />}
      <ChevronDown className="ico" style={{ width: 12, height: 12 }} />
    </button>
  );
}

/** Who answered, plus the notice when it was not the chosen provider. */
export function AnsweredBy({ provider, fallback, kind = 'answered', testId }: { provider?: string | null; fallback?: FallbackInfo | null; kind?: 'answered' | 'planned'; testId?: string }) {
  if (!provider) return null;
  const name = provider === 'rules' || provider === 'none' ? t('aiacc.name.rules') : providerName(provider);
  return (
    <div className="col" style={{ gap: 4 }} data-testid={testId ?? 'answered-by'}>
      <span className="faint small" data-provider={provider}>
        {kind === 'planned' ? t('aiacc.plannedBy', { name }) : t('aiacc.answeredBy', { name })}
      </span>
      <FallbackNote fallback={fallback} />
    </div>
  );
}

export function FallbackNote({ fallback, rulesFrom }: { fallback?: FallbackInfo | null; rulesFrom?: string | null }) {
  const n = fallbackNotice(fallback);
  if (!n && !rulesFrom) return null;
  const target = n?.provider ?? rulesFrom!;
  const login = n ? n.login : PROVIDERS[target as ProviderId]?.kind === 'subscription-cli';
  return (
    <div className="notice small row" style={{ gap: 6, flexWrap: 'wrap' }} data-testid="fallback-note">
      <span>{n ? t(n.key, { from: n.from, to: n.to }) : t('aiacc.fb.rules', { from: providerName(rulesFrom) })}</span>
      <span className="faint">·</span>
      <a href={`#/settings/ai/${encodeURIComponent(target)}`} data-testid="fallback-login">
        {login ? t('aiacc.fb.login') : t('aiacc.fb.settings')}
      </a>
    </div>
  );
}
