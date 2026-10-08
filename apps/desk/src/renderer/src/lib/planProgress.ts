// What the plan card shows while a plan is being made: the engine's current stage in words (with a determinate bar
// when the stage knows how far it is), and the five steps of a plan - done / current / pending / skipped.
import type { IntakeProgress, IntakeStage } from '../../../shared/v04';
import { providerName } from '../../../shared/aiRoutes';
import { fmtClock, t } from '../i18n';

export type PlanStep = 'scan' | 'media' | 'transcribe' | 'model' | 'write';
export type PlanStepState = 'done' | 'current' | 'pending' | 'skipped';

export const PLAN_STEPS: PlanStep[] = ['scan', 'media', 'transcribe', 'model', 'write'];
const STEP_KEY = {
  scan: 'plan.step.scan',
  media: 'plan.step.media',
  transcribe: 'plan.step.transcribe',
  model: 'plan.step.model',
  write: 'plan.step.write',
} as const;

/** probing a file, listening to a sample and looking for faces are all "reading each file" */
export function stepOf(stage: IntakeStage): PlanStep {
  return stage === 'probe' || stage === 'listen' || stage === 'faces' ? 'media' : stage;
}

export interface PlanProgressView {
  /** the current stage in words, e.g. "Transcribing talk.mp4" */
  label: string;
  /** e.g. "4:10 / 12:44" or "file 3 of 27" */
  detail: string | null;
  /** 0..1 when the stage knows how far it is, else null (no bar) */
  fraction: number | null;
  steps: { id: PlanStep; label: string; state: PlanStepState; note: string | null }[];
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

function stageLabel(p: IntakeProgress): string {
  const file = p.file ?? '';
  switch (p.stage) {
    case 'scan':
      return t('plan.prog.scan');
    case 'probe':
      return p.cached ? t('plan.prog.probeCached', { file }) : t('plan.prog.probe', { file });
    case 'listen':
      return t('plan.prog.listen', { file });
    case 'faces':
      return t('plan.prog.faces', { file });
    case 'transcribe':
      return p.cached ? t('plan.prog.transcribeCached', { file }) : t('plan.prog.transcribe', { file });
    case 'model': {
      const who = providerName(p.provider);
      return who && who !== 'none' && who !== 'rules' ? t('plan.prog.model', { provider: who }) : t('plan.prog.modelAny');
    }
    case 'write':
      return t('plan.prog.write');
  }
}

/** -> null while no progress has arrived (an older engine, or the first instant of a plan): the card keeps its
 * plain "Working out a plan…" line then. */
export function planProgressView(p: IntakeProgress | null | undefined): PlanProgressView | null {
  if (!p?.stage) return null;
  const cur = stepOf(p.stage);
  const at = PLAN_STEPS.indexOf(cur);
  const seen = new Set((p.seen ?? [p.stage]).map(stepOf));
  seen.add(cur);
  let detail: string | null = null;
  let fraction: number | null = null;
  if (p.stage === 'transcribe' && !p.cached && p.total_s) {
    const done = Math.min(p.done_s ?? 0, p.total_s);
    detail = `${fmtClock(done)} / ${fmtClock(p.total_s)}`;
    fraction = clamp01(done / p.total_s);
  } else if (cur === 'media' && p.i && p.n) {
    detail = t('plan.prog.ofFiles', { i: p.i, n: p.n });
    fraction = clamp01((p.i - 1) / p.n);
  } else if (p.stage === 'scan' && p.files != null) {
    detail = t('plan.prog.found', { n: p.files });
  }
  const steps = PLAN_STEPS.map((id, k) => {
    let state: PlanStepState = k < at ? 'done' : k === at ? 'current' : 'pending';
    // transcription only runs when the request picks content inside a recording; past it without one, it was not needed
    if (id === 'transcribe' && k < at && !seen.has('transcribe')) state = 'skipped';
    let note: string | null = null;
    if (id === 'transcribe' && state === 'skipped') note = t('plan.step.skipped');
    else if (id === 'transcribe' && (p.reused || (p.stage === 'transcribe' && p.cached))) note = t('plan.step.cached');
    else if (id === 'scan' && p.files != null && state !== 'pending') note = t('plan.prog.found', { n: p.files });
    return { id, label: t(STEP_KEY[id]), state, note };
  });
  return { label: stageLabel(p), detail, fraction, steps };
}
