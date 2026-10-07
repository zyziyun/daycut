// 发布: the week (or month) calendar with today highlighted and free days hatched, the clips not scheduled yet on
// the left (drag them onto a day, or let AI fill the free days), and ONE primary: confirm this week. Clicking a
// post offers the assisted-fill browser (the app fills the forms; she presses publish herself).
import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, ExternalLink, Package, Sparkles, Trash2, CheckCircle2, UserRound } from 'lucide-react';
import { useChannels } from './Channels';
import type { CalendarPost } from '../../../shared/v04';
import { fmtDate, fmtTime, fmtWeekday, t, tk } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { go, href } from '../lib/router';
import { platformName } from './Home';
import { PlatformIcon, SCHEDULE_PLATFORMS } from './PlatformIcon';
import { PlatformPicker } from './PlatformPicker';
import { Empty, Seg, Thumb } from './kit';
import { errText } from './msg';
import { nextSlots } from './Project';
import { useUi } from './ui';

/** Default post time per platform when a clip is dropped on a day (a convention, editable per post). */
export const SLOT_TIME: Record<string, string> = { x: '09:00', instagram: '18:00', 'wechat-channels': '12:00' };

function loadSchedTo(): string {
  try {
    const v = localStorage.getItem('pub.schedTo');
    return v && SCHEDULE_PLATFORMS.includes(v) ? v : 'xiaohongshu';
  } catch {
    return 'xiaohongshu';
  }
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export function weekStart(d: Date, offset = 0): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  const dow = (x.getDay() + 6) % 7; // Monday = 0
  x.setDate(x.getDate() - dow + offset * 7);
  return x;
}

export function CalendarScreen() {
  const { client } = useEngine();
  const { data: hist } = useHistory();
  const ui = useUi();
  const [view, setView] = useState<'week' | 'month'>('week');
  const [off, setOff] = useState(0);
  const start = useMemo(() => weekStart(new Date(), off), [off]);
  const days = useMemo(() => Array.from({ length: view === 'week' ? 7 : 35 }, (_, k) => new Date(start.getTime() + k * 86400000)), [start, view]);
  const { data, reload } = useLoad((c) => c.calendar(), []);
  const { adapters, channels } = useChannels();
  // a publishing account's default post time (发布账号) wins over the convention
  const slotTime = (pf: string) => {
    const a = adapters.find((x) => x.packagePlatforms.includes(pf));
    const c = a && channels.find((x) => x.adapterId === a.id && x.times.length);
    return c?.times[0] ?? SLOT_TIME[pf] ?? '19:00';
  };
  const signedIn = channels.filter((c) => c.login.state === 'in').length;
  const [over, setOver] = useState<string | null>(null);
  const [schedTo, setSchedToState] = useState<string>(loadSchedTo);
  const setSchedTo = (v: string) => {
    setSchedToState(v);
    try {
      localStorage.setItem('pub.schedTo', v);
    } catch {
      /* private mode */
    }
  };
  const today = iso(new Date());
  const posts = data?.posts ?? [];
  const weekPosts = posts.filter((p) => p.at.slice(0, 10) >= iso(days[0]) && p.at.slice(0, 10) <= iso(days[days.length - 1]));

  const schedule = async (item: string, clip: string, day: string) => {
    if (!client) return;
    try {
      const p = await client.schedule({ item, clip, at: `${day}T${slotTime(schedTo)}`, platform: schedTo });
      reload();
      ui.toast(t('pub.scheduled', { date: fmtDate(p.at) }), {
        undo: async () => {
          await client.updatePost(p.id, { remove: true });
          reload();
        },
      });
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const move = async (p: CalendarPost, day: string) => {
    if (!client || p.at.slice(0, 10) === day) return;
    const old = p.at;
    await client.updatePost(p.id, { at: `${day}T${p.at.slice(11, 16)}` });
    reload();
    ui.toast(t('pub.moved', { date: fmtDate(`${day}T12:00`) }), {
      undo: async () => {
        await client.updatePost(p.id, { at: old });
        reload();
      },
    });
  };
  const onDrop = (day: string) => (e: React.DragEvent) => {
    e.preventDefault();
    setOver(null);
    const raw = e.dataTransfer.getData('application/x-vs-post');
    if (!raw) return;
    const d = JSON.parse(raw) as { post?: string; item?: string; clip?: string };
    if (d.post) {
      const p = posts.find((x) => x.id === d.post);
      if (p) void move(p, day);
    } else if (d.item && d.clip) void schedule(d.item, d.clip, day);
  };
  const aiFill = async () => {
    if (!client || !data) return;
    const free = nextSlots(Math.min(7, data.queue.length), posts.filter((p) => p.platform.split(':')[0] === schedTo).map((p) => p.at), slotTime(schedTo), new Date(Date.now() - 86400000));
    const made: string[] = [];
    for (let k = 0; k < free.length; k++) {
      const q = data.queue[k];
      const p = await client.schedule({ item: q.item, clip: q.clip, at: free[k], platform: schedTo });
      made.push(p.id);
    }
    reload();
    ui.toast(t('pub.aiScheduled', { n: made.length }), {
      undo: async () => {
        for (const m of made) await client.updatePost(m, { remove: true });
        reload();
      },
    });
  };
  const confirm = async () => {
    if (!client) return;
    const r = await client.confirmWeek(iso(start));
    reload();
    ui.toast(t('pub.confirmed', { n: r.ready }));
  };
  const postMenu = (p: CalendarPost) => (e: React.MouseEvent) => {
    const batch = hist?.items.find((i) => i.id === p.item);
    ui.menu(e, [
      { label: t('pub.fill'), icon: <ExternalLink className="ico" />, run: () => (batch ? go({ name: 'publish', batch: p.item }) : ui.toast(t('pub.fillHint'))) },
      { label: t('pub.markPosted'), icon: <CheckCircle2 className="ico" />, run: async () => (await client?.updatePost(p.id, { state: 'posted' }), reload()) },
      { label: t('clip.edit'), icon: <Sparkles className="ico" />, run: () => go({ name: 'clip', id: p.item, clip: p.clip }) },
      { label: '', sep: true, run: () => undefined },
      {
        label: t('pub.unschedule'),
        icon: <Trash2 className="ico" />,
        run: async () => {
          await client?.updatePost(p.id, { remove: true });
          reload();
          ui.toast(t('pub.unschedule'), { undo: async () => (await client?.schedule({ item: p.item, clip: p.clip, at: p.at, platform: p.platform }), reload()) });
        },
      },
    ]);
  };

  return (
    <div className="scroll" data-testid="calendar">
      <div className="pg wide">
        <div className="ph">
          <div>
            <h1>{t('pub.title')}</h1>
            <p>{t('pub.subtitle', { n: weekPosts.length })}</p>
          </div>
          <span className="sp" />
          <div className="acts">
            <Seg
              value={view}
              onChange={(v) => (v === ('data' as typeof view) ? go({ name: 'metrics' }) : setView(v))}
              options={[
                { v: 'week', label: t('pub.week') },
                { v: 'month', label: t('pub.month') },
                { v: 'data' as 'week', label: t('pub.data') },
              ]}
            />
            <a className="btn ghost" href={href({ name: 'channels' })} data-testid="pub-accounts" data-tip={t('set.channelsHint')}>
              <UserRound className="ico" />
              {t('ch.manage')}
              {channels.length > 0 && <span className="muted num">{t('ch.status', { n: signedIn, total: channels.length })}</span>}
            </a>
            <button className="btn primary" onClick={() => void confirm()} disabled={!weekPosts.some((p) => p.state === 'planned')} data-testid="pub-confirm">
              {t('pub.confirm')}
            </button>
          </div>
        </div>
        <div className="pubg">
          <aside className="queue" data-testid="pub-queue">
            <div className="sech">
              <h2>{t('pub.queue')}</h2>
              <span className="n muted num">{data?.queue.length ?? ''}</span>
            </div>
            <div className="col" style={{ gap: 6, margin: '4px 0 10px' }} data-testid="pub-platforms" title={t('pub.schedToHint')}>
              <span className="muted small">{t('pub.schedTo')}</span>
              <PlatformPicker value={schedTo} onChange={setSchedTo} connected={adapters.filter((a) => channels.some((c) => c.adapterId === a.id)).flatMap((a) => a.packagePlatforms)} />
            </div>
            {data && !data.queue.length && <p className="muted">{t('pub.queueEmpty')}</p>}
            {(data?.queue ?? []).slice(0, 30).map((q) => (
              <div
                key={`${q.item}/${q.clip}`}
                className="q"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('application/x-vs-post', JSON.stringify({ item: q.item, clip: q.clip }));
                  e.dataTransfer.effectAllowed = 'move';
                }}
                title={t('pub.dragHint')}
                data-testid="pub-queue-item"
              >
                <Thumb src={q.cover} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="clamp2" lang="zh-CN">
                    {q.title}
                  </div>
                  <span className="muted clamp1">{q.project}</span>
                </div>
                <a className="btn ghost icon sm" href={href({ name: 'publish', batch: q.item })} aria-label={t('pkg.open')} data-tip={t('pkg.open')} data-testid="pub-queue-package" draggable={false} onClick={(e) => e.stopPropagation()}>
                  <Package className="ico" />
                </a>
              </div>
            ))}
            {(data?.queue.length ?? 0) > 0 && (
              <button className="btn ghost" onClick={() => void aiFill()} style={{ marginTop: 8 }} data-testid="pub-ai">
                <Sparkles className="ico" />
                {t('pub.aiSchedule')}
              </button>
            )}
          </aside>
          <div>
            <div className="row" style={{ marginBottom: 8 }}>
              <button className="btn ghost icon sm" onClick={() => setOff(off - (view === 'week' ? 1 : 5))} aria-label={t('pub.prev')} data-tip={t('pub.prev')}>
                <ChevronLeft className="ico" />
              </button>
              <span className="muted num">
                {fmtDate(days[0])} – {fmtDate(days[days.length - 1])}
              </span>
              <button className="btn ghost icon sm" onClick={() => setOff(off + (view === 'week' ? 1 : 5))} aria-label={t('pub.next')} data-tip={t('pub.next')}>
                <ChevronRight className="ico" />
              </button>
              {off !== 0 && (
                <button className="btn ghost sm" onClick={() => setOff(0)}>
                  {t('pub.today')}
                </button>
              )}
            </div>
            {!posts.length && !(data?.queue.length ?? 0) && data ? (
              <Empty title={t('pub.emptyWeek')} hint={t('pub.emptyWeekHint')} action={<a className="btn" href={href({ name: 'projects' })}>{t('nav.projects')}</a>} />
            ) : (
              <div className="week" style={view === 'month' ? { gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', gridAutoRows: 'minmax(110px, auto)' } : undefined} data-testid="pub-week">
                {days.map((d) => {
                  const day = iso(d);
                  const mine = posts.filter((p) => p.at.slice(0, 10) === day).sort((a, b) => a.at.localeCompare(b.at));
                  const past = day < today;
                  return (
                    <div
                      key={day}
                      className={`day ${day === today ? 'today' : ''} ${over === day ? 'over' : ''}`}
                      style={view === 'month' ? { borderTop: '1px solid var(--border)' } : undefined}
                      onDragOver={(e) => (e.preventDefault(), setOver(day))}
                      onDragLeave={() => setOver(null)}
                      onDrop={onDrop(day)}
                      data-testid="pub-day"
                      data-day={day}
                    >
                      <div className="dh">
                        <span>{fmtWeekday(d)}</span>
                        <b className="num">{day === today ? t('pub.today') : fmtDate(d, { month: 'numeric', day: 'numeric' })}</b>
                      </div>
                      {mine.map((p) =>
                        view === 'month' ? (
                          <div key={p.id} className="clamp1 muted" onContextMenu={postMenu(p)} onClick={postMenu(p)} style={{ fontSize: 12, cursor: 'pointer' }}>
                            <i className={`dot ${p.state === 'planned' ? 'run' : 'done'}`} /> <PlatformIcon id={p.platform} size={12} /> {fmtTime(p.at)} {p.title}
                          </div>
                        ) : (
                          <div
                            key={p.id}
                            className="post"
                            draggable={p.state !== 'posted'}
                            onDragStart={(e) => e.dataTransfer.setData('application/x-vs-post', JSON.stringify({ post: p.id }))}
                            onClick={postMenu(p)}
                            onContextMenu={postMenu(p)}
                            style={p.state === 'posted' ? { opacity: 0.55 } : undefined}
                            data-testid="pub-post"
                          >
                            <Thumb src={p.cover} />
                            <div className="meta">
                              <span className="num clamp1" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                <PlatformIcon id={p.platform} size={13} />
                                {platformName(p.platform)} {fmtTime(p.at)}
                              </span>
                              <span style={{ color: p.state === 'ready' ? 'var(--ok)' : undefined }}>{tk(`pub.state.${p.state}`)}</span>
                            </div>
                          </div>
                        ),
                      )}
                      {!mine.length && view === 'week' && !past && <div className="gapc">{t('pub.gap')}</div>}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
