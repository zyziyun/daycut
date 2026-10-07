// Security helpers for the app UI and the embedded platform pages.

export interface CspOptions {
  dev: boolean;
  enginePort: number | null;
  devServerUrl?: string;
}

/** Strict CSP for the desk UI. Dev only adds what Vite's HMR + React refresh need (inline preamble, ws). */
export function buildCsp(o: CspOptions): string {
  const engine = o.enginePort ? `http://127.0.0.1:${o.enginePort}` : '';
  const devOrigin = o.dev && o.devServerUrl ? new URL(o.devServerUrl).origin : '';
  const devWs = devOrigin ? devOrigin.replace(/^http/, 'ws') : '';
  const d: Record<string, string[]> = {
    'default-src': ["'none'"],
    'script-src': ["'self'", ...(o.dev ? ["'unsafe-inline'"] : [])],
    'style-src': ["'self'", "'unsafe-inline'"],
    'img-src': ["'self'", 'data:', 'vsmedia:'],
    'media-src': ["'self'", 'vsmedia:'],
    'font-src': ["'self'", 'data:'],
    'connect-src': ["'self'", engine, devWs].filter(Boolean),
    'object-src': ["'none'"],
    'frame-src': ["'none'"],
    'worker-src': ["'none'"],
    'base-uri': ["'none'"],
    'form-action': ["'none'"],
    'frame-ancestors': ["'none'"],
  };
  return Object.entries(d)
    .map(([k, v]) => `${k} ${v.join(' ')}`)
    .join('; ');
}

/** The app UI may only ever show its own origin. */
export function isAppUrl(url: string, appOrigin: string): boolean {
  try {
    // compare scheme + host: Node's URL gives origin "null" for custom schemes such as app://
    const u = new URL(url);
    return `${u.protocol}//${u.host}` === appOrigin;
  } catch {
    return false;
  }
}

/** Links the UI may hand to the system browser. */
export function isSafeExternal(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'mailto:';
  } catch {
    return false;
  }
}

/** Requests from platform pages to the local engine are cancelled (defence in depth; it also needs a token). */
export function isLocalEngineRequest(url: string): boolean {
  try {
    const u = new URL(url);
    return (u.protocol === 'http:' || u.protocol === 'ws:') && ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname);
  } catch {
    return false;
  }
}

/** Permissions platform pages may get: none of camera/mic/geolocation/notifications/midi/hid/serial... Only
 * clipboard writes (copy buttons) and fullscreen of the preview player. */
export const REMOTE_ALLOWED_PERMISSIONS = new Set(['clipboard-sanitized-write', 'fullscreen']);
