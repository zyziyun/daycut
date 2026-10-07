// The calendar part of the publish board: week columns (one card per clip per day, bold time, cover, title,
// platform marks, one calm status, the first problem in amber), clickable empty slots at the account's usual time,
// the month grid, and the dashed cards of a one-sentence plan.
import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Plus } from 'lucide-react';
import type { PostWarning, QueueClip } from '../../../shared/v04';
import { fmtDate, fmtNumber, fmtWeekday, t, tk } from '../i18n';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { media, Thumb } from '../v4/kit';
import { addDays, iso, type GroupStatus, type PostGroup } from './model';

export const DRAG = 'application/x-pb';
export type DragData = { group: string } | { item: string; clip: string };

export function readDrag(e: React.DragEvent): DragData | null {
  try {
    const raw = e.dataTransfer.getData(DRAG);
    return raw ? (JSON.parse(raw) as DragData) : null;
  } catch {
    return null;
  }
}

export function StatusMark({ s, views }: { s: GroupStatus; views?: number | null }) {
  return (
    <span className={`pb-st ${s}`} data-testid="pb-status" data-status={s}>
      {s === 'posted' ? <Check className="ico" /> : <i />}
      <span className="lbl">{tk(`pb.st.${s}`)}</span>
      {s === 'posted' && views != null && <span className="v num">{views >= 1000 ? `${fmtNumber(Math.round(views / 100) / 10)}k` : fmtNumber(views)}</span>}
    </span>
  );
}

export function warnText(w: PostWarning): string {
  return tk(`pb.w.${w.kind}`, { pf: platformName(w.platform) });
}

export function Pfs({ ids, size = 16 }: { ids: string[]; size?: number }) {
  return (
    <span className="pb-pfs">
      {ids.map((p) => (
        <PlatformIcon key={p} id={p} size={size} />
      ))}
    </span>
  );
}

export interface Proposed {
  key: string;
  day: string;
  time: string;
  title: string;
  cover: string | null;
  platforms: string[];
}

export function PostCard({ g, selected, onOpen }: { g: PostGroup; selected: boolean; onOpen: (g: PostGroup) => void }) {
  const w = g.warnings[0];
  return (
    <div
      className={`pc ${g.status} ${selected ? 'sel' : ''}`}
      draggable={g.status !== 'posted'}
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG, JSON.stringify({ group: g.key }));
        e.dataTransfer.effectAllowed = 'move';
      }}
      onClick={() => onOpen(g)}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen(g))}
      role="button"
      tabIndex={0}
      title={t('pb.dragHint')}
      data-testid="pub-post"
      data-group={g.key}
      data-clip={g.clip}
      data-day={g.day}
      data-platforms={g.platforms.join(' ')}
    >
      <div className="pc-top">
        <b className="pc-time num">{g.time}</b>
        <Pfs ids={g.platforms} />
      </div>
      <Thumb src={g.cover} ratio="3/4" />
      <div className="pc-title clamp2" lang="zh-CN">
        {g.title}
      </div>
      <StatusMark s={g.status} views={g.views} />
      {w && (
        <div className="pc-warn" data-testid="pb-warn" data-kind={w.kind}>
          <AlertTriangle className="ico" />
          {w.kind !== 'slot_clash' && <PlatformIcon id={w.platform} size={14} />}
          <span title={warnText(w)}>{tk(`pb.ws.${w.kind}`)}</span>
        </div>
      )}
    </div>
  );
}

function ProposedCard({ p }: { p: Proposed }) {
  return (
    <div className="pc proposed" data-testid="pb-proposed" data-day={p.day}>
      <div className="pc-top">
        <b className="pc-time num">{p.time}</b>
        <Pfs ids={p.platforms} />
      </div>
      <Thumb src={p.cover} ratio="3/4" />
      <div className="pc-title clamp2" lang="zh-CN">
        {p.title}
      </div>
    </div>
  );
}

interface GridProps {
  days: Date[];
  today: string;
  groups: PostGroup[];
  proposed: Proposed[] | null;
  /** days a previewed rule leaves out (hatched "Off") */
  offDays: Set<string>;
  selected: string | null;
  freeTime: string | null;
  onOpen: (g: PostGroup) => void;
  onDrop: (day: string, d: DragData) => void;
  onFree: (day: string, e: React.MouseEvent) => void;
}

export function WeekGrid({ days, today, groups, proposed, offDays, selected, freeTime, onOpen, onDrop, onFree }: GridProps) {
  const [over, setOver] = useState<string | null>(null);
  return (
    <div className="pb-week" data-testid="pub-week">
      {days.map((d) => {
        const day = iso(d);
        const mine = groups.filter((g) => g.day === day);
        const prop = (proposed ?? []).filter((p) => p.day === day);
        const past = day < today;
        const off = offDays.has(day);
        return (
          <div
            key={day}
            className={`pb-day ${day === today ? 'today' : ''} ${over === day ? 'over' : ''} ${past ? 'past' : ''} ${off ? 'off' : ''}`}
            onDragOver={(e) => {
              if (past) return;
              e.preventDefault();
              setOver(day);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              const x = readDrag(e);
              if (x && !past) onDrop(day, x);
            }}
            data-testid="pub-day"
            data-day={day}
          >
            <div className="pb-dh">
              <span>{fmtWeekday(d)}</span>
              <b className="num">{d.getDate()}</b>
            </div>
            <div className="pb-dbody">
              {[...mine.map((g) => ({ at: g.at, el: <PostCard key={g.key} g={g} selected={selected === g.key} onOpen={onOpen} /> })), ...prop.map((p) => ({ at: `${p.day}T${p.time}`, el: <ProposedCard key={p.key} p={p} /> }))]
                .sort((a, b) => a.at.localeCompare(b.at))
                .map((x) => x.el)}
              {off && !mine.length && !prop.length && <div className="pb-offlabel">{t('pb.off')}</div>}
              {!mine.length && !prop.length && !past && !off && freeTime && !proposed && (
                <button className="pb-free" onClick={(e) => onFree(day, e)} data-testid="pb-free" title={t('pb.freeHint', { time: freeTime })}>
                  <span>
                    <Plus className="ico" /> <span className="num">{freeTime}</span>
                  </span>
                  <span className="muted">{t('pb.free')}</span>
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function MonthGrid({ month, today, groups, freeTime, onOpen, onDrop, onFree }: Omit<GridProps, 'days' | 'proposed' | 'offDays' | 'selected'> & { month: Date }) {
  const [over, setOver] = useState<string | null>(null);
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = addDays(first, -((first.getDay() + 6) % 7));
  const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const weeks = Math.ceil(((last.getTime() - start.getTime()) / 86400000 + 1) / 7);
  const cells = Array.from({ length: weeks * 7 }, (_, i) => addDays(start, i));
  const soon = iso(addDays(new Date(`${today}T12:00`), 14)); // free slots are offered for the next two weeks
  return (
    <div className="pb-mwrap">
      <div className="pb-mhead">
        {cells.slice(0, 7).map((d) => (
          <div key={`h${d.getDay()}`} className="pb-mh">
            {fmtWeekday(d)}
          </div>
        ))}
      </div>
    <div className="pb-month" data-testid="pub-month">
      {cells.map((d) => {
        const day = iso(d);
        const inMonth = d.getMonth() === month.getMonth();
        const mine = groups.filter((g) => g.day === day);
        const past = day < today;
        const weekend = d.getDay() === 0 || d.getDay() === 6;
        return (
          <div
            key={day}
            className={`pb-mc ${inMonth ? '' : 'out'} ${over === day ? 'over' : ''}`}
            onDragOver={(e) => {
              if (past) return;
              e.preventDefault();
              setOver(day);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              const x = readDrag(e);
              if (x && !past) onDrop(day, x);
            }}
            data-testid="pub-day"
            data-day={day}
          >
            <span className={`pb-mn num ${day === today ? 'today' : ''}`}>{d.getDate()}</span>
            {mine.slice(0, 3).map((g) => (
              <button key={g.key} className={`pb-ml ${g.status}`} onClick={() => onOpen(g)} draggable={g.status !== 'posted'} onDragStart={(e) => e.dataTransfer.setData(DRAG, JSON.stringify({ group: g.key }))} data-testid="pub-post" data-group={g.key} title={g.title}>
                {g.cover ? <img src={media(g.cover)} alt="" /> : <i className="ph" />}
                <b className="num">{g.time}</b>
                <span className="clamp1" lang="zh-CN">
                  {g.title}
                </span>
                {g.warnings.length > 0 && <i className="wdot" aria-label={warnText(g.warnings[0])} />}
              </button>
            ))}
            {mine.length > 3 && <span className="pb-mmore">{t('pb.m.more', { n: mine.length - 3 })}</span>}
            {!mine.length && inMonth && !past && !weekend && freeTime && day <= soon && (
              <button className="pb-mfree" onClick={(e) => onFree(day, e)} data-testid="pb-free">
                {t('pb.m.free', { time: freeTime })}
              </button>
            )}
          </div>
        );
      })}
    </div>
    </div>
  );
}

/** Clicking an empty slot: the queue as a small list, pick one. */
export function SlotPicker({ at, queue, onPick, onClose }: { at: { day: string; time: string; x: number; y: number }; queue: QueueClip[]; onPick: (q: QueueClip) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    setTimeout(() => window.addEventListener('mousedown', down), 0);
    window.addEventListener('keydown', key);
    return () => {
      window.removeEventListener('mousedown', down);
      window.removeEventListener('keydown', key);
    };
  }, [onClose]);
  const x = Math.min(at.x, window.innerWidth - 340);
  const y = Math.min(at.y, window.innerHeight - 420);
  return (
    <div ref={ref} className="pb-pick" style={{ left: x, top: y }} role="dialog" data-testid="pb-pick">
      <b>{t('pb.pick.title', { time: `${fmtDate(`${at.day}T12:00`, { weekday: 'short', month: 'short', day: 'numeric' })} ${at.time}` })}</b>
      {!queue.length && <span className="muted">{t('pb.pick.empty')}</span>}
      <div className="pb-pick-list">
        {queue.slice(0, 40).map((q) => (
          <button key={`${q.item}/${q.clip}`} onClick={() => onPick(q)} data-testid="pb-pick-item">
            <Thumb src={q.cover} ratio="3/4" />
            <span className="col" style={{ gap: 2, minWidth: 0 }}>
              <span className="clamp2" lang="zh-CN">
                {q.title}
              </span>
              <span className="muted small clamp1">{q.project}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
