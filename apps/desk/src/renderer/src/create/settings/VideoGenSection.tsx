// Settings › Video generation (C12): monthly limit, services (keys go to the OS keychain through the existing
// secrets flow and reach the engine as environment variables - never typed into a chat, never written to a file),
// and what runs on this Mac (optional, with licence notes). Plus the Labs card on the main Settings page.
import { useEffect, useState } from 'react';
import { ArrowLeft, Cpu, Image as ImageIcon, Mic, Monitor, Plus } from 'lucide-react';
import type { SecretName, SecretsStatusMsg, SettingsMsg } from '../../../../shared/deskApi';
import type { ProviderStatus } from '../../../../shared/create';
import { yuan } from '../../../../shared/create';
import { t } from '../../i18n';
import { href } from '../../lib/router';
import { useAction, useCreate, useCreateLoad } from '../api';
import { localGenEnabled, useCreateEnabled } from '../flag';
import { createHref } from '../routes';
import { PluginsCard } from './PluginsCard';

const CAPS = [100, 300, 500, 1000, 0];

interface Svc {
  id: string;
  key: SecretName | null;
  glyph: string;
  color: string;
  name: 'create.set.kling' | 'create.set.minimax' | 'create.set.jimeng' | 'create.set.veo' | 'create.set.ark';
  sub: 'create.set.klingSub' | 'create.set.minimaxSub' | 'create.set.jimengSub' | 'create.set.veoSub' | 'create.set.arkSub';
}

const SERVICES: Svc[] = [
  { id: 'kling-mcp', key: 'kling', glyph: 'K', color: 'var(--src-kling)', name: 'create.set.kling', sub: 'create.set.klingSub' },
  { id: 'minimax', key: 'minimax', glyph: 'H', color: 'var(--src-hailuo)', name: 'create.set.minimax', sub: 'create.set.minimaxSub' },
  { id: 'jimeng', key: null, glyph: 'J', color: 'var(--src-seed)', name: 'create.set.jimeng', sub: 'create.set.jimengSub' },
  { id: 'veo', key: 'gemini', glyph: 'G', color: 'var(--src-veo)', name: 'create.set.veo', sub: 'create.set.veoSub' },
  { id: 'seedance-ark', key: 'ark', glyph: 'S', color: '#5c6b8a', name: 'create.set.ark', sub: 'create.set.arkSub' },
];

export function VideoGenSection({ onSettings }: { onSettings?: (s: SettingsMsg) => void }) {
  const c = useCreate();
  const providers = useCreateLoad((x) => x.providers(), []);
  const spend = useCreateLoad((x) => x.spend(), []);
  const [secrets, setSecrets] = useState<SecretsStatusMsg | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [val, setVal] = useState('');
  const [more, setMore] = useState(false);
  const [which, setWhich] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [license, setLicense] = useState(localGenEnabled());
  const act = useAction();
  useEffect(() => {
    void window.desk.secrets.status().then(setSecrets);
  }, []);
  const byId = new Map<string, ProviderStatus>((providers.data?.providers ?? []).map((p) => [p.id, p]));
  const cap = spend.data?.cap ?? null;
  const used = spend.data?.used ?? 0;

  const saveKey = (k: SecretName) =>
    act.run(async () => {
      setSecrets(await window.desk.secrets.set(k, val.trim()));
      setVal('');
      setOpen(null);
      setNote(t('create.set.restart'));
      await window.desk.restartEngine();
      providers.reload();
    });

  return (
    <div className="cr cr-set" data-testid="create-settings">
      <a className="back" href={href({ name: 'settings' })} style={{ fontSize: 15 }}>
        <ArrowLeft className="ico" /> {t('create.set.back')}
      </a>
      <h1 style={{ marginTop: 12 }}>{t('create.set.title')}</h1>
      <div className="sub">{t('create.set.sub')}</div>

      <div className="card cr-limit" data-testid="create-cap">
        <div className="ft">
          <div style={{ flex: 1 }}>
            <h3>{t('create.set.limit')}</h3>
            <div className="muted" style={{ fontSize: 15, marginTop: 4 }}>
              {t('create.set.limitSub', { used: yuan(used) })}
            </div>
          </div>
          <select
            value={cap ?? 0}
            onChange={(e) =>
              void act.run(async () => {
                if (!c) return;
                await c.setCap(Number(e.target.value) || 100000);
                spend.reload();
              })
            }
            aria-label={t('create.set.limit')}
            data-testid="create-cap-select"
          >
            {CAPS.map((v) => (
              <option key={v} value={v}>
                {v ? yuan(v) : t('create.set.noLimit')}
              </option>
            ))}
            {cap && !CAPS.includes(cap) && <option value={cap}>{cap >= 100000 ? t('create.set.noLimit') : yuan(cap)}</option>}
          </select>
        </div>
        <div className="cr-meter">
          <i className="st" style={{ width: `${cap ? Math.min(100, (used / cap) * 100) : 0}%` }} />
        </div>
      </div>

      <div className="lbl">
        <span>{t('create.set.services')}</span>
        <button className="link" onClick={() => setWhich(!which)}>
          {t('create.set.which')}
        </button>
      </div>
      {which && (
        <div className="muted" style={{ fontSize: 15, marginBottom: 10 }}>
          {t('create.set.whichBody')}
        </div>
      )}
      <div className="card cr-svc" data-testid="create-services">
        {SERVICES.map((s) => {
          const st = byId.get(s.id);
          const hasKey = s.key ? !!secrets?.keys[s.key] : true;
          return (
            <div key={s.id}>
              <div className="row" data-testid={`create-svc-${s.id}`}>
                <span className="lg" style={{ background: s.color }}>
                  {s.glyph}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="t1">{t(s.name)}</div>
                  <div className="t2">{t(s.sub)}</div>
                </div>
                <div className="right">
                  {s.key === null ? (
                    <span className="row" style={{ gap: 8 }}>
                      <i className="dot" />
                      {t('create.set.browser')}
                    </span>
                  ) : hasKey ? (
                    <>
                      <span className="row" style={{ gap: 8 }}>
                        <i className="dot done" />
                        {st?.balance ? t('create.set.credits', { n: st.balance }) : t('create.set.ready')}
                      </span>
                      <button className="link" onClick={() => setOpen(open === s.id ? null : s.id)}>
                        {t('create.set.replace')}
                      </button>
                      <button
                        className="link"
                        onClick={() =>
                          void act.run(async () => {
                            if (s.key) setSecrets(await window.desk.secrets.clear(s.key));
                            await window.desk.restartEngine();
                            providers.reload();
                          })
                        }
                      >
                        {t('create.set.remove')}
                      </button>
                    </>
                  ) : (
                    <button className="link" onClick={() => setOpen(open === s.id ? null : s.id)} data-testid={`create-add-key-${s.id}`}>
                      {s.id === 'kling-mcp' ? t('create.set.addToken') : t('create.set.addKey')}
                    </button>
                  )}
                </div>
              </div>
              {open === s.id && s.key && (
                <div className="keyrow">
                  <div className="col" style={{ flex: 1 }}>
                    {s.id === 'kling-mcp' && <div className="muted">{t('create.set.klingHow')}</div>}
                    {secrets?.backend !== 'keychain' && <div className="cr-err">{t('create.set.keychainOff')}</div>}
                    <div className="row">
                      <input type="password" autoComplete="off" spellCheck={false} value={val} onChange={(e) => setVal(e.target.value)} placeholder={t('create.set.paste')} aria-label={t('create.set.paste')} />
                      <button className="btn primary" disabled={val.trim().length < 8 || act.busy || secrets?.backend !== 'keychain'} onClick={() => void saveKey(s.key as SecretName)}>
                        {t('create.set.save')}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        <div className="row">
          <span className="lg mute">
            <Plus className="ico" />
          </span>
          <div>
            <div className="t1">{t('create.set.more')}</div>
            <div className="t2">{more ? t('create.set.moreBody') : t('create.set.moreSub')}</div>
          </div>
          <div className="right">
            <button className="link" onClick={() => setMore(!more)}>
              {more ? t('create.set.hide') : t('create.set.show')}
            </button>
          </div>
        </div>
      </div>
      {note && <div className="muted" style={{ marginTop: 10 }}>{note}</div>}
      {act.error && <div className="cr-err" style={{ marginTop: 10 }}>{act.error}</div>}

      <div className="lbl">
        <span>{t('create.set.local')}</span>
      </div>
      <div className="card cr-svc" data-testid="create-local">
        <div className="row">
          <span className="lg mute">
            <Cpu className="ico" />
          </span>
          <div style={{ minWidth: 0 }}>
            <div className="t1">{t('create.set.drafts')}</div>
            <div className="t2">{t('create.set.draftsSub')}</div>
            <label className="cr-labs" style={{ marginTop: 8, fontSize: 15 }}>
              <input type="checkbox" checked={license} onChange={(e) => setLicense(e.target.checked)} />
              {t('create.set.draftsLicense')}
            </label>
          </div>
          <div className="right">
            {localGenEnabled() ? (
              <span className="row" style={{ gap: 8 }}>
                <i className="dot done" />
                {t('create.set.on')}
              </span>
            ) : (
              <>
                <span className="muted">{t('create.set.notSetUp')}</span>
                <button
                  className="link"
                  disabled={!license}
                  onClick={() =>
                    void window.desk.setSettings({ createLocalGen: true }).then((s) => {
                      onSettings?.(s);
                      void window.desk.restartEngine();
                    })
                  }
                >
                  {t('create.set.setUp')}
                </button>
              </>
            )}
          </div>
        </div>
        <div className="row">
          <span className="lg mute">
            <ImageIcon className="ico" />
          </span>
          <div>
            <div className="t1">{t('create.set.stills')}</div>
            <div className="t2">{t('create.set.stillsSub')}</div>
          </div>
          <div className="right">
            <span className="row" style={{ gap: 8 }}>
              <i className="dot done" />
              {t('create.set.installed')}
            </span>
          </div>
        </div>
        <div className="row">
          <span className="lg mute">
            <Mic className="ico" />
          </span>
          <div>
            <div className="t1">{t('create.set.voices')}</div>
            <div className="t2">{t('create.set.voicesSub')}</div>
          </div>
          <div className="right muted">{t('create.set.later')}</div>
        </div>
        <div className="row">
          <span className="lg mute">
            <Monitor className="ico" />
          </span>
          <div>
            <div className="t1">{t('create.set.pc')}</div>
            <div className="t2">{t('create.set.pcSub')}</div>
          </div>
          <div className="right muted">{t('create.set.later')}</div>
        </div>
      </div>
      <div className="cr-lic">{t('create.set.licenses')}</div>
      <PluginsCard />
    </div>
  );
}

/** Main Settings page: the Labs switch for the Create page, and (on) the way to Video generation. */
export function CreateSettingsCard({ onChange }: { onChange: (s: SettingsMsg) => void }) {
  const on = useCreateEnabled();
  return (
    <div className="card col" data-testid="settings-create">
      <label className="cr-labs">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => void window.desk.setSettings({ createPage: e.target.checked }).then(onChange)}
          data-testid="settings-create-toggle"
        />
        <span>
          <b style={{ fontWeight: 500 }}>{t('create.set.labs')}</b>
          <div className="muted">{t('create.set.labsSub')}</div>
        </span>
      </label>
      {on && (
        <a className="row" href={createHref({ screen: 'settings' })} style={{ textDecoration: 'none', color: 'inherit', marginTop: 8 }} data-testid="settings-video-link">
          <span style={{ flex: 1 }}>
            <b style={{ fontWeight: 500 }}>{t('create.set.videoRow')}</b>
            <div className="muted">{t('create.set.videoRowSub')}</div>
          </span>
          <span className="link">{t('create.set.open')}</span>
        </a>
      )}
    </div>
  );
}
