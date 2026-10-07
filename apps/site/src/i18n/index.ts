import { zh } from './zh';
import { en } from './en';
import { fr } from './fr';

export type Lang = 'en' | 'zh' | 'fr';
export const LANGS: readonly Lang[] = ['en', 'zh', 'fr'];
export const dict = { en, zh, fr } as const;
export const t = (lang: Lang) => dict[lang];

/** Path prefix for a language: '' for English (default), '/zh' for 中文, '/fr' for Français. */
export const prefix = (lang: Lang) => (lang === 'en' ? '' : `/${lang}`);

/** URL path of `page` ('' = home, 'privacy', 'terms') in `lang`. Home is '/', '/zh/' or '/fr/'. */
export const pathFor = (lang: Lang, page: string) => (page ? `${prefix(lang)}/${page}` : `${prefix(lang)}/`);
