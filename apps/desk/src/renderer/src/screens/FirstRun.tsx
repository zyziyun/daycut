// First-run wizard (P1-7): language -> API keys (OS keychain) -> model downloads (the packaging side's asset
// manager; nothing to download when running on a system Python / dev checkout) -> default platforms ->
// import persona. Every step can be skipped; Settings has the same controls later.
import { useState } from 'react';
import type { SettingsMsg } from '../../../shared/deskApi';
import { AssetsCard, useAssets } from '../components/assets';
import { KeysCard } from '../components/KeysCard';
import { ErrorBox } from '../components/ui';
import { LANGS, LOCALES, setLang, t } from '../i18n';
import { PlatformPicker } from './Clients';

const STEPS = ['welcome', 'keys', 'models', 'platforms', 'persona'] as const;
type Step = (typeof STEPS)[number];

const STEP_KEY = 'firstRunStep';

export function FirstRun({ settings, onDone }: { settings: SettingsMsg; onDone: (s: SettingsMsg) => void }) {
  // the step survives a page reload (e.g. an engine restart that had to change port): downloads never move the user
  const [step, setStepState] = useState<Step>(() => {
    const s = sessionStorage.getItem(STEP_KEY) as Step | null;
    return s && STEPS.includes(s) ? s : 'welcome';
  });
  const setStep = (s: Step) => {
    sessionStorage.setItem(STEP_KEY, s);
    setStepState(s);
  };
  const [lang, setL] = useState(settings.lang);
  const [platforms, setPlatforms] = useState<string[]>(settings.defaultPlatforms?.length ? settings.defaultPlatforms : ['xiaohongshu:full']);
  const [persona, setPersona] = useState(settings.personaPath ?? '');
  const [needsRestart, setNeedsRestart] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const assets = useAssets();
  const i = STEPS.indexOf(step);

  async function finish(skipped = false) {
    setErr(null);
    try {
      // the ONLY place first run is marked done: the explicit finish / skip buttons (never a finished download)
      const s = await window.desk.firstRun.complete(platforms.length ? platforms : ['xiaohongshu:full'], skipped);
      sessionStorage.removeItem(STEP_KEY);
      if (needsRestart) void window.desk.restartEngine().catch(() => undefined);
      location.hash = '#/batches';
      onDone(s);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function importPersona() {
    setErr(null);
    const p = await window.desk.openFile('persona');
    if (!p) return;
    try {
      const s = await window.desk.persona.import(p);
      setPersona(s.personaPath ?? '');
      setNeedsRestart(true);
    } catch (e) {
      setErr((e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''));
    }
  }

  const next = () => (i < STEPS.length - 1 ? setStep(STEPS[i + 1]) : void finish());
  return (
    <div className="firstrun" data-testid="first-run">
      <div className="frcard col">
        <div className="row">
          <b style={{ fontSize: 16 }}>{t('fr.title')}</b>
          <div style={{ flex: 1 }} />
          <button className="btn ghost sm" onClick={() => finish(true)} data-testid="fr-skip">
            {t('fr.skip')}
          </button>
        </div>
        <div className="steps">
          {STEPS.map((s, k) => (
            <span key={s} className={s === step ? 'on' : ''}>
              {k + 1}. {t(`fr.step.${s}`)}
            </span>
          ))}
        </div>
        {step === 'welcome' && (
          <div className="col">
            <p style={{ margin: 0 }}>{t('fr.welcome')}</p>
            <div className="tabs">
              {LANGS.map((l) => (
                <button
                  key={l}
                  className={`tab ${lang === l ? 'on' : ''}`}
                  onClick={() => {
                    setL(l);
                    setLang(l);
                    void window.desk.setSettings({ lang: l });
                  }}
                >
                  {LOCALES[l].label}
                </button>
              ))}
            </div>
            <div className="muted small">{t('settings.privacyBody')}</div>
          </div>
        )}
        {step === 'keys' && (
          <div className="col">
            <p className="small" style={{ margin: 0 }}>
              {t('fr.keysWhy')}
            </p>
            <KeysCard onChange={() => setNeedsRestart(true)} />
          </div>
        )}
        {step === 'models' && (
          <div className="col">
            {assets?.bundled ? (
              <>
                <p className="small" style={{ margin: 0 }}>
                  {t('fr.modelsWhy')}
                </p>
                <AssetsCard />
                {assets.busy && <div className="muted small">{t('fr.downloadsRunning')}</div>}
                <div className="row">
                  <button className="btn ghost sm" data-testid="fr-later" onClick={() => setStep(STEPS[i + 1])}>
                    {t('fr.later')}
                  </button>
                </div>
              </>
            ) : (
              <div className="notice accent">{assets ? t('fr.modelsSystem') : t('common.working')}</div>
            )}
          </div>
        )}
        {step === 'platforms' && (
          <div className="col">
            <p className="small" style={{ margin: 0 }}>
              {t('fr.platformsWhy')}
            </p>
            <PlatformPicker value={platforms} onChange={setPlatforms} />
          </div>
        )}
        {step === 'persona' && (
          <div className="col">
            <p className="small" style={{ margin: 0 }}>
              {t('fr.personaWhy')}
            </p>
            <div className="row">
              <button className="btn" onClick={importPersona} data-testid="fr-persona">
                {t('fr.personaPick')}
              </button>
              <span className="mono small muted">{persona || t('fr.personaNone')}</span>
            </div>
          </div>
        )}
        <ErrorBox error={err} />
        <div className="row">
          <button className="btn" disabled={i === 0} onClick={() => setStep(STEPS[Math.max(0, i - 1)])}>
            {t('common.back')}
          </button>
          <div style={{ flex: 1 }} />
          <button className="btn primary" disabled={step === 'platforms' && !platforms.length} onClick={next} data-testid="fr-next">
            {i === STEPS.length - 1 ? t('fr.start') : t('fr.next')}
          </button>
        </div>
      </div>
    </div>
  );
}
