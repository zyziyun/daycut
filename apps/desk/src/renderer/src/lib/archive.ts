// Project archive (全部项目 › 归档 / 已归档): which projects a filter shows, the archive / restore flows with their undo
// toasts, and the archived date line. Nothing on disk is ever deleted; a running project is never archived.
import type { HistoryItem } from '../../../shared/v02';
import { fmtDate, t, tk } from '../i18n';

export type ProjectsFilter = 'all' | 'running' | 'you' | 'done' | 'failed' | 'archived';

export interface ShownOpts {
  f: ProjectsFilter;
  q: string;
  type: string;
  /** the status bucket of a live item ('all' / 'archived' do not use it) */
  bucketOf: (i: HistoryItem) => string;
  /** agency mode's client filter */
  clientOk?: (i: HistoryItem) => boolean;
  /** search the client name too (agency mode) */
  searchClient?: boolean;
}

/** The cards a filter shows: Archived reads the archived list, every other tab the live one; search / type / client
 * filters work the same in both. */
export function shownProjects(items: HistoryItem[], archived: HistoryItem[], o: ShownOpts): HistoryItem[] {
  const src = o.f === 'archived' ? archived : items;
  const ql = o.q.toLowerCase();
  return src.filter(
    (i) =>
      (o.f === 'all' || o.f === 'archived' || o.bucketOf(i) === o.f) &&
      (!o.type || (i.type ?? 'other') === o.type) &&
      (!o.clientOk || o.clientOk(i)) &&
      (!ql || `${i.name} ${i.recipe ?? ''} ${o.searchClient ? (i.client ?? '') : ''}`.toLowerCase().includes(ql)),
  );
}

/** The empty state of a filter that shows nothing: the search text when there is one, else what is missing
 * ("No running projects"), never a key. */
export function noMatchText(o: Pick<ShownOpts, 'f' | 'q' | 'type'>): string {
  const q = o.q.trim();
  if (q) return t('projects.noMatch', { q });
  if (o.f === 'all' && o.type) return t('projects.none.type', { type: tk(`type.${o.type}`) });
  return t(`projects.none.${o.f}`);
}

/** A run is going (the engine refuses to archive it; the UI says so before asking). */
export function isRunning(i: HistoryItem): boolean {
  return i.live?.state === 'running' || !!i.pilot;
}

/** "Archived Oct 3" (or plain "Archived" for an entry an older desk hid). */
export function archivedLine(i: Pick<HistoryItem, 'archived_at'>): string {
  return i.archived_at ? t('projects.archivedOn', { date: fmtDate(i.archived_at) }) : t('projects.archivedNoDate');
}

export interface ArchiveClient {
  archiveHistory(dirs: string[]): Promise<unknown>;
  restoreHistory(dirs: string[]): Promise<unknown>;
}
export interface ArchiveUi {
  toast(text: string, opts?: { undo?: () => unknown; error?: boolean }): void;
}

/** Archive -> toast 「已归档 N · 撤销」 (undo = restore). A running project is refused with a clear line (nothing
 * archived, the run untouched). -> whether anything was archived. */
export async function archiveFlow(client: ArchiveClient, ui: ArchiveUi, list: HistoryItem[], reload: () => void): Promise<boolean> {
  if (!list.length) return false;
  const busy = list.find(isRunning);
  if (busy) {
    ui.toast(t('projects.archiveRunning', { name: busy.name }), { error: true });
    return false;
  }
  const dirs = list.map((i) => i.dir);
  try {
    await client.archiveHistory(dirs);
  } catch (e) {
    ui.toast((e as Error).message, { error: true }); // the engine's own guard (a run started meanwhile)
    return false;
  }
  reload();
  ui.toast(`${t('projects.archivedN', { n: list.length })} ${t('projects.archiveHint')}`, {
    undo: async () => {
      await client.restoreHistory(dirs);
      reload();
    },
  });
  return true;
}

/** Restore -> toast 「已恢复 N · 撤销」 (undo = archive again). */
export async function restoreFlow(client: ArchiveClient, ui: ArchiveUi, list: HistoryItem[], reload: () => void): Promise<boolean> {
  if (!list.length) return false;
  const dirs = list.map((i) => i.dir);
  try {
    await client.restoreHistory(dirs);
  } catch (e) {
    ui.toast((e as Error).message, { error: true });
    return false;
  }
  reload();
  ui.toast(t('projects.restoredN', { n: list.length }), {
    undo: async () => {
      await client.archiveHistory(dirs);
      reload();
    },
  });
  return true;
}
