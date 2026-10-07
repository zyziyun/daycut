// Home's three ideas from her own work (pure, unit-tested): the next episode of a series, a project with clips left,
// her latest request - topped up with the generic starting points.
import type { HistoryItem } from '../../../shared/v02';
import { t, type MessageKey } from '../i18n';

export const IDEAS: [MessageKey, MessageKey][] = [
  ['home.idea1', 'home.idea1Prompt'],
  ['home.idea2', 'home.idea2Prompt'],
  ['home.idea3', 'home.idea3Prompt'],
  ['home.idea4', 'home.idea4Prompt'],
  ['home.idea5', 'home.idea5Prompt'],
  ['home.idea6', 'home.idea6Prompt'],
];

export interface HomeIdea {
  id: string;
  label: string;
  sub?: string;
  prompt: string;
  kind: 'series' | 'finish' | 'recent' | 'idea';
  thumb?: string | null;
}

export function homeIdeas(items: HistoryItem[], recent: { prompt: string }[] = [], n = 3): HomeIdea[] {
  const out: HomeIdea[] = [];
  const done = items.filter((i) => i.live?.state !== 'running');
  const series = done.find((i) => i.series || i.type === 'aigc');
  if (series) {
    const ep = (series.counts?.total ?? 0) + 1;
    out.push({ id: `s-${series.id}`, kind: 'series', label: t('home.sug.next', { name: series.series ?? series.name }), sub: t('home.sug.episode', { n: ep }), prompt: t('home.sug.nextPrompt', { name: series.series ?? series.name, n: ep }), thumb: series.thumb });
  }
  const unfinished = done.find((i) => i !== series && i.counts && i.counts.total > 0 && i.counts.total - Math.max(i.counts.done, i.counts.approved) > 0 && i.counts.total - Math.max(i.counts.done, i.counts.approved) < i.counts.total);
  if (unfinished) {
    const left = unfinished.counts.total - Math.max(unfinished.counts.done, unfinished.counts.approved);
    out.push({ id: `f-${unfinished.id}`, kind: 'finish', label: t('home.sug.finish', { name: unfinished.name }), sub: t('home.sug.left', { n: left }), prompt: t('home.sug.finishPrompt', { name: unfinished.name }), thumb: unfinished.thumb });
  }
  if (recent[0]?.prompt) out.push({ id: 'r-0', kind: 'recent', label: recent[0].prompt, sub: t('home.sug.again'), prompt: recent[0].prompt });
  for (const [k, pk] of IDEAS) {
    if (out.length >= n) break;
    out.push({ id: k, kind: 'idea', label: t(k), prompt: t(pk) });
  }
  return out.slice(0, n);
}

