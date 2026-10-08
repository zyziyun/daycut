// The Mac App Store (Lite) build names no other download and links nowhere (App Review 3.1.1 / 2.3): the Lite card
// (Settings › General, first run), the Lite AI note (first run, Settings › AI), the version line and the "not in this
// edition" status are checked in every language. The edition module is mocked to the MAS build for this file only.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterAll, describe, expect, it, vi } from 'vitest';

vi.mock('../../src/shared/edition', async (orig) => {
  const real = await orig<typeof import('../../src/shared/edition')>();
  return { ...real, EDITION: 'mas', IS_LITE: true, CAPS: real.capsFor('mas') };
});

const { LiteAiNote, LiteCard } = await import('../../src/renderer/src/components/Lite');
const { LANGS, LOCALES, setLang, t } = await import('../../src/renderer/src/i18n');
const edition = await import('../../src/shared/edition');

const UPSELL = /reelfold\.com|https?:|www\.|full version|get the full|download|完整版|下载|version complète|télécharg/i;

afterAll(() => setLang('en'));

describe('Lite build: no upsell or external download link', () => {
  it('the test really renders the MAS build', () => {
    expect(edition.IS_LITE).toBe(true);
    expect('FULL_DOWNLOAD_URL' in edition).toBe(false);
  });

  it.each(LANGS)('%s: the Lite card and AI note say what the edition does, with no link out', (lang) => {
    setLang(lang);
    for (const el of [createElement(LiteCard), createElement(LiteCard, { compact: true }), createElement(LiteAiNote)]) {
      const html = renderToStaticMarkup(el);
      expect(html).toMatch(/data-testid="lite-(card|ai)"/);
      expect(html).not.toMatch(/<a\b|<button\b|href=/);
      expect(html).not.toMatch(UPSELL);
    }
    expect(renderToStaticMarkup(createElement(LiteCard))).toContain(t('lite.body'));
  });

  it.each(LANGS)('%s: every Lite string and the "not in this edition" status are neutral', (lang) => {
    const m = LOCALES[lang].messages as Record<string, string>;
    const keys = Object.keys(m).filter((k) => k.startsWith('lite.') || k === 'aiacc.st.unavailable');
    expect(keys).toEqual(expect.arrayContaining(['lite.name', 'lite.badge', 'lite.body', 'lite.aiBody', 'lite.updates', 'aiacc.st.unavailable']));
    expect(keys).not.toContain('lite.cta');
    expect(keys).not.toContain('lite.aiSubs');
    for (const k of keys) expect(m[k], `${lang} ${k}`).not.toMatch(UPSELL);
  });
});
