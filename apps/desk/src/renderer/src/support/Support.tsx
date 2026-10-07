// Feedback + problem reports (renderer). Nothing here sends anything: "Send feedback" and "Report this problem"
// build a prefilled GitHub page from text she has just read, and open it in the browser; she posts it there.
//   openFeedback()        Help › Send feedback…, Settings › Help and diagnostics, the small link in empty states
//   openReport(problem)   a failed job (FailureActions), the problem bar (app / window / engine crashed)
// <SupportLayer/> (mounted once in App) owns the two sheets, the problem bar and the renderer error hook.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ExternalLink, MessageSquarePlus } from 'lucide-react';
import { diagnostics, discussionUrl, feedbackBody, issueUrl, okEmail, problemReport, titleOf, type Problem, type SupportEnv } from '../../../shared/support';
import { t, tk } from '../i18n';
import { Segmented, Sheet } from '../settings/kit';
import { useUi } from '../v4/ui';
import '../settings/settings.css';
import './support.css';

type ReportInput = Pick<Problem, 'kind' | 'code' | 'message'> & { stack?: string; id?: string };
type Req = { what: 'feedback'; kind?: 'idea' | 'bug' } | { what: 'report'; problem: ReportInput; asked?: string };

const listeners = new Set<(r: Req) => void>();
const emit = (r: Req) => listeners.forEach((f) => f(r));

/** Open the feedback form (Help menu, Settings, empty states). */
export function openFeedback(kind?: 'idea' | 'bug') {
  emit({ what: 'feedback', kind });
}

/** Open "Report this problem" for one problem (a failed job, a crash). `asked`: what she had asked for, if known. */
export function openReport(problem: ReportInput, asked?: string) {
  emit({ what: 'report', problem, asked });
}

async function loadEnv(): Promise<{ env: SupportEnv; recent: Problem[] }> {
  const [env, ps] = await Promise.all([window.desk.support.env(), window.desk.support.problems()]);
  return { env, recent: ps.recent };
}

/** A stable "show this error" (the UI context changes often; effects should not re-run for it). */
function useShowError() {
  const ui = useUi();
  const ref = useRef(ui);
  ref.current = ui;
  return useCallback((e: unknown) => ref.current.toast(e instanceof Error ? e.message : String(e), { error: true }), []);
}

const IGNORE = /ResizeObserver loop|Script error\.?$|AbortError|The play\(\) request was interrupted/;

export function SupportLayer() {
  const showError = useShowError();
  const [req, setReq] = useState<Req | null>(null);
  const [bar, setBar] = useState<Problem | null>(null);
  useEffect(() => {
    const f = (r: Req) => setReq(r);
    listeners.add(f);
    const offs = [
      window.desk.on('support:open', () => setReq({ what: 'feedback' })),
      window.desk.on('support:problem', (p) => (p as Problem).kind !== 'job' && setBar(p as Problem)),
    ];
    void window.desk.support
      .problems()
      .then((r) => setBar(r.items.find((p) => p.kind !== 'job') ?? null))
      .catch(showError);
    // reporting an error must not raise another one: a failed report goes to the console, never back into the log
    const send = (p: Parameters<typeof window.desk.support.report>[0]) => void window.desk.support.report(p).catch((e: Error) => console.error('[support] report failed', e));
    // renderer errors -> the problem log (redacted in main); the bar offers to report them
    const onErr = (e: ErrorEvent) => {
      const msg = e.message || String(e.error ?? '');
      if (!msg || IGNORE.test(msg)) return;
      send({ kind: 'renderer', code: (e.error as Error)?.name ?? 'Error', message: msg.slice(0, 2000), stack: (e.error as Error)?.stack?.slice(0, 8000) });
    };
    const onRej = (e: PromiseRejectionEvent) => {
      const r = e.reason as Error | undefined;
      const msg = r?.message ?? String(e.reason ?? '');
      if (!msg || IGNORE.test(msg) || /engine not running|Failed to fetch|NetworkError|aborted/i.test(msg)) return;
      send({ kind: 'renderer', code: r?.name ?? 'UnhandledRejection', message: msg.slice(0, 2000), stack: r?.stack?.slice(0, 8000) });
    };
    window.addEventListener('error', onErr);
    window.addEventListener('unhandledrejection', onRej);
    return () => {
      listeners.delete(f);
      offs.forEach((o) => o());
      window.removeEventListener('error', onErr);
      window.removeEventListener('unhandledrejection', onRej);
    };
  }, [showError]);
  const dismiss = (p: Problem) => {
    setBar(null);
    void window.desk.support.dismiss(p.id).catch(showError);
  };
  return (
    <>
      {bar && !req && (
        <div className="sup-bar" role="alert" data-testid="problem-bar" data-kind={bar.kind}>
          <AlertTriangle className="ico" />
          <span>{t('sup.rp.bar', { where: tk(`sup.rp.kind.${bar.kind}`) })}</span>
          <button className="btn sm primary" onClick={() => setReq({ what: 'report', problem: bar })} data-testid="problem-report">
            {t('sup.rp.report')}
          </button>
          <button className="btn sm ghost" onClick={() => dismiss(bar)} data-testid="problem-dismiss">
            {t('sup.rp.dismiss')}
          </button>
        </div>
      )}
      {req?.what === 'feedback' && <FeedbackSheet initial={req.kind ?? 'idea'} onClose={() => setReq(null)} />}
      {req?.what === 'report' && (
        <ReportSheet
          problem={req.problem}
          asked={req.asked}
          onClose={(opened) => {
            setReq(null);
            if (opened && req.problem.id) dismiss(req.problem as Problem);
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- Send feedback
function FeedbackSheet({ initial, onClose }: { initial: 'idea' | 'bug'; onClose: () => void }) {
  const ui = useUi();
  const showError = useShowError();
  const [kind, setKind] = useState<'idea' | 'bug'>(initial);
  const [what, setWhat] = useState('');
  const [email, setEmail] = useState('');
  const [diag, setDiag] = useState(false);
  const [ctx, setCtx] = useState<{ env: SupportEnv; recent: Problem[] } | null>(null);
  useEffect(() => {
    void loadEnv().then(setCtx).catch(showError);
  }, [showError]);
  const diagText = useMemo(() => (ctx ? diagnostics(ctx.env, ctx.recent) : ''), [ctx]);
  const ok = what.trim().length > 0 && okEmail(email);
  const go = async () => {
    if (!ok || !ctx) return;
    const title = titleOf(what, t('sup.fb.title'));
    const url =
      kind === 'bug'
        ? issueUrl({ title, got: feedbackBody({ what, email, diag: null, kind }), logs: diag ? diagText : undefined, env: ctx.env })
        : discussionUrl({ title, body: feedbackBody({ what, email, diag: diag ? diagText : null, kind }) });
    await window.desk.openExternal(url);
    ui.toast(t('sup.fb.opened'));
    onClose();
  };
  return (
    <Sheet
      title={t('sup.feedback')}
      onClose={onClose}
      testId="feedback-sheet"
      footer={
        <>
          <span className="s2-rhint sp">{t(kind === 'bug' ? 'sup.fb.where.bug' : 'sup.fb.where.idea')}</span>
          <button className="btn ghost" onClick={onClose}>
            {t('c.close')}
          </button>
          <button className="btn primary" disabled={!ok || !ctx} onClick={() => void go()} data-testid="feedback-open">
            <ExternalLink className="ico" />
            {t('sup.fb.open')}
          </button>
        </>
      }
    >
      <p className="s2-prose">{t('sup.fb.lead')}</p>
      <Segmented
        value={kind}
        onChange={setKind}
        options={[
          { v: 'idea', label: t('sup.fb.kind.idea'), testId: 'feedback-kind-idea' },
          { v: 'bug', label: t('sup.fb.kind.bug'), testId: 'feedback-kind-bug' },
        ]}
        testId="feedback-kind"
      />
      <label className="sup-field">
        <span>{t('sup.fb.what')}</span>
        <textarea className="inp" rows={5} value={what} onChange={(e) => setWhat(e.target.value)} placeholder={t('sup.fb.whatPh')} maxLength={4000} autoFocus data-testid="feedback-what" />
      </label>
      <label className="sup-field">
        <span>{t('sup.fb.email')}</span>
        <input className="inp" type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} data-testid="feedback-email" />
        <span className={`s2-rhint ${okEmail(email) ? '' : 'sup-bad'}`}>{okEmail(email) ? t('sup.fb.emailHint') : t('sup.fb.emailBad')}</span>
      </label>
      <label className="sup-check">
        <input type="checkbox" checked={diag} onChange={(e) => setDiag(e.target.checked)} data-testid="feedback-diag" />
        <span>
          <b>{t('sup.fb.diag')}</b>
          <span className="s2-rhint">{t('sup.fb.diagHint')}</span>
        </span>
      </label>
      {diag && (
        <details className="sup-details" open>
          <summary>{t('sup.fb.show')}</summary>
          <pre className="sup-pre" data-testid="feedback-diag-text">
            {diagText}
          </pre>
        </details>
      )}
    </Sheet>
  );
}

// ---------------------------------------------------------------- Report this problem
function ReportSheet({ problem, asked, onClose }: { problem: ReportInput; asked?: string; onClose: (opened: boolean) => void }) {
  const ui = useUi();
  const showError = useShowError();
  const [ctx, setCtx] = useState<{ env: SupportEnv; recent: Problem[] } | null>(null);
  const [doing, setDoing] = useState('');
  const [read, setRead] = useState(false);
  useEffect(() => {
    void loadEnv().then(setCtx).catch(showError);
  }, [showError]);
  const text = useMemo(() => (ctx ? problemReport(problem, ctx.env, ctx.recent) : ''), [ctx, problem]);
  const open = async () => {
    if (!ctx || !read) return;
    const what = `${problem.kind} · ${problem.code}`;
    await window.desk.openExternal(
      issueUrl({ title: t('sup.rp.issueTitle', { what }), got: doing.trim() || `${tk(`sup.rp.kind.${problem.kind}`)}: ${problem.code}`, asked, logs: text, env: ctx.env }),
    );
    ui.toast(t('sup.fb.opened'));
    onClose(true);
  };
  return (
    <Sheet
      title={t('sup.rp.title')}
      onClose={() => onClose(false)}
      wide
      testId="report-sheet"
      footer={
        <>
          <label className="sup-check sp">
            <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} data-testid="report-read" />
            <span>{t('sup.rp.reviewed')}</span>
          </label>
          <button className="btn" onClick={() => void window.desk.copyText(text).then(() => ui.toast(t('sup.rp.copied')))} disabled={!text} data-testid="report-copy">
            {t('sup.rp.copy')}
          </button>
          <button className="btn primary" disabled={!read || !ctx} onClick={() => void open()} data-testid="report-open">
            <ExternalLink className="ico" />
            {t('sup.rp.open')}
          </button>
        </>
      }
    >
      <p className="s2-prose">{t('sup.rp.lead')}</p>
      <label className="sup-field">
        <span>{t('sup.rp.what')}</span>
        <input className="inp" value={doing} onChange={(e) => setDoing(e.target.value)} maxLength={600} data-testid="report-doing" />
      </label>
      <pre className="sup-pre tall" data-testid="report-text">
        {text}
      </pre>
    </Sheet>
  );
}

// ---------------------------------------------------------------- small entry points
/** "Something off? Send feedback" for empty / quiet states. */
export function FeedbackLink() {
  return (
    <button className="sup-link" onClick={() => openFeedback()} data-testid="feedback-link">
      <MessageSquarePlus className="ico" />
      {t('sup.link')}
    </button>
  );
}

/** Settings › Advanced › Help and diagnostics: Send feedback + "Send crash reports automatically" (default off). */
export function SupportSettingsRows() {
  const showError = useShowError();
  const [env, setEnv] = useState<SupportEnv | null>(null);
  useEffect(() => {
    void window.desk.support.env().then(setEnv).catch(showError);
  }, [showError]);
  const avail = !!env?.autoAvailable;
  return (
    <>
      <div className="s2-sub">
        <span className="s2-rtext">
          <span className="s2-rlabel">{t('sup.feedback')}</span>
          <span className="s2-rhint">{t('sup.feedbackHint')}</span>
        </span>
        <button className="btn" onClick={() => openFeedback()} data-testid="settings-feedback">
          {t('sup.feedback')}
        </button>
      </div>
      <div className="s2-sub">
        <span className="s2-rtext">
          <span className="s2-rlabel">{t('sup.auto')}</span>
          <span className="s2-rhint" data-testid="crash-auto-hint">
            {avail ? t('sup.autoHint') : t('sup.autoUnavailable')}
          </span>
        </span>
        <label className={`s2-tgl ${env?.autoSend && avail ? 'on' : ''} ${avail ? '' : 'off'}`}>
          <input
            type="checkbox"
            role="switch"
            checked={!!env?.autoSend && avail}
            disabled={!avail}
            onChange={(e) => void window.desk.support.setAuto(e.target.checked).then(setEnv).catch(showError)}
            aria-label={t('sup.auto')}
            data-testid="crash-auto"
          />
          <i />
        </label>
      </div>
    </>
  );
}
