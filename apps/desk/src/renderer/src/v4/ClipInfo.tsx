// A clip's info where the clip is (2026-10 review step 5): cover choices, caption style, versions, the copy per
// platform and when it goes out - in the editor's inspector (layout B) and placed one by one on the Studio's clip page
// (layout A). The copy and the schedule are the publish drawer's own component and calendar rows (PostCopy); cover
// and caption changes re-render the clip in the background (useAutoRender), with the progress shown here.
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CalendarClock, CalendarDays, Check, Clock, Loader2, Plus, RefreshCw } from 'lucide-react';
import type { EditOp, OutputDoc } from '../../../shared/v04';
import type { StripInfo } from '../../../shared/timeline';
import { fmtDate, t, type MessageKey } from '../i18n';
import { useEngine } from '../lib/engine';
import { nextFreeDay } from '../lib/nextSlot';
import type { RenderState } from '../lib/autoRender';
import { href } from '../lib/router';
import { useChannels, useChosenPlatforms } from './Channels';
import { platformName } from './Home';
import { media } from './kit';
import { PlatformIcon } from './PlatformIcon';
import { errText } from './msg';
import { useUi } from './ui';
import { base, groupPosts, iso, sortIds } from '../publish/model';
import { firstTab, PostCopy, type Row } from '../publish/PostCopy';
import { useAccounts, usePublishData } from '../publish/usePublish';
import '../publish/publish.css';
import './clipinfo.css';

type EditFn = (ops: EditOp[], undoToast?: boolean) => Promise<boolean>;

// ---------------------------------------------------------------- cover
/** Frames to choose a cover from: spread over the clip (the sprite's tiles; no extra work). */
export function coverTimes(duration: number, n = 5): number[] {
  if (!duration) return [];
  return Array.from({ length: n }, (_, k) => Math.round(((duration * (k + 0.5)) / n) * 100) / 100);
}

function Tile({ strip, at, w = 34 }: { strip: StripInfo; at: number; w?: number }) {
  const [tw, th] = strip.tile;
  const h = Math.round((w * th) / tw);
  const i = Math.max(0, Math.min(strip.n - 1, Math.round(at / strip.interval)));
  const sc = w / tw;
  return (
    <span
      className="ci-tile"
      style={{
        width: w,
        height: h,
        backgroundImage: `url("${media(strip.sprite)}")`,
        backgroundSize: `${strip.cols * tw * sc}px ${strip.rows * th * sc}px`,
        backgroundPosition: `-${(i % strip.cols) * tw * sc}px -${Math.floor(i / strip.cols) * th * sc}px`,
      }}
    />
  );
}

export function ClipCovers({ doc, strip, time, edit }: { doc: OutputDoc; strip: StripInfo | null; time: number; edit: EditFn }) {
  if (doc.caps.cover === false) return null;
  const cur = doc.cover_edit?.t;
  const text = doc.cover_edit?.text ?? doc.title;
  const pick = (at: number) => void edit([{ op: 'cover', t: Math.round(at * 100) / 100, text, style: 'card' } as EditOp], true);
  const times = coverTimes(doc.duration);
  return (
    <div className="ci-covers" data-testid="ci-covers">
      {doc.cover && (
        <span className={`ci-cover on`} title={t('ci.coverNow')}>
          <img src={media(doc.cover)} alt="" />
        </span>
      )}
      {strip?.sprite
        ? times.map((at) => (
            <button key={at} className={`ci-cover ${cur != null && Math.abs(cur - at) < 0.3 ? 'on' : ''}`} onClick={() => pick(at)} aria-label={t('ci.coverAt', { s: at.toFixed(1) })} data-testid="ci-cover">
              <Tile strip={strip} at={at} />
            </button>
          ))
        : null}
      <button className="ci-cover here" onClick={() => pick(time)} data-tip={t('ci.coverHere')} aria-label={t('ci.coverHere')} data-testid="ci-cover-here">
        <Plus className="ico" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- captions
type Look = 'clean' | 'bold' | 'box';
const LOOKS: Record<Look, Record<string, unknown>> = {
  clean: { box: false, stroke: 0.03 },
  bold: { box: false, stroke: 0.12, stroke_color: '#000000' },
  box: { box: true, box_color: '#000000', stroke: 0 },
};
export function lookOf(s: Record<string, unknown> | null | undefined): Look {
  if (s?.box) return 'box';
  return typeof s?.stroke === 'number' && s.stroke >= 0.08 ? 'bold' : 'clean';
}
const POS = ['bottom', 'middle', 'top'] as const;

export function CaptionLooks({ doc, edit }: { doc: OutputDoc; edit: EditFn }) {
  const can = doc.caps.caption_style !== false && (!!doc.caps.captions_ours || doc.captions.some((c) => c.added));
  if (!can) return <p className="ci-note" data-testid="ci-caps-burned">{t('ci.capsBurned')}</p>;
  const s = (doc.caption_style ?? {}) as Record<string, unknown>;
  const look = lookOf(s);
  const pos = (s.position as string) ?? 'bottom';
  const kw = !!s.highlight && s.highlight !== s.color;
  const set = (style: Record<string, unknown>) => void edit([{ op: 'caption_style', style } as EditOp]);
  return (
    <div className="ci-chips" data-testid="ci-captions">
      {(Object.keys(LOOKS) as Look[]).map((k) => (
        <button key={k} className={`ci-chip ${look === k ? 'on' : ''}`} aria-pressed={look === k} onClick={() => look !== k && set(LOOKS[k])} data-testid={`ci-look-${k}`}>
          {t(`ci.look.${k}` as MessageKey)}
        </button>
      ))}
      <button className="ci-chip" onClick={() => set({ position: POS[(POS.indexOf(pos as (typeof POS)[number]) + 1) % POS.length] })} data-testid="ci-pos">
        {t('ci.pos', { p: t(`editor.pos.${POS.includes(pos as (typeof POS)[number]) ? pos : 'bottom'}` as MessageKey) })}
      </button>
      <button className={`ci-chip ${kw ? 'on' : ''}`} aria-pressed={kw} onClick={() => set({ highlight: kw ? ((s.color as string) ?? '#FFFFFF') : '#FFD60A' })} data-testid="ci-keywords">
        <i className="ci-sw" style={{ background: kw ? (s.highlight as string) : 'transparent' }} />
        {t('ci.keywords')}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- versions
const VERSIONS = ['9:16', '16:9', '3:4'] as const; // international first

export function ClipVersions({ doc, edit }: { doc: OutputDoc; edit: EditFn }) {
  const orig = new Set(doc.files.map((f) => f.aspect));
  const added = new Set(doc.exports.map((e) => e.target));
  const flat = doc.mode === 'flattened';
  return (
    <div className="ci-chips" data-testid="ci-versions">
      {VERSIONS.map((v) => {
        const own = orig.has(v);
        const on = own || added.has(v);
        return (
          <button
            key={v}
            className={`ci-chip ${on ? 'on' : ''}`}
            aria-pressed={on}
            disabled={own || doc.caps.export === false}
            title={own ? t('ci.vOwn') : undefined}
            onClick={() => void edit([on ? { op: 'export_remove', target: v } : { op: 'export_add', target: v, layout: flat ? 'band' : 'auto' }] as EditOp[], true)}
            data-testid={`ci-version-${v}`}
          >
            {on && <Check className="ico" />}
            {t(`ci.v.${v}` as MessageKey)}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- the background render
export function RenderPill({ s, onRetry }: { s: RenderState; onRetry?: () => void }) {
  if (s.phase === 'idle') return null;
  return (
    <span className={`ci-render ${s.phase}`} data-testid="ci-render" data-phase={s.phase}>
      {s.phase === 'done' ? <Check className="ico" /> : s.phase === 'failed' ? <AlertTriangle className="ico" /> : <Loader2 className="ico spin" />}
      {s.phase === 'waiting' && t('ci.r.waiting')}
      {s.phase === 'running' && t('ci.r.running', { p: Math.round(s.progress * 100) })}
      {s.phase === 'done' && t('ci.r.done')}
      {s.phase === 'failed' && t('ci.r.failed')}
      {s.phase === 'failed' && onRetry && (
        <button className="pb-link" onClick={onRetry} data-testid="ci-render-retry">
          <RefreshCw className="ico" />
          {t('ci.r.retry')}
        </button>
      )}
      {s.phase === 'running' && <i className="ci-bar" style={{ width: `${Math.round(s.progress * 100)}%` }} />}
    </span>
  );
}

// ---------------------------------------------------------------- copy + when
/** A clip's calendar rows, its platforms and the next free slot - shared by the post section and the Studio's
 * 「排期发布」 in the page header (one load of the calendar). */
export function useClipSchedule(item: string, clip: string) {
  const ui = useUi();
  const { subscribe } = useEngine();
  const { data, actions, client, reload } = usePublishData();
  const { adapters, channels } = useChannels();
  const chosen = useChosenPlatforms();
  const accounts = useAccounts(adapters, channels, chosen);
  useEffect(() => subscribe((e) => (e.type === 'calendar' || (e.type === 'output-edit' && e.item === item && e.clip === clip) ? reload() : undefined)), [subscribe, item, clip]); // eslint-disable-line react-hooks/exhaustive-deps
  const posts = useMemo(() => data?.posts ?? [], [data]);
  const mine = useMemo(() => posts.filter((p) => p.item === item && p.clip === clip), [posts, item, clip]);
  const today = iso(new Date());
  const groups = useMemo(() => groupPosts(mine, accounts.connected), [mine, accounts.connected]);
  const g = groups.find((x) => x.day >= today && x.status !== 'posted') ?? groups[groups.length - 1] ?? null;
  const [off, setOff] = useState<string[]>([]);
  const pfs = useMemo(() => accounts.connected.filter((pf) => !off.includes(pf)), [accounts.connected, off]);
  const day = useMemo(() => nextFreeDay(posts, new Date(), pfs.map((pf) => accounts.timeOf(pf))), [posts, pfs, accounts]);
  const rows: Row[] = useMemo(() => (g ? sortIds(g.on.map((p) => base(p.platform))).map((pf) => ({ pf, post: g.on.find((p) => base(p.platform) === pf)! })) : []), [g]);
  const [tab, setTab] = useState('');
  const fmtWhen = (d: string, hm: string) => fmtDate(`${d}T${hm}`, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  const when = pfs[0] ? fmtWhen(day, accounts.timeOf(pfs[0])) : '';
  const scheduleNow = () => (pfs.length ? actions.add(pfs.map((pf) => ({ item, clip, platform: pf, at: `${day}T${accounts.timeOf(pf)}` }))) : Promise.resolve(undefined));
  const shorten = async (text: string, platform: string) => {
    try {
      return await client?.shortenCaption({ text, platform });
    } catch (e) {
      ui.toast(errText(e), { error: true });
      return undefined;
    } finally {
      reload();
    }
  };
  return { item, clip, loaded: !!data, g, rows, accounts, actions, off, setOff, pfs, when, scheduledWhen: g ? fmtWhen(g.day, g.time) : '', scheduleNow, tab: rows.some((r) => r.pf === tab) ? tab : firstTab(rows), setTab, shorten };
}
export type ClipScheduleState = ReturnType<typeof useClipSchedule>;

/** The clip's post: unscheduled -> its platforms + "Schedule · <next free slot>"; scheduled -> when, where, and the
 * copy per platform (the publish drawer's component, same rows). */
export function ClipSchedule({ item, clip, compact = false }: { item: string; clip: string; compact?: boolean }) {
  return <ClipScheduleView s={useClipSchedule(item, clip)} compact={compact} />;
}

export function ClipScheduleView({ s, compact = false }: { s: ClipScheduleState; compact?: boolean }) {
  const { g, accounts, actions, off, setOff, pfs, rows } = s;
  if (!s.loaded) return <div className="ci-sched" data-testid="ci-schedule" aria-busy="true" />;
  if (!g) {
    if (!accounts.connected.length)
      return (
        <div className="ci-sched" data-testid="ci-schedule">
          <a className="pb-link" href={href({ name: 'settings', section: 'accounts' })} data-testid="ci-pick-platforms">
            {t('ci.noPlatforms')}
          </a>
        </div>
      );
    return (
      <div className="ci-sched" data-testid="ci-schedule" data-state="unscheduled">
        <div className="ci-chips">
          {accounts.connected.map((pf) => {
            const on = !off.includes(pf);
            return (
              <button key={pf} className={`ci-chip ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => setOff((o) => (on ? [...o, pf] : o.filter((x) => x !== pf)))} data-testid="ci-pf" data-pf={pf}>
                <PlatformIcon id={pf} size={13} />
                {platformName(pf)}
              </button>
            );
          })}
        </div>
        <button className="btn ci-schedule-btn" disabled={!pfs.length} onClick={() => void s.scheduleNow()} data-testid="ci-schedule-btn">
          <CalendarClock className="ico" />
          {t('ci.schedule', { when: s.when })}
        </button>
        {!compact && <p className="ci-note">{t('ci.assist')}</p>}
      </div>
    );
  }
  return (
    <div className="ci-sched" data-testid="ci-schedule" data-state="scheduled">
      <div className="ci-when">
        <label className="pb-field" onClick={(e) => (e.currentTarget.querySelector('input') as HTMLInputElement | null)?.showPicker?.()}>
          <CalendarDays className="ico" />
          <span className="lbl">{fmtDate(`${g.day}T12:00`, { weekday: 'short', month: 'short', day: 'numeric' })}</span>
          <input className="over" type="date" aria-label={t('pb.d.date')} value={g.day} onChange={(e) => e.target.value && void actions.retime(g, e.target.value)} data-testid="ci-date" />
        </label>
        <label className="pb-field narrow">
          <Clock className="ico" />
          <input type="time" aria-label={t('pb.d.time')} value={g.time} onChange={(e) => /^\d{2}:\d{2}$/.test(e.target.value) && void actions.retime(g, g.day, e.target.value)} data-testid="ci-time" />
        </label>
        <a className="pb-link muted" href={href({ name: 'calendar' })} data-testid="ci-calendar">
          {t('ci.openCalendar')}
        </a>
      </div>
      <div className="ci-chips">
        {sortIds([...new Set([...accounts.connected, ...g.posts.map((p) => base(p.platform))])]).map((pf) => {
          const row = g.posts.find((p) => base(p.platform) === pf);
          const on = !!row && row.enabled !== false;
          return (
            <button
              key={pf}
              className={`ci-chip ${on ? 'on' : ''}`}
              aria-pressed={on}
              disabled={row?.state === 'posted'}
              onClick={() => void actions.togglePlatform(g, pf, !on, `${g.day}T${accounts.timeOf(pf)}`, platformName(pf))}
              data-testid="ci-pf"
              data-pf={pf}
            >
              <PlatformIcon id={pf} size={13} />
              {platformName(pf)}
            </button>
          );
        })}
      </div>
      {rows.length > 0 && <PostCopy rows={rows} tab={s.tab} setTab={s.setTab} accounts={accounts} actions={actions} shorten={s.shorten} />}
      {!compact && <p className="ci-note">{t('ci.assist')}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- the inspector (layout B)
export function ClipInfoPanel({ doc, strip, time, edit, sched }: { doc: OutputDoc; strip: StripInfo | null; time: number; edit: EditFn; sched: ClipScheduleState }) {
  return (
    <section className="ci" data-testid="clip-info">
      <div className="ci-sec">
        <span className="ci-lbl">{t('ci.cover')}</span>
        <ClipCovers doc={doc} strip={strip} time={time} edit={edit} />
      </div>
      <div className="ci-sec">
        <span className="ci-lbl">{t('ci.captions')}</span>
        <CaptionLooks doc={doc} edit={edit} />
      </div>
      <div className="ci-sec">
        <span className="ci-lbl">{t('ci.versions')}</span>
        <ClipVersions doc={doc} edit={edit} />
      </div>
      <div className="ci-sec">
        <span className="ci-lbl">{t('ci.post')}</span>
        <ClipScheduleView s={sched} />
      </div>
    </section>
  );
}
