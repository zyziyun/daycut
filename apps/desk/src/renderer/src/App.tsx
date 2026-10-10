import { useCallback, useEffect, useRef, useState } from 'react';
import { Calendar, Clapperboard, Home as HomeIcon, Inbox as InboxIcon, LayoutGrid, Settings as SettingsIcon } from 'lucide-react';
import type { SettingsMsg } from '../../shared/deskApi';
import { AssetsBanner } from './components/assets';
import { UpdatePill, UpdateProvider } from './components/update';
import { BrandSymbol, BrandWordmark } from './components/Brand';
import { getLang, normalizeLang, setLang, t, type MessageKey } from './i18n';
import { EngineProvider, useEngine } from './lib/engine';
import { HistoryProvider, useHistory } from './lib/history';
import { InboxProvider, useInbox } from './lib/inbox';
import { agencyMode, setPrefs } from './lib/prefs';
import { trackUsage } from './lib/usage';
import { href, useRoute, type Route } from './lib/router';
import { PostNow } from './publish/PostNow';
import { Board } from './screens/Board';
import { ClientDetail } from './screens/ClientDetail';
import { Clients } from './screens/Clients';
import { Deliver } from './screens/Deliver';
import { FirstRun } from './screens/FirstRun';
import { UsageAsk } from './components/UsageConsent';
import { JobDetail } from './screens/JobDetail';
import { Metrics } from './screens/Metrics';
import { NewBatch } from './screens/NewBatch';
import { Publish } from './screens/Publish';
import { Review } from './screens/Review';
import { rememberNonSettings, SettingsShell } from './settings/SettingsShell';
import { applyTheme, type AccentName, type ThemeName } from './theme/tokens';
import { CalendarScreen } from './v4/Calendar';
import { Channels } from './v4/Channels';
import { Focus } from './v4/Focus';
import { Home } from './v4/Home';
import { InboxScreen } from './v4/Inbox';
import { OutputEditor } from './v4/OutputEditor';
import { Project } from './v4/Project';
import { Projects } from './v4/Projects';
import { UiProvider } from './v4/ui';
import { SupportLayer } from './support/Support';
import { CreateNavIcon, CreateScreen, setCreatePrefs, useCreateEnabled } from './create';
import { setStudioPrefs, useStudioEnabled } from './lib/studioFlag';
import { StudioProvider } from './lib/studioData';
import { useStudioAttention } from './lib/attention';
import { Studio } from './v4/Studio';

function NavLink({ to, on, icon, label, count, testId }: { to: Route; on: boolean; icon: React.ReactNode; label: string; count?: React.ReactNode; testId: string }) {
  return (
    <a href={href(to)} className={`nav ${on ? 'on' : ''}`} data-testid={testId} aria-current={on ? 'page' : undefined} title={label}>
      {icon}
      <span className="label">{label}</span>
      {count}
    </a>
  );
}

/** System notifications when a run finishes or starts waiting for the creator (window in the background only). */
function useRunNotifications() {
  const { data } = useHistory();
  const studioOn = useStudioEnabled(); // the Studio tells her per video (useStudioAttention)
  const prev = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    if (!data) return;
    const next = new Map<string, string>();
    for (const i of data.items) {
      const s = i.live?.state ?? '';
      next.set(i.id, s);
      const was = prev.current.get(i.id);
      // opt-in usage counts: a run finished (numbers only; a no-op unless she turned sharing on)
      if (prev.current.size && was === 'running' && s === 'done') trackUsage('batch_done', i.counts?.done || i.counts?.total ? { clips: i.counts.done || i.counts.total } : undefined);
      if (prev.current.size && was === 'running' && (s === 'done' || s === 'waiting') && !studioOn) {
        const you = s === 'waiting';
        void window.desk
          .notify?.(t(you ? 'notify.you' : 'notify.done', { name: i.name }), t(you ? 'notify.youBody' : 'notify.doneBody'), href({ name: 'project', id: i.id }))
          ?.catch(() => undefined);
      }
    }
    prev.current = next;
  }, [data, studioOn]);
  useEffect(() => {
    try {
      return window.desk.on('notify:open', (d) => {
        const r = (d as { route?: string }).route;
        if (r && r.startsWith('#/')) location.hash = r;
      });
    } catch {
      return undefined;
    }
  }, []);
}

function Shell({ onSettings }: { onSettings: (s: SettingsMsg) => void }) {
  const r = useRoute();
  const { info, error } = useEngine();
  const { live } = useHistory();
  const inbox = useInbox();
  const createOn = useCreateEnabled();
  const studioOn = useStudioEnabled();
  useRunNotifications();
  useStudioAttention();
  const running = live.filter((i) => i.live?.state === 'running').length;
  const nIn = inbox.items.length;
  useEffect(() => rememberNonSettings(location.hash), [r]);
  const inProject = r.name === 'project' || r.name === 'clip' || r.name === 'board' || r.name === 'job' || r.name === 'deliver' || r.name === 'review';
  const nav = (to: Route, key: MessageKey, on: boolean, icon: React.ReactNode, testId: string, count?: React.ReactNode) => (
    <NavLink to={to} on={on} icon={icon} label={t(key)} count={count} testId={testId} />
  );
  if (r.name === 'focus') return <Focus key={r.id} id={r.id} />;
  // Settings has its own sub-nav in place of the app sidebar
  if (r.name === 'settings' || r.name === 'aiAccounts' || ((r.name === 'clients' || r.name === 'client') && !agencyMode()))
    return <SettingsShell section={r.name === 'aiAccounts' ? 'ai' : r.name === 'settings' ? r.section ?? 'general' : 'general'} sub={r.name === 'aiAccounts' ? r.focus : r.name === 'settings' ? r.sub : undefined} onChange={onSettings} />;
  return (
    <div className={`v4 app ${r.name === 'clip' || r.name === 'studio' ? 'rail' : ''}`}>
      <nav className="side" aria-label={t('nav.main')}>
        {/* solo creator first: the app itself, no workspace / account switcher */}
        <div className="brand" title={t('app.name')} data-testid="app-brand">
          <BrandSymbol size={30} />
          <BrandWordmark height={17} />
          {getLang() === 'zh-CN' ? <span className="zh" aria-hidden="true">千剪</span> : null}
          <span className="sr">{t('app.name')}</span>
        </div>
        {studioOn ? (
          // the Studio: one place for every video (Home, the Inbox and All projects are its composer and filters)
          nav({ name: 'studio' }, 'st.nav', r.name === 'studio' || inProject || r.name === 'new' || r.name === 'create', <Clapperboard className="ico" />, 'nav-studio', nIn > 0 ? <span className="count you" data-testid="inbox-badge">{nIn}</span> : running > 0 ? <span className="count run" data-testid="running-badge">{running}</span> : null)
        ) : (
          <>
            {nav({ name: 'home' }, 'nav.home', r.name === 'home' || r.name === 'new', <HomeIcon className="ico" />, 'nav-home', running > 0 ? <span className="count run" data-testid="running-badge">{running}</span> : null)}
            {createOn && nav({ name: 'create', path: [] }, 'nav.create', r.name === 'create', <CreateNavIcon className="ico" />, 'nav-create')}
            {nav({ name: 'inbox' }, 'nav.inbox', r.name === 'inbox', <InboxIcon className="ico" />, 'nav-inbox', nIn > 0 ? <span className="count you" data-testid="inbox-badge">{nIn}</span> : null)}
            {nav({ name: 'projects' }, 'nav.projects', r.name === 'projects' || inProject, <LayoutGrid className="ico" />, 'nav-projects')}
          </>
        )}
        {nav({ name: 'calendar' }, 'nav.publishTop', r.name === 'calendar' || r.name === 'publish' || r.name === 'metrics' || r.name === 'channels' || r.name === 'postNow', <Calendar className="ico" />, 'nav-publish')}
        <div className="grow" />
        <UpdatePill />
        {nav({ name: 'settings' }, 'nav.settings', r.name === 'clients' || r.name === 'client', <SettingsIcon className="ico" />, 'nav-settings')}
        <div className="eng" data-testid="engine-status" data-mode={error ? 'down' : (info?.mode ?? 'starting')}>
          {error ? (
            <>
              <i className="dot error" /> {t('engine.down')}
            </>
          ) : info ? (
            <>
              {/* no "demo mode" in the product: the fake engine exists for the test harness only (data-mode says which) */}
              <i className="dot done" /> {t('engine.ready')}
            </>
          ) : (
            <>
              <i className="dot" /> {t('engine.starting')}
            </>
          )}
        </div>
      </nav>
      <main className="main">
        <AssetsBanner />
        <UsageAsk />
        {error ? (
          <div className="pg">
            <div className="banner">
              <i className="dot error" />
              <div className="sp">
                <b>{t('engine.down')}</b>
                <span className="muted">{error}</span>
              </div>
              <a className="btn" href={href({ name: 'settings' })}>
                {t('engine.fix')}
              </a>
            </div>
          </div>
        ) : (
          <Screen r={r} onSettings={onSettings} />
        )}
      </main>
    </div>
  );
}

function Screen({ r, onSettings }: { r: Route; onSettings: (s: SettingsMsg) => void }) {
  switch (r.name) {
    case 'studio':
      return <Studio id={r.id} clip={r.clip} />;
    case 'home':
      return <Home />;
    case 'inbox':
      return <InboxScreen />;
    case 'projects':
      return <Projects />;
    case 'project':
      return <Project key={r.id} id={r.id} tab={r.tab ?? 'clips'} />;
    case 'clip':
      return <OutputEditor key={r.id + r.clip} id={r.id} clip={r.clip} />;
    case 'calendar':
      return <CalendarScreen />;
    case 'new':
      return <NewBatch />;
    case 'board':
      return <Board key={r.batch} batch={r.batch} />;
    case 'review':
      return <Review key={r.batch} batch={r.batch} />;
    case 'job':
      return <JobDetail key={r.batch + r.job} batch={r.batch} job={r.job} />;
    case 'publish':
      return <Publish key={r.batch} batch={r.batch} />;
    case 'deliver':
      return <Deliver key={r.batch} batch={r.batch} />;
    case 'clients':
      return <Clients />;
    case 'client':
      return <ClientDetail key={r.slug} slug={r.slug} />;
    case 'channels':
      return <Channels />;
    case 'postNow':
      return <PostNow key={r.id} id={r.id} />;
    case 'metrics':
      return <Metrics />;
    case 'welcome':
      return <WelcomeAgain onDone={onSettings} />;
    case 'create':
      return <CreateScreen path={r.path} onSettings={onSettings} />;
    default:
      return null;
  }
}

function WelcomeAgain({ onDone }: { onDone: (s: SettingsMsg) => void }) {
  const [s, setS] = useState<SettingsMsg | null>(null);
  useEffect(() => {
    void window.desk.getSettings().then(setS);
  }, []);
  return s ? <FirstRun settings={s} onDone={onDone} /> : null;
}

export function App() {
  const [ready, setReady] = useState(false);
  const [, force] = useState(0);
  const [settings, setSettings] = useState<SettingsMsg | null>(null);
  const apply = useCallback((s: SettingsMsg) => {
    setLang(s.lang);
    setPrefs(s);
    setCreatePrefs(s);
    setStudioPrefs(s);
    applyTheme(s.theme as ThemeName, document.documentElement, (s.accent ?? 'teal') as AccentName);
    setSettings(s);
    force((n) => n + 1);
  }, []);
  useEffect(() => {
    window.desk
      .getSettings()
      .then(apply)
      .finally(() => setReady(true));
  }, [apply]);
  const onTheme = useCallback((theme: ThemeName) => void window.desk.setSettings({ theme }).then(apply), [apply]);
  const onLang = useCallback((l: string) => void window.desk.setSettings({ lang: normalizeLang(l) }).then(apply), [apply]);
  if (!ready) return null;
  return (
    <EngineProvider>
      {settings && !settings.firstRunDone ? (
        <FirstRun settings={settings} onDone={apply} />
      ) : (
        <HistoryProvider>
          <InboxProvider>
            <StudioProvider>
              <UiProvider theme={settings?.theme ?? 'studio-dark'} onTheme={onTheme} onLang={onLang}>
                <UpdateProvider>
                  <Shell key={settings?.lang} onSettings={apply} />
                  <SupportLayer key={`sup-${settings?.lang}`} />
                </UpdateProvider>
              </UiProvider>
            </StudioProvider>
          </InboxProvider>
        </HistoryProvider>
      )}
    </EngineProvider>
  );
}
