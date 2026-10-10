// The AI plan card (mockups/02-plan): one paragraph (the engine's summary, in the content language), the clips it
// will make, four numbers, the one thing to decide, "just say it" revisions, and ONE primary: start with a pilot.
import { useState } from 'react';
import { Check, FolderOpen, Plus, RotateCcw, Send, Sparkles, Square } from 'lucide-react';
import type { IntakeJob, IntakePlan } from '../../../shared/v04';
import { fmtClock, fmtMinutes, fmtMoney, getLang, has, t, type Lang } from '../i18n';
import { nameAsSample, planSentence } from '../lib/firstRun';
import { planProgressView, type PlanProgressView } from '../lib/planProgress';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { go, href } from '../lib/router';
import { platformName } from './Home';
import { Elapsed, More, Sk } from './kit';
import { failureReason } from './Failure';
import { emsg, errText } from './msg';
import { IS_LITE } from '../../../shared/edition';
import { useUi } from './ui';
import { AnsweredBy, FallbackNote } from './AiChip';
import { openReport } from '../support/Support';
import { orderPlatforms } from '../../../shared/platforms';

/** How many clips a sub-project makes: its count, its rows, one for a single video; null when the engine picks
 * the number at run time (a segment planner or a focus with no count in the request). */
function clipCount(p: IntakePlan['projects'][number]): number | null {
  if (p.items?.count) return p.items.count;
  if (p.items?.rows?.length) return p.items.rows.length;
  return !p.items || p.items.method === 'single' ? 1 : null;
}

export function planFacts(plan: IntakePlan) {
  const projects = plan.projects ?? [];
  const counts = projects.map(clipCount);
  const clips = counts.some((n) => n == null) ? null : counts.reduce<number>((n, c) => n + (c ?? 0), 0);
  // sizes only when the plan names them (aspects); otherwise each platform's own size is used
  const sizes = Math.max(0, ...projects.map((p) => (p.params?.aspects as string[] | undefined)?.length ?? 0));
  const plats = [...new Set(orderPlatforms(projects.flatMap((p) => (p.params?.platforms as string[] | undefined) ?? [])).map(platformName))];
  const wall = plan.estimate?.wall_min ?? projects.reduce((n, p) => n + (p.estimate?.wall_min ?? 0), 0);
  const usd = plan.estimate?.api_usd ?? projects.reduce((n, p) => n + (p.estimate?.api_usd ?? 0), 0);
  return { clips, sizes, plats, wall, usd };
}

const HTML_LANG = { en: 'en', zh: 'zh-CN', fr: 'fr' } as const;
const htmlLang = (code: string) => (code === 'zh' ? 'zh-CN' : code);

/** The plan's paragraph: the engine's, tagged with the language it is written in (``summary_lang``), or - for a
 * plan made without AI whose template is not in her UI language - the UI's own sentence (``own``, no tag). */
export function summaryView(plan: IntakePlan, ui: Lang): { own: boolean; lang?: string } {
  const noAi = Boolean(plan.planner?.fallback);
  const uiCode = ui === 'zh-CN' ? 'zh' : ui;
  const own = noAi && (plan.summary_lang ? plan.summary_lang !== uiCode : ui !== 'zh-CN');
  if (own) return { own };
  return { own, lang: plan.summary_lang ? htmlLang(plan.summary_lang) : 'zh-CN' }; // older plans: the zh template
}

/** The "things for you to decide" lines: the planner's questions, then its risks. A coded line is worded by the UI
 * (no lang of its own); the planner's free text carries the language it was written in (``plan.ui_lang``). */
export function decideLines(plan: IntakePlan): { text: string; lang?: string }[] {
  const lang = plan.ui_lang ? HTML_LANG[plan.ui_lang] : undefined;
  return [
    ...(plan.questions ?? []).map((q) =>
      q.code ? { text: emsg({ code: q.code, params: q.params, message: q.text, message_zh: q.text }) } : { text: q.text, lang },
    ),
    ...(plan.risks ?? []).map((r) => (typeof r === 'string' ? { text: r, lang } : { text: emsg(r) })),
  ];
}

const STATE_KEY = {
  done: 'plan.step.state.done',
  current: 'plan.step.state.current',
  pending: 'plan.step.state.pending',
  skipped: 'plan.step.state.skipped',
} as const;

/** The engine's current stage (a bar when it knows how far it is) and the plan's steps: done ✓ / now / to come. */
function PlanStage({ view, stage }: { view: PlanProgressView; stage: string }) {
  const pct = view.fraction == null ? null : Math.round(view.fraction * 1000) / 10;
  return (
    <div className="planstage" data-testid="plan-progress" data-stage={stage}>
      <div className="now">
        <b data-testid="plan-progress-label" title={view.label}>
          {view.label}
        </b>
        {view.detail && (
          <span className="muted tnum" data-testid="plan-progress-detail">
            · {view.detail}
          </span>
        )}
      </div>
      {pct == null ? (
        <div className="bar indet" aria-hidden>
          <i />
        </div>
      ) : (
        <div className="bar" role="progressbar" aria-label={view.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} data-testid="plan-progress-bar">
          <i style={{ width: `${pct}%` }} />
        </div>
      )}
      <ol className="plansteps">
        {view.steps.map((s) => (
          <li key={s.id} className={s.state} data-testid={`plan-step-${s.id}`} data-state={s.state}>
            <span className="mk" role="img" aria-label={t(STATE_KEY[s.state])}>
              {s.state === 'done' ? <Check className="ico" /> : s.state === 'current' ? <i className="dot run" /> : s.state === 'skipped' ? '–' : <i className="dot" />}
            </span>
            <span>{s.label}</span>
            {s.note && <span className="muted small">· {s.note}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** ``onApplied``: where she goes once the plan is made into projects (the control room keeps her there and selects
 * the new project); without it the first project's page opens. */
export function PlanCard({ job, jobId, onRevise, onRetry, onReset, onStarted, onApplied, sample = false }: { job: IntakeJob | null; jobId: string; onRevise: (s: string) => void; onRetry: () => void; onReset: () => void; onStarted: () => void; onApplied?: (dirs: string[]) => void; sample?: boolean }) {
  const { client } = useEngine();
  const { reload } = useHistory();
  const ui = useUi();
  const [ask, setAsk] = useState('');
  const [starting, setStarting] = useState(false);
  const plan = job?.plan ?? null;
  const running = !job || job.state === 'running';

  const stop = async () => {
    try {
      await client?.stopIntake(jobId);
    } catch {
      // already finished: going back to the composer is still right
    }
    onReset();
  };
  if (job?.state === 'stopped') return null;
  if (job?.state === 'needs') return <NeedsCard job={job} jobId={jobId} onReset={onReset} />;
  if (job?.state === 'error') {
    const code = job.error_code ?? 'unknown';
    const why = plainError(job.error);
    const known = code !== 'unknown' && has(`fail.reason.${code}`);
    return (
      <div className="card plan" data-testid="plan-card" data-state="error">
        <div className="row">
          <i className="dot error" />
          <b style={{ fontWeight: 500 }}>{t('plan.failed')}</b>
        </div>
        <p className="muted" data-testid="plan-failed-reason">
          {known || !why ? failureReason({ state: 'failed', code, provider: job.error_provider ?? null, error: job.error ?? '', at: null }) : t('plan.failedWhy', { why })}
        </p>
        {job.error && (
          <details className="muted small" data-testid="plan-failed-details">
            <summary>{t('plan.details')}</summary>
            <div>
              {t('plan.failedDetail')}: {why || job.error}
            </div>
            <span className="mono">{job.error}</span>
          </details>
        )}
        <div className="row">
          <button className="btn primary" onClick={onRetry} data-testid="plan-retry">
            {t('c.retry')}
          </button>
          <button className="btn" onClick={onReset} data-testid="plan-start-over">
            <RotateCcw className="ico" />
            {t('plan.discard')}
          </button>
          <button className="btn ghost" onClick={() => openReport({ kind: 'job', code, message: job.error || 'plan failed' })} data-testid="plan-report">
            {t('sup.rp.report')}
          </button>
        </div>
      </div>
    );
  }
  if (!plan || (running && !plan)) {
    const view = planProgressView(job?.progress);
    return (
      <div className="card plan" data-testid="plan-card" aria-busy="true">
        <div className="planprog">
          <Sparkles className="ico" />
          <b style={{ fontWeight: 500 }}>{job?.step === 'revise' ? t('plan.revising') : job?.step === 'plan' ? t('plan.planning') : t('plan.reading')}</b>
          <span className="muted">
            · <Elapsed since={job?.started ?? null} testId="plan-elapsed" />
          </span>
          <span className="sp" />
          <button className="btn ghost" onClick={() => void stop()} data-testid="plan-stop">
            <Square className="ico" />
            {t('plan.stop')}
          </button>
        </div>
        {view ? (
          <PlanStage view={view} stage={job?.progress?.stage ?? ''} />
        ) : (
          <>
            {job?.started && Date.now() / 1000 - job.started > 45 && <p className="muted small">{t('plan.slow')}</p>}
            <div className="col" style={{ marginTop: 16 }}>
              <Sk h={16} />
              <Sk w="80%" h={16} />
              <div className="outs plan" style={{ padding: 0, margin: '16px 0 0', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="sk" style={{ aspectRatio: '3/4' }} />
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    );
  }
  const f = planFacts(plan);
  const noAi = Boolean(plan.planner?.fallback);
  const rows = plan.projects.flatMap((p) => (p.items?.rows ?? []).map((r) => ({ p, r }))).slice(0, 8);
  const video = plan.materials.find((m) => m.kind === 'video');
  const questions = decideLines(plan);
  const sum = summaryView(plan, getLang());
  const start = async () => {
    if (!client) return;
    setStarting(true);
    try {
      // the sample's projects are named as the sample (the engine marks them; the desk labels and can delete them)
      const r = await client.applyIntake(jobId, sample && plan ? { run: true, plan: nameAsSample(plan, t('sample.projectName')) } : { run: true });
      ui.toast(t('plan.started'));
      sessionStorage.removeItem('v4.composer');
      onStarted();
      reload();
      const first = r.projects[0]?.dir;
      if (onApplied) onApplied(r.projects.map((x) => x.dir));
      else if (first) {
        // the new project shows up in the history list a moment later
        for (let i = 0; i < 10; i++) {
          const h = await client.history();
          const hit = h.items.find((x) => x.dir === first);
          if (hit) {
            go({ name: 'project', id: hit.id });
            break;
          }
          await new Promise((res) => setTimeout(res, 300));
        }
      }
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setStarting(false);
    }
  };
  return (
    <div className="card plan" data-testid="plan-card" aria-busy={running}>
      <div className="row">
        <b style={{ fontWeight: 500, fontSize: 15 }}>{noAi ? t('plan.titleRules') : t('plan.title')}</b>
        <span className="muted" data-testid="plan-took">· {t('plan.took', { n: plan.materials.length, s: Math.max(1, Math.round(job?.seconds ?? plan.planner?.seconds ?? 1)) })}</span>
        <span className="sp" />
        {running && <span className="muted">{t('plan.revising')}</span>}
      </div>
      <p className="lead" lang={sum.lang} data-testid="plan-summary">
        {sum.own ? planSentence(plan, platformName) : plan.summary_zh}
      </p>
      {noAi && !plan.planner?.failure && (
        <p className="muted small" style={{ marginTop: -4 }} data-testid="plan-no-ai">
          {t('plan.noAi')}
        </p>
      )}
      {plan.planner?.provider && !(noAi && !plan.planner.failure) && (
        <AnsweredBy provider={plan.planner.fallback ? 'rules' : plan.planner.provider} fallback={plan.planner.provider_fallback} kind="planned" testId="plan-answered-by" />
      )}
      {plan.planner?.fallback && plan.planner.failure && (plan.planner.routed ?? plan.planner.provider) && <FallbackNote rulesFrom={plan.planner.routed ?? plan.planner.provider} />}
      {rows.length > 0 && (
        <div className="outs" data-testid="plan-rows">
          {rows.slice(0, 4).map(({ r }, i) => {
            const rg = r.params?.range;
            const len = rg ? rg[1] - rg[0] : null;
            return (
              <div key={r.id}>
                <div className="th">
                  {video && rg ? (
                    <video src={`${window.desk.mediaUrl(video.path)}#t=${rg[0] + 1}`} muted preload="metadata" playsInline />
                  ) : (
                    <div className="ph-thumb" style={{ height: '100%' }}>
                      {t('plan.clipN', { n: i + 1 })}
                    </div>
                  )}
                  {rg && (
                    <span className="tl st" style={{ background: 'rgba(0,0,0,.55)', color: '#fff', borderColor: 'transparent' }}>
                      {t('plan.source', { t: fmtClock(rg[0]) })}
                    </span>
                  )}
                  {len !== null && <span className="dur num">{fmtClock(len)}</span>}
                </div>
                <div className="t clamp2" lang="zh-CN">
                  {r.params?.title ?? t('plan.clipN', { n: i + 1 })}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="facts" data-testid="plan-facts">
        <div>
          <span>{t('plan.make')}</span>
          <b data-testid="plan-make">{f.clips == null ? t('plan.makeAuto') : f.sizes ? t('plan.makeVal', { n: f.clips, a: f.sizes }) : t('plan.makeClips', { n: f.clips })}</b>
        </div>
        <div>
          <span>{t('plan.to')}</span>
          <b className="clamp1">{f.plats.join(' · ') || '–'}</b>
        </div>
        <div>
          <span>{t('plan.time')}</span>
          <b>{fmtMinutes(f.wall)}</b>
        </div>
        <div>
          <span>{t('plan.cost')}</span>
          <b>{f.usd > 0 ? t('plan.costAbout', { v: fmtMoney(f.usd) }) : t('plan.costFree')}</b>
        </div>
      </div>
      {questions.length > 0 && (
        <div className="decide" data-testid="plan-decide">
          <i className="dot you" />
          <div>
            <b style={{ fontWeight: 500 }}>{t('plan.decide', { n: questions.length })}</b>
            {questions.map((q, i) => (
              <div key={i} className="muted" lang={q.lang}>
                {q.text}
              </div>
            ))}
          </div>
        </div>
      )}
      {(plan.warnings ?? []).length > 0 && (
        <div className="note" style={{ marginTop: 12 }}>
          {plan.warnings.join(' ')}
        </div>
      )}
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          if (ask.trim()) {
            onRevise(ask.trim());
            setAsk('');
          }
        }}
      >
        <input className="inp" value={ask} onChange={(e) => setAsk(e.target.value)} placeholder={t('plan.reviseHint')} disabled={running} data-testid="plan-revise" />
        {ask.trim() && (
          <button className="btn" type="submit" disabled={running} data-testid="plan-revise-send">
            <Send className="ico" />
            {t('plan.revise')}
          </button>
        )}
        <button className="btn primary lg" type="button" onClick={() => void start()} disabled={running || starting} data-testid="plan-start">
          {starting ? t('plan.starting') : t('plan.start')}
        </button>
      </form>
      <More summary={t('plan.advanced')} testId="plan-advanced">
        <p className="muted">{t('plan.advancedHint')}</p>
        <div className="row">
          <a className="btn" href={href({ name: 'new' })}>
            {t('plan.formBatch')}
          </a>
          <a className="btn" href={href({ name: 'new', mode: 'recording' })}>
            {t('plan.formRecording')}
          </a>
          <span className="sp" />
          <button className="btn ghost" onClick={onReset}>
            <RotateCcw className="ico" />
            {t('plan.discard')}
          </button>
        </div>
        <div className="kv">
          {plan.projects.map((p) => (
            <div key={p.id} style={{ display: 'contents' }}>
              <span>{p.recipe_label ?? p.recipe}</span>
              <span>
                {p.recipe} · {JSON.stringify(p.params)}
              </span>
            </div>
          ))}
          {plan.planner?.fallback && (
            <>
              <span>{t('plan.warning')}</span>
              <span>{t('plan.byRules')}</span>
            </>
          )}
        </div>
      </More>
    </div>
  );
}

/** The engine's error in words she can read: no "vstudio.intake plan exited 1:", no exception class, no paths. */
export function plainError(err: string | null | undefined): string {
  let s = String(err ?? '').trim();
  s = s.replace(/^[\w.]+ \w+ exited -?\d+:\s*/, '').replace(/^(?:[A-Z]\w*(?:Error|Exception)|CliError):\s*/, '');
  s = s.replace(/(?:\/(?:Users|home|private|var|tmp|Volumes|opt|Applications)\/|[A-Za-z]:\\)[^\s'"]*/g, '…');
  return s.length > 240 ? `${s.slice(0, 239)}…` : s;
}

/** A request that waits for something only she can give (``needs``: her recordings, her Notion pages): what it
 * needs in words, a drop target + Add files / a folder, a box for page links, and "Plan without it" when it can. */
function NeedsCard({ job, jobId, onReset }: { job: IntakeJob; jobId: string; onReset: () => void }) {
  const { client } = useEngine();
  const ui = useUi();
  const [files, setFiles] = useState<string[]>([]);
  const [links, setLinks] = useState('');
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const needs = job.needs ?? job.plan?.needs ?? [];
  const footage = needs.some((n) => n.code === 'intake.need.footage');
  const plan = job.plan;
  const add = async (kind: 'files' | 'folder') => {
    const got = kind === 'files' ? await window.desk.openFiles('any') : [await window.desk.openFolder()].filter((x): x is string => !!x);
    if (got.length) setFiles((f) => [...new Set([...f, ...got])]);
  };
  const send = async () => {
    if (!client || busy || !(files.length || links.trim())) return;
    setBusy(true);
    try {
      await client.addToIntake(jobId, files, links.trim() || undefined);
      ui.toast(t('plan.needs.added'));
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(false);
    }
  };
  const goOn = async () => {
    if (!client || busy) return;
    setBusy(true);
    try {
      await client.goOnIntake(jobId);
      ui.toast(t('plan.needs.going'));
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card plan" data-testid="plan-card" data-state="needs">
      <div className="row">
        <i className="dot you" />
        <b style={{ fontWeight: 500 }}>{t('plan.needs.title')}</b>
      </div>
      {needs.map((n, i) => (
        <p key={i} className="lead" data-testid="plan-need" data-code={n.code}>
          {emsg(n)}
        </p>
      ))}
      <div
        className={`ux-needs-drop ${over ? 'over' : ''}`}
        data-own-drop
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const paths = [...e.dataTransfer.files].map((f) => window.desk.pathForFile?.(f) ?? '').filter(Boolean);
          if (paths.length) setFiles((f) => [...new Set([...f, ...paths])]);
          if (paths.length && IS_LITE) void window.desk.grantAccess?.(paths).catch(() => undefined);
        }}
        data-testid="plan-need-drop"
      >
        <span className="muted">{t('plan.needs.drop')}</span>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn" onClick={() => void add('files')} data-testid="plan-need-add">
            <Plus className="ico" />
            {t('plan.needs.add')}
          </button>
          <button className="btn ghost" onClick={() => void add('folder')} data-testid="plan-need-folder">
            <FolderOpen className="ico" />
            {t('plan.needs.addFolder')}
          </button>
        </div>
        {files.length > 0 && (
          <div className="muted small" data-testid="plan-need-files">
            {files.map((f) => f.replace(/[\\/]+$/, '').split(/[\\/]/).pop()).join(' · ')}
          </div>
        )}
      </div>
      {!footage && (
        <textarea className="inp" rows={2} style={{ width: '100%', resize: 'vertical' }} value={links} onChange={(e) => setLinks(e.target.value)} placeholder={t('plan.needs.paste')} data-testid="plan-need-links" />
      )}
      {plan && plan.projects?.length > 0 && !footage && (
        <p className="muted small" lang={plan.summary_lang === 'zh' ? 'zh-CN' : plan.summary_lang} data-testid="plan-need-summary">
          {plan.summary_zh}
        </p>
      )}
      <div className="row">
        <button className="btn primary" onClick={() => void send()} disabled={busy || !(files.length || links.trim())} data-testid="plan-need-send">
          {t('plan.needs.send')}
        </button>
        {!footage && (
          <button className="btn" onClick={() => void goOn()} disabled={busy} data-testid="plan-need-go-on">
            {t('plan.needs.goOn')}
          </button>
        )}
        <span className="sp" />
        <button className="btn ghost" onClick={onReset} data-testid="plan-start-over">
          <RotateCcw className="ico" />
          {t('plan.discard')}
        </button>
      </div>
    </div>
  );
}
