// The editor's timeline strip: frame thumbnails, a waveform, the transcript words (drag to select, snapped to
// words), the effects lane (drag to move, edges to resize), trim handles, inner cuts and the playhead.
import { useEffect, useMemo, useRef, useState } from 'react';
import type { EffectInstance, OutputDoc } from '../../../shared/v04';
import { t } from '../i18n';
import { isCut, moveEffect, resizeEffect, snapEdge, snapRange, stackRows, toT, toX } from '../lib/timeline';
import { ZoomIn, ZoomOut } from 'lucide-react';
import { media } from './kit';
import { effectLabel } from './msg';

export interface TimelineProps {
  doc: OutputDoc;
  time: number;
  selection: { a: number; b: number } | null;
  selectedFx: string | null;
  onSeek: (t: number) => void;
  onSelect: (s: { a: number; b: number } | null) => void;
  onSelectFx: (id: string | null) => void;
  onMoveFx: (fx: EffectInstance, start: number, end: number) => void;
  onTrim: (start: number, end: number) => void;
}

export function Timeline({ doc, time, selection, selectedFx, onSeek, onSelect, onSelectFx, onMoveFx, onTrim }: TimelineProps) {
  const view = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const [vw, setVw] = useState(800);
  const D = doc.duration || 1;
  // zoom: pixels per second (null = fit the whole clip); words need ~60 px/s to be readable
  const [pps, setPps] = useState<number | null>(() => {
    const v = sessionStorage.getItem('v4.tlzoom');
    return v === 'fit' ? null : v ? Number(v) : 60;
  });
  useEffect(() => sessionStorage.setItem('v4.tlzoom', pps === null ? 'fit' : String(pps)), [pps]);
  useEffect(() => {
    const el = view.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setVw(el.clientWidth));
    ro.observe(el);
    setVw(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const w = pps ? Math.max(vw, Math.round(D * pps)) : vw;
  const x = (s: number) => toX(s, D, w);
  const tAt = (clientX: number) => toT(clientX - (box.current?.getBoundingClientRect().left ?? 0), D, w);
  // keep the playhead in view while playing / stepping
  useEffect(() => {
    const el = view.current;
    if (!el || w <= vw) return;
    const px = x(time);
    if (px < el.scrollLeft + 24 || px > el.scrollLeft + vw - 24) el.scrollLeft = Math.max(0, px - vw / 3);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [time, w, vw]);

  // drags: word selection, effect move / resize, trim handles
  const [drag, setDrag] = useState<
    | { kind: 'sel'; a: number }
    | { kind: 'fx'; fx: EffectInstance; edge: 'm' | 'l' | 'r'; t0: number; cur: { start: number; end: number } }
    | { kind: 'trim'; edge: 'l' | 'r'; cur: number }
    | null
  >(null);
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const tt = tAt(e.clientX);
      if (drag.kind === 'sel') {
        const r = snapRange(doc.words, drag.a, tt);
        onSelect(r ? { a: r.a, b: r.b } : { a: Math.min(drag.a, tt), b: Math.max(drag.a, tt) });
      } else if (drag.kind === 'fx') {
        const cur = drag.edge === 'm' ? moveEffect(drag.fx, tt - drag.t0, D) : resizeEffect(drag.fx, drag.edge, tt, D);
        setDrag({ ...drag, cur });
      } else {
        setDrag({ ...drag, cur: snapEdge(doc.words, tt) });
      }
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
  }, [drag, doc, w]);

  const fx = useMemo(() => stackRows(doc.effects.map((e) => (drag?.kind === 'fx' && drag.fx.id === e.id ? { ...e, ...drag.cur } : e))), [doc.effects, drag]);
  const rows = Math.max(1, ...fx.map((e) => e.row + 1));
  const trimA = drag?.kind === 'trim' && drag.edge === 'l' ? drag.cur : (doc.trim?.start ?? 0);
  const trimB = drag?.kind === 'trim' && drag.edge === 'r' ? drag.cur : (doc.trim?.end ?? D);

  return (
    <div className="tline" data-testid="timeline">
      <div className="tlzoom">
        <button className="btn ghost icon sm" onClick={() => setPps((p) => (p ? Math.max(10, p / 2) : Math.max(10, (vw / D) * 2)))} aria-label={t('editor.zoomOut')} data-tip={t('editor.zoomOut')} disabled={!pps}>
          <ZoomOut className="ico" />
        </button>
        <button className={`btn ghost sm ${pps ? '' : 'toggle on'}`} onClick={() => setPps(null)} data-testid="tl-fit">
          {t('editor.zoomFit')}
        </button>
        <button className="btn ghost icon sm" onClick={() => setPps((p) => Math.min(400, (p ?? vw / D) * 2))} aria-label={t('editor.zoomIn')} data-tip={t('editor.zoomIn')}>
          <ZoomIn className="ico" />
        </button>
      </div>
      <div className="tlview" ref={view}>
      <div className="rows" ref={box} style={{ width: w }}>
        <div className="tlane" onPointerDown={(e) => e.button === 0 && onSeek(tAt(e.clientX))}>
          <Thumbs file={doc.files[0]?.path ?? null} duration={D} width={w} />
        </div>
        <div className="tlane" onPointerDown={(e) => e.button === 0 && onSeek(tAt(e.clientX))}>
          <span className="lbl">{t('editor.tl.audio')}</span>
          <Wave data={doc.waveform} width={w} />
        </div>
        <div
          className="tlane words"
          onPointerDown={(e) => {
            if (e.button !== 0) return;
            const wt = (e.target as HTMLElement).dataset?.t; // a click on a word seeks to its first frame
            const a = wt ? Number(wt) : tAt(e.clientX);
            onSeek(a);
            onSelect(null);
            setDrag({ kind: 'sel', a });
          }}
          data-testid="tl-words"
        >
          {!doc.words.length && <span className="lbl">{t('editor.tl.words')}</span>}
          {doc.words.map((wd, i) => {
            const left = x(wd.t);
            const width = Math.max(2, x(wd.te) - left);
            const sel = selection && wd.t >= selection.a - 0.01 && wd.te <= selection.b + 0.01;
            return (
              <span key={i} className={`w ${sel ? 'sel' : ''} ${isCut(wd.t, wd.te, doc.cuts) ? 'cut' : ''}`} style={{ left, width }} title={wd.w} data-t={wd.t}>
                {width >= wd.w.length * 11 ? wd.w : width >= 12 ? wd.w.slice(0, Math.floor(width / 11)) : ''}
              </span>
            );
          })}
        </div>
        <div className="tlane fxl" style={{ height: rows * 24 + 4 }} onPointerDown={(e) => e.target === e.currentTarget && (onSelectFx(null), onSeek(tAt(e.clientX)))} data-testid="tl-fx">
          {!fx.length && <span className="lbl">{t('editor.tl.fx')}</span>}
          {fx.map((e) => {
            const left = x(e.start);
            const width = Math.max(14, x(e.end) - left);
            return (
              <div
                key={e.id}
                className={`fxb ${selectedFx === e.id ? 'on' : ''}`}
                style={{ left, width, top: 2 + e.row * 24 }}
                onPointerDown={(ev) => {
                  ev.stopPropagation();
                  onSelectFx(e.id);
                  setDrag({ kind: 'fx', fx: doc.effects.find((y) => y.id === e.id)!, edge: 'm', t0: tAt(ev.clientX), cur: { start: e.start, end: e.end } });
                }}
                title={effectLabel(e.effect, e.label)}
                data-testid="fx-block"
                data-fx={e.effect}
              >
                <i
                  className="hd l"
                  onPointerDown={(ev) => {
                    ev.stopPropagation();
                    onSelectFx(e.id);
                    setDrag({ kind: 'fx', fx: doc.effects.find((y) => y.id === e.id)!, edge: 'l', t0: 0, cur: { start: e.start, end: e.end } });
                  }}
                />
                {effectLabel(e.effect, e.label)}
                {typeof e.params?.text === 'string' && e.params.text ? ` · ${e.params.text}` : ''}
                <i
                  className="hd r"
                  onPointerDown={(ev) => {
                    ev.stopPropagation();
                    onSelectFx(e.id);
                    setDrag({ kind: 'fx', fx: doc.effects.find((y) => y.id === e.id)!, edge: 'r', t0: 0, cur: { start: e.start, end: e.end } });
                  }}
                />
              </div>
            );
          })}
        </div>
        {/* overlays */}
        {trimA > 0.01 && <div className="trimz" style={{ left: 0, width: x(trimA) }} />}
        {trimB < D - 0.01 && <div className="trimz" style={{ left: x(trimB), right: 0 }} />}
        {doc.cuts.map((c) => (
          <div key={c.index} className="cutz" style={{ left: x(c.start), width: Math.max(2, x(c.end) - x(c.start)) }} />
        ))}
        {selection && <div className="selz" style={{ left: x(selection.a), width: Math.max(2, x(selection.b) - x(selection.a)) }} data-testid="tl-selection" />}
        <div className="trimh" style={{ left: x(trimA) }} onPointerDown={(e) => (e.stopPropagation(), setDrag({ kind: 'trim', edge: 'l', cur: trimA }))} data-testid="trim-in" />
        <div className="trimh" style={{ left: x(trimB) }} onPointerDown={(e) => (e.stopPropagation(), setDrag({ kind: 'trim', edge: 'r', cur: trimB }))} data-testid="trim-out" />
        <div className="phead" style={{ left: x(time) }} />
      </div>
      </div>
    </div>
  );
}

/** Frame thumbnails drawn from a hidden video (seek, draw, next). */
function Thumbs({ file, duration, width }: { file: string | null; duration: number; width: number }) {
  const n = Math.max(4, Math.min(60, Math.floor(width / 64)));
  const refs = useRef<(HTMLCanvasElement | null)[]>([]);
  useEffect(() => {
    if (!file || !duration) return;
    let alive = true;
    const v = document.createElement('video');
    v.muted = true;
    v.preload = 'auto';
    v.src = media(file);
    let i = 0;
    const next = () => {
      if (!alive || i >= n) return;
      v.currentTime = Math.min(duration - 0.05, ((i + 0.5) * duration) / n);
    };
    const draw = () => {
      const c = refs.current[i];
      if (c && v.videoWidth) {
        const ctx = c.getContext('2d');
        c.width = 96;
        c.height = 60;
        const r = Math.max(96 / v.videoWidth, 60 / v.videoHeight);
        const w2 = v.videoWidth * r;
        const h2 = v.videoHeight * r;
        ctx?.drawImage(v, (96 - w2) / 2, (60 - h2) / 2, w2, h2);
      }
      i++;
      next();
    };
    v.addEventListener('loadeddata', next, { once: true });
    v.addEventListener('seeked', draw);
    return () => {
      alive = false;
      v.removeAttribute('src');
      v.load();
    };
  }, [file, duration, n]);
  return (
    <div className="thumbs">
      {Array.from({ length: n }, (_, i) => (
        <canvas key={i} ref={(el) => void (refs.current[i] = el)} />
      ))}
    </div>
  );
}

function Wave({ data, width }: { data: number[]; width: number }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.max(1, width * dpr);
    c.height = 32 * dpr;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.fillStyle = getComputedStyle(c).getPropertyValue('--text-faint') || '#777';
    const n = data.length || 1;
    const bw = c.width / n;
    data.forEach((v, i) => {
      const h = Math.max(1, v * c.height * 0.9);
      ctx.fillRect(i * bw, (c.height - h) / 2, Math.max(1, bw - dpr), h);
    });
  }, [data, width]);
  return <canvas ref={ref} className="wave" style={{ width }} />;
}
