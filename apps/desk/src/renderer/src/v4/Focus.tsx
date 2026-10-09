// 审片 as a focused, full-screen flow (mockups/08-review): queue on the left, the big player with the problem spots
// marked on the scrub bar, what to look at in plain words on the right, and three keys: X send back, Space approve
// and next, E tweak (opens the output editor). Decisions are saved together at the end.
import { useEffect, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { ReviewItem } from '../../../shared/types';
import type { Clip } from '../../../shared/v04';
import { fmtClock, t, type MessageKey } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { go, href } from '../lib/router';
import { platformName } from './Home';
import { issueText } from './Inbox';
import { Empty, Thumb } from './kit';
import { PendingList } from './Project';
import { pendingFor } from '../lib/liveStatus';
import { errText } from './msg';
import { Player, type PlayerApi } from './Player';
import { isTyping, useUi } from './ui';
import { orderPlatforms } from '../../../shared/platforms';

/** "lost-words: lost: '我们' @19.01s" -> {code, at, seconds, quote} */
export function parseReason(s: string): { code: string; at: number | null; seconds: number | null; quote: string | null } {
  const m = /^([a-z][a-z0-9-]*)\s*:\s*(.*)$/i.exec(s.replace(/^\[[^\]]*\]\s*/, ''));
  const rest = m ? m[2] : s;
  const at = /@\s*([0-9.]+)\s*s/.exec(rest);
  const dur = /for\s*([0-9.]+)\s*s/.exec(rest);
  const q = /'([^']{1,80})'/.exec(rest);
  return { code: m ? m[1] : 'qc', at: at ? Number(at[1]) : null, seconds: dur ? Number(dur[1]) : null, quote: q ? q[1] : null };
}

const REASONS: MessageKey[] = ['focus.r.pauses', 'focus.r.opening', 'focus.r.captions', 'focus.r.title'];

export function Focus({ id }: { id: string }) {
  const { client } = useEngine();
  const { data: hist, reload } = useHistory();
  const inbox = useInbox();
  // the badge says "Needs you" for a checkpoint, not a clip review: list those here instead of "Nothing to review"
  const pending = pendingFor(inbox.items, id);
  const ui = useUi();
  const item = hist?.items.find((i) => i.id === id);
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [i, setI] = useState(0);
  const [dec, setDec] = useState<Record<string, { decision: 'approve' | 'reject'; reason: string }>>({});
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const pl = useRef<PlayerApi | null>(null);

  useEffect(() => {
    if (!client || !item) return;
    let alive = true;
    (async () => {
      try {
        let r: ReviewItem[];
        try {
          r = await client.review(id);
        } catch {
          await client.openHistory(item.dir); // a found batch: put it on the desk list first
          r = await client.review(id);
        }
        const flagged = new Set(inbox.items.find((x) => x.project.id === id && x.kind === 'review')?.jobs ?? []);
        // 'waiting': a project's clip parked at its publish check (exported, waiting for her yes)
        const todo = flagged.size ? r.filter((x) => flagged.has(x.id)) : r.filter((x) => x.qc === 'red' || (['done', 'pilot-review', 'waiting'].includes(x.state) && !x.review));
        todo.sort((a, b) => Number(b.qc === 'red') - Number(a.qc === 'red'));
        const c = await client.clips(id).catch(() => null);
        if (!alive) return;
        setItems(todo);
        setClips(c?.clips ?? []);
      } catch (e) {
        if (alive) setErr(errText(e));
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, id, item?.id, inbox.items.length > 0]);

  const cur = items?.[i];
  const clip = useMemo(() => clips.find((c) => c.id === cur?.id), [clips, cur]);
  const issues = useMemo(() => (cur?.reasons ?? []).map(parseReason), [cur]);
  const done = Object.keys(dec).length;
  const exit = () => go({ name: 'project', id });

  const decide = (d: 'approve' | 'reject') => {
    if (!cur) return;
    setDec({ ...dec, [cur.id]: { decision: d, reason: d === 'reject' ? reason : '' } });
    setReason('');
    if (items && i < items.length - 1) setI(i + 1);
    else setI(items?.length ?? 0);
  };
  const save = async () => {
    if (!client) return;
    setSaving(true);
    try {
      await client.applyReview(id, { decisions: dec });
      reload();
      inbox.reload();
      ui.toast(t('focus.allDoneHint', { a: Object.values(dec).filter((x) => x.decision === 'approve').length, r: Object.values(dec).filter((x) => x.decision === 'reject').length }));
      exit();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      if (k === 'escape') exit();
      else if (!cur) return;
      else if (k === ' ') {
        e.preventDefault();
        decide('approve');
      } else if (k === 'x') decide('reject');
      else if (k === 'e') go({ name: 'clip', id, clip: cur.id });
      else if (k === 'arrowdown' || k === 'arrowright') setI((x) => Math.min((items?.length ?? 1) - 1, x + 1));
      else if (k === 'arrowup' || k === 'arrowleft') setI((x) => Math.max(0, x - 1));
      else if (k === 'k') pl.current?.play();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  });

  const n = items?.length ?? 0;
  return (
    <div className="rv" data-testid="focus">
      <div className="top">
        <button className="btn ghost" onClick={exit} data-testid="focus-exit">
          <X className="ico" />
          {t('focus.exit')}
        </button>
        <b className="clamp1">{t('focus.title', { name: item?.name ?? '' })}</b>
        {n > 0 && <span className="muted">{t('focus.pos', { i: Math.min(i + 1, n), n })}</span>}
        <span className="sp" />
        <div className="bar prog">
          <i style={{ width: `${n ? (done / n) * 100 : 0}%`, background: 'var(--accent)' }} />
        </div>
      </div>
      <div className="body">
        <div className="strip">
          {(items ?? []).map((x, k) => (
            <button key={x.id} className={`${k === i ? 'cur' : ''} ${dec[x.id] ? 'done' : ''}`} onClick={() => setI(k)} aria-label={x.title}>
              <Thumb src={clips.find((c) => c.id === x.id)?.cover ?? x.sheet} />
            </button>
          ))}
        </div>
        <div className="stage">
          {err ? (
            <Empty title={err} />
          ) : !items ? (
            <div className="sk" style={{ width: '60%', aspectRatio: '3/4', maxHeight: '100%' }} />
          ) : !n ? (
            pending.length ? (
              <div style={{ maxWidth: 560, width: '100%' }}>
                <PendingList items={pending} />
              </div>
            ) : (
              <Empty title={t('focus.empty')} action={<a className="btn" href={href({ name: 'project', id })}>{t('focus.back')}</a>} />
            )
          ) : !cur ? (
            <Empty
              title={t('focus.allDone')}
              hint={t('focus.allDoneHint', { a: Object.values(dec).filter((x) => x.decision === 'approve').length, r: Object.values(dec).filter((x) => x.decision === 'reject').length })}
              action={
                <button className="btn primary lg" onClick={() => void save()} disabled={saving} data-testid="focus-save">
                  {t('focus.submit')}
                </button>
              }
            />
          ) : (
            <Player
              ref={pl}
              key={cur.id}
              files={clip?.files.length ? clip.files : cur.snippet ? [{ path: cur.snippet, aspect: '3:4' }] : []}
              duration={cur.duration ?? undefined}
              marks={issues.map((x) => x.at).filter((x): x is number => x !== null)}
              keys={false}
              autoPlay
            />
          )}
        </div>
        <div className="info">
          {cur && (
            <>
              <div>
                <span className="muted">{t('focus.meta', { i: i + 1, len: fmtClock(cur.duration ?? clip?.duration ?? 0), platform: [...new Set(orderPlatforms(cur.platforms ?? []).map(platformName))].join(' · ') || '–' })}</span>
                <h1 lang="zh-CN">{cur.title}</h1>
              </div>
              <div className="col">
                <h2>{t('focus.lookAt')}</h2>
                {!issues.length && <span className="muted">{t('focus.nothing')}</span>}
                {issues.map((x, k) => (
                  <button key={k} className="issue" style={{ background: 'none', border: 0, textAlign: 'left', padding: 0, color: 'inherit' }} onClick={() => x.at !== null && pl.current?.seek(Math.max(0, x.at - 1))} data-testid="focus-issue">
                    <i className="dot you" />
                    <span>
                      {x.at !== null && <span className="num">{fmtClock(x.at)} </span>}
                      {issueText(x.code, { s: x.seconds ?? '', t: x.at !== null ? fmtClock(x.at) : '' })}
                      {x.quote && (
                        <span className="muted" lang="zh-CN">
                          {' '}
                          「{x.quote}」
                        </span>
                      )}
                    </span>
                  </button>
                ))}
              </div>
              <div className="col">
                <h2>{t('focus.rejectWhy')}</h2>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  {REASONS.map((r) => (
                    <button key={r} className={`chip ${reason === t(r) ? 'on' : ''}`} onClick={() => setReason(reason === t(r) ? '' : t(r))}>
                      {t(r)}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
      <div className="act">
        <button className="btn danger lg" disabled={!cur} onClick={() => decide('reject')} data-testid="focus-reject">
          {t('focus.reject')}
          <span className="kbd">X</span>
        </button>
        <button className="btn primary lg" disabled={!cur} onClick={() => decide('approve')} data-testid="focus-approve">
          {t('focus.approve')}
          <span className="kbd" style={{ color: 'inherit', borderColor: 'currentColor' }}>
            Space
          </span>
        </button>
        <button className="btn ghost lg" disabled={!cur} onClick={() => cur && go({ name: 'clip', id, clip: cur.id })} data-testid="focus-tweak">
          {t('focus.tweak')}
          <span className="kbd">E</span>
        </button>
      </div>
    </div>
  );
}
