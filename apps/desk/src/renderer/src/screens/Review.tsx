// Review grid: contact sheets + 3 s preview loops. space = approve, x = reject with a reason, u = undo,
// arrows / j k = move. Decisions stay local until "submit", then go to the engine (review --apply).
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Decision, ReviewItem } from '../../../shared/types';
import { Empty, ErrorBox, Media, PromptModal, QcLight } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { secs } from '../lib/format';
import { useReviewTiming } from '../lib/reviewTiming';
import { go } from '../lib/router';

type Filter = 'all' | 'red' | 'sample' | 'open';

export function Review({ batch }: { batch: string }) {
  const { client } = useEngine();
  const { data, error, reload } = useLoad((c) => c.review(batch), [batch]);
  const [filter, setFilter] = useState<Filter>('open');
  const [focus, setFocus] = useState(0);
  const [dec, setDec] = useState<Record<string, Decision>>({});
  const [replies, setReplies] = useState<Record<string, string>>({});
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const visible = useMemo(
    () =>
      (data ?? []).filter(
        (it) =>
          filter === 'all' ||
          (filter === 'red' && it.qc === 'red') ||
          (filter === 'sample' && it.sample) ||
          (filter === 'open' && !dec[it.id] && it.state === 'done'),
      ),
    [data, filter, dec],
  );
  const cur = visible[Math.min(focus, Math.max(0, visible.length - 1))];
  const timing = useReviewTiming(batch, cur?.id);

  const decide = useCallback(
    (kind: 'approve' | 'undo', id = cur?.id) => {
      if (!id) return;
      setDec((d) => {
        const n = { ...d };
        if (kind === 'undo') delete n[id];
        else n[id] = { decision: 'approve' };
        return n;
      });
      if (kind !== 'undo' && filter !== 'open') setFocus((f) => Math.min(f + 1, visible.length - 1));
    },
    [cur, filter, visible.length],
  );

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (rejecting || (e.target as HTMLElement).tagName === 'INPUT') return;
      if (e.key === ' ') {
        e.preventDefault();
        decide('approve');
      } else if (e.key === 'x' && cur) setRejecting(cur.id);
      else if (e.key === 'u') decide('undo');
      else if (e.key === 'ArrowRight' || e.key === 'j') setFocus((f) => Math.min(f + 1, visible.length - 1));
      else if (e.key === 'ArrowLeft' || e.key === 'k') setFocus((f) => Math.max(f - 1, 0));
      else if (e.key === 'Enter' && cur) go({ name: 'job', batch, job: cur.id });
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [decide, cur, rejecting, visible.length, batch]);

  const nDec = Object.keys(dec).length;
  const nRep = Object.keys(replies).length;

  async function submit() {
    if (!client) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await client.applyReview(batch, { decisions: dec, cleanup: replies });
      setMsg(t('review.applied', { a: r.approved.length, r: r.rejected.length, c: r.replied.length }) + (r.skipped.length ? ` · ${r.skipped.map((s) => s.join(': ')).join('; ')}` : ''));
      setDec({});
      setReplies({});
      reload();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const pending = (data ?? []).filter((it) => it.confirm.length && it.state === 'done');

  return (
    <>
      <div className="topbar">
        <h1>{t('review.title')}</h1>
        <div className="tabs">
          {(['open', 'all', 'red', 'sample'] as Filter[]).map((f) => (
            <button key={f} className={`tab ${filter === f ? 'on' : ''}`} onClick={() => (setFilter(f), setFocus(0))}>
              {t(`review.f.${f}`)}
            </button>
          ))}
        </div>
        <div className="sp" />
        {cur && (
          <span className={`badge ${timing.idle ? '' : 'accent'}`} title={t('timing.hint')} data-testid="review-timer">
            {cur.id} · {timing.seconds}s
          </span>
        )}
        <span className="muted small">
          <kbd>space</kbd> {t('review.k.approve')} <kbd>x</kbd> {t('review.k.reject')} <kbd>u</kbd> {t('review.k.undo')} <kbd>←</kbd>
          <kbd>→</kbd> {t('review.k.move')} <kbd>↵</kbd> {t('review.k.open')}
        </span>
        <button className="btn primary" disabled={busy || (!nDec && !nRep)} onClick={submit}>
          {t('review.submit', { n: nDec + nRep })}
        </button>
      </div>
      <div className="page col" style={{ gap: 12 }}>
        <ErrorBox error={error} />
        {msg && <div className="notice accent">{msg}</div>}
        {data && visible.length === 0 && <Empty>{t('review.empty')}</Empty>}
        <div className="grid">
          {visible.map((it, i) => (
            <ReviewCard
              key={it.id}
              it={it}
              focus={it === cur}
              d={dec[it.id]}
              onClick={() => setFocus(i)}
              onOpen={() => go({ name: 'job', batch, job: it.id })}
            />
          ))}
        </div>
        {pending.length > 0 && (
          <div className="card col">
            <b>{t('review.needed', { j: pending.length, e: pending.reduce((a, it) => a + it.confirm.length, 0) })}</b>
            <span className="muted small">{t('review.neededHint')}</span>
            {pending.map((it) => (
              <div key={it.id} className="col" style={{ gap: 4 }}>
                <div className="row">
                  <span className="mono">{it.id}</span>
                  <span className="muted">{it.title}</span>
                  <a className="small" href={`#/b/${batch}/job/${encodeURIComponent(it.id)}`}>
                    {t('review.openTranscript')}
                  </a>
                </div>
                <table className="t small">
                  <tbody>
                    {it.confirm.map((e) => (
                      <tr key={e.id}>
                        <td className="mono">{e.id}</td>
                        <td>{e.kind}</td>
                        <td className="sel">
                          …{e.before.slice(-14)} <b>[{e.text}]</b> {e.after.slice(0, 14)}…
                        </td>
                        <td className="muted">{e.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <input
                  className="input"
                  placeholder="确认 3,5 / 保留 7"
                  value={replies[it.id] ?? it.reply}
                  onChange={(e) =>
                    setReplies((r) => {
                      const n = { ...r };
                      if (e.target.value.trim() && e.target.value !== it.reply) n[it.id] = e.target.value.trim();
                      else delete n[it.id];
                      return n;
                    })
                  }
                />
              </div>
            ))}
          </div>
        )}
      </div>
      {rejecting && (
        <PromptModal
          title={t('review.rejectTitle', { id: rejecting })}
          placeholder={t('review.reasonPh')}
          okLabel={t('review.k.reject')}
          onCancel={() => setRejecting(null)}
          onOk={(reason) => {
            const id = rejecting;
            setRejecting(null);
            setDec((d) => ({ ...d, [id]: { decision: 'reject', reason: reason || 'rejected' } }));
          }}
        />
      )}
    </>
  );
}

function ReviewCard({ it, focus, d, onClick, onOpen }: { it: ReviewItem; focus: boolean; d?: Decision; onClick: () => void; onOpen: () => void }) {
  const [hover, setHover] = useState(false);
  const state = d?.decision ?? (it.review === 'approved' ? 'approve' : it.review === 'rejected' ? 'reject' : '');
  return (
    <div className={`rcard ${focus ? 'focus' : ''} ${state}`} onClick={onClick} onDoubleClick={onOpen} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <div className="row">
        <QcLight qc={it.qc} />
        <b className="mono">{it.id}</b>
        {it.sample && <span className="badge">{t('board.sampleBadge')}</span>}
        {it.pilot && <span className="badge accent">{t('board.pilotBadge')}</span>}
        {it.confirm.length > 0 && <span className="badge">{t('review.toConfirm', { n: it.confirm.length })}</span>}
      </div>
      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.title}</div>
      <div className="muted small">
        {it.platforms.join(', ')} · {secs(it.duration)}
      </div>
      {hover && it.snippet ? (
        <video className="thumb" src={window.desk.mediaUrl(it.snippet)} autoPlay muted loop playsInline />
      ) : (
        <Media path={it.sheet} kind="img" />
      )}
      {it.reasons.map((r) => (
        <div key={r} className="small err">
          {r}
        </div>
      ))}
      {it.warnings.slice(0, 2).map((r) => (
        <div key={r} className="small warnc">
          {r}
        </div>
      ))}
      {state && (
        <div className={`small ${state === 'approve' ? 'okc' : 'err'}`}>
          {state === 'approve' ? t('review.approved') : `${t('review.rejected')}: ${d?.reason ?? it.review_reason ?? ''}`}
          {d && <span className="muted"> · {t('review.unsaved')}</span>}
        </div>
      )}
    </div>
  );
}
