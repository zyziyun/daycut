import { useEffect, useState } from 'react';
import { ErrorBox, Empty, StateBadge } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { go, href } from '../lib/router';

export function Batches() {
  const { client, subscribe } = useEngine();
  const { data, error, reload } = useLoad((c) => c.batches(), []);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'batches' || e.type === 'run-exit' || e.type === 'run-start') reload();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe],
  );

  async function importBatch() {
    const dir = await window.desk.openFolder();
    if (!dir || !client) return;
    try {
      const r = await client.importBatch(dir);
      go({ name: 'board', batch: r.id });
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  return (
    <>
      <div className="topbar">
        <h1>{t('batches.title')}</h1>
        <div className="sp" />
        <button className="btn" onClick={importBatch}>
          {t('batches.import')}
        </button>
        <a className="btn primary" href={href({ name: 'new' })}>
          {t('batches.new')}
        </a>
      </div>
      <div className="page">
        <ErrorBox error={error ?? msg} />
        {data && data.length === 0 && <Empty>{t('batches.empty')}</Empty>}
        {data && data.length > 0 && (
          <table className="t">
            <thead>
              <tr>
                <th>{t('batches.name')}</th>
                <th>{t('new.client')}</th>
                <th>{t('batches.recipe')}</th>
                <th>{t('batches.state')}</th>
                <th>{t('batches.jobs')}</th>
                <th>{t('batches.qc')}</th>
                <th>{t('batches.package')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((b) => (
                <tr key={b.id} className="click" onClick={() => go({ name: 'board', batch: b.id })}>
                  <td>
                    <div>{b.name}</div>
                    <div className="muted small mono">{b.dir}</div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>{b.client ? <a href={href({ name: 'client', slug: b.client })}>{b.client}</a> : <span className="muted">—</span>}</td>
                  <td>{b.recipe ?? '-'}</td>
                  <td>
                    <div className="row">
                      <StateBadge state={b.running ? 'running' : b.state} />
                      {b.delivered && <span className="badge accent">{t('deliver.delivered')}</span>}
                      {b.pause_reason && <span className="small warnc">{b.pause_reason}</span>}
                    </div>
                  </td>
                  <td>{b.counts?.total ?? '-'}</td>
                  <td>
                    <span className="okc">{b.counts?.green ?? 0}</span> / <span className="err">{b.counts?.red ?? 0}</span>
                  </td>
                  <td className="mono small">{b.package ? `${b.package.code} · ${b.package.items}` : '-'}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="row">
                      <a className="btn sm" href={href({ name: 'review', batch: b.id })}>
                        {t('nav.review')}
                      </a>
                      <a className="btn sm" href={href({ name: 'deliver', batch: b.id })}>
                        {t('nav.deliver')}
                      </a>
                      <a className="btn sm" href={href({ name: 'publish', batch: b.id })}>
                        {t('nav.publish')}
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
