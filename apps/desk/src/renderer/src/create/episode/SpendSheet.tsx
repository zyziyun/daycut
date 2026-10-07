// The spend sheet (C06): today's estimate per service, the retry allowance, the most it can cost, what is left of
// the series budget / month, hardest shots first - and nothing is sent until "Spend ≈ ¥X" is pressed. The estimate's
// id + confirm code + max go with the run; the engine re-checks everything and refuses on any change.
import { useEffect, useState } from 'react';
import type { Estimate } from '../../../../shared/create';
import { yuan } from '../../../../shared/create';
import { t } from '../../i18n';
import { errText, msgText, useAction, useCreate } from '../api';
import { createHref } from '../routes';

export function SpendSheet({
  eid,
  only,
  onClose,
  onStarted,
  onCheaper,
}: {
  eid: string;
  only?: string[];
  onClose: () => void;
  onStarted: (job: string) => void;
  onCheaper?: () => void;
}) {
  const c = useCreate();
  const [est, setEst] = useState<Estimate | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [hard, setHard] = useState(true);
  const [allowUnknown, setAllowUnknown] = useState(false);
  const act = useAction();
  useEffect(() => {
    if (!c) return;
    c.estimate(eid, 'finals', only)
      .then(setEst)
      .catch((e) => setLoadErr(errText(e)));
  }, [c, eid, only]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);

  const paid = est?.lines.filter((l) => !l.manual) ?? [];
  const manual = est?.lines.filter((l) => l.manual) ?? [];
  const n = (est?.n_paid ?? 0) + (est?.n_manual ?? 0);
  const freeN = Object.values(est?.free ?? {}).reduce((a, b) => a + b, 0);
  const over: string[] = [];
  if (est) {
    if (est.budget.budget !== null && est.budget.left_after !== null && est.budget.left_after < 0)
      over.push(msgText({ code: 'create.over-budget', params: { spent: yuan(est.budget.spent), budget: yuan(est.budget.budget), need: yuan(est.max_cny) } }));
    if (est.month.cap !== null && est.month.left_after !== null && est.month.left_after < 0)
      over.push(msgText({ code: 'create.over-cap', params: { used: yuan(est.month.used), cap: yuan(est.month.cap), need: yuan(est.max_cny) } }));
    if (est.unknown.length && !allowUnknown) over.push(msgText({ code: 'create.unknown-rate', params: { shots: est.unknown.join(', ') } }));
  }
  const blocked = over.length > 0;
  return (
    <div className="cr-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cr-sheet cr" role="dialog" aria-modal="true" data-testid="create-spend-sheet">
        <h2>{t('create.sheet.title', { n })}</h2>
        <div className="sub">{t('create.sheet.sub')}</div>
        {!est && !loadErr && <div className="muted">{t('create.sheet.loading')}</div>}
        {loadErr && <div className="cr-err">{loadErr}</div>}
        {est && (
          <>
            {paid.map((l) => (
              <div key={`${l.provider}/${l.model}`} className="cr-sline" data-testid="create-sheet-line">
                <div>
                  <div className="l1">{t('create.sheet.line', { label: l.label, n: l.shots.length })}</div>
                  <div className="l2">
                    {t('create.sheet.secs', { s: Math.round(l.seconds_billed) })}
                    {' · '}
                    {l.kind === 'mcp' && l.native_units ? t('create.sheet.credits', { n: l.native_units }) : t('create.sheet.viaKey')}
                  </div>
                </div>
                <span className="amt">{yuan(l.cny)}</span>
              </div>
            ))}
            {manual.map((l) => (
              <div key={`${l.provider}/${l.model}`} className="cr-sline">
                <div>
                  <div className="l1">{t('create.sheet.line', { label: l.label, n: l.shots.length })}</div>
                  <div className="l2">{t('create.sheet.manual')}</div>
                </div>
                <span className="amt">{l.native_units ? t('create.sheet.credits', { n: l.native_units }) : t('create.option.credits')}</span>
              </div>
            ))}
            {est.retry_cny > 0 && (
              <div className="cr-sline">
                <div>
                  <div className="l1">{t('create.sheet.retry', { p: Math.round(est.retry_pct * 100) })}</div>
                  <div className="l2">{t('create.sheet.retrySub')}</div>
                </div>
                <span className="amt">{yuan(est.retry_cny)}</span>
              </div>
            )}
            {freeN > 0 && (
              <div className="cr-sline">
                <div>
                  <div className="l1">{t('create.sheet.free')}</div>
                  <div className="l2">{t('create.sheet.freeSub', { n: freeN })}</div>
                </div>
                <span className="amt" style={{ color: 'var(--ok)' }}>
                  {t('create.plan.free')}
                </span>
              </div>
            )}
            <div className="cr-sum" data-testid="create-sheet-total">
              <span className="big">≈ {yuan(est.subtotal_cny)}</span>
              <span className="muted">
                {t('create.sheet.total', { max: yuan(est.max_cny) })}
                {est.budget.left_after !== null && <> · {t('create.sheet.left', { n: yuan(est.budget.left_after) })}</>}
                {est.budget.left_after === null && est.month.left_after !== null && <> · {t('create.sheet.monthLeft', { n: yuan(est.month.left_after) })}</>}
              </span>
            </div>
            {est.hard_first.length > 0 && (
              <label className="cr-hard">
                <input type="checkbox" checked={hard} onChange={(e) => setHard(e.target.checked)} />
                <span>{t('create.sheet.hard', { list: est.hard_first.join(', ') })}</span>
              </label>
            )}
            {est.unknown.length > 0 && (
              <label className="cr-hard" style={{ marginTop: 10 }}>
                <input type="checkbox" checked={allowUnknown} onChange={(e) => setAllowUnknown(e.target.checked)} />
                <span>{t('create.sheet.unknownOk', { max: yuan(est.max_cny) })}</span>
              </label>
            )}
            {(blocked || act.error) && (
              <div className="cr-blocked" data-testid="create-sheet-blocked">
                <b style={{ fontWeight: 500 }}>{t('create.sheet.blocked')}</b>
                {[...over, ...(act.error ? [act.error] : [])].map((x, i) => (
                  <div key={i}>{x}</div>
                ))}
                {act.error && (
                  <a className="link" href={createHref({ screen: 'settings' })}>
                    {t('create.sheet.connect')}
                  </a>
                )}
              </div>
            )}
          </>
        )}
        <div className="acts">
          {onCheaper && (
            <button className="link" onClick={onCheaper} data-testid="create-sheet-cheaper">
              {t('create.sheet.cheaper')}
            </button>
          )}
          <span className="sp" />
          <button className="btn lg" onClick={onClose} data-testid="create-sheet-cancel">
            {t('create.sheet.cancel')}
          </button>
          <button
            className="btn primary lg"
            disabled={!est || blocked || act.busy || !est.confirm_code}
            onClick={() =>
              void act.run(async () => {
                if (!c || !est?.confirm_code) return;
                const { job } = await c.run(eid, {
                  stage: 'finals',
                  estimate_id: est.id,
                  confirm_code: est.confirm_code,
                  max_cny: est.max_cny,
                  ...(allowUnknown ? { allow_unknown: true } : {}),
                  ...(hard ? {} : { hard_first: false }),
                  ...(only?.length ? { only } : {}),
                });
                onStarted(job);
              })
            }
            data-testid="create-spend-confirm"
          >
            {est && est.subtotal_cny > 0 ? t('create.sheet.spend', { n: yuan(est.subtotal_cny) }) : t('create.sheet.start')}
          </button>
        </div>
      </div>
    </div>
  );
}
