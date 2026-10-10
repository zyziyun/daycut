// Feedback + problem reports: what the text says and where it opens. Reelfold never sends either by itself: it opens
// a prefilled GitHub page (a Discussion for ideas / questions, an Issue with the bug template for problems) in the
// browser, and she posts it there (no GitHub token is stored). The one exception is opt-in: "Send crash reports
// automatically" (off by default) — only when a crash-report endpoint exists (feat/usage-stats); see main/problems.ts.
import { redact, redactClip } from './redact';

export const REPO = 'https://github.com/zyziyun/reelfold';
/** The Discussions category for feedback. The repo has no "Feedback" category yet: General until one is created. */
export const FEEDBACK_CATEGORY = 'general';
/** GitHub rejects very long prefill URLs; stay well below its ~8 KB limit. */
export const MAX_URL = 7000;

export type ProblemKind = 'main' | 'renderer' | 'sidecar' | 'job';

export interface Problem {
  id: string;
  at: number;
  kind: ProblemKind;
  /** an error code or reason (engine failure code, exit code, crash reason) */
  code: string;
  /** one line, already redacted */
  message: string;
  /** already redacted */
  stack?: string;
}

export interface SupportEnv {
  app: string;
  electron: string;
  chrome: string;
  node: string;
  os: string;
  arch: string;
  packaged: boolean;
  lang: string;
  engine?: string | null;
  /** the user's home folder: redaction only, never printed */
  home?: string | null;
  /** an endpoint for automatic crash reports exists (usage-stats backend) */
  autoAvailable?: boolean;
  /** her setting: send crash reports automatically (default off) */
  autoSend?: boolean;
}

export function envLines(env: SupportEnv): string[] {
  return [
    `Reelfold ${env.app}${env.packaged ? '' : ' (dev)'} · ${env.os} ${env.arch}`,
    `Electron ${env.electron} · Chrome ${env.chrome} · Node ${env.node}`,
    `UI language ${env.lang} · engine ${env.engine ?? '-'}`,
  ];
}

/** The redacted text of one problem report: exactly what she reviews, and what goes into the issue's Logs field. */
export function problemReport(p: Pick<Problem, 'kind' | 'code' | 'message' | 'stack'>, env: SupportEnv, recent: Problem[] = []): string {
  const h = env.home;
  const out = [
    ...envLines(env),
    '',
    `Problem: ${p.kind} · ${redact(p.code, h)}`,
    `Message: ${redactClip(p.message, 400, h)}`,
  ];
  if (p.stack) out.push('', 'Stack:', redactClip(p.stack, 2500, h));
  const others = recent.filter((r) => r.message !== p.message).slice(0, 5);
  if (others.length) {
    out.push('', 'Earlier problems:');
    for (const r of others) out.push(`- ${new Date(r.at).toISOString().slice(0, 16)} ${r.kind} · ${redact(r.code, h)} · ${redactClip(r.message, 160, h)}`);
  }
  return out.join('\n');
}

/** Diagnostics a feedback post may carry (opt-in): versions + recent error codes, nothing else. */
export function diagnostics(env: SupportEnv, recent: Problem[] = []): string {
  const out = [...envLines(env)];
  if (recent.length) {
    out.push('Recent problems:');
    for (const r of recent.slice(0, 5)) out.push(`- ${r.kind} · ${redact(r.code, env.home)} · ${redactClip(r.message, 160, env.home)}`);
  }
  return out.join('\n');
}

function q(params: Record<string, string | undefined>): string {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v!)}`)
    .join('&');
}

/** Shorten the longest field until the URL fits. */
function fit(build: (cut: number) => string): string {
  let cut = 6000;
  let url = build(cut);
  while (url.length > MAX_URL && cut > 200) {
    cut = Math.floor(cut * 0.8);
    url = build(cut);
  }
  return url;
}

const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

/** A bug report on the bug_report.yml issue form, prefilled field by field (ids from .github/ISSUE_TEMPLATE). */
export function issueUrl(f: { title: string; got: string; asked?: string; logs?: string; env: SupportEnv }): string {
  return fit(
    (cut) =>
      `${REPO}/issues/new?${q({
        template: 'bug_report.yml',
        title: clip(f.title, 120),
        surface: 'Desktop app (Reelfold)',
        asked: f.asked ? clip(f.asked, 600) : undefined,
        got: clip(f.got, Math.min(cut, 2000)),
        version: f.env.app,
        env: `${f.env.os} ${f.env.arch}`,
        logs: f.logs ? clip(f.logs, cut) : undefined,
      })}`,
  );
}

/** An idea / question as a new Discussion (category FEEDBACK_CATEGORY), title + body prefilled. */
export function discussionUrl(f: { title: string; body: string }): string {
  return fit((cut) => `${REPO}/discussions/new?${q({ category: FEEDBACK_CATEGORY, title: clip(f.title, 120), body: clip(f.body, cut) })}`);
}

/** The body of a feedback post: her words, the optional e-mail, the optional diagnostics. */
export function feedbackBody(f: { what: string; email?: string; diag?: string | null; kind: 'idea' | 'bug' }): string {
  const parts = [f.what.trim()];
  if (f.email?.trim()) parts.push('', `Reply to: ${f.email.trim()}`);
  if (f.diag) parts.push('', '<details><summary>Diagnostics</summary>', '', '```', f.diag, '```', '</details>');
  parts.push('', `_Sent from Reelfold › Send feedback (${f.kind === 'bug' ? 'something broke' : 'idea or question'})._`);
  return parts.join('\n');
}

/** A title from the first line of what she wrote. */
export function titleOf(what: string, fallback: string): string {
  const line = what.trim().split('\n')[0].trim();
  return line ? clip(line, 80) : fallback;
}

/** E-mail shape check for the optional field (no validation beyond that: it is only ever shown to her first). */
export function okEmail(s: string): boolean {
  return !s.trim() || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());
}
