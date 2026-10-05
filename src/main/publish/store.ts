// Confirmed package codes and the "posted" log (JSON / JSONL under userData/publish). No credentials, no
// cookies - only what the creator confirmed and what she marked as posted.
import fs from 'node:fs';
import path from 'node:path';
import type { Confirmation } from '../../shared/publish/gating';

export interface PostedEntry {
  batchId: string;
  code: string;
  job: string;
  platform: string;
  adapterId: string;
  account: string;
  url: string | null;
  at: string;
}

export class PublishStore {
  private confFile: string;
  private postedFile: string;

  constructor(dir: string) {
    fs.mkdirSync(dir, { recursive: true });
    this.confFile = path.join(dir, 'confirmations.json');
    this.postedFile = path.join(dir, 'posted.jsonl');
  }

  confirmations(batchId?: string): Confirmation[] {
    let all: Confirmation[];
    try {
      all = JSON.parse(fs.readFileSync(this.confFile, 'utf8'));
    } catch {
      all = [];
    }
    return batchId ? all.filter((c) => c.batchId === batchId) : all;
  }

  confirm(c: Omit<Confirmation, 'confirmedAt'>): Confirmation {
    const entry: Confirmation = { ...c, confirmedAt: new Date().toISOString() };
    const all = this.confirmations().filter((x) => !(x.batchId === c.batchId && x.code === c.code));
    all.push(entry);
    const tmp = this.confFile + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(all, null, 1));
    fs.renameSync(tmp, this.confFile);
    return entry;
  }

  markPosted(e: Omit<PostedEntry, 'at'>): PostedEntry {
    const entry: PostedEntry = { ...e, at: new Date().toISOString() };
    fs.appendFileSync(this.postedFile, JSON.stringify(entry) + '\n');
    return entry;
  }

  posted(batchId?: string): PostedEntry[] {
    let lines: string[];
    try {
      lines = fs.readFileSync(this.postedFile, 'utf8').split('\n');
    } catch {
      return [];
    }
    const out: PostedEntry[] = [];
    for (const l of lines) {
      if (!l.trim()) continue;
      try {
        const e = JSON.parse(l) as PostedEntry;
        if (!batchId || e.batchId === batchId) out.push(e);
      } catch {
        /* skip */
      }
    }
    return out;
  }
}
