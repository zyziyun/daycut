// The built-in publish browser: one WebContentsView per (platform, account), each with its own persistent
// session partition `persist:<platform>-<account>`. The creator signs in herself inside the page; the app never
// sees, stores or exports passwords or cookies. Platform pages get no preload, run sandboxed with context
// isolation, cannot reach the local engine, get no device permissions and cannot download.
import { shell, WebContentsView, type BrowserWindow, type Session, session as electronSession } from 'electron';
import { partitionFor } from '../../shared/ipc';
import { hostAllowed, type Adapter } from '../../shared/publish/adapterSchema';
import { isLocalEngineRequest, isSafeExternal, REMOTE_ALLOWED_PERMISSIONS } from '../security';

/** Sign-in providers platforms open in popups (kept in the same partition so the login sticks). */
const LOGIN_HOSTS = [
  'accounts.google.com',
  '*.google.com',
  'appleid.apple.com',
  '*.facebook.com',
  'x.com',
  'api.twitter.com',
  'open.weixin.qq.com',
  '*.qq.com',
];

export interface PublishState {
  adapterId: string | null;
  account: string | null;
  url: string;
  title: string;
  loading: boolean;
  canGoBack: boolean;
  canGoForward: boolean;
  visible: boolean;
}

const hardened = new WeakSet<Session>();

function hardenSession(ses: Session) {
  if (hardened.has(ses)) return;
  hardened.add(ses);
  ses.setPermissionRequestHandler((_wc, perm, cb) => cb(REMOTE_ALLOWED_PERMISSIONS.has(perm)));
  ses.setPermissionCheckHandler((_wc, perm) => REMOTE_ALLOWED_PERMISSIONS.has(perm));
  ses.setDevicePermissionHandler(() => false);
  ses.on('will-download', (e) => e.preventDefault());
  ses.webRequest.onBeforeRequest((details, cb) => cb({ cancel: isLocalEngineRequest(details.url) }));
}

interface Entry {
  key: string;
  adapter: Adapter;
  account: string;
  view: WebContentsView;
}

export class PublishBrowser {
  private entries = new Map<string, Entry>();
  private current: Entry | null = null;
  private bounds = { x: 0, y: 0, width: 0, height: 0 };
  private visible = false;

  constructor(
    private win: BrowserWindow,
    private onState: (s: PublishState) => void,
  ) {}

  private create(adapter: Adapter, account: string): Entry {
    const partition = partitionFor(adapter.id, account);
    const ses = electronSession.fromPartition(partition);
    hardenSession(ses);
    const view = new WebContentsView({
      webPreferences: {
        partition,
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        nodeIntegrationInSubFrames: false,
        webviewTag: false,
        safeDialogs: true,
        spellcheck: false,
        // deliberately no preload: platform pages get no privileged API
      },
    });
    const wc = view.webContents;
    const allowedPopup = (url: string) => {
      try {
        const u = new URL(url);
        return u.protocol === 'https:' && (hostAllowed(u.hostname, adapter.allowedHosts) || hostAllowed(u.hostname, LOGIN_HOSTS));
      } catch {
        return false;
      }
    };
    wc.setWindowOpenHandler(({ url }) => {
      if (allowedPopup(url)) {
        return {
          action: 'allow',
          overrideBrowserWindowOptions: {
            width: 520,
            height: 720,
            parent: this.win,
            webPreferences: { partition, sandbox: true, contextIsolation: true, nodeIntegration: false },
          },
        };
      }
      if (isSafeExternal(url)) void shell.openExternal(url);
      return { action: 'deny' };
    });
    wc.on('will-navigate', (e, url) => {
      if (!url.startsWith('https:')) e.preventDefault();
    });
    wc.on('will-attach-webview', (e) => e.preventDefault());
    const emit = () => this.emit();
    for (const ev of ['did-navigate', 'did-navigate-in-page', 'page-title-updated', 'did-start-loading', 'did-stop-loading'] as const) {
      wc.on(ev as 'did-navigate', emit);
    }
    const entry = { key: partition, adapter, account, view };
    this.entries.set(partition, entry);
    return entry;
  }

  open(adapter: Adapter, account: string, page: 'upload' | 'login'): Entry {
    const key = partitionFor(adapter.id, account);
    let e = this.entries.get(key);
    const fresh = !e;
    if (!e) e = this.create(adapter, account);
    e.adapter = adapter;
    if (this.current && this.current !== e) this.win.contentView.removeChildView(this.current.view);
    this.current = e;
    this.win.contentView.addChildView(e.view);
    e.view.setBounds(this.bounds);
    e.view.setVisible(this.visible);
    // an existing view keeps its page (a half-filled upload form must survive switching tabs)
    if (fresh) void e.view.webContents.loadURL(page === 'login' ? adapter.loginUrl : adapter.uploadUrl);
    this.emit();
    return e;
  }

  get active(): Entry | null {
    return this.current;
  }

  setBounds(b: { x: number; y: number; width: number; height: number }) {
    this.bounds = b;
    this.visible = b.width > 0 && b.height > 0;
    if (this.current) {
      this.current.view.setBounds(b);
      this.current.view.setVisible(this.visible);
    }
  }

  hide() {
    this.visible = false;
    this.current?.view.setVisible(false);
    this.emit();
  }

  navigate(action: 'back' | 'forward' | 'reload' | 'upload' | 'login') {
    const e = this.current;
    if (!e) return;
    const wc = e.view.webContents;
    if (action === 'back' && wc.navigationHistory.canGoBack()) wc.navigationHistory.goBack();
    else if (action === 'forward' && wc.navigationHistory.canGoForward()) wc.navigationHistory.goForward();
    else if (action === 'reload') wc.reload();
    else if (action === 'upload') void wc.loadURL(e.adapter.uploadUrl);
    else if (action === 'login') void wc.loadURL(e.adapter.loginUrl);
  }

  private emit() {
    const e = this.current;
    const wc = e?.view.webContents;
    this.onState({
      adapterId: e?.adapter.id ?? null,
      account: e?.account ?? null,
      url: wc?.getURL() ?? '',
      title: wc?.getTitle() ?? '',
      loading: wc?.isLoading() ?? false,
      canGoBack: wc?.navigationHistory.canGoBack() ?? false,
      canGoForward: wc?.navigationHistory.canGoForward() ?? false,
      visible: this.visible,
    });
  }

  destroy() {
    for (const e of this.entries.values()) {
      try {
        this.win.contentView.removeChildView(e.view);
      } catch {
        /* window gone */
      }
      e.view.webContents.close();
    }
    this.entries.clear();
    this.current = null;
  }
}
