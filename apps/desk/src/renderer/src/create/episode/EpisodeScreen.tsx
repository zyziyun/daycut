// An episode: Script · Storyboard · Takes · Edit & publish (C05 / C06). The storyboard's primary action is always the
// next ladder step; "Make N final shots" opens the spend sheet - nothing is sent before its confirm.
import { useRef, useState } from 'react';
import { Eye, MoreHorizontal, X } from 'lucide-react';
import type { EpisodeView } from '../../../../shared/create';
import { t } from '../../i18n';
import { href } from '../../lib/router';
import { media } from '../../v4/kit';
import { useAction, useCreate, useCreateLoad, useCreateRefresh, waitJob } from '../api';
import { Crumbs, l10n, Tabs } from '../bits';
import { createHref, goCreate, type EpisodeTab } from '../routes';
import { ScriptBody } from '../series/EpisodesView';
import { PlanCostPanel } from './PlanCostPanel';
import { ShotBoard } from './ShotBoard';
import { SpendSheet } from './SpendSheet';
import { TakesView } from './TakesView';

export function EpisodeScreen({ eid, tab }: { eid: string; tab: EpisodeTab }) {
  const { data, setData, error, reload } = useCreateLoad((c) => c.episode(eid), [eid]);
  const running = data?.run?.state === 'running';
  useCreateRefresh(reload, running, 2000);
  if (error) return <div className="cr cr-wrap cr-err">{error}</div>;
  if (!data) return <div className="cr cr-wrap" data-testid="create-episode-loading" />;
  return <Episode ep={data} tab={tab} reload={reload} setEp={(v) => setData(v)} />;
}

function Episode({ ep, tab, reload, setEp }: { ep: EpisodeView; tab: EpisodeTab; reload: () => void; setEp: (v: EpisodeView) => void }) {
  const c = useCreate();
  const [sheet, setSheet] = useState(false);
  const [animatic, setAnimatic] = useState(false);
  const act = useAction();
  const askRef = useRef<((text: string) => void) | null>(null);
  const cover = ep.shots.find((s) => s.still)?.still;
  const nTakes = ep.shots.filter((s) => s.takes.length > 1 && !s.pick).length;

  const primary = () => {
    const step = ep.next.step;
    if (step === 'finals') return setSheet(true);
    if (step === 'making') return goCreate({ screen: 'series', sid: ep.series, tab: 'making' });
    if (step === 'pick') return goCreate({ screen: 'episode', eid: ep.id, tab: 'takes' });
    if (step === 'ready') return goCreate({ screen: 'series', sid: ep.series, tab: 'ready' });
    void act.run(async () => {
      if (!c) return;
      if (step === 'assemble') {
        const { job } = await c.handoff(ep.id, ep.bible.languages, false);
        await waitJob(c, job);
        goCreate({ screen: 'series', sid: ep.series, tab: 'ready' });
        return;
      }
      const { job } = await c.run(ep.id, { stage: step });
      await waitJob(c, job);
      reload();
    });
  };

  return (
    <div className="cr cr-wrap" data-testid="create-episode">
      <div className="cr-head">
        {cover ? <img className="cv" src={media(cover)} alt="" /> : <span className="cv" />}
        <div style={{ minWidth: 0 }}>
          <Crumbs items={[{ label: t('create.crumb'), to: { screen: 'home' } }, { label: ep.series_name, to: { screen: 'series', sid: ep.series, tab: 'bible' } }]} />
          <h1 className="clamp1" data-testid="create-episode-title">
            {t('create.ep.title', { n: ep.no, title: ep.title })}
          </h1>
        </div>
        <div className="acts">
          <span className="cr-pill accent">{t('create.ep.meta', { format: l10n(ep.format.labels), s: Math.round(ep.runtime), aspect: ep.bible.aspect })}</span>
          {ep.animatic && (
            <button className="btn" onClick={() => setAnimatic(true)} data-testid="create-watch-animatic">
              <Eye className="ico" />
              {t('create.ep.animatic')}
            </button>
          )}
          <button className="btn ghost icon" aria-label="…">
            <MoreHorizontal className="ico" />
          </button>
        </div>
      </div>
      <Tabs
        testId="create-episode-tabs"
        on={tab}
        href={(id) => createHref({ screen: 'episode', eid: ep.id, tab: id })}
        tabs={[
          { id: 'script', key: 'create.tab.script' },
          { id: 'storyboard', key: 'create.tab.storyboard', n: ep.shots.length },
          { id: 'takes', key: 'create.tab.takes', n: nTakes || null },
          { id: 'edit', key: 'create.tab.edit' },
        ]}
      />
      {tab === 'storyboard' && (
        <div className="cr-board">
          <ShotBoard ep={ep} askRef={askRef} onChanged={(v) => (v ? setEp(v) : reload())} />
          <div>
            <PlanCostPanel ep={ep} busy={act.busy} onPrimary={primary} />
            {act.error && <div className="cr-err" style={{ marginTop: 10 }}>{act.error}</div>}
          </div>
        </div>
      )}
      {tab === 'script' && (
        <div className="card" style={{ maxWidth: 900 }}>
          {ep.script?.source === 'rules' && <div className="faint" style={{ marginBottom: 8 }}>{t('create.script.rules')}</div>}
          {ep.shots.length ? <ScriptBody shots={ep.shots} /> : <div className="muted">{t('create.script.empty')}</div>}
          {(ep.lint ?? []).map((m, i) => (
            <div key={i} className="cr-warn" style={{ marginTop: 12 }}>
              {String(m.code).startsWith('create.') ? t(m.code as 'create.lint.length', m.params as Record<string, string>) : m.code}
            </div>
          ))}
        </div>
      )}
      {tab === 'takes' && <TakesView ep={ep} onChanged={reload} />}
      {tab === 'edit' && (
        <div className="card" style={{ maxWidth: 900 }} data-testid="create-edit-tab">
          {ep.handoff ? (
            <div className="row" style={{ gap: 16 }}>
              <a className="btn primary lg" href={href({ name: 'clip', id: ep.handoff.item_id, clip: ep.handoff.clip })} data-testid="create-edit-open">
                {t('create.ready.openEditor')}
              </a>
              <a className="btn lg" href={createHref({ screen: 'series', sid: ep.series, tab: 'ready' })}>
                {t('create.tab.ready')}
              </a>
            </div>
          ) : (
            <div className="muted">{t('create.edit.none')}</div>
          )}
        </div>
      )}
      {sheet && (
        <SpendSheet
          eid={ep.id}
          onClose={() => setSheet(false)}
          onCheaper={() => {
            setSheet(false);
            askRef.current?.(t('create.board.cheaperAsk'));
          }}
          onStarted={() => {
            setSheet(false);
            goCreate({ screen: 'series', sid: ep.series, tab: 'making' });
          }}
        />
      )}
      {animatic && ep.animatic && (
        <div className="cr-scrim" onMouseDown={(e) => e.target === e.currentTarget && setAnimatic(false)}>
          <div style={{ position: 'relative', height: '86vh', aspectRatio: '9 / 16' }}>
            <video src={media(ep.animatic)} autoPlay controls playsInline style={{ width: '100%', height: '100%', borderRadius: 16, background: '#0e0d0c' }} />
            <button className="btn icon" style={{ position: 'absolute', top: 12, right: -52, background: 'var(--surface)' }} onClick={() => setAnimatic(false)} aria-label={t('create.ep.close')}>
              <X className="ico" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
