// The API the preload exposes as window.desk.
import type { AssetsStatusMsg } from './assets';
import type { Adapter } from './publish/adapterSchema';
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
  lang: 'zh' | 'en';
  theme: 'studio-dark' | 'notebook-light';
  accounts: Record<string, string[]>;
  resolved?: { enginePath?: string; python: string; dataDir: string; runtime?: string };
  firstRunDone?: boolean;
  defaultPlatforms?: string[];
  personaPath?: string;
  cleanupDays?: number;
}

export type SecretName = 'anthropic' | 'openai';

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
  openFile(kind: 'video' | 'segments' | 'persona'): Promise<string | null>;
  openFolder(): Promise<string | null>;
  openExternal(url: string): Promise<void>;
  showItem(path: string): Promise<void>;
  copyText(text: string): Promise<void>;
  getSettings(): Promise<SettingsMsg>;
  setSettings(patch: Partial<Pick<SettingsMsg, 'enginePath' | 'python' | 'lang' | 'theme' | 'defaultPlatforms' | 'cleanupDays'>>): Promise<SettingsMsg>;
  openFiles(kind: 'video'): Promise<string[]>;
  saveText(defaultName: string, text: string): Promise<string | null>;
  firstRun: {
    complete(defaultPlatforms: string[], skipped?: boolean): Promise<SettingsMsg>;
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
  on(event: 'publish:state' | 'publish:fillStep' | 'engine:status' | 'assets:progress' | 'update:state', cb: (data: unknown) => void): () => void;
  mediaUrl(path: string): string;
}
