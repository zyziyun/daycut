// What an agent working in the folder says it is doing right now (status.json via the engine's history `live`):
// message, step, progress and how fresh the heartbeat is. Project page banner + a line on the project card.
import { useEffect, useState } from 'react';
import type { LiveStatus } from '../../../shared/v02';
import { liveLine, liveMeta } from '../lib/liveStatus';

function useNow(ms = 5000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const tm = window.setInterval(() => setNow(Date.now() / 1000), ms);
    return () => window.clearInterval(tm);
  }, [ms]);
  return now;
}

export function LiveBanner({ live, title }: { live: LiveStatus | null | undefined; title: string }) {
  const now = useNow(5000);
  const l = liveLine(live, now);
  if (!l) return null;
  return (
    <div className={`banner ${l.stale ? '' : 'run'}`} role="status" data-testid="project-live">
      <i className={`dot ${l.stale ? 'you' : 'run'}`} />
      <div className="sp" style={{ minWidth: 0 }}>
        <b className="clamp2" data-testid="project-live-message">
          {l.message || title}
        </b>
        <span className="muted" data-testid="project-live-meta">
          {liveMeta(l)}
        </span>
      </div>
      {l.pct != null && (
        <div className="bar" aria-label={l.message || title} aria-valuenow={l.pct} role="progressbar">
          <i style={{ width: `${Math.max(3, l.pct)}%` }} />
        </div>
      )}
    </div>
  );
}

export function LiveCardLine({ live }: { live: LiveStatus | null | undefined }) {
  const now = useNow(15000);
  const l = liveLine(live, now);
  if (!l || !(l.message || l.stage)) return null;
  return (
    <div className="muted small clamp1" title={`${l.message}${l.message ? ' · ' : ''}${liveMeta(l)}`} data-testid="project-card-live">
      {l.message || l.stage}
      {l.pct != null ? ` · ${l.pct}%` : ''}
    </div>
  );
}
