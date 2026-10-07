// Ready (C10): assemble an episode on this Mac, open it in the normal editor, its language versions, and when each
// version goes out. "Send to Publish" only puts posts on the calendar - the creator still presses Publish.
import { useEffect, useState } from 'react';
import { Film, Mic, Pencil, Plus, Send } from 'lucide-react';
import type { EpisodeRow, Handoff, SeriesView } from '../../../../shared/create';
import { sortPlatforms } from '../../../../shared/platforms';
import { yuan } from '../../../../shared/create';
import { fmtDate, fmtTime, t } from '../../i18n';
import { useEngine } from '../../lib/engine';
import { useHistory } from '../../lib/history';
import { href } from '../../lib/router';
import { media } from '../../v4/kit';
import { useAction, useCreate, useCreateLoad, waitJob } from '../api';


export function ReadyView({ s, reload }: { s: SeriesView; reload: () => void }) {
  const ready = s.episodes.filter((e) => e.handoff || e.ladder?.finals === 'done');
  const [sel, setSel] = useState<string | null>(null);
  const ep = ready.find((e) => e.id === sel) ?? ready[ready.length - 1];
  if (!ep) return <div className="empty" data-testid="create-ready-empty">{t('create.ready.empty')}</div>;
  return (
    <div data-testid="create-ready">
      {ready.length > 1 && (
        <div className="row" style={{ marginBottom: 16, flexWrap: 'wrap' }}>
          {ready.map((e) => (
            <button key={e.id} className={`chip ${e.id === ep.id ? 'on' : ''}`} onClick={() => setSel(e.id)}>
              {t('create.ep.short', { n: e.no })}
            </button>
          ))}
        </div>
      )}
      <ReadyEpisode key={ep.id} s={s} ep={ep} reload={reload} />
    </div>
  );
}

function ReadyEpisode({ s, ep, reload }: { s: SeriesView; ep: EpisodeRow; reload: () => void }) {
  const c = useCreate();
  const { client } = useEngine();
  const history = useHistory();
  const view = useCreateLoad((x) => x.episode(ep.id), [ep.id, ep.handoff?.at]);
  const h: Handoff | null = ep.handoff;
  const [showAnimatic, setShowAnimatic] = useState(false);
  const [sent, setSent] = useState(false);
  const assemble = useAction();
  const send = useAction();
  useEffect(() => setSent(false), [ep.id]);
  const animatic = view.data?.animatic ?? null;
  const src = showAnimatic && animatic ? animatic : h?.file ?? null;
  const n = (h?.posts ?? []).length;
  return (
    <div className="cr-ready">
      <div className="cr-player" data-testid="create-ready-player">
        {src ? <video key={src} src={media(src)} controls playsInline preload="metadata" /> : null}
        <span className="tag">
          {t('create.ep.short', { n: ep.no })} · {view.data ? `${view.data.runtime} s` : ''}
        </span>
      </div>
      <div className="col" style={{ gap: 20 }}>
        <div className="card">
          <div className="cr-cardh">
            <h2>{h ? t('create.ready.assembled', { n: ep.no }) : t('create.ready.notYet', { n: ep.no, title: ep.title })}</h2>
            {h && (
              <span className="cr-pill ok" style={{ marginLeft: 'auto' }}>
                {h.under && h.under > 0 ? t('create.ready.spentPill', { spent: yuan(h.spent), under: yuan(h.under) }) : t('create.ready.spentOnly', { spent: yuan(h.spent) })}
              </span>
            )}
          </div>
          <div className="muted" style={{ fontSize: 15, marginBottom: 16 }}>
            {t('create.ready.sub')}
          </div>
          {h ? (
            <div className="row" style={{ gap: 16 }}>
              <a className="btn lg" href={href({ name: 'clip', id: h.item_id, clip: h.clip })} data-testid="create-open-editor">
                <Pencil className="ico" />
                {t('create.ready.openEditor')}
              </a>
              {animatic && (
                <button className="btn ghost lg" onClick={() => setShowAnimatic(!showAnimatic)}>
                  <Film className="ico" />
                  {showAnimatic ? t('create.ready.showFinal') : t('create.ready.compare')}
                </button>
              )}
            </div>
          ) : (
            <button
              className="btn primary lg"
              disabled={assemble.busy}
              onClick={() =>
                void assemble.run(async () => {
                  if (!c) return;
                  const { job } = await c.handoff(ep.id, s.bible.languages, false);
                  await waitJob(c, job);
                  history.reload();
                  reload();
                })
              }
              data-testid="create-assemble"
            >
              {assemble.busy ? t('create.ready.assembling') : t('create.ready.assemble', { n: ep.no })}
            </button>
          )}
          {assemble.error && <div className="cr-err" style={{ marginTop: 10 }}>{assemble.error}</div>}
        </div>

        {h && (
          <div className="card cr-langs" data-testid="create-languages">
            <div className="cr-cardh">
              <h3>{t('create.ready.languages')}</h3>
              <span className="link" style={{ marginLeft: 'auto', opacity: 0.5 }}>
                <Plus className="ico" style={{ verticalAlign: -3 }} /> {t('create.ready.addLanguage')}
              </span>
            </div>
            {h.languages.map((l) => {
              const name = t(`create.lang.${l.lang}` as 'create.lang.zh');
              return (
                <div key={l.lang} className="row">
                  <span className="lg">{t(`create.langCode.${l.lang}` as 'create.langCode.zh')}</span>
                  <span style={{ minWidth: 0 }}>
                    <div className="t1">{l.kind === 'original' ? t('create.ready.original', { lang: name }) : name}</div>
                    <div className="t2">
                      {l.kind === 'original' ? t('create.ready.originalSub') : l.kind === 'bilingual' ? t('create.ready.bilingualSub') : l.n_check ? t('create.ready.translatedSub', { n: l.n_check }) : t('create.ready.translatedOk')}
                    </div>
                  </span>
                  <span className="right">
                    {l.state === 'ready' ? <span className="cr-pill ok">{t('create.ready.ok')}</span> : <span className="cr-pill you">{t('create.ready.check', { n: l.n_check })}</span>}
                  </span>
                </div>
              );
            })}
            <div className="row">
              <span className="lg">
                <Mic className="ico" />
              </span>
              <span>
                <div className="t1">{t('create.ready.dub')}</div>
                <div className="t2">{t('create.ready.dubSub')}</div>
              </span>
            </div>
          </div>
        )}

        {h && n > 0 && (
          <div className="card cr-when" data-testid="create-when">
            <div className="cr-cardh">
              <h3>{t('create.ready.when')}</h3>
              <span className="muted" style={{ marginLeft: 'auto', fontSize: 15 }}>
                {t('create.ready.slot')}
              </span>
            </div>
            {h.posts.map((p) => (
              <div key={p.lang} className="row">
                <b style={{ fontWeight: 500 }}>{`${fmtDate(p.at, { weekday: 'short' })} ${fmtTime(p.at)}`}</b>
                <span className="muted">
                  {t('create.ready.versionRow', { lang: t(`create.lang.${p.lang}` as 'create.lang.zh'), platforms: sortPlatforms(p.platforms, (x) => x.split(':')[0]).map((x) => t(`create.plat.${x}` as 'create.plat.douyin')).join(', ') })}
                </span>
                <a className="link" href={href({ name: 'calendar' })}>
                  {t('create.ready.change')}
                </a>
              </div>
            ))}
          </div>
        )}
        {h && n > 0 && (
          <div className="cr-send">
            <span>{t('create.ready.youPress')}</span>
            {sent ? (
              <a className="btn lg" href={href({ name: 'calendar' })} data-testid="create-sent">
                {t('create.ready.sent')}
              </a>
            ) : (
              <button
                className="btn primary lg"
                disabled={send.busy || !client}
                onClick={() =>
                  void send.run(async () => {
                    if (!client) return;
                    for (const p of h.posts) for (const plat of p.platforms) await client.schedule({ item: h.item_id, clip: h.clip, platform: plat, at: p.at });
                    setSent(true);
                  })
                }
                data-testid="create-send-publish"
              >
                <Send className="ico" />
                {t('create.ready.send', { n })}
              </button>
            )}
          </div>
        )}
        {send.error && <div className="cr-err">{send.error}</div>}
      </div>
    </div>
  );
}
