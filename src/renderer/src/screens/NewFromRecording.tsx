// New batch from a raw recording (P0-1): pick file(s) -> AI segment planning (count / length / platforms /
// provider) -> segment review -> estimate -> pilot. The full run is confirmed on the board after the pilot.
import { useEffect, useState, type ReactNode } from 'react';
import type { SecretsStatusMsg } from '../../../shared/deskApi';
import type { Estimate } from '../../../shared/types';
import { acceptedSegments, PROVIDERS, type PlanState, type Provider, type ReviewedSegment } from '../../../shared/v02';
import { SegmentReview } from '../components/SegmentReview';
import { ErrorBox, Field } from '../components/ui';
import { t, tk } from '../i18n';
import { useEngine } from '../lib/engine';
import { go } from '../lib/router';
import { PlatformPicker } from './Clients';
import { ClientSelect, defaultName, EstimateView, initialClient } from './NewBatch';

type Step = 'source' | 'plan' | 'segments' | 'estimate' | 'pilot';
const STEPS: Step[] = ['source', 'plan', 'segments', 'estimate', 'pilot'];
const NAME_RE = /^[\p{L}\p{N}][\p{L}\p{N} .()（）·_-]{0,63}$/u;

interface PlanRow {
  file: string;
  id: string | null;
  state: PlanState | null;
  error: string | null;
}

export function NewFromRecording({ tabs }: { tabs: ReactNode }) {
  const { client, subscribe } = useEngine();
  const [step, setStep] = useState<Step>('source');
  const [files, setFiles] = useState<string[]>([]);
  const [clientSlug, setClientSlug] = useState(initialClient);
  const [name, setName] = useState('');
  const [platforms, setPlatforms] = useState<string[]>(['xiaohongshu:full']);
  const [count, setCount] = useState(6);
  const [minS, setMinS] = useState(30);
  const [maxS, setMaxS] = useState(90);
  const [provider, setProvider] = useState<Provider>('none');
  const [maxUsd, setMaxUsd] = useState('5');
  const [maxHours, setMaxHours] = useState('8');
  const [keys, setKeys] = useState<SecretsStatusMsg | null>(null);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [segs, setSegs] = useState<Record<string, ReviewedSegment[]>>({});
  const [curPlan, setCurPlan] = useState(0);
  const [created, setCreated] = useState<{ id: string; name: string }[]>([]);
  const [ests, setEsts] = useState<Record<string, Estimate>>({});
  const [pilot, setPilot] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void window.desk.getSettings().then((s) => s.defaultPlatforms?.length && setPlatforms(s.defaultPlatforms));
    void window.desk.secrets
      .status()
      .then((k) => {
        setKeys(k);
        if (k.keys.anthropic) setProvider('claude');
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!client || !clientSlug) return;
    sessionStorage.setItem('newClient', clientSlug);
    client
      .client(clientSlug)
      .then((c) => c.effective.platforms?.length && setPlatforms(c.effective.platforms))
      .catch(() => undefined);
  }, [client, clientSlug]);

  // plan progress: SSE `plan` events + a slow poll as a fallback
  useEffect(() => {
    if (step !== 'plan' || !client) return;
    let alive = true;
    const refresh = async () => {
      const next = await Promise.all(
        plans.map(async (p) => (p.id && (!p.state || p.state.state === 'running') ? { ...p, state: await client.plan(p.id).catch(() => p.state) } : p)),
      );
      if (!alive) return;
      setPlans(next);
      if (next.every((p) => p.state && p.state.state !== 'running') && next.some((p) => p.state?.state === 'done')) {
        const s: Record<string, ReviewedSegment[]> = {};
        for (const p of next) if (p.state?.state === 'done' && p.id) s[p.id] = (p.state.result?.segments ?? []).map((x) => ({ ...x, accepted: true }));
        setSegs(s);
        setCurPlan(Math.max(0, next.findIndex((p) => p.state?.state === 'done')));
        setStep('segments');
      }
    };
    const off = subscribe((e) => {
      if (e.type === 'plan') void refresh();
    });
    const timer = setInterval(refresh, 1500);
    void refresh();
    return () => {
      alive = false;
      off();
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, client]);

  async function pickFiles() {
    const f = await window.desk.openFiles('video');
    if (!f.length) return;
    setFiles(f);
    if (!name) setName(defaultName(f[0]));
  }

  async function startPlanning() {
    if (!client) return;
    setBusy(true);
    setError(null);
    try {
      const rows: PlanRow[] = [];
      for (const file of files) {
        try {
          const r = await client.startPlan({ source: file, count, min: minS, max: maxS, provider, platforms, client: clientSlug || undefined });
          rows.push({ file, id: r.id, state: null, error: null });
        } catch (e) {
          rows.push({ file, id: null, state: null, error: (e as Error).message });
        }
      }
      if (rows.every((r) => r.error)) throw new Error(rows.map((r) => r.error).join('\n'));
      setPlans(rows);
      setStep('plan');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const done = plans.filter((p) => p.id && p.state?.state === 'done');
  const totalAccepted = done.reduce((a, p) => a + (segs[p.id!] ?? []).filter((s) => s.accepted).length, 0);

  async function createBatches() {
    if (!client) return;
    setBusy(true);
    setError(null);
    try {
      const num = (v: string) => (v.trim() === '' ? undefined : Number(v));
      const out: { id: string; name: string }[] = [];
      const withSegs = done.filter((p) => acceptedSegments(segs[p.id!] ?? []).length);
      for (const [i, p] of withSegs.entries()) {
        const n = withSegs.length > 1 ? `${name}-${i + 1}`.slice(0, 64) : name;
        const r = await client.planToBatch(p.id!, {
          name: n,
          segments: acceptedSegments(segs[p.id!]),
          platforms,
          client: clientSlug || undefined,
          budget: { max_usd: num(maxUsd), max_hours: num(maxHours) },
        });
        out.push({ id: r.id, name: n });
      }
      setCreated(out);
      const e: Record<string, Estimate> = {};
      for (const b of out) e[b.id] = await client.estimate(b.id);
      setEsts(e);
      setStep('estimate');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function startPilot() {
    if (!client) return;
    setBusy(true);
    setError(null);
    try {
      for (const b of created) {
        const r = await client.run(b.id, { pilot });
        if (!r.started && r.status === 'over-budget') throw new Error(`${b.name}: ${t('est.budgetOver')}`);
      }
      go({ name: 'board', batch: created[0].id });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const validSource = files.length > 0 && NAME_RE.test(name) && platforms.length > 0 && minS < maxS;
  const cur = done[Math.min(curPlan, Math.max(0, done.length - 1))];

  return (
    <>
      <div className="topbar">
        <h1>{t('new.title')}</h1>
        {tabs}
        <div className="sp" />
        {step === 'segments' && (
          <button className="btn primary" disabled={!totalAccepted || busy || !NAME_RE.test(name)} onClick={createBatches} data-testid="create-batch">
            {busy ? t('common.working') : t('seg.create', { n: totalAccepted })}
          </button>
        )}
      </div>
      <div className="page" style={step === 'segments' ? undefined : { maxWidth: 900 }}>
        <div className="steps">
          {STEPS.map((s, i) => (
            <span key={s} className={step === s ? 'on' : ''}>
              {i + 1}. {t(`raw.step.${s}`)}
            </span>
          ))}
        </div>
        <ErrorBox error={error} />
        {step === 'source' && (
          <div className="col" style={{ gap: 14 }}>
            <Field label={t('raw.files')} hint={t('raw.filesHint')}>
              <div className="row">
                <div className="input" style={{ flex: 1, height: 'auto', minHeight: 30, padding: '5px 8px' }} data-testid="raw-files">
                  {files.length ? files.map((f) => <div key={f} className="mono small">{f}</div>) : <span className="muted">{t('new.pickFile')}</span>}
                </div>
                <button className="btn" onClick={pickFiles} data-testid="pick-files">
                  {t('common.choose')}
                </button>
              </div>
            </Field>
            <Field label={t('new.client')}>
              <ClientSelect value={clientSlug} onChange={setClientSlug} />
            </Field>
            <Field label={t('new.name')} hint={t('new.nameHint')}>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} data-testid="batch-name" />
            </Field>
            <Field label={t('new.platforms')}>
              <PlatformPicker value={platforms} onChange={setPlatforms} />
            </Field>
            <div className="row" style={{ gap: 12 }}>
              <Field label={t('raw.count')}>
                <input className="input" type="number" min={1} max={50} value={count} onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} style={{ width: 90 }} />
              </Field>
              <Field label={t('raw.min')}>
                <input className="input" type="number" min={5} max={600} value={minS} onChange={(e) => setMinS(Math.max(5, Math.min(600, Number(e.target.value) || 5)))} style={{ width: 90 }} />
              </Field>
              <Field label={t('raw.max')}>
                <input className="input" type="number" min={10} max={900} value={maxS} onChange={(e) => setMaxS(Math.max(10, Math.min(900, Number(e.target.value) || 10)))} style={{ width: 90 }} />
              </Field>
            </div>
            <Field label={t('raw.provider')} hint={t(`raw.providerHint.${provider}`)}>
              <div className="tabs" role="radiogroup">
                {PROVIDERS.map((p) => {
                  const missing = (p === 'claude' && keys && !keys.keys.anthropic) || (p === 'openai' && keys && !keys.keys.openai);
                  return (
                    <button key={p} role="radio" aria-checked={provider === p} className={`tab ${provider === p ? 'on' : ''}`} onClick={() => setProvider(p)} title={missing ? t('raw.noKey') : ''}>
                      {t(`raw.provider.${p}`)}
                      {missing ? ' ⚠' : ''}
                    </button>
                  );
                })}
              </div>
            </Field>
            {provider !== 'none' && keys && !keys.keys[provider === 'claude' ? 'anthropic' : 'openai'] && (
              <div className="notice">
                {t('raw.noKey')} <a href="#/settings">{t('nav.settings')}</a>
              </div>
            )}
            <div className="row" style={{ gap: 12 }}>
              <Field label={t('new.maxUsd')}>
                <input className="input" value={maxUsd} onChange={(e) => setMaxUsd(e.target.value)} inputMode="decimal" />
              </Field>
              <Field label={t('new.maxHours')}>
                <input className="input" value={maxHours} onChange={(e) => setMaxHours(e.target.value)} inputMode="decimal" />
              </Field>
            </div>
            <div className="row">
              <button className="btn primary" disabled={!validSource || busy} onClick={startPlanning} data-testid="start-plan">
                {busy ? t('common.working') : t('raw.plan')}
              </button>
            </div>
          </div>
        )}
        {step === 'plan' && (
          <div className="col" style={{ gap: 10 }}>
            {plans.map((p) => (
              <div key={p.file} className="card row">
                <span className="mono small" style={{ flex: 1 }}>
                  {p.file}
                </span>
                {p.error || p.state?.error ? (
                  <span className="err small">{p.error ?? p.state?.error}</span>
                ) : (
                  <span className="badge accent">{p.state ? tk(`raw.progress.${p.state.progress}`) : t('common.working')}</span>
                )}
              </div>
            ))}
            {plans.every((p) => p.error || (p.state && p.state.state !== 'running')) && !done.length && (
              <button className="btn" onClick={() => setStep('source')}>
                {t('common.back')}
              </button>
            )}
          </div>
        )}
        {step === 'segments' && cur && (
          <div className="col" style={{ gap: 10 }}>
            {done.length > 1 && (
              <div className="tabs">
                {done.map((p, i) => (
                  <button key={p.id} className={`tab ${p === cur ? 'on' : ''}`} onClick={() => setCurPlan(i)}>
                    {p.file.split(/[\\/]/).pop()} · {(segs[p.id!] ?? []).filter((s) => s.accepted).length}
                  </button>
                ))}
              </div>
            )}
            {cur.state?.result?.provider && (
              <div className="muted small">
                {t('raw.plannedBy', { p: tk(`raw.provider.${cur.state.result.provider}`) !== `raw.provider.${cur.state.result.provider}` ? tk(`raw.provider.${cur.state.result.provider}`) : cur.state.result.provider })}
              </div>
            )}
            <SegmentReview
              key={cur.id!}
              source={cur.file}
              duration={cur.state?.result?.duration ?? cur.state?.result?.words.at(-1)?.te ?? 0}
              words={cur.state?.result?.words ?? []}
              segs={segs[cur.id!] ?? []}
              onChange={(s) => setSegs((m) => ({ ...m, [cur.id!]: s }))}
            />
          </div>
        )}
        {step === 'estimate' && (
          <div className="col" style={{ gap: 14 }}>
            {created.map((b) => (
              <div key={b.id} className="col">
                <b>{b.name}</b>
                {ests[b.id] && <EstimateView est={ests[b.id]} />}
              </div>
            ))}
            <div className="row">
              <button className="btn primary" disabled={created.some((b) => !ests[b.id]?.budget.ok)} onClick={() => setStep('pilot')} data-testid="to-pilot">
                {t('new.toPilot')}
              </button>
            </div>
          </div>
        )}
        {step === 'pilot' && (
          <div className="col" style={{ gap: 14 }}>
            <div className="notice accent">{t('raw.pilotWhy')}</div>
            <Field label={t('new.pilotCount')}>
              <input className="input" type="number" min={1} max={50} value={pilot} onChange={(e) => setPilot(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} style={{ width: 100 }} />
            </Field>
            <div className="row">
              <button className="btn" onClick={() => setStep('estimate')}>
                {t('common.back')}
              </button>
              <button className="btn primary" disabled={busy} onClick={startPilot} data-testid="start-pilot">
                {t('new.startPilot', { n: pilot })}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
