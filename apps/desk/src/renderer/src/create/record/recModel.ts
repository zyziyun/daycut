// The recorder's plain logic (no React, no devices): prefs, the script, what the big button does, the keys, the
// teleprompter's pace. RecordStudio and the unit tests share it.

export type Phase = 'off' | 'ready' | 'countdown' | 'recording' | 'paused' | 'stopping';
export type Speed = 'slow' | 'normal' | 'fast';
export type TextSize = 's' | 'm' | 'l';

/** words per minute of the steady scroll */
export const WPM: Record<Speed, number> = { slow: 110, normal: 140, fast: 170 };
/** teleprompter text size in px */
export const SIZE_PX: Record<TextSize, number> = { s: 20, m: 26, l: 34 };

export interface RecPrefs {
  speed: Speed;
  size: TextSize;
  /** flip the teleprompter text for a glass (beam-splitter) prompter */
  mirrorText: boolean;
  /** show the preview like a mirror (the recording itself is never flipped) */
  mirrorPreview: boolean;
  /** clean the sound on this Mac when the take is used (denoise, de-echo, level) */
  studio: boolean;
  /** 3-2-1 before recording starts */
  countdown: boolean;
  /** read a script (true) or speak freely (false) */
  script: boolean;
}

export const DEFAULT_PREFS: RecPrefs = { speed: 'normal', size: 'm', mirrorText: false, mirrorPreview: true, studio: true, countdown: true, script: true };

const PREFS_KEY = 'rec.prefs';

/** Saved prefs (localStorage JSON) -> RecPrefs; anything unknown or of the wrong type falls back to the default. */
export function parsePrefs(raw: string | null | undefined): RecPrefs {
  let o: Record<string, unknown> = {};
  try {
    const v = raw ? JSON.parse(raw) : {};
    if (v && typeof v === 'object' && !Array.isArray(v)) o = v as Record<string, unknown>;
  } catch {
    o = {};
  }
  const pick = <T extends string>(v: unknown, ok: readonly T[], d: T): T => (ok.includes(v as T) ? (v as T) : d);
  const bool = (v: unknown, d: boolean) => (typeof v === 'boolean' ? v : d);
  const d = DEFAULT_PREFS;
  return {
    speed: pick(o.speed, ['slow', 'normal', 'fast'] as const, d.speed),
    size: pick(o.size, ['s', 'm', 'l'] as const, d.size),
    mirrorText: bool(o.mirrorText, d.mirrorText),
    mirrorPreview: bool(o.mirrorPreview, d.mirrorPreview),
    studio: bool(o.studio, d.studio),
    countdown: bool(o.countdown, d.countdown),
    script: bool(o.script, d.script),
  };
}

export function loadPrefs(): RecPrefs {
  try {
    return parsePrefs(localStorage.getItem(PREFS_KEY));
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(p: RecPrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* storage full / off: prefs just do not stick */
  }
}

/** The script text -> its lines (one per line, blank lines dropped). */
export function scriptLines(text: string): string[] {
  return text
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean);
}

/** Seconds a line takes at ``wpm`` (CJK: ~4 characters per "word"). */
export function lineSeconds(text: string, wpm = WPM.normal): number {
  const cjk = (text.match(/[\u3400-\u9fff]/g) ?? []).length;
  const words = text.replace(/[\u3400-\u9fff]/g, ' ').split(/\s+/).filter(Boolean).length + cjk / 4;
  return Math.max(1.2, (words / wpm) * 60);
}

/** About how long the script takes to read, in seconds. */
export function scriptSeconds(lines: string[], wpm = WPM.normal): number {
  return Math.round(lines.reduce((a, l) => a + lineSeconds(l, wpm), 0));
}

/** Why the big button cannot start now, or null when it can. Speaking freely needs no script. */
export function blockReason(o: { phase: Phase; useScript: boolean; lines: number; busy: boolean }): 'no-camera' | 'no-script' | 'busy' | null {
  if (o.phase === 'off') return 'no-camera';
  if (o.busy || o.phase === 'stopping') return 'busy';
  if (o.phase === 'ready' && o.useScript && o.lines === 0) return 'no-script';
  return null;
}

/** What a press of the big button (or Space) does in each phase. */
export function mainAction(phase: Phase, countdown: boolean): 'countdown' | 'start' | 'cancel' | 'stop' | null {
  if (phase === 'ready') return countdown ? 'countdown' : 'start';
  if (phase === 'countdown') return 'cancel';
  if (phase === 'recording' || phase === 'paused') return 'stop';
  return null;
}

export type KeyAction = 'main' | 'retake' | 'pause' | 'next' | 'prev' | null;

/** A keydown -> what it does. Typing in a field never triggers anything. */
export function keyAction(e: { key: string; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean; tag?: string; editable?: boolean }): KeyAction {
  if (e.tag === 'TEXTAREA' || e.tag === 'INPUT' || e.tag === 'SELECT' || e.editable) return null;
  const mod = !!(e.metaKey || e.ctrlKey);
  if (mod && e.key.toLowerCase() === 'r') return 'retake';
  if (mod || e.altKey) return null;
  if (e.key === ' ') return 'main';
  if (e.key.toLowerCase() === 'p') return 'pause';
  if (e.key === 'ArrowDown') return 'next';
  if (e.key === 'ArrowUp') return 'prev';
  return null;
}

/** The teleprompter after ``dt`` seconds at ``wpm``: -> {cur, progress, advanced} (stops at the end of the last line). */
export function scrollStep(o: { lines: string[]; cur: number; progress: number; dt: number; wpm: number }): { cur: number; progress: number; advanced: boolean } {
  if (!o.lines.length) return { cur: 0, progress: 0, advanced: false };
  const next = o.progress + o.dt / lineSeconds(o.lines[o.cur] ?? '', o.wpm);
  if (next < 1) return { cur: o.cur, progress: next, advanced: false };
  if (o.cur < o.lines.length - 1) return { cur: o.cur + 1, progress: 0, advanced: true };
  return { cur: o.cur, progress: 1, advanced: false };
}

/** A take as the list shows it. */
export interface Take {
  /** the recorder session id (its folder name) */
  id: string;
  dir: string;
  n: number;
  secs: number;
  /** lines reached (0 when speaking freely) */
  lines: number;
  total: number;
  retakes: number;
  thumb: string | null;
}

/** The take Finish uses: the chosen one if it still exists, else the newest. */
export function chosenTake(takes: Take[], chosen: string | null): Take | null {
  return takes.find((x) => x.id === chosen) ?? takes[0] ?? null;
}

/** A session slug from the title (a-z0-9-, 1-40 chars). */
export function slugOf(s: string | null | undefined): string {
  const v = (s ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
    .replace(/-+$/g, '');
  return v || 'recording';
}
