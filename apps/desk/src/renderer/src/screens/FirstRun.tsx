// First-run wizard: language -> AI (the Claude Code / Codex subscription she already pays for first, API keys
// folded under it) -> one-time downloads (bundled runtime only) -> default platforms. One primary per step (Next /
// Start); everything can be skipped and changed later in Settings. No engine words, ports, tokens or paths.
import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { pill, PROVIDERS, type ProviderId } from '../../../shared/aiRoutes';
import type { SettingsMsg } from '../../../shared/deskApi';
import { AssetsCard, useAssets } from '../components/assets';
import { BrandSymbol, BrandWordmark } from '../components/Brand';
import { KeysCard } from '../components/KeysCard';
import { ErrorBox } from '../components/ui';
import { LANGS, LOCALES, setLang, t, tk } from '../i18n';
import { refreshStatus, rowOf, useAi } from '../lib/ai';
import { LoginTerminal, type LoginReq } from '../v4/LoginTerminal';
import { PlatformPicker } from './Clients';

const ALL_STEPS = ['welcome', 'ai', 'models', 'platforms'] as const;
type Step = (typeof ALL_STEPS)[number];

const STEP_KEY = 'firstRunStep';
const SUBS: ProviderId[] = ['claude-code', 'codex'];

export function FirstRun({ settings, onDone }: { settings: SettingsMsg; onDone: (s: SettingsMsg) => void }) {
  const assets = useAssets();
  // the downloads step only exists for the bundled runtime (a dev checkout has its models already)
  const steps: readonly Step[] = assets && !assets.bundled ? ALL_STEPS.filter((s) => s !== 'models') : ALL_STEPS;
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
  const [platforms, setPlatforms] = useState<string[]>(settings.defaultPlatforms?.length ? settings.defaultPlatforms : ['xiaohongshu:full']);
  const [needsRestart, setNeedsRestart] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const i = Math.max(0, steps.indexOf(step));

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
      setErr((e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''));
    }
  }

  const next = () => (i < steps.length - 1 ? setStep(steps[i + 1]) : void finish());
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
        {step === 'ai' && <AiStep onKeys={() => setNeedsRestart(true)} />}
        {step === 'models' && (
          <div className="col">
            <p className="small" style={{ margin: 0 }}>
              {t('fr.modelsWhy')}
            </p>
            {assets?.bundled ? <AssetsCard primary={false} /> : <div className="muted small">{t('common.working')}</div>}
            {assets?.busy && <div className="muted small">{t('fr.downloadsRunning')}</div>}
          </div>
        )}
        {step === 'platforms' && (
          <div className="col">
            <p className="small" style={{ margin: 0 }}>
              {t('fr.platformsWhy')}
            </p>
            <PlatformPicker value={platforms} onChange={setPlatforms} />
            <p className="muted small" style={{ margin: 0 }}>
              {t('fr.laterInSettings')}
            </p>
          </div>
        )}
        <ErrorBox error={err} />
        <div className="row">
          <button className="btn" disabled={i === 0} onClick={() => setStep(steps[Math.max(0, i - 1)])}>
            {t('common.back')}
          </button>
          <div style={{ flex: 1 }} />
          <button className="btn primary" disabled={step === 'platforms' && !platforms.length} onClick={next} data-testid="fr-next">
            {i === steps.length - 1 ? t('fr.start') : t('fr.next')}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Subscription logins first (one row each: name, state, Sign in), API keys folded below. */
function AiStep({ onKeys }: { onKeys: () => void }) {
  const { status, checking } = useAi();
  const [login, setLogin] = useState<LoginReq | null>(null);
  useEffect(() => {
    void refreshStatus({ refresh: true, probe: false });
  }, []);
  return (
    <div className="col" data-testid="fr-ai">
      <p className="small" style={{ margin: 0 }}>
        {t('fr.aiWhy')}
      </p>
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
      <p className="muted small" style={{ margin: 0 }}>
        {t('fr.aiNone')}
      </p>
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
