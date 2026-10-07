// Fix a word in the captions (ux/text-edit §2.2): the original struck through, the new text, Enter saves. Only the
// caption text changes - never the sound or the timing - so it looks unlike a cut (a teal underline, not a red line).
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { t } from '../../i18n';

export function FixWordPopover({ anchor, word, original, canFix, whyNot, onSave, onCancel }: { anchor: HTMLElement | null; word: string; original: string; canFix: boolean; whyNot?: string; onSave: (text: string) => void; onCancel: () => void }) {
  const [v, setV] = useState(word);
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const inp = useRef<HTMLInputElement | null>(null);
  useLayoutEffect(() => {
    if (anchor) setPos({ x: Math.max(8, anchor.offsetLeft - 12), y: anchor.offsetTop + anchor.offsetHeight + 6 });
  }, [anchor]);
  useEffect(() => {
    inp.current?.focus();
    inp.current?.select();
  }, []);
  return (
    <div className="tp-fix" style={{ left: pos.x, top: pos.y }} onPointerDown={(e) => e.stopPropagation()} data-testid="fix-popover">
      <div className="lbl">{t('te.fixTitle')}</div>
      <div className="was" lang="zh-CN">
        <s>{original}</s>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <input
          ref={inp}
          className="inp"
          value={v}
          disabled={!canFix}
          lang="zh-CN"
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === 'Enter' && v.trim() && canFix) onSave(v.trim());
            else if (e.key === 'Escape') onCancel();
          }}
          data-testid="fix-input"
        />
        <button className="btn primary sm" disabled={!canFix || !v.trim() || v.trim() === word} onClick={() => onSave(v.trim())} data-testid="fix-save">
          <Check className="ico" />
        </button>
      </div>
      <div className="muted small">{canFix ? t('te.fixHint') : whyNot}</div>
    </div>
  );
}
