// The Mac App Store "Lite" build says what it leaves out, once, plainly. It names no other download and links nowhere
// (App Review 3.1.1 / 2.3: no pointers to another way to get the app). Renders nothing in the full edition
// (src/shared/edition.ts).
import { IS_LITE } from '../../../shared/edition';
import { t } from '../i18n';

export function LiteCard({ compact = false }: { compact?: boolean }) {
  if (!IS_LITE) return null;
  return (
    <div className="card col" style={{ gap: 6, padding: '12px 14px' }} data-testid="lite-card">
      <div className="row" style={{ gap: 8, alignItems: 'baseline' }}>
        <b style={{ fontWeight: 600 }}>{t('lite.name')}</b>
        <span className="muted small">{t('lite.badge')}</span>
      </div>
      {!compact && <span className="small">{t('lite.body')}</span>}
    </div>
  );
}

/** First run / Settings › AI in the Lite build: API keys and local models. */
export function LiteAiNote() {
  if (!IS_LITE) return null;
  return (
    <div className="col" style={{ gap: 4 }} data-testid="lite-ai">
      <span className="small">{t('lite.aiBody')}</span>
    </div>
  );
}
