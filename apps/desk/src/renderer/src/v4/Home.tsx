// Home (ux/home-redesign A1-A6): say what to make, then what needs doing next, in that order.
//   composer  - the whole card is a drop target; files become chips; the platform chip is editable; ⌘↵ makes a plan
//               (where AI runs lives in Settings, not here)
//   ideas     - from her own work: the next episode of a series, a project with clips left, a recent request
//   Inbox     - the top 3 with their own button each, "n more" in one line (same count as the sidebar badge)
//   Running   - only while something runs
//   Going out today - a thin strip of today's posts
//   quiet     - "All clear" + Continue tiles; first run - six starting points
// Every project / clip / post on the page is the same link as everywhere else (lib/nav).
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Check, ChevronDown, ChevronRight, File as FileIcon, FileText, Film, Folder, FolderOpen, Image as ImageIcon, Lightbulb, MessageSquare, Mic, MoreHorizontal, Music, Paperclip, Plus, Repeat, Sparkles, Video, X } from 'lucide-react';
import type { HistoryItem } from '../../../shared/v02';
import type { CalendarPost, InboxItem, IntakeJob } from '../../../shared/v04';
import { fmtAgo, fmtTime, getLang, t, tk, type MessageKey } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { inboxHref, itemTarget, postHref, projectHref } from '../lib/nav';
import { href } from '../lib/router';
import { itemStatus } from '../lib/status';
import { Empty, Mosaic, Sk, StatusPill, Thumb } from './kit';
import { homeIdeas, IDEAS } from '../lib/homeIdeas';
import { PlanCard } from './PlanCard';
import { inboxSub, inboxTitle, InboxThumb } from './Inbox';
import { FailureActions } from './Failure';
import { PlatformIcon } from './PlatformIcon';
import { PlatformPicker } from './PlatformPicker';
import { useUi } from './ui';
import '../theme/uxcore.css';

/** First run: six starting points (title, what it does, the request it fills in). */
const STARTS: { icon: typeof Film; title: MessageKey; sub: MessageKey; prompt: MessageKey }[] = [
  { icon: Film, title: 'home.start.clips', sub: 'home.start.clipsSub', prompt: 'home.idea1Prompt' },
  { icon: Mic, title: 'home.start.talking', sub: 'home.start.talkingSub', prompt: 'home.idea2Prompt' },
  { icon: MessageSquare, title: 'home.start.course', sub: 'home.start.courseSub', prompt: 'home.idea3Prompt' },
  { icon: Lightbulb, title: 'home.start.explainer', sub: 'home.start.explainerSub', prompt: 'home.idea4Prompt' },
  { icon: Repeat, title: 'home.start.series', sub: 'home.start.seriesSub', prompt: 'home.idea5Prompt' },
  { icon: Folder, title: 'home.start.folder', sub: 'home.start.folderSub', prompt: 'home.start.folderPrompt' },
];

export function platformName(id: string): string {
  return tk(`pf.${id.split(':')[0]}`);
}

function kindIcon(p: string) {
  const e = p.toLowerCase().split('.').pop() ?? '';
  if (['mp4', 'mov', 'm4v', 'mkv', 'webm'].includes(e)) return <Video className="ico" />;
  if (['jpg', 'jpeg', 'png', 'webp', 'heic'].includes(e)) return <ImageIcon className="ico" />;
  if (['wav', 'mp3', 'm4a', 'aac', 'flac'].includes(e)) return <Music className="ico" />;
  if (['pdf', 'docx', 'pptx', 'md', 'txt', 'srt', 'vtt'].includes(e)) return <FileText className="ico" />;
  if (!p.includes('.') || p.endsWith('/')) return <Folder className="ico" />;
  return <FileIcon className="ico" />;
}

const base = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? p;
const isImage = (p: string) => /\.(jpe?g|png|webp)$/i.test(p);
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** Remember the last request + files so a reload never loses what she typed. */
const DRAFT = 'v4.composer';

export function Home() {
  const { client } = useEngine();
  const ui = useUi();
  const { data: hist } = useHistory();
  const draft = useMemo(() => {
    try {
      return JSON.parse(sessionStorage.getItem(DRAFT) ?? '{}') as { prompt?: string; files?: string[]; job?: string };
    } catch {
      return {};
    }
  }, []);
  const [prompt, setPrompt] = useState(draft.prompt ?? '');
  const [files, setFiles] = useState<string[]>(draft.files ?? []);
  const [jobId, setJobId] = useState<string | null>(draft.job ?? null);
  const [job, setJob] = useState<IntakeJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [platforms, setPlatforms] = useState<string[] | null>(null);
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const { data: recent } = useLoad((c) => c.recentPrompts(), [jobId]);
  const firstRun = !!hist && hist.items.length === 0;

  useEffect(() => {
    sessionStorage.setItem(DRAFT, JSON.stringify({ prompt, files, job: jobId }));
  }, [prompt, files, jobId]);
  useEffect(() => {
    void window.desk.getSettings().then((s) => setPlatforms(s.defaultPlatforms ?? []));
  }, []);
  // files dropped anywhere on the window, and 「再来一批」 prefill
  useEffect(() => {
    if (ui.dropped.length) setFiles((f) => [...new Set([...f, ...ui.takeDropped()])]);
  }, [ui.dropped, ui]);
  useEffect(() => {
    if (ui.prefill) {
      setPrompt(ui.prefill);
      ui.setPrefill(null);
      setJobId(null);
      setTimeout(() => ta.current?.focus(), 30);
    }
  }, [ui.prefill, ui]);

  // poll the plan job (engine events also nudge it)
  useEffect(() => {
    if (!client || !jobId) {
      setJob(null);
      return;
    }
    let alive = true;
    let tm: ReturnType<typeof setTimeout>;
    const tick = () =>
      client
        .intake(jobId)
        .then((j) => {
          if (!alive) return;
          setJob(j);
          if (j.state === 'running') tm = setTimeout(tick, 600);
        })
        .catch(() => alive && (setJobId(null), setJob(null)));
    void tick();
    return () => {
      alive = false;
      clearTimeout(tm);
    };
  }, [client, jobId]);

  const ready = !!(prompt.trim() || files.length);
  const submit = async () => {
    if (!client || busy || !ready) return;
    setBusy(true);
    try {
      const r = await client.startIntake(prompt.trim(), files, platforms ?? undefined);
      setJobId(r.id);
    } catch (e) {
      ui.toast((e as Error).message, { error: true });
    } finally {
      setBusy(false);
    }
  };
  const revise = async (text: string) => {
    if (!client || !jobId) return;
    try {
      await client.reviseIntake(jobId, text);
      setJob((j) => (j ? { ...j, state: 'running', step: 'revise' } : j));
      const r = await client.intake(jobId);
      setJob(r);
      setJobId(jobId); // re-arm polling
      const poll = async () => {
        for (let i = 0; i < 600; i++) {
          const j = await client.intake(jobId);
          setJob(j);
          if (j.state !== 'running') return;
          await new Promise((res) => setTimeout(res, 600));
        }
      };
      void poll();
    } catch (e) {
      ui.toast((e as Error).message, { error: true });
    }
  };
  const reset = () => {
    setJobId(null);
    setJob(null);
  };
  const started = () => {
    setPrompt('');
    setFiles([]);
    reset();
  };

  const addFiles = async (kind: 'files' | 'folder') => {
    const got = kind === 'files' ? await window.desk.openFiles('any') : [await window.desk.openFolder()].filter((x): x is string => !!x);
    if (got.length) setFiles((f) => [...new Set([...f, ...got])]);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setOver(false);
    const paths = [...e.dataTransfer.files].map((f) => window.desk.pathForFile?.(f) ?? '').filter(Boolean);
    if (paths.length) setFiles((f) => [...new Set([...f, ...paths])]);
  };
  const savePlatforms = (v: string[]) => {
    setPlatforms(v);
    if (v.length) void window.desk.setSettings({ defaultPlatforms: v.slice(0, 8) }).catch(() => undefined);
  };
  const fill = (p: string) => {
    setPrompt(p);
    setTimeout(() => {
      ta.current?.focus();
      ta.current?.setSelectionRange(p.length, p.length);
    }, 20);
  };

  const planning = !!jobId;
  const ideas = homeIdeas(hist?.items ?? [], recent ?? []);
  return (
    <div className="scroll ux-home" data-testid="home">
      <div className="pg">
        {!planning && (
          <div className={`ux-hello ${firstRun ? 'first' : ''}`}>
            <h1>{firstRun ? t('home.titleFirst') : t('home.title')}</h1>
            {firstRun && <p className="muted">{t('home.firstLead')}</p>}
          </div>
        )}
        <div
          className={`ux-composer ${over ? 'over' : ''} ${prompt ? 'typing' : ''}`}
          data-own-drop
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          data-testid="composer"
        >
          <textarea
            ref={ta}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={firstRun ? t('home.placeholderFirst') : t('home.placeholderDrop')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void submit();
              }
            }}
            readOnly={planning && job?.state === 'running'}
            rows={planning ? 2 : 2}
            data-testid="composer-input"
          />
          {files.length > 0 && (
            <div className="files" data-testid="composer-files">
              {files.map((f) => (
                <span key={f} className="file" title={f}>
                  <span className="ic">{isImage(f) ? <img src={window.desk.mediaUrl(f)} alt="" /> : kindIcon(f)}</span>
                  <span className="clamp1">{base(f)}</span>
                  {!planning && (
                    <button className="x" onClick={() => setFiles(files.filter((x) => x !== f))} aria-label={t('c.remove')}>
                      <X className="ico" />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
          {!planning && (
            <div className="foot">
              <button
                className="btn icon lg ux-attach"
                onClick={(e) => {
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  ui.menu({ clientX: r.left, clientY: r.bottom + 6 }, [
                    { label: t('home.addFiles'), icon: <Plus className="ico" />, run: () => addFiles('files'), testId: 'add-files' },
                    { label: t('home.addFolder'), icon: <FolderOpen className="ico" />, run: () => addFiles('folder'), testId: 'add-folder' },
                  ]);
                }}
                aria-label={t('home.attach')}
                data-tip={t('home.attachTip')}
                data-testid="composer-attach"
              >
                <Paperclip className="ico" />
              </button>
              <PlatformChip value={platforms} onChange={savePlatforms} />
              <span className="sp" />
              <span className="ux-kbdhint" aria-hidden>
                ⌘↵
              </span>
              <button className={`btn lg ux-make ${ready ? 'primary' : ''}`} disabled={busy || !ready} onClick={() => void submit()} data-testid="make-plan">
                <Sparkles className="ico" />
                {t('home.submit')}
              </button>
            </div>
          )}
        </div>
        {!planning && !firstRun && (
          <div className="ux-ideas" data-testid="home-ideas">
            {ideas.map((x) => (
              <button key={x.id} className="ux-idea" onClick={() => fill(x.prompt)} data-kind={x.kind} data-testid="home-idea" title={x.prompt}>
                {x.thumb ? <img src={window.desk.mediaUrl(x.thumb)} alt="" /> : x.kind === 'recent' ? <FolderOpen className="ico" /> : <Repeat className="ico" />}
                <span className="clamp1">{x.label}</span>
                {x.sub && <span className="faint clamp1">{x.sub}</span>}
              </button>
            ))}
            <button
              className="ux-idea more"
              aria-label={t('home.moreIdeas')}
              onClick={(e) => {
                const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                ui.menu({ clientX: r.left - 160, clientY: r.bottom + 6 }, [
                  ...IDEAS.map(([k, pk]) => ({ label: t(k), run: () => fill(t(pk)) })),
                  ...(recent ?? []).slice(1, 4).map((r2) => ({ label: r2.prompt.slice(0, 48), icon: <FolderOpen className="ico" />, run: () => fill(r2.prompt) })),
                ]);
              }}
              data-testid="home-more-ideas"
            >
              <MoreHorizontal className="ico" />
            </button>
          </div>
        )}
        {(recent?.length ?? 0) > 0 && !planning && !firstRun && (
          <span className="sr" data-testid="recent-prompts">
            {recent!.map((r) => r.prompt).join(' · ')}
          </span>
        )}
        {planning && <PlanCard job={job} jobId={jobId!} onRevise={revise} onReset={reset} onStarted={started} />}
        {!planning && (firstRun ? <FirstRunStarts onPick={(p) => fill(p)} /> : <Below />)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the platform chip (editable defaults)
function PlatformChip({ value, onChange }: { value: string[] | null; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('mousedown', close);
    window.addEventListener('keydown', esc);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', esc);
    };
  }, [open]);
  const ids = [...new Set((value ?? []).map((p) => p.split(':')[0]))];
  const names = ids.map(platformName);
  const sep = getLang() === 'zh-CN' ? '、' : ', ';
  const label = !ids.length ? t('home.choosePlatforms') : names.length <= 2 ? names.join(sep) : t('home.platformsMore', { a: names.slice(0, 2).join(sep), n: names.length - 2 });
  return (
    <div className="ux-pfchip-wrap" ref={box}>
      <button className={`ux-pfchip ${ids.length ? '' : 'empty'}`} onClick={() => setOpen((o) => !o)} aria-expanded={open} data-testid="composer-platforms">
        {ids.length ? (
          <span className="ux-pfics">
            {ids.slice(0, 5).map((p) => (
              <PlatformIcon key={p} id={p} size={18} />
            ))}
          </span>
        ) : (
          <Plus className="ico" />
        )}
        <span className="clamp1">{label}</span>
        {ids.length > 0 && <ChevronDown className="ico" />}
      </button>
      {open && (
        <div className="ux-pop" data-testid="platform-popover">
          <div className="muted" style={{ marginBottom: 8 }}>
            {t('home.platformsTitle')}
          </div>
          <PlatformPicker multi value={ids} onChange={(v) => onChange(v)} testId="home-pf" />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- first run
function FirstRunStarts({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="ux-starts" data-testid="home-starts">
      {STARTS.map((s) => (
        <button key={s.title} className="card ux-start" onClick={() => onPick(t(s.prompt))} data-testid="home-start">
          <span className="ic">
            <s.icon className="ico lg" />
          </span>
          <span>
            <b>{t(s.title)}</b>
            <span className="muted">{t(s.sub)}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- below the composer
function Below() {
  const { data, live } = useHistory();
  const inbox = useInbox();
  const { subscribe } = useEngine();
  const { data: cal, reload: reloadCal } = useLoad((c) => c.calendar(today()), []);
  useEffect(() => subscribe((e) => void (e.type === 'calendar' && reloadCal())), [subscribe]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = data?.items ?? [];
  const now = Date.now();
  const todays = (cal?.posts ?? []).filter((p) => p.at.slice(0, 10) === today());
  const next = (cal?.posts ?? []).find((p) => p.state !== 'posted' && new Date(p.at).getTime() > now);
  const runs = live.filter((i) => i.live?.state === 'running');
  if (!data) {
    return (
      <div className="ux-sec">
        <Sk w={160} h={18} />
        <div style={{ marginTop: 12 }}>
          <Sk h={180} r={12} />
        </div>
      </div>
    );
  }
  const quiet = !inbox.items.length && !runs.length;
  return (
    <>
      {inbox.items.length > 0 && <HomeInbox items={inbox.items} />}
      {runs.length > 0 && <Running runs={runs} />}
      {quiet && <AllClear next={next ?? null} />}
      {todays.length > 0 && <GoingOut posts={todays} />}
      {items.length > 0 && (
        <section className="ux-sec" data-testid="home-continue">
          <div className="ux-sech">
            <h2>{t('home.continue')}</h2>
            <span className="sp" />
            <a className="ux-link" href={href({ name: 'projects' })}>
              {t('home.allProjects')} <ArrowRight className="ico" />
            </a>
          </div>
          <div className="ux-tiles">
            {items
              .filter((i) => !runs.includes(i))
              .slice(0, 5)
              .map((i) => (
                <ContinueTile key={i.id} i={i} />
              ))}
          </div>
        </section>
      )}
      {!items.length && <Empty title={t('projects.empty')} hint={t('home.firstTime')} />}
    </>
  );
}

function HomeInbox({ items }: { items: InboxItem[] }) {
  const top = items.slice(0, 3);
  const rest = items.slice(3);
  const minutes = items.reduce((s, x) => s + (x.minutes ?? 1), 0);
  return (
    <section className="ux-sec" data-testid="home-inbox">
      <div className="ux-sech">
        <h2>{t('nav.inbox')}</h2>
        <span className="muted" data-testid="home-inbox-count">
          {t('home.inboxLine', { n: items.length, m: minutes })}
        </span>
        <span className="sp" />
        <a className="ux-link" href={href({ name: 'inbox' })} data-testid="home-open-inbox">
          {t('home.openInbox')} <ArrowRight className="ico" />
        </a>
      </div>
      <div className="card ux-hlist" data-testid="home-needs-you">
        {top.map((x, i) => (
          <HomeInboxRow key={x.key} x={x} first={i === 0} />
        ))}
        {rest.length > 0 && (
          <a className="ux-hmore" href={href({ name: 'inbox' })} data-testid="home-inbox-more">
            <span className="clamp1">{t('home.nMore', { n: rest.length, what: rest.map((x) => inboxTitle(x).toLocaleLowerCase()).join(', ') })}</span>
            <span className="sp" />
            <ChevronRight className="ico" />
          </a>
        )}
      </div>
    </section>
  );
}

function HomeInboxRow({ x, first }: { x: InboxItem; first: boolean }) {
  const th = (x.options ?? []).find((o) => o.cover)?.cover ?? x.project.thumb;
  const act =
    x.kind === 'review' ? t('home.act.fix') : x.kind === 'confirm' ? t('home.act.review') : x.code === 'inbox.spend' ? t('home.act.decide') : t('home.act.open');
  return (
    <div className="ux-hrow" data-testid="home-inbox-row" data-kind={x.kind}>
      <a href={inboxHref({ item: x.key })} className="ux-hrow-main">
        <InboxThumb x={x} src={th} />
        <div className="tx">
          <div className="clamp1">
            <b>{inboxTitle(x)}</b>
            {x.project.name && <span className="muted"> · {x.project.name}</span>}
          </div>
          <div className="muted clamp1">{inboxSub(x)}</div>
        </div>
      </a>
      <span className="muted num">{t('inbox.minutes', { n: x.minutes ?? 1 })}</span>
      {x.failure && x.project.id ? (
        <span className="ux-hacts">
          <FailureActions item={x.project.id} failure={x.failure} primary={false} />
        </span>
      ) : (
        <a className={`btn ${first ? 'soft' : ''}`} href={x.kind === 'confirm' && !x.href ? inboxHref({ item: x.key }) : itemTarget(x)} data-testid="home-inbox-act">
          {act}
        </a>
      )}
    </div>
  );
}

function Running({ runs }: { runs: HistoryItem[] }) {
  return (
    <section className="ux-sec" data-testid="live-lane">
      <div className="ux-sech">
        <h2>{t('home.running')}</h2>
        <span className="muted">{t('home.jobs', { n: runs.length })}</span>
      </div>
      <div className="ux-runs">
        {runs.slice(0, 3).map((i) => (
          <RunCard key={i.id} i={i} />
        ))}
      </div>
      {runs.length > 3 && (
        <a className="ux-link" href={href({ name: 'projects' })} style={{ marginTop: 8, display: 'inline-flex' }}>
          {t('home.nMoreRunning', { n: runs.length - 3 })}
        </a>
      )}
    </section>
  );
}

function RunCard({ i }: { i: HistoryItem }) {
  const s = itemStatus(i);
  const prog = Math.round((i.live?.progress ?? 0) * 100);
  const eta = i.live?.eta;
  return (
    <a className="card ux-run" href={projectHref(i.id)} data-testid="live-row">
      <Thumb src={i.thumb} className="ux-runth" />
      <div className="tx">
        <div className="row1">
          <b className="clamp1">{i.name}</b>
        </div>
        <div className="row1 muted">
          <span className="clamp1">{i.live?.message || i.live?.stage || ''}</span>
          <span className="sp" />
          {eta ? <span className="num">{t('time.minutes', { n: Math.max(1, Math.round(eta / 60)) })}</span> : null}
        </div>
        <div className={`bar ${s === 'you' ? 'you' : ''}`}>
          <i style={{ width: `${Math.max(4, prog)}%` }} />
        </div>
        <span className="sr">
          <StatusPill s={s} testId="live-state" />
        </span>
      </div>
    </a>
  );
}

function AllClear({ next }: { next: CalendarPost | null }) {
  const when = next ? (next.at.slice(0, 10) === today() ? t('home.todayAt', { time: fmtTime(next.at) }) : new Date(next.at).getTime() - Date.now() < 2 * 86400000 ? t('home.tomorrowAt', { time: fmtTime(next.at) }) : fmtAgo(new Date(next.at).getTime() / 1000)) : null;
  return (
    <div className="card ux-clear" data-testid="home-all-clear">
      <span className="ok">
        <Check className="ico" />
      </span>
      <span className="tx">
        <b>{t('home.allClear')}</b> {t('home.allClearLine')}
        {next && when ? ` ${t('home.nextPost', { when, platform: platformName(next.platform) })}` : ''}
      </span>
      <span className="sp" />
      <a className="ux-link" href={href({ name: 'calendar' })}>
        {t('home.calendar')} <ArrowRight className="ico" />
      </a>
    </div>
  );
}

function GoingOut({ posts }: { posts: CalendarPost[] }) {
  return (
    <section className="ux-sec" data-testid="home-today">
      <div className="ux-sech">
        <h2>{t('home.goingOut')}</h2>
        <span className="muted">{t('home.posts', { n: posts.length })}</span>
        <span className="sp" />
        <a className="ux-link" href={href({ name: 'calendar' })}>
          {t('home.calendar')} <ArrowRight className="ico" />
        </a>
      </div>
      <div className="card ux-strip">
        {posts.slice(0, 4).map((p) => (
          <a key={p.id} className="ux-post" href={postHref(p.id)} data-testid="home-post">
            <Thumb src={p.cover} className="ux-postth" />
            <span className="tx">
              <span className="row1">
                <b className="num">{fmtTime(p.at)}</b>
                <PlatformIcon id={p.platform.split(':')[0]} size={18} />
              </span>
              <span className="muted clamp1">{tk(`pub.state.${p.state}`)}</span>
            </span>
          </a>
        ))}
      </div>
    </section>
  );
}

function ContinueTile({ i }: { i: HistoryItem }) {
  const inbox = useInbox();
  const s = itemStatus(i);
  const asks = inbox.items.filter((x) => x.project.id === i.id && x.kind !== 'failed').length;
  const left = i.counts ? i.counts.total - Math.max(i.counts.done, i.counts.approved) : 0;
  const line =
    i.live?.state === 'running'
      ? `${t('status.running')}${i.live.message ? ` · ${i.live.message}` : ''}`
      : asks
        ? t('home.tile.asks', { n: asks })
        : left > 0 && i.counts.total
          ? t('home.sug.left', { n: left })
          : s === 'done'
            ? t('home.tile.ready')
            : fmtAgo(i.updated);
  const typeKey = `type.${i.type ?? 'other'}`;
  const typ = tk(typeKey) === typeKey ? t('type.other') : tk(typeKey);
  return (
    <a className="ux-tile" href={projectHref(i.id)} data-testid="project-card">
      <div className="ux-tileth">
        <TileThumb i={i} />
        <span className="ux-badge">
          {typ}
          {i.counts?.total ? ` · ${Math.max(i.counts.done, i.counts.approved)}/${i.counts.total}` : ''}
        </span>
      </div>
      <b className="clamp1">{i.name}</b>
      <span className="muted clamp1 ux-tline">
        <i className={`dot ${asks ? 'you' : s ?? ''}`} />
        {line}
      </span>
    </a>
  );
}

/** Project card used in 全部项目 (the whole card is the link). */
export function ProjectTile({ i, onContext }: { i: HistoryItem; onContext?: (e: React.MouseEvent) => void }) {
  const inbox = useInbox();
  const raw = itemStatus(i);
  // never 「已完成」 while the inbox holds a decision for it
  const s = raw === 'done' && inbox.items.some((x) => x.project.id === i.id && x.kind !== 'failed') ? 'you' : raw;
  const typeKey = `type.${i.type ?? 'other'}`;
  return (
    <a className="pcard" href={projectHref(i.id)} onContextMenu={onContext} data-testid="project-card">
      <TileThumb i={i} />
      <div className="t clamp1">{i.name}</div>
      <div className="meta">
        <span className="clamp1">
          {tk(typeKey) === typeKey ? t('type.other') : tk(typeKey)} · {fmtAgo(i.updated)}
        </span>
        <StatusPill s={s} />
      </div>
      <ArrowRight className="sr" />
    </a>
  );
}

const thumbCache = new Map<string, { covers: (string | null)[]; cells: ('rendering' | 'queued' | null)[]; video: string | null }>();

function TileThumb({ i }: { i: HistoryItem }) {
  const { client } = useEngine();
  const key = i.id + (i.updated ?? '');
  const [m, setM] = useState(thumbCache.get(key) ?? null);
  useEffect(() => {
    if (!client || m) return;
    let alive = true;
    client
      .clips(i.id)
      .then((d) => {
        const main = d.clips.filter((c) => !c.extra);
        const val = {
          covers: main.slice(0, 4).map((c) => c.cover),
          cells: main.slice(0, 4).map((c) => (c.state === 'running' ? 'rendering' : c.state === 'queued' ? 'queued' : null)) as ('rendering' | 'queued' | null)[],
          video: main.find((c) => c.files.length)?.files[0]?.path ?? null,
        };
        thumbCache.set(key, val);
        if (alive) setM(val);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client, i.id, key, m]);
  const covers = (m?.covers ?? []).filter(Boolean);
  if (m && covers.length >= 2 && (m.covers.length === covers.length || m.cells.some(Boolean))) return <Mosaic srcs={m.covers} cells={m.cells} />;
  const src = covers[0] ?? i.thumb;
  return <Thumb src={src} video={src ? null : m?.video} />;
}

