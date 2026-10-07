// Metrics (P0-5): per batch / client / all. Review s/clip median, rework rate, red rate, cost/clip, deliveries;
// the manual funnel per client (lead -> pilot -> paid) + 7-day data; weekly_metrics.csv export matching
// the gtm weekly metrics sheet (tests/fixtures/weekly_metrics.csv; the 内容号 / 千剪号 / release / LOI / B2B
// columns are entered here by hand).
import { useState } from 'react';
import { FUNNEL, MANUAL_WEEKLY_COLUMNS, type FunnelStage, type MetricsSummary } from '../../../shared/v02';
import { Empty, ErrorBox } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { usd } from '../lib/format';
import { href } from '../lib/router';
import { useAgencyMode } from '../lib/prefs';
import { StageBadge } from './Clients';

type Scope = { kind: 'all' } | { kind: 'client'; slug: string } | { kind: 'batch'; id: string };

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 1000) / 10}%`);
const sec = (v: number | null | undefined) => (v == null ? '—' : `${v}s`);

function Tiles({ s }: { s: MetricsSummary }) {
  const tiles: [string, string][] = [
    [t('metrics.deliveries'), String(s.deliveries)],
    [t('metrics.deliveredClips'), String(s.delivered_clips)],
    [t('metrics.reviewMedian'), sec(s.review_s_median)],
    [t('metrics.reworkRate'), pct(s.rework_rate)],
    [t('metrics.redRate'), pct(s.red_rate)],
    [t('metrics.costPerClip'), s.cost_per_clip == null ? '—' : usd(s.cost_per_clip)],
  ];
  if (s.turnaround_h != null) tiles.push([t('metrics.turnaround'), `${s.turnaround_h} h`]);
  return (
    <div className="tiles">
      {tiles.map(([k, v]) => (
        <div key={k} className="tile">
          <div className="muted small">{k}</div>
          <div className="v">{v}</div>
        </div>
      ))}
    </div>
  );
}

export function Metrics() {
  const { client } = useEngine();
  const [scope, setScope] = useState<Scope>({ kind: 'all' });
  const clients = useLoad((c) => c.clients(), []);
  const agency = useAgencyMode(); // clients only for agencies
  const batches = useLoad((c) => c.batches(), []);
  const m = useLoad((c) => c.metrics(scope.kind === 'client' ? { client: scope.slug } : scope.kind === 'batch' ? { batch: scope.id } : {}), [JSON.stringify(scope)]);
  const weekly = useLoad((c) => c.weekly(), []);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function exportCsv() {
    setErr(null);
    try {
      const w = await client!.weekly();
      const p = await window.desk.saveText('weekly_metrics.csv', w.csv);
      if (p) setSaved(p);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function setStage(slug: string, stage: FunnelStage) {
    try {
      await client!.setCrm(slug, { stage });
      m.reload();
      weekly.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function setManual(week: string, col: string, v: string) {
    const n = v.trim() === '' ? null : Number(v.replace('%', '')) * (v.trim().endsWith('%') ? 0.01 : 1);
    if (n !== null && !Number.isFinite(n)) return;
    try {
      weekly.setData(await client!.setWeekly(week, { [col]: n }));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const d = m.data;
  return (
    <>
      <div className="topbar">
        <h1>{t('nav.metrics')}</h1>
        <div className="tabs">
          <button className={`tab ${scope.kind === 'all' ? 'on' : ''}`} onClick={() => setScope({ kind: 'all' })}>
            {t('common.all')}
          </button>
        </div>
        {agency && (
          <select className="input" aria-label={t('metrics.client')} value={scope.kind === 'client' ? scope.slug : ''} onChange={(e) => setScope(e.target.value ? { kind: 'client', slug: e.target.value } : { kind: 'all' })}>
            <option value="">{t('metrics.client')}…</option>
            {(clients.data ?? []).map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        )}
        <select className="input" aria-label={t('metrics.batch')} value={scope.kind === 'batch' ? scope.id : ''} onChange={(e) => setScope(e.target.value ? { kind: 'batch', id: e.target.value } : { kind: 'all' })}>
          <option value="">{t('metrics.batch')}…</option>
          {(batches.data ?? []).map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        <div className="sp" />
        <button className="btn primary" onClick={exportCsv} data-testid="export-weekly">
          {t('metrics.export')}
        </button>
      </div>
      <div className="page col" style={{ gap: 14 }}>
        <ErrorBox error={err ?? m.error} />
        {saved && <div className="notice accent">{t('metrics.saved', { p: saved })}</div>}
        {d && <Tiles s={d.summary} />}
        {d?.source === 'engine' && <div className="muted small">{t('metrics.fromEngine')}</div>}
        {d?.jobs && (
          <div className="card">
            <table className="t small" data-testid="job-metrics">
              <thead>
                <tr>
                  <th>{t('metrics.job')}</th>
                  <th>QC</th>
                  <th>{t('metrics.reviewS')}</th>
                  <th>{t('metrics.edits')}</th>
                  <th>{t('metrics.reruns')}</th>
                  <th>{t('metrics.rejected')}</th>
                  <th>{t('metrics.cost')}</th>
                </tr>
              </thead>
              <tbody>
                {d.jobs.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <span className="mono">{j.id}</span> <span className="muted">{j.title}</span>
                    </td>
                    <td>{j.qc ?? '—'}</td>
                    <td>{j.review_s ? `${j.review_s}s` : '—'}</td>
                    <td>{j.edits}</td>
                    <td>{j.reruns}</td>
                    <td>{j.rejected ? '✕' : ''}</td>
                    <td>{usd(j.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d?.batches && d.batches.length > 0 && (
          <div className="card">
            <table className="t small">
              <thead>
                <tr>
                  <th>{t('metrics.batch')}</th>
                  <th>{t('metrics.clips')}</th>
                  <th>{t('metrics.reviewMedian')}</th>
                  <th>{t('metrics.reworkRate')}</th>
                  <th>{t('metrics.redRate')}</th>
                  <th>{t('metrics.costPerClip')}</th>
                  <th>{t('metrics.deliveredClips')}</th>
                </tr>
              </thead>
              <tbody>
                {d.batches.map((b) => (
                  <tr key={b.batch} className="click" onClick={() => setScope({ kind: 'batch', id: b.batch })}>
                    <td>{b.name}</td>
                    <td>{b.jobs}</td>
                    <td>{sec(b.review_s_median)}</td>
                    <td>{pct(b.rework_rate)}</td>
                    <td>{pct(b.red_rate)}</td>
                    <td>{b.cost_per_clip == null ? '—' : usd(b.cost_per_clip)}</td>
                    <td>{b.delivered_clips}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {agency && d?.clients && (
          <div className="card col">
            <b>{t('metrics.funnel')}</b>
            {d.clients.length === 0 && <Empty>{t('clients.empty')}</Empty>}
            <table className="t small">
              <thead>
                <tr>
                  <th>{t('clients.name')}</th>
                  <th>{t('clients.stage')}</th>
                  <th>{t('metrics.revenue')}</th>
                  <th>{t('metrics.posts')}</th>
                  <th>{t('crm.priceNext')}</th>
                </tr>
              </thead>
              <tbody>
                {d.clients.map((c) => (
                  <tr key={c.slug}>
                    <td>
                      <a href={href({ name: 'client', slug: c.slug })}>{c.name}</a>
                    </td>
                    <td>
                      <select className="input" aria-label={t('clients.stage')} value={c.crm.stage ?? ''} onChange={(e) => setStage(c.slug, e.target.value as FunnelStage)}>
                        <option value="" disabled>
                          —
                        </option>
                        {[...FUNNEL, 'lost' as const].map((s) => (
                          <option key={s} value={s}>
                            {t(`funnel.${s}`)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>¥{c.crm.revenue.reduce((a, r) => a + r.amount, 0)}</td>
                    <td>{c.crm.posts.length}</td>
                    <td>{c.crm.price_next != null ? `¥${c.crm.price_next}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d?.crm && (
          <div className="card row">
            <b>{t('crm.title')}</b>
            <StageBadge stage={d.crm.stage} />
            <span className="small muted">
              {t('metrics.revenue')} ¥{d.crm.revenue.reduce((a, r) => a + r.amount, 0)} · {t('metrics.posts')} {d.crm.posts.length}
            </span>
          </div>
        )}
        {weekly.data && (
          <div className="card col">
            <div className="row">
              <b>weekly_metrics.csv</b>
              <span className="muted small">{t('metrics.weeklyHint')}</span>
            </div>
            <div style={{ overflow: 'auto' }}>
              <table className="t small weekly" data-testid="weekly">
                <thead>
                  <tr>
                    {weekly.data.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {weekly.data.rows.map((r) => {
                    const week = String(r['周']).split('(')[0];
                    return (
                      <tr key={String(r['周'])}>
                        {weekly.data!.columns.map((c) =>
                          (MANUAL_WEEKLY_COLUMNS as readonly string[]).includes(c) ? (
                            <td key={c}>
                              <input className="input" style={{ width: 80 }} aria-label={`${week} ${c}`} defaultValue={String(r[c] ?? '')} onBlur={(e) => e.target.value !== String(r[c] ?? '') && void setManual(week, c, e.target.value)} />
                            </td>
                          ) : (
                            <td key={c}>{String(r[c] ?? '')}</td>
                          ),
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
