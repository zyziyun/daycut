// Project page (adapts to the type): title -> one line -> the clips (one card per clip: cover, length, size
// versions, caption) -> tabs 成片 / (审片 / 交付) / 修改记录 / 素材和文件 -> details folded. Right: 「让 AI 改」.
// Plain work folders show their in-progress clips and refresh live (fs watch + a 5 s timer while running).
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CalendarPlus, Copy, FolderOpen, Maximize2, Play, Share2, Undo2, Wand2 } from 'lucide-react';
import type { HistoryDetail } from '../../../shared/v02';
import type { Clip, ClipsDoc, OutputDoc } from '../../../shared/v04';
import { fmtDate, fmtMinutes, t } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { go, href, type ProjectTab } from '../lib/router';
import { clipStatus, itemStatus } from '../lib/status';
import { ProjectAIPanel } from './ProjectAIPanel';
import { inboxTitle } from './Inbox';
import { Elapsed, Empty, More, SkGrid, StatusPill, Thumb } from './kit';
import { FailureActions, failureReason } from './Failure';
import { PlayerOverlay } from './Player';
import { ShareButton, ShareDialog } from './ShareDialog';
import { emsg, errText } from './msg';
import { useUi } from './ui';

export function nextSlots(n: number, taken: string[], hour = '19:00', from = new Date()): string[] {
  const out: string[] = [];
  const d = new Date(from);
  d.setHours(0, 0, 0, 0);
  const used = new Set(taken.map((x) => x.slice(0, 10)));
  for (let i = 1; out.length < n && i < 120; i++) {
    const day = new Date(d.getTime() + i * 86400000);
    const iso = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
    if (!used.has(iso)) {
      out.push(`${iso}T${hour}`);
      used.add(iso);
    }
  }
  return out;
}

export function Project({ id, tab }: { id: string; tab: ProjectTab }) {
  const { client, subscribe } = useEngine();
  const { data: hist, reload: reloadHist } = useHistory();
  const inbox = useInbox();
  const ui = useUi();
  const item = hist?.items.find((i) => i.id === id) ?? null;
  const [doc, setDoc] = useState<ClipsDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const [playing, setPlaying] = useState<{ clip: Clip; aspect?: string } | null>(null);
  const [aspects, setAspects] = useState<Record<string, string>>({});
  const [shareClip, setShareClip] = useState<string | null>(null);
  const [n, setN] = useState(0);
  const reload = useCallback(() => setN((x) => x + 1), []);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .clips(id)
      .then((d) => alive && (setDoc(d), setErr(null)))
      .catch((e: Error) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [client, id, n, hist?.at]);
  useEffect(() => subscribe((e) => (e.type === 'output-edit' && e.item === id) || e.type === 'run-exit' ? reload() : undefined), [subscribe, id, reload]);
  const pendingAll = inbox.items.filter((x) => x.project.id === id);
  const reviewItem = pendingAll.find((x) => x.kind === 'review');
  const raw = item ? itemStatus(item) : null;
  // 「已完成」 never sits next to 「审片 3」: clips waiting for her review make the project "needs you"
  const s = raw === 'done' && (reviewItem || pendingAll.some((x) => x.kind === 'confirm' || x.group === 'choose')) ? 'you' : raw;
  const failure = item?.failure ?? null;
  const live = s === 'run' || doc?.clips.some((c) => c.state === 'running');
  useEffect(() => {
    if (!live) return;
    const tm = setInterval(() => {
      reload(); // B4: a rendering folder updates by itself
      reloadHist(); // the pilot's stage / a failure shows up without waiting for the slow history timer
    }, 5000);
    return () => clearInterval(tm);
  }, [live, reload, reloadHist]);

  const clips = useMemo(() => (doc?.clips ?? []).filter((c) => !c.extra), [doc]);
  const extras = useMemo(() => (doc?.clips ?? []).filter((c) => c.extra), [doc]);
  const sel = clips.find((c) => c.id === selId) ?? clips.find((c) => c.post) ?? clips[0] ?? null;
  const pending = pendingAll;
  const review = reviewItem;
  const confirm = pending.find((x) => x.kind === 'confirm' || x.group === 'choose');
  const done = clips.filter((c) => c.state !== 'queued' && c.state !== 'running' && c.files.length);
  const isBatch = item?.kind === 'batch' || item?.kind === 'project';

  const schedule = async (list: Clip[]) => {
    if (!client || !list.length) return;
    const cal = await client.calendar();
    const mine = new Set(cal.posts.filter((p) => p.item === id).map((p) => p.clip));
    const todo = list.filter((c) => !mine.has(c.id));
    const slots = nextSlots(todo.length, cal.posts.map((p) => p.at));
    const made: { id: string; at: string }[] = [];
    for (let i = 0; i < todo.length; i++) made.push(await client.schedule({ item: id, clip: todo[i].id, at: slots[i], platform: 'xiaohongshu' }));
    ui.toast(made.length ? t('pub.scheduled', { date: fmtDate(made[0].at) }) : t('pub.confirmed', { n: 0 }), {
      undo: made.length
        ? async () => {
            for (const p of made) await client.updatePost(p.id, { remove: true });
          }
        : undefined,
    });
  };
  const clipMenu = (c: Clip) => (e: React.MouseEvent) =>
    ui.menu(e, [
      { label: t('clip.play'), icon: <Maximize2 className="ico" />, run: () => setPlaying({ clip: c, aspect: aspects[c.id] }), testId: 'menu-play' },
      { label: t('clip.edit'), icon: <Wand2 className="ico" />, run: () => go({ name: 'clip', id, clip: c.id }), testId: 'menu-edit' },
      { label: t('clip.copyCaption'), icon: <Copy className="ico" />, run: () => copyPost(c) },
      { label: t('c.reveal'), icon: <FolderOpen className="ico" />, run: () => c.files[0] && window.desk.showItem(c.files[0].path) },
      { label: t('clip.schedule'), icon: <CalendarPlus className="ico" />, run: () => schedule([c]) },
      { label: t('share.menu'), icon: <Share2 className="ico" />, run: () => setShareClip(c.id), testId: 'menu-share' },
    ]);
  const copyPost = async (c: Clip) => {
    if (!c.post) return;
    await window.desk.copyText(`${c.post.title}\n\n${c.post.body}\n\n${c.post.tags.map((x) => `#${x}`).join(' ')}`);
    ui.toast(t('c.copied'));
  };

  if (hist && !item) {
    return (
      <div className="pg">
        <a className="back" href={href({ name: 'projects' })}>
          <ArrowLeft className="ico" />
          {t('project.back')}
        </a>
        <Empty title={t('project.notFound')} />
      </div>
    );
  }
  const k = Math.min(clips.length, done.length + 1);
  const sub = failure
    ? t('project.sub.failed')
    : s === 'run'
      ? clips.length
        ? t('project.sub.running', { k, n: clips.length })
        : t('project.sub.runningNoN')
      : review
        ? t('project.sub.review', { passed: review.params.passed ?? 0, n: review.params.n ?? 0 })
        : clips.length
          ? t('project.sub.done', { n: clips.length })
          : t('project.sub.empty');
  const tabs: [ProjectTab, string, number | null][] = [
    ['clips', t('project.tab.clips'), clips.length || null],
    ...(isBatch && item?.openable ? ([['review', t('project.tab.review'), review ? Number(review.params.n) : null]] as [ProjectTab, string, number | null][]) : []),
    ...(isBatch && item?.openable ? ([['deliver', t('project.tab.deliver'), null]] as [ProjectTab, string, number | null][]) : []),
    ['history', t('project.tab.history'), null],
    ['files', t('project.tab.files'), null],
  ];
  const primary = review ? (
    <button className="btn primary" onClick={() => go({ name: 'focus', id })} data-testid="project-primary">
      {t('project.reviewN', { n: review.params.n ?? 0, m: fmtMinutes(review.minutes ?? 1) })}
    </button>
  ) : s === 'done' && done.length ? (
    <button className="btn primary" onClick={() => void schedule(done)} data-testid="project-primary">
      <CalendarPlus className="ico" />
      {t('project.schedule')}
    </button>
  ) : null;

  return (
    <div className={`proj`} data-testid="project">
      <div className="scroll">
        <div className="pg wide">
          <a className="back" href={href({ name: 'projects' })}>
            <ArrowLeft className="ico" />
            {t('project.back')}
          </a>
          <div className="ph">
            <div style={{ minWidth: 0 }}>
              <h1 className="clamp1" data-testid="project-title">
                {item?.name ?? ''}
              </h1>
              <p>{sub}</p>
            </div>
            <span className="sp" />
            <div className="acts">
              <StatusPill s={s} label={failure ? t('status.failed') : undefined} />
              {!failure && done.length > 0 && <ShareButton item={id} />}
              {!failure && primary}
            </div>
          </div>
          {failure && item && (
            <div className="banner error" role="alert" data-testid="project-failed">
              <i className="dot error" />
              <div className="sp">
                <b>{t('fail.title')}</b>
                <span className="muted">{failureReason(failure)}</span>
              </div>
              <div className="acts">
                <FailureActions item={item.id} failure={failure} />
              </div>
            </div>
          )}
          {!failure && s === 'run' && !clips.length && item && (
            <div className="banner run" role="status" data-testid="project-running">
              <i className="dot run" />
              <div className="sp">
                <b>
                  {t('project.pilot.running')}
                  {item.live?.stage ? ` · ${item.live.stage}` : ''}
                </b>
                <span className="muted">
                  {t('project.pilot.elapsed')} <Elapsed since={item.live?.started ?? item.pilot?.started ?? null} />
                </span>
              </div>
              {item.live?.progress != null && (
                <div className="bar" aria-label={t('project.pilot.running')}>
                  <i style={{ width: `${Math.round(Math.min(1, Math.max(0.03, item.live.progress)) * 100)}%` }} />
                </div>
              )}
            </div>
          )}
          {confirm && !review && (
            <div className="banner" data-testid="project-banner">
              <i className="dot you" />
              <div className="sp">
                <b>{confirm.kind === 'confirm' ? t('project.confirmTitle', { n: confirm.params.n ?? 0 }) : inboxTitle(confirm)}</b>
                <span className="muted">{t('project.confirmHint')}</span>
              </div>
              <a className={`btn ${primary ? '' : 'primary'}`} href={href({ name: 'inbox' })}>
                {t('project.confirmGo')}
              </a>
            </div>
          )}
          <nav className="tabs4" role="tablist">
            {tabs.map(([k2, label, cnt]) => (
              <a key={k2} href={href({ name: 'project', id, tab: k2 })} className={tab === k2 ? 'on' : ''} role="tab" aria-selected={tab === k2} data-testid={`tab-${k2}`}>
                {label}
                {cnt ? <span className="n">{k2 === 'clips' && s === 'run' ? `${done.length} / ${cnt}` : cnt}</span> : null}
              </a>
            ))}
          </nav>
          {tab === 'clips' && (
            <>
              {err && <div className="note">{err}</div>}
              {!doc ? (
                <SkGrid n={4} />
              ) : !clips.length ? (
                <Empty title={failure ? t('project.empty.failed') : s === 'run' ? t('project.empty.running') : t('project.sub.empty')} />
              ) : (
                <div className="clips" data-testid="clips">
                  {clips.map((c) => (
                    <ClipCard
                      key={c.id}
                      c={c}
                      on={sel?.id === c.id}
                      aspect={aspects[c.id]}
                      onAspect={(a) => setAspects({ ...aspects, [c.id]: a })}
                      onPick={() => setSelId(c.id)}
                      onPlay={() => setPlaying({ clip: c, aspect: aspects[c.id] })}
                      onContext={clipMenu(c)}
                      eta={c.state === 'running' ? item?.live?.eta : null}
                    />
                  ))}
                </div>
              )}
              {sel?.post && (
                <div className="card copycard" data-testid="post-copy">
                  <div className="row">
                    <h2 className="sp clamp1" lang="zh-CN">
                      {t('project.captionOf', { title: sel.post.title || sel.title })}
                    </h2>
                    <button className="btn" onClick={() => void copyPost(sel)} data-testid="copy-post">
                      <Copy className="ico" />
                      {t('c.copy')}
                    </button>
                  </div>
                  <div className="body" lang="zh-CN">
                    {sel.post.body}
                  </div>
                  <div className="tags">{sel.post.tags.map((x) => `#${x}`).join(' ')}</div>
                </div>
              )}
              <Details id={id} kind={item?.kind} running={s === 'run'} />
            </>
          )}
          {tab === 'review' && <ReviewTab id={id} n={review ? Number(review.params.n) : 0} />}
          {tab === 'deliver' && (
            <div className="row">
              <a className="btn" href={href({ name: 'deliver', batch: id })}>
                {t('project.tab.deliver')}
              </a>
              {done.length > 0 && <ShareButton item={id} testId="deliver-share" />}
            </div>
          )}
          {tab === 'history' && <HistoryTab id={id} clips={clips} onChanged={reload} />}
          {tab === 'files' && <FilesTab id={id} extras={extras} />}
        </div>
      </div>
      <ProjectAIPanel
        item={id}
        clips={done.map((c) => ({ id: c.id, title: c.title }))}
        selected={sel && done.includes(sel) ? { id: sel.id, title: sel.title } : null}
        running={s === 'run'}
        liveText={s === 'run' ? item?.live?.message : null}
        onApplied={reload}
      />
      {shareClip && <ShareDialog item={id} only={[shareClip]} onClose={() => setShareClip(null)} />}
      {playing && (
        <PlayerOverlay
          files={playing.clip.files}
          duration={playing.clip.duration ?? undefined}
          title={playing.clip.title}
          initialAspect={playing.aspect}
          onClose={() => setPlaying(null)}
          onEdit={() => go({ name: 'clip', id, clip: playing.clip.id })}
        />
      )}
    </div>
  );
}

function ClipCard({ c, on, aspect, onAspect, onPick, onPlay, onContext, eta }: { c: Clip; on: boolean; aspect?: string; onAspect: (a: string) => void; onPick: () => void; onPlay: () => void; onContext: (e: React.MouseEvent) => void; eta?: number | null }) {
  const file = c.files.find((f) => f.aspect === aspect) ?? c.files[0];
  const st = clipStatus(c);
  const ready = c.files.length > 0 && c.state !== 'queued' && c.state !== 'running';
  return (
    <div
      className={`clip ${on ? 'on' : ''}`}
      onClick={() => (ready ? (onPick(), onPlay()) : onPick())}
      onContextMenu={ready ? onContext : undefined}
      onKeyDown={(e) => e.key === 'Enter' && ready && onPlay()}
      role="button"
      tabIndex={0}
      data-testid="clip-card"
      data-clip={c.id}
      data-state={c.state}
    >
      {ready ? (
        <Thumb src={c.cover} video={file?.path} dur={c.duration} play />
      ) : (
        <div className="th ph-thumb">{c.state === 'running' ? t('clip.rendering') : t('clip.queued')}</div>
      )}
      <div className="t clamp2" lang="zh-CN">
        {c.title}
      </div>
      {ready ? (
        <div className="row" onClick={(e) => e.stopPropagation()}>
          {c.files.length > 1 ? (
            <div className="vers">
              {c.files.map((f) => (
                <button key={f.aspect} className={f.aspect === file?.aspect ? 'on' : ''} onClick={() => onAspect(f.aspect)} data-testid={`clip-size-${f.aspect}`}>
                  {/^\d+:\d+$/.test(f.aspect) ? f.aspect : t('c.original')}
                </button>
              ))}
            </div>
          ) : (
            <StatusPill s={st} />
          )}
          <span className="sp" />
          {c.post && (
            <button className="link" onClick={onPick}>
              {t('project.caption')}
            </button>
          )}
          <button className="btn ghost icon sm" onClick={onPlay} aria-label={t('clip.play')} data-tip={t('clip.play')}>
            <Play className="ico" />
          </button>
        </div>
      ) : c.state === 'running' ? (
        <>
          <div className="bar">
            <i style={{ width: '55%' }} />
          </div>
          <span className="muted">{eta ? t('clip.renderingLeft', { t: fmtMinutes(eta / 60) }) : t('clip.rendering')}</span>
        </>
      ) : (
        <span className="muted">{t('clip.queued')}</span>
      )}
    </div>
  );
}

function Details({ id, kind, running }: { id: string; kind?: string; running: boolean }) {
  const { client } = useEngine();
  const [d, setD] = useState<HistoryDetail | null>(null);
  return (
    <More summary={running ? t('project.detailsRun') : t('project.details')} testId="project-details">
      <DetailBody id={id} kind={kind} d={d} load={() => client?.historyItem(id).then(setD)} />
    </More>
  );
}

function DetailBody({ id, kind, d, load }: { id: string; kind?: string; d: HistoryDetail | null; load: () => unknown }) {
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  if (!d) return <div className="sk" style={{ height: 80, marginTop: 12 }} />;
  return (
    <div className="col" style={{ marginTop: 12 }}>
      {(d.detail?.notes ?? []).map((n) => (
        <details key={n.path}>
          <summary className="muted">{n.path.split('/').pop()}</summary>
          <pre className="note" style={{ whiteSpace: 'pre-wrap', userSelect: 'text', maxHeight: 360, overflow: 'auto' }} lang="zh-CN">
            {n.text}
          </pre>
        </details>
      ))}
      <div className="kv">
        <span>{t('project.folder')}</span>
        <span>{d.dir}</span>
        <span>{t('c.details')}</span>
        <span>
          {d.kind} · {d.recipe ?? '–'} · {d.status}
          {d.live?.stage ? ` · ${d.live.stage}` : ''}
        </span>
      </div>
      <div className="row">
        <button className="btn" onClick={() => void window.desk.showItem(d.dir)}>
          <FolderOpen className="ico" />
          {t('c.reveal')}
        </button>
        {kind !== 'work' && d.openable && (
          <a className="btn ghost" href={href({ name: 'board', batch: id })}>
            {t('project.openBoard')}
          </a>
        )}
      </div>
      {d.log && (
        <>
          <span className="muted">{t('project.log')}</span>
          <pre className="note" style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: 12, maxHeight: 240, overflow: 'auto', userSelect: 'text' }} data-testid="log-tail">
            {d.log.text}
          </pre>
        </>
      )}
    </div>
  );
}

function ReviewTab({ id, n }: { id: string; n: number }) {
  return (
    <div className="col">
      <div className="row">
        <a className="btn primary" href={href({ name: 'focus', id })}>
          {t('inbox.startReview', { m: fmtMinutes(Math.max(1, n * 1.2)) })}
        </a>
        <a className="btn ghost" href={href({ name: 'review', batch: id })}>
          {t('project.tab.review')}
        </a>
      </div>
    </div>
  );
}

function HistoryTab({ id, clips, onChanged }: { id: string; clips: Clip[]; onChanged: () => void }) {
  const { client } = useEngine();
  const ui = useUi();
  const [docs, setDocs] = useState<OutputDoc[] | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    void Promise.all(clips.filter((c) => c.files.length).map((c) => client.output(id, c.id).catch(() => null))).then((r) => alive && setDocs(r.filter((x): x is OutputDoc => !!x)));
    return () => {
      alive = false;
    };
  }, [client, id, clips, n]);
  if (!docs) return <div className="sk" style={{ height: 120 }} />;
  const edited = docs.filter((d) => d.steps.length);
  if (!edited.length) return <Empty title={t('project.noChanges')} />;
  return (
    <div className="col" style={{ gap: 16 }} data-testid="history-tab">
      {edited.map((d) => (
        <div key={d.id} className="card" style={{ padding: 16 }}>
          <div className="row">
            <b style={{ fontWeight: 500 }} className="sp clamp1" lang="zh-CN">
              {d.title}
            </b>
            <span className="muted">{t('project.edits', { n: d.steps.length })}</span>
            <a className="btn sm" href={href({ name: 'clip', id, clip: d.id })}>
              <Wand2 className="ico" />
              {t('clip.edit')}
            </a>
          </div>
          <div className="oplist" style={{ marginTop: 8 }}>
            {d.steps.map((s, k) => (
              <div key={s.id} className="li">
                <span className="faint num">{k + 1}</span>
                <span className="sp clamp1">{s.describe.map(emsg).join(' · ')}</span>
                <button
                  className="btn ghost sm"
                  onClick={async () => {
                    try {
                      await client?.undoOutput(id, d.id, d.steps.length - k);
                      setN((x) => x + 1);
                      onChanged();
                      ui.toast(t('ai.undone'));
                    } catch (e) {
                      ui.toast(errText(e), { error: true });
                    }
                  }}
                >
                  <Undo2 className="ico" />
                  {t('c.undo')}
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function FilesTab({ id, extras }: { id: string; extras: Clip[] }) {
  const { client } = useEngine();
  const [d, setD] = useState<HistoryDetail | null>(null);
  return (
    <div className="col" style={{ gap: 24 }}>
      {extras.length > 0 && (
        <section>
          <div className="sech">
            <h2>{t('project.otherFiles')}</h2>
          </div>
          <div className="clips">
            {extras.map((c) => (
              <div key={c.id} className="clip">
                <Thumb src={c.cover} video={c.files[0]?.path} dur={c.duration} />
                <span className="clamp1">{c.files[0]?.path.split('/').pop()}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section>
        <DetailBody id={id} kind={undefined} d={d} load={() => client?.historyItem(id).then(setD)} />
      </section>
      {(d?.detail?.sources ?? []).length > 0 && (
        <section>
          <div className="sech">
            <h2>{t('project.sources')}</h2>
          </div>
          <div className="col">
            {d!.detail!.sources.map((s) => (
              <button key={s} className="link" style={{ textAlign: 'left' }} onClick={() => void window.desk.showItem(s)}>
                {s.split('/').pop()}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
