// The AI plan card (mockups/02-plan): one paragraph (the engine's summary, in the content language), the clips it
// will make, four numbers, the one thing to decide, "just say it" revisions, and ONE primary: start with a pilot.
import { useState } from 'react';
import { RotateCcw, Send, Sparkles, Square } from 'lucide-react';
import type { IntakeJob, IntakePlan } from '../../../shared/v04';
import { fmtClock, fmtMinutes, fmtMoney, t } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { go, href } from '../lib/router';
import { platformName } from './Home';
import { Elapsed, More, Sk } from './kit';
import { failureReason } from './Failure';
import { emsg } from './msg';
import { useUi } from './ui';
import { AnsweredBy, FallbackNote } from './AiChip';
import { openReport } from '../support/Support';

export function planFacts(plan: IntakePlan) {
  const projects = plan.projects ?? [];
  const clips = projects.reduce((n, p) => n + (p.items?.count ?? p.items?.rows?.length ?? 1), 0);
  const sizes = Math.max(1, ...projects.map((p) => (p.params?.aspects as string[] | undefined)?.length ?? 1));
  const plats = [...new Set(projects.flatMap((p) => (p.params?.platforms as string[] | undefined) ?? []).map(platformName))];
  const wall = plan.estimate?.wall_min ?? projects.reduce((n, p) => n + (p.estimate?.wall_min ?? 0), 0);
  const usd = plan.estimate?.api_usd ?? projects.reduce((n, p) => n + (p.estimate?.api_usd ?? 0), 0);
  return { clips, sizes, plats, wall, usd };
}

export function PlanCard({ job, jobId, onRevise, onReset, onStarted }: { job: IntakeJob | null; jobId: string; onRevise: (s: string) => void; onReset: () => void; onStarted: () => void }) {
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
  if (job?.state === 'error') {
    return (
      <div className="card plan" data-testid="plan-card">
        <div className="row">
          <i className="dot error" />
          <b style={{ fontWeight: 500 }}>{t('plan.failed')}</b>
        </div>
        <p className="muted" data-testid="plan-failed-reason">
          {failureReason({ state: 'failed', code: job.error_code ?? 'unknown', provider: job.error_provider ?? null, error: job.error ?? '', at: null })}
        </p>
        {job.error && (
          <details className="muted small">
            <summary>{t('plan.details')}</summary>
            <span className="mono">{job.error}</span>
          </details>
        )}
        <div className="row">
          <button className="btn" onClick={onReset}>
            <RotateCcw className="ico" />
            {t('plan.discard')}
          </button>
          <button className="btn ghost" onClick={() => openReport({ kind: 'job', code: job.error_code ?? 'unknown', message: job.error || 'plan failed' })} data-testid="plan-report">
            {t('sup.rp.report')}
          </button>
        </div>
      </div>
    );
  }
  if (!plan || (running && !plan)) {
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
      </div>
    );
  }
  const f = planFacts(plan);
  const rows = plan.projects.flatMap((p) => (p.items?.rows ?? []).map((r) => ({ p, r }))).slice(0, 8);
  const video = plan.materials.find((m) => m.kind === 'video');
  const questions = [
    ...(plan.questions ?? []).map((q) => (q.code ? emsg({ code: q.code, params: q.params, message: q.text, message_zh: q.text }) : q.text)),
    ...(plan.risks ?? []).map((r) => emsg(r)),
  ];
  const start = async () => {
    if (!client) return;
    setStarting(true);
    try {
      const r = await client.applyIntake(jobId, { run: true });
      ui.toast(t('plan.started'));
      sessionStorage.removeItem('v4.composer');
      onStarted();
      reload();
      const first = r.projects[0]?.dir;
      if (first) {
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
      ui.toast((e as Error).message, { error: true });
    } finally {
      setStarting(false);
    }
  };
  return (
    <div className="card plan" data-testid="plan-card" aria-busy={running}>
      <div className="row">
        <b style={{ fontWeight: 500, fontSize: 15 }}>{t('plan.title')}</b>
        <span className="muted">· {t('plan.read', { n: plan.materials.length, s: Math.max(1, Math.round(plan.planner?.seconds ?? 1)) })}</span>
        <span className="sp" />
        {running && <span className="muted">{t('plan.revising')}</span>}
      </div>
      <p className="lead" lang="zh-CN" data-testid="plan-summary">
        {plan.summary_zh}
      </p>
      {plan.planner?.provider && (
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
          <b>{t('plan.makeVal', { n: f.clips, a: f.sizes })}</b>
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
              <div key={i} className="muted" lang="zh-CN">
                {q}
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
