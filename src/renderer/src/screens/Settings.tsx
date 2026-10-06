import { useEffect, useState } from 'react';
import type { SettingsMsg } from '../../../shared/deskApi';
import { AssetsCard } from '../components/assets';
import { WatchFoldersField } from '../components/HistoryList';
import { KeysCard } from '../components/KeysCard';
import { ErrorBox, Field } from '../components/ui';
import { t } from '../i18n';
import { useEngine } from '../lib/engine';
import { PlatformPicker } from './Clients';

export function Settings({ onChange }: { onChange: (s: SettingsMsg) => void }) {
  const { info, error: engineError } = useEngine();
  const [s, setS] = useState<SettingsMsg | null>(null);
  const [enginePath, setEnginePath] = useState('');
  const [python, setPython] = useState('');
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    void window.desk.getSettings().then((x) => {
      setS(x);
      setEnginePath(x.enginePath ?? '');
      setPython(x.python ?? '');
    });
  }, []);

  async function save(patch: Parameters<typeof window.desk.setSettings>[0]) {
    setMsg(null);
    try {
      const next = await window.desk.setSettings(patch);
      setS(next);
      onChange(next);
      setMsg(t('settings.saved'));
    } catch (e) {
      setMsg((e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''));
    }
  }

  if (!s) return null;
  return (
    <>
      <div className="topbar">
        <h1>{t('nav.settings')}</h1>
        <div className="sp" />
      </div>
      <div className="page col" style={{ maxWidth: 760, gap: 16 }}>
        {msg && <div className="notice accent">{msg}</div>}
        <div className="card col">
          <b>{t('settings.engine')}</b>
          <div className="small">
            {t('settings.mode')}: <b>{info?.mode === 'real' ? t('settings.modeReal') : info?.mode === 'mock' ? t('settings.modeMock') : '-'}</b>
            {info?.note && <div className="warnc">{info.note}</div>}
          </div>
          <ErrorBox error={engineError} />
          <div className="muted small mono">
            {t('settings.resolved')}: {s.resolved?.enginePath ?? t('settings.notFound')} · {s.resolved?.python} · {s.resolved?.dataDir}
          </div>
          {s.resolved?.runtime && (
            <div className="muted small mono" data-testid="runtime-info">
              {t('settings.runtime')}: {s.resolved.runtime}
            </div>
          )}
          <Field label={t('settings.enginePath')} hint={t('settings.enginePathHint')}>
            <div className="row">
              <input className="input" style={{ flex: 1 }} value={enginePath} onChange={(e) => setEnginePath(e.target.value)} placeholder="/Users/…/video-studio" />
              <button className="btn" onClick={async () => setEnginePath((await window.desk.openFolder()) ?? enginePath)}>
                {t('common.choose')}
              </button>
            </div>
          </Field>
          <Field label={t('settings.python')} hint={t('settings.pythonHint')}>
            <input className="input" value={python} onChange={(e) => setPython(e.target.value)} placeholder="/Users/…/miniconda3/bin/python3" />
          </Field>
          <div className="row">
            <button className="btn primary" onClick={() => save({ enginePath: enginePath || undefined, python: python || undefined })}>
              {t('settings.saveRestart')}
            </button>
            <button className="btn" onClick={() => window.desk.restartEngine().catch((e: Error) => setMsg(e.message))}>
              {t('settings.restart')}
            </button>
          </div>
        </div>
        <AssetsCard />
        <KeysCard />
        <div className="card col" data-testid="defaults-card">
          <b>{t('settings.defaults')}</b>
          <Field label={t('settings.defaultPlatforms')}>
            <PlatformPicker value={s.defaultPlatforms ?? []} onChange={(v) => v.length && save({ defaultPlatforms: v })} />
          </Field>
          <Field label={t('settings.cleanupDays')} hint={t('settings.cleanupDaysHint')}>
            <input
              className="input"
              type="number"
              min={0}
              max={365}
              style={{ width: 100 }}
              defaultValue={s.cleanupDays ?? 30}
              onBlur={(e) => {
                const n = Math.max(0, Math.min(365, Math.round(Number(e.target.value) || 0)));
                if (n !== s.cleanupDays) void save({ cleanupDays: n });
              }}
            />
          </Field>
          <Field label={t('history.watching')} hint={t('history.watchHint')}>
            <WatchFoldersField />
          </Field>
          <Field label={t('settings.persona')} hint={t('settings.personaHint')}>
            <div className="row">
              <span className="mono small muted" style={{ flex: 1 }}>
                {s.personaPath ?? t('fr.personaNone')}
              </span>
              <button
                className="btn sm"
                onClick={async () => {
                  const p = await window.desk.openFile('persona');
                  if (p) {
                    try {
                      setS(await window.desk.persona.import(p));
                      setMsg(t('settings.personaImported'));
                    } catch (e) {
                      setMsg((e as Error).message);
                    }
                  }
                }}
              >
                {t('fr.personaPick')}
              </button>
              {s.personaPath && (
                <button className="btn ghost sm" onClick={async () => setS(await window.desk.persona.clear())}>
                  {t('keys.remove')}
                </button>
              )}
            </div>
          </Field>
          <div className="row">
            <button className="btn sm" onClick={() => (location.hash = '#/welcome')}>
              {t('settings.rerunWizard')}
            </button>
          </div>
        </div>
        <div className="card col">
          <b>{t('settings.ui')}</b>
          <Field label={t('settings.lang')}>
            <div className="tabs">
              {(['zh', 'en'] as const).map((l) => (
                <button key={l} className={`tab ${s.lang === l ? 'on' : ''}`} onClick={() => save({ lang: l })}>
                  {l === 'zh' ? '中文' : 'English'}
                </button>
              ))}
            </div>
          </Field>
          <Field label={t('settings.theme')} hint={t('settings.themeHint')}>
            <div className="tabs">
              {(['studio-dark', 'notebook-light'] as const).map((th) => (
                <button key={th} className={`tab ${s.theme === th ? 'on' : ''}`} onClick={() => save({ theme: th })}>
                  {t(`theme.${th}`)}
                </button>
              ))}
            </div>
          </Field>
        </div>
        <div className="card col small">
          <b>{t('settings.privacy')}</b>
          <div className="muted">{t('settings.privacyBody')}</div>
        </div>
      </div>
    </>
  );
}
