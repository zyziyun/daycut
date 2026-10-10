// 「看过程」: what the run is doing, line by line, in her words (「第 1 条 · 转写…」「AI 选了封面 · 「一次录完」」) from
// the engine's own events (desk_engine.pilot.progress_feed) - never the engine's log text, ids or paths.
import { useEffect, useState } from 'react';
import type { ProgressEvent, ProgressFeed as Feed } from '../../../shared/v02';
import type { Clip } from '../../../shared/v04';
import { fmtTime, has, t, tk, type MessageKey } from '../i18n';
import { useEngine } from '../lib/engine';
import { clipWords } from '../lib/liveStatus';
import { stepOfStage } from '../lib/pipeline';

function stepWord(stage: string | undefined): string {
  const s = stepOfStage(stage);
  return s ? t(`hub.step.${s}` as MessageKey) : t('feed.aStep');
}

function question(kind: string | undefined): string {
  return kind && has(`checkpoint.${kind}`) ? tk(`checkpoint.${kind}`) : t('hub.decisionOther');
}

/** One event in words, or null for an event that says nothing new. Pure (unit-tested). */
export function feedLine(e: ProgressEvent, clips: Pick<Clip, 'id' | 'title'>[]): string | null {
  const clip = clipWords(e.job ?? e.item, clips) ?? '';
  const pre = (s: string) => (clip ? t('feed.on', { clip, what: s }) : s);
  switch (e.event) {
    case 'run-start':
      return e.n ? t('feed.start', { n: e.n }) : t('feed.startAny');
    case 'stage-start':
      return pre(t('feed.doing', { step: stepWord(e.stage) }));
    case 'stage-retry':
      return pre(t('feed.retry', { step: stepWord(e.stage) }));
    case 'stage-fail':
      return pre(t('feed.fail', { step: stepWord(e.stage) }));
    case 'job-done':
      return clip ? t(e.state === 'failed' ? 'feed.clipFailed' : e.state === 'waiting' ? 'feed.clipWaits' : 'feed.clipDone', { clip }) : null;
    case 'checkpoint':
      return pre(t('feed.asks', { what: question(e.kind) }));
    case 'auto-answer':
      return pre(t(e.by === 'ai' ? 'feed.aiDecided' : 'feed.ruleDecided', { what: question(e.kind) }));
    case 'autopilot-blocked':
      return pre(t('feed.blocked', { what: question(e.kind) }));
    case 'pause':
      return t('feed.paused');
    case 'run-end':
    case 'project-end':
      return t('feed.roundEnd');
    default:
      return null;
  }
}

export function ProgressFeed({ item, clips, running }: { item: string; clips: Pick<Clip, 'id' | 'title'>[]; running: boolean }) {
  const { client } = useEngine();
  const [feed, setFeed] = useState<Feed | null>(null);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    const load = () =>
      client
        .progressFeed(item, 40)
        .then((f) => alive && setFeed(f))
        .catch(() => undefined);
    void load();
    if (!running) return () => void (alive = false);
    const tm = window.setInterval(load, 2500);
    return () => {
      alive = false;
      window.clearInterval(tm);
    };
  }, [client, item, running]);
  const rows = (feed?.events ?? [])
    .map((e, i) => ({ i, at: e.at, text: feedLine(e, clips), bad: e.event === 'stage-fail' || (e.event === 'job-done' && e.state === 'failed') }))
    .filter((r): r is { i: number; at: number | null | undefined; text: string; bad: boolean } => !!r.text)
    .slice(-8)
    .reverse();
  return (
    <ol className="hub-feed" data-testid="hub-feed" aria-live="polite">
      {rows.length ? (
        rows.map((r) => (
          <li key={r.i} className={r.bad ? 'bad' : ''} data-testid="hub-feed-line">
            <span className="num muted">{r.at ? fmtTime(r.at * 1000) : ''}</span>
            <span className="ln">{r.text}</span>
          </li>
        ))
      ) : (
        <li className="muted">{t('feed.none')}</li>
      )}
    </ol>
  );
}
