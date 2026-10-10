// Takes: every shot that has more than one take (or none picked yet) -> watch and pick one. 即梦 shots: the prompts
// to copy (the creator presses Generate on the site) and "Add downloads".
import { useState } from 'react';
import { Check, Copy, ExternalLink, Mic, Upload } from 'lucide-react';
import type { EpisodeView } from '../../../../shared/create';
import { t } from '../../i18n';
import { media } from '../../v4/kit';
import { useAction, useCreate, useCreateLoad } from '../api';
import { goCreate } from '../routes';

const JIMENG = 'https://jimeng.jianying.com/';

export function TakesView({ ep, onChanged }: { ep: EpisodeView; onChanged: () => void | Promise<void> }) {
  const c = useCreate();
  const act = useAction();
  const withTakes = ep.shots.filter((s) => s.takes.length > 0);
  const manualUnits = Object.values(ep.run?.units ?? {}).filter((u) => u.state === 'manual-waiting');
  const recordShots = ep.shots.filter((s) => s.route.kind === 'record' && !s.takes.length);
  return (
    <div className="col" style={{ gap: 16 }} data-testid="create-takes">
      {manualUnits.length > 0 && <ManualPrompts eid={ep.id} n={manualUnits.reduce((a, u) => a + u.shots.length, 0)} onImported={onChanged} />}
      {recordShots.length > 0 && (
        <div className="card row" style={{ flexWrap: 'wrap' }}>
          {recordShots.map((s) => (
            <button key={s.no} className="btn" onClick={() => goCreate({ screen: 'record', eid: ep.id, shot: s.no })}>
              <Mic className="ico" />
              {t('create.takes.record', { no: s.no })}
            </button>
          ))}
        </div>
      )}
      {!withTakes.length && !manualUnits.length && <div className="empty">{t('create.takes.empty')}</div>}
      {withTakes
        .sort((a, b) => Number(b.takes.length > 1 && !b.pick) - Number(a.takes.length > 1 && !a.pick))
        .map((s) => (
          <div key={s.no} className="card" data-testid="create-take-shot" data-shot={s.no}>
            <div className="cr-cardh">
              <h3>{t('create.takes.shot', { no: s.no })}</h3>
              <span className="muted clamp1" style={{ fontSize: 15 }}>
                {s.action}
              </span>
            </div>
            <div className="row" style={{ gap: 14, flexWrap: 'wrap', alignItems: 'flex-start' }}>
              {s.takes.map((tk) => {
                const on = s.pick === tk.file;
                return (
                  <div key={tk.file} className="col" style={{ gap: 8, width: 170 }}>
                    <video src={media(tk.file)} muted playsInline controls preload="metadata" style={{ width: 170, aspectRatio: '9 / 16', borderRadius: 10, background: '#0e0d0c', objectFit: 'cover', outline: on ? '3px solid var(--accent)' : 'none' }} />
                    <button
                      className={`btn ${on ? '' : 'primary'}`}
                      disabled={on || act.busy}
                      onClick={() =>
                        void act.run(async () => {
                          if (!c) return;
                          await c.pick(ep.id, s.no, tk.file);
                          await onChanged(); // the buttons stay off until they show the pick
                        })
                      }
                      data-testid="create-take-use"
                    >
                      {on ? (
                        <>
                          <Check className="ico" />
                          {t('create.takes.picked')}
                        </>
                      ) : (
                        t('create.takes.use')
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      {act.error && <div className="cr-err">{act.error}</div>}
    </div>
  );
}

function ManualPrompts({ eid, n, onImported }: { eid: string; n: number; onImported: () => void }) {
  const c = useCreate();
  const { data } = useCreateLoad((x) => x.prompts(eid), [eid]);
  const [copied, setCopied] = useState<string | null>(null);
  const act = useAction();
  return (
    <div className="card" data-testid="create-manual">
      <h3>{t('create.takes.manualTitle', { n })}</h3>
      <div className="muted" style={{ fontSize: 15, margin: '6px 0 12px' }}>
        {t('create.takes.manualBody')}
      </div>
      {(data?.prompts ?? []).map((p) => (
        <div key={p.unit} className="row" style={{ alignItems: 'flex-start', padding: '10px 0', borderTop: '1px solid var(--border)' }}>
          <b className="num" style={{ width: 48 }}>
            {p.unit}
          </b>
          <span className="muted" style={{ flex: 1, fontSize: 14, userSelect: 'text' }}>
            {p.prompt}
          </span>
          <button
            className="btn sm"
            onClick={() =>
              void window.desk.copyText(p.prompt).then(() => {
                setCopied(p.unit);
                setTimeout(() => setCopied(null), 1500);
              })
            }
          >
            <Copy className="ico" />
            {copied === p.unit ? t('create.takes.copied') : t('create.takes.copy')}
          </button>
        </div>
      ))}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" onClick={() => void window.desk.openExternal(JIMENG)}>
          <ExternalLink className="ico" />
          {t('create.takes.openSite')}
        </button>
        <button
          className="btn primary"
          disabled={act.busy}
          onClick={() =>
            void act.run(async () => {
              if (!c) return;
              const files = await window.desk.openFiles('video');
              if (!files.length) return;
              await c.importTakes(eid, files);
              onImported();
            })
          }
        >
          <Upload className="ico" />
          {t('create.takes.addFiles')}
        </button>
      </div>
      {act.error && <div className="cr-err">{act.error}</div>}
    </div>
  );
}
