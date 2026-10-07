// 待排期: finished clips not on the calendar, grouped by project (collapsible, remembered), drag one onto a day,
// select several for "Schedule…", or "Fill my week". Dropping a card here puts it back (unschedule).
import { useState } from 'react';
import { ChevronDown, ChevronRight, Search, Wand2, X } from 'lucide-react';
import type { QueueClip } from '../../../shared/v04';
import { fmtClock, t } from '../i18n';
import { media, Thumb } from '../v4/kit';
import { DRAG, readDrag, type DragData } from './Board';
import { queueByProject } from './model';

const COLLAPSED = 'pb.collapsed';
const SHOW = 4;

function loadCollapsed(): string[] | null {
  try {
    const v = JSON.parse(localStorage.getItem(COLLAPSED) || 'null');
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : null;
  } catch {
    return null;
  }
}

export const clipKey = (q: { item: string; clip: string }) => `${q.item}/${q.clip}`;

export function QueuePanel({
  queue,
  canFill,
  fillHint,
  selected,
  setSelected,
  onFill,
  onSchedule,
  onDropBack,
}: {
  queue: QueueClip[];
  canFill: boolean;
  fillHint: string;
  selected: string[];
  setSelected: (s: string[]) => void;
  onFill: () => void;
  onSchedule: (e: React.MouseEvent) => void;
  onDropBack: (d: DragData) => void;
}) {
  const groups = queueByProject(queue);
  const [collapsed, setCollapsedS] = useState<string[] | null>(loadCollapsed);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selecting, setSelecting] = useState<Set<string>>(new Set());
  const [q, setQ] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const isCollapsed = (item: string, i: number) => (collapsed ? collapsed.includes(item) : i > 0);
  const toggle = (item: string, i: number) => {
    const cur = collapsed ?? groups.filter((_, k) => k > 0).map((g) => g.item);
    const next = isCollapsed(item, i) ? cur.filter((x) => x !== item) : [...cur, item];
    setCollapsedS(next);
    try {
      localStorage.setItem(COLLAPSED, JSON.stringify(next));
    } catch {
      /* private mode */
    }
  };
  const sel = new Set(selected);
  const pick = (k: string) => setSelected(sel.has(k) ? selected.filter((x) => x !== k) : [...selected, k]);
  const needle = (q ?? '').trim().toLowerCase();
  return (
    <aside
      className={`pb-queue ${over ? 'over' : ''}`}
      data-testid="pub-queue"
      onDragOver={(e) => {
        if (![...e.dataTransfer.types].includes(DRAG)) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const d = readDrag(e);
        if (d && 'group' in d) onDropBack(d);
      }}
    >
      <div className="pb-qhead">
        <div className="row" style={{ gap: 10 }}>
          <h2>{t('pb.q.title')}</h2>
          <span className="pb-count num">{queue.length}</span>
          <span className="sp" />
          <button className="btn ghost icon sm" onClick={() => setQ(q === null ? '' : null)} aria-label={t('pb.q.search')} data-tip={t('pb.q.search')}>
            <Search className="ico" />
          </button>
        </div>
        {q !== null && <input className="input pb-search" autoFocus placeholder={t('pb.q.search')} value={q} onChange={(e) => setQ(e.target.value)} data-testid="pb-search" />}
        <p className="pb-hint">{over ? t('pb.q.dropBack') : t('pb.q.hint')}</p>
        <button className="pb-fill" onClick={onFill} disabled={!canFill || !queue.length} data-testid="pub-ai" title={fillHint}>
          <Wand2 className="ico" />
          {t('pb.q.fill')}
        </button>
        {!canFill && <span className="pb-hint center">{t('pb.q.needPlatform')}</span>}
      </div>
      <div className="pb-qlist">
        {!queue.length && <p className="pb-hint">{t('pb.q.empty')}</p>}
        {groups.map((g, i) => {
          const clips = needle ? g.clips.filter((c) => `${c.title} ${c.clip}`.toLowerCase().includes(needle)) : g.clips;
          if (needle && !clips.length) return null;
          const closed = !needle && isCollapsed(g.item, i);
          const nSel = g.clips.filter((c) => sel.has(clipKey(c))).length;
          const selMode = selecting.has(g.item) || nSel > 0;
          const shown = expanded.has(g.item) || needle ? clips : clips.slice(0, SHOW);
          return (
            <section key={g.item} className="pb-qgroup" data-testid="pb-qgroup" data-item={g.item}>
              <div className="pb-qgh">
                <button className="pb-qtoggle" onClick={() => toggle(g.item, i)} aria-expanded={!closed} aria-label={t(closed ? 'pb.q.expand' : 'pb.q.collapse', { name: g.project })}>
                  {closed ? <ChevronRight className="ico" /> : <ChevronDown className="ico" />}
                  <b className="clamp1">{g.project}</b>
                  <span className="muted num">{g.clips.length}</span>
                </button>
                <span className="sp" />
                {closed ? (
                  nSel > 0 ? (
                    <span className="pb-selcount">{t('pb.q.selected', { n: nSel })}</span>
                  ) : (
                    <span className="pb-stack" aria-hidden>
                      {g.clips.slice(0, 3).map((c) => (c.cover ? <img key={c.clip} src={media(c.cover)} alt="" /> : <i key={c.clip} />))}
                    </span>
                  )
                ) : selMode ? (
                  <button
                    className="pb-link"
                    onClick={() => {
                      setSelected(selected.filter((k) => !g.clips.some((c) => clipKey(c) === k)));
                      const n = new Set(selecting);
                      n.delete(g.item);
                      setSelecting(n);
                    }}
                    data-testid="pb-selected"
                  >
                    {t('pb.q.selected', { n: nSel })}
                  </button>
                ) : (
                  <button className="pb-link muted" onClick={() => setSelecting(new Set(selecting).add(g.item))} data-testid="pb-select">
                    {t('pb.q.select')}
                  </button>
                )}
              </div>
              {!closed && (
                <div className="pb-qitems">
                  {shown.map((c) => {
                    const k = clipKey(c);
                    return (
                      <div
                        key={k}
                        className={`pb-qi ${sel.has(k) ? 'on' : ''}`}
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData(DRAG, JSON.stringify({ item: c.item, clip: c.clip }));
                          e.dataTransfer.effectAllowed = 'move';
                        }}
                        onClick={() => selMode && pick(k)}
                        title={t('pub.dragHint')}
                        data-testid="pub-queue-item"
                        data-clip={c.clip}
                      >
                        {selMode && <input type="checkbox" checked={sel.has(k)} onChange={() => pick(k)} onClick={(e) => e.stopPropagation()} aria-label={c.title} data-testid="pb-pick-clip" />}
                        <Thumb src={c.cover} ratio="3/4" />
                        <div className="pb-qtext">
                          <b className="clamp2" lang="zh-CN">
                            {c.title}
                          </b>
                          <span className="muted num">
                            {c.duration ? `${fmtClock(c.duration)} · ` : ''}
                            {c.has_post === false ? t('pb.q.noCopy') : t('pb.q.captions')}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                  {clips.length > SHOW && !needle && (
                    <button className="pb-link center" onClick={() => setExpanded((s) => (s.has(g.item) ? (s.delete(g.item), new Set(s)) : new Set(s).add(g.item)))}>
                      {expanded.has(g.item) ? t('pb.q.less') : t('pb.q.more', { n: clips.length - SHOW })}
                    </button>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
      {selected.length > 0 && (
        <div className="pb-selbar" data-testid="pb-selbar">
          <span className="num">{t('pb.q.selected', { n: selected.length })}</span>
          <button className="btn sm" onClick={onSchedule} title={t('pb.q.scheduleHint')} data-testid="pb-schedule-sel">
            {t('pb.q.schedule')}
          </button>
          <button className="btn ghost icon sm" onClick={() => (setSelected([]), setSelecting(new Set()))} aria-label={t('pb.q.clear')} data-tip={t('pb.q.clear')}>
            <X className="ico" />
          </button>
        </div>
      )}
    </aside>
  );
}
