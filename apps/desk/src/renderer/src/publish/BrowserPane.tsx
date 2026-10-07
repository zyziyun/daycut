// The built-in browser's place in a screen: a toolbar (back, reload, the address, "Capture this page") and the slot
// the platform view is laid over (the view itself is a native WebContentsView in main; this only sends bounds).
import { useLayoutEffect, useRef } from 'react';
import { ScanLine } from 'lucide-react';
import type { PublishStateMsg } from '../../../shared/deskApi';
import { t } from '../i18n';
import { errText } from '../v4/msg';
import { useUi } from '../v4/ui';

/** Redacted snapshot of the open platform page -> a local file (for tuning an adapter's selectors). */
export async function capturePage(ui: ReturnType<typeof useUi>) {
  try {
    const r = await window.desk.publish.capture();
    ui.toast(t('pl.capture.saved', { n: r.nodes }), { ms: 7000 });
    void window.desk.showItem(r.file);
  } catch (e) {
    ui.toast(errText(e), { error: true });
  }
}

export function BrowserPane({ open, hidden, state, hint }: { open: boolean; hidden?: boolean; state: PublishStateMsg | null; hint: string }) {
  const ui = useUi();
  const slot = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = slot.current;
    if (!el) return;
    const send = () => {
      const r = el.getBoundingClientRect();
      const show = open && !hidden;
      void window.desk.publish.setBounds(show ? { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) } : { x: 0, y: 0, width: 0, height: 0 });
    };
    send();
    const ro = new ResizeObserver(send);
    ro.observe(el);
    window.addEventListener('resize', send);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', send);
    };
  }, [open, hidden]);
  return (
    <div className="col" style={{ gap: 6, minHeight: 0, flex: 1 }}>
      <div className="browser-bar">
        <button className="btn sm" disabled={!open || !state?.canGoBack} onClick={() => window.desk.publish.navigate('back')} aria-label={t('ch.back')}>
          ←
        </button>
        <button className="btn sm" disabled={!open} onClick={() => window.desk.publish.navigate('reload')} aria-label={t('ch.reload')}>
          ⟳
        </button>
        <span className="url mono">{open ? `${state?.loading ? '… ' : ''}${state?.url ?? ''}` : ''}</span>
        <button className="btn ghost sm" disabled={!open} onClick={() => void capturePage(ui)} data-tip={t('pl.capture.hint')} data-testid="capture-page">
          <ScanLine className="ico" />
          {t('pl.capture')}
        </button>
      </div>
      <div className="browser-slot" ref={slot} style={{ flex: 1, minHeight: 480 }} data-testid="post-slot">
        {!open && <span>{hint}</span>}
      </div>
    </div>
  );
}
