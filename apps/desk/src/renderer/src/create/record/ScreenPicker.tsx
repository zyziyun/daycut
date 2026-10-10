// The Screen popover's content: "Share a screen too" lists her screens and windows (rec:screens, thumbnails), a click
// shares that one. Every outcome is visible: Screen Recording off on macOS -> plain steps + a button that opens the
// System Settings pane; any other failure -> its message. Never a silent no-op (0.2.4 did nothing at all).
import { useState } from 'react';
import { AppWindow, Monitor } from 'lucide-react';
import type { ScreenSource } from '../../../../shared/recIpc';
import { t } from '../../i18n';
import type { ScreenResult } from './useRecorder';

type View = { k: 'idle' } | { k: 'loading' } | { k: 'list'; sources: ScreenSource[] } | { k: 'denied' } | { k: 'error'; msg: string };

export function ScreenPicker({ on, share, stop, done }: { on: boolean; share: (id: string) => Promise<ScreenResult>; stop: () => void; done: () => void }) {
  const [view, setView] = useState<View>({ k: 'idle' });
  const [busy, setBusy] = useState<string | null>(null);

  const list = async () => {
    setView({ k: 'loading' });
    try {
      const r = await window.desk.rec.screens();
      if (r.access === 'denied') setView({ k: 'denied' });
      else if (!r.sources.length) setView({ k: 'error', msg: t('rec.screenNone') });
      else setView({ k: 'list', sources: r.sources });
    } catch (e) {
      setView({ k: 'error', msg: String((e as Error)?.message ?? e) });
    }
  };

  const pick = async (s: ScreenSource) => {
    setBusy(s.id);
    const r = await share(s.id);
    setBusy(null);
    if (r === 'on') {
      setView({ k: 'idle' });
      done();
    } else if (r === 'denied') setView({ k: 'denied' });
    else setView({ k: 'error', msg: t('rec.screenFailed', { msg: r.error }) });
  };

  if (on && view.k === 'idle')
    return (
      <>
        <div className="rs-note">{t('rec.screenSharing')}</div>
        <button
          type="button"
          className="btn sm"
          onClick={() => {
            stop();
            done();
          }}
          data-testid="rec-screen-toggle"
        >
          {t('rec.screenStop')}
        </button>
      </>
    );
  if (view.k === 'denied')
    return (
      <div className="rs-screen-denied" role="alert" data-testid="rec-screen-denied">
        <div className="rs-note strong">{t('rec.screenDeniedTitle')}</div>
        <ol className="rs-steps">
          <li>{t('rec.screenDenied1')}</li>
          <li>{t('rec.screenDenied2')}</li>
          <li>{t('rec.screenDenied3')}</li>
        </ol>
        <div className="rs-row">
          <button type="button" className="btn sm primary" onClick={() => void window.desk.rec.openPrivacy('screen')} data-testid="rec-screen-settings">
            {t('rec.screenOpenSettings')}
          </button>
          <button type="button" className="btn sm" onClick={() => void list()} data-testid="rec-screen-retry">
            {t('rec.screenRetry')}
          </button>
        </div>
      </div>
    );
  if (view.k === 'list')
    return (
      <>
        <div className="rs-note">{t('rec.screenChoose')}</div>
        <div className="rs-sources" data-testid="rec-screen-sources">
          {view.sources.map((s) => (
            <button type="button" key={s.id} className="rs-src" disabled={!!busy} onClick={() => void pick(s)} title={s.name} data-testid="rec-screen-source">
              {s.thumb ? <img src={s.thumb} alt="" /> : <span className="ph">{s.kind === 'screen' ? <Monitor className="ico" /> : <AppWindow className="ico" />}</span>}
              <span className="nm">{busy === s.id ? t('rec.screenStarting') : s.name || (s.kind === 'screen' ? t('rec.screenWhole') : t('rec.screenWindow'))}</span>
            </button>
          ))}
        </div>
      </>
    );
  return (
    <>
      <div className="rs-note">{t('rec.screenBody')}</div>
      {view.k === 'error' && (
        <div className="rs-note err" role="alert" data-testid="rec-screen-error">
          {view.msg}
        </div>
      )}
      <button type="button" className="btn sm" disabled={view.k === 'loading'} onClick={() => void list()} data-testid="rec-screen-toggle">
        {view.k === 'loading' ? t('rec.screenLooking') : t('rec.screenShare')}
      </button>
    </>
  );
}
