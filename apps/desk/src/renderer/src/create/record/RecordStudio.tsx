// Record yourself (C08): script on the left, the dark stage with the teleprompter and the camera, takes on the right.
// Space pauses the prompter, ↑ / ↓ change line, ⌘R = say this line again (a retake mark). On Stop the session is
// cleaned on this Mac (best take per line, pauses / fillers, studio sound) and opened as a talking-head project.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AudioLines, Camera, Lightbulb, Mic, Monitor, RotateCcw } from 'lucide-react';
import type { EpisodeView } from '../../../../shared/create';
import { fmtClock, t } from '../../i18n';
import { useHistory } from '../../lib/history';
import { href } from '../../lib/router';
import { useAction, useCreate, useCreateLoad, waitJob } from '../api';
import { Crumbs, l10n } from '../bits';
import { lineSeconds, Teleprompter } from './Teleprompter';
import { useRecorder } from './useRecorder';
import { keyHint } from '../../lib/keys';

interface Ingested {
  project_id?: string;
  duration: number;
  lines: { line: number; attempts: number }[];
  retakes: number;
  imported?: { shot: string }[];
}

interface TakeRow {
  n: number;
  secs: number;
  lastLine: number;
}

export function RecordStudio({ sid, eid, shot }: { sid?: string; eid?: string; shot?: string }) {
  const c = useCreate();
  const history = useHistory();
  const epLoad = useCreateLoad((x) => (eid ? x.episode(eid) : Promise.resolve(null as EpisodeView | null)), [eid]);
  const ep = epLoad.data;
  const fromEpisode = useMemo(() => {
    if (!ep) return null;
    const shots = shot ? ep.shots.filter((s) => s.no === shot) : ep.shots;
    return shots.flatMap((s) => s.lines.map((l) => l.text)).filter(Boolean);
  }, [ep, shot]);
  const [own, setOwn] = useState<string>('');
  const [editing, setEditing] = useState(!eid);
  const lines = useMemo(() => (fromEpisode && !editing && !own ? fromEpisode : own.split('\n').map((x) => x.trim()).filter(Boolean)), [fromEpisode, own, editing]);
  const rec = useRecorder();
  const [cur, setCur] = useState(0);
  const [progress, setProgress] = useState(0);
  const [paused, setPaused] = useState(false);
  const [size, setSize] = useState(30);
  const [mirror, setMirror] = useState(false);
  const [screenOn, setScreenOn] = useState(false);
  const [takes, setTakes] = useState<TakeRow[]>([]);
  const [lineTakes, setLineTakes] = useState<Record<number, number>>({});
  const [result, setResult] = useState<Ingested | null>(null);
  const ingest = useAction();
  const video = useRef<HTMLVideoElement | null>(null);
  const takeNo = takes.length + 1;
  const recording = rec.state === 'recording';

  useEffect(() => {
    if (video.current && rec.stream) video.current.srcObject = rec.stream;
  }, [rec.stream]);

  // the prompter scrolls at a steady pace while recording
  useEffect(() => {
    if (!recording || paused || !lines.length) return;
    const step = 100;
    const tm = window.setInterval(() => {
      setProgress((p) => {
        const dur = lineSeconds(lines[cur] ?? '');
        const next = p + step / 1000 / dur;
        if (next >= 1) {
          if (cur < lines.length - 1) {
            const n = cur + 1;
            setCur(n);
            void rec.mark('line', n);
            setLineTakes((m) => ({ ...m, [cur]: takeNo }));
            return 0;
          }
          return 1;
        }
        return next;
      });
    }, step);
    return () => window.clearInterval(tm);
  }, [recording, paused, cur, lines, rec, takeNo]);

  const goLine = useCallback(
    (n: number) => {
      const k = Math.max(0, Math.min(lines.length - 1, n));
      setCur(k);
      setProgress(0);
      if (recording) void rec.mark('line', k);
    },
    [lines.length, recording, rec],
  );

  const retake = useCallback(() => {
    if (!recording) return;
    setProgress(0);
    void rec.mark('retake', cur);
  }, [recording, rec, cur]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'TEXTAREA' || tag === 'INPUT') return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'r') {
        e.preventDefault();
        retake();
      } else if (e.key === ' ' && recording) {
        e.preventDefault();
        setPaused((p) => !p);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        goLine(cur + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        goLine(cur - 1);
      }
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [retake, goLine, cur, recording]);

  const [startErr, setStartErr] = useState<string | null>(null);
  const start = async () => {
    setStartErr(null);
    try {
      await begin();
    } catch (e) {
      setStartErr((e as Error).message);
    }
  };
  const begin = async () => {
    setResult(null);
    setCur(0);
    setProgress(0);
    setPaused(false);
    const slug = (ep ? `ep${ep.no}` : 'recording').replace(/[^a-z0-9-]/g, '-');
    await rec.start({ slug, title: ep ? t('create.ep.title', { n: ep.no, title: ep.title }) : undefined, script: lines, series: sid ?? ep?.series, episode: eid, shot });
    await rec.mark('line', 0);
  };

  const stop = async () => {
    const secs = rec.elapsed;
    const out = await rec.stop();
    if (!out) return;
    setTakes((tk) => [{ n: tk.length + 1, secs, lastLine: cur }, ...tk]);
    setLineTakes((m) => ({ ...m, [cur]: takeNo }));
    void ingest.run(async () => {
      if (!c) return;
      const target = eid && shot ? `shot:${eid}/${shot}` : 'project:talkinghead';
      const { job } = await c.ingest(out.dir, target, sid ?? ep?.series);
      const res = await waitJob<Ingested>(c, job);
      history.reload(); // the new talking-head project shows up in All projects / its page at once
      setResult(res);
    });
  };

  const lvl = Math.min(1, rec.level * 3);
  return (
    <div className="cr cr-rec" data-testid="create-record">
      <div className="script">
        <Crumbs items={[{ label: t('create.crumb'), to: { screen: 'home' } }, ...(ep ? [{ label: ep.series_name, to: { screen: 'series' as const, sid: ep.series, tab: 'bible' as const } }] : [])]} />
        <h1>{ep ? t('create.ep.title', { n: ep.no, title: ep.title }) : t('create.rec.title')}</h1>
        <div className="muted" style={{ fontSize: 15 }}>
          {ep && t('create.rec.meta', { beats: ep.format.beats.map((b) => l10n(b.labels)).slice(0, 3).join(' → '), s: Math.round(ep.runtime) })}
          {ep && ' · '}
          <button className="link" onClick={() => setEditing(!editing)} data-testid="create-rec-edit">
            {editing ? t('create.rec.doneEditing') : t('create.rec.editScript')}
          </button>
        </div>
        {editing ? (
          <textarea value={own || (fromEpisode ?? []).join('\n')} onChange={(e) => setOwn(e.target.value)} placeholder={t('create.rec.scriptPh')} data-testid="create-rec-script" />
        ) : (
          <div className="lines">
            {lines.map((l, i) => (
              <button key={i} className={`ln ${i === cur ? 'cur' : ''}`} onClick={() => goLine(i)}>
                <span className="k">{i + 1}</span>
                <span>{l}</span>
                <span className="mk">{i === cur && recording ? t('create.rec.recording') : lineTakes[i] ? t('create.rec.take', { n: lineTakes[i] }) : ''}</span>
              </button>
            ))}
          </div>
        )}
        <div className="tip">
          <Lightbulb className="ico" />
          <span>{t('create.rec.tip')}</span>
        </div>
      </div>

      <div className="cr-stage">
        {rec.state === 'idle' || rec.state === 'asking' || rec.state === 'denied' || rec.state === 'error' ? (
          <div className="cr-perm" data-testid="create-rec-perm">
            <Camera className="ico lg" />
            <div className="t1">{t('create.rec.permTitle')}</div>
            <div className="t2">{t('create.rec.permBody')}</div>
            {rec.state === 'denied' ? (
              <>
                <div className="t2">{t('create.rec.permDenied')}</div>
                <button className="btn" onClick={() => void window.desk.rec.openPrivacy('camera')}>
                  {t('create.rec.permOpen')}
                </button>
              </>
            ) : (
              <button className="btn primary lg" disabled={rec.state === 'asking'} onClick={() => void rec.open()} data-testid="create-rec-allow">
                {t('create.rec.permAllow')}
              </button>
            )}
            {rec.error && <div className="t2">{rec.error}</div>}
          </div>
        ) : (
          <>
            <Teleprompter lines={lines} cur={cur} progress={progress} size={size} mirror={mirror} paused={paused} onSize={setSize} onMirror={() => setMirror(!mirror)} />
            <div className="cr-cam">
              <video ref={video} autoPlay muted playsInline data-testid="create-rec-preview" />
              {recording && (
                <span className="recb" data-testid="create-rec-live">
                  <i />
                  {t('create.rec.rec', { n: takeNo })}
                </span>
              )}
            </div>
            <div className="cr-ctrls">
              <span className="cr-ctrl">
                <Camera className="ico" />
                <span className="tx">{t('create.rec.camera')}</span>
              </span>
              <span className="cr-ctrl" aria-label={t('create.rec.studio')}>
                <Mic className="ico" />
                <span className="lvl">
                  {[0.2, 0.45, 0.7, 0.95, 0.6, 0.35].map((k, i) => (
                    <i key={i} style={{ height: `${Math.max(3, Math.min(18, lvl * 18 * k + 3))}px` }} />
                  ))}
                </span>
              </span>
              <button
                className={`cr-ctrl ${screenOn ? '' : 'off'}`}
                disabled={recording}
                onClick={() => void rec.toggleScreen().then(setScreenOn)}
                data-testid="create-rec-screen"
              >
                <Monitor className="ico" />
                <span className="tx">{screenOn ? t('create.rec.screen') : t('create.rec.off')}</span>
              </button>
              <button
                className={`cr-recbtn ${recording ? 'on' : ''}`}
                disabled={rec.state === 'stopping' || !lines.length || ingest.busy}
                onClick={() => void (recording ? stop() : start())}
                aria-label={recording ? t('create.rec.stop') : t('create.rec.start')}
                data-testid={recording ? 'create-rec-stop' : 'create-rec-start'}
              >
                <i />
              </button>
              <span className="cr-timer">{fmtClock(rec.elapsed)}</span>
              <span className="cr-ctrl">
                <AudioLines className="ico" />
                <span className="tx">{t('create.rec.studio')}</span>
              </span>
              <button className="cr-ctrl" disabled={!recording} onClick={retake} data-testid="create-rec-retake">
                <RotateCcw className="ico" />
                <span className="tx">{t('create.rec.retake')}</span> {keyHint('⌘R')}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="side">
        <h3>{t('create.rec.takes')}</h3>
        <div className="muted" style={{ fontSize: 15, marginTop: 4 }}>
          {t('create.rec.takesSub')}
        </div>
        {takes.map((tk, i) => (
          <div key={tk.n} className={`cr-take ${i === 0 ? 'best' : ''}`} data-testid="create-rec-take">
            <span className="tn" />
            <div>
              <div className="t1">{t('create.rec.takeRow', { n: tk.n, t: fmtClock(tk.secs) })}</div>
              <div className="t2">{i === 0 ? t('create.rec.takeBest', { n: tk.lastLine + 1 }) : t('create.rec.takeStopped', { n: tk.lastLine + 1 })}</div>
            </div>
          </div>
        ))}
        {ingest.busy && (
          <div className="cr-take" data-testid="create-rec-processing">
            <div className="t2">{t('create.rec.processing')}</div>
          </div>
        )}
        {result && (
          <div className="cr-take best" data-testid="create-rec-result" style={{ flexDirection: 'column' }}>
            <div className="t1">{result.imported ? t('create.rec.doneShot', { no: shot ?? '' }) : t('create.rec.done')}</div>
            <div className="t2">{t('create.rec.doneBody', { n: result.lines.length, r: result.retakes, s: Math.round(result.duration) })}</div>
            {result.project_id && (
              <a className="btn primary" href={href({ name: 'project', id: result.project_id })} data-testid="create-rec-open">
                {t('create.rec.openProject')}
              </a>
            )}
          </div>
        )}
        {(ingest.error || startErr || rec.error) && <div className="cr-err">{ingest.error ?? startErr ?? rec.error}</div>}
        <div className="cr-when">
          <b>{t('create.rec.whenStop')}</b> {t('create.rec.whenStopBody')}
        </div>
      </div>
    </div>
  );
}
