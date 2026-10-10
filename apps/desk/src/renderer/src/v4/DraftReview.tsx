// An author step in the Inbox (vstudio.project.drafts): the engine drafted the file; she checks the DRAFT in plain
// words - never the file. Keep spans: her transcript, kept sentences plain and cut ones crossed out with the AI's
// label; a click (or a text selection + Cut / Keep selected) changes it. Captions and footage / a script / a config:
// a summary and one plain line per part (a script shows its text). Every kind: "tell the AI what to change" (a new
// draft in the background) and "Advanced: open the file" at the bottom. Nothing drafted yet: "Draft it for me".
import { useEffect, useMemo, useRef, useState } from 'react';
import { RotateCcw, Scissors, Send, Sparkles } from 'lucide-react';
import type { DraftReview, DraftSegment, InboxAuthor } from '../../../shared/v04';
import { fmtClock, t } from '../i18n';
import { draftSummary, keptOf, keptSeconds, mmss } from '../lib/inboxView';
import { useEngine } from '../lib/engine';
import { useInbox } from '../lib/inbox';
import { More } from './kit';
import { errText } from './msg';
import { useUi } from './ui';

export type KeepEdits = Record<number, boolean>;

/** The one line under the title: the draft's summary (her clicks counted in for keep spans). */
export function draftLine(rv: DraftReview, edits?: KeepEdits | null): string {
  if (rv.kind === 'keep-spans' && rv.segments?.length && edits && Object.keys(edits).length) {
    const kept = keptOf(rv.segments, edits);
    return t('draft.keepMine', { kept: mmss(keptSeconds(rv.segments, kept)), total: mmss(rv.total_s ?? 0) });
  }
  return draftSummary(rv.summary);
}

export function DraftPane({ itemKey, a, edits, onEdits }: { itemKey: string; a: InboxAuthor; edits: KeepEdits | null; onEdits: (e: KeepEdits | null) => void }) {
  const rv = a.review ?? null;
  return (
    <div className="col ux-draft" style={{ gap: 12, minWidth: 0 }} data-testid="inbox-draft" data-state={a.drafting ? 'drafting' : a.state ?? ''}>
      {a.drafting ? (
        <div className="ux-opt" data-testid="draft-drafting">
          <div className="ux-optt">
            <Sparkles className="ico" /> {t('draft.drafting')}
          </div>
          <div className="muted">{t('draft.lead.drafting')}</div>
        </div>
      ) : !rv ? (
        <div className="ux-opt" data-testid="draft-none">
          <div className="ux-optt">{a.can_draft ? t('draft.noneCan') : t('draft.lead.none')}</div>
          {a.draft_error ? (
            <div className="muted" data-testid="draft-error">
              {t('draft.failed', { reason: a.draft_error })}
            </div>
          ) : !a.can_draft ? (
            <div className="muted">{t('draft.noAi')}</div>
          ) : null}
        </div>
      ) : (
        <>
          <div className="ux-draft-sum" data-testid="draft-summary">
            <b>{draftLine(rv, edits)}</b>
            <span className="muted small"> · {t(`draft.by.${rv.by === 'her' ? 'her' : rv.by === 'rules' ? 'rules' : 'ai'}` as 'draft.by.ai')}</span>
          </div>
          {rv.kind === 'keep-spans' && rv.segments?.length ? (
            <KeepTranscript segs={rv.segments} rv={rv} edits={edits} onEdits={onEdits} />
          ) : (
            <DraftLines rv={rv} />
          )}
        </>
      )}
      {a.can_draft && !a.drafting && rv && <AskBox itemKey={itemKey} />}
      <Advanced itemKey={itemKey} a={a} />
    </div>
  );
}

function DraftLines({ rv }: { rv: DraftReview }) {
  return (
    <div className="col" style={{ gap: 6 }} data-testid="draft-lines">
      {(rv.lines ?? []).map((l, i) => (
        <div key={i} className="ux-draft-line" data-testid="draft-line">
          {draftSummary(l)}
        </div>
      ))}
      {rv.kind === 'text' && rv.text ? (
        <div className="ux-draft-text" data-testid="draft-text">
          {rv.text}
        </div>
      ) : null}
    </div>
  );
}

/** Her transcript: kept sentences plain, cut ones crossed out (+ the AI's label). A click toggles a sentence; a text
 * selection over several offers Cut selected / Keep selected. */
function KeepTranscript({ segs, rv, edits, onEdits }: { segs: DraftSegment[]; rv: DraftReview; edits: KeepEdits | null; onEdits: (e: KeepEdits | null) => void }) {
  const box = useRef<HTMLDivElement | null>(null);
  const [sel, setSel] = useState<number[]>([]);
  const kept = useMemo(() => keptOf(segs, edits), [segs, edits]);
  const set = (ids: number[], keep: boolean) => {
    const next = { ...(edits ?? {}) };
    for (const i of ids) {
      const s = segs.find((x) => x.i === i);
      if (!s) continue;
      if (keep === s.keep) delete next[i];
      else next[i] = keep;
    }
    onEdits(Object.keys(next).length ? next : null);
  };
  useEffect(() => {
    const on = () => {
      const s = window.getSelection();
      if (!s || s.isCollapsed || !box.current || !box.current.contains(s.anchorNode)) return setSel([]);
      const ids = [...box.current.querySelectorAll<HTMLElement>('[data-i]')].filter((el) => s.containsNode(el, true)).map((el) => Number(el.dataset.i));
      setSel(ids.length > 1 ? ids : []);
    };
    document.addEventListener('selectionchange', on);
    return () => document.removeEventListener('selectionchange', on);
  }, []);
  const extra = [rv.hooks ? t('draft.hooks', { n: rv.hooks }) : '', rv.speeds?.body ? t('draft.speed', { x: rv.speeds.body }) : ''].filter(Boolean);
  return (
    <div className="col" style={{ gap: 8, minWidth: 0 }}>
      {extra.length > 0 && <div className="muted small">{extra.join(' · ')}</div>}
      <div className="row" style={{ gap: 8, minHeight: 30 }}>
        <span className="muted small">{t('draft.toggleHint')}</span>
        <span className="sp" />
        {sel.length > 1 && (
          <>
            <button className="btn sm" onClick={() => (set(sel, false), window.getSelection()?.removeAllRanges())} data-testid="draft-sel-cut">
              <Scissors className="ico" />
              {t('draft.selCut')}
            </button>
            <button className="btn sm" onClick={() => (set(sel, true), window.getSelection()?.removeAllRanges())} data-testid="draft-sel-keep">
              {t('draft.selKeep')}
            </button>
          </>
        )}
        {edits && (
          <button className="btn ghost sm" onClick={() => onEdits(null)} data-testid="draft-reset">
            <RotateCcw className="ico" />
            {t('draft.reset')}
          </button>
        )}
      </div>
      <div className="ux-keep" ref={box} data-testid="draft-transcript" lang="">
        {segs.map((s) => {
          const on = kept.has(s.i);
          return (
            <span
              key={s.i}
              data-i={s.i}
              className={`ux-sent ${on ? 'kept' : 'cut'} ${edits && s.i in edits ? 'mine' : ''}`}
              data-testid="draft-sentence"
              data-keep={on ? '1' : '0'}
              title={fmtClock(s.t)}
              onClick={() => {
                if (!window.getSelection()?.isCollapsed) return;
                set([s.i], !on);
              }}
            >
              {s.text}
              {!on && s.label ? <i className="ux-cutlab">{s.label}</i> : null}{' '}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** "Tell the AI what to change": a new draft in the background (the item shows Drafting… until it is in). */
function AskBox({ itemKey }: { itemKey: string }) {
  const { client } = useEngine();
  const { reload } = useInbox();
  const ui = useUi();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!client || !text.trim()) return;
    setBusy(true);
    try {
      await client.redraftInbox(itemKey, text.trim());
      setText('');
      ui.toast(t('draft.sent'));
      reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="row ux-draft-ask"
      style={{ gap: 8 }}
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <input className="inp" value={text} onChange={(e) => setText(e.target.value)} placeholder={t('draft.ask')} disabled={busy} data-testid="draft-ask" />
      <button className="btn" type="submit" disabled={busy || !text.trim()} data-testid="draft-ask-send">
        <Send className="ico" />
        {t('draft.askSend')}
      </button>
    </form>
  );
}

function Advanced({ itemKey, a }: { itemKey: string; a: InboxAuthor }) {
  const { client } = useEngine();
  const ui = useUi();
  if (!a.file || !a.exists) return null;
  return (
    <More summary={t('draft.advanced')} testId="draft-advanced">
      <button
        className="btn ghost sm"
        onClick={() => void client?.openInboxFile(itemKey, 'file').catch((e) => ui.toast(errText(e), { error: true }))}
        data-testid="draft-open-file"
      >
        {t('inbox.author.open')}
      </button>
    </More>
  );
}

/** "Draft it for me" (nothing drafted yet, or a failed draft): the engine drafts it in the background. */
export function useDraftIt(itemKey: string) {
  const { client } = useEngine();
  const { reload } = useInbox();
  const ui = useUi();
  return async () => {
    if (!client) return;
    try {
      await client.redraftInbox(itemKey);
      reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
}
