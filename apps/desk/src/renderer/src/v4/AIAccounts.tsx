// Settings → AI accounts & models: one card per provider (status pill, account / plan, log in / log in again / log
// out / test / install guide; API keys into the OS keychain), and which AI each task uses (default + per-task
// override + an ordered fallback list, drag to reorder). Logins run in the in-app terminal (LoginTerminal).
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, GripVertical, Plus, RefreshCw, X } from 'lucide-react';
import {
  AI_TASK_IDS,
  effective,
  pill,
  PROVIDER_IDS,
  PROVIDERS,
  providerName,
  type AiRoutes,
  type AiTask,
  type AuthRow,
  type ProviderId,
  type RouteChoice,
} from '../../../shared/aiRoutes';
import type { AiTestMsg, SecretsStatusMsg } from '../../../shared/deskApi';
import { t, tk, type MessageKey } from '../i18n';
import { refreshStatus, rowOf, saveRoutes, useAi } from '../lib/ai';
import { LoginTerminal, type LoginReq } from './LoginTerminal';
import { useUi } from './ui';

const clean = (e: unknown) => (e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '');

export function AIAccounts({ focus }: { focus?: string }) {
  const { status, checking, routes } = useAi();
  const [login, setLogin] = useState<LoginReq | null>(null);
  const [keys, setKeys] = useState<SecretsStatusMsg | null>(null);
  const [restart, setRestart] = useState(false);
  useEffect(() => {
    // the page always checks for real (claude-code: a one-line round-trip, the only way to see an expired token)
    void refreshStatus({ refresh: true });
    void window.desk.secrets.status().then(setKeys);
  }, []);
  useEffect(() => {
    if (focus && status) document.querySelector(`[data-provider-card="${CSS.escape(focus)}"]`)?.scrollIntoView({ block: 'center' });
  }, [focus, status]);

  const group = (kind: 'subscription-cli' | 'api' | 'local', title: MessageKey) => (
    <div className="col" style={{ gap: 10 }}>
      <b>{t(title)}</b>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
        {PROVIDER_IDS.filter((p) => PROVIDERS[p].kind === kind).map((p) => (
          <ProviderCard
            key={p}
            p={p}
            row={rowOf(status, p) ?? (status && !status.error ? missingRow(p) : undefined)}
            focused={focus === p}
            keys={keys}
            onKeys={(k) => {
              setKeys(k);
              setRestart(true);
              void refreshStatus({ refresh: true, probe: false, providers: [p] });
            }}
            onLogin={setLogin}
          />
        ))}
      </div>
    </div>
  );

  return (
    <div className="scroll" data-testid="ai-accounts">
      <div className="pg col" style={{ maxWidth: 1040, gap: 20 }}>
        <div className="ph" style={{ marginBottom: 0 }}>
          <div>
            <a className="btn ghost sm" href="#/settings" style={{ marginBottom: 6 }}>
              <ArrowLeft className="ico" />
              {t('nav.settings')}
            </a>
            <h1>{t('aiacc.title')}</h1>
            <p>{t('aiacc.lead')}</p>
          </div>
          <span className="sp" />
          <button className="btn" onClick={() => void refreshStatus({ refresh: true })} disabled={checking} data-testid="ai-refresh">
            <RefreshCw className="ico" />
            {checking ? t('aiacc.checking') : t('aiacc.refresh')}
          </button>
        </div>
        {status?.error && <div className="notice">{status.error}</div>}
        {restart && (
          <div className="notice accent row">
            <span className="sp">{t('aiacc.keyRestart')}</span>
            <button className="btn sm" onClick={() => void window.desk.restartEngine().then(() => setRestart(false))}>
              {t('aiacc.restart')}
            </button>
          </div>
        )}
        {group('subscription-cli', 'aiacc.group.cli')}
        {routes && <RoutesEditor routes={routes.routes} own={Boolean(routes.saved)} />}
        {group('api', 'aiacc.group.api')}
        {group('local', 'aiacc.group.local')}
      </div>
      {login && <LoginTerminal req={login} onClose={() => setLogin(null)} />}
    </div>
  );
}

/** A provider the engine did not report (older engine): shown as not set up, not as "checking" forever. */
function missingRow(p: ProviderId): AuthRow {
  const kind = PROVIDERS[p].kind;
  return { provider: p, kind, ready: false, state: kind === 'api' ? 'not-configured' : kind === 'local' ? 'server-down' : 'not-installed' };
}

function Pill({ row }: { row: AuthRow | undefined }) {
  const p = pill(row);
  const plan = row?.state === 'logged-in' && row.account?.plan ? row.account.plan.charAt(0).toUpperCase() + row.account.plan.slice(1) : null;
  const cls = p.tone === 'ok' ? 'done' : p.tone === 'bad' ? 'error' : p.tone === 'warn' ? 'you' : '';
  return (
    <span className={`st ${cls}`} data-testid="provider-pill" data-state={row?.state ?? 'checking'}>
      {plan ? t('aiacc.st.loggedInPlan', { plan }) : tk(p.key)}
    </span>
  );
}

function ProviderCard({
  p,
  row,
  focused,
  keys,
  onKeys,
  onLogin,
}: {
  p: ProviderId;
  row: AuthRow | undefined;
  focused: boolean;
  keys: SecretsStatusMsg | null;
  onKeys: (k: SecretsStatusMsg) => void;
  onLogin: (r: LoginReq) => void;
}) {
  const ui = useUi();
  const def = PROVIDERS[p];
  const [test, setTest] = useState<AiTestMsg | 'running' | null>(null);
  const [showInstall, setShowInstall] = useState(false);
  const [key, setKey] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const cli = def.kind === 'subscription-cli';
  const st = row?.state;
  const runTest = async () => {
    setTest('running');
    setTest(await window.desk.ai.test(p));
  };
  const acct = row?.account;
  const method = acct?.auth_method === 'chatgpt' ? t('aiacc.method.chatgpt') : acct?.auth_method === 'api-key' ? t('aiacc.method.apiKey') : null;
  const lines: ReactNode[] = [];
  if (acct?.email) lines.push(<span key="e" className="mono">{acct.email}</span>);
  if (method) lines.push(<span key="m">{method}</span>);
  if (row?.version) lines.push(<span key="v" className="faint">{row.version}</span>);
  const cliP = p as 'claude-code' | 'codex';
  const variants: { id: LoginReq['variant']; key: MessageKey }[] =
    p === 'claude-code'
      ? [
          { id: 'console', key: 'aiacc.variant.console' },
          { id: 'sso', key: 'aiacc.variant.sso' },
        ]
      : p === 'codex'
        ? [{ id: 'device', key: 'aiacc.variant.device' }]
        : [];
  const secret = def.secret;
  const hasKey = secret ? Boolean(keys?.keys[secret]) : false;
  return (
    <div
      className="card col"
      style={{ gap: 8, outline: focused ? '2px solid var(--accent)' : undefined }}
      data-provider-card={p}
      data-testid={`provider-${p}`}
    >
      <div className="row">
        <b style={{ fontWeight: 500 }}>{def.name}</b>
        <span className="sp" />
        <Pill row={row} />
      </div>
      <span className="muted small">{tk(cli ? `aiacc.desc.${p}` : def.kind === 'api' ? 'aiacc.desc.api' : 'aiacc.desc.local')}</span>
      {lines.length > 0 && (
        <div className="row small muted" style={{ flexWrap: 'wrap', gap: 6 }} data-testid="provider-account">
          {lines}
        </div>
      )}
      {cli && st === 'logged-in' && row?.verified === false && <span className="faint small">{t('aiacc.unverified')}</span>}
      {row?.base_url && def.kind === 'local' && <span className="mono small faint">{t('aiacc.server', { url: row.base_url })}</span>}
      {row?.models?.length ? <span className="small muted clamp2">{t('aiacc.models', { n: row.models.length, list: row.models.slice(0, 6).join(', ') })}</span> : null}
      {row?.detail && st !== 'logged-in' && <span className="small faint clamp2" title={row.detail}>{row.detail}</span>}
      {secret && (
        <div className="col" style={{ gap: 4 }}>
          <div className="row">
            <input
              className="input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              style={{ flex: 1 }}
              aria-label={def.name}
              placeholder={hasKey ? t('aiacc.keyReplace') : t('aiacc.keyPlaceholder')}
              value={key}
              disabled={keys?.backend !== 'keychain'}
              onChange={(e) => setKey(e.target.value)}
              data-testid={`key-input-${p}`}
            />
            <button
              className="btn sm"
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
              {t('aiacc.keySave')}
            </button>
            {hasKey && (
              <button className="btn ghost sm" onClick={async () => onKeys(await window.desk.secrets.clear(secret))}>
                {t('aiacc.keyRemove')}
              </button>
            )}
          </div>
          {row?.key_env && <span className="faint small">{t('aiacc.keyEnv', { env: row.key_env })}</span>}
        </div>
      )}
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {cli && row?.can_login !== false && st !== 'not-installed' && (
          <button
            className={`btn sm ${st === 'logged-in' ? '' : 'primary'}`}
            onClick={() => onLogin({ provider: cliP, action: 'login' })}
            data-testid={`login-${p}`}
          >
            {st === 'expired' || st === 'logged-in' ? t('aiacc.relogin') : t('aiacc.login')}
          </button>
        )}
        {cli && variants.length > 0 && st !== 'not-installed' && (
          <button
            className="btn ghost sm"
            onClick={(e) => {
              e.stopPropagation();
              ui.menu(
                e,
                variants.map((v) => ({ label: t(v.key), run: () => onLogin({ provider: cliP, action: 'login', variant: v.id }) })),
              );
            }}
          >
            {t('aiacc.more')}
          </button>
        )}
        {cli && row?.can_logout && (st === 'logged-in' || st === 'expired') && (
          <button
            className="btn ghost sm"
            onClick={() => {
              if (window.confirm(t('aiacc.logoutConfirm', { name: def.name }))) onLogin({ provider: cliP, action: 'logout' });
            }}
            data-testid={`logout-${p}`}
          >
            {t('aiacc.logout')}
          </button>
        )}
        {st !== 'not-installed' && (
          <button className="btn ghost sm" onClick={() => void runTest()} disabled={test === 'running'} data-testid={`test-${p}`}>
            {test === 'running' ? t('aiacc.testing') : t('aiacc.test')}
          </button>
        )}
        {row?.install && (
          <button className="btn ghost sm" onClick={() => setShowInstall((x) => !x)} data-testid={`install-${p}`}>
            {t('aiacc.install')}
          </button>
        )}
      </div>
      {showInstall && row?.install && (
        <div className="col small" style={{ gap: 4 }}>
          <div className="row">
            <span className="mono clamp1" style={{ flex: 1 }}>
              {t('aiacc.installCmd', { cmd: row.install.command })}
            </span>
            <button
              className="btn ghost sm"
              onClick={() => {
                void window.desk.copyText(row.install!.command);
                ui.toast(t('aiacc.copied'));
              }}
            >
              {t('aiacc.copy')}
            </button>
          </div>
          <a href={row.install.url} onClick={(e) => (e.preventDefault(), void window.desk.openExternal(row.install!.url))} className="small">
            {row.install.url}
          </a>
        </div>
      )}
      {test && test !== 'running' && (
        <div className={`notice small ${test.ok ? 'accent' : ''}`} data-testid={`test-result-${p}`}>
          {test.ok ? t('aiacc.testOk', { model: test.model ?? '-', s: test.seconds ?? '-' }) : t('aiacc.testFail', { error: (test.error ?? '').slice(0, 200) })}
        </div>
      )}
      {err && <div className="notice small">{err}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- which AI does what
function RoutesEditor({ routes, own }: { routes: AiRoutes; own: boolean }) {
  const { status } = useAi();
  const ui = useUi();
  const save = async (next: AiRoutes | null) => {
    try {
      await saveRoutes(next);
      ui.toast(t('aiacc.saved'));
    } catch (e) {
      ui.toast(clean(e), { error: true });
    }
  };
  const setDefault = (c: RouteChoice) => void save({ ...routes, default: c });
  const setTask = (k: AiTask, c: RouteChoice | null) => {
    const tasks = { ...routes.tasks };
    if (c) tasks[k] = c;
    else delete tasks[k];
    void save({ ...routes, tasks });
  };
  const label = (p: string) => {
    if (p === 'none') return t('aiacc.none');
    const row = rowOf(status, p);
    return `${providerName(p)}${row && !row.ready ? ` (${t('aiacc.notReady')})` : ''}`;
  };
  return (
    <div className="card col" style={{ gap: 12 }} data-testid="ai-routes">
      <div className="row">
        <b>{t('aiacc.routes')}</b>
        <span className="sp" />
        {own && (
          <button className="btn ghost sm" onClick={() => void save(null)} data-testid="routes-reset">
            {t('aiacc.reset')}
          </button>
        )}
      </div>
      <span className="muted small">
        {t('aiacc.routesHint')} {!own && t('aiacc.fromPersona')}
      </span>
      <RouteRow
        title={t('aiacc.default')}
        choice={routes.default}
        label={label}
        onChange={(c) => c && setDefault(c)}
        testId="route-default"
      />
      {AI_TASK_IDS.map((k) => (
        <RouteRow
          key={k}
          title={tk(`aiacc.task.${k}`)}
          choice={routes.tasks[k] ?? null}
          inherited={effective(routes, k)}
          label={label}
          onChange={(c) => setTask(k, c)}
          testId={`route-${k}`}
        />
      ))}
    </div>
  );
}

function RouteRow({
  title,
  choice,
  inherited,
  label,
  onChange,
  testId,
}: {
  title: string;
  choice: RouteChoice | null;
  inherited?: RouteChoice;
  label: (p: string) => string;
  onChange: (c: RouteChoice | null) => void;
  testId: string;
}) {
  const isTask = inherited !== undefined;
  const cur = choice ?? inherited!;
  const drag = useRef<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const move = (from: number, to: number) => {
    const fb = [...cur.fallback];
    const [x] = fb.splice(from, 1);
    fb.splice(to, 0, x);
    onChange({ ...cur, fallback: fb });
  };
  const addable = PROVIDER_IDS.filter((p) => p !== cur.provider && !cur.fallback.includes(p));
  return (
    <div className="row" style={{ alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }} data-testid={testId}>
      <span style={{ width: 150, paddingTop: 5 }}>{title}</span>
      <select
        className="input"
        style={{ width: 210 }}
        value={choice ? choice.provider : '__default'}
        onChange={(e) => {
          const v = e.target.value;
          if (v === '__default') onChange(null);
          else onChange({ provider: v as ProviderId | 'none', model: null, fallback: cur.fallback.filter((x) => x !== v) });
        }}
        aria-label={title}
        data-testid={`${testId}-provider`}
      >
        {isTask && <option value="__default">{`${t('aiacc.followDefault')} (${label(inherited!.provider)})`}</option>}
        {[...PROVIDER_IDS, 'none' as const].map((p) => (
          <option key={p} value={p}>
            {label(p)}
          </option>
        ))}
      </select>
      <div className="col" style={{ gap: 6, flex: 1, minWidth: 260 }}>
        {(!isTask || choice) && (
          <div className="row" style={{ flexWrap: 'wrap', gap: 6 }} data-testid={`${testId}-fallbacks`}>
            <span className="faint small">{t('aiacc.fallbacks')}</span>
            {cur.fallback.length === 0 && <span className="faint small">{t('aiacc.noFallback')}</span>}
            {cur.fallback.map((p, i) => (
              <span
                key={p}
                className={`chip ${over === i ? 'on' : ''}`}
                style={{ height: 24, padding: '0 6px', cursor: 'grab' }}
                draggable
                title={t('aiacc.dragHint')}
                onDragStart={(e) => {
                  drag.current = i;
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setOver(i);
                }}
                onDragLeave={() => setOver(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setOver(null);
                  if (drag.current !== null && drag.current !== i) move(drag.current, i);
                  drag.current = null;
                }}
                data-testid="fallback-item"
                data-provider={p}
              >
                <GripVertical className="ico" style={{ width: 12, height: 12 }} />
                {i + 1}. {providerName(p)}
                <button
                  style={{ background: 'transparent', border: 0, padding: 0, color: 'inherit', display: 'inline-flex', cursor: 'pointer' }}
                  onClick={() => onChange({ ...cur, fallback: cur.fallback.filter((x) => x !== p) })} aria-label={t('aiacc.removeFallback')}>
                  <X className="ico" style={{ width: 12, height: 12 }} />
                </button>
              </span>
            ))}
            {addable.length > 0 && cur.fallback.length < 4 && (
              <label className="chip" style={{ height: 24, padding: '0 6px', position: 'relative' }}>
                <Plus className="ico" style={{ width: 12, height: 12 }} />
                {t('aiacc.addFallback')}
                <select
                  style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
                  value=""
                  onChange={(e) => e.target.value && onChange({ ...cur, fallback: [...cur.fallback, e.target.value as ProviderId] })}
                  aria-label={t('aiacc.addFallback')}
                  data-testid={`${testId}-add-fallback`}
                >
                  <option value="" />
                  {addable.map((p) => (
                    <option key={p} value={p}>
                      {label(p)}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
