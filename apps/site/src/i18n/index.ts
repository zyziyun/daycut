import { en, type Dict } from './en';
import { zh } from './zh';
import { fr } from './fr';
import { es } from './es';

export type Lang = 'en' | 'zh' | 'fr' | 'es';
/** Order of the language switcher (the creator asked for 中文 / English / Français / Español). */
export const LANGS: readonly Lang[] = ['zh', 'en', 'fr', 'es'];
/** Non-default languages (each lives under /<lang>/). */
export const PREFIXED: readonly Exclude<Lang, 'en'>[] = ['zh', 'fr', 'es'];

export const HTML_LANG: Record<Lang, string> = { en: 'en', zh: 'zh-CN', fr: 'fr', es: 'es' };
export const HREFLANG: Record<Lang, string> = { en: 'en', zh: 'zh-Hans', fr: 'fr', es: 'es' };
export const OG_LOCALE: Record<Lang, string> = { en: 'en_US', zh: 'zh_CN', fr: 'fr_FR', es: 'es_ES' };
export const LANG_NAME: Record<Lang, string> = { zh: '中文', en: 'English', fr: 'Français', es: 'Español' };

const dict: Record<Lang, Dict> = { en, zh, fr, es };
export const t = (lang: Lang): Dict => dict[lang];

/** Path prefix for a language: '' for English (default), '/zh', '/fr', '/es'. */
export const prefix = (lang: Lang) => (lang === 'en' ? '' : `/${lang}`);

/** URL path of `page` ('' = home, 'privacy', 'compare/descript', ...) in `lang`, always with a trailing slash. */
export const pathFor = (lang: Lang, page = '') => `${prefix(lang)}/${page ? `${page}/` : ''}`;

/** Format a YYYY-MM-DD date for display in `lang`. */
export const fmtDate = (lang: Lang, iso: string) =>
  new Intl.DateTimeFormat(HTML_LANG[lang], { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(
    new Date(`${iso}T00:00:00Z`),
  );

export type { Dict };
