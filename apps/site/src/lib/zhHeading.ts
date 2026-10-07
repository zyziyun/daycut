/**
 * Chinese heading line breaks (from the F prototype's H()): split after ，。；：？！ into
 * <span class="ph"> (display:inline-block) so a clause never breaks in the middle, e.g. never
 * "二十个平台，各 / 有各的尺寸". Other languages are returned escaped and unchanged.
 */
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export function heading(text: string, lang: string): string {
  if (lang !== 'zh') return esc(text);
  const parts = text.match(/[^，。；：？！]+[，。；：？！]?|[，。；：？！]/g) ?? [text];
  return parts.map((p) => `<span class="ph">${esc(p)}</span>`).join('');
}
