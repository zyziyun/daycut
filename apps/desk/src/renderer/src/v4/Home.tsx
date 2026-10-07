// Home = the composer: say what to make + drop any files / folders -> AI plan card -> start (a pilot of 1 first).
// Below it: 进行中 (live runs), 需要你 (top of the inbox), 今天要发 (today's calendar), recent projects.
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, File as FileIcon, FileText, Folder, Image as ImageIcon, Music, Plus, Sparkles, Video, X } from 'lucide-react';
import type { HistoryItem } from '../../../shared/v02';
import type { IntakeJob } from '../../../shared/v04';
import { fmtAgo, fmtTime, t, tk, type MessageKey } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { href } from '../lib/router';
import { itemStatus } from '../lib/status';
import { Empty, Mosaic, Sk, StatusPill, Thumb } from './kit';
import { PlanCard } from './PlanCard';
import { inboxTitle } from './Inbox';
import { useUi } from './ui';
import { ProviderChip } from './AiChip';

const IDEAS: [MessageKey, MessageKey][] = [
  ['home.idea1', 'home.idea1Prompt'],
  ['home.idea2', 'home.idea2Prompt'],
  ['home.idea3', 'home.idea3Prompt'],
  ['home.idea4', 'home.idea4Prompt'],
  ['home.idea5', 'home.idea5Prompt'],
];
const LANES = 3;

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

/** Remember the last request + files so a reload never loses what she typed. */
const DRAFT = 'v4.composer';

export function Home() {
  const { client } = useEngine();
  const ui = useUi();
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
  const [platforms, setPlatforms] = useState<string[]>([]);
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const { data: recent } = useLoad((c) => c.recentPrompts(), [jobId]);

  useEffect(() => {
    sessionStorage.setItem(DRAFT, JSON.stringify({ prompt, files, job: jobId }));
  }, [prompt, files, jobId]);
  useEffect(() => {
    void window.desk.getSettings().then((s) => setPlatforms(s.defaultPlatforms ?? ['xiaohongshu:vertical']));
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

  const submit = async () => {
    if (!client || busy || (!prompt.trim() && !files.length)) return;
    setBusy(true);
    try {
      const r = await client.startIntake(prompt.trim(), files);
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

  const planning = !!jobId;
  return (
    <div className="scroll" data-testid="home">
      <div className="pg">
        {!planning && <div className="hello">{t('home.title')}</div>}
        <div
          className={`composer ${over ? 'over' : ''}`}
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
            placeholder={t('home.placeholder')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void submit();
              }
            }}
            readOnly={planning && job?.state === 'running'}
            rows={planning ? 2 : 3}
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
            <>
              {!files.length && <div className="drop">{t('home.drop')}</div>}
              <div className="foot">
                <button className="btn ghost" onClick={() => void addFiles('files')} data-testid="add-files">
                  <Plus className="ico" />
                  {t('home.addFiles')}
                </button>
                <button className="btn ghost" onClick={() => void addFiles('folder')}>
                  <Folder className="ico" />
                  {t('home.addFolder')}
                </button>
                <ProviderChip task="plan" testId="composer-provider-chip" />
                <span className="muted clamp1">{t('home.publishTo', { p: platforms.map(platformName).filter((x, i, a) => a.indexOf(x) === i).join(' · ') })}</span>
                <span className="sp" />
                <button className="btn primary lg" disabled={busy || (!prompt.trim() && !files.length)} onClick={() => void submit()} data-tip="⌘↵" data-testid="make-plan">
                  <Sparkles className="ico" />
                  {t('home.submit')}
                </button>
              </div>
            </>
          )}
        </div>
        {!planning && (
          <>
            <div className="ideas">
              {IDEAS.map(([k, pk]) => (
                <button key={k} className="chip" onClick={() => setPrompt(t(pk))}>
                  {t(k)}
                </button>
              ))}
            </div>
            {(recent?.length ?? 0) > 0 && (
              <div className="recentp" data-testid="recent-prompts">
                <span className="faint">{t('home.recentPrompts')}</span>
                {recent!.slice(0, 4).map((r) => (
                  <button key={r.id} className="chip" onClick={() => setPrompt(r.prompt)} title={r.prompt}>
                    <span className="clamp1" style={{ maxWidth: 220 }}>{r.prompt}</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}
        {planning && <PlanCard job={job} jobId={jobId!} onRevise={revise} onReset={reset} onStarted={started} />}
        {!planning && <Below />}
      </div>
    </div>
  );
}

function Below() {
  const { data, live } = useHistory();
  const inbox = useInbox();
  const { data: cal } = useLoad((c) => c.calendar(new Date().toISOString().slice(0, 10)), []);
  const items = data?.items ?? [];
  const today = new Date().toISOString().slice(0, 10);
  const todays = (cal?.posts ?? []).filter((p) => p.at.slice(0, 10) === today);
  const runs = live.filter((i) => i.live?.state === 'running' || i.live?.state === 'waiting').slice(0, LANES);
  const recent = items.filter((i) => !runs.includes(i)).slice(0, 4);
  if (!data) {
    return (
      <div className="sec">
        <Sk w={160} h={18} />
        <div className="runlane" style={{ marginTop: 12 }}>
          {[0, 1, 2].map((i) => (
            <Sk key={i} h={80} r={12} />
          ))}
        </div>
      </div>
    );
  }
  return (
    <>
      <section className="sec" data-testid="live-lane">
        <div className="sech">
          <h2>{t('home.inProgress')}</h2>
          <span className="n muted">{t('home.runningCount', { n: runs.length })}</span>
        </div>
        <div className="runlane">
          {runs.map((i) => (
            <RunCard key={i.id} i={i} />
          ))}
          {runs.length < LANES && (
            <div className="card runcard" style={{ borderStyle: 'dashed' }}>
              <div className="th ph-thumb" style={{ width: 56 }}>
                <Plus className="ico" />
              </div>
              <div>
                <b>{t('home.idle')}</b>
                <span className="muted">{t('home.idleHint', { n: LANES - runs.length })}</span>
              </div>
            </div>
          )}
        </div>
      </section>
      <section className="sec two">
        <div>
          <div className="sech">
            <h2>{t('home.needsYou')}</h2>
            <span className="sp" />
            {inbox.items.length > 0 && (
              <a className="link" href={href({ name: 'inbox' })}>
                {t('home.allN', { n: inbox.items.length })}
              </a>
            )}
          </div>
          <div className="card mini" data-testid="home-needs-you">
            {inbox.items.slice(0, 3).map((x) => (
              <a key={x.key} href={x.project.id ? href({ name: 'project', id: x.project.id }) : href({ name: 'inbox' })}>
                <i className="dot you" />
                <span className="sp clamp1">{t('home.needsLine', { project: x.project.name ?? '', what: inboxTitle(x) })}</span>
                <span className="muted num">{t('home.minutes', { n: x.minutes ?? 1 })}</span>
              </a>
            ))}
            {!inbox.items.length && <div className="li muted">{t('home.nothingNeeds')}</div>}
          </div>
        </div>
        <div>
          <div className="sech">
            <h2>{t('home.today')}</h2>
            <span className="sp" />
            <a className="link" href={href({ name: 'calendar' })}>
              {t('home.calendar')}
            </a>
          </div>
          <div className="card mini" data-testid="home-today">
            {todays.slice(0, 3).map((p) => (
              <a key={p.id} href={href({ name: 'calendar' })}>
                <i className={`dot ${p.state === 'posted' ? 'done' : p.state === 'ready' ? 'done' : 'run'}`} />
                <span className="sp clamp1">
                  <span className="num">{fmtTime(p.at)}</span> {platformName(p.platform)} · {p.title}
                </span>
                <span className="muted">{tk(`pub.state.${p.state}`)}</span>
              </a>
            ))}
            {!todays.length && <div className="li muted">{t('home.nothingToday')}</div>}
          </div>
        </div>
      </section>
      <section className="sec">
        <div className="sech">
          <h2>{t('home.recent')}</h2>
          <span className="sp" />
          <a className="link" href={href({ name: 'projects' })}>
            {t('home.allProjects')}
          </a>
        </div>
        {recent.length ? (
          <div className="pgrid">
            {recent.map((i) => (
              <ProjectTile key={i.id} i={i} />
            ))}
          </div>
        ) : (
          <Empty title={t('projects.empty')} hint={t('home.firstTime')} />
        )}
      </section>
    </>
  );
}

function RunCard({ i }: { i: HistoryItem }) {
  const s = itemStatus(i);
  const prog = Math.round((i.live?.progress ?? 0) * 100);
  return (
    <a className="card runcard" href={href({ name: 'project', id: i.id })} data-testid="live-row">
      <Thumb src={i.thumb} />
      <div style={{ minWidth: 0 }}>
        <b className="clamp1">{i.name}</b>
        <div className="row">
          <StatusPill s={s} testId="live-state" />
          {i.live?.message && <span className="muted clamp1">{i.live.message}</span>}
        </div>
        <div className={`bar ${s === 'you' ? 'you' : ''}`}>
          <i style={{ width: `${Math.max(4, prog)}%` }} />
        </div>
      </div>
    </a>
  );
}

/** Project card used on Home and in 全部项目 (the whole card is the link). */
export function ProjectTile({ i, onContext }: { i: HistoryItem; onContext?: (e: React.MouseEvent) => void }) {
  const inbox = useInbox();
  const raw = itemStatus(i);
  // never 「已完成」 while the inbox holds a decision for it
  const s = raw === 'done' && inbox.items.some((x) => x.project.id === i.id && x.kind !== 'failed') ? 'you' : raw;
  const typeKey = `type.${i.type ?? 'other'}`;
  return (
    <a className="pcard" href={href({ name: 'project', id: i.id })} onContextMenu={onContext} data-testid="project-card">
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
