// Publishing accounts ("channels"): her 小红书号, 抖音号, YouTube channel ... Each one is an adapter + a short label
// (the label names the built-in browser's session partition persist:<adapter>-<label>) plus what the app
// remembers about it: a display name, default post times, and the login state the built-in browser last SAW
// (signed in = the upload page opened; signed out = the platform sent it to a login page). Never a password,
// never a cookie.
import { hostAllowed, type Adapter } from './publish/adapterSchema';

export type LoginState = 'unknown' | 'in' | 'out';

export interface ChannelPrefs {
  /** what she calls it ("@ziyun 小红书") - free text, shown instead of the label */
  name?: string;
  /** default post times for new calendar slots of this account, "HH:MM" */
  times?: string[];
  login?: { state: LoginState; at: string };
}

export interface ChannelMsg {
  adapterId: string;
  account: string;
  name: string;
  times: string[];
  login: { state: LoginState; at: string | null };
}

export const channelKey = (adapterId: string, account: string) => `${adapterId}/${account}`;

const LOGIN_PATH = /(^|\/)(login|login\.html|signin|sign-in|passport|logon|onboarding)(\/|$)/i;
const LOGIN_QUERY = /(^|[?&])(mode=login|redirectReason=401)/i;
const LOGIN_HOSTS = ['passport.bilibili.com', 'accounts.google.com', 'passport.weibo.com', 'open.weixin.qq.com', 'login.live.com', 'appleid.apple.com'];

/** What the page itself shows (read in an isolated world, never typed into): a file input = an upload form; a
 * password field or a QR / SMS login box = a login form. */
export interface PageSignals {
  fileInput: boolean;
  loginForm: boolean;
}

/** The login state an account's page says: on a login URL (path / query / sign-in host) or showing a login form =
 * signed out; on the platform's upload page showing a file input and no login form = signed in; anything else =
 * no new information (null). Some platforms (抖音, Instagram) show their login box ON the upload URL, so the URL
 * alone never counts as signed in. */
export function loginState(url: string, a: Pick<Adapter, 'uploadUrl' | 'loginUrl' | 'allowedHosts'>, page: PageSignals | null): Exclude<LoginState, 'unknown'> | null {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.protocol !== 'https:') return null;
  if (hostAllowed(u.hostname, LOGIN_HOSTS) || LOGIN_PATH.test(u.pathname) || LOGIN_QUERY.test(u.search)) return 'out';
  const login = new URL(a.loginUrl);
  const up = new URL(a.uploadUrl);
  if (u.hostname === login.hostname && login.pathname !== up.pathname && u.pathname.replace(/\/$/, '') === login.pathname.replace(/\/$/, '')) return 'out';
  if (!hostAllowed(u.hostname, a.allowedHosts) || !page) return null;
  if (page.loginForm && !page.fileInput) return 'out';
  if (page.fileInput && !page.loginForm) return 'in';
  return null;
}

/** A cookie as Electron's session.cookies.get returns it (only name / domain / expiry are looked at; the value
 * only for being non-empty - it is never stored, logged or sent anywhere). */
export interface CookieLike {
  name: string;
  value: string;
  domain?: string;
  expirationDate?: number;
}

/** Signed in or out from the account's own session cookies: one of the adapter's session cookies set (not empty,
 * not expired, on one of its domains) = signed in; none = signed out. null when the adapter names no session
 * cookie (then only what the pages show counts). Works on any page of the platform (小红书's creator home, not
 * just the upload page), and without opening a page at all. */
export function sessionLoginState(cookies: CookieLike[], a: Pick<Adapter, 'session'>, nowSec = Date.now() / 1000): Exclude<LoginState, 'unknown'> | null {
  const s = a.session;
  if (!s) return null;
  const hit = cookies.some((c) => {
    if (!s.cookies.includes(c.name) || !c.value) return false;
    if (c.expirationDate !== undefined && c.expirationDate > 0 && c.expirationDate < nowSec) return false;
    if (s.domains?.length && c.domain && !hostAllowed(c.domain.replace(/^\./, ''), s.domains)) return false;
    return true;
  });
  return hit ? 'in' : 'out';
}

/** Runs inside the platform page (isolated world): only reads whether the two kinds of form are there. */
export const PAGE_SIGNALS_JS = `(() => {
  const vis = (el) => el && el.getClientRects().length > 0;
  const roots = [document];
  for (let i = 0; i < roots.length && i < 200; i++) for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
  const q = (s) => roots.some((r) => [...r.querySelectorAll(s)].length > 0);
  const qv = (s) => roots.some((r) => [...r.querySelectorAll(s)].some(vis));
  const text = (document.body && document.body.innerText || '').slice(0, 3000);
  const loginText = /扫码登录|验证码登录|短信登录|密码登录|登录视频号助手|Log in to TikTok|Log into Instagram|Sign in to continue/i.test(text);
  return { fileInput: q('input[type=file]'), loginForm: qv('input[type=password]') || loginText };
})()`;

/** Settings.accounts (labels) + Settings.channels (prefs) -> the list the UI shows, in adapter order. */
export function listChannels(accounts: Record<string, string[]>, prefs: Record<string, ChannelPrefs> | undefined, order: string[] = []): ChannelMsg[] {
  const ids = [...new Set([...order.filter((id) => accounts[id]?.length), ...Object.keys(accounts)])];
  const out: ChannelMsg[] = [];
  for (const adapterId of ids) {
    for (const account of accounts[adapterId] ?? []) {
      const p = prefs?.[channelKey(adapterId, account)] ?? {};
      out.push({ adapterId, account, name: p.name?.trim() || account, times: p.times?.length ? p.times : [], login: { state: p.login?.state ?? 'unknown', at: p.login?.at ?? null } });
    }
  }
  return out;
}

/** A label for a new account of this platform: main, main-2, main-3 ... */
export function nextAccountLabel(existing: string[]): string {
  if (!existing.includes('main')) return 'main';
  for (let i = 2; ; i++) if (!existing.includes(`main-${i}`)) return `main-${i}`;
}
