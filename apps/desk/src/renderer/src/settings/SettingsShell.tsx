// Settings = direction A of ux/settings-redesign: the app sidebar becomes the settings sub-nav (Back to Reelfold,
// General / AI / Publishing / Advanced with status dots, the version at the bottom), each section a short page of
// macOS-style rows. Every control applies at once; nothing has a Save button.
import { useCallback, useEffect, useState } from 'react';
import { Clapperboard, ChevronLeft, Send, Settings2, Sparkles, Wrench } from 'lucide-react';
import { useCreateEnabled } from '../create';
import { VideoGenSection } from '../create/settings/VideoGenSection';
import type { SettingsMsg, UpdateStateMsg } from '../../../shared/deskApi';
import { t } from '../i18n';
import { useUi } from '../v4/ui';
import { AdvancedSection } from './Advanced';
import { AiSection } from './Ai';
import { GeneralSection } from './General';
import { Dot } from './kit';
import { PublishingSection } from './Publishing';
import { registerSettingsSection, useSettingsSections, type SettingsCtx, type SettingsSection } from './registry';
import { useAccountsDot, useAdvancedDot, useAiDot } from './status';
import './settings.css';
import { IS_LITE } from '../../../shared/edition';

registerSettingsSection({ id: 'general', order: 10, label: () => t('s2.nav.general'), icon: Settings2, render: (c) => <GeneralSection {...c} />, testId: 'snav-general' });
registerSettingsSection({ id: 'ai', order: 20, label: () => t('s2.nav.ai'), icon: Sparkles, render: (c) => <AiSection key={c.sub ?? ''} {...c} />, useDot: useAiDot, testId: 'snav-ai' });
// Create page (Labs): Settings › Video generation, only while the Create page is on
registerSettingsSection({ id: 'video', order: 25, label: () => t('create.set.title'), icon: Clapperboard, render: (c) => <VideoGenSection onSettings={c.onChange} />, useVisible: useCreateEnabled, testId: 'snav-video' });
registerSettingsSection({ id: 'accounts', order: 30, label: () => t('s2.nav.accounts'), icon: Send, render: (c) => <PublishingSection {...c} />, useDot: useAccountsDot, testId: 'snav-accounts' });
registerSettingsSection({ id: 'advanced', order: 90, label: () => t('s2.nav.advanced'), icon: Wrench, render: (c) => <AdvancedSection {...c} />, useDot: useAdvancedDot, testId: 'snav-advanced' });

const BACK = 'set.back';

/** Remember where she came from (Back to Reelfold returns there). Called by the router listener in App. */
export function rememberNonSettings(hash: string) {
  if (!hash.startsWith('#/settings') && !hash.startsWith('#/welcome')) {
    try {
      sessionStorage.setItem(BACK, hash || '#/');
    } catch {
      /* private mode */
    }
  }
}

function NavItem({ s, on }: { s: SettingsSection; on: boolean }) {
  const dot = s.useDot?.() ?? null;
  const visible = s.useVisible?.() ?? true;
  if (!visible) return null;
  const Icon = s.icon;
  return (
    <a href={`#/settings/${s.id}`} className={`nav ${on ? 'on' : ''}`} aria-current={on ? 'page' : undefined} data-testid={s.testId ?? `snav-${s.id}`} data-dot={dot ?? ''}>
      <Icon className="ico" />
      <span className="label">{s.label()}</span>
      <Dot tone={dot} />
    </a>
  );
}

function VersionLine() {
  const [u, setU] = useState<UpdateStateMsg | null>(null);
  useEffect(() => window.desk.on('update:state', (d) => setU(d as UpdateStateMsg)), []);
  const state = u?.state === 'none' ? t('s2.upToDate') : u?.state === 'ready' ? t('s2.updateReady') : u?.state === 'downloading' ? t('s2.updating', { percent: u.percent ?? 0 }) : null;
  return (
    <div className="s2-version" data-testid="settings-version">
      {t('s2.version', { version: __APP_VERSION__ })}
      {IS_LITE && ` · ${t('lite.name')} · ${t('lite.updates')}`}
      {state && ` · ${state}`}
      {u?.state === 'ready' && (
        <button className="s2-link" onClick={() => void window.desk.update.install()} data-testid="update-ready">
          {t('update.restart', { version: u.version ?? '' })}
        </button>
      )}
    </div>
  );
}

/** A section behind a flag that is off shows the first section instead. */
function Body({ s, fallback, ctx }: { s: SettingsSection; fallback: SettingsSection; ctx: SettingsCtx }) {
  const visible = s.useVisible?.() ?? true;
  const cur = visible ? s : fallback;
  return (
    <div className="scroll" data-testid={`settings-${cur.id}-page`}>
      {cur.render(ctx)}
    </div>
  );
}

export function SettingsShell({ section, sub, onChange }: { section: string; sub?: string; onChange: (s: SettingsMsg) => void }) {
  const ui = useUi();
  const sections = useSettingsSections();
  const [s, setS] = useState<SettingsMsg | null>(null);
  useEffect(() => {
    void window.desk.getSettings().then(setS);
  }, []);
  const save = useCallback<SettingsCtx['save']>(
    async (patch) => {
      try {
        const next = await window.desk.setSettings(patch);
        setS(next);
        onChange(next);
        return next;
      } catch (e) {
        ui.toast((e as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''), { error: true });
        return null;
      }
    },
    [onChange, ui],
  );
  const change = useCallback(
    (next: SettingsMsg) => {
      setS(next);
      onChange(next);
    },
    [onChange],
  );
  const cur = sections.find((x) => x.id === section) ?? sections[0];
  let back = '#/';
  try {
    back = sessionStorage.getItem(BACK) || '#/';
  } catch {
    /* private mode */
  }
  return (
    <div className="v4 app s2">
      <nav className="side s2-nav" aria-label={t('s2.title')} data-testid="settings-nav">
        <a className="s2-backlink" href={back} data-testid="settings-back">
          <ChevronLeft className="ico" />
          {t('s2.back')}
        </a>
        <h2 className="s2-navtitle">{t('s2.title')}</h2>
        {sections.map((x) => (
          <NavItem key={x.id} s={x} on={x.id === cur?.id} />
        ))}
        <div className="grow" />
        <VersionLine />
      </nav>
      <main className="main">
        {s && cur ? <Body s={cur} fallback={sections[0]} ctx={{ settings: s, save, onChange: change, sub }} /> : null}
      </main>
    </div>
  );
}
