// The control room (ux/autopilot A1): All projects as a live list grouped by what each one needs (needs you /
// running / ready / scheduled & out / earlier) and the selected one on the right - where it is in the pipeline, what
// the AI decided (each one can be taken back), its clips (each opens the player + editor) and its publishing. A
// request from Home shows here the moment it is sent: planning, a plan waiting for her Start (Ask me first), a failure.
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, CalendarPlus, Check, Sparkles, Trash2 } from 'lucide-react';
import type { HistoryItem } from '../../../shared/v02';
import type { AutopilotDecision, AutopilotDoc, CalendarPost, Clip, OpenRequest } from '../../../shared/v04';
import { fmtAgo, fmtMinutes, getLang, has, t, tk, type MessageKey } from '../i18n';
import { providerName } from '../../../shared/aiRoutes';
import { clipStatus } from '../lib/status';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { clipHref, inboxHref, projectHref } from '../lib/nav';
import { decisionWords, hubGroups, postsOf, requestPipeline, STEPS, stepState, type GroupId, type HubRow, type Pipeline } from '../lib/pipeline';
import { href, routeQuery } from '../lib/router';
import { useIntakeJob } from '../lib/useIntakeJob';
import { studioEnabled } from '../lib/studioFlag';
import { failureReason, FailureActions } from './Failure';
import { Empty, Thumb } from './kit';
import { errText } from './msg';
import { PlanCard } from './PlanCard';
import { ProgressFeed } from './ProgressFeed';
import { scheduleClips } from './Project';
import { newVideo, useUi } from './ui';
import { clipWords, liveText } from '../lib/liveStatus';
import './hub.css';

const GROUPS: [GroupId, MessageKey][] = [
  ['you', 'hub.g.you'],
  ['run', 'hub.g.run'],
  ['ready', 'hub.g.ready'],
  ['out', 'hub.g.out'],
  ['earlier', 'hub.g.earlier'],
];

const SEL = 'v4.hubSel';

export function ControlRoom() {
  const { data, requests = [] } = useHistory();
  const inbox = useInbox();
  const { subscribe } = useEngine();
  const { data: cal, reload: reloadCal } = useLoad((c) => c.calendar(undefined, { queue: false }).catch(() => c.calendar()), []);
  useEffect(() => subscribe((e) => void (e.type === 'calendar' && reloadCal())), [subscribe]); // eslint-disable-line react-hooks/exhaustive-deps
  const posts = useMemo(() => cal?.posts ?? [], [cal]);
  const [q, setQ] = useState('');
  const [sel, setSel] = useState<string | null>(() => routeQuery().sel || sessionStorage.getItem(SEL));
  const [moreEarlier, setMoreEarlier] = useState(false);
  useEffect(() => {
    const on = () => {
      const s = routeQuery().sel;
      if (s) setSel(s);
    };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  useEffect(() => {
    if (sel) sessionStorage.setItem(SEL, sel);
  }, [sel]);
  const deciding = useMemo(() => new Set(inbox.items.filter((x) => x.kind !== 'failed' && x.project.id).map((x) => x.project.id!)), [inbox.items]);
  const items = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const all = data?.items ?? [];
    return ql ? all.filter((i) => [i.name, i.recipe, i.prompt, i.client].some((v) => (v ?? '').toLowerCase().includes(ql))) : all;
  }, [data, q]);
  const reqs = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return ql ? requests.filter((r) => [r.name, r.prompt].some((v) => (v ?? '').toLowerCase().includes(ql))) : requests;
  }, [requests, q]);
  const groups = useMemo(() => hubGroups(items, reqs, posts, deciding), [items, reqs, posts, deciding]);
  const rows = GROUPS.flatMap(([g]) => groups[g]);
  // the selection: what she picked, else (a request that became a project) the newest running one, else the first
  const picked = rows.find((r) => r.id === sel) ?? null;
  // the request she was looking at became projects (Start, or the autopilot applied it): follow it to its project
  const { client } = useEngine();
  const [follow, setFollow] = useState<string[] | null>(null);
  const lost = !!sel && !!data && !picked && /^[0-9a-f]{12}$/.test(sel);
  useEffect(() => {
    if (!lost || !client || !sel) return;
    let alive = true;
    client
      .intake(sel)
      .then((j) => alive && j.applied?.length && setFollow(j.applied.map((x) => x.dir)))
      .catch(() => undefined); // not a request (an archived project): the first row shows
    return () => {
      alive = false;
    };
  }, [lost, client, sel]);
  useEffect(() => {
    if (!follow) return;
    const hit = data?.items.find((x) => follow.includes(x.dir));
    if (hit) {
      setSel(hit.id);
      setFollow(null);
    }
  }, [follow, data]);
  const current = picked ?? groups.you[0] ?? groups.run[0] ?? rows[0] ?? null;
  if (!data) return <div className="hub" data-testid="hub" />;
  if (!rows.length && !q) {
    return (
      <div className="hub-empty" data-testid="hub">
        <Empty
          title={t('hub.empty')}
          action={
            <a className="btn primary" href={href({ name: 'home' })}>
              {t('projects.goHome')}
            </a>
          }
        />
      </div>
    );
  }
  return (
    <div className="hub" data-testid="hub">
      <aside className="hub-list" aria-label={t('projects.title')}>
        <input className="inp hub-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('hub.search')} aria-label={t('hub.search')} data-testid="hub-search" />
        {GROUPS.map(([g, label]) => {
          const list = groups[g];
          if (!list.length) return null;
          const shown = g === 'earlier' && !moreEarlier ? [] : list.slice(0, g === 'earlier' ? 60 : 200);
          return (
            <section key={g} className="hub-group" data-testid={`hub-group-${g}`}>
              <h3>
                {g === 'earlier' ? (
                  <button className="hub-more" onClick={() => setMoreEarlier((v) => !v)} aria-expanded={moreEarlier} data-testid="hub-earlier">
                    {t(label)} · {list.length}
                  </button>
                ) : (
                  <>
                    {t(label)} · {list.length}
                  </>
                )}
              </h3>
              {shown.map((r) => (
                <HubListRow key={r.id} r={r} on={current?.id === r.id} onPick={() => setSel(r.id)} />
              ))}
            </section>
          );
        })}
      </aside>
      <section className="hub-detail" data-testid="hub-detail">
        {current ? (
          current.kind === 'request' ? (
            <RequestDetail key={current.id} r={current.r} onApplied={setFollow} />
          ) : (
            <ProjectDetail key={current.id} i={current.i} p={current.p} posts={posts} />
          )
        ) : (
          <Empty title={t('hub.pick')} />
        )}
      </section>
    </div>
  );
}

export function stateLine(p: Pipeline, i?: HistoryItem, r?: OpenRequest): string {
  switch (p.state) {
    case 'planning':
      return r?.mode === 'autopilot' && r.state === 'done' ? t('hub.s.run') : t('hub.s.planning');
    case 'plan-ready':
      return t('hub.s.planReady');
    case 'you':
      return r?.state === 'needs' ? t('hub.s.needs') : t('hub.s.you');
    case 'queued':
      return t('hub.s.queued', { n: i?.queued ?? 1 });
    case 'run': {
      const msg = liveText(i?.live);
      const step = t(`hub.step.${p.current}` as MessageKey);
      return [step, msg, p.eta ? t('hub.left', { t: fmtMinutes(Math.max(1, Math.round(p.eta / 60))) }) : null].filter(Boolean).join(' · ');
    }
    default:
      return t(`hub.s.${p.state}` as MessageKey);
  }
}

function HubListRow({ r, on, onPick }: { r: HubRow; on: boolean; onPick: () => void }) {
  const name = r.kind === 'request' ? r.r.name || r.r.prompt || t('home.planningRow') : r.i.name;
  const thumb = r.kind === 'project' ? r.i.thumb : null;
  const tone = r.p.state === 'run' || r.p.state === 'planning' ? 'run' : r.p.state === 'you' || r.p.state === 'plan-ready' ? 'you' : r.p.state === 'failed' ? 'error' : r.p.state === 'queued' || r.p.state === 'idle' ? 'off' : 'done';
  const pct = r.p.progress == null ? null : Math.round(r.p.progress * 100);
  return (
    <button className={`hub-row ${on ? 'on' : ''}`} onClick={onPick} aria-current={on ? 'true' : undefined} data-testid="hub-row" data-id={r.id} data-state={r.p.state}>
      <Thumb src={thumb} className="hub-th" />
      <span className="tx">
        <b className="clamp1">{name}</b>
        <span className="s clamp1">
          <i className={`dot ${tone}`} />
          {stateLine(r.p, r.kind === 'project' ? r.i : undefined, r.kind === 'request' ? r.r : undefined)}
          {r.kind === 'project' && r.i.autopilot ? <Sparkles className="ico ap" aria-label={t('ap.auto')} /> : null}
        </span>
        {(r.p.state === 'run' || r.p.state === 'planning' || r.p.state === 'you') && (
          <span className={`bar ${tone === 'you' ? 'you' : ''} ${pct == null ? 'indet' : ''}`}>
            <i style={{ width: `${Math.max(4, pct ?? 30)}%` }} />
          </span>
        )}
      </span>
    </button>
  );
}

function Steps({ p }: { p: Pipeline }) {
  return (
    <ol className="hub-steps" data-testid="hub-steps" data-current={p.current}>
      {STEPS.map((s) => {
        const st = stepState(s, p);
        return (
          <li key={s} className={st} data-step={s} data-state={st}>
            <i />
            <span>{t(`hub.step.${s}` as MessageKey)}</span>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------- a request (not a project yet)
export function RequestDetail({ r, onApplied }: { r: OpenRequest; onApplied: (dirs: string[]) => void }) {
  const { client } = useEngine();
  const { reload } = useHistory();
  const ui = useUi();
  const { job, revise, retry } = useIntakeJob(r.id);
  const discard = async () => {
    if (!client) return;
    try {
      await client.discardIntake(r.id);
      ui.toast(t('hub.discarded'));
      reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  /** 「Start over」: the request goes (nothing was made) and Home has her words and files back in the box */
  const startOver = async () => {
    if (!client) return;
    try {
      await client.discardIntake(r.id);
    } catch {
      // already gone: Home is still where she starts over
    }
    sessionStorage.setItem('v4.composer', JSON.stringify({ prompt: r.prompt ?? '', files: r.inputs ?? [] }));
    sessionStorage.removeItem('v4.hubSel');
    reload();
    newVideo(); // the composer with her words (the Studio's ＋ New video, else Home)
  };
  const p = requestPipeline(r);
  return (
    <div className="hub-d" data-testid="hub-request" data-mode={r.mode}>
      <header className="hub-dh">
        <div className="tx">
          <h2 className="clamp1" data-testid="hub-title">
            {r.name || r.prompt || t('home.planningRow')}
          </h2>
          {r.prompt && <p className="muted clamp2">“{r.prompt}”</p>}
        </div>
        <span className={`hub-mode ${r.mode === 'autopilot' ? 'on' : ''}`} data-testid="hub-request-mode">
          {r.mode === 'autopilot' ? <Sparkles className="ico" /> : null}
          {t(r.mode === 'autopilot' ? 'ap.auto' : 'ap.ask')}
        </span>
        <button className="btn ghost" onClick={() => void discard()} data-testid="hub-discard">
          <Trash2 className="ico" />
          {t('hub.discard')}
        </button>
      </header>
      <div className="card hub-card">
        <b>{stateLine(p, undefined, r)}</b>
        <Steps p={p} />
      </div>
      <PlanCard
        job={job}
        jobId={r.id}
        onRevise={(s) => void revise(s).catch((e) => ui.toast(errText(e), { error: true }))}
        onRetry={() => void retry().catch((e) => ui.toast(errText(e), { error: true }))}
        onReset={() => void startOver()}
        onStarted={() => reload()}
        onApplied={onApplied}
      />
    </div>
  );
}

// ---------------------------------------------------------------- a project
export function ProjectDetail({ i, p, posts }: { i: HistoryItem; p: Pipeline; posts: CalendarPost[] }) {
  const { client, subscribe } = useEngine();
  const { reload: reloadHist } = useHistory();
  const ui = useUi();
  const live = p.state === 'run' || p.state === 'queued';
  const { data: clipsDoc, reload: reloadClips } = useLoad((c) => c.clips(i.id), [i.id, i.updated]);
  const { data: ap, reload: reloadAp } = useLoad((c) => c.autopilot(i.id).catch(() => null as AutopilotDoc | null), [i.id, i.updated]);
  useEffect(() => subscribe((e) => void ((e.type === 'output-edit' && e.item === i.id) || e.type === 'inbox' ? (reloadClips(), reloadAp()) : undefined)), [subscribe, i.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!live) return;
    const tm = setInterval(() => {
      reloadClips();
      reloadAp();
    }, 4000);
    return () => clearInterval(tm);
  }, [live]); // eslint-disable-line react-hooks/exhaustive-deps
  const clips = (clipsDoc?.clips ?? []).filter((c) => !c.extra);
  const ready = clips.filter((c) => clipMade(c));
  const mine = posts.filter((x) => x.item === i.id);
  const pp = postsOf(posts, i.id);
  const unscheduled = ready.filter((c) => !mine.some((x) => x.clip === c.id));
  const on = ap?.supported ? !!ap.autopilot?.on : !!i.autopilot;
  // 「看过程」: open by itself while it runs (what it is doing right now), a click away otherwise
  const [feedOpen, setFeedOpen] = useState(p.state === 'run');
  const setMode = async (v: boolean) => {
    if (!client || v === on) return;
    try {
      await client.autopilotMode(i.id, v);
      ui.toast(t('hub.modeSwitched', { mode: t(v ? 'ap.auto' : 'ap.ask') }));
      reloadAp();
      reloadHist();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  return (
    <div className="hub-d" data-testid="hub-project" data-id={i.id} data-state={p.state}>
      <header className="hub-dh">
        <div className="tx">
          <h2 className="clamp1" data-testid="hub-title">
            {i.name}
          </h2>
          {i.prompt ? <p className="muted clamp2">“{i.prompt}”</p> : <p className="muted">{fmtAgo(i.updated)}</p>}
        </div>
        {(ap?.supported || i.autopilot !== undefined) && (
          <div className="seg hub-modeseg" role="radiogroup" aria-label={t('ap.setting')} data-testid="hub-mode" data-on={on ? '1' : '0'}>
            <button role="radio" aria-checked={on} className={on ? 'on' : ''} onClick={() => void setMode(true)} title={t('hub.modeOn')} data-testid="hub-mode-auto">
              <Sparkles className="ico" />
              {t('ap.auto')}
            </button>
            <button role="radio" aria-checked={!on} className={!on ? 'on' : ''} onClick={() => void setMode(false)} title={t('hub.modeOff')} data-testid="hub-mode-ask">
              {t('ap.ask')}
            </button>
          </div>
        )}
        <a className="btn" href={studioEnabled() ? href({ name: 'project', id: i.id, tab: 'clips' }) : projectHref(i.id)} data-testid="hub-open">
          {studioEnabled() ? t('st.details') : t('hub.open')}
        </a>
      </header>
      <div className="card hub-card" data-testid="hub-status">
        <div className="row">
          <b data-testid="hub-state-line">{stateLine(p, i)}</b>
          <span className="sp" />
          {(i.kind === 'project' || live) && (
            <button className="btn ghost sm hub-feedbtn" onClick={() => setFeedOpen(!feedOpen)} aria-expanded={feedOpen} data-testid="hub-feed-toggle">
              {t(feedOpen ? 'feed.hide' : 'feed.show')}
            </button>
          )}
          {p.state === 'you' && (
            <a className="btn soft sm" href={inboxHref()} data-testid="hub-to-inbox">
              {t('hub.openInbox')}
            </a>
          )}
        </div>
        {p.state === 'queued' && <p className="muted small">{t('hub.queuedLong')}</p>}
        {p.state === 'you' && <p className="muted small">{t('hub.youLong')}</p>}
        {i.failure && (
          <div className="hub-fail" role="alert">
            <span className="muted">{failureReason(i.failure)}</span>
            <FailureActions item={i.id} failure={i.failure} />
          </div>
        )}
        <Steps p={p} />
        {feedOpen && <ProgressFeed item={i.id} clips={clips} running={live || p.state === 'run'} />}
      </div>
      {ap?.supported !== false && <Decisions item={i.id} doc={ap} clips={clips} busy={p.state === 'run'} onChanged={() => (reloadAp(), reloadHist())} />}
      <div className="card hub-card" data-testid="hub-clips">
        <div className="row">
          <b>{t('hub.clips')}</b>
          <span className="muted">{clips.length ? `· ${t('hub.clipsLine', { done: ready.length, n: clips.length })}` : ''}</span>
        </div>
        {clips.length ? (
          <div className="hub-clips">
            {clips.slice(0, 24).map((c) => (
              <ClipTile key={c.id} item={i.id} c={c} post={mine.filter((x) => x.clip === c.id)} />
            ))}
          </div>
        ) : (
          <p className="muted small">{t('hub.clipsNone')}</p>
        )}
      </div>
      <div className="card hub-card" data-testid="hub-publish">
        <div className="row">
          <b>{t('hub.publish')}</b>
          <span className="muted">· {pp.total ? t('hub.postsLine', { s: pp.scheduled, p: pp.posted }) : t('hub.postsNone')}</span>
          <span className="sp" />
          {unscheduled.length > 0 && (
            <button className="btn soft sm" onClick={() => client && void scheduleClips(client, ui, i.id, unscheduled)} data-testid="hub-schedule">
              <CalendarPlus className="ico" />
              {t('hub.schedule', { n: unscheduled.length })}
            </button>
          )}
          <a className="btn ghost sm" href={href({ name: 'calendar' })}>
            {t('hub.openPublish')} <ArrowRight className="ico" />
          </a>
        </div>
      </div>
    </div>
  );
}

/** A clip that came out: not still in the line, not making, not stopped (a stopped job may have left files). */
function clipMade(c: Clip): boolean {
  return c.files.length > 0 && !['queued', 'planned', 'running', 'failed', 'waiting'].includes(c.state);
}

function ClipTile({ item, c, post }: { item: string; c: Clip; post: CalendarPost[] }) {
  const posted = post.find((x) => x.state === 'posted');
  const st =
    c.state === 'running'
      ? t('hub.clipRendering')
      : c.state === 'queued' || c.state === 'planned'
        ? t('hub.clipQueued')
        : c.state === 'failed'
          ? t('hub.clipFailed')
          : clipStatus(c) === 'you'
            ? t('status.you')
            : posted
              ? t('hub.clipPosted')
              : post.length
                ? t('hub.clipScheduled')
                : t('hub.clipReady');
  const made = c.files.length > 0;
  const body = (
    <>
      <Thumb src={c.cover} video={c.cover ? null : c.files[0]?.path ?? null} dur={c.duration} />
      <span className="t clamp1">{c.title}</span>
      <span className={`q ${c.state === 'failed' ? 'bad' : 'muted'}`} data-testid="hub-clip-state" data-state={c.state}>
        {st}
      </span>
    </>
  );
  return made ? (
    <a className="hub-clip" href={clipHref(item, c.id)} data-testid="hub-clip" title={c.title}>
      {body}
    </a>
  ) : (
    <div className="hub-clip off" data-testid="hub-clip" aria-disabled="true">
      {body}
    </div>
  );
}

/** The question in the desk's own words (「确认去口癖」, not the recipe's 「确认去 filler」); the recipe's label only for a
 * question the desk has no words for. */
function decisionLabel(d: AutopilotDecision): string {
  const kindKey = `checkpoint.${d.kind}`;
  if (has(kindKey)) return tk(kindKey);
  const l = d.labels ?? {};
  const own = getLang() === 'zh-CN' ? l.zh || l.en : l.en || l.zh;
  return own || t('hub.decisionOther');
}

function Decisions({ item, doc, clips, busy, onChanged }: { item: string; doc: AutopilotDoc | null; clips: Clip[]; busy: boolean; onChanged: () => void }) {
  const { client } = useEngine();
  const ui = useUi();
  const [sending, setSending] = useState<string | null>(null);
  const list = doc?.decisions ?? [];
  const change = async (d: AutopilotDecision) => {
    if (!client) return;
    if (busy) {
      ui.toast(t('hub.changeBusy'));
      return;
    }
    const k = `${d.checkpoint}:${d.item}`;
    setSending(k);
    try {
      await client.autopilotReopen(item, d.checkpoint, d.item);
      ui.toast(t('hub.changed'));
      onChanged();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setSending(null);
    }
  };
  const made = list.filter((d) => !d.asked);
  return (
    <div className="card hub-card" data-testid="hub-decisions">
      <div className="row">
        <b>{t('hub.decisions')}</b>
        {made.length > 0 && <span className="muted">· {t('hub.decisionsN', { n: made.length })}</span>}
      </div>
      {!list.length ? (
        <p className="muted small">{t('hub.decisionsNone')}</p>
      ) : (
        <ul className="hub-decs">
          {list.slice(0, 40).map((d) => {
            const w = decisionWords(d);
            const k = `${d.checkpoint}:${d.item}`;
            return (
              <li key={k + (d.asked ? ':asked' : '')} data-testid="hub-decision" data-checkpoint={d.checkpoint} data-by={d.asked ? 'asked' : d.by}>
                {d.asked ? <Check className="ico muted" /> : <Sparkles className="ico" />}
                <div className="tx">
                  <div>
                    <b>{decisionLabel(d)}</b>
                    {clipWords(d.item, clips) ? <span className="muted"> · {clipWords(d.item, clips)}</span> : null}
                    {!d.asked && <> — {tk(w.key, w.params)}</>}
                  </div>
                  <div className="muted small">
                    {d.asked ? t('hub.asked') : [d.by === 'ai' ? (d.provider ? t('hub.by.ai', { provider: providerName(d.provider) }) : t('hub.by.aiPlain')) : t('hub.by.rules'), d.reason_code === 'ai' || d.by === 'ai' ? d.reason : null].filter(Boolean).join(' · ')}
                  </div>
                </div>
                {!d.asked && (
                  <button className="btn ghost sm hub-change" onClick={() => void change(d)} disabled={sending === k} data-testid="hub-change">
                    {t('hub.change')}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
