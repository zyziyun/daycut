// Create routes live under one top-level route ({name: 'create', path}) so the app router stays untouched apart from
// one line; this file turns the path into a screen.
//   #/create                      home            #/create/s/<sid>[/<tab>]   series (bible|episodes|scripts|making|ready)
//   #/create/e/<eid>[/<tab>]      episode (script|storyboard|takes|edit)
//   #/create/record[/e/<eid>/<no> | /s/<sid>]     recorder             #/settings/video   Settings › Video generation
export type SeriesTab = 'bible' | 'episodes' | 'scripts' | 'making' | 'ready';
export type EpisodeTab = 'script' | 'storyboard' | 'takes' | 'edit';
export const SERIES_TABS: SeriesTab[] = ['bible', 'episodes', 'scripts', 'making', 'ready'];
export const EPISODE_TABS: EpisodeTab[] = ['script', 'storyboard', 'takes', 'edit'];

export type CreateRoute =
  | { screen: 'home' }
  | { screen: 'series'; sid: string; tab: SeriesTab }
  | { screen: 'episode'; eid: string; tab: EpisodeTab }
  | { screen: 'record'; sid?: string; eid?: string; shot?: string }
  | { screen: 'settings' };

const ID = /^[a-z0-9][a-z0-9-]{0,47}$/;
const SHOT = /^\d{2,3}$/;

export function parseCreate(path: string[]): CreateRoute {
  const [a, b, c, d] = path;
  if (a === 's' && b && ID.test(b)) return { screen: 'series', sid: b, tab: SERIES_TABS.includes(c as SeriesTab) ? (c as SeriesTab) : 'bible' };
  if (a === 'e' && b && ID.test(b)) return { screen: 'episode', eid: b, tab: EPISODE_TABS.includes(c as EpisodeTab) ? (c as EpisodeTab) : 'storyboard' };
  if (a === 'record') {
    if (b === 'e' && c && ID.test(c)) return { screen: 'record', eid: c, shot: d && SHOT.test(d) ? d : undefined };
    if (b === 's' && c && ID.test(c)) return { screen: 'record', sid: c };
    return { screen: 'record' };
  }
  if (a === 'settings') return { screen: 'settings' };
  return { screen: 'home' };
}

export function createPath(r: CreateRoute): string[] {
  switch (r.screen) {
    case 'series':
      return r.tab === 'bible' ? ['s', r.sid] : ['s', r.sid, r.tab];
    case 'episode':
      return r.tab === 'storyboard' ? ['e', r.eid] : ['e', r.eid, r.tab];
    case 'record':
      if (r.eid) return r.shot ? ['record', 'e', r.eid, r.shot] : ['record', 'e', r.eid];
      return r.sid ? ['record', 's', r.sid] : ['record'];
    case 'settings':
      return ['settings'];
    default:
      return [];
  }
}

/** '#/create/…' for a screen ('#/settings/video' for the settings page). */
export function createHref(r: CreateRoute): string {
  if (r.screen === 'settings') return '#/settings/video';
  const p = createPath(r);
  return p.length ? `#/create/${p.map(encodeURIComponent).join('/')}` : '#/create';
}

export function goCreate(r: CreateRoute) {
  location.hash = createHref(r);
}
