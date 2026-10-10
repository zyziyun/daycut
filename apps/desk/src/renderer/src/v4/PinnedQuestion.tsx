// The inbox question pinned on top of the editor's chat (ux/home-redesign I3): arrived from the Inbox (or reviewing in
// a row), the same plain-language options as the Inbox and ONE Confirm ↵ (ux/fewer-steps: Skip only while reviewing in
// a row). The edits are already in the preview - the ticked cuts the clip does not have yet are skipped while it
// plays - so Confirm keeps what she just watched. Options on this clip jump the player there; an option on another
// clip opens that clip (the question stays pinned).
import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Inbox as InboxIcon } from 'lucide-react';
import type { InboxItem } from '../../../shared/v04';
import { fmtAgo, t } from '../i18n';
import { locateCut } from '../lib/decided';
import { clipHref, triageStep, useTriageState } from '../lib/nav';
import { answerOf, inboxTitle, OptionCard, useResolve } from './Inbox';
import { isTyping } from './ui';

export function PinnedQuestion({
  item,
  items,
  clip,
  seek,
  onSkip,
  words,
  onPreviewCuts,
}: {
  item: InboxItem;
  items: InboxItem[];
  clip: string;
  seek: (t: number) => void;
  onSkip: () => void;
  /** the clip's words: a ticked filler cut that is still in the clip is found there and skipped in the preview */
  words?: { w: string; t: number; te: number }[];
  onPreviewCuts?: (spans: [number, number][]) => void;
}) {
  const opts = useMemo(() => item.options ?? [], [item.options]);
  const triage = useTriageState();
  const resolve = useResolve();
  const [picked, setPicked] = useState<Set<string>>(() => new Set(opts.filter((o) => o.checked !== false).map((o) => o.id)));
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [act, setAct] = useState<string | null>(opts.find((o) => o.clip_id === clip)?.id ?? null);
  // pre-applied: what she keeps ticked plays without it, before she confirms
  const spans = useMemo(() => {
    const out: [number, number][] = [];
    for (const o of opts) {
      if (!picked.has(o.id) || o.kind !== 'filler' || (o.clip_id && o.clip_id !== clip)) continue;
      const at = words?.length ? locateCut(words, o.text, o.ctx) : null;
      if (at?.present) out.push([at.t, at.te]);
    }
    return out;
  }, [opts, picked, words, clip]);
  const skey = JSON.stringify(spans);
  useEffect(() => onPreviewCuts?.(spans), [skey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onPreviewCuts?.([]), []); // eslint-disable-line react-hooks/exhaustive-deps
  const confirm = async () => {
    if (await resolve(item, item.kind === 'confirm' || opts.length ? answerOf(item, picked, choices) : undefined)) {
      if (triage) triageStep(items, 1, item.key);
      else history.back();
    }
  };
  const ref = useRef(confirm);
  ref.current = confirm;
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || e.key !== 'Enter') return;
      if (document.querySelector('.scrim, .ctx')) return;
      if ((e.target as HTMLElement | null)?.closest?.('button, a, .tp-body')) return;
      e.preventDefault();
      void ref.current();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);
  const cuts = item.kind === 'confirm' || item.kind === 'filler-confirm';
  const lead = cuts && opts.length ? t('fs.pin.lead', { n: picked.size }) : item.kind === 'confirm' ? t('pin.lead', { n: opts.length }) : inboxTitle(item);
  return (
    <div className="ux-pin" data-testid="pinned-question">
      <div className="ux-pin-hd">
        <InboxIcon className="ico" />
        <b>{t('pin.from')}</b>
        <span className="sp" />
        {item.at ? <span className="muted">{t('pin.asked', { ago: fmtAgo(item.at) })}</span> : null}
      </div>
      <div className="ux-pin-t">{lead}</div>
      <div className="ux-pin-opts">
        {opts.map((o, i) => (
          <OptionCard
            key={o.id}
            o={o}
            n={i + 1}
            compact
            on={picked.has(o.id)}
            act={act === o.id}
            choice={choices[o.id] ?? o.choice ?? null}
            onToggle={(v) =>
              setPicked((s) => {
                const n = new Set(s);
                if (v) n.add(o.id);
                else n.delete(o.id);
                return n;
              })
            }
            onChoice={(c) => setChoices((m) => ({ ...m, [o.id]: c }))}
            onPlay={() => {
              setAct(o.id);
              if (o.clip_id && o.clip_id !== clip && item.project.id) location.hash = clipHref(item.project.id, o.clip_id, { t: o.at, item: item.key, triage: !!triage });
              else if (o.at != null) seek(o.at);
            }}
          />
        ))}
      </div>
      <div className="ux-pin-ft">
        {triage && (
          <button className="btn ghost" onClick={onSkip} data-testid="pin-skip">
            {t('inbox.skipShort')}
          </button>
        )}
        <span className="sp" />
        <button className="btn primary" onClick={() => void confirm()} data-testid="pin-confirm">
          <Check className="ico" />
          {triage ? t('pin.confirmNext') : t('pin.confirm')}
          <span className="kbd on">↵</span>
        </button>
      </div>
    </div>
  );
}
