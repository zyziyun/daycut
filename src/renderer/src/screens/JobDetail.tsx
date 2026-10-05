// Job detail: player, QC reasons, stages, and the transcript with cleanup edits struck through. Clicking an edit
// toggles it; "save" turns the toggles into a cleanup reply (确认 … / 保留 …) and the job re-cuts on the next run.
import { useEffect, useMemo, useState } from 'react';
import { buildReply, canToggle } from '../../../shared/cleanupReply';
import type { CleanupEdit, CleanupPart } from '../../../shared/types';
import { ErrorBox, Media, PromptModal, QcLight, StateBadge } from '../components/ui';
import { t, tStage } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { secs } from '../lib/format';
import { href } from '../lib/router';

export function JobDetail({ batch, job }: { batch: string; job: string }) {
  const { client } = useEngine();
  const { data, error, reload } = useLoad((c) => c.job(batch, job), [batch, job]);
  const [cut, setCut] = useState<Record<number, boolean>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [video, setVideo] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const m: Record<number, boolean> = {};
    for (const p of data.cleanup.parts) for (const e of p.edits) m[e.id] = e.cut;
    setCut(m);
    setVideo(data.media.exports[0]?.file ?? data.media.snippet ?? data.media.master ?? null);
  }, [data]);

  const allEdits = useMemo(() => data?.cleanup.parts.flatMap((p) => p.edits) ?? [], [data]);
  const reply = useMemo(() => buildReply(allEdits.map((e) => ({ id: e.id, action: e.action, cut: cut[e.id] ?? e.cut }))), [allEdits, cut]);
  const dirty = allEdits.some((e) => (cut[e.id] ?? e.cut) !== e.cut);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  if (!data) {
    return (
      <>
        <div className="topbar">
          <h1>{job}</h1>
        </div>
        <div className="page">
          <ErrorBox error={error} />
        </div>
      </>
    );
  }
  const j = data.job;
  const red = j.qc_reasons?.red ?? [];
  const warn = j.qc_reasons?.warn ?? [];

  return (
    <>
      <div className="topbar">
        <a className="btn ghost sm" href={href({ name: 'board', batch })}>
          ← {t('nav.board')}
        </a>
        <h1 className="mono">{j.id}</h1>
        <StateBadge state={j.state} />
        <QcLight qc={j.qc} />
        <div className="sp" />
        <button className="btn" disabled={!['done', 'approved', 'needs-replan'].includes(j.state)} onClick={() => act(() => client!.applyReview(batch, { decisions: { [j.id]: { decision: 'approve' } } }), t('review.approved'))}>
          {t('review.k.approve')}
        </button>
        <button className="btn" onClick={() => setRejecting(true)}>
          {t('review.k.reject')}
        </button>
        <button className="btn" onClick={() => act(() => client!.run(batch, { jobs: [j.id], retry_failed: j.state === 'failed' }), t('job.rerunStarted'))}>
          {t('job.rerun')}
        </button>
      </div>
      <div className="page" style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 420px) 1fr', gap: 16, alignItems: 'start' }}>
        <div className="col">
          {video ? <video key={video} className="thumb" style={{ aspectRatio: '9 / 16', maxHeight: '62vh' }} src={window.desk.mediaUrl(video)} controls playsInline /> : <Media path={null} kind="video" />}
          <div className="tabs">
            {data.media.exports.map((e) => (
              <button key={e.file} className={`tab ${video === e.file ? 'on' : ''}`} onClick={() => setVideo(e.file)}>
                {e.platform}-{e.orientation}
              </button>
            ))}
            {data.media.snippet && (
              <button className={`tab ${video === data.media.snippet ? 'on' : ''}`} onClick={() => setVideo(data.media.snippet)}>
                {t('job.snippet')}
              </button>
            )}
          </div>
          <div className="card col small">
            <b>{String(j.params.title ?? '') || t('board.untitled')}</b>
            <div className="muted">
              {(j.params.platforms as string[] | undefined)?.join(', ')} · {t('job.cost')} ${j.cost?.toFixed(2)}
            </div>
            {j.review_reason && <div className="err">{t('review.rejected')}: {j.review_reason}</div>}
            {red.map((r) => (
              <div key={r} className="err">
                ● {r}
              </div>
            ))}
            {warn.map((r) => (
              <div key={r} className="warnc">
                ● {r}
              </div>
            ))}
            {!red.length && !warn.length && <div className="muted">{t('job.noQc')}</div>}
          </div>
          <div className="card">
            <table className="t small">
              <tbody>
                {data.stages.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td>
                    <td>
                      <span className={`badge ${s.state === 'failed' ? 'danger' : ''}`}>{tStage(s.state)}</span>
                      {s.cached && <span className="muted"> {t('job.cached')}</span>}
                    </td>
                    <td className="muted">{secs(s.seconds)}</td>
                    <td className="err">{s.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="col">
          <ErrorBox error={error} />
          {msg && <div className="notice accent">{msg}</div>}
          <div className="row">
            <b>{t('job.transcript')}</b>
            <span className="muted small">{t('job.transcriptHint')}</span>
            <div style={{ flex: 1 }} />
            <span className="mono small muted" title={t('job.reply')}>
              {reply || '—'}
            </span>
            <button className="btn primary sm" disabled={!dirty} onClick={() => act(() => client!.applyReview(batch, { cleanup: { [j.id]: reply } }), t('job.saved'))}>
              {t('job.save')}
            </button>
          </div>
          <div className="row small muted">
            <span className="transcript">
              <span className="edit auto cut">{t('job.legendAuto')}</span> <span className="edit confirm">{t('job.legendConfirm')}</span>
            </span>
          </div>
          {data.cleanup.parts.length === 0 && <div className="muted">{t('job.noTranscript')}</div>}
          {data.cleanup.parts.map((p) => (
            <div key={p.part} className="card">
              <div className="muted small" style={{ marginBottom: 6 }}>
                {p.part === 'hook' ? t('job.hook') : t('job.body')}
              </div>
              <Transcript part={p} cut={cut} onToggle={(e) => canToggle(e) && setCut((c) => ({ ...c, [e.id]: !(c[e.id] ?? e.cut) }))} />
            </div>
          ))}
        </div>
      </div>
      {rejecting && (
        <PromptModal
          title={t('review.rejectTitle', { id: j.id })}
          placeholder={t('review.reasonPh')}
          okLabel={t('review.k.reject')}
          onCancel={() => setRejecting(false)}
          onOk={(reason) => {
            setRejecting(false);
            void act(() => client!.applyReview(batch, { decisions: { [j.id]: { decision: 'reject', reason: reason || 'rejected' } } }), t('review.rejected'));
          }}
        />
      )}
    </>
  );
}

function Transcript({ part, cut, onToggle }: { part: CleanupPart; cut: Record<number, boolean>; onToggle: (e: CleanupEdit) => void }) {
  const byWord = new Map<number, CleanupEdit>();
  for (const e of part.edits) for (const w of e.words) if (!byWord.has(w)) byWord.set(w, e);
  const pauses = part.edits.filter((e) => e.words.length === 0).sort((a, b) => a.t0 - b.t0);
  const out: React.ReactNode[] = [];
  let pi = 0;
  part.words.forEach((w, i) => {
    while (pi < pauses.length && pauses[pi].t0 <= w.t) {
      const e = pauses[pi++];
      const isCut = cut[e.id] ?? e.cut;
      out.push(
        <span key={`p${e.id}`} className={`pause ${isCut ? 'cut' : ''}`} title={`#${e.id} ${e.kind}: ${e.reason}`} onClick={() => onToggle(e)}>
          {e.kind} {(e.t1 - e.t0).toFixed(1)}s
        </span>,
      );
    }
    const e = byWord.get(i);
    if (!e) {
      out.push(
        <span key={i} className="w">
          {w.w}{' '}
        </span>,
      );
      return;
    }
    const isCut = cut[e.id] ?? e.cut;
    out.push(
      <span key={i} className={`w edit ${e.action} ${isCut ? 'cut' : ''}`} title={`#${e.id} ${e.kind} (${e.action}): ${e.reason}`} onClick={() => onToggle(e)}>
        {w.w}{' '}
      </span>,
    );
  });
  return <div className="transcript">{out}</div>;
}
