// 发布账号: the creator's own publishing accounts (her 小红书号, 抖音号, YouTube channel ...), one row per account with
// the login state the built-in browser last saw, default post times, and Sign in / Open upload page - the platform
// page opens on the right in that account's own session. Replaces the old workspace / client switcher: a solo
// creator has accounts, not workspaces.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ExternalLink, LogIn, Plus, Trash2 } from 'lucide-react';
import type { ChannelMsg } from '../../../shared/channels';
import { nextAccountLabel } from '../../../shared/channels';
import type { PublishStateMsg } from '../../../shared/deskApi';
import type { Adapter } from '../../../shared/publish/adapterSchema';
import { Modal } from '../components/ui';
import { fmtAgo, getLang, t } from '../i18n';
import { Empty } from './kit';
import { errText } from './msg';
import { sortPlatforms } from '../../../shared/platforms';
import { PlatformIcon } from './PlatformIcon';
import { useUi } from './ui';

export const adapterName = (a: Adapter) => (getLang() === 'zh-CN' ? a.nameZh : a.name);

export function LoginPill({ c }: { c: ChannelMsg }) {
  const cls = c.login.state === 'in' ? 'done' : c.login.state === 'out' ? 'you' : '';
  return (
    <span className="muted small" data-testid="channel-state" data-state={c.login.state} title={c.login.at ? t('ch.seen', { when: fmtAgo(Date.parse(c.login.at) / 1000) }) : undefined}>
      <i className={`dot ${cls}`} /> {t(`ch.state.${c.login.state}`)}
    </span>
  );
}

/** Adapters + channels, refreshed when the built-in browser reports a page (the login state may have changed). */
export function useChannels() {
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [channels, setChannels] = useState<ChannelMsg[]>([]);
  const reload = useCallback(async () => {
    const [a, c] = await Promise.all([window.desk.publish.adapters(), window.desk.publish.channels()]);
    setAdapters(a.adapters);
    setChannels(c);
  }, []);
  useEffect(() => {
    void reload().catch(() => undefined);
    let tmr: ReturnType<typeof setTimeout> | null = null;
    const off = window.desk.on('publish:state', () => {
      if (tmr) clearTimeout(tmr);
      tmr = setTimeout(() => void reload().catch(() => undefined), 3500); // after the page-signal check in main
    });
    return () => {
      off();
      if (tmr) clearTimeout(tmr);
    };
  }, [reload]);
  return { adapters, channels, setChannels, reload };
}

/** Adapters in the shared platform order (English / global, Chinese, other); inside a group the platforms with a
 * connected account first. */
export function sortAdapters(adapters: Adapter[], channels: Pick<ChannelMsg, 'adapterId'>[]): Adapter[] {
  const connected = adapters.filter((a) => channels.some((c) => c.adapterId === a.id)).flatMap((a) => a.packagePlatforms);
  return sortPlatforms(adapters, (a) => a.packagePlatforms[0], connected);
}

/** Platform ids she has a publishing account for (a YouTube channel counts for long-form and Shorts). */
export function useConnectedPlatforms(): string[] {
  const { adapters, channels } = useChannels();
  return adapters.filter((a) => channels.some((c) => c.adapterId === a.id)).flatMap((a) => a.packagePlatforms);
}

export function Channels() {
  const ui = useUi();
  const { adapters, channels, setChannels } = useChannels();
  const [sel, setSel] = useState<{ adapterId: string; account: string } | null>(null);
  const [bstate, setBstate] = useState<PublishStateMsg | null>(null);
  const [editing, setEditing] = useState<ChannelMsg | null>(null);
  const [removing, setRemoving] = useState<ChannelMsg | null>(null);

  useEffect(() => {
    const off = window.desk.on('publish:state', (s) => setBstate(s as PublishStateMsg));
    return () => {
      off();
      void window.desk.publish.hide();
    };
  }, []);

  // ------------------------------------------------ embedded browser placement (same as the publish page)
  const slot = useRef<HTMLDivElement>(null);
  const overlay = editing !== null || removing !== null;
  const browserOpen = !!bstate && !!sel && bstate.adapterId === sel.adapterId && bstate.account === sel.account;
  useLayoutEffect(() => {
    const el = slot.current;
    if (!el) return;
    const send = () => {
      const r = el.getBoundingClientRect();
      const show = browserOpen && !overlay;
      void window.desk.publish.setBounds(show ? { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) } : { x: 0, y: 0, width: 0, height: 0 });
    };
    send();
    const ro = new ResizeObserver(send);
    ro.observe(el);
    window.addEventListener('resize', send);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', send);
    };
  }, [browserOpen, overlay]);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    }
  };
  const open = (c: { adapterId: string; account: string }, page: 'login' | 'upload', fresh = false) =>
    run(async () => {
      setSel({ adapterId: c.adapterId, account: c.account });
      await window.desk.publish.open(c.adapterId, c.account, page);
      if (!fresh) await window.desk.publish.navigate(page); // an account opened before keeps its page otherwise
    });
  // Settings › Publishing / the status line asked to sign in to one account: open its login page here
  useEffect(() => {
    let want: { adapterId: string; account: string } | null = null;
    try {
      want = JSON.parse(sessionStorage.getItem('ch.login') || 'null');
    } catch {
      want = null;
    }
    if (!want || !channels.some((c) => c.adapterId === want!.adapterId && c.account === want!.account)) return;
    sessionStorage.removeItem('ch.login');
    void open(want, 'login');
    // once, when the accounts have loaded
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels]);
  const add = (a: Adapter) =>
    run(async () => {
      const label = nextAccountLabel(channels.filter((c) => c.adapterId === a.id).map((c) => c.account));
      await window.desk.publish.addAccount(a.id, label);
      setChannels(await window.desk.publish.channels());
      void open({ adapterId: a.id, account: label }, 'login', true);
    });

  const signedIn = channels.filter((c) => c.login.state === 'in').length;

  return (
    <div className="scroll" data-testid="channels">
      <div className="pg wide">
        <div className="ph">
          <div>
            <h1>{t('ch.title')}</h1>
            <p>{t('ch.subtitle')}</p>
          </div>
          <span className="sp" />
          {channels.length > 0 && <span className="muted num">{t('ch.status', { n: signedIn, total: channels.length })}</span>}
        </div>
        <div className="pubg" style={{ gridTemplateColumns: 'minmax(340px, 420px) 1fr' }}>
          <aside className="col" style={{ gap: 10 }} data-testid="channel-list">
            {!channels.length && <Empty title={t('ch.empty')} hint={t('ch.emptyHint')} />}
            {sortAdapters(adapters, channels)
              .map((a) => {
              const mine = channels.filter((c) => c.adapterId === a.id);
              return (
                <div key={a.id} className="card col" style={{ gap: 6 }} data-testid="channel-platform" data-adapter={a.id}>
                  <div className="row" style={{ gap: 8 }}>
                    <PlatformIcon id={a.packagePlatforms[0]} size={16} title={a.name} />
                    <b style={{ flex: 1 }}>{adapterName(a)}</b>
                    <span className="muted small">{t('ch.platformAccounts', { n: mine.length })}</span>
                    <button className="btn ghost sm" onClick={() => void add(a)} data-testid="channel-add" aria-label={mine.length ? t('ch.addAnother') : t('ch.add')} data-tip={mine.length ? t('ch.addAnother') : t('ch.add')}>
                      <Plus className="ico" />
                      {!mine.length && t('ch.add')}
                    </button>
                  </div>
                  {a.status === 'todo' && mine.length > 0 && <span className="muted small">{t('ch.fillTodo')}</span>}
                  {mine.map((c) => {
                    const on = sel?.adapterId === c.adapterId && sel.account === c.account;
                    return (
                      <div key={c.account} className={`row ${on ? 'on' : ''}`} style={{ gap: 8, flexWrap: 'wrap', padding: '6px 8px', borderRadius: 8, background: on ? 'var(--accent-soft)' : 'var(--surface-2)' }} data-testid="channel-row" data-account={c.account}>
                        <div className="col" style={{ flex: 1, minWidth: 0, gap: 2 }}>
                          <span className="clamp1">{c.name}</span>
                          <span className="row small" style={{ gap: 8 }}>
                            <LoginPill c={c} />
                            {c.times.length > 0 && <span className="muted num">{c.times.join(' · ')}</span>}
                          </span>
                        </div>
                        <button className="btn sm" onClick={() => void open(c, 'login')} data-testid="channel-login">
                          <LogIn className="ico" />
                          {c.login.state === 'in' ? t('ch.relogin') : t('ch.login')}
                        </button>
                        <button className="btn ghost icon sm" onClick={() => void open(c, 'upload')} aria-label={t('ch.openUpload')} data-tip={t('ch.openUpload')} data-testid="channel-upload">
                          <ExternalLink className="ico" />
                        </button>
                        <button className="btn ghost sm" onClick={() => setEditing(c)} data-testid="channel-edit">
                          {t('ch.edit')}
                        </button>
                        <button className="btn ghost icon sm" onClick={() => setRemoving(c)} aria-label={t('ch.remove')} data-tip={t('ch.remove')} data-testid="channel-remove">
                          <Trash2 className="ico" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </aside>
          <div className="col" style={{ gap: 6, minHeight: 560 }}>
            <div className="browser-bar">
              <button className="btn sm" disabled={!browserOpen || !bstate?.canGoBack} onClick={() => window.desk.publish.navigate('back')} aria-label={t('ch.back')}>
                ←
              </button>
              <button className="btn sm" disabled={!browserOpen} onClick={() => window.desk.publish.navigate('reload')} aria-label={t('ch.reload')}>
                ⟳
              </button>
              <span className="url mono">{browserOpen ? `${bstate?.loading ? '… ' : ''}${bstate?.url}` : ''}</span>
            </div>
            <div className="browser-slot" ref={slot} style={{ flex: 1, minHeight: 520 }} data-testid="channel-slot">
              {!browserOpen && <span>{t('ch.slotHint')}</span>}
            </div>
          </div>
        </div>
      </div>
      {editing && (
        <EditModal
          c={editing}
          onClose={() => setEditing(null)}
          onSave={(name, times) =>
            run(async () => {
              setChannels(await window.desk.publish.updateChannel(editing.adapterId, editing.account, { name, times }));
              setEditing(null);
            })
          }
        />
      )}
      {removing && (
        <RemoveModal
          c={removing}
          onClose={() => setRemoving(null)}
          onOk={(signOut) =>
            run(async () => {
              setChannels(await window.desk.publish.removeAccount(removing.adapterId, removing.account, signOut));
              if (sel?.adapterId === removing.adapterId && sel.account === removing.account) setSel(null);
              setRemoving(null);
            })
          }
        />
      )}
    </div>
  );
}

export function parseTimes(s: string): string[] | null {
  const xs = s
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => (/^\d:\d\d$/.test(x) ? `0${x}` : x));
  return xs.every((x) => /^([01]\d|2[0-3]):[0-5]\d$/.test(x)) && xs.length <= 6 ? xs : null;
}

function EditModal({ c, onClose, onSave }: { c: ChannelMsg; onClose: () => void; onSave: (name: string, times: string[]) => void }) {
  const [name, setName] = useState(c.name === c.account ? '' : c.name);
  const [times, setTimes] = useState(c.times.join(', '));
  const parsed = parseTimes(times);
  return (
    <Modal title={c.name} onClose={onClose}>
      <label className="col small" style={{ gap: 4 }}>
        {t('ch.name')}
        <input className="input" value={name} maxLength={60} placeholder={t('ch.namePh')} onChange={(e) => setName(e.target.value)} data-testid="channel-name" autoFocus />
      </label>
      <label className="col small" style={{ gap: 4 }}>
        {t('ch.times')}
        <input className="input" value={times} placeholder="19:00" onChange={(e) => setTimes(e.target.value)} data-testid="channel-times" />
        <span className="muted">{t('ch.timesHint')}</span>
      </label>
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button className="btn primary" disabled={!parsed} onClick={() => parsed && onSave(name, parsed)} data-testid="channel-save">
          {t('ch.save')}
        </button>
      </div>
    </Modal>
  );
}

function RemoveModal({ c, onClose, onOk }: { c: ChannelMsg; onClose: () => void; onOk: (signOut: boolean) => void }) {
  const [signOut, setSignOut] = useState(true);
  return (
    <Modal title={t('ch.removeTitle', { name: c.name })} onClose={onClose}>
      <div className="muted small">{t('ch.removeBody')}</div>
      <label className="row small" style={{ gap: 6 }}>
        <input type="checkbox" checked={signOut} onChange={(e) => setSignOut(e.target.checked)} />
        {t('ch.signOut')}
      </label>
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button className="btn primary" onClick={() => onOk(signOut)} data-testid="channel-remove-ok">
          {t('ch.remove')}
        </button>
      </div>
    </Modal>
  );
}
