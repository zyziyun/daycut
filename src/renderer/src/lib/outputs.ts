// Preview-side folding of edit ops (the "after" of a 让 AI 改 proposal before it is applied): trim, inner cuts and
// effects, mirroring what the engine's render will do, for what the player can show.
import type { EditOp, OutputDoc } from '../../../shared/v04';

export function previewDoc(doc: OutputDoc, ops: EditOp[] | null): OutputDoc {
  if (!ops?.length) return doc;
  const out: OutputDoc = { ...doc, cuts: [...doc.cuts], effects: [...doc.effects], trim: doc.trim ? { ...doc.trim } : null };
  let n = doc.effects.length;
  for (const o of ops) {
    if (o.op === 'trim') out.trim = o.start == null && o.end == null ? null : { start: o.start ?? 0, end: o.end ?? doc.duration };
    else if (o.op === 'cut') out.cuts.push({ start: o.start, end: o.end, index: out.cuts.length });
    else if (o.op === 'cut_remove') out.cuts = out.cuts.filter((c) => c.index !== o.index);
    else if (o.op === 'effect_add') out.effects.push({ id: `preview${++n}`, effect: o.effect, start: o.start, end: o.end ?? o.start + 1.2, params: o.params ?? {} });
    else if (o.op === 'effect_remove') out.effects = out.effects.filter((e) => e.id !== o.id);
    else if (o.op === 'effect_update') out.effects = out.effects.map((e) => (e.id === o.id ? { ...e, start: o.start ?? e.start, end: o.end ?? e.end, params: { ...e.params, ...(o.params ?? {}) } } : e));
  }
  out.cuts.sort((a, b) => a.start - b.start);
  return out;
}

/** Kept length after trim and inner cuts. */
export function keptLength(doc: Pick<OutputDoc, 'duration' | 'trim' | 'cuts'>): number {
  const a = doc.trim?.start ?? 0;
  const b = doc.trim?.end ?? doc.duration;
  let cut = 0;
  for (const c of doc.cuts) cut += Math.max(0, Math.min(b, c.end) - Math.max(a, c.start));
  return Math.max(0, b - a - cut);
}
