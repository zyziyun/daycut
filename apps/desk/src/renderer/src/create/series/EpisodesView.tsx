// Episodes (list) and Scripts (every episode's beats + lines) of a series.
import type { SeriesView } from '../../../../shared/create';
import { t } from '../../i18n';
import { media } from '../../v4/kit';
import { msgText, useCreateLoad } from '../api';
import { createHref } from '../routes';

export function EpisodesView({ s }: { s: SeriesView }) {
  if (!s.episodes.length) return <div className="empty">{t('create.episodes.empty')}</div>;
  return (
    <div className="col" style={{ gap: 12 }} data-testid="create-episodes">
      {s.episodes.map((e) => (
        <a key={e.id} className="cr-se" href={createHref({ screen: 'episode', eid: e.id, tab: 'storyboard' })} data-testid="create-episode-row">
          {e.cover ? <img className="cv" src={media(e.cover)} alt="" /> : <span className="cv" />}
          <span className="tx">
            <span className="t1">{t('create.ep.title', { n: e.no, title: e.title })}</span>
            {e.logline && <span className="t2">{e.logline}</span>}
            <span className="t3">
              <span className="cr-pill">{msgText(e.status)}</span>
              <span>{t('create.episodes.shots', { n: e.shots })}</span>
            </span>
          </span>
        </a>
      ))}
    </div>
  );
}

export function ScriptsView({ s }: { s: SeriesView }) {
  if (!s.episodes.length) return <div className="empty">{t('create.scripts.empty')}</div>;
  return (
    <div className="col" style={{ gap: 16 }}>
      {s.episodes.map((e) => (
        <EpisodeScript key={e.id} eid={e.id} />
      ))}
    </div>
  );
}

export function EpisodeScript({ eid }: { eid: string }) {
  const { data } = useCreateLoad((c) => c.episode(eid), [eid]);
  if (!data) return null;
  return (
    <div className="card" data-testid="create-script">
      <div className="cr-cardh">
        <h3>{t('create.ep.title', { n: data.no, title: data.title })}</h3>
        <a className="link" href={createHref({ screen: 'episode', eid, tab: 'storyboard' })}>
          {t('create.tab.storyboard')}
        </a>
      </div>
      {data.script?.source === 'rules' && <div className="faint" style={{ marginBottom: 8 }}>{t('create.script.rules')}</div>}
      {data.shots.length === 0 && <div className="muted">{t('create.script.empty')}</div>}
      <ScriptBody shots={data.shots} />
    </div>
  );
}

export function ScriptBody({ shots }: { shots: { no: string; beat: string; action: string; lines: { who: string; text: string }[]; card?: string | null }[] }) {
  let last = '';
  return (
    <div className="col" style={{ gap: 6, fontSize: 15 }}>
      {shots.map((sh) => {
        const head = sh.beat !== last ? sh.beat : null;
        last = sh.beat;
        return (
          <div key={sh.no}>
            {head && <div style={{ fontWeight: 500, marginTop: 10 }}>{head}</div>}
            <div className="muted">
              <span className="faint num" style={{ marginRight: 8 }}>
                {sh.no}
              </span>
              {sh.card ? <i>{sh.card}</i> : sh.action}
            </div>
            {sh.lines.map((ln, i) => (
              <div key={i} style={{ paddingLeft: 30 }}>
                <b style={{ fontWeight: 500 }}>{ln.who}</b> {t('create.board.line', { text: ln.text })}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
