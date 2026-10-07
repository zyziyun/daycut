// Settings › AI (ux/settings-redesign A2): the AI in use (status, Switch AI…, ⋯), the fallback order in one
// sentence, "different AI for specific jobs" as a second page, other accounts (subscriptions, API keys, models on
// this Mac). Sign-in runs in the sign-in sheet (the terminal is folded under "Show details").
import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Cpu, KeyRound, MoreHorizontal, Sparkles, TerminalSquare } from 'lucide-react';
import { effective, pill, PROVIDER_IDS, PROVIDERS, providerName, type AuthRow, type ProviderId } from '../../../shared/aiRoutes';
import type { AiTestMsg, SecretsStatusMsg } from '../../../shared/deskApi';
import { AI_TASK_IDS } from '../../../shared/aiRoutes';
import { fmtAgo, has, t, tk } from '../i18n';
import { refreshStatus, rowOf, saveRoutes, switchProvider, useAi } from '../lib/ai';
import { missingRow, RouteRow, RoutesEditor } from '../v4/AIAccounts';
import { LoginTerminal, type LoginReq } from '../v4/LoginTerminal';
import { useUi, type MenuItem } from '../v4/ui';
import { Dot, Group, Page, RestartBar, Sheet } from './kit';
import { markRestart, useRestart } from './restart';
import type { SettingsCtx } from './registry';
import { takePendingSignIn } from './status';

const clean = (e: unknown) => (e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
const CLI = PROVIDER_IDS.filter((p) => PROVIDERS[p].kind === 'subscription-cli');
const API = PROVIDER_IDS.filter((p) => PROVIDERS[p].kind === 'api');
const LOCAL = PROVIDER_IDS.filter((p) => PROVIDERS[p].kind === 'local');

function Icon({ p, big }: { p: string; big?: boolean }) {
  const kind = PROVIDERS[p as ProviderId]?.kind;
  return (
    <span className={`s2-pico ${p} ${big ? 'big' : ''}`}>
      {p === 'claude-code' ? <Sparkles className="ico" /> : p === 'codex' ? <TerminalSquare className="ico" /> : kind === 'local' ? <Cpu className="ico" /> : <KeyRound className="ico" />}
    </span>
  );
}

function StatePill({ row, working }: { row: AuthRow | undefined; working?: boolean }) {
  const p = pill(row);
  const tone = p.tone === 'ok' ? 'ok' : p.tone === 'bad' ? 'error' : p.tone === 'warn' ? 'warn' : 'off';
  const plan = row?.state === 'logged-in' && row.account?.plan ? row.account.plan.charAt(0).toUpperCase() + row.account.plan.slice(1) : null;
  return (
    <span className={`s2-pill ${tone}`} data-testid="provider-pill" data-state={row?.state ?? 'checking'}>
      <Dot tone={tone} />
      {working && row?.ready ? t('s2.ai.working') : plan ? t('aiacc.st.loggedInPlan', { plan }) : tk(p.key)}
    </span>
  );
}

export function AiSection({ sub }: SettingsCtx) {
  const ui = useUi();
  const { status, checking, routes } = useAi();
  const [login, setLogin] = useState<LoginReq | null>(null);
  const [keys, setKeys] = useState<SecretsStatusMsg | null>(null);
  const [sheet, setSheet] = useState<'order' | 'keys' | 'local' | null>(null);
  const [tests, setTests] = useState<Record<string, AiTestMsg | 'running'>>({});
  const restart = useRestart();
  const focus = sub && sub !== 'jobs' ? sub : undefined;
  useEffect(() => {
    void refreshStatus({ refresh: true });
    void window.desk.secrets.status().then(setKeys);
    const p = takePendingSignIn();
    if (p) setLogin({ provider: p, action: 'login' });
  }, []);
  useEffect(() => {
    if (!focus) return;
    const kind = PROVIDERS[focus as ProviderId]?.kind;
    if (kind === 'api') setSheet('keys');
    else if (kind === 'local') setSheet('local');
  }, [focus]);

  const row = (p: ProviderId) => rowOf(status, p) ?? (status ? (status.error ? { ...missingRow(p), state: 'error' } : missingRow(p)) : undefined);
  const def = (routes?.routes.default.provider ?? null) as ProviderId | 'none' | null;
  const cur = def && def !== 'none' ? def : null;
  const runTest = async (p: ProviderId) => {
    setTests((x) => ({ ...x, [p]: 'running' }));
    const r = await window.desk.ai.test(p);
    setTests((x) => ({ ...x, [p]: r }));
    ui.toast(r.ok ? t('aiacc.testOk', { model: r.model ?? '-', s: r.seconds ?? '-' }) : t('aiacc.testFail', { error: (r.error ?? '').slice(0, 200) }), { error: !r.ok });
  };
  const menuFor = (p: ProviderId): MenuItem[] => {
    const r = row(p);
    const cli = PROVIDERS[p].kind === 'subscription-cli';
    const cp = p as 'claude-code' | 'codex';
    const items: MenuItem[] = [];
    if (cli && r?.can_login !== false && r?.state !== 'not-installed') items.push({ label: t(r?.state === 'logged-in' || r?.state === 'expired' ? 's2.ai.signInAgain' : 's2.ai.signIn'), run: () => setLogin({ provider: cp, action: 'login' }), testId: `menu-login-${p}` });
    if (cli && p === 'claude-code') {
      items.push({ label: `${t('s2.ai.otherWays')}: ${t('aiacc.variant.console')}`, run: () => setLogin({ provider: cp, action: 'login', variant: 'console' }) });
      items.push({ label: `${t('s2.ai.otherWays')}: ${t('aiacc.variant.sso')}`, run: () => setLogin({ provider: cp, action: 'login', variant: 'sso' }) });
    }
    if (cli && p === 'codex') items.push({ label: `${t('s2.ai.otherWays')}: ${t('aiacc.variant.device')}`, run: () => setLogin({ provider: cp, action: 'login', variant: 'device' }) });
    if (r?.state !== 'not-installed') items.push({ label: t('s2.ai.test'), run: () => void runTest(p), testId: `test-${p}` });
    if (def !== p && r?.ready) items.push({ label: t('s2.ai.useForAll'), run: () => void switchProvider('default', p) });
    if (r?.install) items.push({ label: t('s2.ai.install'), run: () => void window.desk.openExternal(r.install!.url) });
    if (cli && r?.can_logout && (r.state === 'logged-in' || r.state === 'expired'))
      items.push({ label: '', sep: true, run: () => undefined }, { label: t('s2.ai.signOut'), run: () => window.confirm(t('aiacc.logoutConfirm', { name: providerName(p) })) && setLogin({ provider: cp, action: 'logout' }), testId: `logout-${p}` });
    return items;
  };
  const More = ({ p }: { p: ProviderId }) => (
    <button className="btn ghost icon" aria-label={t('s2.ai.more')} data-tip={t('s2.ai.more')} onClick={(e) => (e.stopPropagation(), ui.menu(e, menuFor(p)))} data-testid={`more-${p}`}>
      <MoreHorizontal className="ico" />
    </button>
  );
  const SignIn = ({ p, primary }: { p: ProviderId; primary?: boolean }) => {
    const r = row(p);
    if (PROVIDERS[p].kind !== 'subscription-cli' || r?.ready || r?.can_login === false || r?.state === 'not-installed' || !r) return null;
    return (
      <button className={`btn ${primary ? 'primary' : ''}`} onClick={() => setLogin({ provider: p as 'claude-code' | 'codex', action: 'login' })} data-testid={`login-${p}`}>
        {r.state === 'expired' ? t('s2.ai.signInAgain') : t('s2.ai.signIn')}
      </button>
    );
  };

  if (sub === 'jobs')
    return (
      <Page title={t('s2.ai.jobsTitle')} testId="ai-accounts">
        <a className="s2-back" href="#/settings/ai" data-testid="ai-jobs-back">
          <ChevronLeft className="ico" />
          {t('s2.nav.ai')}
        </a>
        {routes && <RoutesEditor routes={routes.routes} own={Boolean(routes.saved)} />}
      </Page>
    );

  const fb = routes?.routes.default.fallback ?? [];
  const chain = [...fb.map((p) => providerName(p)), t('s2.ai.rules')];
  const overridden = routes ? AI_TASK_IDS.filter((k) => routes.routes.tasks[k] && effective(routes.routes, k).provider !== routes.routes.default.provider).length : 0;
  const nKeys = keys ? Object.values(keys.keys).filter(Boolean).length : 0;
  const localUp = LOCAL.map((p) => rowOf(status, p)).find((r) => r?.ready);
  const curRow = cur ? row(cur) : undefined;
  return (
    <Page title={t('s2.nav.ai')} lead={t('s2.ai.lead')} testId="ai-accounts">
      {status?.error && (
        <div className="s2-note warn" data-testid="ai-status-error">
          {has(`aiacc.err.${status.error}`) ? tk(`aiacc.err.${status.error}`) : t('aiacc.err.failed')}
        </div>
      )}
      {status?.probeTimedOut && !status.error && (
        <div className="s2-note" data-testid="ai-probe-slow">
          {t('aiacc.probeSlow')}
        </div>
      )}
      {restart.what === 'key' && <RestartBar text={t('s2.ai.keyRestart')} onRestart={() => window.desk.restartEngine().then(() => markRestart(null))} />}
      <div className="s2-card s2-current" data-testid={cur ? `provider-${cur}` : 'provider-none'} data-provider-card={cur ?? 'none'}>
        <div className="s2-curtop">
          {cur ? <Icon p={cur} big /> : <span className="s2-pico big" />}
          <div className="s2-rtext">
            <div className="row" style={{ gap: 10 }}>
              <b className="s2-curname">{cur ? providerName(cur) : t('aiacc.none')}</b>
              {cur && <StatePill row={curRow} working />}
            </div>
            <span className="s2-rhint" data-testid="provider-account">
              {cur ? tk(PROVIDERS[cur].kind === 'subscription-cli' ? `aiacc.desc.${cur}` : PROVIDERS[cur].kind === 'api' ? 'aiacc.desc.api' : 'aiacc.desc.local') : t('s2.st.aiNoneBody')}
              {curRow?.account?.email ? ` · ${curRow.account.email}` : ''}
              {status?.at ? ` · ${t('s2.ai.checked', { when: fmtAgo(status.at) })}` : ''}
            </span>
          </div>
          {cur && <SignIn p={cur} primary />}
          <button
            className="btn"
            onClick={(e) =>
              ui.menu(
                e,
                [...PROVIDER_IDS]
                  .sort((a, b) => Number(!!rowOf(status, b)?.ready) - Number(!!rowOf(status, a)?.ready))
                  .filter((p) => p !== cur)
                  .map((p) => ({ label: `${providerName(p)}${rowOf(status, p)?.ready ? '' : ` (${t('aiacc.notReady')})`}`, run: () => void switchProvider('default', p), testId: `switch-${p}` })),
              )
            }
            data-testid="ai-switch"
          >
            {t('s2.ai.switch')}
          </button>
          {cur && <More p={cur} />}
        </div>
        <div className="s2-curfoot">
          <span data-testid="ai-fallback-sentence">
            {fb.length ? (
              <>
                {t('s2.ai.fb', { chain: '\u0000' }).split('\u0000')[0]}
                {chain.map((c, i) => (
                  <span key={c}>
                    {i > 0 && ' → '}
                    <b>{c}</b>
                  </span>
                ))}
                {t('s2.ai.fb', { chain: '\u0000' }).split('\u0000')[1]}
              </>
            ) : (
              t('s2.ai.fbNone')
            )}
          </span>
          <button className="s2-link" onClick={() => setSheet('order')} data-testid="ai-order">
            {t('s2.ai.order')}
          </button>
        </div>
      </div>
      <a className="s2-card s2-linkrow" href="#/settings/ai/jobs" data-testid="ai-perjob">
        <span className="s2-rtext">
          <span className="s2-rlabel">{t('s2.ai.perJob')}</span>
          <span className="s2-rhint">{t('s2.ai.perJobHint')}</span>
        </span>
        <span className="s2-val">{overridden ? t('s2.ai.perJobMixed', { n: overridden }) : cur ? t('s2.ai.perJobAll', { name: providerName(cur) }) : ''}</span>
        <ChevronRight className="ico" />
      </a>
      <Group
        title={t('s2.ai.others')}
        action={
          <button className="s2-link" onClick={() => void refreshStatus({ refresh: true })} disabled={checking} data-testid="ai-refresh">
            {checking ? t('s2.ai.checking') : t('s2.ai.check')}
          </button>
        }
      >
        {CLI.filter((p) => p !== cur).map((p) => {
          const r = row(p);
          return (
            <div key={p} className={`s2-row ${focus === p ? 'focus' : ''}`} data-testid={`provider-${p}`} data-provider-card={p}>
              <Icon p={p} />
              <div className="s2-rtext">
                <div className="s2-rlabel">{providerName(p)}</div>
                <div className="s2-rhint">{tk(`aiacc.desc.${p}`)}</div>
              </div>
              <div className="s2-rctl">
                <StatePill row={r} />
                <SignIn p={p} />
                <More p={p} />
              </div>
            </div>
          );
        })}
        <div className="s2-row" data-testid="ai-keys">
          <span className="s2-pico plain">
            <KeyRound className="ico" />
          </span>
          <div className="s2-rtext">
            <div className="s2-rlabel">{t('s2.ai.keys')}</div>
            <div className="s2-rhint">{t('s2.ai.keysHint')}</div>
          </div>
          <div className="s2-rctl">
            <span className="s2-val">{nKeys ? t('s2.ai.keysN', { n: nKeys }) : t('s2.ai.keysNone')}</span>
            <button className="s2-link" onClick={() => setSheet('keys')} data-testid="ai-add-key">
              {t('s2.ai.addKey')}
            </button>
          </div>
        </div>
        <div className="s2-row" data-testid="ai-local">
          <span className="s2-pico plain">
            <Cpu className="ico" />
          </span>
          <div className="s2-rtext">
            <div className="s2-rlabel">{t('s2.ai.local')}</div>
            <div className="s2-rhint">{t('s2.ai.localHint')}</div>
          </div>
          <div className="s2-rctl">
            <span className="s2-val">{localUp ? t('s2.ai.localUp', { name: providerName(localUp.provider) }) : t('s2.ai.localNone')}</span>
            <button className="s2-link" onClick={() => setSheet('local')} data-testid="ai-local-setup">
              {t('s2.ai.localSetup')}
            </button>
          </div>
        </div>
      </Group>

      {sheet === 'order' && routes && (
        <Sheet title={t('s2.ai.orderTitle', { name: cur ? providerName(cur) : t('aiacc.none') })} onClose={() => setSheet(null)} wide testId="ai-order-sheet" footer={<button className="btn primary" onClick={() => setSheet(null)}>{t('s2.done')}</button>}>
          <p className="s2-rhint">{t('s2.ai.orderBody')}</p>
          <RouteRow
            title={t('aiacc.default')}
            choice={routes.routes.default}
            label={(p) => (p === 'none' ? t('aiacc.none') : `${providerName(p)}${rowOf(status, p) && !rowOf(status, p)!.ready ? ` (${t('aiacc.notReady')})` : ''}`)}
            onChange={(c) => c && void saveRoutes({ ...routes.routes, default: c }).catch((e) => ui.toast(clean(e), { error: true }))}
            testId="route-default"
          />
        </Sheet>
      )}
      {sheet === 'keys' && (
        <Sheet title={t('s2.ai.keySheet')} onClose={() => setSheet(null)} wide testId="ai-keys-sheet">
          <p className="s2-rhint">{keys?.backend === 'keychain' ? t('s2.ai.keySheetBody') : t('keys.noKeychain')}</p>
          <div className="s2-card">
            {API.map((p) => (
              <KeyRow key={p} p={p} row={row(p)} keys={keys} focused={focus === p} onKeys={(k) => (setKeys(k), markRestart('key'), void refreshStatus({ refresh: true, probe: false, providers: [p] }))} />
            ))}
          </div>
        </Sheet>
      )}
      {sheet === 'local' && (
        <Sheet title={t('s2.ai.local')} onClose={() => setSheet(null)} wide testId="ai-local-sheet">
          <p className="s2-rhint">{t('s2.ai.localBody')}</p>
          <div className="s2-card">
            {LOCAL.map((p) => {
              const r = row(p);
              const tr = tests[p];
              return (
                <div key={p} className="s2-row" data-testid={`provider-${p}`} data-provider-card={p}>
                  <Icon p={p} />
                  <div className="s2-rtext">
                    <div className="s2-rlabel">{providerName(p)}</div>
                    <div className="s2-rhint">
                      {r?.models?.length ? t('aiacc.models', { n: r.models.length, list: r.models.slice(0, 4).join(', ') }) : tk('aiacc.desc.local')}
                    </div>
                  </div>
                  <div className="s2-rctl">
                    <StatePill row={r} />
                    {r?.state !== 'server-down' && r && (
                      <button className="btn" onClick={() => void runTest(p)} disabled={tr === 'running'}>
                        {tr === 'running' ? t('aiacc.testing') : t('s2.ai.test')}
                      </button>
                    )}
                    {r?.install && (
                      <button className="s2-link" onClick={() => void window.desk.openExternal(r.install!.url)}>
                        {t('s2.ai.install')}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </Sheet>
      )}
      {login && <LoginTerminal req={login} onClose={() => setLogin(null)} />}
    </Page>
  );
}

function KeyRow({ p, row, keys, focused, onKeys }: { p: ProviderId; row: AuthRow | undefined; keys: SecretsStatusMsg | null; focused: boolean; onKeys: (k: SecretsStatusMsg) => void }) {
  const [key, setKey] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const secret = PROVIDERS[p].secret;
  const hasKey = secret ? Boolean(keys?.keys[secret]) : false;
  if (!secret) return null;
  return (
    <div className={`s2-row ${focused ? 'focus' : ''}`} data-testid={`provider-${p}`} data-provider-card={p}>
      <div className="s2-rtext">
        <div className="row" style={{ gap: 10 }}>
          <span className="s2-rlabel">{PROVIDERS[p].name}</span>
          <StatePill row={row} />
        </div>
        {err && <div className="s2-rhint warn">{err}</div>}
      </div>
      <div className="s2-rctl">
        <input
          className="input s2-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          aria-label={PROVIDERS[p].name}
          placeholder={hasKey ? t('aiacc.keyReplace') : t('s2.ai.keyPh')}
          value={key}
          disabled={keys?.backend !== 'keychain'}
          onChange={(e) => setKey(e.target.value)}
          data-testid={`key-input-${p}`}
        />
        <button
          className="btn"
          disabled={!key.trim() || keys?.backend !== 'keychain'}
          onClick={async () => {
            setErr(null);
            try {
              onKeys(await window.desk.secrets.set(secret, key.trim()));
              setKey('');
            } catch (e) {
              setErr(clean(e));
            }
          }}
        >
          {t('s2.ai.save')}
        </button>
        {hasKey && (
          <button className="s2-link muted" onClick={async () => onKeys(await window.desk.secrets.clear(secret))}>
            {t('s2.ai.remove')}
          </button>
        )}
      </div>
    </div>
  );
}
