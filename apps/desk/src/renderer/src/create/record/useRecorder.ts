// Camera + mic (+ screen) recording with separate tracks, 1 s chunks streamed to main (crash-safe), a level meter
// and line / retake marks. Studio sound is applied at ingest, not live (raw, no browser noise suppression).
import { useCallback, useEffect, useRef, useState } from 'react';

export type RecTrack = 'camera' | 'mic' | 'screen';
export type RecState = 'idle' | 'asking' | 'denied' | 'ready' | 'recording' | 'stopping' | 'error';

const VIDEO_TYPES = ['video/webm;codecs=vp9', 'video/webm;codecs=h264', 'video/webm', 'video/mp4;codecs=avc1'];
const AUDIO_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];

export function pickMime(kinds: string[], supported: (t: string) => boolean = (t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)): string | undefined {
  return kinds.find((k) => supported(k));
}

interface Session {
  id: string;
  dir: string;
  t0: number;
  recorders: MediaRecorder[];
  chains: Promise<unknown>[];
}

export function useRecorder() {
  const [state, setState] = useState<RecState>('idle');
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const sess = useRef<Session | null>(null);
  const screen = useRef<MediaStream | null>(null);
  const raf = useRef<number | null>(null);
  const actx = useRef<AudioContext | null>(null);

  const stopStream = useCallback((s: MediaStream | null) => s?.getTracks().forEach((tr) => tr.stop()), []);

  useEffect(
    () => () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      void actx.current?.close().catch(() => undefined);
      stopStream(screen.current);
    },
    [stopStream],
  );
  useEffect(() => () => stopStream(stream), [stream, stopStream]);

  /** Ask (macOS) and open the camera + mic. */
  const open = useCallback(async () => {
    setState('asking');
    setError(null);
    try {
      const st = await window.desk.rec.status();
      if (st.camera !== 'granted' || st.microphone !== 'granted') {
        const cam = st.camera === 'granted' || (await window.desk.rec.ask('camera'));
        const mic = st.microphone === 'granted' || (await window.desk.rec.ask('microphone'));
        if (!cam || !mic) {
          setState('denied');
          return;
        }
      }
      const s = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1080 }, height: { ideal: 1920 }, frameRate: { ideal: 30 } },
        audio: { noiseSuppression: false, echoCancellation: false, autoGainControl: false },
      });
      setStream(s);
      const ctx = new AudioContext();
      actx.current = ctx;
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(new MediaStream(s.getAudioTracks())).connect(an);
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(peak / 128);
        raf.current = requestAnimationFrame(tick);
      };
      tick();
      setState('ready');
    } catch (e) {
      const name = (e as Error).name;
      setState(name === 'NotAllowedError' ? 'denied' : 'error');
      setError((e as Error).message);
    }
  }, []);

  const toggleScreen = useCallback(async () => {
    if (screen.current) {
      stopStream(screen.current);
      screen.current = null;
      return false;
    }
    try {
      screen.current = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      return true;
    } catch {
      screen.current = null;
      return false;
    }
  }, [stopStream]);

  const start = useCallback(
    async (req: { slug: string; title?: string; script: string[]; series?: string; episode?: string; shot?: string }) => {
      if (!stream) return;
      const vMime = pickMime(VIDEO_TYPES);
      const aMime = pickMime(AUDIO_TYPES);
      const tracks: RecTrack[] = ['camera', 'mic', ...(screen.current ? (['screen'] as RecTrack[]) : [])];
      const { sessionId, dir } = await window.desk.rec.begin({ ...req, tracks, mime: { camera: vMime ?? '', mic: aMime ?? '', ...(screen.current ? { screen: vMime ?? '' } : {}) } });
      const s: Session = { id: sessionId, dir, t0: performance.now(), recorders: [], chains: [] };
      const add = (track: RecTrack, ms: MediaStream, mime?: string) => {
        const r = new MediaRecorder(ms, mime ? { mimeType: mime } : undefined);
        let seq = 0;
        let chain: Promise<unknown> = Promise.resolve();
        const i = s.chains.length;
        s.chains.push(chain);
        r.ondataavailable = (ev) => {
          if (!ev.data || !ev.data.size) return;
          const n = seq++;
          const startMs = n === 0 ? Date.now() - 1000 : undefined;
          chain = chain.then(async () => {
            const data = new Uint8Array(await ev.data.arrayBuffer());
            await window.desk.rec.chunk(startMs === undefined ? { sessionId, track, seq: n, data } : { sessionId, track, seq: n, data, startMs });
          });
          s.chains[i] = chain.catch((e) => setError(String((e as Error).message)));
        };
        r.start(1000);
        s.recorders.push(r);
      };
      add('camera', new MediaStream(stream.getVideoTracks()), vMime);
      add('mic', new MediaStream(stream.getAudioTracks()), aMime);
      if (screen.current) add('screen', screen.current, vMime);
      sess.current = s;
      setElapsed(0);
      setState('recording');
    },
    [stream],
  );

  useEffect(() => {
    if (state !== 'recording') return;
    const tm = window.setInterval(() => sess.current && setElapsed((performance.now() - sess.current.t0) / 1000), 250);
    return () => window.clearInterval(tm);
  }, [state]);

  const mark = useCallback(async (kind: 'line' | 'retake', line: number) => {
    const s = sess.current;
    if (!s) return;
    await window.desk.rec.mark({ sessionId: s.id, t: Math.max(0, (performance.now() - s.t0) / 1000), kind, line });
  }, []);

  /** Stop -> every chunk written -> main closes the session. -> {dir} */
  const stop = useCallback(async () => {
    const s = sess.current;
    if (!s) return null;
    setState('stopping');
    await Promise.all(
      s.recorders.map(
        (r) =>
          new Promise<void>((res) => {
            if (r.state === 'inactive') return res();
            r.addEventListener('stop', () => res(), { once: true });
            r.stop();
          }),
      ),
    );
    await new Promise((r) => setTimeout(r, 50));
    await Promise.all(s.chains);
    const out = await window.desk.rec.end(s.id);
    sess.current = null;
    setState('ready');
    return out;
  }, []);

  return { state, stream, level, error, elapsed, open, start, stop, mark, toggleScreen, screenOn: () => !!screen.current };
}
