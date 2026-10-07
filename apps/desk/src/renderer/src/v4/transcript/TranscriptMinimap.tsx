// The whole clip as a thin bar above the transcript: the stretch in view, the playhead, applied (grey) and pending
// (red hatch) cuts. Click anywhere to go there.
import { t } from '../../i18n';

export function TranscriptMinimap({ duration, time, view, pending, applied, onJump }: { duration: number; time: number; view: [number, number]; pending: [number, number][]; applied: { start: number; end: number }[]; onJump: (t: number) => void }) {
  const D = Math.max(0.1, duration);
  const pct = (x: number) => `${Math.min(100, Math.max(0, (x / D) * 100))}%`;
  return (
    <div
      className="tp-mini"
      role="slider"
      aria-label={t('te.minimap')}
      aria-valuemin={0}
      aria-valuemax={Math.round(D)}
      aria-valuenow={Math.round(time)}
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onJump(((e.clientX - r.left) / r.width) * D);
      }}
      data-testid="transcript-minimap"
    >
      <i className="track" />
      <i className="view" style={{ left: pct(view[0]), width: `calc(${pct(view[1])} - ${pct(view[0])})` }} />
      {applied.map((c, k) => (
        <i key={`a${k}`} className="cut a" style={{ left: pct(c.start), width: `calc(${pct(c.end)} - ${pct(c.start)})` }} />
      ))}
      {pending.map(([a, b], k) => (
        <i key={`p${k}`} className="cut p" style={{ left: pct(a), width: `max(3px, calc(${pct(b)} - ${pct(a)}))` }} />
      ))}
      <i className="head" style={{ left: pct(time) }} />
    </div>
  );
}
