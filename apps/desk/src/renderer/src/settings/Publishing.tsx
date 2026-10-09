// Settings › Publishing accounts (ux/settings-redesign A4): each account's login state (read from the account's own
// session, so a page she is signed in to counts); the signed-out one gets the page's single primary "Sign in".
// Accounts on platforms she does not post to are listed apart and never nag. Below: how scheduled posts reach her
// (Open at login + menu bar) and the official posting APIs she may connect (YouTube today; the others documented).
import { useEffect, useState } from 'react';
import { ChevronRight, MoreHorizontal, Plus, Send } from 'lucide-react';
import { CAPS } from '../../../shared/edition';
import type { ApiStatusMsg } from '../../../shared/publish/apiPlatforms';
import { fmtAgo, t } from '../i18n';
import { href } from '../lib/router';
import { inUse, useChannels, useChosenPlatforms } from '../v4/Channels';
import { errText } from '../v4/msg';
import { PlatformIcon } from '../v4/PlatformIcon';
import { platformName } from '../v4/Home';
import { useUi } from '../v4/ui';
import { Dot, Group, Page, Row, Sheet, Toggle } from './kit';
import type { SettingsCtx } from './registry';
import { adapterShort, signInChannel } from './status';

export function PublishingSection(ctx: Partial<SettingsCtx>) {
  const ui = useUi();
  const { adapters, channels } = useChannels();
  const chosen = useChosenPlatforms();
  const mine = inUse(channels, adapters, chosen);
  const others = channels.filter((c) => !mine.includes(c));
  const firstOut = mine.find((c) => c.login.state === 'out');
  const signed = mine.filter((c) => c.login.state === 'in').length;
  const row = (c: (typeof channels)[number], muted: boolean) => {
    const a = adapters.find((x) => x.id === c.adapterId);
    const st = c.login.state;
    return (
      <div key={`${c.adapterId}/${c.account}`} className={`s2-row ${muted ? 's2-muted' : ''}`} data-testid="settings-channel" data-adapter={c.adapterId} data-in-use={!muted}>
        {a ? <PlatformIcon id={a.packagePlatforms[0]} size={36} /> : <span className="s2-pico plain" />}
        <div className="s2-rtext">
          <div className="s2-rlabel">{a ? adapterShort(a) : c.adapterId}</div>
          <div className="s2-rhint">
            {c.name === c.account ? c.account : `${c.name} · ${c.account}`}
            {muted && ` · ${t('pl.set.notUsed')}`}
          </div>
        </div>
        <div className="s2-rctl">
          <span className={`s2-pill ${st === 'in' ? 'ok' : st === 'out' && !muted ? 'warn' : 'off'}`} data-testid="channel-state" data-state={st}>
            <Dot tone={st === 'in' ? 'ok' : st === 'out' && !muted ? 'warn' : 'off'} />
            {t(`ch.state.${st}`)}
          </span>
          {c.login.at && st === 'in' && <span className="s2-val">{t('s2.ai.checked', { when: fmtAgo(Date.parse(c.login.at) / 1000) })}</span>}
          {st !== 'in' && !muted && (
            <button className={`btn ${c === firstOut ? 'primary' : ''}`} onClick={() => signInChannel(c.adapterId, c.account)} data-testid="settings-channel-signin">
              {t('ch.login')}
            </button>
          )}
          <button
            className="btn ghost icon"
            aria-label={t('s2.ai.more')}
            onClick={(e) =>
              ui.menu(e, [
                { label: st === 'in' ? t('ch.relogin') : t('ch.login'), run: () => signInChannel(c.adapterId, c.account) },
                { label: t('s2.pub.manage'), run: () => (location.hash = href({ name: 'channels' })) },
              ])
            }
          >
            <MoreHorizontal className="ico" />
          </button>
        </div>
      </div>
    );
  };
  return (
    <Page title={t('set.channels')} lead={t('s2.pub.lead')} testId="settings-channels">
      <Group title={mine.length ? <span data-testid="settings-signed-count">{t('pl.set.signedIn', { n: signed, total: mine.length })}</span> : undefined}>
        <div className="s2-card">
          {!channels.length && <div className="s2-row s2-rhint">{t('s2.pub.none')}</div>}
          {mine.map((c) => row(c, false))}
          {others.map((c) => row(c, true))}
          <a className="s2-row s2-addrow" href={href({ name: 'channels' })} data-testid="open-channels">
            <Plus className="ico" />
            {t('s2.pub.add')}
          </a>
        </div>
      </Group>
      <Group title={t('pl.set.scheduled')} testId="settings-scheduled">
        <Row label={t('pl.set.atLogin')} hint={t('pl.set.atLoginHint')}>
          <Toggle checked={!!ctx.settings?.openAtLogin} onChange={(v) => void ctx.save?.({ openAtLogin: v })} label={t('pl.set.atLogin')} testId="open-at-login" />
        </Row>
        <div className="s2-row s2-rhint">{t('pl.set.how')}</div>
      </Group>
      {CAPS.youtubeApi && <ApiGroup />}
      <p className="s2-foot">
        <Send className="ico" />
        {t('s2.pub.foot')}
        <a className="s2-link" href={href({ name: 'channels' })}>
          {t('s2.pub.footLink')}
          <ChevronRight className="ico" />
        </a>
      </p>
    </Page>
  );
}

function ApiGroup() {
  const ui = useUi();
  const [st, setSt] = useState<ApiStatusMsg[] | null>(null);
  const [sheet, setSheet] = useState<'client' | 'connect' | null>(null);
  const [busy, setBusy] = useState(false);
  const [cid, setCid] = useState('');
  const [secret, setSecret] = useState('');
  useEffect(() => {
    void window.desk.publish.api.status().then(setSt).catch(() => undefined);
  }, []);
  const run = async (fn: () => Promise<ApiStatusMsg[]>) => {
    setBusy(true);
    try {
      setSt(await fn());
      return true;
    } catch (e) {
      ui.toast(errText(e), { error: true });
      return false;
    } finally {
      setBusy(false);
    }
  };
  if (!st) return null;
  const yt = st.find((a) => a.id === 'youtube')!;
  return (
    <Group title={t('pl.api.title')} testId="settings-api">
      <div className="s2-row s2-rhint">{t('pl.api.lead')}</div>
      <Row label={<span className="row" style={{ gap: 8 }}><PlatformIcon id="youtube" size={20} />{platformName('youtube')}</span>} hint={yt.connected ? t('pl.api.ytConnected', { when: yt.connectedAt ? fmtAgo(Date.parse(yt.connectedAt) / 1000) : '' }) : yt.hasClient ? t('pl.api.ytReady') : t('pl.api.ytNeedsClient')} testId="api-youtube">
        {yt.connected ? (
          <>
            <Toggle checked={yt.auto} onChange={(v) => void run(() => window.desk.publish.api.setAuto(v))} label={t('pl.api.auto')} testId="api-youtube-auto" />
            <button className="btn ghost" disabled={busy} onClick={() => void run(() => window.desk.publish.api.disconnect())} data-testid="api-youtube-disconnect">
              {t('pl.api.disconnect')}
            </button>
          </>
        ) : yt.hasClient ? (
          <>
            <button className="btn primary" disabled={busy || !yt.keychain} onClick={() => setSheet('connect')} data-testid="api-youtube-connect">
              {t('pl.api.connect')}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => void run(() => window.desk.publish.api.disconnect(true))}>
              {t('pl.api.forgetClient')}
            </button>
          </>
        ) : (
          <button className="btn" disabled={!yt.keychain} onClick={() => setSheet('client')} data-testid="api-youtube-client">
            {t('pl.api.addClient')}
          </button>
        )}
      </Row>
      {st
        .filter((a) => a.availability === 'later')
        .map((a) => (
          <Row key={a.id} label={<span className="row" style={{ gap: 8 }}><PlatformIcon id={a.platforms[0]} size={20} />{t(`pl.api.name.${a.id}` as 'pl.api.name.tiktok')}</span>} hint={t(`pl.api.later.${a.id}` as 'pl.api.later.tiktok')} testId={`api-${a.id}`}>
            <span className="s2-pill off">{t('pl.api.notYet')}</span>
          </Row>
        ))}
      {!yt.keychain && <div className="s2-row s2-rhint pb-amber">{t('pl.api.noKeychain')}</div>}
      {sheet === 'client' && (
        <Sheet
          title={t('pl.api.clientTitle')}
          onClose={() => setSheet(null)}
          testId="api-client-sheet"
          footer={
            <button className="btn primary" disabled={busy || !cid.trim() || !secret.trim()} onClick={() => void run(() => window.desk.publish.api.setClient(cid, secret)).then((ok) => ok && (setSheet(null), setSecret('')))} data-testid="api-client-save">
              {t('pl.api.saveClient')}
            </button>
          }
        >
          <p className="muted small">{t('pl.api.clientHow')}</p>
          <label className="col small" style={{ gap: 4 }}>
            {t('pl.api.clientId')}
            <input className="input mono" value={cid} onChange={(e) => setCid(e.target.value)} placeholder="1234-abc.apps.googleusercontent.com" data-testid="api-client-id" />
          </label>
          <label className="col small" style={{ gap: 4 }}>
            {t('pl.api.clientSecret')}
            <input className="input mono" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} data-testid="api-client-secret" />
          </label>
          <p className="muted small">{t('pl.api.private')}</p>
        </Sheet>
      )}
      {sheet === 'connect' && (
        <Sheet
          title={t('pl.api.connectTitle')}
          onClose={() => setSheet(null)}
          testId="api-connect-sheet"
          footer={
            <button className="btn primary" disabled={busy} onClick={() => void run(() => window.desk.publish.api.connect()).then((ok) => ok && setSheet(null))} data-testid="api-connect-go">
              {busy ? t('pl.api.waiting') : t('pl.api.openBrowser')}
            </button>
          }
        >
          <p>{t('pl.api.scopesLead')}</p>
          <ul className="mono small">
            {yt.scopes.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <p className="muted small">{t('pl.api.scopesWhat')}</p>
          <p className="muted small">{t('pl.api.audit')}</p>
        </Sheet>
      )}
    </Group>
  );
}
