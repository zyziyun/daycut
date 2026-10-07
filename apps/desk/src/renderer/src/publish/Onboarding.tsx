// First visit, no publishing account yet: one question instead of a wall of 20 platforms. Picking adds the
// accounts (nothing is opened, no network); step 2 is signing in on 发布 → 账号.
import { useState } from 'react';
import { Check } from 'lucide-react';
import { nextAccountLabel } from '../../../shared/channels';
import type { Adapter } from '../../../shared/publish/adapterSchema';
import { t } from '../i18n';
import { go } from '../lib/router';
import { platformName } from '../v4/Home';
import { PlatformIcon } from '../v4/PlatformIcon';
import { errText } from '../v4/msg';
import { useUi } from '../v4/ui';

const ZH = ['xiaohongshu', 'douyin', 'wechat-channels', 'bilibili'];
const INTL = ['youtube', 'tiktok', 'instagram', 'x'];

export function PublishOnboarding({ adapters, onDone }: { adapters: Adapter[]; onDone: () => void }) {
  const ui = useUi();
  const [sel, setSel] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const tile = (pf: string) => {
    const on = sel.includes(pf);
    return (
      <button key={pf} className={`pb-obtile ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => setSel(on ? sel.filter((x) => x !== pf) : [...sel, pf])} data-testid="pb-ob-tile" data-pf={pf}>
        {on && (
          <span className="ck">
            <Check className="ico" />
          </span>
        )}
        <PlatformIcon id={pf} size={40} />
        <span>{platformName(pf)}</span>
      </button>
    );
  };
  const go2 = async () => {
    setBusy(true);
    try {
      for (const pf of sel) {
        const a = adapters.find((x) => x.packagePlatforms.includes(pf));
        if (a) await window.desk.publish.addAccount(a.id, nextAccountLabel([]));
      }
      onDone();
      go({ name: 'channels' });
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="pb-ob" data-testid="pb-onboarding">
      <div className="pb-obcard">
        <span className="pb-obstep">{t('pb.ob.step')}</span>
        <h2>{t('pb.ob.title')}</h2>
        <p className="muted">{t('pb.ob.body')}</p>
        <h5>{t('pb.ob.zh')}</h5>
        <div className="pb-obgrid">{ZH.map(tile)}</div>
        <h5>{t('pb.ob.intl')}</h5>
        <div className="pb-obgrid">{INTL.map(tile)}</div>
        <div className="pb-obfoot">
          <p className="muted">{t('pb.ob.foot')}</p>
          <button className="btn primary lg" disabled={!sel.length || busy} onClick={() => void go2()} data-testid="pb-ob-continue">
            {t('pb.ob.continue', { n: sel.length })}
          </button>
        </div>
      </div>
    </div>
  );
}
