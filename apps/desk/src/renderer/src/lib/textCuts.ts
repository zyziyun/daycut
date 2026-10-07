// Pending transcript cuts of one clip (ux/text-edit §2.2): word indices + tightened pauses, with their own undo /
// redo stack (⌘Z undoes a pending cut before it touches the engine's steps). Kept on this Mac per clip (localStorage),
// so leaving the clip, closing the window or restarting keeps them; Apply turns them into one engine step and clears them.
import { useCallback, useEffect, useState } from 'react';
import { EMPTY_DRAFTS, type Drafts } from './transcript';

interface Stored {
  cur: Drafts;
  undo: Drafts[];
  redo: Drafts[];
}

const MAX = 100;

export function draftKey(item: string, clip: string): string {
  return `ce.drafts.${item}/${clip}`;
}

export function loadDrafts(key: string, store: Pick<Storage, 'getItem'> = localStorage): Stored {
  try {
    const v = JSON.parse(store.getItem(key) ?? 'null') as Stored | null;
    if (v && v.cur && typeof v.cur.words === 'object' && Array.isArray(v.cur.gaps)) return { cur: v.cur, undo: v.undo ?? [], redo: v.redo ?? [] };
  } catch {
    /* a broken entry starts empty */
  }
  return { cur: EMPTY_DRAFTS, undo: [], redo: [] };
}

/** The reducer behind useTextCuts (pure, unit-tested): set / undo / redo / clear. */
export function step(s: Stored, a: { kind: 'set'; next: Drafts } | { kind: 'undo' } | { kind: 'redo' } | { kind: 'clear' }): Stored {
  if (a.kind === 'set') return JSON.stringify(a.next) === JSON.stringify(s.cur) ? s : { cur: a.next, undo: [...s.undo, s.cur].slice(-MAX), redo: [] };
  if (a.kind === 'undo') return s.undo.length ? { cur: s.undo[s.undo.length - 1], undo: s.undo.slice(0, -1), redo: [...s.redo, s.cur] } : s;
  if (a.kind === 'redo') return s.redo.length ? { cur: s.redo[s.redo.length - 1], undo: [...s.undo, s.cur], redo: s.redo.slice(0, -1) } : s;
  return { cur: EMPTY_DRAFTS, undo: [], redo: [] };
}

export function useTextCuts(key: string) {
  const [box, setBox] = useState<{ key: string; s: Stored }>(() => ({ key, s: loadDrafts(key) }));
  // another clip: its own pending cuts (never the previous clip's written under the new key)
  const s = box.key === key ? box.s : loadDrafts(key);
  useEffect(() => {
    if (box.key !== key) setBox({ key, s: loadDrafts(key) });
  }, [key, box.key]);
  useEffect(() => {
    if (box.key !== key) return;
    const v = box.s;
    const empty = !Object.keys(v.cur.words).length && !v.cur.gaps.length && !v.undo.length;
    if (empty) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify({ ...v, undo: v.undo.slice(-20), redo: v.redo.slice(-20) }));
  }, [box, key]);
  const apply = useCallback((a: Parameters<typeof step>[1]) => setBox((b) => ({ key: b.key, s: step(b.s, a) })), []);
  const set = useCallback((f: (d: Drafts) => Drafts) => setBox((b) => ({ key: b.key, s: step(b.s, { kind: 'set', next: f(b.s.cur) }) })), []);
  const undo = useCallback(() => apply({ kind: 'undo' }), [apply]);
  const redo = useCallback(() => apply({ kind: 'redo' }), [apply]);
  const clear = useCallback(() => apply({ kind: 'clear' }), [apply]);
  return { drafts: s.cur, set, undo, redo, clear, canUndo: s.undo.length > 0, canRedo: s.redo.length > 0 };
}
