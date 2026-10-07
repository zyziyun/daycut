// The Mac App Store "Lite" build says what it leaves out, once, plainly, with the way to the full version. Renders
// nothing in the full edition (src/shared/edition.ts).
import { ExternalLink } from 'lucide-react';
import { FULL_DOWNLOAD_URL, IS_LITE } from '../../../shared/edition';
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
      <div>
        <button className="btn sm" onClick={() => void window.desk.openExternal(FULL_DOWNLOAD_URL)} data-testid="lite-full">
          <ExternalLink className="ico" />
          {t('lite.cta')}
        </button>
      </div>
    </div>
  );
}

/** First run / Settings › AI in the Lite build: API keys and local models, and why there is no subscription sign-in. */
export function LiteAiNote() {
  if (!IS_LITE) return null;
  return (
    <div className="col" style={{ gap: 4 }} data-testid="lite-ai">
      <span className="small">{t('lite.aiBody')}</span>
      <span className="muted small">
        {t('lite.aiSubs')}{' '}
        <button className="s2-link" onClick={() => void window.desk.openExternal(FULL_DOWNLOAD_URL)}>
          {t('lite.cta')}
        </button>
      </span>
    </div>
  );
}
