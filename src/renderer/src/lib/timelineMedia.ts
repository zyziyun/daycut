// The editor's timeline media: the filmstrip sprite + audio peaks of the clip's file (made once by the engine,
// cached there; kept here per session too), and 「听一遍这条片子」 (transcription) state with its events.
import { useCallback, useEffect, useState } from 'react';
import type { EngineClient } from '../../../shared/engineClient';
import type { StripInfo, TranscribeState } from '../../../shared/timeline';
import type { StreamEvent } from '../../../shared/types';

const cache = new Map<string, StripInfo>();

/** null while it is being made (skeleton), then the strip; `failed` when the engine could not make one. */
export function useStrip(client: EngineClient | null, item: string, clip: string, file: string | null): { strip: StripInfo | null; failed: boolean } {
  const key = `${item}\0${clip}\0${file ?? ''}`;
  const [st, setSt] = useState<{ key: string; strip: StripInfo | null; failed: boolean }>(() => ({ key, strip: cache.get(key) ?? null, failed: false }));
  useEffect(() => {
    if (!client || !file) return;
    const hit = cache.get(key);
    if (hit) {
      setSt({ key, strip: hit, failed: false });
      return;
    }
    setSt({ key, strip: null, failed: false });
    const ac = new AbortController();
    client
      .outputStrip(item, clip, ac.signal)
      .then((s) => {
        cache.set(key, s);
        setSt({ key, strip: s, failed: false });
      })
      .catch(() => !ac.signal.aborted && setSt({ key, strip: null, failed: true }));
    return () => ac.abort();
  }, [client, item, clip, file, key]);
  return st.key === key ? { strip: st.strip, failed: st.failed } : { strip: null, failed: false };
}

/** 「听一遍」: start it, follow output-transcribe events, call onDone (reload the document) when words exist. */
export function useTranscribe(
  client: EngineClient | null,
  subscribe: (fn: (e: StreamEvent) => void) => () => void,
  item: string,
  clip: string,
  onDone: () => void,
): { state: TranscribeState; start: () => void } {
  const [state, setState] = useState<TranscribeState>({ state: 'idle' });
  useEffect(() => {
    setState({ state: 'idle' });
    if (!client) return;
    let alive = true;
    client
      .transcribeState(item, clip)
      .then((s) => alive && s.state === 'running' && setState(s))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client, item, clip]);
  useEffect(
    () =>
      subscribe((e) => {
        if (e.type !== 'output-transcribe' || e.item !== item || e.clip !== clip) return;
        setState({ state: e.state, error: e.error, words: e.words });
        if (e.state === 'done') onDone();
      }),
    [subscribe, item, clip, onDone],
  );
  const start = useCallback(() => {
    if (!client) return;
    setState({ state: 'running' });
    client
      .transcribeOutput(item, clip)
      .then((s) => setState((cur) => (cur.state === 'running' ? s : cur)))
      .catch((e: Error) => setState({ state: 'failed', error: e.message }));
  }, [client, item, clip]);
  return { state, start };
}
