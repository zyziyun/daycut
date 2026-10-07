// The clip editor's layout (ux/text-edit §2.1): the player / lower pane split (presets 70 / 50 / 34 % for the player:
// ⌘1 watch, ⌘2 balanced (default), ⌘3 edit), divider drag with min sizes (player 240 px, lower pane 180 px) and
// double-click back to balanced; the AI column's width (320-560 px) and collapsed state (⌘\, auto under 1280 px);
// the lower pane's tab. Saved on this Mac for every clip (localStorage `ce.layout`; the old `ce.chatW` is read once).
import { useCallback, useEffect, useRef, useState } from 'react';

export type Preset = 'watch' | 'balanced' | 'edit';
export type LowerTab = 'transcript' | 'timeline';

export interface Layout {
  stage: number;
  preset: Preset | null;
  tab: LowerTab | null;
  chatW: number;
  chatCollapsed: boolean;
}

export const PRESETS: Record<Preset, number> = { watch: 0.7, balanced: 0.5, edit: 0.34 };
export const MIN_STAGE = 240;
export const MIN_LOWER = 180;
export const CHAT_MIN = 320;
export const CHAT_MAX = 560;
export const CHAT_RAIL = 48;
export const NARROW = 1280;
const KEY = 'ce.layout';

export const DEFAULT_LAYOUT: Layout = { stage: PRESETS.balanced, preset: 'balanced', tab: null, chatW: 400, chatCollapsed: false };

export function clampChat(w: number): number {
  return Math.round(Math.min(CHAT_MAX, Math.max(CHAT_MIN, w)));
}

/** The player's share for a container height, kept inside the min sizes (both panes stay usable). */
export function clampStage(frac: number, height: number): number {
  if (!height || height < MIN_STAGE + MIN_LOWER) return Math.min(0.85, Math.max(0.15, frac));
  const lo = MIN_STAGE / height;
  const hi = 1 - MIN_LOWER / height;
  return Math.min(hi, Math.max(lo, frac));
}

/** Which preset a fraction is (within 2 %), else null (a dragged size). */
export function presetOf(frac: number): Preset | null {
  for (const [k, v] of Object.entries(PRESETS) as [Preset, number][]) if (Math.abs(v - frac) < 0.02) return k;
  return null;
}

export function loadLayout(store: Pick<Storage, 'getItem'> = localStorage): Layout {
  let saved: Partial<Layout>;
  try {
    saved = JSON.parse(store.getItem(KEY) ?? '{}') as Partial<Layout>;
  } catch {
    saved = {};
  }
  const legacy = Number(store.getItem('ce.chatW'));
  const out: Layout = { ...DEFAULT_LAYOUT, ...saved };
  if (saved.chatW == null && legacy) out.chatW = legacy;
  out.chatW = clampChat(Number(out.chatW) || DEFAULT_LAYOUT.chatW);
  out.stage = Number.isFinite(out.stage) ? Math.min(0.85, Math.max(0.15, out.stage)) : DEFAULT_LAYOUT.stage;
  if (out.preset && !(out.preset in PRESETS)) out.preset = presetOf(out.stage);
  if (out.tab !== 'transcript' && out.tab !== 'timeline') out.tab = null;
  out.chatCollapsed = !!out.chatCollapsed;
  return out;
}

export function saveLayout(l: Layout, store: Pick<Storage, 'setItem'> = localStorage) {
  store.setItem(KEY, JSON.stringify(l));
}

export function useSplit() {
  const [layout, setLayout] = useState<Layout>(() => loadLayout());
  const [height, setHeight] = useState(0);
  const [winW, setWinW] = useState(() => (typeof window !== 'undefined' ? window.innerWidth : 1440));
  // under 1280 px the AI column folds by itself; opening it there sticks for this window only
  const [forceOpen, setForceOpen] = useState(false);
  const box = useRef<HTMLElement | null>(null);
  useEffect(() => saveLayout(layout), [layout]);
  useEffect(() => {
    const on = () => setWinW(window.innerWidth);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  const ro = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    ro.current?.disconnect();
    ro.current = null;
    box.current = el;
    if (!el) return;
    setHeight(el.clientHeight);
    ro.current = new ResizeObserver(() => setHeight(el.clientHeight));
    ro.current.observe(el);
  }, []);
  const narrow = winW < NARROW;
  const collapsed = layout.chatCollapsed || (narrow && !forceOpen);
  const stage = clampStage(layout.stage, height);
  const setPreset = useCallback((p: Preset) => setLayout((l) => ({ ...l, stage: PRESETS[p], preset: p })), []);
  const setStage = useCallback((f: number) => setLayout((l) => ({ ...l, stage: f, preset: presetOf(f) })), []);
  const setTab = useCallback((tab: LowerTab) => setLayout((l) => ({ ...l, tab })), []);
  const setChatW = useCallback((w: number) => setLayout((l) => ({ ...l, chatW: clampChat(w) })), []);
  const toggleChat = useCallback(() => {
    if (collapsed) {
      setLayout((l) => ({ ...l, chatCollapsed: false }));
      if (narrow) setForceOpen(true);
    } else {
      setLayout((l) => ({ ...l, chatCollapsed: true }));
      setForceOpen(false);
    }
  }, [collapsed, narrow]);
  /** Open the AI column if it is folded (by ⌘\ or because the window is narrow): anything that opens a card there
   * (Export, /, a marker) must be visible, not land in a folded column. */
  const openChat = useCallback(() => {
    if (!collapsed) return;
    setLayout((l) => ({ ...l, chatCollapsed: false }));
    if (narrow) setForceOpen(true);
  }, [collapsed, narrow]);
  /** pointer-drag on the divider (pointer capture), clamped to the min sizes */
  const dragDivider = useCallback(
    (e: React.PointerEvent) => {
      const el = box.current;
      if (!el) return;
      e.preventDefault();
      const top = el.getBoundingClientRect().top;
      const h = el.clientHeight;
      const target = e.currentTarget as HTMLElement;
      target.setPointerCapture?.(e.pointerId);
      target.classList.add('on');
      const mv = (ev: PointerEvent) => setStage(clampStage((ev.clientY - top) / h, h));
      const up = () => {
        target.classList.remove('on');
        window.removeEventListener('pointermove', mv);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', mv);
      window.addEventListener('pointerup', up);
    },
    [setStage],
  );
  return { layout, stage, height, collapsed, narrow, ref, setPreset, setStage, setTab, setChatW, toggleChat, openChat, dragDivider, reset: () => setPreset('balanced') };
}
