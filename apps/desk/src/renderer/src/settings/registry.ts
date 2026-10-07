// The Settings sub-nav is a registry, so a feature can add its own section without touching the shell:
//
//   registerSettingsSection({ id: 'video', order: 25, label: () => t('nav.videoGen'), icon: Clapperboard,
//                             render: (ctx) => <VideoGenerationSettings onChange={ctx.onChange} /> });
//
// shows "Video generation" between AI (20) and Publishing (30) at #/settings/video. Built-in orders: General 10,
// AI 20, Publishing 30, Advanced 90. `dot` puts a status dot in the nav ('ok' green, 'warn' amber, 'error' red).
import { useSyncExternalStore, type ComponentType, type ReactNode } from 'react';
import type { SettingsMsg } from '../../../shared/deskApi';

export type Dot = 'ok' | 'warn' | 'error' | null;

export interface SettingsCtx {
  settings: SettingsMsg;
  /** save a patch (instant apply) and update the whole app */
  save: (patch: Parameters<typeof window.desk.setSettings>[0]) => Promise<SettingsMsg | null>;
  onChange: (s: SettingsMsg) => void;
  /** the rest of the route after the section id (#/settings/ai/jobs -> 'jobs') */
  sub?: string;
}

export interface SettingsSection {
  id: string;
  order: number;
  label: () => string;
  icon: ComponentType<{ className?: string }>;
  render: (ctx: SettingsCtx) => ReactNode;
  /** a hook: the nav dot for this section */
  useDot?: () => Dot;
  /** a hook: false hides the section (a feature behind a flag) */
  useVisible?: () => boolean;
  testId?: string;
}

let sections: SettingsSection[] = [];
const subs = new Set<() => void>();

export function registerSettingsSection(s: SettingsSection) {
  sections = [...sections.filter((x) => x.id !== s.id), s].sort((a, b) => a.order - b.order);
  subs.forEach((f) => f());
}

export function settingsSections(): SettingsSection[] {
  return sections;
}

export function useSettingsSections(): SettingsSection[] {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => sections,
  );
}
