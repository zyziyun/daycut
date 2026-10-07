// 「一句话排期」: type a rule, see it as dashed cards on the board (nothing is written), then Apply (one undo) or
// Cancel. While a plan is shown it owns the page's single primary button.
import { forwardRef } from 'react';
import { AlertTriangle, CornerDownLeft, Sparkles } from 'lucide-react';
import type { SchedulePlan } from '../../../shared/v04';
import { fmtDate, fmtList, fmtWeekday, t } from '../i18n';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { addDays, dayOf } from './model';

const at = (s: string) => `${fmtWeekday(dayOf(s))} ${s.slice(11, 16)}`;

export function daysText(days: number[] | undefined): string {
  const d = [...(days ?? [])].sort((a, b) => a - b).join(',');
  if (d === '0,1,2,3,4') return t('pb.nl.days.weekdays');
  if (d === '0,1,2,3,4,5,6' || !d) return t('pb.nl.days.daily');
  if (d === '5,6') return t('pb.nl.days.weekends');
  if (d === '0,2,4,6') return t('pb.nl.days.alternate');
  const monday = new Date(2026, 9, 5); // any Monday
  return fmtList((days ?? []).map((i) => fmtWeekday(addDays(monday, i))));
}

export function planSummary(p: SchedulePlan): string {
  const n = p.drafts.length;
  const platforms = fmtList((p.platforms ?? []).map(platformName));
  const days = daysText(p.days);
  let s = p.time ? t('pb.nl.summary', { n, platforms, days, time: p.time }) : t('pb.nl.summaryNoTime', { n, platforms, days });
  if ((p.days ?? []).join(',') === '0,1,2,3,4') s += ` · ${t('pb.nl.weekendsOff')}`;
  if ((p.per_day ?? 1) > 1) s += ` · ${t('pb.nl.perDay', { n: p.per_day ?? 1 })}`;
  return s;
}

export const NlBar = forwardRef<
  HTMLInputElement,
  {
    text: string;
    setText: (s: string) => void;
    busy: boolean;
    plan: SchedulePlan | null;
    onPreview: () => void;
    onApply: () => void;
    onCancel: () => void;
  }
>(function NlBar({ text, setText, busy, plan, onPreview, onApply, onCancel }, ref) {
  const open = busy || !!plan;
  return (
    <div className={`pb-nl ${open ? 'open' : ''}`} data-testid="pb-nl">
      <div className="pb-nlrow">
        <Sparkles className="ico accent" />
        <input
          ref={ref}
          value={text}
          placeholder={t('pb.nl.ph')}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && text.trim() && !e.nativeEvent.isComposing) onPreview();
            if (e.key === 'Escape' && plan) onCancel();
          }}
          aria-label={t('pb.nl.ph')}
          data-testid="pb-nl-input"
        />
        {text.trim() && (
          <button className="pb-kbd" onClick={onPreview} aria-label={t('pb.nl.go')} data-tip={t('pb.nl.go')} data-testid="pb-nl-go">
            <CornerDownLeft className="ico" />
          </button>
        )}
      </div>
      {busy && !plan && <div className="pb-nlplan muted">{t('pb.nl.reading')}</div>}
      {plan && (
        <div className="pb-nlplan" data-testid="pb-nl-plan" data-ok={plan.ok ? '1' : '0'}>
          <span className="pb-nlicon">
            <Sparkles className="ico" />
          </span>
          {plan.ok ? (
            <div className="col" style={{ gap: 4, minWidth: 0, flex: 1 }}>
              <b data-testid="pb-nl-summary">{planSummary(plan)}</b>
              <span className="pb-nlsub">
                {(plan.platforms ?? []).slice(0, 1).map((p) => (
                  <PlatformIcon key={p} id={p} size={16} />
                ))}
                <span>{t(plan.from_selection ? 'pb.nl.fromSel' : 'pb.nl.fromQueue', { n: plan.clips ?? 0 })}</span>
                <span>{t('pb.nl.dashed')}</span>
                {plan.adjustments.slice(0, 2).map((a) => (
                  <span key={a.frm + a.platform} className="pb-amber">
                    <AlertTriangle className="ico" /> {t('pb.nl.moved', { from: at(a.frm), to: a.to.slice(11, 16) })}
                  </span>
                ))}
              </span>
            </div>
          ) : (
            <span className="pb-amber" style={{ flex: 1 }} data-testid="pb-nl-error">
              {t(`pb.nl.${plan.reason ?? 'not_understood'}` as 'pb.nl.not_understood')}
            </span>
          )}
          <button className="btn ghost" onClick={onCancel} data-testid="pb-nl-cancel">
            {t('pb.nl.cancel')}
          </button>
          {plan.ok && (
            <>
              <button className="btn" onClick={() => (ref && 'current' in ref ? ref.current?.focus() : undefined)}>
                {t('pb.nl.edit')}
              </button>
              <button className="btn primary" onClick={onApply} data-testid="pb-nl-apply" title={fmtDate(plan.start)}>
                {t('pb.nl.apply', { n: plan.drafts.length })}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
});
