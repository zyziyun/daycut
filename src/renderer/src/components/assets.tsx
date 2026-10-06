// First-run downloads (fonts, MediaPipe models, Whisper weights, optional Chromium) and the update indicator.
import { useEffect, useState } from 'react';
import type { AssetsStatusMsg } from '../../../shared/assets';
import type { UpdateStateMsg } from '../../../shared/deskApi';
import { t } from '../i18n';

type Status = AssetsStatusMsg & { bundled?: boolean };

export function useAssets() {
  const [s, setS] = useState<Status | null>(null);
  useEffect(() => {
    void window.desk.assets.status().then(setS);
    return window.desk.on('assets:progress', (d) => setS((old) => ({ ...(d as Status), bundled: old?.bundled })));
  }, []);
  return s;
}

const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);

function Bar({ received, total }: { received: number; total: number }) {
  const pct = total ? Math.min(100, (received / total) * 100) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} style={{ height: 6, background: 'var(--line, #333)', borderRadius: 3 }}>
      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent, #5ad)', borderRadius: 3, transition: 'width .2s' }} />
    </div>
  );
}

/** Shown above every screen while required assets are missing (bundled runtime only). */
export function AssetsBanner() {
  const s = useAssets();
  if (!s?.bundled) return null;
  const missing = s.groups.filter((g) => g.required && !g.installed);
  if (!missing.length && !s.restartNeeded) return null;
  const active = s.groups.find((g) => g.progress);
  const total = missing.reduce((a, g) => a + g.bytes, 0);
  return (
    <div className="notice accent col" data-testid="assets-banner" style={{ margin: 12, gap: 8 }}>
      {missing.length ? (
        <>
          <b>{t('assets.firstRun')}</b>
          <span className="small">{t('assets.firstRunBody', { size: mb(total) })}</span>
          {active?.progress ? (
            <>
              <Bar {...active.progress} />
              <span className="small mono">
                {active.progress.file} · {mb(active.progress.received)} / {mb(active.progress.total)}
              </span>
              <div className="row">
                <button className="btn" onClick={() => window.desk.assets.cancel()}>
                  {t('common.cancel')}
                </button>
              </div>
            </>
          ) : (
            <div className="row">
              <button className="btn primary" disabled={s.busy} onClick={() => window.desk.assets.install()}>
                {t('assets.download', { size: mb(total) })}
              </button>
              {missing.some((g) => g.error) && <span className="err small">{missing.map((g) => g.error).filter(Boolean).join(' · ')}</span>}
            </div>
          )}
        </>
      ) : (
        <div className="row">
          <span>{t('assets.restartNeeded')}</span>
          <button className="btn primary" onClick={() => window.desk.restartEngine()}>
            {t('settings.restart')}
          </button>
        </div>
      )}
    </div>
  );
}

/** Settings card: every asset group with size, licence and status. */
export function AssetsCard() {
  const s = useAssets();
  if (!s) return null;
  return (
    <div className="card col" data-testid="assets-card">
      <b>{t('assets.title')}</b>
      <div className="muted small mono">{s.dir}</div>
      {s.groups.map((g) => (
        <div key={g.id} className="col" style={{ gap: 4 }}>
          <div className="row">
            <span className="mono">{t(`assets.group.${g.id.replace(/-(darwin|win32).*$/, '')}`)}</span>
            <span className="muted small">
              {mb(g.bytes)} · {g.required ? t('assets.required') : t('assets.optional')}
            </span>
            <div className="sp" />
            {g.installed ? (
              <span className="badge accent">{t('assets.installed')}</span>
            ) : g.progress ? (
              <button className="btn" onClick={() => window.desk.assets.cancel()}>
                {t('common.cancel')}
              </button>
            ) : (
              <button className="btn" disabled={s.busy} onClick={() => window.desk.assets.install([g.id])}>
                {t('assets.downloadOne')}
              </button>
            )}
          </div>
          {g.progress && <Bar {...g.progress} />}
          {g.error && <span className="err small">{g.error}</span>}
          <span className="muted small">{g.licence}</span>
        </div>
      ))}
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
