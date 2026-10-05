// Assisted fill = a list of steps executed over the Chrome DevTools Protocol in the platform page.
// Step kinds are closed: set files on a file input, type text into a field, outline the publish button.
// There is no click step - publishing is always the creator's own click.
import type { Adapter } from './adapterSchema';
import { formatTags, type PostCopy } from './postCopy';

export type FillStep =
  | { kind: 'files'; field: 'file' | 'cover'; selectors: string[]; paths: string[]; timeoutMs: number }
  | {
      kind: 'text';
      field: 'title' | 'description' | 'tags';
      selectors: string[];
      text: string;
      editable: 'input' | 'contenteditable';
      clear: boolean;
      timeoutMs: number;
    }
  | { kind: 'highlight'; field: 'publish'; selectors: string[]; timeoutMs: number };

export interface FillPayload {
  videoPath: string;
  coverPath?: string | null;
  copy: PostCopy;
}

const DEFAULT_TIMEOUT = 20000;

function clip(s: string, n?: number): string {
  if (!n) return s;
  const chars = Array.from(s);
  return chars.length > n ? chars.slice(0, n).join('') : s;
}

export function planFill(a: Adapter, p: FillPayload): FillStep[] {
  const f = a.fields;
  const steps: FillStep[] = [
    { kind: 'files', field: 'file', selectors: f.file.selectors, paths: [p.videoPath], timeoutMs: f.file.timeoutMs ?? DEFAULT_TIMEOUT },
  ];
  if (f.title && p.copy.title) {
    steps.push({
      kind: 'text',
      field: 'title',
      selectors: f.title.selectors,
      text: clip(p.copy.title, f.title.maxLength),
      editable: f.title.kind,
      clear: f.title.clear,
      timeoutMs: f.title.timeoutMs ?? DEFAULT_TIMEOUT,
    });
  }
  let desc = p.copy.description;
  if (f.tags && p.copy.tags.length) {
    const tagText = formatTags(p.copy.tags, f.tags.format, f.tags.max);
    if (f.tags.mode === 'append-to-description') {
      desc = desc ? `${desc}\n\n${tagText}` : tagText;
    } else if (f.tags.selectors) {
      steps.push({
        kind: 'text',
        field: 'tags',
        selectors: f.tags.selectors,
        text: p.copy.tags.slice(0, f.tags.max ?? p.copy.tags.length).join(','),
        editable: 'input',
        clear: false,
        timeoutMs: DEFAULT_TIMEOUT,
      });
    }
  }
  if (f.description && desc) {
    // description goes before separate tags so the page order is natural
    const idx = steps.findIndex((s) => s.field === 'tags');
    const step: FillStep = {
      kind: 'text',
      field: 'description',
      selectors: f.description.selectors,
      text: clip(desc, f.description.maxLength),
      editable: f.description.kind,
      clear: f.description.clear,
      timeoutMs: f.description.timeoutMs ?? DEFAULT_TIMEOUT,
    };
    if (idx >= 0) steps.splice(idx, 0, step);
    else steps.push(step);
  }
  if (f.cover && p.coverPath) {
    steps.push({ kind: 'files', field: 'cover', selectors: f.cover.selectors, paths: [p.coverPath], timeoutMs: f.cover.timeoutMs ?? 5000 });
  }
  if (a.publishButton) {
    steps.push({ kind: 'highlight', field: 'publish', selectors: a.publishButton.selectors, timeoutMs: 3000 });
  }
  return steps;
}
