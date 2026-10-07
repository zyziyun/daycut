// 「这周的素材 → 一周的帖子」 card (Home, and 发布 until the week is laid out). One primary per step:
//   planning  "Reading your footage…"            Stop
//   ready     the clips, platforms, time, cost + when to post (her words; else usual times / platform rhythm)
//             -> Make n clips and plan the week
//   making    progress; she can leave
//   review    the clips wait for her OK (the publish check is never automatic) -> Review the clips
//   preview   Home: "Your week is ready" -> See the week (发布 shows the dashed cards + Schedule n posts)
//   failed    the reason in plain words -> Report this problem / Put away
import { useEffect, useState } from 'react';
import { CalendarDays, Sparkles, Square } from 'lucide-react';
import type { WeekPlan } from '../../../shared/weekPlan';
import { fmtMinutes, fmtMoney, getLang, t } from '../i18n';
import { useEngine } from '../lib/engine';
import { go } from '../lib/router';
import { daysText } from '../publish/NlBar';
import { failureReason } from '../v4/Failure';
import { platformName } from '../v4/Home';
import { Elapsed } from '../v4/kit';
import { planFacts } from '../v4/PlanCard';
import { PlatformIcon } from '../v4/PlatformIcon';
import { openReport } from '../support/Support';
import type { useWeekPlan } from './useWeekPlan';
import './weekplan.css';

/** Platform names as a list people read ("Xiaohongshu, Douyin" / 「小红书、抖音」). */
const names = (pfs: string[]) => pfs.map(platformName).join(getLang() === 'zh-CN' ? '、' : ', ');

export function ruleLines(p: Pick<WeekPlan, 'rules'>): string[] {
  return (p.rules ?? []).map((r) => t('wp.rule', { platform: platformName(r.platform), days: daysText(r.days), time: r.time }));
}

export function WeekPlanCard({ wp, where }: { wp: ReturnType<typeof useWeekPlan>; where: 'home' | 'publish' }) {
  const p = wp.plan;
  const { info } = useEngine();
  const demo = info?.mode !== 'real';
  const [words, setWords] = useState(p?.text ?? '');
  const [miss, setMiss] = useState(false);
  useEffect(() => setWords(p?.text ?? ''), [p?.id, p?.text]);
  if (!p) return null;
  if (where === 'publish' && p.state === 'preview') return null; // the board itself shows the week
  const n = (p.plan ? planFacts(p.plan).clips : null) ?? p.want;
  const plats = (
    <span className="wp-pfs">
      {p.platforms.map((pf) => (
        <PlatformIcon key={pf} id={pf} size={18} />
      ))}
      {names(p.platforms)}
    </span>
  );
  const head = (
    <div className="wp-head">
      <CalendarDays className="ico accent" />
      <b>{t('wp.title')}</b>
      <span className="muted">· {t('wp.from', { n: p.inputs })}</span>
      <span className="sp" />
    </div>
  );
  const say = async () => {
    const r = await wp.actions.reword(p.id, words);
    setMiss(!!r && r.ok === false);
  };

  if (p.state === 'planning') {
    return (
      <div className="card wp" data-testid="weekplan" data-state={p.state} aria-busy="true">
        {head}
        <div className="wp-line">
          <Sparkles className="ico accent" />
          <span>{t('wp.reading')}</span>
          <span className="muted">
            · <Elapsed since={p.created} />
          </span>
          <span className="sp" />
          <button className="btn ghost" onClick={() => void wp.actions.dismiss(p.id)} data-testid="weekplan-stop">
            <Square className="ico" />
            {t('wp.stop')}
          </button>
        </div>
      </div>
    );
  }
  if (p.state === 'failed') {
    return (
      <div className="card wp" data-testid="weekplan" data-state={p.state}>
        {head}
        <div className="wp-line">
          <i className="dot error" />
          <b style={{ fontWeight: 500 }}>{t('wp.failed')}</b>
        </div>
        <p className="muted" data-testid="weekplan-reason">
          {failureReason({ state: 'failed', code: p.error_code ?? 'unknown', provider: null, error: p.error ?? '', at: null })}
        </p>
        <div className="row">
          <button className="btn" onClick={() => openReport({ kind: 'job', code: p.error_code ?? 'unknown', message: p.error || 'week plan failed' })} data-testid="weekplan-report">
            {t('sup.rp.report')}
          </button>
          <button className="btn ghost" onClick={() => void wp.actions.dismiss(p.id)} data-testid="weekplan-dismiss">
            {t('wp.putAway')}
          </button>
        </div>
      </div>
    );
  }
  if (p.state === 'making') {
    const pct = Math.round((p.progress ?? 0) * 100);
    return (
      <div className="card wp" data-testid="weekplan" data-state={p.state}>
        {head}
        <div className="wp-line">
          <b style={{ fontWeight: 500 }} data-testid="weekplan-making">
            {t('wp.making', { pct })}
          </b>
          <span className="sp" />
          {plats}
        </div>
        <div className="wp-bar">
          <i style={{ width: `${Math.max(4, pct)}%` }} />
        </div>
        <p className="muted small">{t('wp.makingHint')}</p>
      </div>
    );
  }
  if (p.state === 'review') {
    const first = p.review?.[0];
    return (
      <div className="card wp" data-testid="weekplan" data-state={p.state}>
        {head}
        <div className="wp-line">
          <i className="dot you" />
          <b style={{ fontWeight: 500 }}>{t('wp.review')}</b>
          <span className="sp" />
          {first && (
            <button className="btn primary lg" onClick={() => go({ name: 'focus', id: first.item })} data-testid="weekplan-review">
              {t('wp.reviewGo')}
            </button>
          )}
        </div>
        <p className="muted small">{t('wp.reviewHint')}</p>
      </div>
    );
  }
  if (p.state === 'preview') {
    const k = p.preview?.drafts.length ?? 0;
    return (
      <div className="card wp" data-testid="weekplan" data-state={p.state}>
        {head}
        <div className="wp-line">
          <b style={{ fontWeight: 500 }}>{p.preview?.ok ? t('wp.ready', { n: k }) : t('wp.noClips')}</b>
          <span className="sp" />
          {p.preview?.ok ? (
            <button className="btn primary lg" onClick={() => go({ name: 'calendar' })} data-testid="weekplan-see">
              {t('wp.see')}
            </button>
          ) : (
            <button className="btn ghost" onClick={() => void wp.actions.dismiss(p.id)} data-testid="weekplan-dismiss">
              {t('wp.putAway')}
            </button>
          )}
        </div>
        {(p.failed?.length ?? 0) > 0 && <p className="muted small">{t('wp.someFailed', { n: p.failed!.length })}</p>}
      </div>
    );
  }
  // ready: the plan and when it goes out
  const f = p.plan ? planFacts(p.plan) : null;
  return (
    <div className="card wp" data-testid="weekplan" data-state={p.state}>
      {head}
      {p.plan?.summary_zh && (
        <p className="lead wp-sum" lang="zh-CN" data-testid="weekplan-summary">
          {p.plan.summary_zh}
        </p>
      )}
      <div className="facts" data-testid="weekplan-facts">
        <div>
          <span>{t('wp.clips')}</span>
          <b>{t('wp.clipsVal', { n })}</b>
        </div>
        <div>
          <span>{t('wp.to')}</span>
          <b className="clamp1">{names(p.platforms)}</b>
        </div>
        <div>
          <span>{t('wp.time')}</span>
          <b>{fmtMinutes(f?.wall ?? 0)}</b>
        </div>
        <div>
          <span>{t('wp.cost')}</span>
          <b>{f && f.usd > 0 ? t('plan.costAbout', { v: fmtMoney(f.usd) }) : t('plan.costFree')}</b>
        </div>
      </div>
      <div className="wp-when">
        <span className="wp-label">{t('wp.when')}</span>
        <ul data-testid="weekplan-rules">
          {ruleLines(p).map((l, i) => (
            <li key={i}>
              <PlatformIcon id={p.rules[i].platform} size={16} /> {l}
            </li>
          ))}
        </ul>
        <span className="muted small">{t('wp.ruleHint')}</span>
        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault();
            void say();
          }}
        >
          <input className="inp" value={words} onChange={(e) => (setWords(e.target.value), setMiss(false))} placeholder={t('wp.whenPh')} data-testid="weekplan-words" />
          {words.trim() !== (p.text ?? '') && (
            <button className="btn" type="submit" disabled={wp.busy} data-testid="weekplan-words-go">
              {t('wp.whenSet')}
            </button>
          )}
        </form>
        {miss && (
          <span className="pb-amber small" data-testid="weekplan-miss">
            {t('wp.notUnderstood')}
          </span>
        )}
      </div>
      <div className="row wp-foot">
        <button className="btn ghost" onClick={() => void wp.actions.dismiss(p.id)} data-testid="weekplan-dismiss">
          {t('wp.putAway')}
        </button>
        <span className="sp" />
        {demo && (
          <span className="muted small" data-testid="weekplan-needs-engine">
            {t('wp.needsEngine')}
          </span>
        )}
        <button className="btn primary lg" disabled={wp.busy || demo} onClick={() => void wp.actions.run(p.id)} data-testid="weekplan-run">
          {t('wp.run', { n })}
        </button>
      </div>
    </div>
  );
}
