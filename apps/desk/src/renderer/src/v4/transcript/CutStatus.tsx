// The quiet line that replaced "N cuts pending · Apply cuts" (ux/fewer-steps): a delete in the transcript takes effect
// at once - the preview skips it - and is saved by itself a moment later. This says so in a few words, with Undo
// (⌘Z); a save that failed says why, with Retry, and keeps the cut in the preview until it is saved or discarded.
import { AlertTriangle, Check, LoaderCircle, Undo2 } from 'lucide-react';
import { t } from '../../i18n';
import { keyHint } from '../../lib/keys';

export type CutSave =
  | { kind: 'idle' }
  | { kind: 'saving'; secs: number }
  | { kind: 'saved'; secs: number; step: string | null }
  | { kind: 'short' }
  | { kind: 'error'; why: string };

export function CutStatus({ s, note, onUndo, onRetry, onDiscard }: { s: CutSave; note?: string | null; onUndo: () => void; onRetry: () => void; onDiscard: () => void }) {
  if (s.kind === 'idle') return null;
  const secs = 'secs' in s && s.secs > 0.05 ? `−${s.secs.toFixed(1)} s` : null;
  return (
    <div className={`tp-status ${s.kind}`} role="status" aria-live="polite" data-testid="cut-status" data-state={s.kind}>
      {s.kind === 'saving' && <LoaderCircle className="ico spin" />}
      {s.kind === 'saved' && <Check className="ico ok" />}
      {(s.kind === 'error' || s.kind === 'short') && <AlertTriangle className="ico warn" />}
      <span className="clamp1" title={s.kind === 'error' ? s.why : undefined}>
        {s.kind === 'saving' ? t('fs.cut.saving') : s.kind === 'saved' ? t('fs.cut.saved') : s.kind === 'short' ? t('te.tooShort') : t('fs.cut.failed', { why: s.why })}
      </span>
      {secs && <span className="minus num">{secs}</span>}
      {note && s.kind !== 'error' && <span className="note clamp1" title={note}>· {note}</span>}
      {s.kind === 'error' ? (
        <>
          <button className="btn sm" onClick={onRetry} data-testid="cut-status-retry">
            {t('fs.retry')}
          </button>
          <button className="btn ghost sm" onClick={onDiscard} data-testid="cut-status-discard">
            {t('te.discard')}
          </button>
        </>
      ) : s.kind === 'saving' ? null : (
        <button className="btn ghost sm" onClick={onUndo} data-tip={`${t('c.undo')} · ${keyHint('⌘Z')}`} data-testid="cut-status-undo">
          <Undo2 className="ico" />
          {t('c.undo')}
        </button>
      )}
    </div>
  );
}
