// First-run wizard (feat/first-run, dogfood "first 10 minutes"): language -> AI (her Claude Code / Codex
// subscription first, API keys folded under it, or an explicit "continue without AI") -> where she posts. The one-time
// downloads start by themselves the moment the wizard opens (the smallest speech model first) and run in the
// background: every step shows how far they are and how long is left, and nothing waits for them except the first
// batch. One primary per step; everything can be changed later in Settings. No engine words, ports, tokens or paths.
import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { pill, PROVIDERS, type ProviderId } from '../../../shared/aiRoutes';
import type { SettingsMsg } from '../../../shared/deskApi';
import { DownloadStrip, useAssets, useAutoDownload } from '../components/assets';
import { BrandSymbol, BrandWordmark } from '../components/Brand';
import { KeysCard } from '../components/KeysCard';
import { ErrorBox } from '../components/ui';
import { getLang, LANGS, LOCALES, setLang, t, tk } from '../i18n';
import { refreshStatus, rowOf, useAi } from '../lib/ai';
import { defaultPlatformsFor } from '../lib/firstRun';
import { LoginTerminal, type LoginReq } from '../v4/LoginTerminal';
import { PlatformPicker } from './Clients';
import { UsageFirstRunCard } from '../components/UsageConsent';
import { LiteAiNote, LiteCard } from '../components/Lite';
import { CAPS } from '../../../shared/edition';

// The order of the wizard (the usage-counts consent card sits on the welcome step).
const ALL_STEPS = ['welcome', 'ai', 'platforms'] as const;
type Step = (typeof ALL_STEPS)[number];

const STEP_KEY = 'firstRunStep';
// the Lite (Mac App Store) build has no subscription sign-in: API keys / local models only
const SUBS: ProviderId[] = CAPS.cliLogins ? ['claude-code', 'codex'] : [];

export function FirstRun({ settings, onDone }: { settings: SettingsMsg; onDone: (s: SettingsMsg) => void }) {
  const assets = useAssets();
  useAutoDownload(assets);
  const steps: readonly Step[] = ALL_STEPS;
  // the step survives a page reload (e.g. an engine restart that had to change port): downloads never move the user
  const [step, setStepState] = useState<Step>(() => {
    const s = sessionStorage.getItem(STEP_KEY) as Step | null;
    return s && (ALL_STEPS as readonly string[]).includes(s) ? s : 'welcome';
  });
  const setStep = (s: Step) => {
    sessionStorage.setItem(STEP_KEY, s);
    setStepState(s);
  };
  const [lang, setL] = useState(settings.lang);
  const [platforms, setPlatforms] = useState<string[]>(() => defaultPlatformsFor(getLang(), settings.defaultPlatforms));
  const [touched, setTouched] = useState(false);
  const [needsRestart, setNeedsRestart] = useState(false);
  const [aiReady, setAiReady] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const i = Math.max(0, steps.indexOf(step));

  async function finish(skipped = false) {
    setErr(null);
    try {
      // the ONLY place first run is marked done: the explicit finish / skip buttons (never a finished download)
      const s = await window.desk.firstRun.complete(platforms.length ? platforms : defaultPlatformsFor(getLang()), skipped);
      sessionStorage.removeItem(STEP_KEY);
      if (needsRestart) void window.desk.restartEngine().catch(() => undefined);
      location.hash = '#/'; // Home: the composer and "Try with a sample"
      onDone(s);
    } catch (e) {
      setErr((e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''));
    }
  }

  const next = () => (i < steps.length - 1 ? setStep(steps[i + 1]) : void finish());
  const primary = i === steps.length - 1 ? t('fr.start') : step === 'ai' && !aiReady ? t('fr.noAiPrimary') : t('fr.next');
  return (
    <div className="firstrun" data-testid="first-run">
      <div className="frcard col">
        <div className="row">
          <span className="fr-brand" data-testid="fr-brand">
            <BrandSymbol size={34} />
            <BrandWordmark height={18} />
            {lang === 'zh-CN' ? <span className="zh">千剪</span> : null}
          </span>
          <div style={{ flex: 1 }} />
          <button className="btn ghost sm" onClick={() => finish(true)} data-testid="fr-skip">
            {t('fr.skip')}
          </button>
        </div>
        <div className="steps">
          {steps.map((s, k) => (
            <span key={s} className={s === step ? 'on' : ''}>
              {k + 1}. {t(`fr.step.${s}`)}
            </span>
          ))}
        </div>
        {step === 'welcome' && (
          <div className="col">
            <b style={{ fontSize: 18, fontWeight: 600 }}>{t('fr.title')}</b>
            <p style={{ margin: 0 }}>{t('fr.welcome')}</p>
            <div className="tabs" role="group" aria-label={t('set.language')}>
              {LANGS.map((l) => (
                <button
                  key={l}
                  className={`tab ${lang === l ? 'on' : ''}`}
                  aria-pressed={lang === l}
                  data-testid={`fr-lang-${l}`}
                  onClick={() => {
                    setL(l);
                    setLang(l);
                    if (!touched) setPlatforms(defaultPlatformsFor(l, settings.defaultPlatforms));
                    void window.desk.setSettings({ lang: l });
                  }}
                >
                  {LOCALES[l].label}
                </button>
              ))}
            </div>
            <div className="muted small">{t('settings.privacyBody')}</div>
            <LiteCard />
            <UsageFirstRunCard settings={settings} />
          </div>
        )}
        {step === 'ai' && (
          <AiStep
            onKeys={() => {
              setNeedsRestart(true);
              setAiReady(true);
            }}
            onReady={(r) => setAiReady((old) => old || r)}
          />
        )}
        {step === 'platforms' && (
          <div className="col">
            <p className="small" style={{ margin: 0 }}>
              {t('fr.platformsWhy')}
            </p>
            <PlatformPicker
              value={platforms}
              onChange={(v) => {
                setTouched(true);
                setPlatforms(v);
              }}
            />
            <p className="muted small" style={{ margin: 0 }}>
              {t('fr.laterInSettings')}
            </p>
          </div>
        )}
        <DownloadStrip status={assets} />
        <ErrorBox error={err} />
        <div className="row">
          <button className="btn" disabled={i === 0} onClick={() => setStep(steps[Math.max(0, i - 1)])}>
            {t('common.back')}
          </button>
          <div style={{ flex: 1 }} />
          <button className="btn primary" disabled={step === 'platforms' && !platforms.length} onClick={next} data-testid="fr-next">
            {primary}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Subscription logins first (one row each: name, state, Sign in), API keys folded below, and "continue without AI"
 * said out loud: what still works and what does not. */
function AiStep({ onKeys, onReady }: { onKeys: () => void; onReady: (ready: boolean) => void }) {
  const { status, checking } = useAi();
  const [login, setLogin] = useState<LoginReq | null>(null);
  useEffect(() => {
    void refreshStatus({ refresh: true, probe: false });
  }, []);
  const ready = SUBS.find((p) => rowOf(status, p)?.state === 'logged-in');
  useEffect(() => onReady(Boolean(ready)), [ready, onReady]);
  if (!CAPS.cliLogins) {
    // Lite: the keys card open, local models named, and the full version for a subscription sign-in
    return (
      <div className="col" data-testid="fr-ai">
        <b style={{ fontSize: 16, fontWeight: 600 }}>{t('lite.aiTitle')}</b>
        <p className="small" style={{ margin: 0 }}>
          {t('fr.aiWhy')}
        </p>
        <LiteAiNote />
        <KeysCard onChange={onKeys} />
        <div className="card col" style={{ gap: 4, padding: '12px 14px' }} data-testid="fr-no-ai">
          <b style={{ fontWeight: 500 }}>{t('fr.noAiTitle')}</b>
          <span className="muted small">{t('fr.noAiBody')}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="col" data-testid="fr-ai">
      <b style={{ fontSize: 16, fontWeight: 600 }}>{t('fr.aiTitle')}</b>
      <p className="small" style={{ margin: 0 }}>
        {t('fr.aiWhy')}
      </p>
      <div className="muted small" style={{ fontWeight: 500 }}>
        {t('fr.subsTitle')}
      </div>
      <div className="col" style={{ gap: 8 }}>
        {SUBS.map((p) => {
          const row = rowOf(status, p);
          const st = row?.state;
          const pl = pill(row ?? (status ? { provider: p, kind: 'subscription-cli', ready: false, state: 'not-installed' } : undefined));
          const tone = pl.tone === 'ok' ? 'done' : pl.tone === 'bad' ? 'error' : pl.tone === 'warn' ? 'you' : '';
          return (
            <div key={p} className="card row fr-sub" data-testid={`fr-sub-${p}`}>
              <div className="col" style={{ gap: 2, flex: 1, minWidth: 0 }}>
                <b style={{ fontWeight: 500 }}>{PROVIDERS[p].name}</b>
                <span className="muted small">{tk(`fr.sub.${p}`)}</span>
              </div>
              <span className={`st ${tone}`} data-testid="fr-sub-state" data-state={st ?? (checking ? 'checking' : 'unknown')}>
                {tk(pl.key)}
              </span>
              {st !== 'logged-in' && st !== 'not-installed' && row?.can_login !== false && row && (
                <button className="btn sm" onClick={() => setLogin({ provider: p as 'claude-code' | 'codex', action: 'login' })} data-testid={`fr-login-${p}`}>
                  {st === 'expired' ? t('aiacc.relogin') : t('aiacc.login')}
                </button>
              )}
              {st === 'not-installed' && row?.install && (
                <button className="btn ghost sm" onClick={() => void window.desk.openExternal(row.install!.url)}>
                  {t('fr.howToInstall')}
                </button>
              )}
            </div>
          );
        })}
      </div>
      <details className="fr-keys">
        <summary>
          <ChevronRight className="ico" />
          {t('fr.orKeys')}
        </summary>
        <KeysCard onChange={onKeys} />
      </details>
      {ready ? (
        <p className="small" style={{ margin: 0 }} data-testid="fr-ai-ready">
          {t('fr.aiReady', { name: PROVIDERS[ready].name })}
        </p>
      ) : (
        <div className="card col" style={{ gap: 4, padding: '12px 14px' }} data-testid="fr-no-ai">
          <b style={{ fontWeight: 500 }}>{t('fr.noAiTitle')}</b>
          <span className="muted small">{t('fr.noAiBody')}</span>
        </div>
      )}
      {login && (
        <LoginTerminal
          req={login}
          onClose={() => {
            setLogin(null);
            void refreshStatus({ refresh: true, probe: false });
          }}
        />
      )}
    </div>
  );
}
