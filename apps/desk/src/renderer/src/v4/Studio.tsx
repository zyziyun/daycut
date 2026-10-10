// The Studio (2026-10 review steps 6-8, layout A): every video in one list on the left - needs you / in progress /
// ready to post / scheduled, each row with its dot, where it is, time left and progress - and the selected video's
// one page on the right (the clip page: player, cover, captions, versions, the question, the transcript, the post,
// one AI bar). A request still being planned or a project with no clips yet opens its own detail; a question about a
// whole project opens the question itself. ＋ New video (⌘N) starts the next one from here; ↑ ↓ and ⌘1–9 switch.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Play, Plus, Sparkles } from 'lucide-react';
import type { CalendarPost, Clip, InboxItem } from '../../../shared/v04';
import { fmtClock, fmtDate, fmtMinutes, t, type MessageKey } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { inboxTitle } from '../lib/inboxView';
import { keyHint } from '../lib/keys';
import { startTriage } from '../lib/nav';
import { href, routeQuery } from '../lib/router';
import { STUDIO_FILTERS, grouped, needsYou, studioRows, timeLeft, type StudioFilter, type StudioGroup, type StudioRow } from '../lib/studio';
import { platformName } from './Home';
import { ItemPane, useResolve } from './Inbox';
import { Empty, Thumb } from './kit';
import { OutputEditor } from './OutputEditor';
import { ProjectDetail, RequestDetail, stateLine } from './Hub';
import { itemPipeline } from '../lib/pipeline';
import { Composer } from './Composer';
import { isTyping } from './ui';
import './studio.css';

const FKEY = 'studio.filter';

/** Every recent project's clips, loaded once per project version (a run's new clip shows as soon as it exists). */
function useClipsOf(ids: { id: string; v: string }[]) {
  const { client, subscribe } = useEngine();
  const [clips, setClips] = useState<Record<string, Clip[] | undefined>>({});
  const seen = useRef<Record<string, string>>({});
  const [n, setN] = useState(0);
  useEffect(() => subscribe((e) => (e.type === 'output-edit' || e.type === 'calendar' ? ((seen.current = {}), setN((x) => x + 1)) : undefined)), [subscribe]);
  const key = ids.map((x) => `${x.id}:${x.v}`).join('|');
  useEffect(() => {
    if (!client) return;
    let alive = true;
    for (const { id, v } of ids) {
      if (seen.current[id] === v) continue;
      seen.current[id] = v;
      client
        .clips(id)
        .then((d) => alive && setClips((c) => ({ ...c, [id]: d.clips })))
        .catch(() => alive && setClips((c) => ({ ...c, [id]: [] })));
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, key, n]);
  return clips;
}

/** 「连着看」: clips waiting for her review play one after another (space approves, X sends back - Focus); other
 * questions come one after another on their clips' pages. */
function inRow(items: InboxItem[]) {
  const review = items.find((x) => (x.kind === 'review' || x.kind === 'publish') && x.project.id);
  if (review?.project.id) location.hash = href({ name: 'focus', id: review.project.id });
  else startTriage(items);
}

function rowHref(r: StudioRow): string {
  if (r.kind === 'clip') return href({ name: 'studio', id: r.item!, clip: r.clip! });
  if (r.kind === 'project') return href({ name: 'studio', id: r.item! }) + (r.ask ? `?ask=${encodeURIComponent(r.ask.key)}` : '');
  return `${href({ name: 'studio' })}?sel=${r.r!.id}`;
}

export function Studio({ id, clip }: { id?: string; clip?: string }) {
  const { data: hist, requests = [] } = useHistory();
  const inbox = useInbox();
  const { subscribe } = useEngine();
  const { data: cal, reload: reloadCal } = useLoad((c) => c.calendar(undefined, { queue: false }).catch(() => c.calendar()), []);
  useEffect(() => subscribe((e) => void (e.type === 'calendar' && reloadCal())), [subscribe]); // eslint-disable-line react-hooks/exhaustive-deps
  const posts = useMemo(() => cal?.posts ?? [], [cal]);
  const items = useMemo(() => hist?.items ?? [], [hist]);
  const now = Date.now() / 1000;
  const recent = useMemo(() => items.filter((i) => now - (i.updated ?? i.created ?? 0) < 14 * 86400 || i.live?.state === 'running' || i.live?.state === 'waiting'), [items]); // eslint-disable-line react-hooks/exhaustive-deps
  const clips = useClipsOf(recent.map((i) => ({ id: i.id, v: `${i.updated ?? 0}:${i.status}:${i.live?.state ?? ''}` })));
  const rows = useMemo(() => studioRows(recent, requests, clips, posts, inbox.items), [recent, requests, clips, posts, inbox.items]);
  const groups = useMemo(() => grouped(rows), [rows]);
  const q = routeQuery();
  const [filter, setFilterS] = useState<StudioFilter>(() => (STUDIO_FILTERS.includes(q.f as StudioFilter) ? (q.f as StudioFilter) : ((sessionStorage.getItem(FKEY) as StudioFilter | null) ?? 'all')));
  useEffect(() => {
    const on = () => {
      // the Inbox is the Studio's Needs you filter now (an old link, a notification, ⌘K)
      if (/^#\/inbox\b/.test(location.hash)) {
        const rest = location.hash.split('?')[1];
        history.replaceState(null, '', `#/studio?f=you${rest ? `&${rest}` : ''}`);
      }
      const f = routeQuery().f as StudioFilter | undefined;
      if (f && STUDIO_FILTERS.includes(f)) setFilterS(f);
    };
    on();
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const setFilter = (f: StudioFilter) => {
    setFilterS(f);
    sessionStorage.setItem(FKEY, f);
  };
  const order: StudioGroup[] = filter === 'all' ? ['you', 'run', 'ready', 'scheduled'] : [filter];
  const list = order.flatMap((g) => groups[g]);
  const selKey = clip && id ? `${id}/${clip}` : id ? `p:${id}` : q.sel ? (rows.some((r) => r.key === `r:${q.sel}`) ? `r:${q.sel}` : rows.some((r) => r.item === q.sel) ? `p:${q.sel}` : null) : null;
  const cur = (selKey ? rows.find((r) => r.key === selKey) : null) ?? null;
  // nothing chosen: the first video of the list (what needs her first)
  const first = list[0] ?? null;
  useEffect(() => {
    if (!selKey && first && hist) history.replaceState(null, '', rowHref(first));
    if (!selKey && first && hist) window.dispatchEvent(new HashChangeEvent('hashchange'));
  }, [selKey, first?.key, !!hist]); // eslint-disable-line react-hooks/exhaustive-deps
  const [composer, setComposer] = useState(false);

  // ↑ ↓ the next / previous video, ⌘1–9 the n-th one in the list
  const go = useCallback((r: StudioRow | undefined) => r && (location.hash = rowHref(r)), []);
  const keys = useRef<(e: KeyboardEvent) => void>(() => undefined);
  keys.current = (e: KeyboardEvent) => {
    if (document.querySelector('.scrim, .ctx, .palette')) return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && !e.shiftKey && !e.altKey && /^[1-9]$/.test(e.key)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      go(list[Number(e.key) - 1]);
      return;
    }
    if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'n') {
      e.preventDefault();
      setComposer(true);
      return;
    }
    if (isTyping(e.target) || mod || e.altKey || e.shiftKey) return;
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if ((e.target as HTMLElement | null)?.closest?.('[data-testid=transcript-body], .tl, [role=slider]')) return;
    const k = cur ? list.findIndex((r) => r.key === cur.key) : -1;
    const next = list[Math.max(0, Math.min(list.length - 1, k + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next && next.key !== cur?.key) {
      e.preventDefault();
      go(next);
      document.querySelector(`[data-row="${CSS.escape(next.key)}"]`)?.scrollIntoView({ block: 'nearest' });
    }
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => keys.current(e);
    window.addEventListener('keydown', on, true);
    return () => window.removeEventListener('keydown', on, true);
  }, []);

  const count = (g: StudioFilter) => (g === 'all' ? rows.length : groups[g].length);
  return (
    <div className="studio" data-testid="studio">
      <aside className="st-list" aria-label={t('st.list')}>
        <button className={`st-new ${composer ? 'on' : ''}`} onClick={() => setComposer((v) => !v)} aria-expanded={composer} data-testid="studio-new">
          <Plus className="ico" />
          <span className="tx">{composer ? t('st.new') : t('st.newHint')}</span>
          <span className="kbd">{keyHint('⌘N')}</span>
        </button>
        {composer && (
          <div className="st-composer" data-testid="studio-composer">
            <Composer compact autoFocus onSent={(rid) => (setComposer(false), (location.hash = `${href({ name: 'studio' })}?sel=${rid}`))} onClose={() => setComposer(false)} />
          </div>
        )}
        <div className="st-filters" role="tablist" aria-label={t('st.filters')}>
          {STUDIO_FILTERS.map((f) => (
            <button key={f} role="tab" aria-selected={filter === f} className={`st-f ${filter === f ? 'on' : ''} ${f === 'you' && count('you') ? 'you' : ''}`} onClick={() => setFilter(f)} data-testid={`studio-f-${f}`}>
              {t(`st.f.${f}` as MessageKey)}
              {count(f) > 0 && <b className="n">{count(f)}</b>}
            </button>
          ))}
        </div>
        <div className="st-rows" data-testid="studio-rows">
          {!rows.length && hist && <p className="st-empty muted">{t('st.emptyAll')}</p>}
          {rows.length > 0 && !list.length && <p className="st-empty muted">{t('st.empty')}</p>}
          {order.map((g) => {
            const l = groups[g];
            if (!l.length) return null;
            const left = g === 'run' ? timeLeft(l) : null;
            return (
              <section key={g} className="st-group" data-testid={`studio-group-${g}`}>
                <h3>
                  <span>
                    {t(`st.f.${g}` as MessageKey)} · {l.length}
                  </span>
                  <span className="sp" />
                  {g === 'you' && inbox.items.length > 0 && (
                    <button className="st-inrow" onClick={() => inRow(inbox.items)} data-testid="studio-in-row">
                      {t('st.inRow')} <Play className="ico" />
                    </button>
                  )}
                  {left ? <span className="muted">{t('st.left', { t: fmtMinutes(Math.max(1, Math.round(left / 60))) })}</span> : null}
                </h3>
                {l.map((r) => (
                  <StudioListRow key={r.key} r={r} on={cur?.key === r.key} n={list.indexOf(r) + 1} />
                ))}
              </section>
            );
          })}
        </div>
        <footer className="st-foot muted">
          <span>{t('st.jump', { key: keyHint('⌘K') })}</span>
          <span className="sp" />
          {needsYou(rows) > 0 && (
            <span className="st-you" data-testid="studio-you-count">
              <i className="dot you" /> {needsYou(rows)}
            </span>
          )}
        </footer>
      </aside>
      <section className="st-page" data-testid="studio-page">
        {cur ? <Page key={cur.key} r={cur} posts={posts} /> : <Empty title={rows.length ? t('st.pick') : t('st.emptyAll')} />}
      </section>
    </div>
  );
}

function lineOf(r: StudioRow): string {
  // the control room's words (Hub.stateLine): one vocabulary for where a video is
  if (r.kind === 'request') return stateLine(r.p, undefined, r.r);
  if (r.ask) return inboxTitle(r.ask);
  if (r.group === 'you') return r.tone === 'error' ? t('hub.s.failed') : t('hub.s.you');
  if (r.group === 'run') {
    if (r.tone === 'off' && !r.i?.queued) return t('st.r.queued');
    return stateLine(r.p, r.i);
  }
  if (r.group === 'scheduled' && r.post) {
    const when = fmtDate(r.post.at, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
    return r.posted ? t('st.r.posted', { when }) : `${when} · ${platformName(r.post.platform)}`;
  }
  return t('st.r.made', { d: r.duration ? fmtClock(r.duration) : '—' });
}

function StudioListRow({ r, on, n }: { r: StudioRow; on: boolean; n: number }) {
  const pct = r.p.progress == null ? null : Math.round(r.p.progress * 100);
  const where = [r.project, r.pos ? `${r.pos[0]}/${r.pos[1]}` : null].filter(Boolean).join(' · ');
  return (
    <a className={`st-row ${on ? 'on' : ''}`} href={rowHref(r)} aria-current={on ? 'true' : undefined} data-testid="studio-row" data-row={r.key} data-group={r.group} data-kind={r.kind} title={n > 0 && n < 10 ? `${r.title} · ${keyHint(`⌘${n}`)}` : r.title}>
      <Thumb src={r.thumb} className="st-th" />
      <span className="tx">
        <b className="clamp1" lang="zh-CN">
          {r.title || t('home.planningRow')}
        </b>
        <span className="s clamp1">
          <i className={`dot ${r.tone}`} />
          {lineOf(r)}
          {r.kind === 'project' && r.i?.autopilot ? <Sparkles className="ico ap" aria-label={t('ap.auto')} /> : null}
        </span>
        {where && <span className="w clamp1 faint">{where}</span>}
        {r.group === 'run' && r.tone === 'run' && (
          <span className={`bar ${pct == null ? 'indet' : ''}`}>
            <i style={{ width: `${Math.max(4, pct ?? 30)}%` }} />
          </span>
        )}
      </span>
    </a>
  );
}

/** The right side: the video's page, or what a request / a project without clips / a project's question needs. */
function Page({ r, posts }: { r: StudioRow; posts: CalendarPost[] }) {
  const resolve = useResolve();
  // a made clip: its page; one still being made: what it waits for (its question), else where its project is
  if (r.kind === 'clip' && r.video) return <OutputEditor id={r.item!} clip={r.clip!} layout="studio" ask={r.ask} place={{ project: r.project, pos: r.pos }} />;
  if (r.kind === 'request') return <div className="st-detail"><RequestDetail r={r.r!} onApplied={() => undefined} /></div>;
  if (r.ask)
    return (
      <div className="st-detail st-ask" data-testid="studio-project-ask">
        <p className="muted small">{r.kind === 'clip' ? [r.project, r.title].filter(Boolean).join(' · ') : `${t('st.projectAsk')} · ${r.title}`}</p>
        <ItemPane key={r.ask.key} x={r.ask} onDone={(a) => void resolve(r.ask!, a)} onSkip={() => undefined} />
      </div>
    );
  return (
    <div className="st-detail">
      <ProjectDetail i={r.i!} p={itemPipeline(r.i!, posts)} posts={posts} />
    </div>
  );
}
