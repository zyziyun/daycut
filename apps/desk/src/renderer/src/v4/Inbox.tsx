// 收件箱: every decision waiting for the creator, across projects, grouped (选择 / 审片 / 花费), with the action right
// on the card and bulk "accept suggestions" for selected cards. Only the top card's button is the primary.
import { useMemo, useState } from 'react';
import { CheckSquare, Square } from 'lucide-react';
import type { InboxGroup, InboxItem } from '../../../shared/v04';
import { fmtList, has, t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { useInbox } from '../lib/inbox';
import { go, href } from '../lib/router';
import { Empty, Seg, Sk, Thumb } from './kit';
import { FailureActions, failureReason } from './Failure';
import { useUi } from './ui';

/** The card's title from the engine's code + params (UI language); the engine's own text otherwise. */
export function inboxTitle(x: InboxItem): string {
  if (x.code && has(x.code)) return tk(x.code, x.params);
  if (x.kind && has(`checkpoint.${x.kind}`)) return tk(`checkpoint.${x.kind}`);
  return x.text ?? t('inbox.checkpoint');
}

export function issueText(code: string, vars: Record<string, string | number> = {}): string {
  const k = `issue.${code}`;
  return has(k) ? tk(k, vars) : has('issue.qc') ? t('issue.qc') : code;
}

export function InboxScreen() {
  const { items, loading, reload } = useInbox();
  const { client } = useEngine();
  const ui = useUi();
  const [f, setF] = useState<'all' | InboxGroup>('all');
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Record<string, Set<string>>>({});
  const shown = useMemo(() => items.filter((x) => f === 'all' || x.group === f), [items, f]);
  const count = (g: InboxGroup) => items.filter((x) => x.group === g).length;

  const answer = async (keys: string[], answer?: Record<string, unknown>) => {
    if (!client || !keys.length) return;
    try {
      await client.answerInbox(keys, answer);
      setSel(new Set());
      reload();
      ui.toast(t('inbox.done', { n: keys.length }), {
        undo: async () => {
          await client.undoInbox(keys);
          reload();
        },
      });
    } catch (e) {
      ui.toast((e as Error).message, { error: true });
    }
  };

  return (
    <div className="scroll" data-testid="inbox">
      <div className="pg">
        <div className="ph">
          <div>
            <h1>{t('inbox.title')}</h1>
            <p>{t('inbox.subtitle')}</p>
          </div>
          <span className="sp" />
          <Seg
            value={f}
            onChange={setF}
            testId="inbox-filter"
            options={[
              { v: 'all', label: t('inbox.f.all', { n: items.length }) },
              ...(count('failed') ? [{ v: 'failed' as const, label: `${t('inbox.f.failed')} ${count('failed')}` }] : []),
              { v: 'choose', label: `${t('inbox.f.choose')} ${count('choose') || ''}`.trim() },
              { v: 'review', label: `${t('inbox.f.review')} ${count('review') || ''}`.trim() },
              { v: 'spend', label: `${t('inbox.f.spend')} ${count('spend') || ''}`.trim() },
            ]}
          />
        </div>
        {loading ? (
          [0, 1, 2].map((i) => <Sk key={i} h={140} r={12} />)
        ) : !shown.length ? (
          <Empty title={t('inbox.empty')} hint={t('inbox.emptyHint')} />
        ) : (
          shown.map((x, idx) => {
            const on = sel.has(x.key);
            const opts = x.options ?? [];
            const chosen = picked[x.key] ?? new Set(opts.filter((o) => o.checked !== false).map((o) => o.id));
            const primary = idx === 0 ? 'btn primary' : 'btn';
            return (
              <div key={x.key} className={`card inb${x.failure ? ' failed' : ''}`} data-testid="inbox-item" data-kind={x.kind}>
                <button
                  className="btn ghost icon sm"
                  aria-pressed={on}
                  aria-label={t('c.select')}
                  onClick={() => {
                    const n = new Set(sel);
                    if (on) n.delete(x.key);
                    else n.add(x.key);
                    setSel(n);
                  }}
                  data-testid="inbox-select"
                >
                  {on ? <CheckSquare className="ico" /> : <Square className="ico" />}
                </button>
                <a href={x.project.id ? href({ name: 'project', id: x.project.id }) : undefined}>
                  <Thumb src={x.project.thumb} />
                </a>
                <div style={{ minWidth: 0 }}>
                  <div className="muted clamp1">{x.project.name}</div>
                  <div className="what">{inboxTitle(x)}</div>
                  {x.kind === 'review' && x.params.total ? (
                    <div className="muted">
                      {t('inbox.passed', { passed: x.params.passed, total: x.params.total })}{' '}
                      {(x.reasons ?? []).length > 0 &&
                        t('inbox.why', { reasons: fmtList((x.reasons ?? []).map((r) => `${issueText(r.code)} ×${r.n}`)) })}
                    </div>
                  ) : null}
                  {x.kind === 'checkpoint' && x.text && <div className="muted">{x.text}</div>}
                  {x.failure && <div className="muted" data-testid="inbox-failed-reason">{failureReason(x.failure)}</div>}
                  {opts.length > 0 && (
                    <div className="col" style={{ gap: 0, marginTop: 8 }}>
                      {opts.map((o) => (
                        <label key={o.id} className="check">
                          <input
                            type="checkbox"
                            checked={chosen.has(o.id)}
                            onChange={(e) => {
                              const n = new Set(chosen);
                              if (e.target.checked) n.add(o.id);
                              else n.delete(o.id);
                              setPicked({ ...picked, [x.key]: n });
                            }}
                          />
                          <span lang="zh-CN">
                            {o.clip ? <b style={{ fontWeight: 500 }}>{o.clip} </b> : null}
                            {o.text}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
                <div className="acts">
                  {x.failure && x.project.id ? (
                    <FailureActions item={x.project.id} failure={x.failure} primary={idx === 0} />
                  ) : x.kind === 'confirm' || opts.length ? (
                    <button className={primary} onClick={() => void answer([x.key], { approve: [...chosen], keep: opts.filter((o) => !chosen.has(o.id)).map((o) => o.id) })} data-testid="inbox-confirm">
                      {t('inbox.confirmN', { n: chosen.size })}
                    </button>
                  ) : x.kind === 'review' ? (
                    <button className={primary} onClick={() => x.project.id && go({ name: 'focus', id: x.project.id })} data-testid="inbox-review">
                      {t('inbox.startReview', { m: t('inbox.minutes', { n: x.minutes ?? 1 }) })}
                    </button>
                  ) : (
                    <button className={primary} onClick={() => void answer([x.key])}>
                      {t('inbox.continue')}
                    </button>
                  )}
                  {x.project.id && (
                    <a className="btn ghost" href={href({ name: 'project', id: x.project.id })}>
                      {t('inbox.openProject')}
                    </a>
                  )}
                </div>
              </div>
            );
          })
        )}
        {sel.size > 0 && (
          <div className="bulk" data-testid="inbox-bulk">
            <b style={{ fontWeight: 500 }}>{t('c.selected', { n: sel.size })}</b>
            <button className="btn ghost" onClick={() => setSel(new Set(shown.map((x) => x.key)))}>
              {t('c.selectAll')}
            </button>
            <span className="sp" />
            <button className="btn ghost" onClick={() => setSel(new Set())}>
              {t('c.clear')}
            </button>
            <button className="btn primary" onClick={() => void answer([...sel])} data-testid="inbox-bulk-accept">
              {t('inbox.acceptAll')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
