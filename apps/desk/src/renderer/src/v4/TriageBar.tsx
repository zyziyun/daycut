// "Review all in a row" (ux/home-redesign I3): a thin bar on top of the editor (or the Inbox for items without a clip)
// - ← Inbox · progress · n of N · what it is · Skip (S) · Next (J). Resolving the pinned question moves on by itself.
import { useEffect } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { InboxItem } from '../../../shared/v04';
import { t } from '../i18n';
import { endTriage, triageStep, useTriageState } from '../lib/nav';
import { inboxClip, inboxTitle } from './Inbox';
import { isTyping } from './ui';

export function TriageBar({ item, items, onSkip }: { item: InboxItem | null; items: InboxItem[]; onSkip?: () => void }) {
  const s = useTriageState();
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector('.scrim, .ctx')) return;
      const k = e.key.toLowerCase();
      if (k === 's') {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (onSkip) onSkip();
        else triageStep(items, 1);
      } else if (k === 'j') {
        // J is "next" while reviewing in a row (the player's J shuttle waits until the queue ends)
        e.preventDefault();
        e.stopImmediatePropagation();
        triageStep(items, 1);
      }
    };
    window.addEventListener('keydown', on, true);
    return () => window.removeEventListener('keydown', on, true);
  }, [items, onSkip]);
  if (!s) return null;
  const n = s.keys.length;
  return (
    <div className="ux-triage" data-testid="triage-bar">
      <button className="btn ghost" onClick={() => endTriage(true)} data-testid="triage-back">
        <ChevronLeft className="ico" />
        {t('nav.inbox')}
      </button>
      <span className="ux-tprog" aria-hidden>
        {s.keys.map((k, i) => (
          <i key={k} className={i < s.i ? 'done' : i === s.i ? 'on' : ''} />
        ))}
      </span>
      <b className="num" data-testid="triage-count">
        {t('triage.nOfN', { i: s.i + 1, n })}
      </b>
      {item && <span className="muted clamp1">· {[inboxTitle(item), inboxClip(item)].filter(Boolean).join(' · ')}</span>}
      <span className="sp" />
      <button className="btn ghost" onClick={() => (onSkip ? onSkip() : triageStep(items, 1))} data-testid="triage-skip">
        {t('inbox.skipShort')}
        <span className="kbd">S</span>
      </button>
      <button className="btn" onClick={() => triageStep(items, 1)} data-testid="triage-next">
        {t('triage.next')}
        <ChevronRight className="ico" />
        <span className="kbd">J</span>
      </button>
    </div>
  );
}
