// Problems the app noticed (main process exceptions, a renderer that died or threw, the engine sidecar exiting,
// failed jobs reported by the UI) -> a small redacted log (<userData>/logs/problems.json, last 20) the UI offers
// to report. Reports are manual by default: the UI shows the redacted text, she reviews it and opens a prefilled
// GitHub issue herself. "Send crash reports automatically" (default OFF) only does anything when a sender is
// installed (setCrashSender: the opt-in usage-stats backend); without one there is no automatic path at all.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { redactClip } from '../shared/redact';
import { problemReport, type Problem, type ProblemKind, type SupportEnv } from '../shared/support';

const MAX = 20;
const SAME_WINDOW_MS = 60_000;

export type CrashSender = (report: string, p: Problem) => Promise<boolean>;
let sender: CrashSender | null = null;

/** The usage-stats backend (feat/usage-stats) installs its endpoint here; null = manual reports only. */
export function setCrashSender(fn: CrashSender | null) {
  sender = fn;
}

export function crashSenderAvailable(): boolean {
  return sender !== null;
}

export class ProblemLog {
  private file: string;
  private items: (Problem & { seen?: boolean; sent?: boolean })[] = [];

  constructor(
    dir: string,
    private onNew: (p: Problem) => void = () => undefined,
    private env: () => SupportEnv | null = () => null,
    private autoSend: () => boolean = () => false,
  ) {
    this.file = path.join(dir, 'problems.json');
    try {
      const v = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (Array.isArray(v)) this.items = v.filter((x) => x && typeof x.id === 'string').slice(-MAX);
    } catch {
      this.items = [];
    }
  }

  private save() {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.writeFileSync(this.file, JSON.stringify(this.items.slice(-MAX), null, 1));
    } catch {
      /* the log must never throw */
    }
  }

  /** Record (redacted on the way in; the same message within a minute counts once). Never throws. */
  record(kind: ProblemKind, code: string, message: string, stack?: string): Problem | null {
    try {
      const home = os.homedir();
      const msg = redactClip(message || code, 600, home);
      const now = Date.now();
      const dup = this.items.find((x) => x.kind === kind && x.message === msg && now - x.at < SAME_WINDOW_MS);
      if (dup) return null;
      const p: Problem = {
        id: `${now.toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        at: now,
        kind,
        code: redactClip(String(code || 'unknown'), 80, home),
        message: msg,
        ...(stack ? { stack: redactClip(stack, 4000, home) } : {}),
      };
      this.items.push(p);
      this.items = this.items.slice(-MAX);
      this.save();
      this.onNew(p);
      void this.maybeSend(p);
      return p;
    } catch {
      return null;
    }
  }

  private async maybeSend(p: Problem) {
    const env = this.env();
    if (!sender || !env || !this.autoSend()) return;
    try {
      const ok = await sender(problemReport(p, env), p);
      if (ok) {
        const x = this.items.find((y) => y.id === p.id);
        if (x) x.sent = true;
        this.save();
      }
    } catch {
      /* automatic reports are best effort */
    }
  }

  /** Not yet dismissed, newest first. */
  list(): (Problem & { sent?: boolean })[] {
    return this.items.filter((x) => !x.seen).reverse().map(({ seen: _s, ...p }) => p);
  }

  /** Everything recorded (for "Earlier problems" in a report), newest first. */
  recent(): Problem[] {
    return [...this.items].reverse().map(({ seen: _s, sent: _t, ...p }) => p);
  }

  dismiss(id?: string) {
    for (const x of this.items) if (!id || x.id === id) x.seen = true;
    this.save();
  }
}
