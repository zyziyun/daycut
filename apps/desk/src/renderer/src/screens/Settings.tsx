import { useEffect, useState } from 'react';
import type { SettingsMsg } from '../../../shared/deskApi';
import { AssetsCard } from '../components/assets';
import { WatchFoldersField } from '../components/WatchFolders';
import { ErrorBox, Field } from '../components/ui';
import { LANGS, LOCALES, t } from '../i18n';
import { useEngine } from '../lib/engine';
import { PlatformPicker } from './Clients';
import { adapterName, LoginPill, useChannels } from '../v4/Channels';
import { PlatformIcon } from '../v4/PlatformIcon';

/** Settings -> 发布账号: her accounts with their login state; managed on 发布 -> 账号 (built-in browser there). */
function ChannelsCard() {
  const { adapters, channels } = useChannels();
  return (
    <div className="card col" data-testid="settings-channels">
      <b>{t('set.channels')}</b>
      <span className="muted small">{t('set.channelsHint')}</span>
      {!channels.length && <span className="muted small">{t('set.channelsNone')}</span>}
      {channels.map((c) => {
        const a = adapters.find((x) => x.id === c.adapterId);
        return (
          <div key={`${c.adapterId}/${c.account}`} className="row small" style={{ gap: 8 }} data-testid="settings-channel">
            {a && <PlatformIcon id={a.packagePlatforms[0]} size={14} />}
            <span style={{ minWidth: 120 }}>{a ? adapterName(a) : c.adapterId}</span>
            <span className="clamp1" style={{ flex: 1 }}>{c.name}</span>
            <LoginPill c={c} />
          </div>
        );
      })}
      <div className="row">
        <a className="btn" href="#/publish/accounts" data-testid="open-channels">
          {t('set.channelsManage')}
        </a>
      </div>
    </div>
  );
}

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
    <div className="scroll">
      <div className="pg col" style={{ maxWidth: 760, gap: 16 }}>
        <div className="ph" style={{ marginBottom: 8 }}>
          <h1>{t('nav.settings')}</h1>
        </div>
        {msg && <div className="notice accent">{msg}</div>}
        <div className="card col" data-testid="settings-appearance">
          <b>{t('set.appearance')}</b>
          <Field label={t('set.language')} hint={t('set.languageHint')}>
            <div className="tabs">
              {LANGS.map((l) => (
                <button key={l} className={`tab ${s.lang === l ? 'on' : ''}`} onClick={() => save({ lang: l })} data-testid={`lang-${l}`}>
                  {LOCALES[l].label}
                </button>
              ))}
            </div>
          </Field>
          <Field label={t('set.theme')}>
            <div className="tabs">
              {(['studio-dark', 'notebook-light'] as const).map((th) => (
                <button key={th} className={`tab ${s.theme === th ? 'on' : ''}`} onClick={() => save({ theme: th })}>
                  {t(`set.theme.${th}`)}
                </button>
              ))}
            </div>
          </Field>
          <Field label={t('set.accent')}>
            <div className="tabs">
              {(['teal', 'red'] as const).map((a) => (
                <button key={a} className={`tab ${(s.accent ?? 'teal') === a ? 'on' : ''}`} onClick={() => save({ accent: a })}>
                  <span className="dot" style={{ background: a === 'teal' ? '#4FBFAE' : '#F0435B', marginRight: 6 }} />
                  {t(`set.accent.${a}`)}
                </button>
              ))}
            </div>
          </Field>
        </div>
        <ChannelsCard />
        <AssetsCard />
        <div className="card col" data-testid="settings-ai">
          <b>{t('aiacc.title')}</b>
          <span className="muted small">{t('aiacc.openHint')}</span>
          <div className="row">
            <a className="btn primary" href="#/settings/ai" data-testid="open-ai-accounts">
              {t('aiacc.open')}
            </a>
          </div>
        </div>
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
              defaultValue={s.cleanupDays ?? 0}
              onBlur={(e) => {
                const n = Math.max(0, Math.min(365, Math.round(Number(e.target.value) || 0)));
                if (n !== s.cleanupDays) void save({ cleanupDays: n });
              }}
            />
          </Field>
          <div className="row">
            <button className="btn sm" onClick={() => (location.hash = '#/welcome')}>
              {t('settings.rerunWizard')}
            </button>
          </div>
        </div>
        <div className="card col" data-testid="settings-advanced">
          <b>{t('set.advanced')}</b>
          <label className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
            <input type="checkbox" checked={!!s.agencyMode} onChange={(e) => (setS({ ...s, agencyMode: e.target.checked }), void save({ agencyMode: e.target.checked }))} data-testid="agency-toggle" style={{ marginTop: 3 }} />
            <span className="col" style={{ gap: 2 }}>
              <span>{t('set.agency')}</span>
              <span className="muted small">{t('set.agencyHint')}</span>
            </span>
          </label>
          {s.agencyMode && (
            <div className="row">
              <a className="btn" href="#/clients" data-testid="open-clients">
                {t('set.clientsManage')}
              </a>
              <a className="btn ghost" href="#/metrics">
                {t('set.openMetrics')}
              </a>
            </div>
          )}
          <details className="devset" data-testid="settings-developer">
            <summary>{t('set.developer')}</summary>
            <span className="muted small">{t('set.developerHint')}</span>
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
            <div className="col" data-testid="settings-engine" style={{ gap: 10 }}>
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
              {!s.packaged && (
                <>
                  <Field label={t('settings.enginePath')} hint={t('settings.enginePathHint')}>
                    <div className="row">
                      <input className="input" style={{ flex: 1 }} value={enginePath} onChange={(e) => setEnginePath(e.target.value)} placeholder="/Users/…/reelfold" />
                      <button className="btn" onClick={async () => setEnginePath((await window.desk.openFolder()) ?? enginePath)}>
                        {t('common.choose')}
                      </button>
                    </div>
                  </Field>
                  <Field label={t('settings.python')} hint={t('settings.pythonHint')}>
                    <input className="input" value={python} onChange={(e) => setPython(e.target.value)} placeholder="/Users/…/miniconda3/bin/python3" />
                  </Field>
                </>
              )}
              <div className="row">
                {!s.packaged && (
                  <button className="btn" onClick={() => save({ enginePath: enginePath || undefined, python: python || undefined })}>
                    {t('settings.saveRestart')}
                  </button>
                )}
                <button className="btn" onClick={() => window.desk.restartEngine().catch((e: Error) => setMsg(e.message))}>
                  {t('settings.restart')}
                </button>
              </div>
            </div>
          </details>
        </div>
        <div className="card col small">
          <b>{t('settings.privacy')}</b>
          <div className="muted">{t('settings.privacyBody')}</div>
        </div>
        <div className={s.platform === 'win32' ? 'notice' : 'muted small'} data-testid="settings-platforms">
          {t('about.platforms')}
        </div>
      </div>
    </div>
  );
}
