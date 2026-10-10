// Record a pickup (补录) in place of the player (ux/record/pickups A3): the same camera and mic as the recording, the
// selected words on the teleprompter when re-recording them (optional), 3-2-1 if she likes it, Space to start / stop,
// Esc to cancel. Stop -> the pickup is transcribed and spliced in on this Mac (one undo step) and the editor shows it.
// Nothing is silent: no camera, a refusal, a pickup without speech - each says so, with what to do.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, X } from 'lucide-react';
import type { OutputDoc } from '../../../../shared/v04';
import { fmtClock, t } from '../../i18n';
import { useEngine } from '../../lib/engine';
import { loadPrefs, SIZE_PX } from '../../create/record/recModel';
import { Teleprompter } from '../../create/record/Teleprompter';
import { loadDevices, useRecorder } from '../../create/record/useRecorder';
import { errText } from '../msg';
import { spotBody, type Spot } from './pickupModel';
import '../../create/record/record.css';
import './pickup.css';

type Phase = 'opening' | 'ready' | 'countdown' | 'recording' | 'stopping' | 'splicing' | 'failed';

export function PickupStage({ item, clip, doc, spot, onDone, onCancel }: { item: string; clip: string; doc: OutputDoc; spot: Spot; onDone: (r: { doc: OutputDoc; text: string }) => void; onCancel: () => void }) {
  const { client } = useEngine();
  const rec = useRecorder();
  const prefs = useRef(loadPrefs()).current;
  const [count, setCount] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>('opening');
  const [err, setErr] = useState<string | null>(null);
  const [prompt, setPrompt] = useState(spot.kind === 'replace');
  const video = useRef<HTMLVideoElement | null>(null);
  const session = useRef<string | null>(null);
  const { open } = rec;

  useEffect(() => {
    void open(loadDevices());
  }, [open]);
  useEffect(() => {
    if (rec.state === 'ready' && phase === 'opening') setPhase('ready');
    if ((rec.state === 'denied' || rec.state === 'error') && phase === 'opening') setPhase('failed');
  }, [rec.state, phase]);
  useEffect(() => {
    if (video.current && rec.stream) video.current.srcObject = rec.stream;
  }, [rec.stream, phase]);

  const discard = useCallback(async () => {
    const id = session.current;
    session.current = null;
    if (id) await window.desk.rec.discard(id).catch(() => undefined);
  }, []);

  const begin = useCallback(async () => {
    setErr(null);
    await discard();
    try {
      await rec.start({ slug: 'pickup', script: spot.kind === 'replace' && spot.text ? [spot.text.slice(0, 500)] : [], studio: doc.recording?.studio ?? prefs.studio, pickup: true });
      setPhase('recording');
    } catch (e) {
      setErr(errText(e));
      setPhase('failed');
    }
  }, [rec, spot, doc.recording, prefs.studio, discard]);

  const stop = useCallback(async () => {
    if (!client) return;
    setPhase('stopping');
    try {
      const out = await rec.stop();
      if (!out) return setPhase('ready');
      session.current = out.sessionId;
      if (out.secs < 0.5) throw new Error(t('pk.tooShort'));
      setPhase('splicing');
      const r = await client.pickupOutput(item, clip, { session_dir: out.dir, ...spotBody(spot), sig: doc.words_sig ?? null });
      session.current = null; // it is the clip's now (undo keeps it)
      onDone({ doc: r.doc, text: r.pickup?.text ?? '' });
    } catch (e) {
      setErr(errText(e));
      setPhase('failed');
    }
  }, [client, rec, item, clip, spot, doc.words_sig, onDone]);

  const cancel = useCallback(async () => {
    setCount(null);
    if (phase === 'recording') await rec.stop().then((o) => (session.current = o?.sessionId ?? session.current)).catch(() => undefined);
    await discard();
    onCancel();
  }, [phase, rec, discard, onCancel]);

  const main = useCallback(() => {
    if (phase === 'ready' || (phase === 'failed' && rec.stream)) {
      if (prefs.countdown) {
        setPhase('countdown');
        setCount(3);
      } else void begin();
    } else if (phase === 'countdown') {
      setCount(null);
      setPhase('ready');
    } else if (phase === 'recording') void stop();
  }, [phase, prefs.countdown, begin, stop, rec.stream]);

  useEffect(() => {
    if (count === null) return;
    if (count === 0) {
      setCount(null);
      void begin();
      return;
    }
    const tm = window.setTimeout(() => setCount((c) => (c === null ? null : c - 1)), 1000);
    return () => window.clearTimeout(tm);
  }, [count, begin]);

  const keys = useRef<(e: KeyboardEvent) => void>(() => undefined);
  keys.current = (e: KeyboardEvent) => {
    const el = e.target as HTMLElement | null;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
    if (e.key === ' ' && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (el?.tagName === 'BUTTON') el.blur();
      main();
    } else if (e.key === 'Escape' && phase !== 'splicing' && phase !== 'stopping') {
      e.preventDefault();
      e.stopImmediatePropagation();
      void cancel();
    }
  };
  useEffect(() => {
    const k = (e: KeyboardEvent) => keys.current(e);
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, []);

  const busy = phase === 'stopping' || phase === 'splicing';
  const where = spot.kind === 'replace' ? t('pk.whereReplace', { text: clipText(spot.text) }) : t('pk.whereAfter', { text: clipText(spot.text, true) });
  return (
    <div className="pk-stage" data-testid="pickup-stage" data-phase={phase}>
      <div className="pk-head">
        <span className="pk-dot" />
        <b>{t('pk.title')}</b>
        <span className="muted clamp1" lang="zh-CN">
          {where}
        </span>
        <span className="sp" />
        {spot.kind === 'replace' && spot.text && (
          <label className="pk-toggle">
            <input type="checkbox" checked={prompt} onChange={(e) => setPrompt(e.target.checked)} data-testid="pickup-prompt-toggle" />
            {t('pk.showWords')}
          </label>
        )}
        <button className="btn ghost icon sm" disabled={busy} onClick={() => void cancel()} aria-label={t('pk.cancel')} data-tip={`${t('pk.cancel')} · Esc`} data-testid="pickup-cancel">
          <X className="ico" />
        </button>
      </div>
      <div className="rs-cam pk-cam">
        {rec.stream ? <video ref={video} autoPlay muted playsInline className={prefs.mirrorPreview ? 'mirror' : ''} data-testid="pickup-preview" /> : null}
        {prompt && spot.text && <Teleprompter lines={[spot.text]} cur={0} progress={0} size={SIZE_PX[prefs.size]} mirror={prefs.mirrorText} />}
        {phase === 'recording' && (
          <span className="rs-badge" data-testid="pickup-live">
            <i />
            {t('rec.live', { t: fmtClock(rec.elapsed) })}
          </span>
        )}
        {phase === 'countdown' && <div className="rs-count">{count}</div>}
        {busy && (
          <div className="rs-count rs-preparing" role="status" data-testid="pickup-splicing">
            <span>{phase === 'splicing' ? t('pk.splicing') : t('rec.saving')}</span>
          </div>
        )}
        {phase === 'opening' && <div className="rs-count rs-preparing">{t('pk.opening')}</div>}
      </div>
      {phase === 'failed' && (
        <div className="pk-err" role="alert" data-testid="pickup-error">
          {rec.state === 'denied' ? (
            <>
              <span>{t('rec.permDenied')}</span>
              <button className="btn sm" onClick={() => void window.desk.rec.openPrivacy('camera')}>
                {t('rec.permOpen')}
              </button>
            </>
          ) : (
            <span>{err ?? rec.error ?? t('pk.failed')}</span>
          )}
        </div>
      )}
      <div className="pk-dock">
        <span className="rs-lvl" aria-hidden>
          <Mic className="ico" />
          <i style={{ width: `${Math.round(Math.min(1, rec.level * 3) * 100)}%` }} />
        </span>
        <button
          type="button"
          className={`rs-rec ${phase === 'recording' || phase === 'countdown' ? 'stop' : 'start'}`}
          disabled={busy || phase === 'opening' || (!rec.stream && phase === 'failed')}
          onClick={main}
          aria-label={phase === 'recording' ? t('pk.stop') : t('pk.record')}
          title={`${phase === 'recording' ? t('pk.stop') : t('pk.record')} (Space)`}
          data-testid={phase === 'recording' ? 'pickup-stop' : 'pickup-record'}
        >
          <i />
        </button>
        <span className="muted small pk-hint">{phase === 'recording' ? t('pk.hintRec') : phase === 'failed' && rec.stream ? t('pk.hintRetry') : t('pk.hintReady')}</span>
      </div>
    </div>
  );
}

function clipText(s: string, tail = false): string {
  if (s.length <= 40) return s;
  return tail ? `…${s.slice(-38)}` : `${s.slice(0, 38)}…`;
}
