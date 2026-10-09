// One request's plan job (POST /api/intake ...): read and followed while it runs (polled + the engine's intake
// events), revised in words, tried again after a failure. Used by the control room's plan card.
import { useCallback, useEffect, useState } from 'react';
import type { IntakeJob } from '../../../shared/v04';
import { getLang } from '../i18n';
import { useEngine } from './engine';

export function useIntakeJob(id: string | null) {
  const { client, subscribe } = useEngine();
  const [job, setJob] = useState<IntakeJob | null>(null);
  const [n, setN] = useState(0);
  const again = useCallback(() => setN((x) => x + 1), []);
  useEffect(() => {
    if (!client || !id) {
      setJob(null);
      return;
    }
    let alive = true;
    let tm: ReturnType<typeof setTimeout>;
    const tick = () =>
      client
        .intake(id)
        .then((j) => {
          if (!alive) return;
          setJob(j);
          if (j.state === 'running') tm = setTimeout(tick, 700);
        })
        .catch(() => alive && setJob(null));
    void tick();
    return () => {
      alive = false;
      clearTimeout(tm);
    };
  }, [client, id, n]);
  useEffect(() => subscribe((e) => void (e.type === 'intake' && e.id === id && again())), [subscribe, id, again]);
  const revise = useCallback(
    async (text: string) => {
      if (!client || !id) return;
      await client.reviseIntake(id, text, getLang());
      setJob((j) => (j ? { ...j, state: 'running', step: 'revise' } : j));
      again();
    },
    [client, id, again],
  );
  const retry = useCallback(async () => {
    if (!client || !id) return;
    await client.retryIntake(id);
    setJob((j) => (j ? { ...j, state: 'running', error: null, error_code: null } : j));
    again();
  }, [client, id, again]);
  return { job, revise, retry, reload: again };
}
