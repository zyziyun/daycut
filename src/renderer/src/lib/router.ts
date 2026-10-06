import { useEffect, useState } from 'react';

// Hash routes (v0.4): #/ home · #/inbox · #/projects · #/p/<id>[/<tab>] · #/p/<id>/clip/<clip> (editor)
//   · #/p/<id>/focus (full-screen review) · #/publish · #/settings · #/new[/recording]
// Kept for the per-batch tools: #/b/<id>/board|review|deliver|publish · #/b/<id>/job/<job> · #/clients[/<slug>]
//   · #/metrics · #/welcome. Old #/work[/<id>] and #/batches links land on the new pages.
export type ProjectTab = 'clips' | 'review' | 'deliver' | 'history' | 'files';
export type Route =
  | { name: 'home' }
  | { name: 'inbox' }
  | { name: 'projects' }
  | { name: 'project'; id: string; tab?: ProjectTab }
  | { name: 'clip'; id: string; clip: string }
  | { name: 'focus'; id: string }
  | { name: 'calendar' }
  | { name: 'new'; mode?: 'recording' }
  | { name: 'settings' }
  | { name: 'aiAccounts'; focus?: string }
  | { name: 'clients' }
  | { name: 'client'; slug: string }
  | { name: 'metrics' }
  | { name: 'welcome' }
  | { name: 'deliver'; batch: string }
  | { name: 'board'; batch: string }
  | { name: 'review'; batch: string }
  | { name: 'publish'; batch: string }
  | { name: 'job'; batch: string; job: string };

const ID = /^[0-9a-f]{12}$/;
const TABS: ProjectTab[] = ['clips', 'review', 'deliver', 'history', 'files'];

export function parseRoute(hash: string): Route {
  const p = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map((x) => {
    try {
      return decodeURIComponent(x);
    } catch {
      return x;
    }
  });
  if (!p.length || p[0] === 'home') return { name: 'home' };
  if (p[0] === 'inbox') return { name: 'inbox' };
  if (p[0] === 'projects' || p[0] === 'batches') return { name: 'projects' };
  if (p[0] === 'work') return p[1] && ID.test(p[1]) ? { name: 'project', id: p[1] } : { name: 'projects' };
  if (p[0] === 'p' && p[1] && ID.test(p[1])) {
    if (p[2] === 'clip' && p[3]) return { name: 'clip', id: p[1], clip: p[3] };
    if (p[2] === 'focus') return { name: 'focus', id: p[1] };
    return { name: 'project', id: p[1], tab: TABS.includes(p[2] as ProjectTab) ? (p[2] as ProjectTab) : undefined };
  }
  if (p[0] === 'publish') return { name: 'calendar' };
  if (p[0] === 'new') return p[1] === 'recording' ? { name: 'new', mode: 'recording' } : { name: 'new' };
  if (p[0] === 'settings') return p[1] === 'ai' ? { name: 'aiAccounts', focus: p[2] } : { name: 'settings' };
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
  switch (r.name) {
    case 'home':
      return '#/';
    case 'inbox':
    case 'projects':
    case 'settings':
    case 'clients':
    case 'metrics':
    case 'welcome':
      return `#/${r.name}`;
    case 'calendar':
      return '#/publish';
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
    const on = () => setR(parseRoute(location.hash));
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return r;
}
