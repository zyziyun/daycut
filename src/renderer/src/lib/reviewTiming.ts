// useReviewTiming(batch, job): measures active review time on one job (ReviewTimer: visibility, focus, idle
// cutoff, playing video) and sends `timing` start/stop events to the engine. A stop (with the active seconds
// since the last stop) goes out when the job changes, the view unmounts, the window hides, and every 30 s.
import { useEffect, useRef, useState } from 'react';
import { ReviewTimer } from '../../../shared/reviewTimer';
import { useEngine } from './engine';

const FLUSH_MS = 30_000;
const IDLE_S = 60;
const ACTIVITY = ['keydown', 'pointerdown', 'pointermove', 'wheel'] as const;

export function useReviewTiming(batch: string, job: string | null | undefined): { seconds: number; idle: boolean } {
  const { client } = useEngine();
  const [view, setView] = useState({ seconds: 0, idle: false });
  const timer = useRef<ReviewTimer | null>(null);

  useEffect(() => {
    if (!client || !job) return;
    const now = () => performance.now();
    const tm = new ReviewTimer(now(), { idleCutoffS: IDLE_S });
    timer.current = tm;
    tm.setVisible(document.visibilityState === 'visible', now());
    tm.setFocused(document.hasFocus(), now());
    let lastMove = 0;
    const send = (event: 'start' | 'stop', active_s?: number) =>
      client.timing(batch, { job, event, what: 'review', ...(active_s !== undefined ? { active_s } : {}) }).catch(() => undefined);
    const flush = () => {
      const d = tm.take(now());
      if (d > 0) void send('stop', d);
    };
    void send('start');
    const onAct = (e: Event) => {
      if (e.type === 'pointermove') {
        const t = now();
        if (t - lastMove < 1000) return; // pointermove is chatty
        lastMove = t;
      }
      tm.activity(now());
    };
    const onVis = () => {
      tm.setVisible(document.visibilityState === 'visible', now());
      if (document.visibilityState !== 'visible') flush();
    };
    const onFocus = () => tm.setFocused(true, now());
    const onBlur = () => tm.setFocused(false, now());
    const onMedia = (e: Event) => {
      if (e.target instanceof HTMLVideoElement) tm.setPlaying(!e.target.paused && !e.target.ended, now());
    };
    for (const ev of ACTIVITY) window.addEventListener(ev, onAct, { passive: true, capture: true });
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('focus', onFocus);
    window.addEventListener('blur', onBlur);
    for (const ev of ['play', 'pause', 'ended'] as const) document.addEventListener(ev, onMedia, true);
    const tick = setInterval(() => setView({ seconds: Math.round(tm.seconds(now())), idle: tm.isIdle(now()) }), 1000);
    const flusher = setInterval(flush, FLUSH_MS);
    const onUnload = () => flush();
    window.addEventListener('beforeunload', onUnload);
    return () => {
      flush();
      clearInterval(tick);
      clearInterval(flusher);
      for (const ev of ACTIVITY) window.removeEventListener(ev, onAct, { capture: true });
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('beforeunload', onUnload);
      for (const ev of ['play', 'pause', 'ended'] as const) document.removeEventListener(ev, onMedia, true);
      timer.current = null;
    };
  }, [client, batch, job]);

  return view;
}
