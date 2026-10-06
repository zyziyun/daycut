// Segment review (P0-1): the AI's candidate segments on a timeline with the transcript. Accept / reject each,
// drag start / end (snapped to word edges), edit title / hook / notes / tags, then generate the batch.
// Keys: j/k or ↑/↓ move · space accept/reject · [ ] nudge start · { } nudge end · p play the segment.
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { joinWords, nudgeEdge, overlaps, setEdge, wordsIn, type ReviewedSegment, type Word } from '../../../shared/v02';
import { t } from '../i18n';
import { hms } from '../lib/format';

const PAD = 15; // seconds of context around the selected segment

function inInput(e: KeyboardEvent) {
  const el = e.target as HTMLElement;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable;
}

export function SegmentReview({
  source,
  duration,
  words,
  segs,
  onChange,
}: {
  source: string;
  duration: number;
  words: Word[];
  segs: ReviewedSegment[];
  onChange: (s: ReviewedSegment[]) => void;
}) {
  const [sel, setSel] = useState(0);
  const cur = segs[Math.min(sel, segs.length - 1)];
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const over = useMemo(() => overlaps(segs), [segs]);

  const update = (s: ReviewedSegment) => onChange(segs.map((x) => (x.id === s.id ? s : x)));

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (inInput(e) || !cur) return;
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        setSel((i) => Math.min(i + 1, segs.length - 1));
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        setSel((i) => Math.max(i - 1, 0));
      } else if (e.key === ' ') {
        e.preventDefault();
        update({ ...cur, accepted: !cur.accepted });
      } else if (e.key === '[' || e.key === ']') {
        update(setEdge(cur, 'start', nudgeEdge(cur.start, words, 'start', e.key === '[' ? -1 : 1), words));
      } else if (e.key === '{' || e.key === '}') {
        update(setEdge(cur, 'end', nudgeEdge(cur.end, words, 'end', e.key === '{' ? -1 : 1), words));
      } else if (e.key === 'p') play();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  });

  function play(from?: number) {
    const v = video.current;
    if (!v || !cur) return;
    v.currentTime = from ?? cur.start;
    stopAt.current = cur.end;
    void v.play().catch(() => undefined);
  }

  if (!cur) return <div className="muted">{t('seg.none')}</div>;
  const nAcc = segs.filter((s) => s.accepted).length;
  return (
    <div className="col" style={{ gap: 10 }} data-testid="segment-review">
      <Overview duration={duration} segs={segs} sel={cur.id} over={over} onPick={(id) => setSel(segs.findIndex((s) => s.id === id))} />
      <div className="row small muted">
        <span>{t('seg.accepted', { n: nAcc, total: segs.length })}</span>
        <span>
          <kbd>j</kbd>/<kbd>k</kbd> {t('seg.k.move')} <kbd>space</kbd> {t('seg.k.accept')} <kbd>[</kbd>
          <kbd>]</kbd> {t('seg.k.start')} <kbd>{'{'}</kbd>
          <kbd>{'}'}</kbd> {t('seg.k.end')} <kbd>p</kbd> {t('seg.k.play')}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 320px) 1fr', gap: 12, alignItems: 'start' }}>
        <div className="seglist" role="listbox" aria-label={t('seg.list')}>
          {segs.map((s, i) => (
            <div
              key={s.id}
              role="option"
              aria-selected={s.id === cur.id}
              className={`segitem ${s.id === cur.id ? 'on' : ''} ${s.accepted ? 'acc' : 'rej'}`}
              onClick={() => setSel(i)}
            >
              <div className="row">
                <input
                  type="checkbox"
                  checked={s.accepted}
                  aria-label={t('seg.accept')}
                  onChange={() => update({ ...s, accepted: !s.accepted })}
                  onClick={(e) => e.stopPropagation()}
                />
                <b style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title || t('board.untitled')}</b>
                {s.score != null && <span className="muted small">{Math.round(s.score * 100)}</span>}
              </div>
              <div className="muted small mono">
                {hms(s.start)}–{hms(s.end)} · {Math.round(s.end - s.start)}s{s.chapter ? ` · ${s.chapter}` : ''}
              </div>
              {over.has(s.id) && <div className="warnc small">{t('seg.overlap')}</div>}
              {s.risk && <div className="warnc small">{s.risk}</div>}
            </div>
          ))}
        </div>
        <div className="col" style={{ gap: 10 }}>
          <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
            <video
              ref={video}
              className="thumb"
              style={{ width: 260, aspectRatio: '16 / 10' }}
              src={window.desk.mediaUrl(source)}
              preload="metadata"
              controls
              onTimeUpdate={(e) => {
                if (stopAt.current != null && e.currentTarget.currentTime >= stopAt.current) {
                  e.currentTarget.pause();
                  stopAt.current = null;
                }
              }}
            />
            <div className="col" style={{ flex: 1, gap: 6 }}>
              <div className="row">
                <button className={`btn sm ${cur.accepted ? 'primary' : ''}`} onClick={() => update({ ...cur, accepted: !cur.accepted })} data-testid="seg-toggle">
                  {cur.accepted ? t('seg.acceptedOne') : t('seg.rejectedOne')}
                </button>
                <button className="btn sm" onClick={() => play()}>
                  ▶ {t('seg.k.play')}
                </button>
                <span className="mono small muted">
                  {hms(cur.start)}–{hms(cur.end)} ({(cur.end - cur.start).toFixed(1)}s)
                </span>
              </div>
              {cur.why && (
                <div className="small">
                  <span className="muted">{t('seg.why')}:</span> {cur.why}
                </div>
              )}
            </div>
          </div>
          <EdgeEditor seg={cur} words={words} duration={duration} onChange={update} onSeek={(tt) => play(tt)} />
          <div className="card col">
            <label className="small muted" htmlFor="seg-title">
              {t('seg.title')}
            </label>
            <input id="seg-title" className="input" value={cur.title} maxLength={100} onChange={(e) => update({ ...cur, title: e.target.value })} data-testid="seg-title" />
            <span className="small muted">{t('seg.hook')}</span>
            {(cur.hook_candidates ?? []).length > 0 && (
              <div className="col" style={{ gap: 4 }}>
                {(cur.hook_candidates ?? []).map((h, i) => (
                  <label key={i} className="row small">
                    <input type="radio" name={`hook-${cur.id}`} checked={cur.hook?.start === h.start && cur.hook?.end === h.end} onChange={() => update({ ...cur, hook: { ...h } })} />
                    <span className="mono muted">{hms(h.start)}</span> {h.text}
                  </label>
                ))}
              </div>
            )}
            {cur.hook && (
              <input className="input" aria-label={t('seg.hookText')} value={cur.hook.text} maxLength={200} onChange={(e) => update({ ...cur, hook: { ...cur.hook!, text: e.target.value } })} />
            )}
            <label className="small muted" htmlFor="seg-notes">
              {t('seg.notes')}
            </label>
            <textarea
              id="seg-notes"
              className="input"
              rows={3}
              value={(cur.notes ?? []).join('\n')}
              onChange={(e) => update({ ...cur, notes: e.target.value.split('\n').slice(0, 10).map((x) => x.slice(0, 200)) })}
            />
            <label className="small muted" htmlFor="seg-tags">
              {t('seg.tags')}
            </label>
            <input
              id="seg-tags"
              className="input"
              value={(cur.tags ?? []).join(', ')}
              onChange={(e) =>
                update({
                  ...cur,
                  tags: e.target.value
                    .split(/[,，、]/)
                    .map((x) => x.trim().replace(/^#/, ''))
                    .filter(Boolean)
                    .slice(0, 20),
                })
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function Overview({ duration, segs, sel, over, onPick }: { duration: number; segs: ReviewedSegment[]; sel: string; over: Set<string>; onPick: (id: string) => void }) {
  const d = Math.max(1, duration);
  return (
    <div className="overview" aria-label={t('seg.timeline')}>
      {segs.map((s) => (
        <button
          key={s.id}
          className={`blk ${s.accepted ? 'acc' : ''} ${s.id === sel ? 'on' : ''} ${over.has(s.id) ? 'over' : ''}`}
          style={{ left: `${(100 * s.start) / d}%`, width: `${Math.max(0.4, (100 * (s.end - s.start)) / d)}%` }}
          title={`${s.title} · ${hms(s.start)}–${hms(s.end)}`}
          onClick={() => onPick(s.id)}
        />
      ))}
      <span className="tick l">0:00</span>
      <span className="tick r">{hms(d)}</span>
    </div>
  );
}

/** Zoomed track around one segment: drag the edges (snapped to word edges), click a word to seek. */
export function EdgeEditor<S extends { start: number; end: number }>({
  seg,
  words,
  duration,
  onChange,
  onSeek,
}: {
  seg: S;
  words: Word[];
  duration: number;
  onChange: (s: S) => void;
  onSeek?: (t: number) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<null | 'start' | 'end'>(null);
  const [view, setView] = useState({ a: 0, b: 1 });
  // the window follows the segment unless an edge is being dragged
  useEffect(() => {
    if (!drag) setView({ a: Math.max(0, seg.start - PAD), b: Math.min(Math.max(duration, seg.end), seg.end + PAD) });
  }, [seg.start, seg.end, duration, drag]);
  const { a, b } = view;
  const span = Math.max(1, b - a);
  const ctx = useMemo(() => wordsIn(words, a, b), [words, a, b]);
  const pos = (tt: number) => `${(100 * (tt - a)) / span}%`;
  const at = (clientX: number) => {
    const r = track.current!.getBoundingClientRect();
    return a + ((clientX - r.left) / r.width) * span;
  };
  const move = (e: ReactPointerEvent) => {
    if (!drag) return;
    onChange(setEdge(seg, drag, at(e.clientX), words));
  };
  const handle = (edge: 'start' | 'end') => ({
    onPointerDown: (e: ReactPointerEvent) => {
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      setDrag(edge);
    },
    onPointerMove: move,
    onPointerUp: () => setDrag(null),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        e.stopPropagation();
        const v = edge === 'start' ? seg.start : seg.end;
        onChange(setEdge(seg, edge, nudgeEdge(v, words, edge, e.key === 'ArrowLeft' ? -1 : 1), words));
      }
    },
  });
  const inside = wordsIn(words, seg.start, seg.end);
  return (
    <div className="card col" style={{ gap: 6 }}>
      <div className="edgetrack" ref={track}>
        {ctx.map((w, i) => (
          <i key={i} className="wtick" style={{ left: pos(w.t), width: `${(100 * (w.te - w.t)) / span}%` }} />
        ))}
        <div className="sel" style={{ left: pos(seg.start), width: `${(100 * (seg.end - seg.start)) / span}%` }} />
        <div className="hdl" role="slider" tabIndex={0} aria-label={t('seg.start')} aria-valuenow={seg.start} style={{ left: pos(seg.start) }} {...handle('start')} data-testid="edge-start" />
        <div className="hdl" role="slider" tabIndex={0} aria-label={t('seg.end')} aria-valuenow={seg.end} style={{ left: pos(seg.end) }} {...handle('end')} data-testid="edge-end" />
      </div>
      <div className="transcript small" style={{ fontSize: 13, lineHeight: 1.9, maxHeight: 140, overflow: 'auto' }}>
        {ctx.map((w, i) => {
          const mid = (w.t + w.te) / 2;
          const inSeg = mid >= seg.start && mid <= seg.end;
          return (
            <span
              key={i}
              className={`w ${inSeg ? '' : 'out'}`}
              title={`${w.t.toFixed(2)}s`}
              onClick={(e) => {
                if (e.altKey || e.shiftKey) onChange(setEdge(seg, e.altKey ? 'start' : 'end', e.altKey ? w.t : w.te, words));
                else onSeek?.(w.t);
              }}
            >
              {w.w}
            </span>
          );
        })}
      </div>
      <div className="muted small">
        {t('seg.edgeHint')} · {joinWords(inside).length} {t('seg.chars')}
      </div>
    </div>
  );
}
