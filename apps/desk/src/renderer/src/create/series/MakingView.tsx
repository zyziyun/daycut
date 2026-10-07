// Making (C07): every episode being made, one cell per shot; money of this run; a timeout is shown with "check
// the service" and "try again" (a new estimate + confirm for that one shot) - never retried on its own.
import { useState } from 'react';
import { Check, CircleDollarSign, Clock, Pause, TriangleAlert } from 'lucide-react';
import type { MakingView as MV, SeriesView } from '../../../../shared/create';
import { yuan } from '../../../../shared/create';
import { has, t, tk } from '../../i18n';
import { media } from '../../v4/kit';
import { useAction, useCreate, useCreateLoad, useCreateRefresh } from '../api';
import { localGenEnabled } from '../flag';
import { goCreate } from '../routes';
import { SpendSheet } from '../episode/SpendSheet';

export const svc = (p: string) => (has(`create.svc.${p}`) ? tk(`create.svc.${p}`) : p);
const SITE: Record<string, string> = {
  'kling-mcp': 'https://klingai.com/',
  minimax: 'https://www.minimax.io/platform',
  veo: 'https://aistudio.google.com/',
  'seedance-ark': 'https://console.volcengine.com/ark',
};

export function MakingView({ s }: { s: SeriesView }) {
  const c = useCreate();
  const { data, reload } = useCreateLoad((x) => x.runs(s.id), [s.id]);
  const running = (data?.rows ?? []).some((r) => r.state === 'running');
  useCreateRefresh(reload, running, 1200);
  const [retry, setRetry] = useState<{ eid: string; shots: string[] } | null>(null);
  const pause = useAction();
  if (!data) return null;
  const v: MV = data;
  if (!v.rows.length) return <div className="empty" data-testid="create-making-empty">{t('create.making.empty')}</div>;
  const pickRow = v.rows.find((r) => r.pick > 0);
  const services = Object.entries(v.running);
  return (
    <div data-testid="create-making">
      <div className="cr-stats">
        <div className="card cr-stat">
          <div className="l">
            <CircleDollarSign className="ico" />
            {t('create.making.spent')}
          </div>
          <div className="v">
            <b>{yuan(v.spent)}</b>
            {t('create.making.ofApproved', { n: yuan(v.approved) })}
          </div>
          <div className="cr-meter">
            <i className="st" style={{ width: `${v.approved ? Math.min(100, (v.spent / v.approved) * 100) : 0}%` }} />
          </div>
        </div>
        {(services.length ? services : [['kling-mcp', 0] as [string, number]]).slice(0, 2).map(([p, n]) => (
          <div key={p} className="card cr-stat">
            <div className="l">
              <i className={`cr-sw sw-${p === 'kling-mcp' ? 'kling' : p === 'minimax' ? 'hailuo' : p === 'veo' ? 'veo' : 'seed'}`} />
              {svc(p)}
            </div>
            <div className="v">
              <b>{n}</b>
              {t('create.making.running', { n: v.limits[p] ?? 4 })}
            </div>
          </div>
        ))}
        {localGenEnabled() && (
          <div className="card cr-stat">
            <div className="l">
              <i className="cr-sw sw-local" />
              {t('create.making.local')}
            </div>
            <div className="v">
              <b>1</b>
              {t('create.making.localSub')}
            </div>
          </div>
        )}
        <div className="card cr-stat">
          <div className="l">
            <Clock className="ico" />
            {t('create.making.doneAround')}
          </div>
          <div className="v">{v.eta ? <><b>{v.eta}</b>{t('create.making.today')}</> : <b style={{ fontSize: 18 }}>{t('create.making.idle')}</b>}</div>
        </div>
      </div>

      {v.alerts
        .filter((a) => a.code === 'create.unknown-charge')
        .map((a, i) => {
          const p = a.params as { provider?: string; shots?: string[]; cny?: number };
          const svcName = svc(p.provider ?? '');
          return (
            <div key={i} className="cr-alert" data-testid="create-alert-timeout">
              <TriangleAlert className="ico" />
              <span>
                <b style={{ fontWeight: 500 }}>{t('create.making.timeout', { ep: t('create.ep.short', { n: a.episode_no }), shots: (p.shots ?? []).join(', '), service: svcName })}</b>{' '}
                {t('create.making.timeoutBody')}
              </span>
              <span className="acts">
                {SITE[p.provider ?? ''] && (
                  <button className="btn" onClick={() => void window.desk.openExternal(SITE[p.provider ?? ''])}>
                    {t('create.making.check', { service: svcName })}
                  </button>
                )}
                <button className="btn" onClick={() => setRetry({ eid: a.episode, shots: p.shots ?? [] })} data-testid="create-retry-shot">
                  {t('create.making.tryAgain', { n: yuan(p.cny ?? 0) })}
                </button>
              </span>
            </div>
          );
        })}

      {v.rows.map((r) => (
        <div key={r.id} className="card cr-eprow" data-testid="create-making-row">
          <div className="hd">
            <b style={{ fontWeight: 500 }}>{t('create.ep.title', { n: r.no, title: r.title })}</b>
            <span className="sub">
              {t('create.making.finalShots')}
              {Object.keys(v.running).length > 0 && r.state === 'running' ? ` · ${Object.entries(v.running).map(([p, n]) => t('create.making.onService', { n, service: svc(p) })).join(' · ')}` : ''}
            </span>
            <span className="right">
              <span className="num">{yuan(r.spent)}</span>
              {r.paused ? (
                <span className="cr-pill you">{t('create.making.paused')}</span>
              ) : r.pick ? (
                <span className="cr-pill you">{t('create.making.pickN', { n: r.pick })}</span>
              ) : r.state === 'running' ? (
                <span className="cr-pill run">{t('create.making.progress', { done: r.done, total: r.total, m: r.eta_min ?? 1 })}</span>
              ) : null}
            </span>
          </div>
          <div className="cr-cells">
            {r.cells.map((cell) => (
              <button
                key={cell.no}
                className={`cr-cell ${cell.state}`}
                onClick={() => goCreate({ screen: 'episode', eid: r.id, tab: cell.state === 'pick' ? 'takes' : 'storyboard' })}
                title={cell.no}
                data-testid="create-cell"
                data-state={cell.state}
              >
                {cell.still && <img src={media(cell.still)} alt="" />}
                {cell.state === 'pick' && <span className="ov">{t('create.making.takesN', { n: cell.n_takes })}</span>}
                {cell.state === 'run' && <span className="ov">…</span>}
                {cell.state === 'bad' && <span className="ov">!</span>}
                {cell.state === 'you' && <span className="ov">{svc('jimeng')}</span>}
                {cell.state === 'ok' && (
                  <span className="okm">
                    <Check className="ico" />
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      ))}

      <div className="cr-mkfoot">
        {(
          [
            ['ok', 'var(--ok)', 'create.legend.ok'],
            ['run', 'var(--run)', 'create.legend.run'],
            ['local', 'var(--src-local)', 'create.legend.local'],
            ['you', 'var(--you)', 'create.legend.you'],
            ['q', 'var(--surface-3)', 'create.legend.q'],
          ] as const
        ).map(([k, col, key]) => (
          <span key={k} className="k">
            <i style={{ background: col }} />
            {t(key)}
          </span>
        ))}
        <span className="acts">
          <button
            className="btn lg"
            disabled={!running || pause.busy}
            onClick={() =>
              void pause.run(async () => {
                if (!c) return;
                for (const r of v.rows.filter((x) => x.state === 'running')) await c.stop(r.id);
                reload();
              })
            }
          >
            <Pause className="ico" />
            {t('create.making.pauseAll')}
          </button>
          {pickRow && (
            <button className="btn primary lg" onClick={() => goCreate({ screen: 'episode', eid: pickRow.id, tab: 'takes' })} data-testid="create-pick-takes">
              {t('create.making.pickIn', { n: pickRow.pick, ep: pickRow.no })}
            </button>
          )}
        </span>
      </div>
      {retry && <SpendSheet eid={retry.eid} only={retry.shots} onClose={() => setRetry(null)} onStarted={() => (setRetry(null), reload())} />}
    </div>
  );
}
