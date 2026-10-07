// The player's scrub bar: full width under the video, buffered / played fill, a handle that grows on hover, click or
// drag to seek (frame-accurate on release), a hover tag with the time and a frame from the timeline's sprite sheet,
// and ticks for chapters / edits (amber = draft, teal = applied). Keys live on the player (Space, J/K/L, ←/→, Home/End).
import { useRef, useState } from 'react';
import type { StripInfo } from '../../../shared/timeline';
import { fmtClock } from '../i18n';
import { clamp } from '../lib/player';
import { clock, tileAt, tileOffset } from '../lib/timeline';
import { media } from './kit';
import './timeline.css';

export interface ScrubTick {
  t: number;
  /** a range (an edit that spans time) */
  b?: number;
  tone: 'draft' | 'applied' | 'chapter';
  label?: string;
}

export interface ScrubberProps {
  duration: number;
  time: number;
  buffered: [number, number][];
  strip?: StripInfo | null;
  ticks?: ScrubTick[];
  selection?: { a: number; b: number } | null;
  trim?: { start: number; end: number } | null;
  label: string;
  onSeek: (t: number, final: boolean) => void;
  onScrub?: (active: boolean) => void;
}

/** The preview frame: at most 168 x 120, the tile's aspect. */
export function previewBox(strip: Pick<StripInfo, 'tile'>, maxW = 168, maxH = 120): { w: number; h: number; scale: number } {
  const [tw, th] = strip.tile;
  const scale = Math.min(maxW / tw, maxH / th);
  return { w: Math.round(tw * scale), h: Math.round(th * scale), scale };
}

export function Scrubber({ duration, time, buffered, strip, ticks, selection, trim, label, onSeek, onScrub }: ScrubberProps) {
  const el = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<{ t: number; x: number } | null>(null);
  const [drag, setDrag] = useState(false);
  const D = duration || 0;
  const pct = (x: number) => `${D ? clamp((x / D) * 100, 0, 100) : 0}%`;
  const at = (clientX: number) => {
    const r = el.current?.getBoundingClientRect();
    if (!r || !r.width) return { t: 0, x: 0 };
    const x = clamp(clientX - r.left, 0, r.width);
    return { t: (x / r.width) * D, x };
  };
  const width = el.current?.clientWidth ?? 0;
  const pv = strip?.sprite && strip.n ? previewBox(strip) : null;
  const show = hover ?? (drag ? { t: time, x: D ? (time / D) * width : 0 } : null);
  const tagW = pv ? pv.w : 64;
  return (
    <div
      ref={el}
      className={`scrub2 ${drag ? 'drag' : ''} ${hover ? 'hov' : ''}`}
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.round(D)}
      aria-valuenow={Math.round(time)}
      aria-valuetext={fmtClock(time)}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        setDrag(true);
        onScrub?.(true);
        onSeek(at(e.clientX).t, false);
      }}
      onPointerMove={(e) => {
        const p = at(e.clientX);
        setHover(p);
        if (drag) onSeek(p.t, false);
      }}
      onPointerUp={(e) => {
        if (!drag) return;
        setDrag(false);
        onScrub?.(false);
        onSeek(at(e.clientX).t, true);
      }}
      onPointerLeave={() => setHover(null)}
      data-testid="scrub"
    >
      <div className="rail">
        {buffered.map(([a, b], i) => (
          <i key={i} className="buf" style={{ left: pct(a), width: pct(b - a) }} />
        ))}
        {trim && trim.start > 0.01 && <i className="out" style={{ left: 0, width: pct(trim.start) }} />}
        {trim && trim.end < D - 0.01 && <i className="out" style={{ left: pct(trim.end), right: 0 }} />}
        {selection && <i className="sel" style={{ left: pct(selection.a), width: pct(selection.b - selection.a) }} data-testid="selection" />}
        <i className="fill" style={{ width: pct(time) }} />
        {hover && !drag && <i className="ghost" style={{ width: pct(hover.t) }} />}
      </div>
      {(ticks ?? []).map((k, i) => (
        <i key={i} className={`tick ${k.tone}`} style={{ left: pct(k.t), width: k.b != null && k.b > k.t ? pct(k.b - k.t) : undefined }} title={k.label} data-testid={`scrub-tick-${k.tone}`} />
      ))}
      <i className="knob" style={{ left: pct(time) }} />
      {show && width > 0 && (
        <div className="tag" style={{ left: clamp(show.x, tagW / 2, Math.max(tagW / 2, width - tagW / 2)) }} data-testid="scrub-tag">
          {pv && strip && (
            <span
              className="pv"
              style={{
                width: pv.w,
                height: pv.h,
                backgroundImage: `url("${media(strip.sprite!)}")`,
                backgroundSize: `${strip.cols * strip.tile[0] * pv.scale}px auto`,
                backgroundPosition: (() => {
                  const o = tileOffset(tileAt(show.t, strip), strip);
                  return `-${o.x * pv.scale}px -${o.y * pv.scale}px`;
                })(),
              }}
            />
          )}
          <b className="num">{clock(show.t, D < 120)}</b>
        </div>
      )}
    </div>
  );
}
