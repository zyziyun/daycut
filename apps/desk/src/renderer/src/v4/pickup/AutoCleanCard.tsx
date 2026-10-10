// A recording's automatic first pass, on top of the editor's chat (ux/record/pickups A1): what was already cut -
// dropped retakes, ums, long pauses - with "Bring back all" per kind (one undo step). Each cut is also a marker in the
// transcript ("retake 4.1 s") whose popover shows the words and Restore. Hidden once nothing of it is left.
import { useState } from 'react';
import { RotateCcw, Sparkles } from 'lucide-react';
import type { OutputDoc } from '../../../../shared/v04';
import { t } from '../../i18n';
import { autoKinds, type AutoKind } from './pickupModel';

export function AutoCleanCard({ doc, restore }: { doc: OutputDoc; restore: (indexes: number[]) => Promise<boolean> }) {
  const [busy, setBusy] = useState<AutoKind | null>(null);
  const kinds = autoKinds(doc);
  if (!kinds) return null;
  const rows: [AutoKind, string][] = [
    ['retake', t('pk.auto.retakes', { n: kinds.retake.length })],
    ['filler', t('pk.auto.fillers', { n: kinds.filler.length })],
    ['pause', t('pk.auto.pauses', { n: kinds.pause.length })],
  ];
  return (
    <div className="ux-pin decided" data-testid="auto-clean-card">
      <div className="ux-pin-hd">
        <Sparkles className="ico" />
        <b>{t('pk.auto.title')}</b>
      </div>
      <div className="ux-pin-t muted dec-lead">{t('pk.auto.lead')}</div>
      <div className="ux-pin-opts">
        {rows
          .filter(([k]) => kinds[k].length > 0)
          .map(([k, label]) => (
            <div key={k} className="dec-row" data-testid="auto-clean-row" data-kind={k}>
              <div className="dec-main">
                <div className="dec-tx">
                  <div className="clamp1">{label}</div>
                  {k === 'retake' && <div className="muted small clamp1">{t('pk.auto.retakeWhy')}</div>}
                </div>
                <button
                  className="btn ghost sm"
                  disabled={busy != null}
                  onClick={() => {
                    setBusy(k);
                    void restore(kinds[k]).finally(() => setBusy(null));
                  }}
                  data-testid="auto-clean-restore"
                >
                  <RotateCcw className="ico" />
                  {t('pk.auto.bringBack')}
                </button>
              </div>
            </div>
          ))}
      </div>
    </div>
  );
}
