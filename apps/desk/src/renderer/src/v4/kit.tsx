// Small building blocks for the v0.4 screens: status pill, thumbnails (hover to scrub), mosaic, skeletons, empty
// states, segmented control. Icons: Lucide only, one size / stroke (CSS .ico).
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, ExternalLink, Film, Play } from 'lucide-react';
import { fmtClock, t } from '../i18n';
import { STATUS_KEY, type Status4 } from '../lib/status';

export const media = (p: string | null | undefined) => (p ? window.desk.mediaUrl(p) : '');

/** Seconds since ``since`` (epoch s or ms), ticking once a second: "0:42", "3:05". */
export function Elapsed({ since, testId }: { since: number | null | undefined; testId?: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tm = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tm);
  }, []);
  if (!since) return null;
  const ms = since < 1e12 ? since * 1000 : since;
  return (
    <span className="tnum" data-testid={testId ?? 'elapsed'}>
      {fmtClock(Math.max(0, (now - ms) / 1000))}
    </span>
  );
}

export function StatusPill({ s, label, testId }: { s: Status4 | null; label?: string; testId?: string }) {
  if (!s) return null;
  return (
    <span className={`st ${s}`} data-testid={testId ?? 'status'} data-status={s}>
      <i className={`dot ${s}`} />
      {label ?? t(STATUS_KEY[s])}
    </span>
  );
}

/** A 3:4 (or given ratio) thumbnail; with `video`, hovering plays it muted and moving the mouse scrubs. */
export function Thumb({
  src,
  video,
  ratio = '3/4',
  dur,
  label,
  play,
  className = '',
  children,
}: {
  src?: string | null;
  video?: string | null;
  ratio?: string;
  dur?: number | null;
  label?: ReactNode;
  play?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const v = useRef<HTMLVideoElement | null>(null);
  const [hover, setHover] = useState(false);
  const [ready, setReady] = useState(false);
  const [x, setX] = useState<number | null>(null);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    const el = v.current;
    if (!el) return;
    if (hover) void el.play().catch(() => undefined);
    else {
      el.pause();
      setX(null);
    }
  }, [hover]);
  const onMove = (e: React.MouseEvent) => {
    const el = v.current;
    if (!el || !el.duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    setX(f);
    el.currentTime = f * el.duration;
  };
  return (
    <div
      className={`th ${!src && !video ? 'ph-thumb' : ''} ${className}`}
      style={{ aspectRatio: ratio }}
      onMouseEnter={() => video && setHover(true)}
      onMouseLeave={() => setHover(false)}
      onMouseMove={video ? onMove : undefined}
    >
      {src && !broken ? <img src={media(src)} alt="" loading="lazy" draggable={false} onError={() => setBroken(true)} /> : !video ? label ?? <Film className="ico lg" /> : null}
      {video && (hover || !src || broken) && (
        <video
          ref={v}
          className={`hov ${ready ? 'ready' : ''}`}
          style={!src || broken ? { opacity: 1, position: 'static' } : undefined}
          src={media(video)}
          muted
          playsInline
          loop
          preload="metadata"
          onLoadedData={() => setReady(true)}
        />
      )}
      {x !== null && <i className="scrubline" style={{ width: `${x * 100}%` }} />}
      {dur ? <span className="dur num">{fmtClock(dur)}</span> : null}
      {play && (
        <span className="play">
          <i>
            <Play className="ico" />
          </i>
        </span>
      )}
      {children}
    </div>
  );
}

/** A clip's cover that opens the clip's own page (player + editor); a click on it never reaches the card around it
 * (a publish card opens its drawer, a queue row is dragged or picked). */
export function ClipThumbLink({ href, src, ratio = '3/4', label, testId = 'open-clip' }: { href: string; src?: string | null; ratio?: string; label: string; testId?: string }) {
  return (
    <a className="clip-open" href={href} onClick={(e) => e.stopPropagation()} draggable={false} aria-label={label} title={label} data-testid={testId}>
      <Thumb src={src} ratio={ratio} play />
    </a>
  );
}

/** A posted clip's live page, when Reelfold knows it (opened in her browser). */
export function PostLink({ url }: { url?: string | null }) {
  if (!url || !/^https?:\/\//.test(url)) return null;
  return (
    <button className="btn ghost sm" onClick={(e) => (e.stopPropagation(), void window.desk.openExternal(url))} data-testid="post-link" title={url}>
      <ExternalLink className="ico" />
      {t('pub.viewPost')}
    </button>
  );
}

export function Mosaic({ srcs, cells, ratio = '3/4' }: { srcs: (string | null)[]; cells?: ('rendering' | 'queued' | null)[]; ratio?: string }) {
  const four = [0, 1, 2, 3].map((i) => srcs[i] ?? null);
  return (
    <div className="mosaic" style={{ aspectRatio: ratio }}>
      {four.map((s, i) =>
        s ? (
          <img key={i} src={media(s)} alt="" loading="lazy" draggable={false} />
        ) : (
          <div key={i} className="ph-thumb">
            {cells?.[i] === 'rendering' ? t('projects.rendering') : cells?.[i] === 'queued' ? t('projects.queued') : ''}
          </div>
        ),
      )}
    </div>
  );
}

export function Sk({ w = '100%', h = 16, r }: { w?: number | string; h?: number | string; r?: number }) {
  return <div className="sk" style={{ width: w, height: h, borderRadius: r }} aria-hidden />;
}

export function SkGrid({ n = 8, ratio = '3/4' }: { n?: number; ratio?: string }) {
  return (
    <div className="pgrid" aria-busy="true" aria-label={t('c.loading')}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="col" style={{ padding: 8 }}>
          <div className="sk" style={{ aspectRatio: ratio }} />
          <Sk w="70%" />
          <Sk w="40%" h={12} />
        </div>
      ))}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty" data-testid="empty">
      <b>{title}</b>
      {hint && <span className="muted">{hint}</span>}
      {action}
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange, testId }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void; testId?: string }) {
  return (
    <div className="seg" role="tablist" data-testid={testId}>
      {options.map((o) => (
        <button key={o.v} role="tab" aria-selected={o.v === value} className={o.v === value ? 'on' : ''} onClick={() => onChange(o.v)} data-v={o.v}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function More({ summary, children, testId }: { summary: string; children: ReactNode; testId?: string }) {
  return (
    <details className="more" data-testid={testId}>
      <summary>
        <ChevronRight className="ico" />
        {summary}
      </summary>
      {children}
    </details>
  );
}

/** Ratio of a clip file for thumbnails ("9:16" -> "9/16"). */
export function ratioOf(aspect?: string | null): string {
  if (!aspect || !/^\d+:\d+$/.test(aspect)) return '3/4';
  return aspect.replace(':', '/');
}
