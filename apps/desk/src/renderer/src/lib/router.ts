import { useEffect, useState } from 'react';
import { createEnabled } from '../create/flag';
import { studioEnabled } from './studioFlag';

// Hash routes (v0.4): #/ home · #/inbox · #/projects · #/p/<id>[/<tab>] · #/p/<id>/clip/<clip> (editor)
//   · #/p/<id>/focus (full-screen review) · #/publish · #/publish/accounts (publishing accounts) · #/settings · #/new[/recording]
// Kept for the per-batch tools: #/b/<id>/board|review|deliver|publish · #/b/<id>/job/<job> · #/clients[/<slug>]
//   · #/metrics · #/welcome. Old #/work[/<id>] and #/batches links land on the new pages.
export type ProjectTab = 'clips' | 'review' | 'deliver' | 'history' | 'files';
export type Route =
  /** #/studio[/<project>[/<clip>]]: every video in one list, one page per video (the Studio flag; with it on, Home,
   * the Inbox, All projects, a project's clips and the clip editor land here) */
  | { name: 'studio'; id?: string; clip?: string }
  | { name: 'home' }
  | { name: 'inbox' }
  | { name: 'projects' }
  | { name: 'project'; id: string; tab?: ProjectTab }
  | { name: 'clip'; id: string; clip: string }
  | { name: 'focus'; id: string }
  | { name: 'calendar' }
  | { name: 'channels' }
  /** #/publish/post/<id>: "Time to post" for one scheduled post (fill its upload page, she presses Publish) */
  | { name: 'postNow'; id: string }
  | { name: 'new'; mode?: 'recording' }
  /** #/settings[/<section>[/<sub>]]: a section of the settings registry (settings/registry.ts) */
  | { name: 'settings'; section?: string; sub?: string }
  | { name: 'aiAccounts'; focus?: string }
  | { name: 'clients' }
  | { name: 'client'; slug: string }
  | { name: 'metrics' }
  | { name: 'welcome' }
  | { name: 'deliver'; batch: string }
  | { name: 'board'; batch: string }
  | { name: 'review'; batch: string }
  | { name: 'publish'; batch: string }
  | { name: 'job'; batch: string; job: string }
  /** Create page (flag-gated; the sub-path is parsed in create/routes.ts) */
  | { name: 'create'; path: string[] };

const ID = /^[0-9a-f]{12}$/;
const TABS: ProjectTab[] = ['clips', 'review', 'deliver', 'history', 'files'];

/** `#/p/<id>/clip/<clip>?t=2.5&triage=1` -> {t: '2.5', triage: '1'} (the part after `?`; routes ignore it). */
export function routeQuery(hash: string = typeof location !== 'undefined' ? location.hash : ''): Record<string, string> {
  const q = hash.indexOf('?');
  return q < 0 ? {} : Object.fromEntries(new URLSearchParams(hash.slice(q + 1)));
}

export function parseRoute(hash: string): Route {
  const p = hash.replace(/^#\/?/, '').replace(/\?.*$/, '').split('/').filter(Boolean).map((x) => {
    try {
      return decodeURIComponent(x);
    } catch {
      return x;
    }
  });
  const r = parseOwn(p);
  return studioEnabled() ? toStudio(r) : r.name === 'studio' ? { name: 'home' } : r;
}

/** With the Studio on, the pages it replaces open in it (the filter / selection ride along in the query). */
export function toStudio(r: Route): Route {
  switch (r.name) {
    case 'home':
    case 'inbox':
    case 'projects':
      return { name: 'studio' };
    case 'project':
      return r.tab ? r : { name: 'studio', id: r.id };
    case 'clip':
      return { name: 'studio', id: r.id, clip: r.clip };
    default:
      return r;
  }
}

function parseOwn(p: string[]): Route {
  if (!p.length || p[0] === 'home') return { name: 'home' };
  if (p[0] === 'studio') return p[1] && ID.test(p[1]) ? (p[2] ? { name: 'studio', id: p[1], clip: p[2] } : { name: 'studio', id: p[1] }) : { name: 'studio' };
  if (p[0] === 'inbox') return { name: 'inbox' };
  if (p[0] === 'projects' || p[0] === 'batches') return { name: 'projects' };
  if (p[0] === 'work') return p[1] && ID.test(p[1]) ? { name: 'project', id: p[1] } : { name: 'projects' };
  if (p[0] === 'p' && p[1] && ID.test(p[1])) {
    if (p[2] === 'clip' && p[3]) return { name: 'clip', id: p[1], clip: p[3] };
    if (p[2] === 'focus') return { name: 'focus', id: p[1] };
    return { name: 'project', id: p[1], tab: TABS.includes(p[2] as ProjectTab) ? (p[2] as ProjectTab) : undefined };
  }
  if (p[0] === 'publish') return p[1] === 'accounts' ? { name: 'channels' } : p[1] === 'post' && p[2] && ID.test(p[2]) ? { name: 'postNow', id: p[2] } : { name: 'calendar' };
  if (p[0] === 'new') return p[1] === 'recording' ? { name: 'new', mode: 'recording' } : { name: 'new' };
  if (p[0] === 'create') return createEnabled() ? { name: 'create', path: p.slice(1, 5) } : { name: 'home' };
  if (p[0] === 'settings') return p[1] === 'ai' ? { name: 'aiAccounts', focus: p[2] } : p[1] ? { name: 'settings', section: p[1], sub: p[2] } : { name: 'settings' };
  if (p[0] === 'metrics') return { name: 'metrics' };
  if (p[0] === 'welcome') return { name: 'welcome' };
  if (p[0] === 'clients') return p[1] ? { name: 'client', slug: p[1] } : { name: 'clients' };
  if (p[0] === 'b' && p[1]) {
    if (p[2] === 'job' && p[3]) return { name: 'job', batch: p[1], job: p[3] };
    if (p[2] === 'review') return { name: 'review', batch: p[1] };
    if (p[2] === 'publish') return { name: 'publish', batch: p[1] };
    if (p[2] === 'deliver') return { name: 'deliver', batch: p[1] };
    return { name: 'board', batch: p[1] };
  }
  return { name: 'home' };
}

export function href(r: Route): string {
  if (studioEnabled() && r.name !== 'studio') {
    const s = toStudio(r);
    if (s.name === 'studio') return href(s) + (r.name === 'inbox' ? '?f=you' : '');
  }
  switch (r.name) {
    case 'studio':
      return `#/studio${r.id ? `/${r.id}${r.clip ? `/${encodeURIComponent(r.clip)}` : ''}` : ''}`;
    case 'home':
      return '#/';
    case 'settings':
      return `#/settings${r.section ? `/${encodeURIComponent(r.section)}${r.sub ? `/${encodeURIComponent(r.sub)}` : ''}` : ''}`;
    case 'inbox':
    case 'projects':
    case 'clients':
    case 'metrics':
    case 'welcome':
      return `#/${r.name}`;
    case 'calendar':
      return '#/publish';
    case 'channels':
      return '#/publish/accounts';
    case 'postNow':
      return `#/publish/post/${r.id}`;
    case 'aiAccounts':
      return r.focus ? `#/settings/ai/${encodeURIComponent(r.focus)}` : '#/settings/ai';
    case 'new':
      return r.mode ? `#/new/${r.mode}` : '#/new';
    case 'project':
      return `#/p/${r.id}${r.tab && r.tab !== 'clips' ? `/${r.tab}` : ''}`;
    case 'clip':
      return `#/p/${r.id}/clip/${encodeURIComponent(r.clip)}`;
    case 'focus':
      return `#/p/${r.id}/focus`;
    case 'client':
      return `#/clients/${encodeURIComponent(r.slug)}`;
    case 'job':
      return `#/b/${r.batch}/job/${encodeURIComponent(r.job)}`;
    case 'create':
      if (r.path[0] === 'settings') return '#/settings/video';
      return r.path.length ? `#/create/${r.path.map(encodeURIComponent).join('/')}` : '#/create';
    default:
      return `#/b/${r.batch}/${r.name}`;
  }
}

export function go(r: Route) {
  location.hash = href(r);
}

export function useRoute(): Route {
  const [r, setR] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const on = () =>
      setR((prev) => {
        const next = parseRoute(location.hash);
        return JSON.stringify(next) === JSON.stringify(prev) ? prev : next; // a query change keeps the screen
      });
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return r;
}

/** The query of the current hash, updated on every navigation. */
export function useRouteQuery(): Record<string, string> {
  const [q, setQ] = useState(() => routeQuery());
  useEffect(() => {
    const on = () => setQ(routeQuery());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return q;
}
