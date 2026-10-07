// First-run downloads (fonts, MediaPipe models, Whisper weights, optional Chromium) and the update indicator.
import { useEffect, useState } from 'react';
import type { AssetsStatusMsg } from '../../../shared/assets';
import type { UpdateStateMsg } from '../../../shared/deskApi';
import { t, tk } from '../i18n';

type Status = AssetsStatusMsg & { bundled?: boolean };

export function useAssets() {
  const [s, setS] = useState<Status | null>(null);
  useEffect(() => {
    void window.desk.assets.status().then(setS);
    return window.desk.on('assets:progress', (d) => setS((old) => ({ ...(d as Status), bundled: old?.bundled })));
  }, []);
  return s;
}

const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n <= 0 ? '0 MB' : `${Math.max(1, Math.round(n / 1e6))} MB`);

function Bar({ received, total }: { received: number; total: number }) {
  const pct = total ? Math.min(100, (received / total) * 100) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} style={{ height: 6, background: 'var(--line, #333)', borderRadius: 3 }}>
      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent, #5ad)', borderRadius: 3, transition: 'width .2s' }} />
    </div>
  );
}

const groupName = (id: string) => tk(`assets.group.${id.replace(/-(darwin|win32).*$/, '')}`);

/** Shown above every screen (bundled runtime only): missing required assets, background progress, engine restart. */
export function AssetsBanner() {
  const s = useAssets();
  if (!s?.bundled) return null;
  const missing = s.groups.filter((g) => g.required && !g.installed);
  const active = s.groups.find((g) => g.progress);
  if (active?.progress) {
    return (
      <div className="notice accent col" data-testid="assets-banner" style={{ margin: 12, gap: 8 }}>
        <span className="small">
          {t('assets.bgBusy', { name: groupName(active.id), done: mb(active.progress.received), total: mb(active.progress.total) })}
        </span>
        <Bar {...active.progress} />
        <div className="row">
          <button className="btn" onClick={() => window.desk.assets.cancel()}>
            {t('assets.cancelAll')}
          </button>
        </div>
      </div>
    );
  }
  if (!missing.length && !s.restartNeeded) return null;
  const total = missing.reduce((a, g) => a + g.bytes, 0);
  return (
    <div className="notice accent col" data-testid="assets-banner" style={{ margin: 12, gap: 8 }}>
      {missing.length ? (
        <>
          <b>{t('assets.firstRun')}</b>
          <span className="small">{t('assets.firstRunBody', { size: mb(total) })}</span>
          <div className="row">
            <button className="btn primary" disabled={s.busy} onClick={() => window.desk.assets.install()}>
              {t('assets.download', { size: mb(total) })}
            </button>
            {missing.some((g) => g.error) && <span className="err small">{missing.map((g) => g.error).filter(Boolean).join(' · ')}</span>}
          </div>
        </>
      ) : (
        <div className="row">
          <span>{s.restartWhenIdle ? t('assets.restartWhenIdle') : t('assets.restartNeeded')}</span>
          <button className="btn primary" onClick={() => window.desk.restartEngine()}>
            {s.restartWhenIdle ? t('assets.restartNow') : t('settings.restart')}
          </button>
        </div>
      )}
    </div>
  );
}

/** Every asset group with size, licence, a checkbox and its own status / progress. Several groups can be queued;
 * downloads run in the main process in the background, so leaving this card (or the wizard step) never stops them.
 * Used by the first-run wizard and by Settings. */
export function AssetsCard({ primary = true, showDir = false }: { primary?: boolean; showDir?: boolean } = {}) {
  const s = useAssets();
  const [picked, setPicked] = useState<Set<string> | null>(null);
  if (!s) return null;
  const sel = picked ?? new Set(s.groups.filter((g) => g.required && !g.installed).map((g) => g.id));
  const can = s.groups.filter((g) => sel.has(g.id) && !g.installed && !g.queued && !g.progress);
  const toggle = (id: string) => {
    const n = new Set(sel);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setPicked(n);
  };
  return (
    <div className="card col" data-testid="assets-card">
      <b>{t('assets.title')}</b>
      <div className="muted small">{t('assets.pick')}</div>
      {showDir && <div className="muted small mono">{s.dir}</div>}
      {s.groups.map((g) => (
        <div key={g.id} className="col" style={{ gap: 4 }} data-testid={`asset-${g.id}`}>
          <div className="row">
            <input
              type="checkbox"
              aria-label={groupName(g.id)}
              data-testid={`asset-pick-${g.id}`}
              checked={g.installed || g.queued || Boolean(g.progress) || sel.has(g.id)}
              disabled={g.installed || g.queued || Boolean(g.progress)}
              onChange={() => toggle(g.id)}
            />
            <span>{groupName(g.id)}</span>
            <span className="muted small">
              {mb(g.bytes)} · {g.required ? t('assets.required') : t('assets.optional')}
            </span>
            <div className="sp" />
            {g.installed ? (
              <span className="badge accent" data-testid={`asset-state-${g.id}`}>
                {t('assets.installed')}
              </span>
            ) : g.progress ? (
              <>
                <span className="small" data-testid={`asset-state-${g.id}`}>
                  {t('assets.downloading')} {mb(g.progress.received)} / {mb(g.progress.total)}
                </span>
                <button className="btn sm" onClick={() => window.desk.assets.cancel(g.id)}>
                  {t('common.cancel')}
                </button>
              </>
            ) : g.queued ? (
              <>
                <span className="badge" data-testid={`asset-state-${g.id}`}>
                  {t('assets.queued')}
                </span>
                <button className="btn sm" onClick={() => window.desk.assets.cancel(g.id)}>
                  {t('assets.remove')}
                </button>
              </>
            ) : g.error ? (
              <button className="btn sm" onClick={() => window.desk.assets.install([g.id])}>
                {t('assets.retry')}
              </button>
            ) : null}
          </div>
          {g.progress && <Bar {...g.progress} />}
          {g.error && <span className="err small">{g.error}</span>}
          <span className="muted small">{g.licence}</span>
        </div>
      ))}
      <div className="row">
        <button
          className={primary && can.length ? 'btn primary' : 'btn'}
          data-testid="assets-download-selected"
          disabled={!can.length}
          hidden={!can.length && !primary}
          onClick={() => {
            void window.desk.assets.install(can.map((g) => g.id));
            setPicked(new Set());
          }}
        >
          {t('assets.downloadSelected', { n: can.length, size: mb(can.reduce((a, g) => a + g.bytes, 0)) })}
        </button>
        {s.busy && (
          <button className="btn" onClick={() => window.desk.assets.cancel()}>
            {t('assets.cancelAll')}
          </button>
        )}
      </div>
    </div>
  );
}

export function UpdateBadge() {
  const [u, setU] = useState<UpdateStateMsg | null>(null);
  useEffect(() => window.desk.on('update:state', (d) => setU(d as UpdateStateMsg)), []);
  if (!u || (u.state !== 'ready' && u.state !== 'downloading')) return null;
  return u.state === 'ready' ? (
    <button className="btn primary small" data-testid="update-ready" onClick={() => window.desk.update.install()}>
      {t('update.restart', { version: u.version ?? '' })}
    </button>
  ) : (
    <span className="muted small">{t('update.downloading', { percent: u.percent ?? 0 })}</span>
  );
}
