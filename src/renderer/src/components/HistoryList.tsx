// 全部项目 / All work (also on the Batches page as 历史 / History): every batch, project and plain work folder made
// on this computer - desk + engine registries, projects, watched folders - without an import. The 进行中 lane on
// top shows live runs (inside or outside the app). Open puts a batch on the board / shows a work folder, reveal
// shows it in Finder, remove only hides it from this list (files are never deleted).
import { useMemo, useState } from 'react';
import { WORK_TYPES, type HistoryItem } from '../../../shared/v02';
import { t, tState } from '../i18n';
import { useEngine } from '../lib/engine';
import { fmtDuration, useHistory } from '../lib/history';
import { go } from '../lib/router';
import { ErrorBox, Media } from './ui';

const STATUSES = ['delivered', 'packaged', 'done', 'in-progress', 'planned', 'adopted'] as const;
const DATES = { all: 0, d7: 7, d30: 30, d90: 90 } as const;

export function statusLabel(s: string): string {
  const k = `history.status.${s}`;
  return t(k) === k ? tState(s) : t(k);
}

export function typeLabel(s: string | undefined): string {
  const k = `history.type.${s ?? 'other'}`;
  return t(k) === k ? (s ?? '—') : t(k);
}

export function LiveLane({ items, onOpen }: { items: HistoryItem[]; onOpen: (i: HistoryItem) => void }) {
  const now = Date.now() / 1000;
  if (!items.length) return null;
  return (
    <div data-testid="live-lane" style={{ margin: '8px 0 14px' }}>
      <h3 style={{ margin: '0 0 6px' }}>
        {t('history.running')} <span className="badge accent">{items.filter((i) => i.live?.state !== 'interrupted').length}</span>
      </h3>
      {items.map((i) => {
        const l = i.live!;
        const end = l.state === 'running' || l.state === 'waiting' ? now : (l.heartbeat ?? now);
        const elapsed = l.started ? end - l.started : null;
        return (
          <div key={i.dir} className="card" data-testid="live-row" style={{ padding: 10, marginBottom: 6, cursor: 'pointer' }} onClick={() => onOpen(i)}>
            <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <b>{i.name}</b>
              <span className="badge">{typeLabel(i.type)}</span>
              {l.needs_you ? (
                <span className="badge danger" data-testid="needs-you">
                  {t('history.needsYou')}
                </span>
              ) : (
                <span className={`badge ${l.state === 'interrupted' ? 'danger' : 'accent'}`} data-testid="live-state">
                  {t(`history.live.${l.state}`)}
                </span>
              )}
              {l.stage && <span className="small mono">{l.stage}</span>}
              <div className="sp" />
              <span className="small muted">
                {t('history.elapsed')} {fmtDuration(elapsed)}
                {l.eta != null && l.state === 'running' ? ` · ${t('history.eta')} ${fmtDuration(l.eta)}` : ''}
                {l.age != null ? ` · ${t('history.lastBeat', { s: fmtDuration(l.age) })}` : ''}
              </span>
            </div>
            {l.progress != null && (
              <div className="progress" style={{ marginTop: 6 }}>
                <i style={{ width: `${Math.round(Math.max(0, Math.min(1, l.progress)) * 100)}%` }} />
              </div>
            )}
            {l.message && (
              <div className="small muted" style={{ marginTop: 4 }}>
                {l.message}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function HistoryList({ full = false }: { full?: boolean }) {
  const { client } = useEngine();
  const { data, error, reload, live } = useHistory();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState<'' | 'batch' | 'project' | 'work'>('');
  const [type, setType] = useState('');
  const [who, setWho] = useState('');
  const [when, setWhen] = useState<keyof typeof DATES>('all');
  const [msg, setMsg] = useState<string | null>(null);
  const [editWatch, setEditWatch] = useState(false);
  const [watchText, setWatchText] = useState('');

  const clients = useMemo(() => [...new Set((data?.items ?? []).map((i) => i.client).filter(Boolean) as string[])].sort(), [data]);
  const types = useMemo(() => WORK_TYPES.filter((ty) => (data?.items ?? []).some((i) => i.type === ty)), [data]);
  const items = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const since = DATES[when] ? Date.now() / 1000 - DATES[when] * 86400 : 0;
    return (data?.items ?? []).filter(
      (i) =>
        (!status || i.status === status) &&
        (!kind || i.kind === kind) &&
        (!type || i.type === type) &&
        (!who || i.client === who) &&
        (!since || (i.updated ?? i.created ?? 0) >= since) &&
        (!ql || [i.name, i.recipe, i.client, i.dir, i.series].some((v) => (v ?? '').toLowerCase().includes(ql))),
    );
  }, [data, q, status, kind, type, who, when]);

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
      if (i.kind === 'work' || !i.openable) {
        go({ name: 'workItem', id: i.id });
        return;
      }
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
    <section className={full ? '' : 'card'} data-testid="history" style={full ? undefined : { marginTop: 18 }}>
      {full && <LiveLane items={live} onOpen={open} />}
      <div className="row" style={{ alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {!full && <h2 style={{ margin: 0 }}>{t('history.title')}</h2>}
        <span className="muted small">{t('history.hint')}</span>
        <div className="sp" />
        <input className="input" placeholder={t('history.search')} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('history.search')} data-testid="history-search" style={{ width: 200 }} />
        <select className="input" value={type} onChange={(e) => setType(e.target.value)} aria-label={t('history.typeLabel')} data-testid="history-type">
          <option value="">{t('history.allTypes')}</option>
          {types.map((ty) => (
            <option key={ty} value={ty}>
              {typeLabel(ty)}
            </option>
          ))}
        </select>
        <select className="input" value={who} onChange={(e) => setWho(e.target.value)} aria-label={t('new.client')}>
          <option value="">{t('history.allClients')}</option>
          {clients.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t('batches.state')}>
          <option value="">{t('history.allStates')}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value as '' | 'batch' | 'project' | 'work')} aria-label={t('history.kind')}>
          <option value="">{t('history.allKinds')}</option>
          <option value="batch">{t('history.kind.batch')}</option>
          <option value="project">{t('history.kind.project')}</option>
          <option value="work">{t('history.kind.work')}</option>
        </select>
        <select className="input" value={when} onChange={(e) => setWhen(e.target.value as keyof typeof DATES)} aria-label={t('history.date')}>
          {Object.keys(DATES).map((k) => (
            <option key={k} value={k}>
              {t(`history.when.${k}`)}
            </option>
          ))}
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
              <th>{t('history.typeLabel')}</th>
              <th>{t('new.client')}</th>
              <th>{t('history.date')}</th>
              <th>{t('history.outputs')}</th>
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
                    {i.name} <span className="badge">{t(`history.kind.${i.kind}`)}</span>
                    {i.series && <span className="badge">{i.series}</span>}
                  </div>
                  <div className="muted small mono">{i.dir}</div>
                </td>
                <td>
                  {typeLabel(i.type)}
                  {i.recipe && <div className="muted small mono">{i.recipe}</div>}
                </td>
                <td>{i.client ?? '—'}</td>
                <td className="small">{i.updated || i.created ? new Date((i.updated || i.created || 0) * 1000).toLocaleDateString() : '—'}</td>
                <td>
                  {i.counts.total}
                  {i.kind !== 'work' && (
                    <div className="small">
                      <span className="okc">{i.counts.green}</span> / <span className="err">{i.counts.red}</span>
                    </div>
                  )}
                </td>
                <td>
                  <span className="badge">{statusLabel(i.status)}</span>
                  {i.live && (i.live.state === 'running' || i.live.state === 'waiting' || i.live.state === 'interrupted') && (
                    <span className={`badge ${i.live.needs_you || i.live.state === 'interrupted' ? 'danger' : 'accent'}`}>{i.live.needs_you ? t('history.needsYou') : t(`history.live.${i.live.state}`)}</span>
                  )}
                </td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    <button className="btn sm primary" onClick={() => open(i)} data-testid="history-open">
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

/** Settings: the folders 全部项目 scans (default ~/Desktop/video-studio-demos). Never deletes anything. */
export function WatchFoldersField() {
  const { client } = useEngine();
  const { data, reload } = useHistory();
  const [text, setText] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const value = text ?? (data?.watch ?? []).join('\n');
  return (
    <div data-testid="watch-folders">
      <textarea className="input mono" rows={3} style={{ width: '100%' }} value={value} onChange={(e) => setText(e.target.value)} aria-label={t('history.watching')} />
      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <button
          className="btn sm"
          onClick={async () => {
            const dir = await window.desk.openFolder();
            if (dir) setText([...value.split('\n').filter((s) => s.trim()), dir].join('\n'));
          }}
        >
          {t('history.addWatch')}
        </button>
        <button
          className="btn sm primary"
          onClick={async () => {
            setMsg(null);
            try {
              await client!.setHistoryWatch(value.split('\n').map((s) => s.trim()).filter(Boolean));
              setText(null);
              reload();
              setMsg(t('settings.saved'));
            } catch (e) {
              setMsg((e as Error).message);
            }
          }}
        >
          {t('clients.save')}
        </button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
    </div>
  );
}
