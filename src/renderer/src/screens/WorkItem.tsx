// One entry of 全部项目: live status, outputs so far (players), covers, contact sheets, post copy, notes, the log
// tail; 转成项目 (adopt) for a plain work folder; open on the board for a batch / project; reveal; remove from list.
import { useEffect, useState } from 'react';
import { LiveLane, statusLabel, typeLabel } from '../components/HistoryList';
import { ErrorBox, Media } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { go, href } from '../lib/router';

const base = (p: string) => p.split(/[\\/]/).pop() ?? p;

export function WorkItem({ id }: { id: string }) {
  const { client } = useEngine();
  const { data: list } = useHistory();
  const { data, error, reload } = useLoad((c) => c.historyItem(id), [id]);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (list) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list?.at]);

  async function act(fn: () => Promise<unknown>) {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  const d = data?.detail;
  return (
    <>
      <div className="topbar">
        <a href={href({ name: 'work' })} className="muted">
          ← {t('nav.allWork')}
        </a>
        <h1 style={{ marginLeft: 10 }}>{data?.name ?? '…'}</h1>
        {data && <span className="badge">{typeLabel(data.type)}</span>}
        {data && <span className="badge">{statusLabel(data.status)}</span>}
        <div className="sp" />
        {data && data.kind !== 'work' && data.openable && (
          <button className="btn primary" onClick={() => act(async () => go({ name: 'board', batch: (await client!.openHistory(data.dir)).id }))}>
            {t('history.openBoard')}
          </button>
        )}
        {data && data.kind === 'work' && (
          <button className="btn primary" data-testid="adopt" disabled={!!data.adopted} title={t('history.adoptHint')} onClick={() => act(async () => (await client!.adoptHistory(id), reload()))}>
            {data.adopted ? t('history.adopted') : t('history.adopt')}
          </button>
        )}
        {data && (
          <button className="btn" onClick={() => void window.desk.showItem(data.dir)}>
            {t('history.reveal')}
          </button>
        )}
      </div>
      <div className="page" data-testid="work-item">
        <ErrorBox error={error ?? msg} />
        {data && <div className="muted small mono">{data.dir}</div>}
        {data?.live && <LiveLane items={[data]} onOpen={() => undefined} />}
        {d && d.outputs.length > 0 && (
          <section>
            <h3>{t('history.outputs')}</h3>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
              {d.outputs.map((p) => (
                <figure key={p} style={{ margin: 0, width: 220 }}>
                  <Media path={p} kind="video" />
                  <figcaption className="small mono muted">{base(p)}</figcaption>
                </figure>
              ))}
            </div>
          </section>
        )}
        {d && d.covers.length + d.sheets.length > 0 && (
          <section>
            <h3>{t('history.covers')}</h3>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
              {[...d.covers, ...d.sheets].map((p) => (
                <figure key={p} style={{ margin: 0, width: 200 }}>
                  <Media path={p} kind="img" />
                  <figcaption className="small mono muted">{base(p)}</figcaption>
                </figure>
              ))}
            </div>
          </section>
        )}
        {d?.posts.map((p) => (
          <section key={p.path}>
            <h3>
              {t('history.post')} <span className="small mono muted">{base(p.path)}</span>
              <button className="btn sm" style={{ marginLeft: 8 }} onClick={() => void window.desk.copyText(p.text)}>
                {t('history.copy')}
              </button>
            </h3>
            <pre className="card small" style={{ whiteSpace: 'pre-wrap' }}>
              {p.text}
            </pre>
          </section>
        ))}
        {d?.notes.map((n) => (
          <details key={n.path}>
            <summary>
              {t('history.notes')} · <span className="mono">{base(n.path)}</span>
            </summary>
            <pre className="card small" style={{ whiteSpace: 'pre-wrap', maxHeight: 400, overflow: 'auto' }}>
              {n.text}
            </pre>
          </details>
        ))}
        {data?.log && (
          <details open={!!data.live && data.live.state !== 'done'}>
            <summary>
              {t('history.log')} · <span className="mono">{base(data.log.path)}</span>
            </summary>
            <pre className="card small mono" data-testid="log-tail" style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
              {data.log.text}
            </pre>
          </details>
        )}
        {d && !d.outputs.length && !d.posts.length && !d.notes.length && <div className="muted">{t('history.nothingYet')}</div>}
      </div>
    </>
  );
}
