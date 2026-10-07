// The week plan going on right now (engine weekplan.py), shared by Home and 发布: start one from dropped files, follow
// it (polled while it plans / makes, nudged by engine events), and the actions on it. Each action reloads.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { WeekPlan } from '../../../shared/weekPlan';
import { getLang, t } from '../i18n';
import { useEngine } from '../lib/engine';
import { errText } from '../v4/msg';
import { useUi } from '../v4/ui';
import { iso, weekStart } from '../publish/model';
import { useAccounts } from '../publish/usePublish';
import { useChannels } from '../v4/Channels';

/** The account's own usual post time per connected platform (no app defaults: the engine fills those per platform). */
export function usualTimes(accounts: ReturnType<typeof useAccounts>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const pf of accounts.connected) {
    const c = accounts.accountOf(pf);
    if (c?.times?.length) out[pf] = c.times[0];
  }
  return out;
}

export function useWeekPlan() {
  const { client, subscribe } = useEngine();
  const ui = useUi();
  const { adapters, channels } = useChannels();
  const accounts = useAccounts(adapters, channels);
  const [plans, setPlans] = useState<WeekPlan[] | null>(null);
  const [busy, setBusy] = useState(false);
  const uiRef = useRef(ui);
  uiRef.current = ui;

  const reload = useCallback(async () => {
    if (!client) return;
    try {
      setPlans((await client.weekPlans()).plans);
    } catch (e) {
      uiRef.current.toast(errText(e), { error: true });
    }
  }, [client]);
  useEffect(() => {
    void reload();
  }, [reload]);
  // planning / making: follow closely; review (waiting for her OK, maybe for hours): now and then
  const every = plans?.some((p) => p.state === 'planning' || p.state === 'making') ? 900 : plans?.some((p) => p.state === 'review') ? 4000 : 0;
  useEffect(() => {
    if (!every) return;
    const tm = setInterval(() => void reload(), every);
    return () => clearInterval(tm);
  }, [every, reload]);
  // approvals in the review / Inbox move a parked week on: those show up as batch / inbox events
  useEffect(() => subscribe((e) => void ((e.type === 'weekplan' || e.type === 'intake' || e.type === 'batches' || e.type === 'inbox') && reload())), [subscribe, reload]);

  const plan = plans?.[0] ?? null;

  const act = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      setBusy(true);
      try {
        return await fn();
      } catch (e) {
        ui.toast(errText(e), { error: true });
        return undefined;
      } finally {
        setBusy(false);
        void reload();
      }
    },
    [ui, reload],
  );

  const actions = useMemo(() => {
    const c = () => {
      if (!client) throw new Error('engine not running');
      return client;
    };
    const now = () => new Date();
    return {
      /** files / folders dropped (+ her words, optional) -> plan */
      start: (inputs: string[], text = '') =>
        act(() =>
          c().startWeekPlan({
            inputs,
            text,
            start: iso(weekStart(now())),
            today: iso(now()),
            platforms: accounts.connected,
            times: usualTimes(accounts),
            lang: getLang(),
          }),
        ),
      run: (id: string) => act(() => c().weekPlanAct(id, 'run')),
      reword: (id: string, text: string) => act(() => c().rewordWeekPlan(id, text, iso(now()))),
      dismiss: (id: string) =>
        act(async () => {
          const r = await c().weekPlanAct(id, 'dismiss');
          ui.toast(t('wp.putAwayDone'));
          return r;
        }),
      /** the one primary button: the previewed week goes on the board (undo = unschedule those posts) */
      confirm: (id: string, onUndo?: () => void) =>
        act(async () => {
          const r = await c().weekPlanAct(id, 'confirm');
          const ids = r.ids ?? [];
          ui.toast(t('wp.scheduled', { n: ids.length }), {
            undo: async () => {
              await c().unscheduleMany(ids);
              onUndo?.();
            },
          });
          return r;
        }),
    };
  }, [client, act, accounts, ui]);

  return { plan, plans, busy, reload, actions, accounts };
}
