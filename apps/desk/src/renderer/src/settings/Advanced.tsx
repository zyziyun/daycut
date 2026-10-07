// Settings › Advanced (ux/settings-redesign A5/A6), collapsed by default: Engine (in words, never a raw path —
// the full path is in the tooltip and the diagnostic report), Downloads (one Download / Cancel per row), Style
// defaults (persona), first-run setup, Help and diagnostics. Only engine path / Python ask for "Restart now".
import { useState } from 'react';
import { AlertTriangle, Cpu, Download, LifeBuoy, Paintbrush, Wand2 } from 'lucide-react';
import { providerName } from '../../../shared/aiRoutes';
import { useAssets } from '../components/assets';
import { t, tk } from '../i18n';
import { useAi } from '../lib/ai';
import { useEngine } from '../lib/engine';
import { useChannels } from '../v4/Channels';
import { useUi } from '../v4/ui';
import { Disclosure, Dot, Page, RestartBar, Sheet } from './kit';
import { markRestart, useRestart } from './restart';
import type { SettingsCtx } from './registry';
import { engineWords, pythonWords } from './words';

const mb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n <= 0 ? '0 MB' : `${Math.max(1, Math.round(n / 1e6))} MB`);
const base = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p;
const groupName = (id: string) => tk(`assets.group.${id.replace(/-(darwin|win32).*$/, '')}`);
const OPEN = 'set.advOpen';

function loadOpen(): string[] {
  try {
    const v = JSON.parse(sessionStorage.getItem(OPEN) || '[]');
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function AdvancedSection({ settings: s, save, onChange }: SettingsCtx) {
  const ui = useUi();
  const { info, error } = useEngine();
  const assets = useAssets();
  const restart = useRestart();
  const ai = useAi();
  const { channels } = useChannels();
  const [open, setOpenS] = useState<string[]>(loadOpen);
  const [licences, setLicences] = useState(false);
  const toggle = (k: string) => {
    const n = open.includes(k) ? open.filter((x) => x !== k) : [...open, k];
    setOpenS(n);
    try {
      sessionStorage.setItem(OPEN, JSON.stringify(n));
    } catch {
      /* private mode */
    }
  };
  const demo = info?.mode === 'mock';
  const changePath = async (kind: 'engine' | 'python') => {
    const p = kind === 'engine' ? await window.desk.openFolder() : await window.desk.openFile('python');
    if (!p) return;
    const r = await save(kind === 'engine' ? { enginePath: p } : { python: p });
    if (r) markRestart(kind);
  };
  const groups = assets?.groups ?? [];
  const missing = groups.filter((g) => !g.installed);
  const report = () => {
    const lines = [
      `Reelfold ${__APP_VERSION__} · ${s.platform ?? navigator.platform}${s.packaged ? ' · packaged' : ' · dev'}`,
      `UI language: ${s.lang} · theme: ${s.theme}`,
      `Engine: ${info?.mode ?? '-'}${error ? ` · error: ${error.split('\n')[0].slice(0, 200)}` : ''}${info?.note ? ` · ${info.note}` : ''}`,
      `Engine path: ${s.resolved?.enginePath ?? '-'}`,
      `Python: ${s.resolved?.python ?? '-'} · runtime: ${s.resolved?.runtime ?? '-'}`,
      `Data: ${s.resolved?.dataDir ?? '-'}`,
      `AI default: ${ai.routes ? providerName(ai.routes.routes.default.provider) : '-'} · fallback: ${(ai.routes?.routes.default.fallback ?? []).join(', ') || '-'}`,
      `AI status: ${(ai.status?.providers ?? []).map((r) => `${r.provider}=${r.state}`).join(', ') || '-'}`,
      `Downloads: ${groups.map((g) => `${g.id}=${g.installed ? 'installed' : g.progress ? 'downloading' : g.queued ? 'queued' : g.error ? 'error' : 'missing'}`).join(', ') || '-'}`,
      `Publishing accounts: ${channels.map((c) => `${c.adapterId}/${c.account}=${c.login.state}`).join(', ') || '-'}`,
      `Agency mode: ${s.agencyMode ? 'on' : 'off'} · default platforms: ${(s.defaultPlatforms ?? []).join(', ')} · tidy after: ${s.cleanupDays ?? 0} days`,
    ];
    void window.desk.copyText(lines.join('\n')).then(() => ui.toast(t('s2.diag.copied')));
  };
  return (
    <Page title={t('s2.nav.advanced')} lead={t('s2.adv.lead')} testId="settings-advanced">
      {restart.what === 'engine' || restart.what === 'python' ? (
        <RestartBar text={t('s2.restart.bar', { what: t(restart.what === 'engine' ? 's2.restart.engine' : 's2.restart.python') })} onRestart={() => window.desk.restartEngine().then(() => markRestart(null))} />
      ) : null}
      <div className="s2-card">
        <Disclosure icon={<Cpu className="ico" />} label={t('s2.engine')} hint={t('s2.engineHint')} value={demo || error ? <Dot tone={error ? 'error' : 'warn'} /> : undefined} open={open.includes('engine')} onToggle={() => toggle('engine')} testId="adv-engine">
          <div data-testid="settings-engine">
            {demo && (
              <div className="s2-note warn" data-testid="demo-warning">
                <AlertTriangle className="ico" />
                <span>
                  {t('s2.st.demoBody')}
                  {info?.note ? ` ${info.note}` : ''}
                </span>
              </div>
            )}
            {error && (
              <div className="s2-note error" data-testid="engine-error" title={error}>
                <AlertTriangle className="ico" />
                <span>{t('s2.st.engineDown')}</span>
              </div>
            )}
            <div className="s2-sub">
              <span className="s2-rlabel">{t('s2.engine.folder')}</span>
              <span className="s2-val" title={s.resolved?.enginePath ?? ''} data-testid="engine-words">
                {engineWords(s.resolved?.enginePath, s.packaged)}
              </span>
              {!s.packaged && (
                <button className="s2-link" onClick={() => void changePath('engine')} data-testid="change-engine">
                  {t('s2.change')}
                </button>
              )}
            </div>
            <div className="s2-sub">
              <span className="s2-rlabel">{t('s2.engine.python')}</span>
              <span className="s2-val" title={s.resolved?.python ?? ''} data-testid="runtime-info">
                {pythonWords(s)}
              </span>
              {!s.packaged && (
                <button className="s2-link" onClick={() => void changePath('python')} data-testid="change-python">
                  {t('s2.change')}
                </button>
              )}
            </div>
            <div className="s2-sub">
              <span className="s2-rlabel">{t('s2.engine.data')}</span>
              <span className="s2-val" />
              {s.resolved?.dataDir && (
                <button className="s2-link" onClick={() => void window.desk.showItem(s.resolved!.dataDir)} title={s.resolved.dataDir}>
                  {t('s2.engine.showInFinder')}
                </button>
              )}
            </div>
            <div className="s2-sub">
              <span className="s2-rlabel">{t('s2.engine.mode')}</span>
              <span className="s2-val">{info?.mode === 'real' ? t('s2.engine.modeReal') : info?.mode === 'mock' ? t('s2.engine.modeDemo') : '–'}</span>
              {!restart.what && (
                <button className="s2-link" onClick={() => void window.desk.restartEngine().catch((e: Error) => ui.toast(e.message, { error: true }))} data-testid="engine-restart">
                  {t('s2.engine.restart')}
                </button>
              )}
            </div>
          </div>
        </Disclosure>
        <Disclosure
          icon={<Download className="ico" />}
          label={t('s2.dl')}
          hint={t('s2.dlHint')}
          value={assets?.bundled && missing.some((g) => g.required) ? <Dot tone="warn" /> : undefined}
          open={open.includes('downloads')}
          onToggle={() => toggle('downloads')}
          testId="adv-downloads"
        >
          <div data-testid="assets-card">
            {groups.map((g) => (
              <div key={g.id} className="s2-sub" data-testid={`asset-${g.id}`}>
                <span className="s2-rlabel">{groupName(g.id)}</span>
                <span className="s2-val num">
                  {mb(g.bytes)}
                  {!g.installed && ` · ${g.required ? t('s2.dl.required') : t('s2.dl.optional')}`}
                </span>
                {g.installed ? (
                  <span className="s2-pill ok" data-testid={`asset-state-${g.id}`}>
                    <Dot tone="ok" />
                    {t('s2.dl.installed')}
                  </span>
                ) : g.progress ? (
                  <>
                    <span className="s2-prog" data-testid={`asset-state-${g.id}`} title={`${mb(g.progress.received)} / ${mb(g.progress.total)}`}>
                      <i style={{ width: `${g.progress.total ? Math.min(100, (g.progress.received / g.progress.total) * 100) : 0}%` }} />
                    </span>
                    <button className="btn" onClick={() => void window.desk.assets.cancel(g.id)} data-testid={`asset-cancel-${g.id}`}>
                      {t('s2.dl.cancel')}
                    </button>
                  </>
                ) : g.queued ? (
                  <>
                    <span className="s2-val" data-testid={`asset-state-${g.id}`}>
                      {t('s2.dl.queued')}
                    </span>
                    <button className="btn" onClick={() => void window.desk.assets.cancel(g.id)}>
                      {t('s2.dl.cancel')}
                    </button>
                  </>
                ) : (
                  <button className="btn" onClick={() => void window.desk.assets.install([g.id])} data-testid={`asset-download-${g.id}`} title={g.error ?? undefined}>
                    {g.error ? t('s2.dl.retry') : t('s2.dl.download')}
                  </button>
                )}
              </div>
            ))}
            <div className="s2-sub end">
              <button className="s2-link muted" onClick={() => setLicences(true)}>
                {t('s2.dl.licences')}
              </button>
              {assets?.busy && (
                <button className="s2-link" onClick={() => void window.desk.assets.cancel()}>
                  {t('s2.dl.cancelAll')}
                </button>
              )}
            </div>
          </div>
        </Disclosure>
        <Disclosure icon={<Paintbrush className="ico" />} label={t('s2.style')} hint={t('s2.styleHint')} value={s.personaPath ? base(s.personaPath) : t('s2.style.default')} open={open.includes('style')} onToggle={() => toggle('style')} testId="adv-style">
          <div className="s2-sub" title={s.personaPath ?? ''}>
            <span className="s2-rlabel">{s.personaPath ? base(s.personaPath) : t('s2.style.default')}</span>
            <span className="s2-val" />
            <button
              className="s2-link"
              onClick={async () => {
                const p = await window.desk.openFile('persona');
                if (!p) return;
                try {
                  onChange(await window.desk.persona.import(p));
                  ui.toast(t('settings.personaImported'));
                } catch (e) {
                  ui.toast((e as Error).message, { error: true });
                }
              }}
            >
              {t('s2.style.import')}
            </button>
            {s.personaPath && (
              <button className="s2-link muted" onClick={async () => onChange(await window.desk.persona.clear())}>
                {t('s2.style.remove')}
              </button>
            )}
          </div>
        </Disclosure>
        <Disclosure icon={<Wand2 className="ico" />} label={t('s2.wizard')} hint={t('s2.wizardHint')} open={false} onToggle={() => (location.hash = '#/welcome')} testId="adv-wizard" value={t('s2.wizard.open')} />
        <Disclosure icon={<LifeBuoy className="ico" />} label={t('s2.diag')} hint={t('s2.diagHint')} open={open.includes('diag')} onToggle={() => toggle('diag')} testId="adv-diag">
          <div className="s2-sub">
            <span className="s2-rtext">
              <span className="s2-rlabel">{t('s2.diag.copy')}</span>
              <span className="s2-rhint">{t('s2.diag.copyHint')}</span>
            </span>
            <button className="btn" onClick={report} data-testid="diag-copy">
              {t('s2.diag.copy')}
            </button>
          </div>
          <div className="s2-sub">
            <span className="s2-rtext">
              <span className="s2-rlabel">{t('s2.diag.logs')}</span>
              <span className="s2-rhint">{t('s2.diag.logsHint')}</span>
            </span>
            <button className="btn" onClick={() => void window.desk.openLogs()} data-testid="diag-logs">
              {t('s2.diag.logs')}
            </button>
          </div>
          <p className="s2-rhint" data-testid="settings-platforms" style={{ padding: '4px 0 8px' }}>
            {t('about.platforms')}
          </p>
        </Disclosure>
      </div>
      {licences && (
        <Sheet title={t('s2.dl.licencesTitle')} onClose={() => setLicences(false)} wide>
          {groups.map((g) => (
            <p key={g.id} className="s2-prose">
              <b>{groupName(g.id)}</b> — {g.licence}
            </p>
          ))}
          {assets?.dir && <p className="s2-rhint" title={assets.dir}>{base(assets.dir)}</p>}
        </Sheet>
      )}
    </Page>
  );
}
