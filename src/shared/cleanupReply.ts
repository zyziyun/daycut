// Transcript toggles -> the creator reply understood by vstudio.cleanup.parse_reply ("确认 3,5 / 保留 7").
// auto edits are cut unless kept; confirm edits are cut only when approved; keep edits are never cut.

export interface EditState {
  id: number;
  action: 'auto' | 'confirm' | 'keep';
  cut: boolean;
}

export function buildReply(edits: EditState[]): string {
  const approve = edits.filter((e) => e.action === 'confirm' && e.cut).map((e) => e.id);
  const keep = edits.filter((e) => e.action === 'auto' && !e.cut).map((e) => e.id);
  const sort = (a: number[]) => [...new Set(a)].sort((x, y) => x - y).join(',');
  const parts: string[] = [];
  if (approve.length) parts.push(`确认 ${sort(approve)}`);
  if (keep.length) parts.push(`保留 ${sort(keep)}`);
  return parts.join(' / ');
}

export function canToggle(e: { action: string }): boolean {
  return e.action === 'auto' || e.action === 'confirm';
}
