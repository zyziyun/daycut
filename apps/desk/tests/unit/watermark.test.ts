// The watermark contract on the desk side: the export card's default follows the engine's rule (off until a mark
// is set up and "Add to every video" is on; a platform switched off stays clean), the settings page lists platforms in
// the shared registry order, the IPC accepts the logo picker, and every watermark message exists in en / zh / fr.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { EXPORT_PLATFORMS } from '../../src/shared/chatEdit';
import { validateIpc } from '../../src/shared/ipc';
import { orderPlatforms } from '../../src/shared/platforms';
import { watermarkOnFor, type WatermarkDoc } from '../../src/shared/watermark';
import { watermarkEn, watermarkFr, watermarkZh } from '../../src/renderer/src/i18n/locales/watermark';

const doc = (over: Partial<WatermarkDoc['settings']> = {}, configured = true): WatermarkDoc => ({
  configured,
  default_on: configured && !!over.default,
  logo: null,
  settings: { kind: 'text', text: '@me', style: 'badge', color: '#FFFFFF', position: 'bottom-right', size: 0.24, opacity: 0.8, margin: 0.02, default: false, platforms: {}, ...over },
});

describe('watermarkOnFor', () => {
  it('is off until a mark is set up and on by default', () => {
    expect(watermarkOnFor(null)).toBe(false);
    expect(watermarkOnFor(doc({ default: true }, false))).toBe(false);
    expect(watermarkOnFor(doc({ default: false }))).toBe(false);
    expect(watermarkOnFor(doc({ default: true }))).toBe(true);
  });
  it('respects platforms switched off', () => {
    const d = doc({ default: true, platforms: { douyin: false } });
    expect(watermarkOnFor(d, ['douyin:vertical'])).toBe(false);
    expect(watermarkOnFor(d, ['douyin:vertical', 'tiktok:vertical'])).toBe(true);
  });
});

describe('settings page', () => {
  it('lists the platform chips international first', () => {
    const ids = orderPlatforms(EXPORT_PLATFORMS.map((p) => p.id));
    expect(ids.slice(0, 4)).toEqual(['youtube', 'tiktok', 'instagram', 'x']);
    expect(ids.indexOf('xiaohongshu')).toBeGreaterThan(ids.indexOf('x'));
    const src = fs.readFileSync(path.join(import.meta.dirname, '../../src/renderer/src/settings/Watermark.tsx'), 'utf8');
    expect(src).toContain('orderPlatforms(');
  });
  it('the logo picker is an allowed dialog kind', () => {
    expect(validateIpc('dialog:openFile', { kind: 'image' })).toEqual({ kind: 'image' });
  });
  it('has every message in zh and fr', () => {
    expect(Object.keys(watermarkZh).sort()).toEqual(Object.keys(watermarkEn).sort());
    expect(Object.keys(watermarkFr).sort()).toEqual(Object.keys(watermarkEn).sort());
    for (const v of [...Object.values(watermarkZh), ...Object.values(watermarkFr)]) expect(v.trim()).not.toBe('');
  });
});
