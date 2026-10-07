// macOS-style settings building blocks: a titled group card, a row (label + hint left, control right), segmented
// control, colour swatches, a switch (a real checkbox), a disclosure row, the one "Restart to apply" bar, a sheet.
import { useEffect, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { t } from '../i18n';

export function Page({ title, lead, children, testId }: { title: string; lead?: string; children: ReactNode; testId?: string }) {
  return (
    <div className="s2-page" data-testid={testId}>
      <h1>{title}</h1>
      {lead && <p className="s2-lead">{lead}</p>}
      {children}
    </div>
  );
}

export function Group({ title, action, children, testId }: { title?: ReactNode; action?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section className="s2-group" data-testid={testId}>
      {(title || action) && (
        <div className="s2-gtitle">
          <span>{title}</span>
          {action}
        </div>
      )}
      <div className="s2-card">{children}</div>
    </section>
  );
}

export function Row({ label, hint, children, icon, testId, title }: { label: ReactNode; hint?: ReactNode; children?: ReactNode; icon?: ReactNode; testId?: string; title?: string }) {
  return (
    <div className="s2-row" data-testid={testId} title={title}>
      {icon && <span className="s2-ricon">{icon}</span>}
      <div className="s2-rtext">
        <div className="s2-rlabel">{label}</div>
        {hint && <div className="s2-rhint">{hint}</div>}
      </div>
      {children !== undefined && <div className="s2-rctl">{children}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, testId }: { value: T; options: { v: T; label: string; testId?: string }[]; onChange: (v: T) => void; testId?: string }) {
  return (
    <div className="s2-seg" role="radiogroup" data-testid={testId}>
      {options.map((o) => (
        <button key={o.v} role="radio" aria-checked={o.v === value} className={o.v === value ? 'on' : ''} onClick={() => o.v !== value && onChange(o.v)} data-testid={o.testId} data-v={o.v}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Swatches<T extends string>({ value, options, onChange }: { value: T; options: { v: T; color: string; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="s2-sw" role="radiogroup">
      {options.map((o) => (
        <button key={o.v} role="radio" aria-checked={o.v === value} aria-label={o.label} data-tip={o.label} className={o.v === value ? 'on' : ''} style={{ ['--c' as string]: o.color }} onClick={() => onChange(o.v)} data-testid={`accent-${o.v}`} />
      ))}
    </div>
  );
}

/** A switch that is a real checkbox (keyboard, screen readers and Playwright's check() all work). It flips at once;
 * the saved value catches up when the setting comes back. */
export function Toggle({ checked, onChange, label, testId }: { checked: boolean; onChange: (v: boolean) => void; label: string; testId?: string }) {
  const [on, setOn] = useState(checked);
  useEffect(() => setOn(checked), [checked]);
  return (
    <label className={`s2-tgl ${on ? 'on' : ''}`}>
      <input
        type="checkbox"
        role="switch"
        checked={on}
        onChange={(e) => {
          setOn(e.target.checked);
          onChange(e.target.checked);
        }}
        aria-label={label}
        data-testid={testId}
      />
      <i />
    </label>
  );
}

export function Disclosure({
  icon,
  label,
  hint,
  value,
  open,
  onToggle,
  children,
  testId,
}: {
  icon: ReactNode;
  label: string;
  hint: string;
  value?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children?: ReactNode;
  testId?: string;
}) {
  return (
    <div className={`s2-disc ${open ? 'open' : ''}`} data-testid={testId}>
      <button className="s2-dhead" onClick={onToggle} aria-expanded={open}>
        <span className="s2-ricon box">{icon}</span>
        <span className="s2-rtext">
          <span className="s2-rlabel">{label}</span>
          <span className="s2-rhint">{hint}</span>
        </span>
        {value && <span className="s2-dval">{value}</span>}
        {children !== undefined ? open ? <ChevronDown className="ico" /> : <ChevronDown className="ico" style={{ transform: 'rotate(-90deg)' }} /> : <ChevronRight className="ico" />}
      </button>
      {open && children !== undefined && <div className="s2-dbody">{children}</div>}
    </div>
  );
}

export function RestartBar({ text, onRestart, testId = 'restart-bar' }: { text: string; onRestart: () => void; testId?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="s2-restart" data-testid={testId}>
      <span>{text}</span>
      <button
        className="btn primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onRestart();
          } finally {
            setBusy(false);
          }
        }}
        data-testid="restart-now"
      >
        {t('s2.restart.now')}
      </button>
    </div>
  );
}

export function Sheet({ title, children, onClose, wide, testId, footer }: { title: ReactNode; children: ReactNode; onClose: () => void; wide?: boolean; testId?: string; footer?: ReactNode }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
  return (
    <div className="scrim s2-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`s2-sheet ${wide ? 'wide' : ''}`} role="dialog" aria-label={typeof title === 'string' ? title : undefined} data-testid={testId}>
        <div className="s2-shead">
          <h2>{title}</h2>
          <button className="btn ghost icon" onClick={onClose} aria-label={t('s2.close')}>
            <X className="ico" />
          </button>
        </div>
        <div className="s2-sbody">{children}</div>
        {footer && <div className="s2-sfoot">{footer}</div>}
      </div>
    </div>
  );
}

export function Dot({ tone }: { tone: 'ok' | 'warn' | 'error' | 'off' | null }) {
  if (!tone) return null;
  return <i className={`s2-dot ${tone}`} aria-hidden />;
}
