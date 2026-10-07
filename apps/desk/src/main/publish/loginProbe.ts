// Login state from an account's own session partition (persist:<adapter>-<account>, the same partition the built-in
// browser panel uses): only whether one of the adapter's session cookies is set. Cookie values never leave this
// function - not stored, not logged, not sent.
import { sessionLoginState, type CookieLike } from '../../shared/channels';
import type { Adapter } from '../../shared/publish/adapterSchema';

export interface CookieJar {
  cookies: { get(filter: Record<string, unknown>): Promise<CookieLike[]> };
}

export async function probeLogin(ses: CookieJar, adapter: Pick<Adapter, 'session'>, nowSec = Date.now() / 1000): Promise<'in' | 'out' | null> {
  if (!adapter.session) return null;
  let all: CookieLike[];
  try {
    const lists = await Promise.all(adapter.session.cookies.map((name) => ses.cookies.get({ name })));
    all = lists.flat().map((c) => ({ name: c.name, value: c.value ? 'x' : '', domain: c.domain, expirationDate: c.expirationDate }));
  } catch {
    return null;
  }
  return sessionLoginState(all, adapter, nowSec);
}
