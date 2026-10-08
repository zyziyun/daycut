// The creator's watermark (engine: lib/vstudio/watermark.py, settings in $VSTUDIO_HOME/watermark.json). Nothing is
// drawn until she sets a handle or a logo AND turns on "Add to every video"; one export can still say on / off.

export type WatermarkKind = 'text' | 'image' | 'generate';
export type WatermarkStyle = 'badge' | 'monogram' | 'plain';
export type WatermarkPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

export interface WatermarkSettings {
  kind: WatermarkKind;
  text: string;
  style: WatermarkStyle;
  color: string;
  position: WatermarkPosition;
  /** the mark fits a square of size x the frame's short side */
  size: number;
  opacity: number;
  margin: number;
  /** add it to every export by default */
  default: boolean;
  /** platform id -> false: never on that platform */
  platforms: Record<string, boolean>;
}

export interface WatermarkDoc {
  settings: WatermarkSettings;
  /** a handle (text / generate) or a logo file is set */
  configured: boolean;
  /** exports get it unless an export says off */
  default_on: boolean;
  /** file name of the stored logo (kind image) */
  logo: string | null;
  /** JPEG data URLs: the mark over a sample frame, placed as the export places it */
  previews?: Record<'9:16' | '16:9', string>;
}

export const WM_POSITIONS: WatermarkPosition[] = ['top-left', 'top-right', 'bottom-left', 'bottom-right'];
export const WM_STYLES: WatermarkStyle[] = ['badge', 'monogram', 'plain'];
export const WM_SIZE = { min: 0.08, max: 0.4 };
export const WM_OPACITY = { min: 0.2, max: 1 };
export const WM_MAX_TEXT = 40;

/** Whether exports for these platforms get the mark by default (the export card's switch starts here): on when
 * any chosen platform takes it. */
export function watermarkOnFor(doc: Pick<WatermarkDoc, 'configured' | 'settings'> | null | undefined, platforms: string[] = []): boolean {
  if (!doc?.configured || !doc.settings.default) return false;
  if (!platforms.length) return true;
  return platforms.some((p) => doc.settings.platforms?.[p.split(':')[0]] !== false);
}
