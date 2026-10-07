// The series bible (C04): the engine, beats, cast (locked once), always / never, and the next episode ideas.
import { useState } from 'react';
import { Check, ChevronRight, FileText, Plus, RefreshCw, X } from 'lucide-react';
import type { CastMember, SeriesView } from '../../../../shared/create';
import { yuan } from '../../../../shared/create';
import { t } from '../../i18n';
import { useAction, useCreate, waitJob } from '../api';
import { AskBar, CastAvatar } from '../bits';
import { svc } from './MakingView';
import { goCreate } from '../routes';

export function BibleView({ s, reload }: { s: SeriesView; reload: () => void }) {
  const c = useCreate();
  const b = s.bible;
  const [editing, setEditing] = useState(false);
  const [engine, setEngine] = useState(b.engine);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const fresh = s.ideas.filter((i) => !i.episode);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(fresh.filter((i) => i.picked).map((i) => i.id)));
  const write = useAction();
  const more = useAction();
  const ask = useAction();
  const save = useAction();
  const langs = (b.languages ?? []).map((l) => t(`create.lang.${l}` as 'create.lang.zh')).join(' + ');

  const patch = (p: Parameters<NonNullable<typeof c>['patchBible']>[1]) =>
    save.run(async () => {
      if (!c) return;
      await c.patchBible(s.id, p);
      reload();
    });

  return (
    <>
      <div className="cr-two">
        <div className="col" style={{ gap: 20 }}>
          <div className="card" data-testid="create-bible-engine">
            <div className="cr-cardh">
              <h3>{t('create.bible.engine')}</h3>
              <button className="link" onClick={() => (editing ? void patch({ engine }).then(() => setEditing(false)) : setEditing(true))}>
                {editing ? t('create.bible.save') : t('create.bible.edit')}
              </button>
            </div>
            {editing ? (
              <textarea className="inp" style={{ width: '100%', minHeight: 90, padding: 12, fontSize: 16 }} value={engine} onChange={(e) => setEngine(e.target.value)} />
            ) : (
              <div className="cr-engine">{b.engine}</div>
            )}
            <div className="cr-beats">
              {b.beats.map((x, i) => (
                <span key={x.id} className="row" style={{ gap: 8 }}>
                  {i > 0 && <ChevronRight className="ico faint" />}
                  <span className="cr-beat">
                    {x.n ? <b>{x.n + 1}</b> : null}
                    {x.label}
                  </span>
                </span>
              ))}
            </div>
            <div className="muted" style={{ fontSize: 15 }}>
              {t('create.bible.facts', { len: b.length_s, aspect: b.aspect, langs })}
            </div>
          </div>

          <div className="card" data-testid="create-bible-cast">
            <div className="cr-cardh">
              <h3>{t('create.bible.cast')}</h3>
              <button className="link" onClick={() => setAdding(true)}>
                <Plus className="ico" style={{ verticalAlign: -3 }} /> {t('create.bible.add')}
              </button>
            </div>
            <div className="muted" style={{ fontSize: 15 }}>
              {t('create.bible.castSub')}
            </div>
            <div className="cr-cast">
              {b.cast.map((m, i) => (
                <Member key={m.id} m={m} i={i} />
              ))}
              {adding && (
                <div className="cr-member">
                  <CastAvatar id={String.fromCharCode(65 + b.cast.length)} i={b.cast.length} />
                  <div className="col" style={{ flex: 1 }}>
                    <input className="inp" autoFocus placeholder={t('create.bible.addName')} value={newName} onChange={(e) => setNewName(e.target.value)} />
                    <div className="row">
                      <button className="btn ghost sm" onClick={() => setAdding(false)}>
                        {t('create.series.cancel')}
                      </button>
                      <button
                        className="btn sm"
                        disabled={!newName.trim()}
                        onClick={() =>
                          void patch({ cast: [...b.cast, { id: String.fromCharCode(65 + b.cast.length), name: newName.trim(), essence: newName.trim(), look: '' }] }).then(() => {
                            setAdding(false);
                            setNewName('');
                          })
                        }
                      >
                        {t('create.bible.save')}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="card" data-testid="create-bible-rules">
            <h3>{t('create.bible.rules')}</h3>
            <div className="cr-rules">
              <div>
                {b.rules.always.map((r, i) => (
                  <div key={i} className="cr-check">
                    <Check className="ico" />
                    <span style={{ color: 'var(--text)' }}>{r}</span>
                  </div>
                ))}
              </div>
              <div>
                {b.rules.never.map((r, i) => (
                  <div key={i} className="cr-check no">
                    <X className="ico" />
                    <span style={{ color: 'var(--text)' }}>{r}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          {save.error && <div className="cr-err">{save.error}</div>}
          <AskBar
            testId="create-bible-ask"
            placeholder={ask.busy ? t('create.bible.revising') : t('create.bible.ask')}
            busy={ask.busy}
            onAsk={(text) =>
              void ask.run(async () => {
                if (!c) return;
                const { job } = await c.reviseBible(s.id, text);
                await waitJob(c, job);
                reload();
              })
            }
          />
          {ask.error && <div className="cr-err">{ask.error}</div>}
        </div>

        <div className="card cr-ideas" data-testid="create-ideas">
          <div className="cr-cardh">
            <h3>{t('create.bible.next')}</h3>
            <button
              className="link"
              disabled={more.busy}
              onClick={() =>
                void more.run(async () => {
                  if (!c) return;
                  const { job } = await c.moreIdeas(s.id, 2);
                  await waitJob(c, job);
                  reload();
                })
              }
              data-testid="create-ideas-more"
            >
              <RefreshCw className="ico" style={{ verticalAlign: -3 }} /> {t('create.bible.more')}
            </button>
          </div>
          <div className="muted" style={{ fontSize: 15, marginBottom: 6 }}>
            {t('create.bible.nextSub')}
          </div>
          {fresh.map((i) => (
            <label key={i.id} className="idea" data-testid="create-idea">
              <input
                type="checkbox"
                checked={picked.has(i.id)}
                onChange={(e) => {
                  const n = new Set(picked);
                  if (e.target.checked) n.add(i.id);
                  else n.delete(i.id);
                  setPicked(n);
                }}
              />
              <span style={{ minWidth: 0 }}>
                <div className="t1">{i.title}</div>
                {i.logline && <div className="t2">{i.logline}</div>}
                <div className="t3">{i.est_cny ? t('create.bible.finals', { n: yuan(i.est_cny) }) : t('create.bible.recorded')}</div>
              </span>
            </label>
          ))}
          <button
            className="btn primary lg cr-wide"
            style={{ marginTop: 16 }}
            disabled={!picked.size || write.busy}
            onClick={() =>
              void write.run(async () => {
                if (!c) return;
                const { job } = await c.addEpisodes(s.id, [...picked]);
                const r = await waitJob<{ episodes: string[] }>(c, job);
                reload();
                if (r.episodes[0]) goCreate({ screen: 'episode', eid: r.episodes[0], tab: 'storyboard' });
              })
            }
            data-testid="create-write-scripts"
          >
            <FileText className="ico" />
            {write.busy ? t('create.bible.writing') : t('create.bible.write', { n: picked.size })}
          </button>
          <div className="cr-foot">{t('create.bible.writeHint')}</div>
          {(write.error || more.error) && <div className="cr-err">{write.error ?? more.error}</div>}
        </div>
      </div>
    </>
  );
}

function Member({ m, i }: { m: CastMember; i: number }) {
  return (
    <div className="cr-member" data-testid="create-cast-member">
      <CastAvatar id={m.id} i={i} />
      <div style={{ minWidth: 0 }}>
        <div className="nm">
          {m.id} · {m.name}
        </div>
        {(m.look || (m.essence && m.essence !== m.name)) && <div className="ess">{m.look || m.essence}</div>}
        <div className="cr-check">
          <Check className="ico" />
          {m.own ? t('create.bible.faceOwn') : m.face_locked ? t('create.bible.faceLocked', { service: svc('kling-mcp') }) : t('create.bible.faceOpen')}
        </div>
        <div className="cr-check">
          <Check className="ico" />
          {m.own || m.voice?.engine === 'own' ? t('create.bible.voiceOwn') : m.voice?.engine === 'qwen3-tts' ? t('create.bible.voiceTts') : t('create.bible.voiceNative')}
        </div>
      </div>
    </div>
  );
}
