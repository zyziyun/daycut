import { zh } from './zh';
import { en } from './en';

export type Lang = 'en' | 'zh';
export const dict = { en, zh } as const;
export const t = (lang: Lang) => dict[lang];

/** Path prefix for a language: '' for English (default), '/zh' for 中文. */
export const prefix = (lang: Lang) => (lang === 'zh' ? '/zh' : '');

/** URL path of `page` ('' = home, 'privacy', 'terms') in `lang`. Home is '/' or '/zh/'. */
export const pathFor = (lang: Lang, page: string) => (page ? `${prefix(lang)}/${page}` : `${prefix(lang)}/`);
