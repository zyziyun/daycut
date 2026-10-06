// Client delivery package (P0-4): per-platform folders, covers, 文案.md (with the AI-label reminder), 排期表.csv,
// 交付说明.md, manifest (sha256) and a zip; the batch becomes "delivered"; source footage goes to the Trash
// N days later (setting).
import { useEffect, useState } from 'react';
import { ErrorBox, Field } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { bytes, hms } from '../lib/format';
import { href } from '../lib/router';
import { ClientSelect } from './NewBatch';

export function Deliver({ batch }: { batch: string }) {
  const { client } = useEngine();
  const st = useLoad((c) => c.status(batch), [batch]);
  const del = useLoad((c) => c.delivery(batch), [batch]);
  const batches = useLoad((c) => c.batches(), []);
  const [clientSlug, setClientSlug] = useState('');
  const [zip, setZip] = useState(true);
  const [cleanup, setCleanup] = useState(true);
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void window.desk.getSettings().then((s) => {
      if (s.cleanupDays === 0) setCleanup(false);
      else if (s.cleanupDays) setDays(s.cleanupDays);
    });
  }, []);
  useEffect(() => {
    const b = batches.data?.find((x) => x.id === batch);
    if (b?.client) setClientSlug(b.client);
  }, [batches.data, batch]);

  const jobs = st.data?.jobs ?? [];
  const approved = jobs.filter((j) => j.state === 'approved' || j.state === 'packaged');
  const open = jobs.filter((j) => j.state === 'done');
  const d = del.data?.delivery ?? null;

  async function deliver() {
    if (!client) return;
    setBusy(true);
    setErr(null);
    try {
      if (clientSlug && batches.data?.find((x) => x.id === batch)?.client !== clientSlug) await client.setBatchClient(batch, clientSlug);
      await client.deliver(batch, { client: clientSlug || undefined, zip, cleanup_days: cleanup ? days : null });
      del.reload();
      batches.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveCleanup(enabled: boolean, n: number) {
    if (!client) return;
    try {
      await client.setCleanup(batch, { enabled, days: enabled ? n : null });
      del.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <>
      <div className="topbar">
        <h1>{t('deliver.title')}</h1>
        <span className="muted small">{st.data?.meta.name}</span>
        {d && <span className="badge accent">{t('deliver.delivered')}</span>}
        <div className="sp" />
      </div>
      <div className="page col" style={{ maxWidth: 860, gap: 14 }}>
        <ErrorBox error={err ?? st.error ?? del.error} />
        <div className="card col">
          <div className="row" style={{ gap: 18 }}>
            <span>
              {t('deliver.approved')}: <b>{approved.length}</b>
            </span>
            <span className={open.length ? 'warnc' : 'muted'}>
              {t('deliver.open')}: {open.length}
            </span>
            {open.length > 0 && <a href={href({ name: 'review', batch })}>{t('deliver.toReview')}</a>}
          </div>
          <Field label={t('new.client')}>
            <ClientSelect value={clientSlug} onChange={setClientSlug} />
          </Field>
          <label className="row small">
            <input type="checkbox" checked={zip} onChange={(e) => setZip(e.target.checked)} /> {t('deliver.zip')}
          </label>
          <label className="row small">
            <input type="checkbox" checked={cleanup} onChange={(e) => setCleanup(e.target.checked)} data-testid="cleanup-toggle" />
            {t('deliver.cleanup')}
            <input className="input" type="number" min={1} max={365} style={{ width: 70 }} value={days} disabled={!cleanup} onChange={(e) => setDays(Math.max(1, Math.min(365, Number(e.target.value) || 30)))} aria-label={t('deliver.days')} />
            {t('deliver.days')}
          </label>
          <span className="muted small">{t('deliver.cleanupHint')}</span>
          <div className="row">
            <button className="btn primary" disabled={busy || !approved.length} onClick={deliver} data-testid="deliver">
              {busy ? t('common.working') : d ? t('deliver.again') : t('deliver.export')}
            </button>
          </div>
          <div className="notice small">{t('deliver.aiReminder')}</div>
        </div>
        {d && (
          <div className="card col" data-testid="delivery">
            <b>{t('deliver.done', { date: d.date })}</b>
            <div className="small">
              {t('deliver.summary', { jobs: d.jobs, items: d.items })}
              {d.duration_s != null && ` · ${hms(d.duration_s)}`}
            </div>
            <div className="row small">
              <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {d.dir}
              </span>
              <button className="btn sm" onClick={() => window.desk.showItem(d.zip ?? d.dir)}>
                {t('deliver.show')}
              </button>
            </div>
            <div className="row small">
              <input type="checkbox" checked={d.cleanup.enabled} disabled={d.cleanup.done} onChange={(e) => saveCleanup(e.target.checked, d.cleanup.days ?? days)} aria-label={t('deliver.cleanup')} />
              {d.cleanup.done
                ? t('deliver.cleaned')
                : d.cleanup.enabled && d.cleanup.due
                  ? t('deliver.cleanupOn', { date: new Date(d.cleanup.due * 1000).toLocaleDateString() })
                  : t('deliver.cleanupOff')}
            </div>
            {d.manifest?.items && (
              <table className="t small">
                <tbody>
                  {d.manifest.items.map((f) => (
                    <tr key={f.path}>
                      <td className="mono">{f.path}</td>
                      <td className="muted">{bytes(f.bytes)}</td>
                      <td className="mono muted">{f.sha256.slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </>
  );
}
