import { zh } from './zh';
import { en } from './en';

export type Lang = 'zh' | 'en';
export const dict = { zh, en } as const;
export const t = (lang: Lang) => dict[lang];

/** Path prefix for a language: '' for 中文 (default), '/en' for English. */
export const prefix = (lang: Lang) => (lang === 'en' ? '/en' : '');

/** Same page in the other language. `page` is '' (home), 'privacy' or 'terms'. */
export const altPath = (lang: Lang, page: string) => {
  const other: Lang = lang === 'en' ? 'zh' : 'en';
  return `${prefix(other)}/${page}`.replace(/\/+$/, '') || '/';
};
