// A control-bar button that opens a small panel above it (camera, microphone, screen, settings). Closes on Escape,
// on a click outside, or when another one opens.
import { useEffect, useRef, type ReactNode } from 'react';
import { ChevronUp } from 'lucide-react';

export function Pop({
  id,
  open,
  onOpen,
  label,
  icon,
  text,
  extra,
  title,
  children,
  testId,
  className = '',
}: {
  id: string;
  open: string | null;
  onOpen: (id: string | null) => void;
  label: string;
  icon: ReactNode;
  text?: ReactNode;
  extra?: ReactNode;
  title?: string;
  children: ReactNode;
  testId: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const isOpen = open === id;
  useEffect(() => {
    if (!isOpen) return;
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOpen(null);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpen(null);
    };
    window.addEventListener('mousedown', down);
    window.addEventListener('keydown', key);
    return () => {
      window.removeEventListener('mousedown', down);
      window.removeEventListener('keydown', key);
    };
  }, [isOpen, onOpen]);
  return (
    <div className="rs-pop" ref={ref}>
      <button type="button" className={`rs-ctl ${isOpen ? 'on' : ''} ${className}`} aria-label={label} aria-expanded={isOpen} title={title ?? label} onClick={() => onOpen(isOpen ? null : id)} data-testid={testId}>
        {icon}
        {text && <span className="tx">{text}</span>}
        {extra}
        <ChevronUp className="car" />
      </button>
      {isOpen && (
        <div className="rs-panel" role="dialog" aria-label={label} data-testid={`${testId}-panel`}>
          {children}
        </div>
      )}
    </div>
  );
}
