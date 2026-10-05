import { useEffect, useState } from 'react';

// Hash routes: #/batches  #/new  #/b/<id>/board|review|publish  #/b/<id>/job/<job>  #/settings
export type Route =
  | { name: 'batches' }
  | { name: 'new' }
  | { name: 'settings' }
  | { name: 'board'; batch: string }
  | { name: 'review'; batch: string }
  | { name: 'publish'; batch: string }
  | { name: 'job'; batch: string; job: string };

export function parseRoute(hash: string): Route {
  const p = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  if (p[0] === 'new') return { name: 'new' };
  if (p[0] === 'settings') return { name: 'settings' };
  if (p[0] === 'b' && p[1]) {
    if (p[2] === 'job' && p[3]) return { name: 'job', batch: p[1], job: p[3] };
    if (p[2] === 'review') return { name: 'review', batch: p[1] };
    if (p[2] === 'publish') return { name: 'publish', batch: p[1] };
    return { name: 'board', batch: p[1] };
  }
  return { name: 'batches' };
}

export function href(r: Route): string {
  switch (r.name) {
    case 'batches':
    case 'new':
    case 'settings':
      return `#/${r.name}`;
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
