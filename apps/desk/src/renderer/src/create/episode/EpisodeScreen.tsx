// An episode: Script · Storyboard · Takes · Edit & publish (C05 / C06). The storyboard's primary action is always the
// next ladder step; "Make N final shots" opens the spend sheet - nothing is sent before its confirm.
import { useRef, useState } from 'react';
import { Eye, MoreHorizontal, X } from 'lucide-react';
import type { EpisodeView } from '../../../../shared/create';
import { t } from '../../i18n';
import { href } from '../../lib/router';
import { media } from '../../v4/kit';
import { msgText, useAction, useCreate, useCreateLoad, useCreateRefresh, waitJob } from '../api';
import { Crumbs, l10n, Tabs } from '../bits';
import { createHref, goCreate, type EpisodeTab } from '../routes';
import { ScriptBody } from '../series/EpisodesView';
import { PlanCostPanel } from './PlanCostPanel';
import { ShotBoard } from './ShotBoard';
import { SpendSheet } from './SpendSheet';
import { TakesView } from './TakesView';
import { BoardDrop, ImportBoardButton, ImportNote, useBoardImport } from '../ImportBoard';

export function EpisodeScreen({ eid, tab }: { eid: string; tab: EpisodeTab }) {
  const { data, setData, error, reload } = useCreateLoad((c) => c.episode(eid), [eid]);
  const running = data?.run?.state === 'running' || data?.make?.state === 'running';
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
  const imp = useBoardImport({ eid: ep.id, shots: ep.shots.length, onDone: () => reload() });
  const askRef = useRef<((text: string) => void) | null>(null);
  const cover = ep.shots.find((s) => s.still)?.still;
  const nTakes = ep.shots.filter((s) => s.takes.length > 1 && !s.pick).length;

  /** The episode as the engine has it now: awaited before an action's buttons are live again, so they never show the
   * state from before the action (a click on a stale button would act on the new state). */
  const refresh = async () => {
    if (c) setEp(await c.episode(ep.id));
  };

  const primary = () => {
    const step = ep.next.step;
    if (step === 'finals') return setSheet(true);
    if (step === 'making') return goCreate({ screen: 'series', sid: ep.series, tab: 'making' });
    if (step === 'pick') return goCreate({ screen: 'episode', eid: ep.id, tab: 'takes' });
    if (step === 'ready') return goCreate({ screen: 'series', sid: ep.series, tab: 'ready' });
    void act.run(async () => {
      if (!c) return;
      if (step === 'make') {
        // plugin / agent shots: parallel lanes, each shot in its own job folder; progress shows on the board
        const { job } = await c.make(ep.id);
        reload();
        await waitJob(c, job, () => undefined, 1500);
        await refresh();
        return;
      }
      if (step === 'assemble') {
        const { job } = await c.handoff(ep.id, ep.bible.languages, false);
        await waitJob(c, job);
        goCreate({ screen: 'series', sid: ep.series, tab: 'ready' });
        return;
      }
      const { job } = await c.run(ep.id, { stage: step });
      await waitJob(c, job);
      await refresh(); // the next step's label before the button is live again
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
        <BoardDrop onPath={(p) => void imp.run(p)}>
          <div className="row" style={{ gap: 10, alignItems: 'center', margin: '0 0 12px' }}>
            <ImportBoardButton imp={imp} testId="create-storyboard-import" small />
            {ep.imported?.importer && <span className="muted" style={{ fontSize: 13 }}>{t('create.import.done', { n: ep.shots.length, importer: ep.imported.importer })}</span>}
            {ep.make && <MakeStatus ep={ep} />}
          </div>
          <ImportNote imp={imp} errorsOnly />
        </BoardDrop>
      )}
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
      {tab === 'takes' && <TakesView ep={ep} onChanged={refresh} />}
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

/** Plugin / agent shots: "3 of 7 made · 2 lanes", the shots waiting for you or failed (with the reason). */
function MakeStatus({ ep }: { ep: EpisodeView }) {
  const m = ep.make;
  if (!m) return null;
  const units = Object.entries(m.units ?? {});
  const done = units.filter(([, u]) => u.state === 'done').length;
  const lanes = Object.values(m.lanes ?? {}).reduce((a, b) => a + b, 0);
  const odd = units.filter(([, u]) => u.state === 'failed' || u.state === 'manual-waiting');
  return (
    <span className="muted" style={{ fontSize: 13 }} data-testid="create-make-status" data-state={m.state}>
      {m.state === 'running' ? t('create.make.running', { done, total: units.length, lanes }) : t('create.make.done', { done, total: units.length })}
      {odd.slice(0, 2).map(([no, u]) => (
        <span key={no} className={u.state === 'failed' ? 'cr-err' : ''} style={{ marginLeft: 10 }} data-testid="create-make-issue">
          {u.code ? msgText({ code: u.code, params: (u.params ?? {}) as Record<string, string> }) : no}
        </span>
      ))}
    </span>
  );
}
