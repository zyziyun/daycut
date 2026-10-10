// The applied transcript cut in the chat (ux/text-edit 05): "Cut 3 phrases · −5.0 s · 1:23 → 1:18", the words that
// went (struck, with their time), what moved with them (captions re-timed, a note card shortened, every size
// updated) and Undo (one step for the whole batch) · Show in transcript.
import { Check, CheckCircle2, Scissors, Undo2 } from 'lucide-react';
import type { ChatDoc, ChatTurn, HistStep } from '../../../../shared/chatEdit';
import { fmtClock, fmtList, t } from '../../i18n';
import { effectLabel } from '../msg';
import { keyHint } from '../../lib/keys';

export interface CutCardMeta {
  before?: number;
  after?: number;
  /** kept with the turn, so the card still reads right once its step is undone */
  phrases?: number;
  pauses?: number;
  secs?: number;
}

export function cutMeta(turn: ChatTurn): CutCardMeta {
  try {
    const v = JSON.parse(turn.reply ?? '{}') as CutCardMeta;
    return typeof v === 'object' && v ? v : {};
  } catch {
    return {};
  }
}

export function CutCard({ turn, doc, state, onUndo, onRestore, onShow }: { turn: ChatTurn; doc: ChatDoc; state: string; onUndo: () => void; onRestore?: () => void; onShow: (t: number) => void }) {
  const step: HistStep | undefined = doc.steps.find((s) => s.id === turn.applied_step);
  const cuts = (step?.describe ?? []).filter((d) => d.code === 'op-cut').map((d) => ({ start: Number(d.params?.start ?? 0), end: Number(d.params?.end ?? 0), said: String(d.params?.said ?? ''), why: String(d.params?.why ?? '') }));
  const secs = cuts.reduce((s, c) => s + (c.end - c.start), 0);
  const m = cutMeta(turn);
  const rt = step?.retimed;
  const lines: string[] = [];
  const cap = rt?.captions;
  if (cap && (cap.retimed || cap.shortened || cap.removed)) lines.push(t('te.card.captions', { n: cap.retimed ?? 0, s: cap.shortened ?? 0, r: cap.removed ?? 0 }));
  for (const e of rt?.effects?.trimmed ?? []) lines.push(t('te.card.trimmed', { what: effectLabel(e.effect, e.label), a: e.from_s.toFixed(1), b: e.to_s.toFixed(1) }));
  if (rt?.effects?.removed?.length) lines.push(t('te.card.removed', { what: fmtList(rt.effects.removed.map((e) => effectLabel(e.effect, e.label))) }));
  if (rt?.sfx_removed) lines.push(t('te.card.sfx', { n: rt.sfx_removed }));
  const sizes = [...new Set([...(doc.files ?? []).map((f) => f.aspect).filter((a) => /^\d+:\d+$/.test(a)), ...(doc.exports ?? []).map((e) => (e.target.includes(':') && !/^\d/.test(e.target) ? '' : e.target)).filter(Boolean)])];
  if (sizes.length > 1) lines.push(t('te.card.sizes', { list: fmtList(sizes) }));
  else if (sizes.length === 1) lines.push(t('te.card.size', { a: sizes[0] }));
  const live = state === 'applied';
  const pauses = step ? cuts.filter((c) => c.why === 'pause').length : (m.pauses ?? 0);
  const phrases = step ? cuts.length - pauses : (m.phrases ?? 0);
  const total = step ? secs : (m.secs ?? 0);
  const gone = !step ? (turn.text ?? '').split(' / ').filter(Boolean) : [];
  return (
    <div className={`card2 cutcard ${live ? '' : 'muted2'}`} data-testid="cut-card">
      <div className="chd">
        <span className="ic">
          <Scissors className="ico" />
        </span>
        <div style={{ minWidth: 0 }}>
          <b>{phrases ? t('te.card.title', { n: phrases }) : t('te.card.titlePauses', { n: pauses })}</b>
          <div className="mono">
            −{total.toFixed(1)} s{m.before != null && m.after != null ? ` · ${fmtClock(m.before)} → ${fmtClock(m.after)}` : ''}
          </div>
        </div>
        <span style={{ flex: 1 }} />
        {live ? (
          <span className="ok-pill" data-testid="cut-card-applied">
            <Check className="ico" />
            {t('te.card.applied')}
          </span>
        ) : (
          <span className="muted">{state === 'reverted' ? t('te.card.undone') : t('ce.undone')}</span>
        )}
      </div>
      <div className="cbd">
        <div className="cutlist">
          {cuts
            .filter((c) => c.said)
            .slice(0, 8)
            .map((c, k) => (
              <div key={k} className="cutrow">
                <s className="clamp1" lang="zh-CN">
                  {c.said}
                </s>
                <span className="mono">{fmtClock(c.start)}</span>
              </div>
            ))}
          {gone.slice(0, 8).map((g, k) => (
            <div key={`g${k}`} className="cutrow">
              <s className="clamp1" lang="zh-CN">
                {g}
              </s>
            </div>
          ))}
          {pauses > 0 && phrases > 0 && <div className="muted">{t('te.card.pauses', { n: pauses })}</div>}
        </div>
        {live && lines.length > 0 && (
          <div className="cutfx">
            {lines.map((l) => (
              <div key={l}>
                <CheckCircle2 className="ico" />
                <span>{l}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {(live || onRestore) && (
        <div className="cft">
          {live ? (
            <button className="btn ghost sm" onClick={onUndo} data-testid="cut-card-undo">
              <Undo2 className="ico" />
              {t('c.undo')}
              <span className="kbd">{keyHint('⌘Z')}</span>
            </button>
          ) : (
            onRestore && (
              <button className="btn ghost sm" onClick={onRestore} data-testid="cut-card-restore">
                {t('ce.restore')}
              </button>
            )
          )}
          <span style={{ flex: 1 }} />
          {cuts.length > 0 && (
            <button className="btn ghost sm" onClick={() => onShow(cuts[0].start)} data-testid="cut-card-show">
              {t('te.card.show')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
