// YouTube Data API v3 posting (opt-in): her own Google Cloud OAuth client ("Desktop app"), OAuth 2.0 for installed
// apps with PKCE and a loopback redirect (127.0.0.1, random port) in the system browser, scope youtube.upload only.
// The refresh token is kept in the keychain (ApiVault). Upload = videos.insert, resumable; a time ahead -> private +
// status.publishAt, so YouTube itself publishes at her time even when the Mac is asleep.
// Google's rule for unverified API projects (since 2020-07-28): their uploads are locked to private until the
// project passes YouTube's API audit - docs/PUBLISHING.md says how; the result is shown, never hidden.
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { Readable } from 'node:stream';
import type { ApiVault } from './vault';

export const YT_SCOPE = 'https://www.googleapis.com/auth/youtube.upload';
const AUTH = 'https://accounts.google.com/o/oauth2/v2/auth';
const TOKEN = 'https://oauth2.googleapis.com/token';
const REVOKE = 'https://oauth2.googleapis.com/revoke';
const UPLOAD = 'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status';

export type Fetch = typeof fetch;

export interface YtDeps {
  vault: ApiVault;
  fetch?: Fetch;
  /** opens the consent page in the system browser */
  openExternal: (url: string) => Promise<void> | void;
  log?: (msg: string) => void;
}

export interface YtVideo {
  file: string;
  title: string;
  description: string;
  tags: string[];
  /** null: public now */
  publishAt: Date | null;
}

const b64url = (b: Buffer) => b.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/** YouTube refuses < and > in titles / descriptions; title max 100 chars, description 5000 bytes, tags 500 chars. */
export function ytMeta(v: Pick<YtVideo, 'title' | 'description' | 'tags' | 'publishAt'>) {
  const clean = (s: string) => s.replace(/[<>]/g, '');
  const title = Array.from(clean(v.title).trim() || 'Untitled').slice(0, 100).join('');
  let description = clean(v.description);
  while (Buffer.byteLength(description, 'utf8') > 5000) description = Array.from(description).slice(0, -1).join('');
  const tags: string[] = [];
  let len = 0;
  for (const t of v.tags.map((x) => clean(x).replace(/^#/, '').trim()).filter(Boolean)) {
    const add = t.length + (t.includes(' ') ? 2 : 0) + (tags.length ? 1 : 0);
    if (len + add > 500) break;
    tags.push(t);
    len += add;
  }
  return {
    snippet: { title, description, tags, categoryId: '22' },
    status: v.publishAt
      ? { privacyStatus: 'private', publishAt: v.publishAt.toISOString(), selfDeclaredMadeForKids: false }
      : { privacyStatus: 'public', selfDeclaredMadeForKids: false },
  };
}

export class YouTubeApi {
  private access: { token: string; until: number } | null = null;

  constructor(private d: YtDeps) {}

  private get f(): Fetch {
    return this.d.fetch ?? fetch;
  }

  setClient(clientId: string, clientSecret: string) {
    if (!/^[\w.-]{5,200}\.apps\.googleusercontent\.com$/.test(clientId)) throw new Error('client ID: the "….apps.googleusercontent.com" ID of a Desktop-app OAuth client');
    if (!/^[\x21-\x7e]{8,200}$/.test(clientSecret)) throw new Error('client secret: the secret shown next to that client ID');
    this.d.vault.set('youtube', { clientId, clientSecret, refreshToken: undefined, connectedAt: undefined });
    this.access = null;
  }

  status() {
    const s = this.d.vault.get('youtube');
    return { hasClient: !!(s.clientId && s.clientSecret), connected: !!s.refreshToken, connectedAt: s.connectedAt ?? null };
  }

  /** OAuth in the system browser; resolves once Google redirected back to the loopback port (or after 5 minutes). */
  async connect(timeoutMs = 5 * 60_000): Promise<{ connected: true }> {
    const s = this.d.vault.get('youtube');
    if (!s.clientId || !s.clientSecret) throw new Error('add your OAuth client first');
    const verifier = b64url(crypto.randomBytes(48));
    const challenge = b64url(crypto.createHash('sha256').update(verifier).digest());
    const state = b64url(crypto.randomBytes(16));
    const { code, redirect } = await new Promise<{ code: string; redirect: string }>((resolve, reject) => {
      const server = http.createServer((req, res) => {
        const u = new URL(req.url ?? '/', 'http://127.0.0.1');
        if (u.pathname !== '/') {
          res.writeHead(404).end();
          return;
        }
        const ok = u.searchParams.get('state') === state && !!u.searchParams.get('code');
        res.writeHead(ok ? 200 : 400, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(ok ? '<p style="font:16px system-ui">Reelfold is connected to YouTube. You can close this tab.</p>' : '<p style="font:16px system-ui">Not connected. Go back to Reelfold and try again.</p>');
        finish(ok ? null : new Error(u.searchParams.get('error') || 'the consent was not completed'), u.searchParams.get('code'));
      });
      const timer = setTimeout(() => finish(new Error('no answer from Google within 5 minutes'), null), timeoutMs);
      let settled = false;
      const finish = (err: Error | null, c: string | null) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        server.close();
        if (err || !c) reject(err ?? new Error('no code'));
        else resolve({ code: c, redirect: `http://127.0.0.1:${(server.address() as AddressInfo | null)?.port ?? port}` });
      };
      let port = 0;
      server.listen(0, '127.0.0.1', () => {
        port = (server.address() as AddressInfo).port;
        const q = new URLSearchParams({
          client_id: s.clientId!,
          redirect_uri: `http://127.0.0.1:${port}`,
          response_type: 'code',
          scope: YT_SCOPE,
          code_challenge: challenge,
          code_challenge_method: 'S256',
          state,
          access_type: 'offline',
          prompt: 'consent',
        });
        void Promise.resolve(this.d.openExternal(`${AUTH}?${q}`)).catch((e: Error) => finish(e, null));
      });
    });
    const r = await this.f(TOKEN, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ code, client_id: s.clientId, client_secret: s.clientSecret, redirect_uri: redirect, grant_type: 'authorization_code', code_verifier: verifier }),
    });
    const j = (await r.json().catch(() => ({}))) as { access_token?: string; refresh_token?: string; expires_in?: number; scope?: string; error_description?: string; error?: string };
    if (!r.ok || !j.refresh_token) throw new Error(`Google did not grant access: ${j.error_description || j.error || r.status}`);
    this.d.vault.set('youtube', { refreshToken: j.refresh_token, scope: j.scope, connectedAt: new Date().toISOString() });
    if (j.access_token) this.access = { token: j.access_token, until: Date.now() + (j.expires_in ?? 3000) * 1000 - 60_000 };
    return { connected: true };
  }

  async disconnect() {
    const s = this.d.vault.get('youtube');
    if (s.refreshToken) {
      await this.f(`${REVOKE}?token=${encodeURIComponent(s.refreshToken)}`, { method: 'POST' }).catch(() => undefined);
    }
    this.d.vault.set('youtube', { refreshToken: undefined, scope: undefined, connectedAt: undefined });
    this.access = null;
  }

  private async token(): Promise<string> {
    if (this.access && this.access.until > Date.now()) return this.access.token;
    const s = this.d.vault.get('youtube');
    if (!s.refreshToken || !s.clientId || !s.clientSecret) throw new Error('YouTube is not connected');
    const r = await this.f(TOKEN, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ client_id: s.clientId, client_secret: s.clientSecret, refresh_token: s.refreshToken, grant_type: 'refresh_token' }),
    });
    const j = (await r.json().catch(() => ({}))) as { access_token?: string; expires_in?: number; error?: string };
    if (!r.ok || !j.access_token) {
      if (j.error === 'invalid_grant') this.d.vault.set('youtube', { refreshToken: undefined, connectedAt: undefined });
      throw new Error(`YouTube sign-in expired or was revoked (${j.error ?? r.status}): connect again`);
    }
    this.access = { token: j.access_token, until: Date.now() + (j.expires_in ?? 3000) * 1000 - 60_000 };
    return j.access_token;
  }

  /** videos.insert (resumable): -> the video's link. */
  async upload(v: YtVideo): Promise<{ id: string; url: string; privacy: string }> {
    const size = fs.statSync(v.file).size;
    const meta = ytMeta(v);
    const token = await this.token();
    const init = await this.f(UPLOAD, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json; charset=UTF-8',
        'X-Upload-Content-Length': String(size),
        'X-Upload-Content-Type': 'video/*',
      },
      body: JSON.stringify(meta),
    });
    const loc = init.headers.get('location');
    if (!init.ok || !loc) throw new Error(`YouTube refused the upload: ${await errText(init)}`);
    if (!loc.startsWith('https://www.googleapis.com/')) throw new Error('unexpected upload location');
    const put = await this.f(loc, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Length': String(size), 'Content-Type': 'video/*' },
      body: Readable.toWeb(fs.createReadStream(v.file)) as unknown as BodyInit,
      duplex: 'half',
    } as RequestInit);
    const j = (await put.json().catch(() => ({}))) as { id?: string; status?: { privacyStatus?: string } };
    if (!put.ok || !j.id) throw new Error(`YouTube upload failed: ${put.status}`);
    this.d.log?.(`[youtube] uploaded ${j.id} (${j.status?.privacyStatus ?? meta.status.privacyStatus})`);
    return { id: j.id, url: `https://youtu.be/${j.id}`, privacy: j.status?.privacyStatus ?? meta.status.privacyStatus };
  }
}

async function errText(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { error?: { message?: string; errors?: { reason?: string }[] } };
    return `${r.status} ${j.error?.errors?.[0]?.reason ?? ''} ${j.error?.message ?? ''}`.trim();
  } catch {
    return String(r.status);
  }
}
