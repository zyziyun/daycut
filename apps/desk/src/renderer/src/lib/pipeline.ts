// The control room's model (ux/autopilot A1): where each project is in the pipeline
// plan → transcribe → cut → captions → render → check → copy → ready → out, and which group of the list it sits in
// (needs you / running / ready / out / earlier). Pure functions: the hub, Home and the tests share them.
import type { HistoryItem, LiveStatus } from '../../../shared/v02';
import type { AutopilotDecision, CalendarPost, OpenRequest } from '../../../shared/v04';
import { itemStatus } from './status';

export const STEPS = ['plan', 'transcribe', 'cut', 'captions', 'render', 'check', 'copy', 'ready', 'out'] as const;
export type StepId = (typeof STEPS)[number];

/** An engine stage name (a recipe stage, a plan progress stage or a live-status label) -> the pipeline step. */
const STAGE_RX: [StepId, RegExp][] = [
  ['plan', /^(scan|probe|faces|model|write|plan|intake|segment|segments|select|pick|outline|script|storyboard|analy[sz]e)|选段|方案|读素材/i],
  ['transcribe', /^(asr|extract|listen|transcri|whisper|align|diar|glossary)|转写|听/i],
  ['cut', /^(cleanup|cut|trim|filler|apply|edit|edl|speed|hook|take|split|clip|tight|geometry|pickup)|去停顿|剪/i],
  ['captions', /^(subs?|caption|proofread|keyword|notes|bubble|panel)|字幕/i],
  ['render', /^(compose|render|reframe|export|encode|cover|retouch|music|mix|fx|effect|layout|overlay|hf|frames?)|导出|渲染|封面/i],
  ['check', /^(qc|check|verify|firstpass|review|preview|publish|cp_publish)|检查|试看|审/i],
  ['copy', /^(copy|post|caption-copy|title)|文案/i],
];

export function stepOfStage(stage: string | null | undefined): StepId | null {
  // the batch runner writes "s003:export" (the clip it is on, then the stage), several joined with ", "
  const parts = (stage ?? '').split(',').map((x) => x.trim().replace(/^[^:\s]+:(?=[a-z])/i, '').replace(/^cp_/, '')).filter(Boolean);
  let best: StepId | null = null;
  for (const s of parts) {
    const id = STAGE_RX.find(([, rx]) => rx.test(s))?.[0] ?? null;
    if (id && (best == null || STEPS.indexOf(id) < STEPS.indexOf(best))) best = id; // every clip has reached it
  }
  return best;
}

/** Where a live run is: the least advanced of the stages running now (one per clip), else its stage line. */
export function stepOfLive(live: Pick<LiveStatus, 'stage' | 'stages'> | null | undefined): StepId | null {
  const st = live?.stages?.length ? live.stages.map((x) => x.stage).join(', ') : live?.stage;
  return stepOfStage(st);
}

export type HubState = 'planning' | 'plan-ready' | 'queued' | 'run' | 'you' | 'failed' | 'ready' | 'scheduled' | 'out' | 'idle';

export interface Pipeline {
  state: HubState;
  /** the step it is at (the last one reached when finished) */
  current: StepId;
  /** 0..1 when known */
  progress: number | null;
  /** seconds left when the engine says */
  eta: number | null;
}

/** Posts of one project: how many are scheduled / out. */
export function postsOf(posts: CalendarPost[], item: string): { scheduled: number; posted: number; total: number } {
  const mine = posts.filter((p) => p.item === item);
  const posted = mine.filter((p) => p.state === 'posted').length;
  return { scheduled: mine.length - posted, posted, total: mine.length };
}

export function requestPipeline(r: OpenRequest): Pipeline {
  if (r.state === 'error') return { state: 'failed', current: 'plan', progress: null, eta: null };
  if (r.state === 'needs') return { state: 'you', current: 'plan', progress: null, eta: null }; // waits for her files / pages
  if (r.state === 'done') return { state: r.mode === 'ask' ? 'plan-ready' : 'planning', current: 'plan', progress: 1, eta: null };
  const p = r.progress;
  const frac = p?.total_s ? Math.min(1, (p.done_s ?? 0) / p.total_s) : null;
  return { state: 'planning', current: p?.stage === 'transcribe' ? 'transcribe' : 'plan', progress: frac, eta: null };
}

/** A project's place in the pipeline. ``hasDecision``: the Inbox holds a question for it. */
export function itemPipeline(i: HistoryItem, posts: CalendarPost[] = [], hasDecision = false): Pipeline {
  const s = itemStatus(i);
  const live = i.live;
  const progress = live?.progress ?? null;
  const eta = live?.eta ?? null;
  const at = stepOfLive(live);
  if (i.queued) return { state: 'queued', current: 'plan', progress: null, eta: null };
  if (s === 'error') return { state: 'failed', current: at ?? stepOfStage(i.failure?.stage) ?? 'plan', progress, eta: null };
  // something waits for her (an Inbox question, a run parked at one): she is what it waits for - 「需要你」, not 「进行中」
  if (s === 'you' || hasDecision || live?.needs_you) return { state: 'you', current: at ?? 'check', progress: s === 'run' ? progress : null, eta: null };
  if (s === 'run') return { state: 'run', current: at ?? 'plan', progress, eta };
  const p = postsOf(posts, i.id);
  if (p.total && p.scheduled === 0) return { state: 'out', current: 'out', progress: 1, eta: null };
  if (p.total) return { state: 'scheduled', current: 'out', progress: 1, eta: null };
  if (s === 'done') return { state: 'ready', current: 'ready', progress: 1, eta: null };
  return { state: 'idle', current: at ?? 'plan', progress, eta };
}

/** Steps before ``current`` are done; when the project is ready / out, every step up to it is. */
export function stepState(step: StepId, p: Pipeline): 'done' | 'current' | 'todo' {
  const k = STEPS.indexOf(step);
  const c = STEPS.indexOf(p.current);
  if (k < c) return 'done';
  if (k === c) return p.state === 'ready' || p.state === 'out' || p.state === 'scheduled' ? 'done' : 'current';
  return 'todo';
}

export type GroupId = 'you' | 'run' | 'ready' | 'out' | 'earlier';
export type HubRow = { kind: 'request'; id: string; r: OpenRequest; p: Pipeline; at: number } | { kind: 'project'; id: string; i: HistoryItem; p: Pipeline; at: number };

const RECENT_S = 14 * 86400;

/** The list of the control room, grouped by what each one needs: needs you, running (planning / queued / making),
 * ready, out (scheduled or posted), earlier (finished more than 14 days ago). Newest first inside a group. */
export function hubGroups(items: HistoryItem[], requests: OpenRequest[], posts: CalendarPost[], deciding: Set<string>, now = Date.now() / 1000): Record<GroupId, HubRow[]> {
  const out: Record<GroupId, HubRow[]> = { you: [], run: [], ready: [], out: [], earlier: [] };
  for (const r of requests) {
    const p = requestPipeline(r);
    const row: HubRow = { kind: 'request', id: r.id, r, p, at: r.started ?? now };
    out[p.state === 'failed' || p.state === 'plan-ready' || p.state === 'you' ? 'you' : 'run'].push(row);
  }
  for (const i of items) {
    const p = itemPipeline(i, posts, deciding.has(i.id));
    const row: HubRow = { kind: 'project', id: i.id, i, p, at: i.updated ?? i.created ?? 0 };
    const g: GroupId =
      p.state === 'you' || p.state === 'failed'
        ? 'you'
        : p.state === 'run' || p.state === 'queued' || p.state === 'planning'
          ? 'run'
          : now - row.at > RECENT_S
            ? 'earlier'
            : p.state === 'out' || p.state === 'scheduled'
              ? 'out'
              : 'ready';
    out[g].push(row);
  }
  for (const k of Object.keys(out) as GroupId[]) out[k].sort((a, b) => b.at - a.at);
  // running: making first, then queued in line order
  out.run.sort((a, b) => rank(a) - rank(b) || b.at - a.at);
  return out;
}

function rank(r: HubRow): number {
  if (r.kind === 'project' && r.p.state === 'queued') return 2 + (r.i.queued ?? 0) / 1000;
  return r.p.state === 'planning' ? 1 : 0;
}

/** A decision in plain words: the i18n key + its params (the hub words it; the engine's free-text reason is shown
 * under it as written). */
export function decisionWords(d: AutopilotDecision): { key: string; params: Record<string, string | number> } {
  const p = (d.params ?? {}) as Record<string, unknown>;
  const n = (k: string) => (typeof p[k] === 'number' ? (p[k] as number) : 0);
  switch (d.kind) {
    case 'filler-confirm':
      return { key: 'ap.d.filler', params: { cut: n('cut'), kept: n('kept') } };
    case 'hook-pick':
      return n('pick') < 0 || p.pick === undefined ? { key: 'ap.d.hookNone', params: {} } : { key: 'ap.d.hook', params: { n: n('pick') + 1 } };
    case 'cover-pick':
      return { key: 'ap.d.cover', params: { n: n('pick') + 1 } };
    case 'publish':
    case 'review':
      return { key: 'ap.d.approved', params: {} };
    case 'budget-approval':
      return { key: 'ap.d.budget', params: { n: n('total') } };
    case 'segment-approval':
      return { key: 'ap.d.segments', params: {} };
    case 'keywords':
      return { key: 'ap.d.keywords', params: {} };
    case 'author':
    case 'script-lock':
    case 'storyboard-approval':
    case 'media-selection': {
      // the AI's draft of a step she would have written (vstudio.project.drafts); keep spans say how much stays
      const m = (s: number) => `${Math.floor(Math.round(s) / 60)}:${String(Math.round(s) % 60).padStart(2, '0')}`;
      if (String(p.summary ?? '').startsWith('draft.keep') && typeof p.kept === 'number' && typeof p.total === 'number')
        return { key: 'ap.d.keep', params: { kept: m(n('kept')), total: m(n('total')) } };
      return { key: 'ap.d.drafted', params: {} };
    }
    default:
      return { key: 'ap.d.default', params: {} };
  }
}
