// Settings › Publishing accounts (ux/settings-redesign A4): each account's login state; the signed-out one gets the
// page's single primary "Sign in" (opens its login page in the built-in browser on 发布 → 账号).
import { ChevronRight, MoreHorizontal, Plus, Send } from 'lucide-react';
import { fmtAgo, t } from '../i18n';
import { href } from '../lib/router';
import { useChannels } from '../v4/Channels';
import { PlatformIcon } from '../v4/PlatformIcon';
import { useUi } from '../v4/ui';
import { Dot, Page } from './kit';
import { adapterShort, signInChannel } from './status';

export function PublishingSection() {
  const ui = useUi();
  const { adapters, channels } = useChannels();
  const firstOut = channels.find((c) => c.login.state === 'out');
  return (
    <Page title={t('set.channels')} lead={t('s2.pub.lead')} testId="settings-channels">
      <div className="s2-card">
        {!channels.length && <div className="s2-row s2-rhint">{t('s2.pub.none')}</div>}
        {channels.map((c) => {
          const a = adapters.find((x) => x.id === c.adapterId);
          const st = c.login.state;
          return (
            <div key={`${c.adapterId}/${c.account}`} className="s2-row" data-testid="settings-channel" data-adapter={c.adapterId}>
              {a ? <PlatformIcon id={a.packagePlatforms[0]} size={36} /> : <span className="s2-pico plain" />}
              <div className="s2-rtext">
                <div className="s2-rlabel">{a ? adapterShort(a) : c.adapterId}</div>
                <div className="s2-rhint">{c.name === c.account ? c.account : `${c.name} · ${c.account}`}</div>
              </div>
              <div className="s2-rctl">
                <span className={`s2-pill ${st === 'in' ? 'ok' : st === 'out' ? 'warn' : 'off'}`} data-testid="channel-state" data-state={st}>
                  <Dot tone={st === 'in' ? 'ok' : st === 'out' ? 'warn' : 'off'} />
                  {t(`ch.state.${st}`)}
                </span>
                {c.login.at && st === 'in' && <span className="s2-val">{t('s2.ai.checked', { when: fmtAgo(Date.parse(c.login.at) / 1000) })}</span>}
                {st !== 'in' && (
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
        })}
        <a className="s2-row s2-addrow" href={href({ name: 'channels' })} data-testid="open-channels">
          <Plus className="ico" />
          {t('s2.pub.add')}
        </a>
      </div>
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
