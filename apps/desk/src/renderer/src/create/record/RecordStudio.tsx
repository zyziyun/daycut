// Record yourself (ux/record/redesign A): what to say on the left (a script, or speak freely), the dark stage in the
// middle (the teleprompter on the preview right under the lens, one big record button, devices and settings in
// popovers), your takes on the right with one primary action: Finish — make my video. Finish stitches the best take
// of each line on this Mac (vstudio.create record ingest, target "assembled") and hands the file to an autopilot
// request, exactly like a request from Home; from a storyboard shot it becomes that shot's take instead.
// Keys: Space record / stop · P pause · ⌘R say this line again · ↑ / ↓ change line.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AudioLines, Camera, ChevronLeft, ChevronRight, Lightbulb, Mic, Monitor, Pause, Play, RotateCcw, Settings2, Trash2 } from 'lucide-react';
import type { EpisodeView } from '../../../../shared/create';
import { fmtClock, getLang, t } from '../../i18n';
import { useHistory } from '../../lib/history';
import { useEngine } from '../../lib/engine';
import { href } from '../../lib/router';
import { keyHint } from '../../lib/keys';
import { useAssets } from '../../components/assets';
import { downloadSummary } from '../../lib/firstRun';
import { useUi } from '../../v4/ui';
import { errText, useAction, useCreateLoad, waitJob } from '../api';
import { Crumbs, l10n } from '../bits';
import { Pop } from './Pop';
import { blockReason, chosenTake, keyAction, loadPrefs, mainAction, savePrefs, scriptLines, scriptSeconds, scrollStep, SIZE_PX, slugOf, WPM, type Phase, type RecPrefs, type Take } from './recModel';
import { Teleprompter } from './Teleprompter';
import { useRecorder } from './useRecorder';
import './record.css';

interface Ingested {
  assembled?: string;
  duration: number;
  lines: { line: number; attempts: number }[];
  retakes: number;
  imported?: { shot: string }[];
}

const KEY_RETAKE = keyHint('⌘R');

function Kbd({ k }: { k: string }) {
  return <kbd className="rs-kbd">{k}</kbd>;
}

/** "{space} stop" style hints: each key placeholder becomes a key cap. */
function withKeys(key: Parameters<typeof t>[0], keys: Record<string, string>) {
  const marks = Object.fromEntries(Object.keys(keys).map((k) => [k, `\ue000${k}\ue000`]));
  return t(key, marks)
    .split(/\ue000(\w+)\ue000/)
    .map((part, i) => (i % 2 ? <Kbd key={i} k={keys[part] ?? part} /> : part ? <span key={i}>{part}</span> : null));
}

export function RecordStudio({ sid, eid, shot }: { sid?: string; eid?: string; shot?: string }) {
  const { client } = useEngine();
  const history = useHistory();
  const ui = useUi();
  const assets = useAssets();
  const modelsReady = !assets?.bundled || (downloadSummary(assets).state === 'done' && !assets.restartNeeded);
  const modelsRef = useRef(modelsReady);
  modelsRef.current = modelsReady;

  const epLoad = useCreateLoad((x) => (eid ? x.episode(eid) : Promise.resolve(null as EpisodeView | null)), [eid]);
  const ep = epLoad.data;
  const fromEpisode = useMemo(() => {
    if (!ep) return '';
    const shots = shot ? ep.shots.filter((s) => s.no === shot) : ep.shots;
    return shots
      .flatMap((s) => s.lines.map((l) => l.text))
      .filter(Boolean)
      .join('\n');
  }, [ep, shot]);

  const [prefs, setPrefs] = useState<RecPrefs>(loadPrefs);
  const setPref = <K extends keyof RecPrefs>(k: K, v: RecPrefs[K]) =>
    setPrefs((p) => {
      const n = { ...p, [k]: v };
      savePrefs(n);
      return n;
    });
  const [text, setText] = useState('');
  const touched = useRef(false);
  useEffect(() => {
    if (fromEpisode && !touched.current) setText(fromEpisode);
  }, [fromEpisode]);
  const [editing, setEditing] = useState(true);
  useEffect(() => {
    if (fromEpisode && !touched.current) setEditing(false);
  }, [fromEpisode]);
  const [panel, setPanel] = useState(true);
  const useScript = prefs.script;
  const lines = useMemo(() => (useScript ? scriptLines(text) : []), [text, useScript]);

  const rec = useRecorder();
  const { mark } = rec;
  const [screenOk, setScreenOk] = useState(false);
  useEffect(() => {
    void window.desk.rec
      .status()
      .then((s) => setScreenOk(!!s.screenPicker))
      .catch(() => setScreenOk(false));
  }, []);
  const [tp, setTp] = useState({ cur: 0, progress: 0 });
  const tpRef = useRef(tp);
  const reached = useRef(0);
  const redone = useRef(new Set<number>());
  const [count, setCount] = useState<number | null>(null);
  const [pop, setPop] = useState<string | null>(null);
  const [takes, setTakes] = useState<Take[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const takeNo = useRef(0);
  const [ask, setAsk] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [stage, setStage] = useState<'working' | 'models' | null>(null);
  const [shotDone, setShotDone] = useState<Ingested | null>(null);
  const finishing = useAction();
  const video = useRef<HTMLVideoElement | null>(null);

  const live = rec.state === 'recording' || rec.state === 'paused' || rec.state === 'stopping';
  const off = !rec.stream || rec.state === 'idle' || rec.state === 'asking' || rec.state === 'denied' || rec.state === 'error';
  const phase: Phase = off && !live ? 'off' : count !== null ? 'countdown' : rec.state === 'recording' ? 'recording' : rec.state === 'paused' ? 'paused' : rec.state === 'stopping' ? 'stopping' : 'ready';
  const blocked = blockReason({ phase, useScript, lines: lines.length, busy: finishing.busy });
  const setTpBoth = (v: { cur: number; progress: number }) => {
    tpRef.current = v;
    setTp(v);
  };

  useEffect(() => {
    if (video.current && rec.stream) video.current.srcObject = rec.stream;
  }, [rec.stream, phase]);

  // the prompter scrolls at a steady pace while recording (not while paused)
  useEffect(() => {
    if (phase !== 'recording' || !useScript || !lines.length) return;
    const step = 100;
    const tm = window.setInterval(() => {
      const n = scrollStep({ lines, cur: tpRef.current.cur, progress: tpRef.current.progress, dt: step / 1000, wpm: WPM[prefs.speed] });
      if (n.advanced) {
        reached.current = Math.max(reached.current, n.cur);
        void mark('line', n.cur);
      }
      tpRef.current = { cur: n.cur, progress: n.progress };
      setTp(tpRef.current);
    }, step);
    return () => window.clearInterval(tm);
  }, [phase, useScript, lines, prefs.speed, mark]);

  const goLine = useCallback(
    (n: number) => {
      if (!lines.length) return;
      const k = Math.max(0, Math.min(lines.length - 1, n));
      setTpBoth({ cur: k, progress: 0 });
      if (rec.state === 'recording' || rec.state === 'paused') {
        reached.current = Math.max(reached.current, k);
        void mark('line', k);
      }
    },
    [lines.length, rec.state, mark],
  );

  const retake = useCallback(() => {
    if (rec.state !== 'recording' || !useScript || !lines.length) return;
    const cur = tpRef.current.cur;
    setTpBoth({ cur, progress: 0 });
    redone.current.add(cur);
    void mark('retake', cur);
  }, [rec.state, useScript, lines.length, mark]);

  const begin = async () => {
    setErr(null);
    setShotDone(null);
    setTpBoth({ cur: 0, progress: 0 });
    reached.current = 0;
    redone.current = new Set();
    try {
      await rec.start({
        slug: slugOf(ep ? `ep${ep.no}` : 'recording'),
        title: ep ? t('create.ep.title', { n: ep.no, title: ep.title }) : undefined,
        script: lines,
        series: sid ?? ep?.series,
        episode: eid,
        shot,
        studio: prefs.studio,
      });
      await mark('line', 0);
    } catch (e) {
      setErr(errText(e));
    }
  };

  const grab = (): string | null => {
    const v = video.current;
    if (!v || !v.videoWidth) return null;
    try {
      const c = document.createElement('canvas');
      c.height = 160;
      c.width = Math.round((160 * v.videoWidth) / v.videoHeight);
      c.getContext('2d')?.drawImage(v, 0, 0, c.width, c.height);
      return c.toDataURL('image/jpeg', 0.7);
    } catch {
      return null;
    }
  };

  const stop = async () => {
    const thumb = grab();
    try {
      const out = await rec.stop();
      if (!out) return;
      takeNo.current += 1;
      const tk: Take = {
        id: out.sessionId,
        dir: out.dir,
        n: takeNo.current,
        secs: out.secs,
        lines: useScript ? Math.min(lines.length, reached.current + 1) : 0,
        total: useScript ? lines.length : 0,
        retakes: redone.current.size,
        thumb,
      };
      setTakes((x) => [tk, ...x]);
      setChosen(tk.id);
    } catch (e) {
      setErr(errText(e));
    }
  };

  const onMain = () => {
    const a = mainAction(phase, prefs.countdown);
    if ((a === 'countdown' || a === 'start') && blocked) return;
    setPop(null);
    if (a === 'countdown') setCount(3);
    else if (a === 'start') void begin();
    else if (a === 'cancel') setCount(null);
    else if (a === 'stop') void stop();
  };
  const onPause = () => (rec.state === 'paused' ? rec.resume() : rec.state === 'recording' ? rec.pause() : undefined);

  // 3-2-1, then record
  useEffect(() => {
    if (count === null) return;
    if (count === 0) {
      setCount(null);
      void begin();
      return;
    }
    const tm = window.setTimeout(() => setCount((c) => (c === null ? null : c - 1)), 1000);
    return () => window.clearTimeout(tm);
  }, [count]); // eslint-disable-line react-hooks/exhaustive-deps

  const keyRef = useRef<(e: KeyboardEvent) => void>(() => undefined);
  keyRef.current = (e: KeyboardEvent) => {
    const el = e.target as HTMLElement | null;
    const a = keyAction({ key: e.key, metaKey: e.metaKey, ctrlKey: e.ctrlKey, altKey: e.altKey, tag: el?.tagName, editable: !!el?.isContentEditable });
    if (!a) return;
    if (a === 'main') {
      if (phase === 'off') return;
      e.preventDefault();
      if (el?.tagName === 'BUTTON') el.blur(); // Space must not also click the focused button
      onMain();
    } else if (a === 'retake') {
      if (rec.state !== 'recording') return;
      e.preventDefault();
      retake();
    } else if (a === 'pause') {
      if (!live) return;
      e.preventDefault();
      onPause();
    } else if (a === 'next' || a === 'prev') {
      if (!useScript || !lines.length || phase === 'off') return;
      e.preventDefault();
      goLine(tpRef.current.cur + (a === 'next' ? 1 : -1));
    }
  };
  useEffect(() => {
    const k = (e: KeyboardEvent) => keyRef.current(e);
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  const discard = async (tk: Take) => {
    try {
      await window.desk.rec.discard(tk.id);
      setTakes((x) => x.filter((y) => y.id !== tk.id));
      ui.toast(t('rec.deleted', { n: tk.n }));
    } catch (e) {
      setErr(errText(e));
    }
  };

  const using = chosenTake(takes, chosen);
  const finish = () =>
    void finishing.run(async () => {
      const tk = chosenTake(takes, chosen);
      if (!tk || !client) return;
      setErr(null);
      setStage('working');
      try {
        const series = sid ?? ep?.series;
        if (eid && shot) {
          const { job } = await client.create.ingest(tk.dir, `shot:${eid}/${shot}`, series);
          setShotDone(await waitJob<Ingested>(client.create, job));
          return;
        }
        const { job } = await client.create.ingest(tk.dir, 'assembled', series);
        const res = await waitJob<Ingested>(client.create, job);
        if (!res.assembled) throw new Error('no assembled file');
        if (!modelsRef.current) {
          setStage('models');
          while (!modelsRef.current) await new Promise((r) => setTimeout(r, 1000));
        }
        const auto = (await window.desk.getSettings()).autopilot !== false;
        const r = await client.startIntake(ask.trim() || t('rec.finishPrompt'), [res.assembled], undefined, getLang(), { mode: auto ? 'autopilot' : 'ask' });
        history.reload();
        const to = `${href({ name: 'projects' })}?sel=${encodeURIComponent(r.id)}`;
        ui.toast(t(auto ? 'rec.sent' : 'rec.sentAsk'), { action: { label: t('rec.open'), href: to }, ms: 8000 });
        location.hash = to;
      } catch (e) {
        setErr(errText(e));
      } finally {
        setStage(null);
      }
    });

  const lvl = Math.min(1, rec.level * 3);
  const meter = (
    <span className="rs-lvl" aria-hidden>
      {[0.35, 0.6, 0.95, 0.7, 0.45].map((k, i) => (
        <i key={i} style={{ height: `${Math.max(3, Math.min(16, lvl * 16 * k + 3))}px` }} />
      ))}
    </span>
  );
  const atEnd = useScript && lines.length > 0 && tp.cur === lines.length - 1 && tp.progress >= 1;
  const hint =
    phase === 'off'
      ? t('rec.needCamera')
      : blocked === 'no-script'
        ? t('rec.needScript')
        : phase === 'countdown'
          ? withKeys('rec.hintCountdown', { key: 'Space' })
          : phase === 'recording'
            ? atEnd
              ? withKeys('rec.endOfScript', { key: 'Space' })
              : withKeys(useScript && lines.length ? 'rec.hintRec' : 'rec.hintRecFree', { space: 'Space', p: 'P', r: KEY_RETAKE })
            : phase === 'paused'
              ? withKeys('rec.hintPaused', { space: 'Space', p: 'P' })
              : phase === 'stopping'
                ? t('rec.saving')
                : withKeys('rec.hintReady', { key: 'Space' });
  const mainLabel = phase === 'countdown' ? t('rec.cancel') : live ? t('rec.stop') : t('rec.start');
  const mainKey = phase === 'countdown' || live ? 'stop' : 'start';
  const title = ep ? t('create.ep.title', { n: ep.no, title: ep.title }) : t('rec.title');

  return (
    <div className={`rs ${panel ? '' : 'no-script'}`} data-testid="create-record" data-phase={phase}>
      {/* ---------------------------------------------------------------- what to say */}
      {panel ? (
        <section className="rs-script" data-testid="rec-script-panel">
          <div className="rs-head">
            <Crumbs items={[{ label: t('create.crumb'), to: { screen: 'home' } }, ...(ep ? [{ label: ep.series_name, to: { screen: 'series' as const, sid: ep.series, tab: 'bible' as const } }] : [])]} />
            <button type="button" className="rs-icon" onClick={() => setPanel(false)} aria-label={t('rec.hidePanel')} title={t('rec.hidePanel')} data-testid="rec-script-hide">
              <ChevronLeft className="ico" />
            </button>
          </div>
          <h1>{title}</h1>
          {ep && <div className="rs-sub">{t('create.rec.meta', { beats: ep.format.beats.map((b) => l10n(b.labels)).slice(0, 3).join(' → '), s: Math.round(ep.runtime) })}</div>}
          <div className="rs-seg" role="radiogroup">
            <button type="button" role="radio" aria-checked={useScript} className={useScript ? 'on' : ''} disabled={live} onClick={() => setPref('script', true)} data-testid="rec-mode-script">
              {t('rec.modeScript')}
            </button>
            <button type="button" role="radio" aria-checked={!useScript} className={!useScript ? 'on' : ''} disabled={live} onClick={() => setPref('script', false)} data-testid="rec-mode-free">
              {t('rec.modeFree')}
            </button>
          </div>
          {!useScript ? (
            <p className="rs-free">{t('rec.freeBody')}</p>
          ) : editing || !lines.length ? (
            <>
              <textarea
                value={text}
                onChange={(e) => {
                  touched.current = true;
                  setText(e.target.value);
                }}
                placeholder={t('rec.scriptPh')}
                disabled={live}
                data-testid="create-rec-script"
              />
              <div className="rs-row">
                <span className="rs-meta">{lines.length ? t('rec.scriptMeta', { n: lines.length, s: scriptSeconds(lines, WPM[prefs.speed]) }) : ''}</span>
                <button type="button" className="btn sm" disabled={!lines.length} onClick={() => setEditing(false)} data-testid="create-rec-edit">
                  {t('rec.scriptDone')}
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="rs-row">
                <span className="rs-meta">{t('rec.scriptMeta', { n: lines.length, s: scriptSeconds(lines, WPM[prefs.speed]) })}</span>
                <button type="button" className="link" disabled={live} onClick={() => setEditing(true)} data-testid="rec-script-edit">
                  {t('rec.scriptEdit')}
                </button>
              </div>
              <ol className="rs-lines">
                {lines.map((l, i) => (
                  <li key={i}>
                    <button type="button" className={`rs-ln ${i === tp.cur ? 'cur' : ''} ${live && i < tp.cur ? 'said' : ''}`} onClick={() => goLine(i)} aria-current={i === tp.cur} data-testid="rec-line">
                      <span className="k">{i + 1}</span>
                      <span className="tx">{l}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </>
          )}
          <div className="rs-tip">
            <Lightbulb className="ico" />
            <span>{useScript ? t('rec.tip', { key: KEY_RETAKE }) : t('rec.tipFree')}</span>
          </div>
        </section>
      ) : (
        <button type="button" className="rs-rail" onClick={() => setPanel(true)} aria-label={t('rec.showPanel')} title={t('rec.showPanel')} data-testid="rec-script-show">
          <ChevronRight className="ico" />
        </button>
      )}

      {/* ---------------------------------------------------------------- the stage */}
      <section className="rs-stage">
        {phase === 'off' ? (
          <div className="rs-perm" data-testid="create-rec-perm">
            <Camera className="ico lg" />
            <div className="t1">{t('rec.permTitle')}</div>
            <div className="t2">{t('rec.permBody')}</div>
            {rec.state === 'denied' ? (
              <>
                <div className="t2">{t('rec.permDenied')}</div>
                <button type="button" className="btn" onClick={() => void window.desk.rec.openPrivacy('camera')}>
                  {t('rec.permOpen')}
                </button>
              </>
            ) : (
              <button type="button" className="btn primary lg" disabled={rec.state === 'asking'} onClick={() => void rec.open()} data-testid="create-rec-allow">
                {t('rec.permAllow')}
              </button>
            )}
            {rec.error && <div className="t2">{rec.error}</div>}
          </div>
        ) : (
          <>
            <div className="rs-cam">
              <video ref={video} autoPlay muted playsInline className={prefs.mirrorPreview ? 'mirror' : ''} data-testid="create-rec-preview" />
              {useScript && lines.length > 0 && <Teleprompter lines={lines} cur={tp.cur} progress={tp.progress} size={SIZE_PX[prefs.size]} mirror={prefs.mirrorText} />}
              {(phase === 'recording' || phase === 'paused') && (
                <span className={`rs-badge ${phase}`} data-testid="create-rec-live">
                  <i />
                  {t(phase === 'paused' ? 'rec.paused' : 'rec.live', { t: fmtClock(rec.elapsed) })}
                </span>
              )}
              {phase === 'countdown' && (
                <div className="rs-count" data-testid="rec-countdown" aria-live="assertive">
                  {count}
                </div>
              )}
              {phase === 'stopping' && <div className="rs-saving">{t('rec.saving')}</div>}
            </div>

            <div className="rs-dock" data-testid="rec-dock">
              <div className="rs-side l">
                {live ? (
                  <button type="button" className="rs-ctl" disabled={phase === 'stopping'} onClick={onPause} title={`${rec.state === 'paused' ? t('rec.resume') : t('rec.pause')} (P)`} data-testid="rec-pause">
                    {rec.state === 'paused' ? <Play className="ico" /> : <Pause className="ico" />}
                    <span className="tx">{rec.state === 'paused' ? t('rec.resume') : t('rec.pause')}</span>
                  </button>
                ) : (
                  <>
                    <Pop id="cam" open={pop} onOpen={setPop} label={t('rec.camera')} icon={<Camera className="ico" />} text={t('rec.camera')} testId="rec-camera">
                      <div className="rs-ph">{t('rec.camera')}</div>
                      {rec.cameras.map((d) => (
                        <button type="button" key={d.id} className={`rs-opt ${d.id === rec.cameraId ? 'on' : ''}`} onClick={() => void rec.switchDevice('camera', d.id).then(() => setPop(null))} data-testid="rec-camera-opt">
                          {d.label}
                        </button>
                      ))}
                    </Pop>
                    <Pop id="mic" open={pop} onOpen={setPop} label={t('rec.mic')} icon={<Mic className="ico" />} text={t('rec.mic')} extra={meter} testId="rec-mic">
                      <div className="rs-ph">{t('rec.mic')}</div>
                      <div className="rs-meter" data-testid="rec-mic-level">
                        <i style={{ width: `${Math.round(lvl * 100)}%` }} />
                      </div>
                      <div className="rs-note">{t('rec.micLevel')}</div>
                      {rec.mics.map((d) => (
                        <button type="button" key={d.id} className={`rs-opt ${d.id === rec.micId ? 'on' : ''}`} onClick={() => void rec.switchDevice('mic', d.id).then(() => setPop(null))} data-testid="rec-mic-opt">
                          {d.label}
                        </button>
                      ))}
                    </Pop>
                    <Pop id="screen" open={pop} onOpen={setPop} label={t('rec.screen')} icon={<Monitor className="ico" />} text={rec.screenOn ? t('rec.screenOn') : t('rec.screen')} className={rec.screenOn ? 'lit' : ''} testId="create-rec-screen">
                      <div className="rs-ph">{t('rec.screen')}</div>
                      <div className="rs-note">{screenOk ? t('rec.screenBody') : t('rec.screenUnavailable')}</div>
                      {screenOk && (
                        <button type="button" className="btn sm" onClick={() => void rec.toggleScreen().then(() => setPop(null))} data-testid="rec-screen-toggle">
                          {rec.screenOn ? t('rec.screenStop') : t('rec.screenShare')}
                        </button>
                      )}
                    </Pop>
                  </>
                )}
              </div>

              <button
                type="button"
                className={`rs-rec ${mainKey}`}
                disabled={phase === 'stopping' || (!live && phase !== 'countdown' && !!blocked)}
                onClick={onMain}
                aria-label={mainLabel}
                title={`${mainLabel} (Space)`}
                data-testid={live ? 'create-rec-stop' : phase === 'countdown' ? 'rec-cancel' : 'create-rec-start'}
              >
                <i />
              </button>

              <div className="rs-side r">
                {live ? (
                  useScript &&
                  lines.length > 0 && (
                    <button type="button" className="rs-ctl" disabled={rec.state !== 'recording'} onClick={retake} title={`${t('rec.again')} (${KEY_RETAKE})`} data-testid="create-rec-retake">
                      <RotateCcw className="ico" />
                      <span className="tx">{t('rec.again')}</span>
                      <Kbd k={KEY_RETAKE} />
                    </button>
                  )
                ) : (
                  <Pop id="set" open={pop} onOpen={setPop} label={t('rec.settings')} icon={<Settings2 className="ico" />} text={t('rec.settingsShort')} testId="rec-settings">
                    <div className="rs-ph">{t('rec.settings')}</div>
                    <div className="rs-field">
                      <span>{t('rec.speed')}</span>
                      <div className="rs-seg sm">
                        {(['slow', 'normal', 'fast'] as const).map((s) => (
                          <button type="button" key={s} className={prefs.speed === s ? 'on' : ''} onClick={() => setPref('speed', s)} data-testid={`rec-speed-${s}`}>
                            {t(`rec.${s}`)}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="rs-field">
                      <span>{t('rec.size')}</span>
                      <div className="rs-seg sm">
                        {(['s', 'm', 'l'] as const).map((s) => (
                          <button type="button" key={s} className={prefs.size === s ? 'on' : ''} onClick={() => setPref('size', s)} data-testid={`rec-size-${s}`}>
                            {t(s === 's' ? 'rec.sizeS' : s === 'm' ? 'rec.sizeM' : 'rec.sizeL')}
                          </button>
                        ))}
                      </div>
                    </div>
                    {(
                      [
                        ['studio', 'rec.studio', <AudioLines key="i" className="ico" />],
                        ['mirrorPreview', 'rec.mirrorPreview', null],
                        ['mirrorText', 'rec.mirrorText', null],
                        ['countdown', 'rec.countdown', null],
                      ] as const
                    ).map(([k, label, icon]) => (
                      <label key={k} className="rs-toggle">
                        {icon}
                        <span className="tx">
                          {t(label)}
                          {k === 'studio' && <small>{t('rec.studioHint')}</small>}
                        </span>
                        <input type="checkbox" role="switch" checked={prefs[k]} onChange={(e) => setPref(k, e.target.checked)} data-testid={`rec-pref-${k}`} />
                      </label>
                    ))}
                  </Pop>
                )}
              </div>
            </div>
            <div className={`rs-hint ${blocked === 'no-script' ? 'warn' : ''}`} data-testid="rec-hint">
              {hint}
            </div>
          </>
        )}
      </section>

      {/* ---------------------------------------------------------------- takes + finish */}
      <section className="rs-takes" data-testid="rec-takes">
        <h2>{t('rec.takes')}</h2>
        <div className="rs-sub">{t('rec.takesSub')}</div>
        <div className="rs-list">
          {live && (
            <div className="rs-take live">
              <span className="th rec" />
              <div className="tx">
                <div className="t1">{t('rec.takeNow', { n: takeNo.current + 1 })}</div>
                <div className="t2">{useScript && lines.length ? t('rec.takePart', { n: tp.cur + 1, total: lines.length }) : t('rec.takeFree')}</div>
              </div>
            </div>
          )}
          {takes.map((tk) => {
            const on = using?.id === tk.id;
            return (
              <div key={tk.id} className={`rs-take ${on ? 'sel' : ''}`} data-testid="create-rec-take">
                <button type="button" className="pick" onClick={() => setChosen(tk.id)} aria-pressed={on} title={t('rec.use')} data-testid="rec-take-use">
                  {tk.thumb ? <img className="th" src={tk.thumb} alt="" /> : <span className="th" />}
                  <span className="tx">
                    <span className="t1">
                      {t('rec.take', { n: tk.n })} · {fmtClock(tk.secs)}
                    </span>
                    <span className="t2">
                      {tk.total ? (tk.lines >= tk.total ? t('rec.takeAll', { total: tk.total }) : t('rec.takePart', { n: tk.lines, total: tk.total })) : t('rec.takeFree')}
                      {tk.retakes > 0 && ` · ${t('rec.takeRedo', { n: tk.retakes })}`}
                    </span>
                  </span>
                  {on && <span className="using">{t('rec.using')}</span>}
                </button>
                <button type="button" className="rs-icon del" disabled={finishing.busy} onClick={() => void discard(tk)} aria-label={t('rec.delete', { n: tk.n })} title={t('rec.delete', { n: tk.n })} data-testid="rec-take-delete">
                  <Trash2 className="ico" />
                </button>
              </div>
            );
          })}
          {!takes.length && !live && <div className="rs-empty">{t('rec.takesEmpty')}</div>}
        </div>

        <div className="rs-finish">
          {shotDone ? (
            <div className="rs-done" data-testid="create-rec-result">
              <div className="t1">{t('rec.doneShot', { no: shot ?? '' })}</div>
              <div className="t2">{t('rec.doneBody', { n: shotDone.lines.length, r: shotDone.retakes, s: Math.round(shotDone.duration) })}</div>
              {eid && (
                <a className="btn" href={`#/create/e/${eid}`}>
                  {t('rec.backToEpisode')}
                </a>
              )}
            </div>
          ) : (
            <>
              {!(eid && shot) && <textarea className="rs-ask" rows={2} value={ask} onChange={(e) => setAsk(e.target.value)} placeholder={t('rec.askPh')} disabled={finishing.busy} data-testid="rec-ask" />}
              <button type="button" className="btn primary lg rs-go" disabled={!using || live || finishing.busy} onClick={finish} data-testid="rec-finish">
                {eid && shot ? t('rec.finishShot', { no: shot }) : t('rec.finish')}
              </button>
              <div className="rs-note" data-testid="rec-finish-note">
                {stage === 'working' ? t('rec.working', { n: using?.n ?? 1 }) : stage === 'models' ? t('rec.waitModels') : !using ? t('rec.finishNeedTake') : <FinishNote />}
              </div>
            </>
          )}
          {(finishing.error || err || rec.error) && (
            <div className="rs-err" data-testid="rec-error">
              {finishing.error ?? err ?? rec.error}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function FinishNote() {
  const [auto, setAuto] = useState(true);
  useEffect(() => {
    void window.desk.getSettings().then((s) => setAuto(s.autopilot !== false));
  }, []);
  return <>{t(auto ? 'rec.finishAuto' : 'rec.finishAsk')}</>;
}
