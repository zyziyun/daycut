// 历史 / History: every past batch / project found on this computer (desk + engine registries, projects, watched
// folders) without a manual import. Open puts it on the board, reveal shows it in Finder, remove only hides it
// from this list (files are never deleted).
import { useEffect, useMemo, useState } from 'react';
import type { HistoryItem } from '../../../shared/v02';
import { t, tState } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { go } from '../lib/router';
import { ErrorBox, Media } from './ui';

const STATUSES = ['delivered', 'packaged', 'done', 'in-progress', 'planned'] as const;

export function HistoryList() {
  const { client, subscribe } = useEngine();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState<'' | 'batch' | 'project'>('');
  const { data, error, reload } = useLoad((c) => c.history(), []);
  const [msg, setMsg] = useState<string | null>(null);
  const [editWatch, setEditWatch] = useState(false);
  const [watchText, setWatchText] = useState('');

  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'batches' || e.type === 'run-exit') reload();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe],
  );

  const items = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (data?.items ?? []).filter(
      (i) =>
        (!status || i.status === status) &&
        (!kind || i.kind === kind) &&
        (!ql || [i.name, i.recipe, i.client, i.dir, i.series].some((v) => (v ?? '').toLowerCase().includes(ql))),
    );
  }, [data, q, status, kind]);

  async function act(fn: () => Promise<unknown>) {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  const open = (i: HistoryItem) =>
    act(async () => {
      const r = await client!.openHistory(i.dir);
      go({ name: 'board', batch: r.id });
    });
  const hide = (i: HistoryItem) =>
    act(async () => {
      if (!window.confirm(t('history.hideConfirm', { name: i.name }))) return;
      await client!.hideHistory(i.dir);
      reload();
    });
  const saveWatch = () =>
    act(async () => {
      const list = watchText
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      await client!.setHistoryWatch(list);
      setEditWatch(false);
      reload();
    });
  const addWatch = () =>
    act(async () => {
      const dir = await window.desk.openFolder();
      if (!dir) return;
      await client!.setHistoryWatch([...(data?.watch ?? []), dir]);
      reload();
    });

  return (
    <section className="card" data-testid="history" style={{ marginTop: 18 }}>
      <div className="row" style={{ alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>{t('history.title')}</h2>
        <span className="muted small">{t('history.hint')}</span>
        <div className="sp" />
        <input className="input" placeholder={t('history.search')} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('history.search')} data-testid="history-search" style={{ width: 200 }} />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t('batches.state')}>
          <option value="">{t('history.allStates')}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`history.status.${s}`)}
            </option>
          ))}
        </select>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value as '' | 'batch' | 'project')} aria-label={t('history.kind')}>
          <option value="">{t('history.allKinds')}</option>
          <option value="batch">{t('history.kind.batch')}</option>
          <option value="project">{t('history.kind.project')}</option>
        </select>
        <button className="btn sm" onClick={() => reload()}>
          {t('history.refresh')}
        </button>
      </div>
      <div className="muted small" style={{ margin: '6px 0' }}>
        {t('history.watching')}: <span className="mono">{(data?.watch ?? []).join(' · ') || '—'}</span>{' '}
        <button className="btn sm" onClick={addWatch}>
          {t('history.addWatch')}
        </button>{' '}
        <button
          className="btn sm"
          onClick={() => {
            setWatchText((data?.watch ?? []).join('\n'));
            setEditWatch((v) => !v);
          }}
        >
          {t('history.editWatch')}
        </button>
      </div>
      {editWatch && (
        <div className="row" style={{ gap: 8, alignItems: 'flex-start', marginBottom: 8 }}>
          <textarea className="input mono" rows={3} style={{ flex: 1 }} value={watchText} onChange={(e) => setWatchText(e.target.value)} aria-label={t('history.watching')} />
          <button className="btn primary sm" onClick={saveWatch}>
            {t('clients.save')}
          </button>
        </div>
      )}
      <ErrorBox error={error && /not found|404/i.test(error) ? t('history.restart') : (error ?? msg)} />
      {data && items.length === 0 && <div className="muted">{t('history.empty')}</div>}
      {items.length > 0 && (
        <table className="t" data-testid="history-table">
          <thead>
            <tr>
              <th />
              <th>{t('batches.name')}</th>
              <th>{t('batches.recipe')}</th>
              <th>{t('new.client')}</th>
              <th>{t('history.date')}</th>
              <th>{t('batches.jobs')}</th>
              <th>{t('batches.state')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.dir} data-testid="history-row">
                <td style={{ width: 120 }}>{i.thumb ? <Media path={i.thumb} kind="img" /> : <div className="thumb ph">{t('common.noPreview')}</div>}</td>
                <td>
                  <div>
                    {i.name} {i.kind === 'project' && <span className="badge">{t('history.kind.project')}</span>}
                    {i.series && <span className="badge">{i.series}</span>}
                  </div>
                  <div className="muted small mono">{i.dir}</div>
                </td>
                <td>{i.recipe ?? '—'}</td>
                <td>{i.client ?? '—'}</td>
                <td className="small">{i.updated || i.created ? new Date((i.updated || i.created || 0) * 1000).toLocaleDateString() : '—'}</td>
                <td>
                  {i.counts.total}
                  <div className="small">
                    <span className="okc">{i.counts.green}</span> / <span className="err">{i.counts.red}</span>
                  </div>
                </td>
                <td>
                  <span className="badge">{t(`history.status.${i.status}`) === `history.status.${i.status}` ? tState(i.status) : t(`history.status.${i.status}`)}</span>
                </td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    <button className="btn sm primary" disabled={!i.openable} title={i.openable ? '' : t('history.notRun')} onClick={() => open(i)}>
                      {t('history.open')}
                    </button>
                    <button className="btn sm" onClick={() => void window.desk.showItem(i.dir)}>
                      {t('history.reveal')}
                    </button>
                    <button className="btn sm" onClick={() => hide(i)} data-testid="history-hide">
                      {t('history.hide')}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
