// Board: one column per job state, cards with QC lights, filters, bulk actions, run controls + live log.
import { useEffect, useMemo, useState } from 'react';
import type { BatchStatus, Estimate, JobRow } from '../../../shared/types';
import { ErrorBox, Modal, PromptModal, QcLight, StateBadge } from '../components/ui';
import { t, tk } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { secs } from '../lib/format';
import { go } from '../lib/router';
import { EstimateView } from './NewBatch';
import { orderPlatforms } from '../../../shared/platforms';

const LANES: { key: string; states: string[] }[] = [
  { key: 'queued', states: ['planned'] },
  { key: 'running', states: ['running'] },
  { key: 'failed', states: ['failed'] },
  { key: 'review', states: ['done'] },
  { key: 'replan', states: ['needs-replan'] },
  { key: 'approved', states: ['approved'] },
  { key: 'packaged', states: ['packaged'] },
];

export function useBatchStatus(batch: string) {
  const { subscribe } = useEngine();
  const st = useLoad((c) => c.status(batch), [batch]);
  const [log, setLog] = useState<string[]>([]);
  const [lastExit, setLastExit] = useState<{ code: number; status: string } | null>(null);
  useEffect(
    () =>
      subscribe((e) => {
        if (!('batch' in e) || e.batch !== batch) return;
        if (e.type === 'status') st.setData(e.status as BatchStatus);
        if (e.type === 'log') setLog((l) => [...l.slice(-400), e.line]);
        if (e.type === 'run-start') {
          setLastExit(null);
          setLog((l) => [...l, `$ ${e.cmd.join(' ')}`]);
        }
        if (e.type === 'run-exit') {
          setLastExit({ code: e.code, status: e.status });
          st.reload();
        }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe, batch],
  );
  return { ...st, log, lastExit };
}

function progressPct(p: string): number {
  const [a, b] = p.split('/').map(Number);
  return b ? Math.round((100 * a) / b) : 0;
}

export function Board({ batch }: { batch: string }) {
  const { client } = useEngine();
  const { data, error, log, lastExit, reload } = useBatchStatus(batch);
  const [q, setQ] = useState('');
  const [qc, setQc] = useState<'all' | 'green' | 'red'>('all');
  const [platform, setPlatform] = useState('all');
  const [onlyPilot, setOnlyPilot] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [est, setEst] = useState<Estimate | null>(null);
  const [pilotN, setPilotN] = useState(3);

  const jobs = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data?.jobs ?? []).filter(
      (j) =>
        (!s || j.id.toLowerCase().includes(s) || j.title.toLowerCase().includes(s) || j.note.toLowerCase().includes(s)) &&
        (qc === 'all' || j.qc === qc) &&
        (platform === 'all' || j.platforms.includes(platform)) &&
        (!onlyPilot || j.pilot),
    );
  }, [data, q, qc, platform, onlyPilot]);
  const platforms = useMemo(() => orderPlatforms((data?.jobs ?? []).flatMap((j) => j.platforms)), [data]);

  const meta = data?.meta;
  const toggle = (id: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  async function act(fn: () => Promise<unknown>, okMsg?: string) {
    setMsg(null);
    try {
      await fn();
      if (okMsg) setMsg(okMsg);
      reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  const run = (opts: Parameters<NonNullable<typeof client>['run']>[1]) =>
    act(async () => {
      const r = await client!.run(batch, opts);
      if (!r.started) throw new Error(r.status === 'pilot-waits' ? t('board.pilotWaits') : r.status === 'over-budget' ? `${t('est.budgetOver')}: ${(r.over ?? []).join('; ')}` : r.status ?? 'not started');
      setShowLog(true);
    });

  const pickedRows = (data?.jobs ?? []).filter((j) => picked.has(j.id));
  const approvable = pickedRows.filter((j) => ['done', 'approved', 'needs-replan'].includes(j.state));

  return (
    <>
      <div className="topbar">
        <h1>{meta?.name ?? t('nav.board')}</h1>
        {meta && <StateBadge state={meta.running ? 'running' : meta.state} />}
        {meta?.pause_reason && <span className="small warnc">{meta.pause_reason}</span>}
        <div className="sp" />
        {meta?.running ? (
          <button className="btn danger" onClick={() => act(() => client!.cancel(batch))}>
            {t('board.stop')}
          </button>
        ) : (
          <>
            <button className="btn" onClick={() => act(async () => setEst(await client!.estimate(batch)))}>
              {t('board.estimate')}
            </button>
            <input className="input" type="number" min={1} max={50} value={pilotN} onChange={(e) => setPilotN(Math.max(1, Number(e.target.value) || 1))} style={{ width: 56 }} title={t('new.pilotCount')} />
            <button className="btn" onClick={() => run({ pilot: pilotN })}>
              {t('board.pilot')}
            </button>
            {meta?.state === 'pilot-review' ? (
              <button className="btn primary" onClick={() => confirm(t('board.confirmPilotQ')) && run({ confirm_pilot: true })}>
                {t('board.runAll')}
              </button>
            ) : (
              <button className="btn primary" onClick={() => run({})}>
                {t('board.run')}
              </button>
            )}
            {meta?.state === 'paused' && (
              <button className="btn" onClick={() => run({ resume: true })}>
                {t('board.resume')}
              </button>
            )}
          </>
        )}
        <button className="btn ghost" onClick={() => setShowLog((s) => !s)}>
          {t('board.log')}
        </button>
      </div>
      <div className="page" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <ErrorBox error={error ?? msg} />
        {lastExit && (
          <div className={`notice ${lastExit.code === 0 ? 'accent' : ''}`}>
            {t('board.exit', { status: tk(`exit.${lastExit.status}`) !== `exit.${lastExit.status}` ? tk(`exit.${lastExit.status}`) : lastExit.status })}
          </div>
        )}
        {showLog && <div className="log">{log.length ? log.join('\n') : t('board.noLog')}</div>}
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input className="input" placeholder={t('board.search')} value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 200 }} />
          <div className="tabs">
            {(['all', 'green', 'red'] as const).map((k) => (
              <button key={k} className={`tab ${qc === k ? 'on' : ''}`} onClick={() => setQc(k)}>
                {k === 'all' ? t('common.all') : t(`qc.${k}`)}
              </button>
            ))}
          </div>
          <select className="input" value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="all">{t('board.allPlatforms')}</option>
            {platforms.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <label className="row small">
            <input type="checkbox" checked={onlyPilot} onChange={(e) => setOnlyPilot(e.target.checked)} /> {t('board.onlyPilot')}
          </label>
          <div style={{ flex: 1 }} />
          {picked.size > 0 && (
            <>
              <span className="muted small">{t('board.picked', { n: picked.size })}</span>
              <button className="btn sm" disabled={!approvable.length} onClick={() => act(() => client!.applyReview(batch, { decisions: Object.fromEntries(approvable.map((j) => [j.id, { decision: 'approve' as const }])) }).then(() => setPicked(new Set())))}>
                {t('board.approve')}
              </button>
              <button className="btn sm" onClick={() => setRejecting(true)}>
                {t('board.reject')}
              </button>
              <button className="btn sm" disabled={meta?.running} onClick={() => run({ jobs: [...picked], retry_failed: pickedRows.some((j) => j.state === 'failed') }).then(() => setPicked(new Set()))}>
                {t('board.rerun')}
              </button>
              <button className="btn sm ghost" onClick={() => setPicked(new Set())}>
                {t('common.clear')}
              </button>
            </>
          )}
        </div>
        <div className="board" style={{ flex: 1 }}>
          {LANES.map((lane) => {
            const items = jobs.filter((j) => lane.states.includes(j.state));
            const greens = items.filter((j) => j.qc === 'green' && !j.sample);
            return (
              <div className="lane" key={lane.key}>
                <h3>
                  <span>{tk(`lane.${lane.key}`)}</span>
                  <span className="row">
                    {lane.key === 'review' && greens.length > 0 && (
                      <button className="btn sm" title={t('board.approveGreenHint')} onClick={() => act(() => client!.applyReview(batch, { decisions: Object.fromEntries(greens.map((j) => [j.id, { decision: 'approve' as const }])) }), t('board.approvedN', { n: greens.length }))}>
                        {t('board.approveGreen', { n: greens.length })}
                      </button>
                    )}
                    <span className="muted">{items.length}</span>
                  </span>
                </h3>
                <div className="cards">
                  {items.map((j) => (
                    <JobCard key={j.id} j={j} picked={picked.has(j.id)} onPick={() => toggle(j.id)} onOpen={() => go({ name: 'job', batch, job: j.id })} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {rejecting && (
        <PromptModal
          title={t('board.rejectTitle', { n: picked.size })}
          placeholder={t('review.reasonPh')}
          okLabel={t('board.reject')}
          onCancel={() => setRejecting(false)}
          onOk={(reason) => {
            setRejecting(false);
            void act(() => client!.applyReview(batch, { decisions: Object.fromEntries([...picked].map((id) => [id, { decision: 'reject' as const, reason }])) }).then(() => setPicked(new Set())));
          }}
        />
      )}
      {est && (
        <Modal title={t('board.estimate')} onClose={() => setEst(null)}>
          <EstimateView est={est} />
        </Modal>
      )}
    </>
  );
}

function JobCard({ j, picked, onPick, onOpen }: { j: JobRow; picked: boolean; onPick: () => void; onOpen: () => void }) {
  return (
    <div className={`jcard ${picked ? 'picked' : ''}`} onClick={(e) => (e.metaKey || e.shiftKey ? onPick() : onOpen())}>
      <div className="row">
        <input type="checkbox" checked={picked} onChange={onPick} onClick={(e) => e.stopPropagation()} />
        <QcLight qc={j.qc} title={[...j.qc_red, ...j.qc_warn].join('\n') || undefined} />
        <span className="mono small">{j.id}</span>
        {j.pilot && <span className="badge accent">{t('board.pilotBadge')}</span>}
        {j.sample && <span className="badge">{t('board.sampleBadge')}</span>}
      </div>
      <div className="t" title={j.title}>
        {j.title || <span className="muted">{t('board.untitled')}</span>}
      </div>
      {j.state === 'running' && (
        <>
          <div className="progress">
            <i style={{ width: `${progressPct(j.progress)}%` }} />
          </div>
          <div className="muted small">
            {j.stage} · {j.progress}
          </div>
        </>
      )}
      <div className="row muted small" style={{ flexWrap: 'wrap' }}>
        {orderPlatforms(j.platforms).map((p) => (
          <span className="badge" key={p}>
            {p}
          </span>
        ))}
        <span>{secs(j.duration)}</span>
      </div>
      {(j.note || j.qc_red[0]) && <div className="small err">{j.note || j.qc_red[0]}</div>}
    </div>
  );
}
