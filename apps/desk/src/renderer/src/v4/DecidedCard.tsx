// What the AI already decided on this clip (ux/fewer-steps), on top of the editor's chat: on autopilot the unsure
// filler cuts and the opening were decided while the clip was made - they are shown as made, each with Undo (a cut
// kept / a kept word cut) or Change (another opening), never as a question to confirm. A change answers that one
// decision in her name and the clip is re-made in the background.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Minus, Play, Sparkles, X } from 'lucide-react';
import type { AutopilotDecision, AutopilotDoc, InboxOption } from '../../../shared/v04';
import { t } from '../i18n';
import { clipDecisions, flipAnswer, locateCut, pickAnswer } from '../lib/decided';
import { useEngine } from '../lib/engine';
import { emsg, errText } from './msg';
import { useUi } from './ui';

const hideKey = (item: string, clip: string) => `ce.decided.${item}/${clip}`;

export function DecidedCard({ item, clip, words, seek }: { item: string; clip: string; words: { w: string; t: number; te: number }[]; seek: (t: number) => void }) {
  const { client, subscribe } = useEngine();
  const ui = useUi();
  const [doc, setDoc] = useState<AutopilotDoc | null>(null);
  const [n, setN] = useState(0);
  // what she changed here (the engine lists it as hers from then on): shown as changed while the clip is re-made
  const [mine, setMine] = useState<Record<string, AutopilotDecision>>({});
  const [sending, setSending] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [hidden, setHidden] = useState(() => localStorage.getItem(hideKey(item, clip)));
  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .autopilot(item)
      .then((d) => alive && setDoc(d))
      .catch(() => alive && setDoc(null));
    return () => {
      alive = false;
    };
  }, [client, item, n]);
  useEffect(() => subscribe((e) => void (e.type === 'inbox' || e.type === 'batches' ? setN((x) => x + 1) : undefined)), [subscribe]);
  useEffect(() => {
    setMine({});
    setOpen(null);
    setHidden(localStorage.getItem(hideKey(item, clip)));
  }, [item, clip]);
  const list = useMemo(() => {
    const own = clipDecisions(doc?.decisions ?? [], clip);
    const keys = new Set(own.map((d) => d.checkpoint));
    return [...own.map((d) => mine[d.checkpoint] ?? d), ...Object.values(mine).filter((d) => !keys.has(d.checkpoint))];
  }, [doc, clip, mine]);
  const sig = list.map((d) => `${d.checkpoint}:${d.at ?? ''}`).join('|');
  const change = useCallback(
    async (d: AutopilotDecision, answer: { approve: string[]; keep: string[] }, next: InboxOption[]) => {
      if (!client) return;
      if (doc?.running) {
        ui.toast(t('hub.changeBusy'));
        return;
      }
      setSending(d.checkpoint);
      try {
        await client.autopilotChange(item, d.checkpoint, d.item, answer);
        setMine((m) => ({ ...m, [d.checkpoint]: { ...d, options: next, by: undefined } }));
        setOpen(null);
      } catch (e) {
        ui.toast(errText(e), { error: true });
      } finally {
        setSending(null);
      }
    },
    [client, doc, item, ui],
  );
  if (!list.length || hidden === sig) return null;
  const calls = list.reduce((s, d) => s + (d.kind === 'hook-pick' ? 1 : d.options?.length ?? 0), 0);
  const remaking = Object.keys(mine).length > 0;
  return (
    <div className="ux-pin decided" data-testid="decided-card">
      <div className="ux-pin-hd">
        <Sparkles className="ico" />
        <b>{t('fs.dec.title', { n: calls })}</b>
        <span className="sp" />
        <button
          className="btn ghost icon sm"
          onClick={() => {
            localStorage.setItem(hideKey(item, clip), sig);
            setHidden(sig);
          }}
          aria-label={t('fs.dec.hide')}
          data-tip={t('fs.dec.hide')}
          data-testid="decided-hide"
        >
          <X className="ico" />
        </button>
      </div>
      <div className="ux-pin-t muted dec-lead">{remaking ? t('fs.dec.remaking') : t('fs.dec.lead')}</div>
      <div className="ux-pin-opts">
        {list.map((d) => {
          const opts = d.options ?? [];
          const why = d.by === 'ai' && d.reason ? d.reason : null;
          const hers = !!mine[d.checkpoint];
          if (d.kind === 'hook-pick') {
            const cur = opts.find((o) => o.checked) ?? null;
            return (
              <div key={d.checkpoint} className="dec-row" data-testid="decided-row" data-kind="opening">
                <div className="dec-main">
                  <span className="dec-ic">{hers ? <Check className="ico" /> : <Sparkles className="ico" />}</span>
                  <div className="dec-tx">
                    <div className="clamp1" lang="zh-CN">{cur ? t('fs.dec.opening', { text: cur.text }) : t('fs.dec.noOpeningShort')}</div>
                    <div className="muted small clamp1">{why ?? (cur ? null : t('fs.dec.noOpeningWhy'))}</div>
                  </div>
                  <button className="btn ghost sm" disabled={sending != null} onClick={() => setOpen(open === d.checkpoint ? null : d.checkpoint)} aria-expanded={open === d.checkpoint} data-testid="decided-change">
                    {t('hub.change')}
                  </button>
                </div>
                {open === d.checkpoint && (
                  <div className="dec-picks" role="radiogroup">
                    {[null, ...opts].map((o) => {
                      const on = o ? !!o.checked : !cur;
                      return (
                        <button key={o?.id ?? 'none'} className={`dec-pick ${on ? 'on' : ''}`} disabled={on || sending != null} onClick={() => void change(d, pickAnswer(opts, o?.id ?? null), opts.map((x) => ({ ...x, checked: x.id === o?.id })))} data-testid="decided-pick" lang="zh-CN">
                          {o ? `“${o.text}”` : t('fs.dec.noOpening')}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          }
          return opts.map((o) => {
            const at = locateCut(words, o.text, o.ctx);
            return (
              <div key={`${d.checkpoint}:${o.id}`} className={`dec-row ${o.checked ? '' : 'kept'}`} data-testid="decided-row" data-kind="filler" data-cut={o.checked ? '1' : '0'}>
                <div className="dec-main">
                  <span className="dec-ic">{o.checked ? <Check className="ico" /> : <Minus className="ico" />}</span>
                  <div className="dec-tx">
                    <div className="clamp1" lang="zh-CN">{o.checked ? t('fs.dec.cut', { w: o.text }) : t('fs.dec.kept', { w: o.text })}</div>
                    {o.quote ? (
                      <div className="muted small clamp1" lang="zh-CN">
                        「{o.quote}」
                      </div>
                    ) : why ? (
                      <div className="muted small clamp1">{why}</div>
                    ) : null}
                  </div>
                  {at && (
                    <button className="btn ghost icon sm" onClick={() => seek(Math.max(0, at.t - 1.5))} aria-label={t('fs.dec.play')} data-tip={t('fs.dec.play')} data-testid="decided-play">
                      <Play className="ico" />
                    </button>
                  )}
                  <button className="btn ghost sm" disabled={sending != null} onClick={() => void change(d, flipAnswer(opts, o.id), opts.map((x) => (x.id === o.id ? { ...x, checked: !x.checked } : x)))} data-testid="decided-flip">
                    {o.checked ? t('fs.dec.keep') : t('fs.dec.cutIt')}
                  </button>
                </div>
                {emsg(o.detail ?? null) ? <div className="muted small">{emsg(o.detail ?? null)}</div> : null}
              </div>
            );
          });
        })}
      </div>
    </div>
  );
}
