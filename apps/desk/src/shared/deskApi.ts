// The API the preload exposes as window.desk.
import type { AiRoutes, AuthStatusMsg, KeyName } from './aiRoutes';
import type { AssetsStatusMsg } from './assets';
import type { ChannelMsg, ChannelPrefs } from './channels';
import type { Adapter } from './publish/adapterSchema';
import type { ApiStatusMsg } from './publish/apiPlatforms';
import type { Confirmation } from './publish/gating';
import type { EngineInfo } from './types';

export interface PublishStateMsg {
  adapterId: string | null;
  account: string | null;
  url: string;
  title: string;
  loading: boolean;
  canGoBack: boolean;
  canGoForward: boolean;
  visible: boolean;
}

export interface FillStepMsg {
  field: string;
  kind: string;
  status: 'ok' | 'not-found' | 'error';
  detail?: string;
}

export type FillResult =
  | { ok: true; results: FillStepMsg[]; job: string; platform: string }
  | { ok: false; reason: string; detail?: string };

export interface DueMsg {
  ids: string[];
  /** an official API is handling (or failed) this post */
  api: Record<string, { status: 'uploading' | 'done' | 'failed'; detail?: string; tries: number } | null>;
}

export type PostFillMsg =
  | { ok: true; postId: string; adapterId: string; account: string; results: FillStepMsg[]; video: string; cover: string | null }
  | { ok: false; reason: 'no-post' | 'posted' | 'no-adapter' | 'adapter-todo' | 'no-account' | 'no-file' | 'file-missing' | 'login-required' | 'page-failed' | 'debugger-busy'; detail?: string; adapterId?: string; account?: string };

export interface PostedEntryMsg {
  batchId: string;
  code: string;
  job: string;
  platform: string;
  adapterId: string;
  account: string;
  url: string | null;
  at: string;
}

export interface SettingsMsg {
  enginePath?: string;
  python?: string;
  lang: 'en' | 'zh-CN' | 'fr';
  theme: 'studio-dark' | 'notebook-light';
  accent?: 'teal' | 'red';
  accounts: Record<string, string[]>;
  resolved?: { enginePath?: string; python: string; dataDir: string; runtime?: string };
  /** a built app (engine path / Python are fixed, developer settings hidden) */
  packaged?: boolean;
  platform?: string;
  /** 'mas': the Mac App Store (Lite) build (src/shared/edition.ts) */
  edition?: 'full' | 'mas';
  firstRunDone?: boolean;
  defaultPlatforms?: string[];
  personaPath?: string;
  cleanupDays?: number;
  aiRoutes?: AiRoutes;
  channels?: Record<string, ChannelPrefs>;
  agencyMode?: boolean;
  /** Create page flag (DESK_CREATE=1/0 overrides it) */
  createPage?: boolean;
  createLocalGen?: boolean;
  /** anonymous usage counts: 'on' only after she chose it; unset (never asked) = off */
  usagePings?: 'on' | 'off';
  openAtLogin?: boolean;
  publishApi?: Partial<Record<'youtube' | 'tiktok' | 'x' | 'instagram', { auto: boolean }>>;
}

export interface UsageStatusMsg {
  on: boolean;
  /** this build may send (installed app; development builds and tests never send) */
  allowed: boolean;
  installId: string | null;
  queued: number;
  lastSentDay: string | null;
  docs: string;
}
export type UsageNumbersMsg = Partial<Record<'clips' | 'formats' | 'minutes_in' | 'count' | 'platform_count', number>>;

export type SecretName = KeyName;

export interface AiRoutesMsg {
  /** the creator's own choices (null: none yet, the persona's routes apply) */
  saved: AiRoutes | null;
  /** the persona / client routes the engine reports (the starting values) */
  initial: AiRoutes;
  /** what runs: saved ?? initial */
  routes: AiRoutes;
}

export interface AiTestMsg {
  ok: boolean;
  provider: string;
  model?: string | null;
  error?: string;
  seconds?: number;
}

export interface TermStartMsg {
  id: string;
  display: string;
  backend: 'pty' | 'python' | 'script' | 'pipe';
}

export interface SecretsStatusMsg {
  /** 'keychain': OS keychain-backed encryption (macOS Keychain / Windows DPAPI / libsecret) */
  backend: 'keychain' | 'basic' | 'unavailable';
  keys: Record<SecretName, boolean>;
}

export interface FillRequestMsg {
  batchId: string;
  code: string;
  job: string;
  platform: string;
  adapterId: string;
  account: string;
  /** adapter params (Reddit: subreddit) - fill only */
  params?: Record<string, string>;
}

export interface UpdateStateMsg {
  state: 'disabled' | 'idle' | 'checking' | 'available' | 'downloading' | 'ready' | 'none' | 'error';
  version?: string;
  percent?: number;
  error?: string;
}

export interface DeskApi {
  engineInfo(): Promise<EngineInfo>;
  restartEngine(): Promise<EngineInfo>;
  /** 'board': a board file OR a project folder (HyperFrames) - Create's Import board */
  openFile(kind: 'video' | 'segments' | 'persona' | 'python' | 'board'): Promise<string | null>;
  openFolder(): Promise<string | null>;
  openExternal(url: string): Promise<void>;
  /** feedback + problem reports (never sends by itself) */
  support: import('./supportIpc').SupportApi;
  showItem(path: string): Promise<void>;
  /** open <userData>/logs in Finder / Explorer */
  openLogs(): Promise<void>;
  copyText(text: string): Promise<void>;
  getSettings(): Promise<SettingsMsg>;
  setSettings(patch: Partial<Pick<SettingsMsg, 'enginePath' | 'python' | 'lang' | 'theme' | 'accent' | 'defaultPlatforms' | 'cleanupDays' | 'agencyMode' | 'createPage' | 'createLocalGen' | 'usagePings' | 'openAtLogin'>>): Promise<SettingsMsg>;
  openFiles(kind: 'video' | 'any'): Promise<string[]>;
  /** absolute path of a file dropped on the window (Electron webUtils; '' when unavailable) */
  pathForFile(file: File): string;
  /** system notification (only when the window is in the background); clicking it focuses the app at `route` */
  notify(title: string, body: string, route?: string): Promise<void>;
  saveText(defaultName: string, text: string): Promise<string | null>;
  firstRun: {
    complete(defaultPlatforms: string[], skipped?: boolean): Promise<SettingsMsg>;
  };
  /** opt-in anonymous usage counts (Settings › General › Privacy); every call is a no-op while sharing is off */
  usage: {
    status(): Promise<UsageStatusMsg>;
    track(ev: 'batch_done' | 'export_done' | 'publish_package', n?: UsageNumbersMsg): Promise<void>;
    resetId(): Promise<UsageStatusMsg>;
    deleteData(): Promise<{ ok: boolean; deleted?: number; error?: string; status: UsageStatusMsg }>;
  };
  secrets: {
    status(): Promise<SecretsStatusMsg>;
    set(name: SecretName, value: string): Promise<SecretsStatusMsg>;
    clear(name: SecretName): Promise<SecretsStatusMsg>;
  };
  persona: {
    import(path: string): Promise<SettingsMsg>;
    clear(): Promise<SettingsMsg>;
  };
  publish: {
    adapters(): Promise<{ adapters: Adapter[]; errors: { file: string; error: string }[] }>;
    accounts(): Promise<Record<string, string[]>>;
    channels(): Promise<ChannelMsg[]>;
    updateChannel(adapterId: string, account: string, patch: { name?: string; times?: string[] }): Promise<ChannelMsg[]>;
    removeAccount(adapterId: string, account: string, signOut: boolean): Promise<ChannelMsg[]>;
    addAccount(adapterId: string, account: string): Promise<Record<string, string[]>>;
    open(adapterId: string, account: string, page: 'upload' | 'login'): Promise<void>;
    setBounds(b: { x: number; y: number; width: number; height: number }): Promise<void>;
    hide(): Promise<void>;
    navigate(action: 'back' | 'forward' | 'reload' | 'upload' | 'login'): Promise<void>;
    confirmPackage(batchId: string, code: string): Promise<Confirmation>;
    confirmations(batchId: string): Promise<Confirmation[]>;
    fill(req: FillRequestMsg): Promise<FillResult>;
    markPosted(req: FillRequestMsg & { url?: string }): Promise<PostedEntryMsg>;
    caption(batchId: string, job: string, platform: string): Promise<{ title: string; description: string; tags: string[]; video: string }>;
    postedLog(batchId?: string): Promise<PostedEntryMsg[]>;
    /** posts whose time has come and that she still has to publish (ticks the scheduler first) */
    due(): Promise<DueMsg>;
    /** open the upload page of a scheduled post in its account's session and fill it (never presses Publish) */
    fillPost(postId: string, account?: string): Promise<PostFillMsg>;
    /** redacted snapshot of the page open in the built-in browser -> a local file (selector tuning) */
    capture(): Promise<{ file: string; nodes: number }>;
    api: {
      status(): Promise<ApiStatusMsg[]>;
      setClient(clientId: string, clientSecret: string): Promise<ApiStatusMsg[]>;
      connect(): Promise<ApiStatusMsg[]>;
      disconnect(forgetClient?: boolean): Promise<ApiStatusMsg[]>;
      setAuto(auto: boolean): Promise<ApiStatusMsg[]>;
    };
  };
  assets: {
    status(): Promise<AssetsStatusMsg & { bundled: boolean }>;
    /** queue groups for background download; returns at once */
    install(ids?: string[]): Promise<AssetsStatusMsg>;
    /** cancel the running download + the queue, or one queued / running group */
    cancel(id?: string): Promise<void>;
  };
  update: {
    check(): Promise<UpdateStateMsg>;
    install(): Promise<void>;
  };
  on(event: 'publish:state' | 'publish:fillStep' | 'engine:status' | 'assets:progress' | 'update:state' | 'history:changed' | 'notify:open' | 'term:data' | 'term:exit' | 'ai:routes' | 'publish:due' | 'publish:posted' | 'publish:channels' | 'support:problem' | 'support:open', cb: (data: unknown) => void): () => void;
  /** watch these folders for live job changes ('history:changed' events); -> the folders watched */
  watchHistory(roots: string[]): Promise<string[]>;
  /** Lite (Mac App Store) build: ask once to keep reading dropped files after a relaunch (no-op elsewhere) */
  grantAccess?(paths: string[]): Promise<{ needed: boolean; granted: boolean }>;
  /** source cleanup: a dialog lists the exact files; only on confirm are they moved to the Trash */
  ai: {
    status(opts?: { refresh?: boolean; probe?: boolean; providers?: string[] }): Promise<AuthStatusMsg>;
    test(provider: string): Promise<AiTestMsg>;
    /** run the CLI's login / logout command (from the engine) in the in-app terminal */
    terminal(req: { provider: 'claude-code' | 'codex'; action: 'login' | 'logout'; variant?: 'console' | 'sso' | 'device'; cols: number; rows: number }): Promise<TermStartMsg>;
    input(id: string, data: string): Promise<void>;
    resize(id: string, cols: number, rows: number): Promise<void>;
    kill(id: string): Promise<void>;
    routes(): Promise<AiRoutesMsg>;
    setRoutes(routes: AiRoutes | null): Promise<AiRoutesMsg>;
  };
  /** Create recorder (main refuses while the Create flag is off) */
  rec: {
    status(): Promise<{ camera: string; microphone: string; screen: string; platform: string; release: string }>;
    ask(kind: 'camera' | 'microphone'): Promise<boolean>;
    openPrivacy(pane: 'camera' | 'microphone' | 'screen'): Promise<void>;
    begin(req: { slug: string; title?: string; script: string[]; tracks: ('camera' | 'mic' | 'screen')[]; series?: string; episode?: string; shot?: string; mime?: Partial<Record<'camera' | 'mic' | 'screen', string>> }): Promise<{ sessionId: string; dir: string }>;
    chunk(req: { sessionId: string; track: 'camera' | 'mic' | 'screen'; seq: number; data: Uint8Array; startMs?: number }): Promise<{ ok: boolean; seq: number }>;
    mark(req: { sessionId: string; t: number; kind: 'line' | 'retake'; line: number }): Promise<{ ok: boolean; n: number }>;
    end(sessionId: string): Promise<{ dir: string; tracks: string[]; marks: number }>;
    recover(): Promise<{ id: string; dir: string }[]>;
  };
  confirmCleanup(batchId: string): Promise<{ confirmed: boolean; trashed: string[]; failed: string[]; outside: string[] }>;
  mediaUrl(path: string): string;
}
