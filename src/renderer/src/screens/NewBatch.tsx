// New batch: from a raw recording (AI segment planning -> segment review, NewFromRecording) or the classic
// wizard: material + recipe + platforms + budget -> plan -> estimate (budget gate) -> pilot.
import { useEffect, useState, type ReactNode } from 'react';
import type { Estimate } from '../../../shared/types';
import { ErrorBox, Field } from '../components/ui';
import { t } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { bytes, hms, usd } from '../lib/format';
import { go } from '../lib/router';
import { NewFromRecording } from './NewFromRecording';

export const PLATFORM_CHOICES = [
  { id: 'xiaohongshu:full', label: 'platform.xiaohongshu-full' },
  { id: 'xiaohongshu:vertical', label: 'platform.xiaohongshu-vertical' },
  { id: 'douyin', label: 'platform.douyin' },
  { id: 'tiktok', label: 'platform.tiktok' },
  { id: 'youtube-shorts', label: 'platform.youtube-shorts' },
  { id: 'youtube', label: 'platform.youtube' },
  { id: 'bilibili', label: 'platform.bilibili' },
];

type Step = 'source' | 'estimate' | 'pilot';

export function EstimateView({ est }: { est: Estimate }) {
  return (
    <div className="col">
      <div className="row" style={{ gap: 24, flexWrap: 'wrap' }}>
        <Stat label={t('est.jobs')} value={String(est.jobs)} />
        <Stat label={t('est.machine')} value={hms(est.machine_s)} />
        <Stat label={t('est.wall')} value={`~${hms(est.wall_s)}`} />
        <Stat label={t('est.storage')} value={`+${bytes(est.storage_bytes)}`} sub={est.free_bytes != null ? t('est.free', { v: bytes(est.free_bytes) }) : undefined} />
        <Stat label={t('est.api')} value={usd(est.api_usd)} sub={t('est.spent', { v: usd(est.spent_usd) })} />
      </div>
      {est.budget.ok ? (
        <div className="notice accent">{t('est.budgetOk')}</div>
      ) : (
        <div className="notice" style={{ borderColor: 'var(--danger)' }}>
          <b>{t('est.budgetOver')}</b>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {est.budget.over.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </div>
      )}
      <table className="t">
        <thead>
          <tr>
            <th>{t('est.stage')}</th>
            <th>{t('est.resource')}</th>
            <th>{t('est.machine')}</th>
            <th>{t('est.storage')}</th>
            <th>{t('est.bench')}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(est.stages).map(([k, s]) => (
            <tr key={k}>
              <td>{k}</td>
              <td className="mono">{s.resource}</td>
              <td>{hms(s.seconds)}</td>
              <td>{bytes(s.bytes)}</td>
              <td className="muted">{s.measured ? t('est.measured') : t('est.guess')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="muted small">{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600 }}>{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}

/** Client preselected from a client page ("+ new batch") or the last choice. */
export function initialClient(): string {
  return sessionStorage.getItem('newClient') ?? '';
}

export function ClientSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const clients = useLoad((c) => c.clients(), []);
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={t('new.client')} data-testid="client-select">
      <option value="">{t('new.noClient')}</option>
      {(clients.data ?? []).map((c) => (
        <option key={c.slug} value={c.slug}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

export function NewBatch() {
  const [mode, setMode] = useState<'raw' | 'classic'>('raw');
  const tabs = (
    <div className="tabs" role="tablist">
      {(['raw', 'classic'] as const).map((m) => (
        <button key={m} role="tab" aria-selected={mode === m} className={`tab ${mode === m ? 'on' : ''}`} onClick={() => setMode(m)} data-testid={`mode-${m}`}>
          {t(`new.mode.${m}`)}
        </button>
      ))}
    </div>
  );
  return mode === 'raw' ? <NewFromRecording tabs={tabs} /> : <ClassicNewBatch tabs={tabs} />;
}

function ClassicNewBatch({ tabs }: { tabs: ReactNode }) {
  const { client } = useEngine();
  const recipes = useLoad((c) => c.recipes(), []);
  const [step, setStep] = useState<Step>('source');
  const [recipe, setRecipe] = useState('longform-slices');
  const [source, setSource] = useState('');
  const [folder, setFolder] = useState('');
  const [segments, setSegments] = useState('');
  const [name, setName] = useState('');
  const [platforms, setPlatforms] = useState<string[]>(['xiaohongshu:full']);
  const [maxUsd, setMaxUsd] = useState('5');
  const [maxHours, setMaxHours] = useState('8');
  const [maxGb, setMaxGb] = useState('');
  const [outDir, setOutDir] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [est, setEst] = useState<Estimate | null>(null);
  const [pilot, setPilot] = useState(3);
  const [clientSlug, setClientSlug] = useState(initialClient);
  useEffect(() => {
    void window.desk.getSettings().then((st) => st.defaultPlatforms?.length && setPlatforms(st.defaultPlatforms));
  }, []);

  const longform = recipe.startsWith('longform'); // one long recording (slices: + a segments job list)
  const needSegments = recipe === 'longform-slices';
  const valid = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(name) && platforms.length > 0 && (longform ? source && (!needSegments || segments) : folder);

  async function pick(kind: 'video' | 'segments' | 'folder' | 'out') {
    const p = kind === 'folder' || kind === 'out' ? await window.desk.openFolder() : await window.desk.openFile(kind);
    if (!p) return;
    if (kind === 'video') {
      setSource(p);
      if (!name) setName(defaultName(p));
    } else if (kind === 'segments') setSegments(p);
    else if (kind === 'folder') {
      setFolder(p);
      if (!name) setName(defaultName(p));
    } else setOutDir(p);
  }

  async function plan() {
    if (!client) return;
    setBusy(true);
    setError(null);
    try {
      const num = (v: string) => (v.trim() === '' ? undefined : Number(v));
      const r = await client.createBatch({
        name,
        recipe,
        source: longform ? source : undefined,
        folder: longform ? undefined : folder,
        segments: segments || undefined,
        platforms,
        budget: { max_usd: num(maxUsd), max_hours: num(maxHours), max_storage_gb: num(maxGb) },
        out_dir: outDir || undefined,
        client: clientSlug || undefined,
      });
      setBatchId(r.id);
      setEst(await client.estimate(r.id));
      setStep('estimate');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function startPilot() {
    if (!client || !batchId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await client.run(batchId, { pilot });
      if (!r.started && r.status === 'over-budget') throw new Error(t('est.budgetOver'));
      go({ name: 'board', batch: batchId });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="topbar">
        <h1>{t('new.title')}</h1>
        {tabs}
        <div className="sp" />
      </div>
      <div className="page" style={{ maxWidth: 860 }}>
        <div className="steps">
          {(['source', 'estimate', 'pilot'] as Step[]).map((s, i) => (
            <span key={s} className={step === s ? 'on' : ''}>
              {i + 1}. {t(`new.step.${s}`)}
            </span>
          ))}
        </div>
        <ErrorBox error={error ?? recipes.error} />
        {step === 'source' && (
          <div className="col" style={{ gap: 14 }}>
            <Field label={t('new.recipe')}>
              <select className="input" value={recipe} onChange={(e) => setRecipe(e.target.value)}>
                {(recipes.data ?? []).map((r) => (
                  <option key={r.name} value={r.name}>
                    {t(`recipe.${r.name}`) !== `recipe.${r.name}` ? t(`recipe.${r.name}`) : r.name}
                  </option>
                ))}
              </select>
            </Field>
            <div className="muted small">{recipes.data?.find((r) => r.name === recipe)?.description}</div>
            {longform ? (
              <>
                <Field label={t('new.source')}>
                  <div className="row">
                    <input className="input" style={{ flex: 1 }} value={source} readOnly placeholder={t('new.pickFile')} />
                    <button className="btn" onClick={() => pick('video')}>
                      {t('common.choose')}
                    </button>
                  </div>
                </Field>
                <Field label={needSegments ? t('new.segments') : t('new.segmentsOptional')} hint={t('new.segmentsHint')}>
                  <div className="row">
                    <input className="input" style={{ flex: 1 }} value={segments} readOnly placeholder="segments.yaml" />
                    <button className="btn" onClick={() => pick('segments')}>
                      {t('common.choose')}
                    </button>
                  </div>
                </Field>
              </>
            ) : (
              <>
                <Field label={t('new.folder')}>
                  <div className="row">
                    <input className="input" style={{ flex: 1 }} value={folder} readOnly placeholder={t('new.pickFolder')} />
                    <button className="btn" onClick={() => pick('folder')}>
                      {t('common.choose')}
                    </button>
                  </div>
                </Field>
                <Field label={t('new.segmentsOptional')}>
                  <div className="row">
                    <input className="input" style={{ flex: 1 }} value={segments} readOnly placeholder="clips.csv" />
                    <button className="btn" onClick={() => pick('segments')}>
                      {t('common.choose')}
                    </button>
                  </div>
                </Field>
              </>
            )}
            <Field label={t('new.client')}>
              <ClientSelect value={clientSlug} onChange={setClientSlug} />
            </Field>
            <Field label={t('new.name')} hint={t('new.nameHint')}>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} />
            </Field>
            <Field label={t('new.platforms')}>
              <div className="tabs">
                {PLATFORM_CHOICES.map((p) => (
                  <button
                    key={p.id}
                    className={`tab ${platforms.includes(p.id) ? 'on' : ''}`}
                    onClick={() => setPlatforms((x) => (x.includes(p.id) ? x.filter((y) => y !== p.id) : [...x, p.id]))}
                  >
                    {t(p.label)}
                  </button>
                ))}
              </div>
            </Field>
            <div className="row" style={{ gap: 12 }}>
              <Field label={t('new.maxUsd')}>
                <input className="input" value={maxUsd} onChange={(e) => setMaxUsd(e.target.value)} inputMode="decimal" />
              </Field>
              <Field label={t('new.maxHours')}>
                <input className="input" value={maxHours} onChange={(e) => setMaxHours(e.target.value)} inputMode="decimal" />
              </Field>
              <Field label={t('new.maxGb')}>
                <input className="input" value={maxGb} onChange={(e) => setMaxGb(e.target.value)} inputMode="decimal" />
              </Field>
            </div>
            <Field label={t('new.outDir')} hint={t('new.outDirHint')}>
              <div className="row">
                <input className="input" style={{ flex: 1 }} value={outDir} readOnly placeholder={t('new.outDirDefault')} />
                <button className="btn" onClick={() => pick('out')}>
                  {t('common.choose')}
                </button>
              </div>
            </Field>
            <div className="row">
              <button className="btn primary" disabled={!valid || busy} onClick={plan}>
                {busy ? t('common.working') : t('new.plan')}
              </button>
            </div>
          </div>
        )}
        {step === 'estimate' && est && (
          <div className="col" style={{ gap: 14 }}>
            <EstimateView est={est} />
            <div className="row">
              <button className="btn" onClick={() => setStep('source')}>
                {t('common.back')}
              </button>
              <button className="btn primary" disabled={!est.budget.ok} onClick={() => setStep('pilot')}>
                {t('new.toPilot')}
              </button>
            </div>
          </div>
        )}
        {step === 'pilot' && (
          <div className="col" style={{ gap: 14 }}>
            <div className="notice accent">{t('new.pilotWhy')}</div>
            <Field label={t('new.pilotCount')}>
              <input className="input" type="number" min={1} max={50} value={pilot} onChange={(e) => setPilot(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} style={{ width: 100 }} />
            </Field>
            <div className="row">
              <button className="btn" onClick={() => setStep('estimate')}>
                {t('common.back')}
              </button>
              <button className="btn primary" disabled={busy} onClick={startPilot}>
                {t('new.startPilot', { n: pilot })}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export function defaultName(p: string): string {
  const base = p.split(/[\\/]/).filter(Boolean).pop() ?? 'batch';
  return (base.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'batch').slice(0, 40);
}
