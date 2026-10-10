// "● 3 cuts pending −5.0 s · skipped in preview | Discard | Apply cuts ⌘↵" floating over the lower pane. Apply is the
// one filled button while cuts are pending; it is off (with the reason) when less than a second would be left.
import { Scissors } from 'lucide-react';
import { t } from '../../i18n';
import { keyHint } from '../../lib/keys';

export function PendingBar({ n, secs, tooShort, note, busy, onDiscard, onApply }: { n: number; secs: number; tooShort: boolean; note?: string | null; busy: boolean; onDiscard: () => void; onApply: () => void }) {
  return (
    <div className="tp-pending" role="status" data-testid="pending-bar">
      <i className="dot" />
      <b data-testid="pending-count">{t('te.pending', { n })}</b>
      <span className="minus num" data-testid="pending-secs">
        −{secs.toFixed(1)} s
      </span>
      <span className="muted">· {tooShort ? t('te.tooShort') : t('te.skipped')}</span>
      {note && <span className="warn clamp1" title={note}>{note}</span>}
      <span className="sp" />
      <button className="btn ghost" onClick={onDiscard} data-testid="pending-discard">
        {t('te.discard')}
      </button>
      <button className="btn primary" disabled={tooShort || busy} onClick={onApply} title={tooShort ? t('te.tooShort') : undefined} data-testid="pending-apply">
        <Scissors className="ico" />
        {busy ? t('ce.applying') : t('te.apply')}
        <span className="kbd on">{keyHint('⌘↵')}</span>
      </button>
    </div>
  );
}
