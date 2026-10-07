// Settings › Video generation › Plugins: every importer, shot provider and agent runner Reelfold found (built in,
// a plugins folder, or a Python package), on / off, version, what it may do (permissions) and what it costs. Agent
// runners also get their parallel lanes, and "Any command" its command line. Third-party plugins start off.
import { useState } from 'react';
import type { Lang3, PluginRow } from '../../../../shared/create';
import { t } from '../../i18n';
import { useAction, useCreate, useCreateLoad } from '../api';
import { uiLang3 } from '../bits';

const KINDS: PluginRow['kind'][] = ['importer', 'shot-provider', 'agent-runner'];

function text(v: string | Partial<Record<Lang3, string>> | undefined, lang: Lang3): string {
  if (!v) return '';
  if (typeof v === 'string') return v;
  return v[lang] ?? v.en ?? '';
}

/** "a b 'c d'" -> ['a', 'b', 'c d'] (quotes group words; no shell). */
export function splitCommand(line: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) out.push(m[1] ?? m[2] ?? m[3] ?? '');
  return out.filter(Boolean);
}

function permText(p: string): string {
  if (p.startsWith('exec:')) return t('create.plugins.perm.exec', { cmd: p.slice(5) });
  const k = `create.plugins.perm.${p}`;
  return ['read-files', 'write-job', 'network', 'spend'].includes(p) ? t(k as 'create.plugins.perm.network') : p;
}

export function PluginsCard() {
  const c = useCreate();
  const lang = uiLang3();
  const list = useCreateLoad((x) => x.plugins(lang), [lang]);
  const act = useAction();
  const [cmd, setCmd] = useState<string | null>(null);
  const rows = list.data?.plugins ?? [];
  const set = (key: string, body: { enabled?: boolean; settings?: Record<string, unknown> }) =>
    act.run(async () => {
      if (!c) return;
      await c.setPlugin(key, body);
      list.reload();
    });
  return (
    <>
      <div className="lbl">
        <span>{t('create.plugins.title')}</span>
      </div>
      <div className="card" data-testid="create-plugins">
        <div className="muted" style={{ marginBottom: 12 }}>
          {t('create.plugins.sub')}
        </div>
        {KINDS.map((k) => {
          const of = rows.filter((r) => r.kind === k);
          if (!of.length) return null;
          return (
            <div key={k} style={{ marginBottom: 14 }}>
              <div className="t1" style={{ fontWeight: 600, margin: '6px 0' }}>
                {t(`create.plugins.kind.${k}`)}
              </div>
              <div className="cr-plugins">
                {of.map((p) => (
                  <div key={`${p.key}-${p.where}`} className={`cr-plugin ${p.error ? 'bad' : ''}`} data-testid="create-plugin" data-key={p.key} data-enabled={p.enabled ? '1' : '0'}>
                    <div style={{ minWidth: 0 }}>
                      <div className="nm">
                        {p.label} <span className="meta">{t('create.plugins.version', { v: p.version })}</span>
                      </div>
                      <div className="meta">{text(p.description, lang)}</div>
                      <div className="meta">
                        {p.origin === 'builtin' ? t('create.plugins.builtin') : t('create.plugins.external', { where: p.where })}
                        {' · '}
                        {t(`create.plugins.cost.${p.cost.kind}`)}
                        {p.cost.notes && text(p.cost.notes, lang) ? ` (${text(p.cost.notes, lang)})` : ''}
                      </div>
                      {p.permissions.length > 0 && (
                        <div className="meta">
                          {t('create.plugins.perms')}:{' '}
                          {p.permissions.map((x) => (
                            <span key={x} className="perm">
                              {permText(x)}
                            </span>
                          ))}
                        </div>
                      )}
                      {p.error && <div className="cr-err meta">{t('create.plugins.broken', { error: p.error })}</div>}
                      {!p.error && p.enabled && p.status && !p.status.ready && (
                        <div className="meta" data-testid="create-plugin-not-ready">
                          {t('create.plugins.notReady', { detail: String(p.status.params?.detail ?? p.status.code) })}
                        </div>
                      )}
                      {p.kind === 'agent-runner' && p.enabled && (
                        <div className="row" style={{ gap: 8, marginTop: 6, alignItems: 'center' }}>
                          <label className="meta">
                            {t('create.make.lanes')}{' '}
                            <select value={p.lanes} onChange={(e) => void set(p.key, { settings: { lanes: Number(e.target.value) } })} data-testid="create-plugin-lanes">
                              {[...new Set([1, 2, 3, 4, 6, 8, p.lanes])].sort((a, b) => a - b).map((n) => (
                                <option key={n} value={n}>
                                  {n}
                                </option>
                              ))}
                            </select>
                          </label>
                          {p.id === 'shell' && (
                            <>
                              <input
                                className="input"
                                style={{ flex: 1, minWidth: 200 }}
                                placeholder={t('create.plugins.commandPlaceholder', { job_dir: '{job_dir}', outputs: '{outputs}' })}
                                value={cmd ?? ''}
                                onChange={(e) => setCmd(e.target.value)}
                                data-testid="create-plugin-command"
                              />
                              <button className="btn sm" disabled={!cmd?.trim()} onClick={() => void set(p.key, { settings: { command: splitCommand(cmd ?? '') } })}>
                                {t('c.save')}
                              </button>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                    <label className="row" style={{ gap: 6, alignItems: 'center' }}>
                      <input type="checkbox" checked={p.enabled} disabled={!!p.error || act.busy} onChange={(e) => void set(p.key, { enabled: e.target.checked })} data-testid="create-plugin-toggle" />
                      {p.enabled ? t('create.plugins.on') : t('create.plugins.off')}
                    </label>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {list.data && <div className="meta muted" style={{ fontSize: 13 }}>{t('create.plugins.addHint', { dir: list.data.dirs[0] ?? '' })}</div>}
        {(act.error || list.error) && <div className="cr-err">{act.error ?? list.error}</div>}
      </div>
    </>
  );
}
