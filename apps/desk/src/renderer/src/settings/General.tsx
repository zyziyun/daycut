// Settings › General: one status line with one action, Appearance (language, theme, accent), How you work
// (platforms for new projects, watched folders, tidy-up, 「我在帮别人做视频」), and the privacy line.
import { useState } from 'react';
import { AlertTriangle, Check, Lock, XCircle } from 'lucide-react';
import { LANGS, LOCALES, fmtList, t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { href } from '../lib/router';
import { WatchFoldersField } from '../components/WatchFolders';
import { CreateSettingsCard } from '../create';
import { UsageSettingsGroup } from '../components/UsageConsent';
import { LiteCard } from '../components/Lite';
import { IS_LITE } from '../../../shared/edition';
import { PlatformPicker } from '../screens/Clients';
import { PLATFORM_CHOICES } from '../screens/NewBatch';
import { Group, Page, Row, Segmented, Sheet, Swatches, Toggle } from './kit';
import type { SettingsCtx } from './registry';
import { useStatus } from './status';
import { orderPlatforms } from '../../../shared/platforms';

const TIDY = [0, 7, 30, 90];

function Summary() {
  const st = useStatus();
  const Icon = st.tone === 'ok' ? Check : st.tone === 'error' ? XCircle : AlertTriangle;
  return (
    <div className={`s2-status ${st.tone}`} data-testid="settings-status" data-tone={st.tone}>
      <span className="s2-sicon">
        <Icon className="ico" />
      </span>
      <div className="s2-rtext">
        <b>{st.title}</b>
        <span>{st.body}</span>
      </div>
      {st.action && (
        <button className="btn" onClick={st.action.run} data-testid="settings-status-action">
          {st.action.label}
        </button>
      )}
    </div>
  );
}

export function GeneralSection({ settings: s, save, onChange }: SettingsCtx) {
  const { data: hist } = useHistory();
  useEngine();
  const [sheet, setSheet] = useState<'platforms' | 'watch' | 'privacy' | null>(null);
  const [custom, setCustom] = useState(false);
  const days = s.cleanupDays ?? 0;
  const tidyValue = custom || !TIDY.includes(days) ? 'custom' : String(days);
  const watch = hist?.watch ?? [];
  const folderName = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p;
  const pfNames = orderPlatforms(s.defaultPlatforms ?? []).map((id) => tk(PLATFORM_CHOICES.find((p) => p.id === id)?.label ?? `pf.${id.split(':')[0]}`));
  return (
    <Page title={t('s2.nav.general')} lead={t('s2.general.lead')} testId="settings-general">
      <Summary />
      <LiteCard />
      <Group title={t('s2.appearance')} testId="settings-appearance">
        <Row label={t('s2.language')} hint={t('s2.languageHint')}>
          <Segmented value={s.lang} onChange={(l) => void save({ lang: l })} options={LANGS.map((l) => ({ v: l, label: LOCALES[l].label, testId: `lang-${l}` }))} testId="settings-lang" />
        </Row>
        <Row label={t('s2.theme')}>
          <Segmented
            value={s.theme}
            onChange={(th) => void save({ theme: th })}
            options={[
              { v: 'notebook-light' as const, label: t('s2.theme.light'), testId: 'theme-light' },
              { v: 'studio-dark' as const, label: t('s2.theme.dark'), testId: 'theme-dark' },
            ]}
          />
        </Row>
        <Row label={t('s2.accent')}>
          <Swatches
            value={s.accent ?? 'teal'}
            onChange={(a) => void save({ accent: a })}
            options={[
              { v: 'teal' as const, color: s.theme === 'studio-dark' ? '#4FBFAE' : '#0F7A6C', label: t('set.accent.teal') },
              { v: 'red' as const, color: s.theme === 'studio-dark' ? '#F0435B' : '#D81E3A', label: t('set.accent.red') },
            ]}
          />
        </Row>
      </Group>
      <Group title={t('s2.work')} testId="settings-work">
        <Row label={t('ap.setting')} hint={s.autopilot === false ? t('ap.settingAskHint') : t('ap.settingAutoHint')}>
          <Segmented
            value={s.autopilot === false ? 'ask' : 'auto'}
            onChange={(v) => void save({ autopilot: v === 'auto' })}
            options={[
              { v: 'auto' as const, label: t('ap.auto'), testId: 'mode-auto' },
              { v: 'ask' as const, label: t('ap.ask'), testId: 'mode-ask' },
            ]}
            testId="settings-autopilot"
          />
        </Row>
        <Row label={t('s2.platformsNew')}>
          <span className="s2-val">{fmtList(pfNames)}</span>
          <button className="s2-link" onClick={() => setSheet('platforms')} data-testid="change-platforms">
            {t('s2.change')}
          </button>
        </Row>
        <Row label={t('s2.watch')} hint={t('s2.watchHint')}>
          <span className="s2-val" title={watch.join('\n')}>
            {watch.length ? fmtList(watch.map(folderName)) : t('s2.watchNone')}
          </span>
          <button className="s2-link" onClick={() => setSheet('watch')} data-testid="change-watch">
            {t('s2.change')}
          </button>
        </Row>
        <Row label={t('s2.tidy')} hint={t('s2.tidyHint')}>
          {tidyValue === 'custom' && (
            <input
              className="input s2-num"
              type="number"
              min={1}
              max={365}
              defaultValue={days || 14}
              placeholder={t('s2.tidy.customPh')}
              aria-label={t('s2.tidy.customPh')}
              onBlur={(e) => {
                const n = Math.max(0, Math.min(365, Math.round(Number(e.target.value) || 0)));
                if (n !== days) void save({ cleanupDays: n });
              }}
              data-testid="tidy-days"
            />
          )}
          <select
            className="s2-select"
            value={tidyValue}
            onChange={(e) => {
              if (e.target.value === 'custom') return setCustom(true);
              setCustom(false);
              void save({ cleanupDays: Number(e.target.value) });
            }}
            aria-label={t('s2.tidy')}
            data-testid="tidy"
          >
            {TIDY.map((n) => (
              <option key={n} value={String(n)}>
                {n ? t('s2.tidy.days', { n }) : t('s2.tidy.never')}
              </option>
            ))}
            <option value="custom">{t('s2.tidy.custom')}</option>
          </select>
        </Row>
        <Row
          label={t('s2.agency')}
          hint={
            <>
              {t('s2.agencyHint')}
              {s.agencyMode && (
                <span className="s2-sublinks">
                  <a href={href({ name: 'clients' })} data-testid="open-clients">
                    {t('s2.clients')}
                  </a>
                  <a href={href({ name: 'metrics' })}>{t('s2.numbers')}</a>
                </span>
              )}
            </>
          }
        >
          <Toggle checked={!!s.agencyMode} onChange={(v) => void save({ agencyMode: v })} label={t('s2.agency')} testId="agency-toggle" />
        </Row>
        <Row label={t('fs.set.askAi')} hint={t('fs.set.askAiHint')}>
          <Toggle checked={!!s.askAiEdits} onChange={(v) => void save({ askAiEdits: v })} label={t('fs.set.askAi')} testId="ask-ai-edits-toggle" />
        </Row>
      </Group>
      <div className="s2-group s2-labs">
        <CreateSettingsCard onChange={onChange} />
      </div>
      <UsageSettingsGroup settings={s} save={save} />
      <p className="s2-foot" data-testid="settings-privacy">
        <Lock className="ico" />
        {t('s2.privacyLine')}
        <button className="s2-link" onClick={() => setSheet('privacy')}>
          {t('s2.privacyMore')}
        </button>
      </p>
      {sheet === 'platforms' && (
        <Sheet title={t('s2.platformsNew')} onClose={() => setSheet(null)} footer={<button className="btn primary" onClick={() => setSheet(null)}>{t('s2.done')}</button>}>
          <PlatformPicker value={s.defaultPlatforms ?? []} onChange={(v) => v.length && void save({ defaultPlatforms: v })} />
        </Sheet>
      )}
      {sheet === 'watch' && (
        <Sheet title={t('s2.watch')} onClose={() => setSheet(null)}>
          <p className="s2-rhint">{t('s2.watchHint')}</p>
          {IS_LITE && <p className="s2-rhint">{t('lite.watchHint')}</p>}
          <WatchFoldersField />
        </Sheet>
      )}
      {sheet === 'privacy' && (
        <Sheet title={t('settings.privacy')} onClose={() => setSheet(null)}>
          <p className="s2-prose">{t('settings.privacyBody')}</p>
        </Sheet>
      )}
    </Page>
  );
}
