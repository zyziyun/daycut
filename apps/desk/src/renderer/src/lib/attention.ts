// Orca-style attention (2026-10 review step 8): the Dock badge is the Studio's Needs you count, a notification when a
// video starts waiting for her opens that video with its question, one when a run finishes opens its first clip.
import { useEffect, useRef } from 'react';
import { t } from '../i18n';
import { inboxTitle } from './inboxView';
import { needsYou, type StudioRow } from './studio';
import { rowHref, useStudioData } from './studioData';
import { useStudioEnabled } from './studioFlag';

/** What to tell her when the list changes: a video that starts waiting for her (its question), and a project whose
 * run finished (its first made clip). Pure: unit-tested. */
export function attentionChanges(before: StudioRow[] | null, after: StudioRow[]): { title: string; body: string; route: string }[] {
  if (!before) return [];
  // a question she has not been told about (rows also change shape as a project's clips load: keyed by the question)
  const told = new Set(before.flatMap((r) => (r.ask ? [r.ask.key] : [])));
  const out: { title: string; body: string; route: string }[] = [];
  for (const r of after) {
    if (r.group !== 'you' || !r.ask || told.has(r.ask.key)) continue;
    told.add(r.ask.key);
    out.push({ title: t('notify.st.you', { title: r.title || r.project || '' }), body: inboxTitle(r.ask), route: rowHref(r, true) });
  }
  // a project that was running and has stopped running with made clips: finished
  const ran = new Set(before.filter((r) => r.item && r.group === 'run' && r.tone === 'run').map((r) => r.item!));
  for (const item of ran) {
    const now = after.filter((r) => r.item === item);
    if (!now.length || now.some((r) => r.group === 'run' && r.tone === 'run')) continue;
    const made = now.filter((r) => r.kind === 'clip' && (r.group === 'ready' || r.group === 'scheduled'));
    if (!made.length) continue;
    out.push({ title: t('notify.st.done', { name: made[0].project ?? made[0].title }), body: t('notify.st.doneBody', { n: made.length }), route: rowHref(made[0]) });
  }
  return out;
}

/** The Dock badge (= the Studio's Needs you count) and the notifications, for the whole app. */
export function useStudioAttention() {
  const on = useStudioEnabled();
  const { rows, ready } = useStudioData();
  const n = on ? needsYou(rows) : 0;
  useEffect(() => {
    if (!on) return;
    void window.desk.setBadge?.(n)?.catch(() => undefined);
  }, [n, on]);
  useEffect(() => () => void window.desk.setBadge?.(0)?.catch(() => undefined), []);
  const prev = useRef<StudioRow[] | null>(null);
  useEffect(() => {
    if (!on || !ready) return;
    for (const x of attentionChanges(prev.current, rows)) void window.desk.notify?.(x.title, x.body, x.route)?.catch(() => undefined);
    prev.current = rows;
  }, [rows, on, ready]);
}
