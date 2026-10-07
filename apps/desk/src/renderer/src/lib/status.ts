// The four status words (运行中 / 需要你 / 已完成 / 出错). Every engine state maps onto one of them or onto nothing
// (queued / planned items show no pill); the raw state stays in the details.
import type { HistoryItem } from '../../../shared/v02';
import type { Clip } from '../../../shared/v04';

export type Status4 = 'run' | 'you' | 'done' | 'error';

export const STATUS_KEY = { run: 'status.running', you: 'status.you', done: 'status.done', error: 'status.error' } as const;

export function itemStatus(i: Pick<HistoryItem, 'live' | 'status' | 'counts' | 'kind' | 'updated'> & Partial<Pick<HistoryItem, 'failure' | 'pilot'>>, now = Date.now() / 1000): Status4 | null {
  if (i.failure) return 'error';
  const l = i.live;
  if (l) {
    if (l.state === 'running') return 'run';
    if (l.state === 'waiting') return 'you';
    if (l.state === 'failed') return 'error';
    if (l.state === 'interrupted') return now - (l.heartbeat ?? 0) < 86400 ? 'error' : null;
  }
  if (i.pilot) return 'run'; // the pilot the desk started is going (before its first heartbeat)
  const c = i.counts;
  switch (i.status) {
    case 'failed':
      return 'error';
    case 'unreadable':
      return 'error';
    case 'delivered':
    case 'packaged':
      return 'done';
    case 'done':
      if (i.kind !== 'work' && c && c.red > 0 && c.approved < c.total) return 'you';
      if (i.kind !== 'work' && c && c.done > c.approved && c.approved < c.total && i.kind === 'batch') return 'you';
      return 'done';
    case 'in-progress':
      if (c && c.failed > 0) return 'error';
      if (i.kind === 'work') return now - (i.updated ?? 0) < 7200 ? 'run' : null;
      return 'you';
    case 'planned':
      return null;
    default:
      return null;
  }
}

export function clipStatus(c: Pick<Clip, 'state' | 'qc' | 'review'>): Status4 | null {
  if (c.state === 'running') return 'run';
  if (c.state === 'failed') return 'error';
  if (c.state === 'queued' || c.state === 'planned') return null;
  if (c.review === 'reject' || c.review === 'rejected' || c.state === 'needs-replan') return 'you';
  if (c.qc === 'red' && !(c.review === 'approve' || c.review === 'approved')) return 'you';
  return 'done';
}

/** Never 「已完成」 while the Inbox holds a decision for the project (the tile, the project page and the filter agree). */
export function withInbox(s: Status4 | null, hasDecision: boolean): Status4 | null {
  return s === 'done' && hasDecision ? 'you' : s;
}

/** Projects filter buckets; `hasDecision`: the Inbox has an open (non-failure) item for this project. */
export function bucket(i: HistoryItem, hasDecision = false): 'running' | 'you' | 'done' | 'failed' | 'other' {
  const s = withInbox(itemStatus(i), hasDecision);
  return s === 'run' ? 'running' : s === 'you' ? 'you' : s === 'done' ? 'done' : s === 'error' ? 'failed' : 'other';
}
