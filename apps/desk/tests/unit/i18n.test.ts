// The locale adapter: every key exists in every locale with the same placeholders (a missing key is also a type
// error), ICU plurals / select / numbers, fallback to English, and no hard-coded copy in the v0.4 components.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { formatMessage, placeholders } from '../../src/renderer/src/i18n/icu';
import { en } from '../../src/renderer/src/i18n/locales/en';
import { zhCN } from '../../src/renderer/src/i18n/locales/zh-CN';
import { LANGS, LOCALES, normalizeLang, setLang, t, tk } from '../../src/renderer/src/i18n';

describe('locales', () => {
  it('every locale has every key, with the same placeholders', () => {
    for (const l of LANGS) {
      const m = LOCALES[l].messages as Record<string, string>;
      const missing = Object.keys(en).filter((k) => typeof m[k] !== 'string' || !m[k].trim());
      expect(missing, `${l} misses keys`).toEqual([]);
      const extra = Object.keys(m).filter((k) => !(k in en));
      expect(extra, `${l} has unknown keys`).toEqual([]);
    }
    for (const l of LANGS.filter((x) => x !== 'en')) {
      const m = LOCALES[l].messages as Record<string, string>;
      const bad = Object.keys(en).filter((k) => {
        const a = placeholders((en as Record<string, string>)[k]).filter((x) => !/^(one|other|few|many|zero|two)$/.test(x));
        const b = placeholders(m[k]).filter((x) => !/^(one|other|few|many|zero|two)$/.test(x));
        // plural branches may differ between languages; the variables must not
        return a.filter((x) => !b.includes(x)).length > 0;
      });
      expect(bad, `${l} placeholders`).toEqual([]);
    }
    expect(LANGS).toEqual(['en', 'zh-CN', 'fr']);
    expect(zhCN['status.you']).toBe('要你看'); // one set of status words (shared/videoStatus)
  });

  it('English is the default; zh / zh-CN map to the registered locale', () => {
    expect(normalizeLang(undefined)).toBe('en');
    expect(normalizeLang('zh')).toBe('zh-CN');
    expect(normalizeLang('fr')).toBe('fr');
    expect(normalizeLang('fr-CA')).toBe('fr');
    expect(normalizeLang('de')).toBe('en');
  });

  it('formats plurals, numbers and select with the active locale', () => {
    expect(formatMessage('{n, plural, one {# clip} other {# clips}}', 'en', { n: 1 })).toBe('1 clip');
    expect(formatMessage('{n, plural, one {# clip} other {# clips}}', 'en', { n: 1200 })).toBe('1,200 clips');
    expect(formatMessage('{n, plural, =0 {none} other {#}}', 'en', { n: 0 })).toBe('none');
    expect(formatMessage('{k, select, a {A} other {B}}', 'en', { k: 'z' })).toBe('B');
    expect(formatMessage('Hi {name}', 'en', { name: '小红' })).toBe('Hi 小红');
    setLang('zh-CN');
    expect(t('projects.clips', { n: 4 })).toBe('4 条');
    expect(t('status.you')).toBe('要你看');
    setLang('en');
    expect(t('projects.clips', { n: 4 })).toBe('4 clips');
    expect(tk('no.such.key')).toBe('no.such.key');
  });

  it('the v0.4 screens have no hard-coded copy (CJK or English words outside the locale files)', () => {
    const dir = path.resolve(import.meta.dirname, '../../src/renderer/src/v4');
    const offenders: string[] = [];
    for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.tsx'))) {
      const src = fs.readFileSync(path.join(dir, f), 'utf8').replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
      src.split('\n').forEach((line, i) => {
        if (/[一-鿿]/.test(line)) offenders.push(`${f}:${i + 1} CJK: ${line.trim()}`);
        const jsxText = line.match(/[^=]>\s*([A-Za-z][A-Za-z ,.'!?]{2,})\s*<\//);
        if (jsxText && !/^(Space|Esc)$/.test(jsxText[1].trim())) offenders.push(`${f}:${i + 1} text: ${jsxText[1]}`);
        const attr = line.match(/\b(placeholder|title|aria-label|data-tip)="([A-Za-z][^"]{2,})"/);
        if (attr) offenders.push(`${f}:${i + 1} ${attr[1]}: ${attr[2]}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
