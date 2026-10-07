// AI accounts building blocks used by Settings › AI (settings/Ai.tsx): the status pill, the routes editor (which AI
// each task uses: default + per-task override + an ordered fallback list, drag to reorder).
import { useRef, useState } from 'react';
import { GripVertical, Plus, X } from 'lucide-react';
import {
  AI_TASK_IDS,
  availableProviders,
  effective,
  pill,
  PROVIDERS,
  providerName,
  type AiRoutes,
  type AiTask,
  type AuthRow,
  type ProviderId,
  type RouteChoice,
} from '../../../shared/aiRoutes';

// what this build can use (the Lite / Mac App Store build has no subscription CLIs)
const PROVIDER_IDS = availableProviders();
import { t, tk } from '../i18n';
import { rowOf, saveRoutes, useAi } from '../lib/ai';
import { useUi } from './ui';

const clean = (e: unknown) => (e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '');

/** A provider the engine did not report (older engine): shown as not set up, not as "checking" forever. */
export function missingRow(p: ProviderId): AuthRow {
  const kind = PROVIDERS[p].kind;
  return { provider: p, kind, ready: false, state: kind === 'api' ? 'not-configured' : kind === 'local' ? 'server-down' : 'not-installed' };
}

export function Pill({ row }: { row: AuthRow | undefined }) {
  const p = pill(row);
  const plan = row?.state === 'logged-in' && row.account?.plan ? row.account.plan.charAt(0).toUpperCase() + row.account.plan.slice(1) : null;
  const cls = p.tone === 'ok' ? 'done' : p.tone === 'bad' ? 'error' : p.tone === 'warn' ? 'you' : '';
  return (
    <span className={`st ${cls}`} data-testid="provider-pill" data-state={row?.state ?? 'checking'}>
      {plan ? t('aiacc.st.loggedInPlan', { plan }) : tk(p.key)}
    </span>
  );
}

// ---------------------------------------------------------------- which AI does what
export function RoutesEditor({ routes, own }: { routes: AiRoutes; own: boolean }) {
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

export function RouteRow({
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
        style={{ width: 'auto', minWidth: 210, maxWidth: 360 }}
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
