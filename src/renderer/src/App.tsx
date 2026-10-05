import { useEffect, useState } from 'react';
import type { SettingsMsg } from '../../shared/deskApi';
import { setLang, t } from './i18n';
import { EngineProvider, useEngine } from './lib/engine';
import { href, useRoute, type Route } from './lib/router';
import { Batches } from './screens/Batches';
import { Board } from './screens/Board';
import { JobDetail } from './screens/JobDetail';
import { NewBatch } from './screens/NewBatch';
import { Publish } from './screens/Publish';
import { Review } from './screens/Review';
import { Settings } from './screens/Settings';
import { applyTheme } from './theme/tokens';

function lastBatch(r: Route): string | null {
  return 'batch' in r ? r.batch : sessionStorage.getItem('lastBatch');
}

function Shell({ onSettings }: { onSettings: (s: SettingsMsg) => void }) {
  const r = useRoute();
  const { info, error, connected } = useEngine();
  const b = lastBatch(r);
  useEffect(() => {
    if ('batch' in r) sessionStorage.setItem('lastBatch', r.batch);
  }, [r]);
  const nav = (to: Route, label: string, on: boolean, disabled = false) => (
    <a href={href(to)} className={`${on ? 'on' : ''} ${disabled ? 'disabled' : ''}`}>
      {label}
    </a>
  );
  return (
    <div className="app">
      <nav className="side">
        <div className="brand">
          video-studio desk
          <small>{t('app.tagline')}</small>
        </div>
        {nav({ name: 'batches' }, t('nav.batches'), r.name === 'batches' || r.name === 'new')}
        {nav({ name: 'board', batch: b ?? '' }, t('nav.board'), r.name === 'board' || r.name === 'job', !b)}
        {nav({ name: 'review', batch: b ?? '' }, t('nav.review'), r.name === 'review', !b)}
        {nav({ name: 'publish', batch: b ?? '' }, t('nav.publish'), r.name === 'publish', !b)}
        <div className="grow" />
        {nav({ name: 'settings' }, t('nav.settings'), r.name === 'settings')}
        <div className="engine" data-testid="engine-status">
          {error ? (
            <span className="err">{t('engine.down')}</span>
          ) : info ? (
            <>
              <span className={`light ${connected ? 'green' : ''}`} /> {t('engine.label')} · {info.mode === 'real' ? t('settings.modeReal') : t('settings.modeMock')}
            </>
          ) : (
            t('engine.starting')
          )}
        </div>
      </nav>
      <main className="main">
        {error && r.name !== 'settings' ? (
          <div className="page">
            <div className="notice">
              <b>{t('engine.down')}</b>
              <div className="err small">{error}</div>
              <a href={href({ name: 'settings' })}>{t('engine.fix')}</a>
            </div>
          </div>
        ) : r.name === 'batches' ? (
          <Batches />
        ) : r.name === 'new' ? (
          <NewBatch />
        ) : r.name === 'board' ? (
          <Board key={r.batch} batch={r.batch} />
        ) : r.name === 'review' ? (
          <Review key={r.batch} batch={r.batch} />
        ) : r.name === 'job' ? (
          <JobDetail key={r.batch + r.job} batch={r.batch} job={r.job} />
        ) : r.name === 'publish' ? (
          <Publish key={r.batch} batch={r.batch} />
        ) : (
          <Settings onChange={onSettings} />
        )}
      </main>
    </div>
  );
}

export function App() {
  const [ready, setReady] = useState(false);
  const [, force] = useState(0);
  const apply = (s: SettingsMsg) => {
    setLang(s.lang);
    applyTheme(s.theme);
    force((n) => n + 1);
  };
  useEffect(() => {
    window.desk
      .getSettings()
      .then(apply)
      .finally(() => setReady(true));
  }, []);
  if (!ready) return null;
  return (
    <EngineProvider>
      <Shell onSettings={apply} />
    </EngineProvider>
  );
}
