// Publish board state + every create / read / update / delete action, each with one undo (toast).
import { useCallback, useMemo } from 'react';
import type { CalendarPost, NewPost } from '../../../shared/v04';
import type { ChannelMsg } from '../../../shared/channels';
import type { Adapter } from '../../../shared/publish/adapterSchema';
import { PLATFORM_IDS } from '../../../shared/platforms';
import { fmtDate, t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { errText } from '../v4/msg';
import { useUi } from '../v4/ui';
import { base, type PostGroup } from './model';

/** Default post time per platform when nothing else says (a convention, editable per post). */
export const SLOT_TIME: Record<string, string> = { x: '09:00', instagram: '18:00', 'wechat-channels': '12:00' };

export interface Accounts {
  /** the platforms she posts to, in the shared platform order: the ones she chose ("Platforms for new projects");
   * before she chose any, the ones she has a publishing account for */
  connected: string[];
  /** every platform an adapter can post (for "+ Add platform") */
  all: string[];
  timeOf: (pf: string) => string;
  accountOf: (pf: string) => ChannelMsg | undefined;
  adapterOf: (pf: string) => Adapter | undefined;
}

export function useAccounts(adapters: Adapter[], channels: ChannelMsg[], chosen: string[] | null = null): Accounts {
  return useMemo(() => {
    const adapterOf = (pf: string) => adapters.find((a) => a.packagePlatforms.includes(pf));
    const order = (a: string, b: string) => PLATFORM_IDS.indexOf(a) - PLATFORM_IDS.indexOf(b);
    const withAccount = [...new Set(adapters.filter((a) => channels.some((c) => c.adapterId === a.id)).map((a) => a.packagePlatforms[0]))];
    const connected = (chosen?.length ? [...new Set(chosen.map(base))] : withAccount).sort(order);
    const all = [...new Set(adapters.flatMap((a) => a.packagePlatforms))].sort(order);
    const accountOf = (pf: string) => {
      const a = adapterOf(base(pf));
      return a ? channels.find((c) => c.adapterId === a.id) : undefined;
    };
    const timeOf = (pf: string) => {
      const a = adapterOf(base(pf));
      const c = a && channels.find((x) => x.adapterId === a.id && x.times.length);
      return c?.times[0] ?? SLOT_TIME[base(pf)] ?? '19:00';
    };
    return { connected, all, timeOf, accountOf, adapterOf: (pf: string) => adapterOf(base(pf)) };
  }, [adapters, channels, chosen]);
}

export function usePublishData() {
  const { client } = useEngine();
  const ui = useUi();
  const cal = useLoad((c) => c.calendar(), []);
  const { reload } = cal;

  const run = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      try {
        return await fn();
      } catch (e) {
        ui.toast(errText(e), { error: true });
        return undefined;
      } finally {
        reload();
      }
    },
    [ui, reload],
  );

  const actions = useMemo(() => {
    const c = () => {
      if (!client) throw new Error('engine not running');
      return client;
    };
    const undoAdd = (ids: string[]) => async () => {
      await c().unscheduleMany(ids);
      reload();
    };
    return {
      /** new posts (drag from the queue, an empty slot, duplicate, NL apply, platform on) - one undo */
      add: (posts: NewPost[], msg?: string) =>
        run(async () => {
          if (!posts.length) return undefined;
          const r = await c().scheduleMany(posts);
          ui.toast(msg ?? t('pb.t.scheduled', { date: fmtDate(`${posts[0].at.slice(0, 10)}T12:00`, { weekday: 'short', month: 'short', day: 'numeric' }) }), { undo: undoAdd(r.ids) });
          return r;
        }),
      /** move a whole card (every platform keeps its own time) */
      moveGroup: (g: PostGroup, day: string) =>
        run(async () => {
          if (g.day === day) return;
          const before = g.posts.map((p) => [p.id, p.at] as const);
          for (const p of g.posts) await c().updatePost(p.id, { at: `${day}${p.at.slice(10)}` });
          ui.toast(t('pb.t.moved', { date: fmtDate(`${day}T12:00`, { weekday: 'short', month: 'short', day: 'numeric' }) }), {
            undo: async () => {
              for (const [id, at] of before) await c().updatePost(id, { at });
              reload();
            },
          });
        }),
      /** date and / or time for a card (time: every switched-on platform gets it) */
      retime: (g: PostGroup, day: string, time?: string) =>
        run(async () => {
          const before = g.posts.map((p) => [p.id, p.at] as const);
          for (const p of g.posts) {
            const at = `${day}T${time && p.enabled !== false ? time : p.at.slice(11, 16)}`;
            if (at !== p.at) await c().updatePost(p.id, { at });
          }
          ui.toast(t('pb.t.moved', { date: fmtDate(`${day}T${time ?? g.time}`, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) }), {
            undo: async () => {
              for (const [id, at] of before) await c().updatePost(id, { at });
              reload();
            },
          });
        }),
      setPostTime: (p: CalendarPost, time: string) => run(() => c().updatePost(p.id, { at: `${p.at.slice(0, 10)}T${time}` })),
      /** back to the queue: calendar rows only, never files */
      unschedule: (g: PostGroup) =>
        run(async () => {
          const r = await c().unscheduleMany(g.posts.map((p) => p.id));
          ui.toast(t('pb.t.unscheduled', { title: g.title, project: g.project ?? '' }), {
            undo: async () => {
              await c().restorePosts(r.removed);
              reload();
            },
          });
        }),
      togglePlatform: (g: PostGroup, pf: string, on: boolean, at: string, name: string) =>
        run(async () => {
          const row = g.posts.find((p) => base(p.platform) === pf);
          if (row) {
            await c().updatePost(row.id, { enabled: on });
            ui.toast(t(on ? 'pb.t.platformOn' : 'pb.t.platformOff', { pf: name }), {
              undo: async () => {
                await c().updatePost(row.id, { enabled: !on });
                reload();
              },
            });
          } else if (on) {
            const r = await c().scheduleMany([{ item: g.item, clip: g.clip, platform: pf, at }]);
            ui.toast(t('pb.t.platformOn', { pf: name }), { undo: undoAdd(r.ids) });
          }
        }),
      caption: (p: CalendarPost, text: string | null) => run(() => c().updatePost(p.id, { caption: text })),
      /** the card's title, on every row of the card (a platform's own title still wins there) - one undo */
      retitle: (g: PostGroup, title: string) =>
        run(async () => {
          const rows = g.posts.filter((p) => p.title !== title);
          if (!rows.length) return;
          const before = rows.map((p) => [p.id, p.title] as const);
          for (const p of rows) await c().updatePost(p.id, { title });
          ui.toast(t('pl.t.retitled'), {
            undo: async () => {
              for (const [id, tt] of before) await c().updatePost(id, { title: tt });
              reload();
            },
          });
        }),
      /** one platform's own title (null: back to the card's title) */
      postTitle: (p: CalendarPost, title: string | null) => run(() => c().updatePost(p.id, { platform_title: title })),
      setState: (p: CalendarPost, state: CalendarPost['state']) => run(() => c().updatePost(p.id, { state })),
      stats: (p: CalendarPost, stats: { views?: number; likes?: number }) => run(() => c().updatePost(p.id, { stats })),
      fillWeek: (start: string, platforms: string[], times: Record<string, string>, clips?: { item: string; clip: string }[]) =>
        run(async () => {
          const r = await c().fillWeek({ start, platforms, times, clips });
          if (!r.ids.length) ui.toast(t(r.reason === 'no_free_days' ? 'pb.fill.no_free_days' : 'pb.fill.no_clips'));
          else ui.toast(t('pb.fill.done', { n: new Set(r.posts.map((p) => p.at.slice(0, 10))).size }), { undo: undoAdd(r.ids) });
          return r;
        }),
      confirm: (start: string) =>
        run(async () => {
          const r = await c().confirmWeek(start);
          ui.toast(t('pub.confirmed', { n: r.ready }));
        }),
    };
  }, [client, run, ui, reload]);

  return { ...cal, actions, client };
}
