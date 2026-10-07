// The clip player: large in-page (overlay) and true full screen (double-click, F, Esc), frame-accurate scrubbing,
// J/K/L shuttle, ←/→ one frame (Shift: 1 s), I/O selection + loop, speed, size versions (3:4 / 9:16) and the
// captions / safe-area overlays. Embedded in the output editor and the focused review with the same keys.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type ReactNode } from 'react';
import { Maximize2, Minimize2, Pause, Play, Repeat, ScanLine, StepBack, StepForward, Subtitles, Wand2, X } from 'lucide-react';
import type { CaptionCue, ClipFile, EffectInstance } from '../../../shared/v04';
import type { StripInfo } from '../../../shared/timeline';
import { fmtClock, t } from '../i18n';
import { clamp, frameTime, loopTime, safeAreas, shuttle, step, timecode } from '../lib/player';
import { isTyping } from './ui';
import { media } from './kit';
import { Scrubber, type ScrubTick } from './Scrubber';

export interface PlayerApi {
  seek(t: number): void;
  time(): number;
  play(): void;
  pause(): void;
  selection(): { a: number; b: number } | null;
  setSelection(s: { a: number; b: number } | null): void;
  aspect(): string | undefined;
}

export interface PlayerProps {
  files: ClipFile[];
  fps?: number;
  duration?: number;
  captions?: CaptionCue[];
  captionStyle?: { size?: number; color?: string; highlight?: string; position?: string };
  keywords?: { word: string; color: string }[];
  effects?: EffectInstance[];
  /** ranges skipped while playing (inner cuts) and the kept window (trim) */
  cuts?: { start: number; end: number }[];
  trim?: { start: number; end: number } | null;
  marks?: number[];
  /** chapter / edit ticks on the scrub bar (amber draft, teal applied) */
  ticks?: ScrubTick[];
  /** the timeline's sprite sheet: a frame preview while hovering the scrub bar */
  strip?: StripInfo | null;
  onPlaying?: (playing: boolean) => void;
  title?: string;
  /** overlay mode: Esc closes, the player owns the keyboard */
  onClose?: () => void;
  onEdit?: () => void;
  onTime?: (t: number) => void;
  onSelection?: (s: { a: number; b: number } | null) => void;
  keys?: boolean;
  autoPlay?: boolean;
  initialAspect?: string;
  extra?: ReactNode;
  testId?: string;
  /** before / after on the player itself: the "before" overlays left of a draggable divider, this player's own
   * (the "after") on the right; never a modal */
  compare?: { effects: EffectInstance[]; captions?: CaptionCue[]; labels: [string, string] } | null;
  /** a label pinned top-left of the frame (e.g. "Original" while C is held) */
  badge?: string | null;
}

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export const Player = forwardRef<PlayerApi, PlayerProps>(function Player(p, ref) {
  const box = useRef<HTMLDivElement | null>(null);
  const v = useRef<HTMLVideoElement | null>(null);
  const [vi, setVi] = useState(() => Math.max(0, p.files.findIndex((f) => f.aspect === p.initialAspect)));
  const file = p.files[vi] ?? p.files[0];
  const aspect = file?.aspect;
  const fps = file?.fps || p.fps || 30;
  const [dur, setDur] = useState(file?.duration || p.duration || 0);
  const [cur, setCur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(0); // shuttle rate (J/K/L); 0 = paused
  const [speed, setSpeed] = useState(1);
  const [sel, setSelS] = useState<{ a: number; b: number } | null>(null);
  const [loop, setLoop] = useState(false);
  const [caps, setCaps] = useState(false);
  const [split, setSplit] = useState(50);
  const [safe, setSafe] = useState(false);
  const [full, setFull] = useState(false);
  const [err, setErr] = useState(false);
  const [buffered, setBuffered] = useState<[number, number][]>([]);
  const selRef = useRef(sel);
  selRef.current = sel;
  const setSel = useCallback(
    (s: { a: number; b: number } | null) => {
      setSelS(s);
      p.onSelection?.(s);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [p.onSelection],
  );

  const seek = useCallback(
    (x: number) => {
      const el = v.current;
      if (!el) return;
      const tt = clamp(x, 0, el.duration || dur || 0);
      el.currentTime = tt;
      setCur(tt);
      p.onTime?.(tt);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dur, p.onTime],
  );

  useImperativeHandle(
    ref,
    () => ({
      seek,
      time: () => v.current?.currentTime ?? 0,
      play: () => void v.current?.play().catch(() => undefined),
      pause: () => v.current?.pause(),
      selection: () => selRef.current,
      setSelection: setSel,
      aspect: () => aspect,
    }),
    [seek, setSel, aspect],
  );

  // keep position when switching size versions
  const keepAt = useRef(0);
  useEffect(() => {
    const el = v.current;
    if (!el) return;
    const at = keepAt.current;
    const onMeta = () => {
      setDur(el.duration || dur);
      if (at) el.currentTime = at;
      setErr(false);
    };
    el.addEventListener('loadedmetadata', onMeta);
    return () => el.removeEventListener('loadedmetadata', onMeta);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file?.path]);

  // play loop: time, selection loop, skip cuts / outside trim, reverse shuttle
  useEffect(() => {
    let raf = 0;
    let lastT = -1;
    let last = performance.now();
    const tick = (now: number) => {
      const el = v.current;
      const dt = (now - last) / 1000;
      last = now;
      if (el) {
        if (rate < 0) {
          const nt = Math.max(0, el.currentTime + rate * dt);
          el.currentTime = nt;
          if (nt <= 0) setRate(0);
        }
        let tt = el.currentTime;
        if (!el.paused || rate < 0) {
          const back = loopTime(tt, selRef.current, loop);
          if (back !== null) {
            el.currentTime = back;
            tt = back;
          } else if (rate >= 0) {
            const c = (p.cuts ?? []).find((x) => tt >= x.start && tt < x.end - 0.01);
            if (c) {
              el.currentTime = c.end;
              tt = c.end;
            } else if (p.trim && tt < p.trim.start - 0.05) {
              el.currentTime = p.trim.start;
              tt = p.trim.start;
            } else if (p.trim && tt >= p.trim.end) {
              el.pause();
              el.currentTime = p.trim.end;
              tt = p.trim.end;
            }
          }
        }
        if (Math.abs(tt - lastT) > 0.04 || (el.paused && tt !== lastT)) {
          lastT = tt;
          setCur(tt);
          p.onTime?.(tt);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rate, loop, p.cuts, p.trim, p.onTime]);

  useEffect(() => {
    const el = v.current;
    if (!el) return;
    if (rate > 0) {
      el.playbackRate = rate * speed;
      void el.play().catch(() => undefined);
    } else if (rate < 0) el.pause();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rate]);
  useEffect(() => {
    if (v.current && rate >= 0) v.current.playbackRate = Math.max(1, rate || 1) * speed;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speed]);

  const toggle = useCallback(() => {
    const el = v.current;
    if (!el) return;
    if (el.paused && rate <= 0) {
      setRate(1);
    } else {
      setRate(0);
      el.pause();
    }
  }, [rate]);

  const toggleFull = useCallback(() => {
    const el = box.current;
    if (!el) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
      setFull(false);
      return;
    }
    if (full) {
      setFull(false);
      return;
    }
    setFull(true); // maximised in-window at once; true OS full screen when the window allows it
    void el.requestFullscreen?.().catch(() => undefined);
  }, [full]);

  useEffect(() => {
    const on = () => {
      if (!document.fullscreenElement) setFull(false);
    };
    document.addEventListener('fullscreenchange', on);
    return () => document.removeEventListener('fullscreenchange', on);
  }, []);

  // keyboard
  const keysOn = p.keys !== false;
  const onClose = p.onClose;
  useEffect(() => {
    if (!keysOn) return;
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector('.scrim, .ctx')) return;
      const el = v.current;
      if (!el) return;
      const k = e.key;
      const lower = k.toLowerCase();
      if (k === ' ' || lower === 'k') {
        e.preventDefault();
        if (lower === 'k') {
          setRate(0);
          el.pause();
        } else toggle();
      } else if (lower === 'j' || (lower === 'l' && !e.shiftKey)) {
        e.preventDefault();
        setRate((r) => shuttle(el.paused && r > 0 ? 0 : r, lower as 'j' | 'l'));
      } else if (lower === 'l' && e.shiftKey) {
        e.preventDefault();
        setLoop((x) => !x);
      } else if (k === 'ArrowLeft' || k === 'ArrowRight') {
        e.preventDefault();
        setRate(0);
        el.pause();
        seek(step(el.currentTime, k === 'ArrowRight' ? 1 : -1, fps, el.duration || dur, e.shiftKey));
      } else if (k === 'Home' || k === 'End') {
        e.preventDefault();
        setRate(0);
        el.pause();
        seek(k === 'Home' ? (p.trim?.start ?? 0) : (p.trim?.end ?? (el.duration || dur)));
      } else if (lower === 'i') {
        const a = el.currentTime;
        setSel({ a, b: Math.max(a + 0.1, selRef.current?.b ?? Math.min(dur, a + 3)) });
      } else if (lower === 'o') {
        const b = el.currentTime;
        setSel({ a: Math.min(selRef.current?.a ?? Math.max(0, b - 3), b - 0.1), b });
      } else if (lower === 'f') {
        e.preventDefault();
        toggleFull();
      } else if (k === 'Escape') {
        if (full && !document.fullscreenElement) setFull(false);
        else if (!document.fullscreenElement && onClose) onClose();
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [keysOn, onClose, toggle, toggleFull, seek, setSel, fps, dur, full, p.trim]);

  const areas = safeAreas(file?.aspect ?? '', file?.safe_box, file?.caption_box, file?.w, file?.h);
  const cue = caps ? (p.captions ?? []).find((c) => !c.removed && cur >= c.start && cur <= c.end) : undefined;
  const style = p.captionStyle ?? {};
  const fxAt = (list: EffectInstance[] | undefined) => (list ?? []).filter((x) => cur >= x.start && cur <= x.end && typeof x.params?.text === 'string' && x.params.text);
  const liveFx = fxAt(p.effects);
  const cueAt = (list: CaptionCue[] | undefined) => (caps ? (list ?? []).find((c) => !c.removed && cur >= c.start && cur <= c.end) : undefined);
  const overlays = (c: CaptionCue | undefined, fx: EffectInstance[], tag: string) => (
    <>
      {c && (
        <div className={`capov ${style.position ?? 'bottom'}`} style={{ color: style.color ?? '#fff', fontSize: style.size ? `calc(clamp(14px, 2.4vh, 26px) * ${style.size})` : undefined }} data-testid={`caption-overlay${tag}`}>
          {highlight(c.text, p.keywords ?? [], style.highlight)}
        </div>
      )}
      {fx.map((x) => (
        <div key={x.id} className="capov middle fxov" style={{ color: String(x.params?.color ?? '#FFD60A'), fontSize: `calc(clamp(22px, 4vh, 44px) * ${Math.max(0.6, Math.min(2, Number(x.params?.size ?? 0.11) / 0.11))})` }} data-testid={`fx-overlay${tag}`}>
          {String(x.params?.text ?? '')}
        </div>
      ))}
    </>
  );

  return (
    <div ref={box} className={`pl ${full ? 'full' : ''}`} tabIndex={-1} data-testid={p.testId ?? 'player'} data-full={full ? '1' : '0'}>
      {(p.title || p.onClose) && (
        <div className="row">
          {p.title && <b className="clamp1" style={{ fontWeight: 500, fontSize: 15 }}>{p.title}</b>}
          <span className="sp" />
          {p.onEdit && (
            <button className="btn sm" onClick={p.onEdit} data-testid="player-edit">
              <Wand2 className="ico" />
              {t('player.edit')}
            </button>
          )}
          {p.onClose && (
            <button className="btn ghost icon sm" onClick={p.onClose} aria-label={t('player.close')} data-tip={`${t('player.close')} · Esc`} data-testid="player-close">
              <X className="ico" />
            </button>
          )}
        </div>
      )}
      <div className="stage" onDoubleClick={toggleFull}>
        {file ? (
          <div className="frame">
            <video
              ref={v}
              src={media(file.path)}
              preload="auto"
              playsInline
              autoPlay={p.autoPlay}
              onPlay={() => (setPlaying(true), p.onPlaying?.(true))}
              onPause={() => (setPlaying(false), p.onPlaying?.(false))}
              onProgress={(e) => {
                const b = (e.target as HTMLVideoElement).buffered;
                setBuffered(Array.from({ length: b.length }, (_, i) => [b.start(i), b.end(i)] as [number, number]));
              }}
              onLoadedMetadata={(e) => setDur((e.target as HTMLVideoElement).duration || dur)}
              onError={() => setErr(true)}
              onClick={() => toggle()}
              data-testid="player-video"
            />
            {safe && areas && (
              <>
                <div className="safe" style={{ left: pct2(areas.safe.l), top: pct2(areas.safe.t), right: pct2(areas.safe.r), bottom: pct2(areas.safe.b) }}>
                  <span>{t('player.safe')}</span>
                </div>
                <div className="safe cap" style={{ left: pct2(areas.cap.l), top: pct2(areas.cap.t), right: pct2(areas.cap.r), bottom: pct2(areas.cap.b) }} />
              </>
            )}
            {p.compare ? (
              <>
                <div className="ovl" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>{overlays(cueAt(p.compare.captions ?? p.captions), fxAt(p.compare.effects), '-before')}</div>
                <div className="ovl" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>{overlays(cue, liveFx, '')}</div>
                <div
                  className="wipe"
                  style={{ left: `${split}%` }}
                  onClick={(e) => e.stopPropagation()}
                  onDoubleClick={(e) => e.stopPropagation()}
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    const fr = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
                    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
                    const mv = (ev: PointerEvent) => setSplit(clamp(((ev.clientX - fr.left) / fr.width) * 100, 4, 96));
                    const up = () => {
                      window.removeEventListener('pointermove', mv);
                      window.removeEventListener('pointerup', up);
                    };
                    window.addEventListener('pointermove', mv);
                    window.addEventListener('pointerup', up);
                  }}
                  data-testid="compare-wipe"
                >
                  <span className="l">{p.compare.labels[0]}</span>
                  <i />
                  <span className="r">{p.compare.labels[1]}</span>
                </div>
              </>
            ) : (
              overlays(cue, liveFx, '')
            )}
            {p.badge && <span className="pbadge" data-testid="player-badge">{p.badge}</span>}
          </div>
        ) : (
          <div className="muted" style={{ padding: 48 }}>{t('player.noVideo')}</div>
        )}
        {err && <div className="note" style={{ position: 'absolute', bottom: 12 }}>{t('player.cantPlay')}</div>}
      </div>
      <Scrubber
        duration={dur}
        time={cur}
        buffered={buffered}
        strip={p.strip}
        ticks={[...(p.ticks ?? []), ...(p.marks ?? []).map((m) => ({ t: m, tone: 'chapter' as const }))]}
        selection={sel}
        trim={p.trim}
        label={t('player.seek')}
        onSeek={(x, final) => seek(final ? frameTime(x, fps) : x)}
      />
      <div className="ctl">
        <button className="btn icon sm" onClick={() => seek(step(cur, -1, fps, dur))} aria-label={t('player.frameBack')} data-tip={`${t('player.frameBack')} · ←`}>
          <StepBack className="ico" />
        </button>
        <button className="btn icon" onClick={toggle} aria-label={playing ? t('player.pause') : t('player.play')} data-tip={`${playing ? t('player.pause') : t('player.play')} · Space`} data-testid="player-play">
          {playing ? <Pause className="ico" /> : <Play className="ico" />}
        </button>
        <button className="btn icon sm" onClick={() => seek(step(cur, 1, fps, dur))} aria-label={t('player.frameFwd')} data-tip={`${t('player.frameFwd')} · →`}>
          <StepForward className="ico" />
        </button>
        <span className="tc num" data-testid="timecode">
          <TC v={timecode(cur, fps)} /> <span className="of">/ {fmtClock(dur)}</span>
        </span>
        {rate !== 0 && rate !== 1 && <span className="muted num">{rate > 0 ? `${rate}×` : `◀ ${-rate}×`}</span>}
        <span className="sp" />
        {p.files.length > 1 && (
          <div className="vers" role="group" aria-label={t('player.size')}>
            {p.files.map((f, i) => (
              <button
                key={i}
                className={i === vi ? 'on' : ''}
                onClick={() => {
                  keepAt.current = v.current?.currentTime ?? 0;
                  setVi(i);
                }}
                data-testid={`size-${f.aspect}`}
              >
                {f.label ? `${f.label} ${/^\d+:\d+$/.test(f.aspect) ? f.aspect : ''}`.trim() : /^\d+:\d+$/.test(f.aspect) ? f.aspect : t('c.original')}
              </button>
            ))}
          </div>
        )}
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label={t('player.speed')} data-testid="speed">
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
        <button className={`btn icon sm toggle ${loop ? 'on' : ''}`} onClick={() => setLoop((x) => !x)} aria-pressed={loop} aria-label={t('player.loop')} data-tip={`${t('player.loop')} · Shift L`} data-testid="loop">
          <Repeat className="ico" />
        </button>
        {(p.captions?.length ?? 0) > 0 && (
          <button className={`btn icon sm toggle ${caps ? 'on' : ''}`} onClick={() => setCaps((x) => !x)} aria-pressed={caps} aria-label={t('player.captions')} data-tip={t('player.captions')} data-testid="toggle-captions">
            <Subtitles className="ico" />
          </button>
        )}
        {areas && (
          <button className={`btn icon sm toggle ${safe ? 'on' : ''}`} onClick={() => setSafe((x) => !x)} aria-pressed={safe} aria-label={t('player.safe')} data-tip={t('player.safe')} data-testid="toggle-safe">
            <ScanLine className="ico" />
          </button>
        )}
        <button className="btn icon sm" onClick={toggleFull} aria-label={full ? t('player.exitFullscreen') : t('player.fullscreen')} data-tip={`${full ? t('player.exitFullscreen') : t('player.fullscreen')} · F`} data-testid="fullscreen">
          {full ? <Minimize2 className="ico" /> : <Maximize2 className="ico" />}
        </button>
      </div>
      {p.extra}
      {p.onClose && <div className="help">{t('player.help')}</div>}
    </div>
  );
});

const pct2 = (f: number) => `${f * 100}%`;

/** 00:00:23:12 with the leading zero groups dimmed (the text stays the full timecode). */
function TC({ v }: { v: string }) {
  const m = /^((?:00:)*)(.*)$/.exec(v);
  const lead = m?.[1] ?? '';
  return (
    <>
      {lead && <span className="z">{lead}</span>}
      {m?.[2] ?? v}
    </>
  );
}

function highlight(text: string, kws: { word: string; color: string }[], fallback?: string): ReactNode {
  if (!kws.length) return text;
  const parts: ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest) {
    let best: { i: number; w: { word: string; color: string } } | null = null;
    for (const w of kws) {
      const i = rest.indexOf(w.word);
      if (i >= 0 && (!best || i < best.i)) best = { i, w };
    }
    if (!best) {
      parts.push(rest);
      break;
    }
    if (best.i) parts.push(rest.slice(0, best.i));
    parts.push(
      <span key={k++} style={{ color: best.w.color || fallback }}>
        {best.w.word}
      </span>,
    );
    rest = rest.slice(best.i + best.w.word.length);
  }
  return parts;
}

/** The large in-page player over everything (Esc closes; F / double-click for true full screen). */
export function PlayerOverlay(props: PlayerProps & { onClose: () => void }) {
  return (
    <div className="pl-overlay" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()} data-testid="player-overlay">
      <Player {...props} autoPlay keys />
    </div>
  );
}
