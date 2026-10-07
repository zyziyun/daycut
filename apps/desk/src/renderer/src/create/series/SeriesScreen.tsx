// A series: Bible · Episodes · Scripts · Making · Ready (C04 / C07 / C10).
import { useState } from 'react';
import { MoreHorizontal, Settings as Gear } from 'lucide-react';
import type { SeriesView } from '../../../../shared/create';
import { yuan } from '../../../../shared/create';
import { t } from '../../i18n';
import { media } from '../../v4/kit';
import { useAction, useCreate, useCreateLoad, useCreateRefresh } from '../api';
import { Crumbs, FormatArt, l10n, Tabs } from '../bits';
import { createHref, type SeriesTab } from '../routes';
import { BibleView } from './BibleView';
import { MakingView } from './MakingView';
import { ReadyView } from './ReadyView';
import { EpisodesView, ScriptsView } from './EpisodesView';

export function SeriesScreen({ sid, tab }: { sid: string; tab: SeriesTab }) {
  const { data, error, reload } = useCreateLoad((c) => c.series(sid), [sid]);
  useCreateRefresh(reload, tab === 'making', 2500);
  if (error) return <div className="cr cr-wrap cr-err">{error}</div>;
  if (!data) return <div className="cr cr-wrap" data-testid="create-series-loading" />;
  const cover = data.episodes.find((e) => e.cover)?.cover;
  return (
    <div className="cr cr-wrap" data-testid="create-series">
      <div className="cr-head">
        {cover ? (
          <img className="cv" src={media(cover)} alt="" />
        ) : (
          <span className="cv">
            <FormatArt id={data.format.id} badge={false} />
          </span>
        )}
        <div style={{ minWidth: 0 }}>
          <Crumbs items={[{ label: t('create.crumb'), to: { screen: 'home' } }, { label: l10n(data.format.labels) }]} />
          <h1 className="clamp1" data-testid="create-series-title">
            {data.name}
          </h1>
        </div>
        <div className="acts">
          <BudgetBox s={data} onSaved={reload} />
          <button className="btn ghost icon" aria-label="…">
            <MoreHorizontal className="ico" />
          </button>
        </div>
      </div>
      <Tabs
        testId="create-series-tabs"
        on={tab}
        href={(id) => createHref({ screen: 'series', sid, tab: id })}
        tabs={[
          { id: 'bible', key: 'create.tab.bible' },
          { id: 'episodes', key: 'create.tab.episodes', n: data.episodes.length },
          { id: 'scripts', key: 'create.tab.scripts' },
          { id: 'making', key: 'create.tab.making', n: data.counts.making },
          { id: 'ready', key: 'create.tab.ready', n: data.counts.ready },
        ]}
      />
      {tab === 'bible' && <BibleView s={data} reload={reload} />}
      {tab === 'episodes' && <EpisodesView s={data} />}
      {tab === 'scripts' && <ScriptsView s={data} />}
      {tab === 'making' && <MakingView s={data} />}
      {tab === 'ready' && <ReadyView s={data} reload={reload} />}
    </div>
  );
}

function BudgetBox({ s, onSaved }: { s: SeriesView; onSaved: () => void }) {
  const c = useCreate();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState(String(s.meta.budget_cny ?? ''));
  const act = useAction();
  const spent = s.spend.series?.spent ?? 0;
  const budget = s.spend.series?.budget;
  return (
    <span className="row" style={{ gap: 12, position: 'relative' }}>
      <span className="muted num" style={{ fontSize: 15 }} data-testid="create-series-budget">
        {budget ? t('create.series.budgetLine', { spent: yuan(spent), budget: yuan(budget) }) : t('create.series.budgetNone', { spent: yuan(spent) })}
      </span>
      <button className="btn" onClick={() => setOpen(!open)} data-testid="create-series-settings">
        <Gear className="ico" />
        {t('create.series.settings')}
      </button>
      {open && (
        <div className="cr-pop" style={{ right: 0, left: 'auto', width: 280, padding: 16 }}>
          <div className="col" style={{ gap: 10 }}>
            <label className="muted">{t('create.series.budgetLabel')}</label>
            <input className="inp" inputMode="numeric" value={v} onChange={(e) => setV(e.target.value.replace(/[^\d.]/g, ''))} />
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button className="btn ghost" onClick={() => setOpen(false)}>
                {t('create.series.cancel')}
              </button>
              <button
                className="btn primary"
                disabled={act.busy}
                onClick={() =>
                  void act.run(async () => {
                    if (!c) return;
                    await c.seriesSettings(s.id, { budget_cny: v ? Number(v) : null });
                    setOpen(false);
                    onSaved();
                  })
                }
              >
                {t('create.series.save')}
              </button>
            </div>
            {act.error && <div className="cr-err">{act.error}</div>}
          </div>
        </div>
      )}
    </span>
  );
}
