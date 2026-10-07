// Plan & cost (C05, right): the cheap-first ladder with each step's price, what this step costs against the
// series budget, and the one primary action = the next step.
import { Check, Sparkles } from 'lucide-react';
import type { EpisodeView } from '../../../../shared/create';
import { yuan } from '../../../../shared/create';
import { fmtList, t } from '../../i18n';
import { svc } from '../series/MakingView';

type Step = 'stills' | 'animatic' | 'drafts' | 'finals' | 'assemble';

export function PlanCostPanel({ ep, busy, onPrimary }: { ep: EpisodeView; busy: boolean; onPrimary: () => void }) {
  const est = ep.estimate;
  const lad = ep.ladder ?? {};
  const state = (k: Step): 'done' | 'now' | '' => {
    const v = lad[k];
    if (v === 'done' || v === 'skipped') return 'done';
    const order: Step[] = ['stills', 'animatic', 'drafts', 'finals', 'assemble'];
    const first = order.find((x) => !['done', 'skipped'].includes(String(lad[x] ?? '')) && !(x === 'drafts'));
    return first === k ? 'now' : '';
  };
  const parts = [
    ...est.lines.map((l) => t('create.plan.part', { n: l.shots.length, service: l.provider === 'jimeng' ? svc('jimeng') : l.label })),
    ...Object.entries(est.free).map(([k, n]) => t('create.plan.partFree', { n, kind: t(`create.kind.${k}` as 'create.kind.card') })),
  ];
  const spent = est.budget.spent;
  const budget = est.budget.budget;
  const scale = Math.max(budget ?? 0, spent + est.subtotal_cny, 1);
  const next = ep.next;
  const label =
    next.step === 'stills'
      ? t('create.plan.doStills')
      : next.step === 'animatic'
        ? t('create.plan.doAnimatic')
        : next.step === 'finals'
          ? next.cny
            ? t('create.plan.doFinals', { n: next.n ?? 0, cny: yuan(next.cny) })
            : t('create.plan.doFinalsFree', { n: next.n ?? 0 })
          : next.step === 'making'
            ? t('create.plan.doMaking')
            : next.step === 'pick'
              ? t('create.plan.doPick')
              : next.step === 'ready'
                ? t('create.plan.doReady')
                : t('create.plan.doAssemble');
  const rows: { k: Step; title: string; sub: string; price: string | null }[] = [
    { k: 'stills', title: t('create.plan.stills'), sub: t('create.plan.stillsSub', { n: ep.shots.length }), price: null },
    { k: 'animatic', title: t('create.plan.animatic'), sub: t('create.plan.animaticSub', { s: Math.round(ep.runtime) }), price: null },
    { k: 'drafts', title: t('create.plan.drafts'), sub: lad.drafts === 'done' ? t('create.plan.draftsSub') : t('create.plan.draftsOff'), price: null },
    { k: 'finals', title: t('create.plan.finals'), sub: t('create.plan.finalsSub', { parts: fmtList(parts) }), price: est.subtotal_cny ? yuan(est.subtotal_cny) : null },
    { k: 'assemble', title: t('create.plan.assemble'), sub: t('create.plan.assembleSub'), price: null },
  ];
  return (
    <aside className="card cr-plan" data-testid="create-plan-panel">
      <h2>{t('create.plan.title')}</h2>
      <div className="sub">{t('create.plan.sub')}</div>
      {rows.map((r, i) => {
        const st = state(r.k);
        return (
          <div key={r.k} className={`cr-step ${st}`} data-testid={`create-step-${r.k}`} data-state={st || 'todo'}>
            <span className="mk">{st === 'done' ? <Check className="ico" /> : i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="t1">
                <span>{r.title}</span>
                <span className={`pr ${r.price ? '' : 'free'}`}>{r.price ?? t('create.plan.free')}</span>
              </div>
              <div className="t2">{r.sub}</div>
            </div>
          </div>
        );
      })}
      <div className="cr-total">
        <span className="big">{yuan(est.subtotal_cny)}</span>
        <span className="muted">
          {t('create.plan.thisStep')} · {budget ? t('create.plan.seriesSpent', { spent: yuan(spent), budget: yuan(budget) }) : t('create.plan.seriesSpentNone', { spent: yuan(spent) })}
        </span>
      </div>
      <div className="cr-meter">
        <i className="sp" style={{ width: `${(spent / scale) * 100}%` }} />
        <i className="st" style={{ width: `${(est.subtotal_cny / scale) * 100}%` }} />
      </div>
      <div className="cr-legend">
        <span>
          <i className="cr-sw" style={{ background: 'var(--text-faint)' }} />
          {t('create.plan.legendSpent')}
        </span>
        <span>
          <i className="cr-sw" style={{ background: 'var(--accent)' }} />
          {t('create.plan.legendStep')}
        </span>
        {est.retry_cny > 0 && <span>{t('create.plan.retry', { p: Math.round(est.retry_pct * 100) })}</span>}
      </div>
      <button className="btn primary lg cr-wide" style={{ marginTop: 18 }} disabled={busy} onClick={onPrimary} data-testid="create-primary">
        <Sparkles className="ico" />
        {busy ? t('create.plan.working') : label}
      </button>
      <div className="cr-foot">{t('create.plan.exact')}</div>
    </aside>
  );
}
