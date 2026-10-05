import { useEffect, useRef, useState, type ReactNode } from 'react';
import { t, tState } from '../i18n';

export function QcLight({ qc, title }: { qc: string | null | undefined; title?: string }) {
  const cls = qc === 'green' ? 'green' : qc === 'red' ? 'red' : '';
  return <span className={`light ${cls}`} title={title ?? (qc ? t(`qc.${qc}`) : t('qc.none'))} />;
}

export function StateBadge({ state }: { state: string }) {
  const tone = state === 'failed' || state === 'paused' || state === 'missing' ? 'danger' : state === 'approved' || state === 'pilot-review' ? 'accent' : '';
  return <span className={`badge ${tone}`}>{tState(state)}</span>;
}

export function ErrorBox({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return <div className="err small">{error}</div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={title}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        {children}
      </div>
    </div>
  );
}

/** A text prompt as a modal (window.prompt does not exist in Electron). */
export function PromptModal({
  title,
  placeholder,
  okLabel,
  onOk,
  onCancel,
}: {
  title: string;
  placeholder?: string;
  okLabel?: string;
  onOk: (v: string) => void;
  onCancel: () => void;
}) {
  const [v, setV] = useState('');
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <Modal title={title} onClose={onCancel}>
      <input
        ref={ref}
        className="input"
        value={v}
        placeholder={placeholder}
        maxLength={500}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onOk(v.trim());
          e.stopPropagation();
        }}
      />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onCancel}>
          {t('common.cancel')}
        </button>
        <button className="btn primary" onClick={() => onOk(v.trim())}>
          {okLabel ?? t('common.ok')}
        </button>
      </div>
    </Modal>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="muted" style={{ padding: 32, textAlign: 'center' }}>{children}</div>;
}

export function Media({ path, kind, className }: { path: string | null | undefined; kind: 'img' | 'video'; className?: string }) {
  if (!path) return <div className={`thumb ph ${className ?? ''}`}>{t('common.noPreview')}</div>;
  const src = window.desk.mediaUrl(path);
  return kind === 'img' ? (
    <img className={`thumb ${className ?? ''}`} src={src} loading="lazy" alt="" />
  ) : (
    <video className={`thumb ${className ?? ''}`} src={src} controls playsInline preload="metadata" />
  );
}
