// 发布 = direction A of ux/publish-redesign: a week board (one card per clip per slot) with the clips still to
// schedule on the left, one sentence to schedule many, a drawer for one card, month and data views. One layer you
// see, one layer you open; one primary button per screen (Confirm n posts, or Apply while a plan is previewed).
import { useCallback, useMemo, useRef, useState } from 'react';
import { Check, ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import type { SchedulePlan } from '../../../shared/v04';
import { fmtDate, fmtList, t } from '../i18n';
import { href } from '../lib/router';
import { useChannels, useChosenPlatforms } from '../v4/Channels';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { Seg } from '../v4/kit';
import { errText } from '../v4/msg';
import { useUi } from '../v4/ui';
import { MonthGrid, SlotPicker, WeekGrid, type DragData, type Proposed } from './Board';
import { DataView } from './DataView';
import { PostDrawer } from './Drawer';
import { addDays, base, groupPosts, iso, sortIds, weekStart, type PostGroup } from './model';
import { DueBanner } from './DueBanner';
import { NlBar } from './NlBar';
import { PublishOnboarding } from './Onboarding';
import { clipKey, QueuePanel } from './Queue';
import { useAccounts, usePublishData } from './usePublish';
import './publish.css';

type View = 'week' | 'month' | 'data';

function load<T extends string>(k: string, ok: readonly T[], d: T): T {
  try {
    const v = localStorage.getItem(k) as T | null;
    return v && ok.includes(v) ? v : d;
  } catch {
    return d;
  }
}
function save(k: string, v: string) {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* private mode */
  }
}

export function PublishBoard() {
  const ui = useUi();
  const { data, actions, client, reload } = usePublishData();
  const { adapters, channels, reload: reloadChannels } = useChannels();
  const chosen = useChosenPlatforms();
  const accounts = useAccounts(adapters, channels, chosen);
  const [view, setViewS] = useState<View>(() => load('pb.view', ['week', 'month', 'data'] as const, 'week'));
  const setView = (v: View) => (setViewS(v), save('pb.view', v));
  const [off, setOff] = useState(0);
  const [filter, setFilterS] = useState<string>(() => localStorage.getItem('pb.filter') ?? 'all');
  const setFilter = (v: string) => (setFilterS(v), save('pb.filter', v));
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [nl, setNl] = useState('');
  const [plan, setPlan] = useState<SchedulePlan | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [pick, setPick] = useState<{ day: string; time: string; x: number; y: number } | null>(null);
  const nlRef = useRef<HTMLInputElement>(null);

  const now = new Date();
  const today = iso(now);
  const start = useMemo(() => weekStart(new Date(), off), [off]);
  const month = useMemo(() => new Date(now.getFullYear(), now.getMonth() + off, 1), [off]); // eslint-disable-line react-hooks/exhaustive-deps
  const planWeek = plan?.ok ? weekStart(new Date(`${plan.start}T12:00`)) : null;
  const shownStart = planWeek ?? start;
  const days = useMemo(() => Array.from({ length: 7 }, (_, k) => addDays(shownStart, k)), [shownStart]);
  const range: [string, string] = view === 'month' ? [iso(month), iso(new Date(month.getFullYear(), month.getMonth() + 1, 0))] : [iso(days[0]), iso(days[6])];

  const posts = useMemo(() => data?.posts ?? [], [data]);
  const queue = useMemo(() => data?.queue ?? [], [data]);
  const known = sortIds([...new Set([...accounts.connected, ...posts.filter((p) => p.at.slice(0, 10) >= range[0] && p.at.slice(0, 10) <= range[1]).map((p) => base(p.platform))])]);
  const activeFilter = filter !== 'all' && known.includes(filter) ? filter : 'all';
  const targets = activeFilter === 'all' ? accounts.connected : [activeFilter];
  const allGroups = useMemo(() => groupPosts(posts, accounts.connected), [posts, accounts.connected]);
  const inRange = allGroups.filter((g) => g.day >= range[0] && g.day <= range[1]);
  const groups = activeFilter === 'all' ? inRange : inRange.filter((g) => g.platforms.includes(activeFilter) || g.posts.some((p) => base(p.platform) === activeFilter));
  const open = openKey ? allGroups.find((g) => g.key === openKey) ?? null : null;
  const look = inRange.filter((g) => g.warnings.length).length;
  const toConfirm = inRange.filter((g) => g.on.some((p) => p.state === 'planned')).length;
  const freeTime = targets.length ? accounts.timeOf(targets[0]) : null;
  const countOn = (pf: string) => inRange.reduce((n, g) => n + g.on.filter((p) => base(p.platform) === pf).length, 0);
  const noAccounts = data !== null && channels.length === 0 && adapters.length > 0;

  const proposed: Proposed[] | null = plan?.ok
    ? Object.values(
        plan.drafts.reduce<Record<string, Proposed>>((acc, d) => {
          const k = `${d.item}/${d.clip}/${d.at.slice(0, 10)}`;
          const p = (acc[k] ??= { key: `p:${k}`, day: d.at.slice(0, 10), time: d.at.slice(11, 16), title: d.title ?? d.clip, cover: d.cover ?? null, platforms: [] });
          if (!p.platforms.includes(base(d.platform))) p.platforms.push(base(d.platform));
          if (d.at.slice(11, 16) < p.time) p.time = d.at.slice(11, 16);
          return acc;
        }, {}),
      )
    : null;
  const offDays = new Set(plan?.ok ? days.filter((d) => !(plan.days ?? []).includes((d.getDay() + 6) % 7)).map(iso) : []);

  const times = useCallback(() => Object.fromEntries(accounts.connected.map((pf) => [pf, accounts.timeOf(pf)])), [accounts]);
  const selClips = () => selected.map((k) => queue.find((q) => clipKey(q) === k)).filter(Boolean).map((q) => ({ item: q!.item, clip: q!.clip }));

  const onDrop = (day: string, d: DragData) => {
    if ('group' in d) {
      const g = allGroups.find((x) => x.key === d.group);
      if (g) void actions.moveGroup(g, day);
    } else if (targets.length) {
      void actions.add(targets.map((pf) => ({ item: d.item, clip: d.clip, platform: pf, at: `${day}T${accounts.timeOf(pf)}` })));
    } else ui.toast(t('pb.q.needPlatform'));
  };
  const preview = async () => {
    if (!client || !nl.trim()) return;
    setPlanBusy(true);
    try {
      const p = await client.planSchedule({ text: nl.trim(), start: iso(start), today, platforms: targets.length ? targets : accounts.connected, times: times(), clips: selected.length ? selClips() : undefined });
      setPlan(p);
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setPlanBusy(false);
    }
  };
  const apply = async () => {
    if (!plan?.ok) return;
    const r = await actions.add(
      plan.drafts.map((d) => ({ item: d.item, clip: d.clip, platform: d.platform, at: d.at })),
      t('pb.nl.applied', { n: plan.drafts.length }),
    );
    if (r) {
      const w = weekStart(new Date(`${plan.start}T12:00`));
      setOff(Math.round((w.getTime() - weekStart(new Date()).getTime()) / (7 * 86400000)));
      setPlan(null);
      setNl('');
      setSelected([]);
    }
  };
  const fill = () => void actions.fillWeek(iso(start), targets, times(), selected.length ? selClips() : undefined).then((r) => r?.ids.length && setSelected([]));
  const scheduleSel = (e: React.MouseEvent) =>
    ui.menu(e, [
      { label: t('pb.q.fill'), run: fill, testId: 'pb-sel-fill' },
      { label: t('pb.nl.ph'), run: () => nlRef.current?.focus(), testId: 'pb-sel-nl' },
    ]);

  const subtitle = () => {
    if (view === 'data') return <span>{t('pb.sub.data')}</span>;
    if (plan?.ok) return <span>{t('pb.sub.range', { n: inRange.length, range: `${fmtDate(days[0])} – ${fmtDate(days[6])}` })} · {t('pb.sub.waiting', { n: queue.length })}</span>;
    if (!posts.length) return <span>{t('pb.sub.nothing', { n: queue.length })}</span>;
    const main =
      view === 'month'
        ? t('pb.sub.month', { n: inRange.length, month: fmtDate(month, { month: 'long' }) })
        : off === 0
          ? t('pb.sub.this', { n: inRange.length })
          : off === 1
            ? t('pb.sub.next', { n: inRange.length })
            : t('pb.sub.range', { n: inRange.length, range: `${fmtDate(days[0])} – ${fmtDate(days[6])}` });
    return (
      <span>
        {main}
        {look > 0 && (
          <>
            {' · '}
            <b className="pb-amber" data-testid="pb-look">
              {t('pb.sub.look', { n: look })}
            </b>
          </>
        )}
      </span>
    );
  };

  return (
    <div className="scroll pb" data-testid="calendar">
      <div className="pb-page">
        <header className="pb-header">
          <div>
            <h1>{t('pub.title')}</h1>
            <p data-testid="pb-sub">{subtitle()}</p>
          </div>
          <span className="sp" />
          <Seg
            value={view}
            onChange={(v) => (setView(v), setOff(0), setPlan(null))}
            options={[
              { v: 'week', label: t('pub.week') },
              { v: 'month', label: t('pub.month') },
              { v: 'data', label: t('pub.data') },
            ]}
            testId="pb-view"
          />
          {accounts.connected.length ? (
            <a className="pb-acc" href={href({ name: 'channels' })} data-testid="pub-accounts" data-tip={t('pb.accountsHint')}>
              <span className="pb-pfs tight">
                {accounts.connected.slice(0, 4).map((p) => (
                  <PlatformIcon key={p} id={p} size={20} />
                ))}
              </span>
              {t('pb.accounts', { n: channels.length })}
            </a>
          ) : (
            <a className="btn" href={href({ name: 'channels' })} data-testid="pub-accounts">
              {t('pb.connect')}
            </a>
          )}
          {view !== 'data' && !plan && toConfirm > 0 && (
            <button className="btn primary lg" onClick={() => void actions.confirm(iso(view === 'month' ? weekStart(new Date()) : start))} data-testid="pub-confirm" title={t('pb.confirmHint')}>
              <Check className="ico" />
              {t('pb.confirm', { n: toConfirm })}
            </button>
          )}
        </header>

        <DueBanner />
        {view !== 'data' && (
          <NlBar ref={nlRef} text={nl} setText={setNl} busy={planBusy} plan={plan} onPreview={() => void preview()} onApply={() => void apply()} onCancel={() => setPlan(null)} />
        )}

        {view === 'data' ? (
          <DataView posts={posts} actions={actions} />
        ) : (
          <div className="pb-cols">
            <QueuePanel
              queue={queue}
              canFill={targets.length > 0}
              fillHint={t('pb.q.fillHint', { platforms: fmtList(targets.map(platformName)) })}
              selected={selected}
              setSelected={setSelected}
              onFill={fill}
              onSchedule={scheduleSel}
              onDropBack={(d) => {
                const g = 'group' in d ? allGroups.find((x) => x.key === d.group) : undefined;
                if (g) void actions.unschedule(g);
              }}
            />
            <section className="pb-board">
              <div className="pb-tools">
                <button className="btn icon" onClick={() => (setOff(off - 1), setPlan(null))} aria-label={t('pub.prev')} data-tip={t('pub.prev')} data-testid="pb-prev">
                  <ChevronLeft className="ico" />
                </button>
                <button className="btn icon" onClick={() => (setOff(off + 1), setPlan(null))} aria-label={t('pub.next')} data-tip={t('pub.next')} data-testid="pb-next">
                  <ChevronRight className="ico" />
                </button>
                <b className="pb-range num" data-testid="pb-range">
                  {view === 'month' ? fmtDate(month, { month: 'long', year: 'numeric' }) : `${fmtDate(days[0], { month: 'short', day: 'numeric' })} – ${days[6].getMonth() === days[0].getMonth() ? days[6].getDate() : fmtDate(days[6], { month: 'short', day: 'numeric' })}`}
                </b>
                <button className="btn" onClick={() => (setOff(0), setPlan(null))} disabled={off === 0 && !planWeek} data-testid="pb-today">
                  {t('pub.today')}
                </button>
                <span className="sp" />
                {!noAccounts && (
                  <div className="pb-filter" data-testid="pub-platforms">
                    <button className={activeFilter === 'all' ? 'on' : ''} onClick={() => setFilter('all')} data-pf="all">
                      {t('pb.all')}
                    </button>
                    {known.map((pf) => (
                      <button key={pf} className={activeFilter === pf ? 'on' : ''} aria-pressed={activeFilter === pf} onClick={() => setFilter(pf)} data-pf={pf} title={t('pb.filterHint', { name: platformName(pf) })}>
                        <PlatformIcon id={pf} size={18} />
                        {platformName(pf)}
                        <span className="n num">{countOn(pf)}</span>
                      </button>
                    ))}
                    <a className="add" href={href({ name: 'channels' })} title={t('pb.addHint')} data-testid="pb-add-platform">
                      <Plus className="ico" />
                      {t('pb.add')}
                    </a>
                  </div>
                )}
              </div>
              {!adapters.length || !data ? (
                <div className="pb-loading" aria-busy="true" />
              ) : noAccounts ? (
                <PublishOnboarding adapters={adapters} onDone={() => void reloadChannels()} />
              ) : view === 'month' ? (
                <MonthGrid month={month} today={today} groups={groups} freeTime={freeTime} onOpen={(g) => setOpenKey(g.key)} onDrop={onDrop} onFree={(day, e) => setPick({ day, time: freeTime ?? '19:00', x: e.clientX, y: e.clientY })} />
              ) : (
                <WeekGrid
                  days={days}
                  today={today}
                  groups={groups}
                  proposed={proposed}
                  offDays={offDays}
                  selected={openKey}
                  freeTime={freeTime}
                  onOpen={(g: PostGroup) => setOpenKey(g.key)}
                  onDrop={onDrop}
                  onFree={(day, e) => setPick({ day, time: freeTime ?? '19:00', x: e.clientX, y: e.clientY })}
                />
              )}
            </section>
          </div>
        )}
      </div>
      {pick && (
        <SlotPicker
          at={pick}
          queue={queue}
          onClose={() => setPick(null)}
          onPick={(q) => {
            setPick(null);
            void actions.add(targets.map((pf) => ({ item: q.item, clip: q.clip, platform: pf, at: `${pick.day}T${accounts.timeOf(pf)}` })));
          }}
        />
      )}
      {open && (
        <>
          <div className="pb-scrim" onClick={() => setOpenKey(null)} />
          <PostDrawer
            key={open.key}
            g={open}
            accounts={accounts}
            actions={actions}
            onClose={() => setOpenKey(null)}
            onMoved={(day) => setOpenKey(`${open.item}/${open.clip}/${day}`)}
            shorten={async (text, platform) => {
              try {
                return await client?.shortenCaption({ text, platform });
              } catch (e) {
                ui.toast(errText(e), { error: true });
                return undefined;
              } finally {
                reload();
              }
            }}
          />
        </>
      )}
    </div>
  );
}
