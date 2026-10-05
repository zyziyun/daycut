import { useEffect, useState } from 'react';
import type { SettingsMsg } from '../../../shared/deskApi';
import { ErrorBox, Field } from '../components/ui';
import { t } from '../i18n';
import { useEngine } from '../lib/engine';

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
