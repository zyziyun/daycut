// The in-app update, as one state the main process owns (main/updater.ts feeds it electron-updater's events) and the
// window shows: a pill in the sidebar footer while it downloads / once it is ready, a one-time card "Reelfold 0.2.5 is
// ready — Restart to update" (What's new · Later), and Settings › General › Updates. Pure: shared by main, renderer
// and the unit tests.

export type UpdatePhase = 'disabled' | 'idle' | 'checking' | 'available' | 'downloading' | 'ready' | 'none' | 'error';

/** Where an update went wrong: the words she sees differ (offline check vs. a broken download vs. the install). */
export type UpdateErrorStage = 'check' | 'download' | 'install';

export interface UpdateStateMsg {
  state: UpdatePhase;
  /** the version on offer (available / downloading / ready) */
  version?: string;
  /** download progress, 0-100 */
  percent?: number;
  /** first line of the updater's error, as is (shown under the plain words) */
  error?: string;
  errorStage?: UpdateErrorStage;
  /** release notes of the version on offer, as plain text (see notesText) */
  notes?: string;
  /** when the last check finished (ms since epoch), whatever its result */
  checkedAt?: number;
  /** the running version */
  current?: string;
}

export type UpdateEvent =
  | { type: 'checking' }
  | { type: 'available'; version: string; notes?: string; at: number }
  | { type: 'none'; at: number }
  | { type: 'progress'; percent: number }
  | { type: 'downloaded'; version: string; notes?: string; at?: number }
  | { type: 'error'; message: string; at: number }
  | { type: 'install-failed'; message: string };

/** The next state for one updater event. A downloaded update stays ready through a later "checking" / "available"
 * of the same version; only an install failure takes it away. */
export function reduceUpdate(s: UpdateStateMsg, e: UpdateEvent): UpdateStateMsg {
  const base = { current: s.current, checkedAt: s.checkedAt };
  if (s.state === 'disabled') return s;
  switch (e.type) {
    case 'checking':
      return s.state === 'ready' || s.state === 'downloading' ? s : { ...base, state: 'checking' };
    case 'available':
      if (s.state === 'ready' && s.version === e.version) return s;
      return { ...base, state: 'available', version: e.version, notes: e.notes ?? s.notes, percent: 0, checkedAt: e.at };
    case 'none':
      return s.state === 'ready' ? { ...s, checkedAt: e.at } : { ...base, state: 'none', checkedAt: e.at };
    case 'progress':
      if (s.state === 'ready') return s;
      return { ...base, state: 'downloading', version: s.version, notes: s.notes, percent: clampPercent(e.percent) };
    case 'downloaded':
      return { ...base, state: 'ready', version: e.version, notes: e.notes ?? s.notes, percent: 100, checkedAt: e.at ?? s.checkedAt };
    case 'error': {
      const message = firstLine(e.message);
      // once downloaded nothing checks any more (shouldCheck): an error now is the OS installer (Squirrel.Mac)
      // failing to stage it, so "Restart to update" would not install anything
      if (s.state === 'ready') return { ...base, state: 'error', error: message, errorStage: 'install', version: s.version, notes: s.notes };
      const stage: UpdateErrorStage = s.state === 'downloading' || s.state === 'available' ? 'download' : 'check';
      return { ...base, state: 'error', error: message, errorStage: stage, version: stage === 'download' ? s.version : undefined, checkedAt: e.at };
    }
    case 'install-failed':
      return { ...base, state: 'error', error: firstLine(e.message), errorStage: 'install', version: s.version, notes: s.notes };
  }
}

function clampPercent(p: number): number {
  return Number.isFinite(p) ? Math.max(0, Math.min(100, Math.round(p))) : 0;
}

function firstLine(m: string): string {
  return String(m ?? '').split('\n')[0].trim().slice(0, 300);
}

/** A periodic / launch check is skipped while one runs and once an update is downloaded (nothing newer to do until
 * she restarts); a check she asks for in Settings always runs, except during a download. */
export function shouldCheck(s: UpdateStateMsg, manual: boolean): boolean {
  if (s.state === 'disabled' || s.state === 'checking' || s.state === 'downloading') return false;
  if (s.state === 'ready') return false;
  return manual || s.state !== 'available';
}

// ---------------------------------------------------------------- release notes
type NoteEntry = { version?: string; note?: string | null };

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', '#39': "'", mdash: '—', ndash: '–', hellip: '…', rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“' };

function decode(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z0-9]+);/gi, (m, name: string) => {
    if (name[0] === '#') {
      const n = name[1].toLowerCase() === 'x' ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
      return Number.isFinite(n) && n > 0 && n < 0x110000 ? String.fromCodePoint(n) : m;
    }
    return ENTITIES[name.toLowerCase()] ?? m;
  });
}

const HEAD = '\u0001'; // marks a heading: a blank line goes before it, nowhere else

/** One release's notes as plain text. GitHub's release feed gives the body as HTML (rendered Markdown); a generic
 * feed (latest-mac.yml `releaseNotes`) gives Markdown or plain text. A heading starts a new block (blank line before
 * it), list items get "• ", every other line is kept as a line; all markup is dropped. Never HTML out: the window
 * shows it as text. */
export function noteToText(raw: string): string {
  let s = String(raw ?? '');
  if (/<[a-z][\s\S]*>/i.test(s)) {
    s = s
      .replace(/<(script|style)[\s\S]*?<\/\1>/gi, '')
      .replace(/\s+/g, ' ') // HTML whitespace is not layout
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<li[^>]*>/gi, '\n• ')
      .replace(/<h[1-6][^>]*>/gi, `\n${HEAD}`)
      .replace(/<\/(h[1-6]|p|ul|ol|li|div|blockquote|pre)>/gi, '\n')
      .replace(/<p[^>]*>/gi, '\n')
      .replace(/<[^>]+>/g, '');
    s = decode(s);
  } else {
    s = s
      .replace(/^#{1,6}[ \t]+/gm, HEAD)
      .replace(/^[ \t]*[-*+][ \t]+/gm, '• ')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/__([^_]+)__/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  }
  return s
    .split('\n')
    .map((l) => l.replace(/[ \t]+/g, ' ').trim())
    .filter((l) => l && l !== HEAD)
    .join('\n')
    .replace(new RegExp(`\\n?${HEAD}`, 'g'), '\n\n')
    .trim();
}

/** electron-updater's `releaseNotes` (a string, or one entry per version newer than this one with fullChangelog) as
 * plain text; '' when there are none. Capped so a long changelog cannot flood the window. */
export function notesText(releaseNotes: string | NoteEntry[] | null | undefined, max = 8000): string {
  if (!releaseNotes) return '';
  const text = Array.isArray(releaseNotes)
    ? releaseNotes
        .map((n) => {
          const body = noteToText(n?.note ?? '');
          return n?.version ? `${n.version}\n${body}`.trim() : body;
        })
        .filter(Boolean)
        .join('\n\n')
    : noteToText(releaseNotes);
  return text.length > max ? `${text.slice(0, max).trimEnd()}\n…` : text;
}

// ---------------------------------------------------------------- the prompt
/** The one-time card: once per version per launch, when the update is ready and she has not said "Later" to that
 * version in this launch. "Later" lasts for this launch only: the card is back next time the app opens (and the
 * update installs by itself when she quits). */
export function shouldShowCard(s: UpdateStateMsg | null, later: ReadonlySet<string>, shown: ReadonlySet<string>): boolean {
  if (!s || s.state !== 'ready' || !s.version) return false;
  return !later.has(s.version) && !shown.has(s.version);
}

/** What "Restart to update" does with projects running: nothing to wait for -> restart now; otherwise ask
 * (restart when they finish / restart now / cancel). */
export function restartPlan(running: number): 'now' | 'ask' {
  return running > 0 ? 'ask' : 'now';
}

/** "Restart when done": restart once nothing runs any more (and the update is still ready). */
export function restartWhenDoneDue(pending: boolean, running: number, s: UpdateStateMsg | null): boolean {
  return pending && running === 0 && s?.state === 'ready';
}

/** Plain words for an error stage (an i18n key; the raw updater line is shown smaller underneath). */
export function errorKey(stage: UpdateErrorStage | undefined): 'upd.err.check' | 'upd.err.download' | 'upd.err.install' {
  return stage === 'download' ? 'upd.err.download' : stage === 'install' ? 'upd.err.install' : 'upd.err.check';
}
