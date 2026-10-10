// The editor's timeline: a fixed gutter with the lane names, then (scrolling when zoomed) a time ruler with adaptive
// ticks, the filmstrip (sprite sheet tiles), the waveform from real audio peaks, the transcript words at their times
// (drag across them to select; 「听一遍这条片子」 when there are none yet), the effects lane (drag to move, edges to
// resize), trim handles, cuts, draft (amber) / applied (teal) markers and the playhead across every lane (drag it, or
// the ruler, to scrub). Zoom: − / Fit / +, ⌘+ / ⌘− / ⌘0, pinch; the view follows the playhead while playing.
// Thumbnails, waveform columns and words are only drawn for the visible stretch, so 10+ minute outputs stay fluid.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AudioLines, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import type { StripInfo, TranscribeState } from '../../../shared/timeline';
import type { EffectDef, EffectInstance, OutputDoc } from '../../../shared/v04';
import { t } from '../i18n';
import {
  clampPps,
  fitPps,
  fitText,
  isCut,
  listenEstimate,
  mergeWords,
  moveEffect,
  peakColumns,
  resizeEffect,
  rulerTicks,
  snapEdge,
  snapRange,
  stackRows,
  tileAt,
  tileOffset,
  wordsIn,
  zoomAt,
} from '../lib/timeline';
import { isTyping } from './ui';
import { media } from './kit';
import { effectLabel } from './msg';
import './timeline.css';
import { keyHint } from '../lib/keys';

export interface TimelineMarker {
  id: string;
  a: number;
  b: number;
  tone: 'draft' | 'applied';
  turn?: string;
  kind: string;
}

export interface TimelineProps {
  doc: OutputDoc;
  time: number;
  playing?: boolean;
  selection: { a: number; b: number } | null;
  selectedFx: string | null;
  onSeek: (t: number) => void;
  onSelect: (s: { a: number; b: number } | null) => void;
  onSelectFx: (id: string | null) => void;
  onMoveFx: (fx: EffectInstance, start: number, end: number) => void;
  onTrim: (start: number, end: number) => void;
  /** chat cards on the timeline: amber = a draft change, teal = applied; a click opens the card */
  markers?: TimelineMarker[];
  onMarker?: (turn: string) => void;
  strip?: StripInfo | null;
  stripFailed?: boolean;
  transcribe?: { state: TranscribeState; start: () => void } | null;
  defs?: EffectDef[];
  /** left side of the bar above the lanes (legend / hint) */
  header?: ReactNode;
  /** ⌘+ / ⌘− / ⌘0 and pinch (off when another view owns the keyboard) */
  keys?: boolean;
  /** pending transcript cuts (red hatch across every lane, the same as the transcript's strike-through) */
  pending?: [number, number][];
  /** grow the lanes with the space the lower pane gives (the editor's split); the base heights are the minimum */
  fill?: boolean;
}

const GUTTER = 76;

/** Seconds of [a, b] left after the cuts. */
function keptOf(a: number, b: number, cuts: [number, number][]): number {
  let cut = 0;
  for (const [x, y] of cuts) cut += Math.max(0, Math.min(b, y) - Math.max(a, x));
  return Math.max(0, b - a - cut);
}
const H = { ruler: 24, film: 46, wave: 40, words: 30, fxRow: 24 };
const OVERSCAN = 240; // px drawn beyond each edge of the viewport

export function Timeline(p: TimelineProps) {
  const { doc, time, selection, selectedFx, onSeek, onSelect, onSelectFx, onMoveFx, onTrim, markers, onMarker, strip } = p;
  const view = useRef<HTMLDivElement | null>(null);
  const [vw, setVw] = useState(0);
  const [scroll, setScroll] = useState(0);
  const D = Math.max(0.1, doc.duration || strip?.duration || 1);
  // zoom: pixels per second, null = fit; kept for the session
  const [zoom, setZoom] = useState<number | null>(() => {
    const v = sessionStorage.getItem('v4.tlzoom2');
    return !v || v === 'fit' ? null : Number(v) || null;
  });
  useEffect(() => sessionStorage.setItem('v4.tlzoom2', zoom === null ? 'fit' : String(zoom)), [zoom]);
  useLayoutEffect(() => {
    const el = view.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setVw(el.clientWidth));
    ro.observe(el);
    setVw(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const width = vw || 800;
  const fit = fitPps(D, width);
  const pps = zoom === null ? fit : clampPps(zoom, D, width);
  const W = Math.max(width, Math.round(D * pps));
  const x = useCallback((s: number) => s * pps, [pps]);
  const tAtClient = (clientX: number) => {
    const r = view.current?.getBoundingClientRect();
    const px = clientX - (r?.left ?? 0) + (view.current?.scrollLeft ?? 0);
    return Math.min(D, Math.max(0, px / pps));
  };
  const t0 = Math.max(0, (scroll - OVERSCAN) / pps);
  const t1 = Math.min(D, (scroll + width + OVERSCAN) / pps);

  // zoom, keeping an anchor (the cursor, else the playhead) in place
  const pendingScroll = useRef<number | null>(null);
  const zoomBy = useCallback(
    (factor: number, anchorPx?: number) => {
      const el = view.current;
      if (!el) return;
      const anchor = anchorPx ?? Math.min(width, Math.max(0, time * pps - el.scrollLeft));
      const z = zoomAt(pps, factor, el.scrollLeft, anchor, D, width);
      pendingScroll.current = z.scrollLeft;
      setZoom(z.pps <= fit * 1.001 ? null : z.pps);
    },
    [pps, D, width, fit, time],
  );
  useLayoutEffect(() => {
    if (pendingScroll.current == null || !view.current) return;
    view.current.scrollLeft = pendingScroll.current;
    setScroll(view.current.scrollLeft);
    pendingScroll.current = null;
  }, [pps]);
  // ⌘+ / ⌘− / ⌘0
  const keys = p.keys !== false;
  useEffect(() => {
    if (!keys) return;
    const on = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || isTyping(e.target)) return;
      if (document.querySelector('.scrim, .ctx')) return;
      if (e.key === '=' || e.key === '+') zoomBy(2);
      else if (e.key === '-' || e.key === '_') zoomBy(0.5);
      else if (e.key === '0') setZoom(null);
      else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener('keydown', on, true);
    return () => window.removeEventListener('keydown', on, true);
  }, [keys, zoomBy]);
  // pinch (ctrl + wheel) zooms at the cursor; a vertical wheel scrolls sideways when zoomed
  const zoomRef = useRef(zoomBy);
  zoomRef.current = zoomBy;
  useEffect(() => {
    const el = view.current;
    if (!el) return;
    const on = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        zoomRef.current(Math.exp(-e.deltaY * 0.01), e.clientX - el.getBoundingClientRect().left);
      } else if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && el.scrollWidth > el.clientWidth + 1) {
        e.preventDefault();
        el.scrollLeft += e.deltaY;
      }
    };
    el.addEventListener('wheel', on, { passive: false });
    return () => el.removeEventListener('wheel', on);
  }, []);

  // drags: word selection, effect move / resize, trim handles, the playhead / ruler scrub
  const [drag, setDrag] = useState<
    | { kind: 'sel'; a: number }
    | { kind: 'fx'; fx: EffectInstance; edge: 'm' | 'l' | 'r'; t0: number; cur: { start: number; end: number } }
    | { kind: 'trim'; edge: 'l' | 'r'; cur: number }
    | { kind: 'head' }
    | null
  >(null);
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const tt = tAtClient(e.clientX);
      if (drag.kind === 'head') onSeek(tt);
      else if (drag.kind === 'sel') {
        const r = snapRange(doc.words, drag.a, tt);
        onSelect(r ? { a: r.a, b: r.b } : { a: Math.min(drag.a, tt), b: Math.max(drag.a, tt) });
      } else if (drag.kind === 'fx') {
        const cur = drag.edge === 'm' ? moveEffect(drag.fx, tt - drag.t0, D) : resizeEffect(drag.fx, drag.edge, tt, D);
        setDrag({ ...drag, cur });
      } else setDrag({ ...drag, cur: snapEdge(doc.words, tt) });
    };
    const up = () => {
      if (drag.kind === 'fx' && (drag.cur.start !== drag.fx.start || drag.cur.end !== drag.fx.end)) onMoveFx(drag.fx, drag.cur.start, drag.cur.end);
      if (drag.kind === 'trim') {
        const a = doc.trim?.start ?? 0;
        const b = doc.trim?.end ?? D;
        if (drag.edge === 'l') onTrim(Math.min(drag.cur, b - 0.5), b);
        else onTrim(a, Math.max(drag.cur, a + 0.5));
      }
      setDrag(null);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up, { once: true });
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, doc, pps]);

  // follow the playhead while playing (unless she just scrolled by hand)
  const manual = useRef(0);
  const ours = useRef(false);
  useEffect(() => {
    const el = view.current;
    if (!el || W <= width + 1) return;
    const px = time * pps;
    const out = px < el.scrollLeft + 8 || px > el.scrollLeft + width - 24;
    if (!out) return;
    if (p.playing && Date.now() - manual.current < 1500) return;
    if (!p.playing && drag?.kind !== 'head') {
      // stepping / seeking while paused: bring it into view only when it left it
      if (px >= el.scrollLeft && px <= el.scrollLeft + width) return;
    }
    ours.current = true;
    el.scrollLeft = Math.max(0, p.playing ? px - width * 0.12 : px - width / 2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [time, pps, width, W, p.playing]);

  const fx = useMemo(() => stackRows(doc.effects.map((e) => (drag?.kind === 'fx' && drag.fx.id === e.id ? { ...e, ...drag.cur } : e))), [doc.effects, drag]);
  const rows = Math.max(1, ...fx.map((e) => e.row + 1));
  const fxH = rows * H.fxRow + 8;
  // lanes grow with the pane (up to 2.4x, words up to 1.5x): a tall lower pane is not empty space
  const [avail, setAvail] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const el = rootRef.current?.parentElement;
    if (!p.fill || !el) return;
    const ro = new ResizeObserver(() => setAvail(el.clientHeight));
    ro.observe(el);
    setAvail(el.clientHeight);
    return () => ro.disconnect();
  }, [p.fill]);
  const sc = p.fill && avail ? Math.min(2.4, Math.max(1, (avail - 64 - H.ruler - fxH) / (H.film + H.wave + H.words))) : 1;
  const L = { film: Math.round(H.film * sc), wave: Math.round(H.wave * sc), words: Math.round(H.words * Math.min(sc, 1.5)) };
  const trimA = drag?.kind === 'trim' && drag.edge === 'l' ? drag.cur : (doc.trim?.start ?? 0);
  const trimB = drag?.kind === 'trim' && drag.edge === 'r' ? drag.cur : (doc.trim?.end ?? D);
  const cats = useMemo(() => new Map((p.defs ?? []).map((d) => [d.id, d.category ?? 'other'])), [p.defs]);
  const [hover, setHover] = useState<number | null>(null);

  const seekDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    onSeek(tAtClient(e.clientX));
    setDrag({ kind: 'head' });
  };
  const ticks = useMemo(() => rulerTicks(pps, t0, t1), [pps, t0, t1]);
  const visWords = useMemo(() => {
    const vis = wordsIn(doc.words, t0, t1).map((v) => v.w);
    return pps < 40 ? mergeWords(vis, pps) : vis;
  }, [doc.words, t0, t1, pps]);
  const tr = p.transcribe;
  const est = listenEstimate(D);
  const lanesTop = H.ruler;
  const lanesH = L.film + L.wave + L.words + fxH;

  return (
    <div className="tl2" ref={rootRef} data-testid="timeline" style={{ ['--tl-g' as string]: `${GUTTER}px` }}>
      <div className="tl2-bar">
        <div className="lead">{p.header}</div>
        <div className="zm" role="group" aria-label={t('tl.fit')}>
          <button className="btn ghost icon sm" onClick={() => zoomBy(0.5)} disabled={zoom === null} aria-label={t('tl.zoomOut')} data-tip={`${t('tl.zoomOut')} · ${keyHint('⌘−')}`} data-testid="tl-zoom-out">
            <ZoomOut className="ico" />
          </button>
          <button className={`btn ghost sm fitb ${zoom === null ? 'on' : ''}`} onClick={() => setZoom(null)} aria-pressed={zoom === null} data-tip={`${t('tl.fitTip')} · ${keyHint('⌘0')}`} data-testid="tl-fit">
            {t('tl.fit')}
          </button>
          <button className="btn ghost icon sm" onClick={() => zoomBy(2)} disabled={pps >= 399} aria-label={t('tl.zoomIn')} data-tip={`${t('tl.zoomIn')} · ${keyHint('⌘+')}`} data-testid="tl-zoom-in">
            <ZoomIn className="ico" />
          </button>
        </div>
      </div>
      <div className="tl2-body">
        <div className="tl2-gutter" aria-hidden="true">
          <span style={{ height: H.ruler }} />
          <span style={{ height: L.film }}>{t('tl.lane.video')}</span>
          <span style={{ height: L.wave }}>{t('tl.lane.audio')}</span>
          <span style={{ height: L.words }}>{t('tl.lane.words')}</span>
          <span style={{ height: fxH }}>{t('tl.lane.fx')}</span>
        </div>
        <div
          className="tl2-view"
          ref={view}
          onScroll={(e) => {
            setScroll(e.currentTarget.scrollLeft);
            if (ours.current) ours.current = false;
            else manual.current = Date.now();
          }}
          onPointerMove={(e) => setHover(tAtClient(e.clientX))}
          onPointerLeave={() => setHover(null)}
          data-testid="tl-view"
          data-pps={pps.toFixed(3)}
        >
          <div className="tl2-content" style={{ width: W, height: lanesTop + lanesH }}>
            {/* ruler: click / drag scrubs */}
            <div className="ruler" style={{ height: H.ruler }} onPointerDown={seekDown} data-testid="tl-ruler">
              {ticks.minor.map((m) => (
                <i key={`m${m}`} className="mi" style={{ left: x(m) }} />
              ))}
              {ticks.major.map((m) => (
                <span key={`M${m.t}`} className="mj" style={{ left: x(m.t) }}>
                  <i />
                  <b className="num">{m.label}</b>
                </span>
              ))}
              {(markers ?? [])
                .filter((m) => m.tone === 'applied')
                .map((m) => (
                  <i
                    key={m.id}
                    className="amk"
                    style={{ left: x(m.a), width: Math.max(4, x(m.b) - x(m.a)) }}
                    onPointerDown={(e) => {
                      if (!m.turn || !onMarker) return;
                      e.stopPropagation();
                      onMarker(m.turn);
                    }}
                    data-testid="tl-marker-applied"
                  />
                ))}
            </div>
            {/* filmstrip */}
            <div className="ln film" style={{ top: lanesTop, height: L.film }} onPointerDown={seekDown} data-testid="tl-film" data-ready={strip?.sprite ? '1' : '0'}>
              <Film strip={strip ?? null} failed={!!p.stripFailed} pps={pps} W={W} from={scroll - OVERSCAN} to={scroll + width + OVERSCAN} h={L.film} />
            </div>
            {/* waveform */}
            <div className="ln wave" style={{ top: lanesTop + L.film, height: L.wave }} onPointerDown={seekDown} data-testid="tl-wave">
              <Wave strip={strip ?? null} pps={pps} scroll={scroll} width={width} h={L.wave} time={time} />
            </div>
            {/* transcript */}
            <div
              className="ln words"
              style={{ top: lanesTop + L.film + L.wave, height: L.words }}
              onPointerDown={(e) => {
                if (e.button !== 0 || (e.target as HTMLElement).closest('.listen')) return;
                const wt = (e.target as HTMLElement).dataset?.t; // a click on a word seeks to its first frame
                const a = wt ? Number(wt) : tAtClient(e.clientX);
                onSeek(a);
                onSelect(null);
                if (doc.words.length) setDrag({ kind: 'sel', a });
              }}
              data-testid="tl-words"
            >
              {visWords.map((wd) => {
                const left = x(wd.t);
                const w = Math.max(2, x(wd.te) - left - 1);
                const sel = selection && wd.t >= selection.a - 0.01 && wd.te <= selection.b + 0.01;
                return (
                  <span key={`${wd.t}`} className={`w ${sel ? 'sel' : ''} ${isCut(wd.t, wd.te, doc.cuts) ? 'cut' : ''} ${w < 14 ? 'tiny' : ''}`} style={{ left, width: w }} title={wd.w} data-t={wd.t}>
                    {w >= 14 ? fitText(wd.w, w - 6) : ''}
                  </span>
                );
              })}
              {!doc.words.length && (
                <div className="listen" style={{ left: Math.max(0, scroll) + 8 }}>
                  {!tr ? null : tr.state.state === 'running' ? (
                    <span className="busy" data-testid="tl-listening">
                      <i className="sk-bars" />
                      {t('tl.listening', { s: est })}
                    </span>
                  ) : tr.state.state === 'failed' ? (
                    <span className="fail">
                      {t('tl.listenFailed', { e: tr.state.error ?? '' })}
                      <button className="btn ghost sm" onClick={tr.start} data-testid="tl-transcribe-retry">
                        <RotateCcw className="ico" />
                        {t('tl.retry')}
                      </button>
                    </span>
                  ) : (
                    <button className="btn sm" onClick={tr.start} data-testid="tl-transcribe">
                      <AudioLines className="ico" />
                      {t('tl.listen', { s: est })}
                    </button>
                  )}
                </div>
              )}
            </div>
            {/* effects */}
            <div
              className="ln fxl"
              style={{ top: lanesTop + L.film + L.wave + L.words, height: fxH }}
              onPointerDown={(e) => {
                if (e.target !== e.currentTarget) return;
                onSelectFx(null);
                seekDown(e);
              }}
              data-testid="tl-fx"
            >
              {!fx.length && (
                <span className="none" style={{ left: Math.max(0, scroll) + 10 }}>
                  {t('tl.noFx')}
                </span>
              )}
              {fx.map((e) => {
                const left = x(e.start);
                const w = Math.max(10, x(e.end) - left);
                const name = effectLabel(e.effect, e.label);
                const text = typeof e.params?.text === 'string' && e.params.text ? e.params.text : '';
                const grab = (edge: 'm' | 'l' | 'r') => (ev: React.PointerEvent) => {
                  if (ev.button !== 0) return;
                  ev.stopPropagation();
                  onSelectFx(e.id);
                  const orig = doc.effects.find((y) => y.id === e.id)!;
                  setDrag({ kind: 'fx', fx: orig, edge, t0: edge === 'm' ? tAtClient(ev.clientX) : 0, cur: { start: e.start, end: e.end } });
                };
                // a pending transcript cut shortens / removes this effect: amber dashed, said in the tooltip
                const kept = (p.pending ?? []).length ? keptOf(e.start, e.end, p.pending ?? []) : null;
                const hit = kept != null && kept < e.end - e.start - 0.02;
                const why = hit ? (kept < 0.4 ? t('te.fxRemoved') : t('te.fxShorter', { a: (e.end - e.start).toFixed(1), b: kept.toFixed(1) })) : '';
                return (
                  <div
                    key={e.id}
                    className={`fxb c-${cats.get(e.effect) ?? 'other'} ${selectedFx === e.id ? 'on' : ''} ${e.id.startsWith('preview') || hit ? 'draft' : ''}`}
                    style={{ left, width: w, top: 4 + e.row * H.fxRow }}
                    onPointerDown={grab('m')}
                    title={[text ? `${name} · ${text}` : name, why].filter(Boolean).join(' — ')}
                    data-hit={hit ? '1' : undefined}
                    data-testid="fx-block"
                    data-fx={e.effect}
                  >
                    <i className="hd l" onPointerDown={grab('l')} />
                    {w >= 30 && <span className="nm">{fitText(name, w - 18)}</span>}
                    {text && w >= 30 + name.length * 12 + 20 && <span className="tx">{text}</span>}
                    <i className="hd r" onPointerDown={grab('r')} />
                  </div>
                );
              })}
            </div>
            {/* overlays across the lanes */}
            <div className="ovl" style={{ top: lanesTop, height: lanesH }}>
              {trimA > 0.01 && <div className="trimz" style={{ left: 0, width: x(trimA) }} />}
              {trimB < D - 0.01 && <div className="trimz" style={{ left: x(trimB), right: 0 }} />}
              {doc.cuts.map((c) => (
                <div key={c.index} className="cutz" style={{ left: x(c.start), width: Math.max(2, x(c.end) - x(c.start)) }} />
              ))}
              {(p.pending ?? []).map(([a, b], k) => (
                <div key={`p${k}`} className="cutz pend" style={{ left: x(a), width: Math.max(3, x(b) - x(a)) }} data-testid="tl-pending" />
              ))}
              {(markers ?? [])
                .filter((m) => m.tone === 'draft' || m.kind === 'cut')
                .map((m) => (
                  <div
                    key={m.id}
                    className={`tmk ${m.tone} ${m.kind}`}
                    style={{ left: x(m.a), width: Math.max(3, x(m.b) - x(m.a)) }}
                    onPointerDown={(e) => {
                      if (!m.turn || !onMarker) return;
                      e.stopPropagation();
                      onMarker(m.turn);
                    }}
                    data-testid={`tl-marker-${m.tone}`}
                  />
                ))}
              {selection && <div className="selz" style={{ left: x(selection.a), width: Math.max(2, x(selection.b) - x(selection.a)) }} data-testid="tl-selection" />}
              <div className="trimh l" style={{ left: x(trimA) }} onPointerDown={(e) => (e.stopPropagation(), setDrag({ kind: 'trim', edge: 'l', cur: trimA }))} data-testid="trim-in" />
              <div className="trimh r" style={{ left: x(trimB) }} onPointerDown={(e) => (e.stopPropagation(), setDrag({ kind: 'trim', edge: 'r', cur: trimB }))} data-testid="trim-out" />
            </div>
            {hover != null && !drag && <i className="hov" style={{ left: x(hover), height: lanesTop + lanesH }} />}
            <div
              className={`phead ${drag?.kind === 'head' ? 'drag' : ''}`}
              style={{ left: x(Math.min(time, D)), height: lanesTop + lanesH }}
              onPointerDown={(e) => {
                if (e.button !== 0) return;
                e.stopPropagation();
                setDrag({ kind: 'head' });
              }}
              role="slider"
              aria-label={t('tl.playhead')}
              aria-valuemin={0}
              aria-valuemax={Math.round(D)}
              aria-valuenow={Math.round(time)}
              data-testid="tl-playhead"
            >
              <i className="knob" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Filmstrip: tiles of the lane's height laid edge to edge, each showing the frame at its start; only the visible
 * ones are in the DOM. A shimmer while the sprite is being made. */
function Film({ strip, failed, pps, W, from, to, h }: { strip: StripInfo | null; failed: boolean; pps: number; W: number; from: number; to: number; h: number }) {
  if (!strip?.sprite) return <div className={`film-sk ${failed ? 'off' : ''}`} aria-label={failed ? undefined : t('tl.loading')} />;
  const [tw, th] = strip.tile;
  const scale = h / th;
  const dw = Math.max(8, tw * scale);
  const n = Math.ceil(W / dw);
  const k0 = Math.max(0, Math.floor(from / dw));
  const k1 = Math.min(n - 1, Math.ceil(to / dw));
  const url = `url("${media(strip.sprite)}")`;
  const size = `${strip.cols * tw * scale}px auto`;
  const out: ReactNode[] = [];
  for (let k = k0; k <= k1; k++) {
    const o = tileOffset(tileAt((k * dw) / pps, strip), strip);
    out.push(<i key={k} style={{ left: k * dw, width: Math.min(dw, W - k * dw), backgroundImage: url, backgroundSize: size, backgroundPosition: `-${o.x * scale}px -${o.y * scale}px` }} />);
  }
  return <>{out}</>;
}

/** Waveform: a canvas the size of the viewport (it rides along with the scroll), one mirrored bar per 2 px. */
function Wave({ strip, pps, scroll, width, h, time }: { strip: StripInfo | null; pps: number; scroll: number; width: number; h: number; time: number }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const peaks = strip?.peaks;
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.max(1, Math.round(width * dpr));
    c.height = Math.round(h * dpr);
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    if (!peaks?.length) return;
    ctx.fillStyle = getComputedStyle(c).getPropertyValue('--text').trim() || '#d8d4cf';
    // zoomed in: one bar per 3 px; fitted: a smooth mirrored envelope (calmer than a comb of bars)
    const bars = pps >= 120;
    const step = bars ? 3 : 1;
    const cols = peakColumns(peaks, strip?.peaks_rate ?? 50, scroll / pps, pps / step, Math.ceil(width / step));
    const mid = c.height / 2;
    const amp = (v: number) => Math.max(dpr * 0.5, (v * (c.height - 4 * dpr)) / 2);
    const playedX = (time * pps - scroll) * dpr;
    const paint = (alpha: number, clip: [number, number]) => {
      ctx.save();
      ctx.beginPath();
      ctx.rect(clip[0], 0, clip[1] - clip[0], c.height);
      ctx.clip();
      ctx.globalAlpha = alpha;
      if (bars) {
        for (let i = 0; i < cols.length; i++) {
          const a = amp(cols[i]);
          ctx.fillRect(Math.round(i * step * dpr), Math.round(mid - a), Math.max(1, Math.round(2 * dpr)), Math.max(1, Math.round(2 * a)));
        }
      } else {
        ctx.beginPath();
        ctx.moveTo(0, mid);
        for (let i = 0; i < cols.length; i++) ctx.lineTo(i * dpr, mid - amp(cols[i]));
        for (let i = cols.length - 1; i >= 0; i--) ctx.lineTo(i * dpr, mid + amp(cols[i]));
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();
    };
    paint(0.62, [0, Math.max(0, Math.min(c.width, playedX))]);
    paint(0.3, [Math.max(0, Math.min(c.width, playedX)), c.width]);
  }, [peaks, strip?.peaks_rate, pps, scroll, width, h, time]);
  if (strip && !strip.has_audio) return <span className="none">{t('tl.noAudio')}</span>;
  if (!strip) return <div className="wave-sk" />;
  return <canvas ref={ref} className="wavec" style={{ left: scroll, width, height: h }} />;
}
