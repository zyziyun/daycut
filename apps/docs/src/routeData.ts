import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import ZH_SERIF from './assets/fonts/noto-serif-sc-sub.woff2?url';
import INSTRUMENT from '@fontsource/instrument-serif/files/instrument-serif-latin-400-normal.woff2?url';

// Per-locale Open Graph image, Twitter card, og:locale and a preload of the display font for that locale.
const OG: Record<string, string> = { en: 'og-en.png', 'zh-CN': 'og-zh.png', fr: 'og-en.png', es: 'og-en.png' };
const OG_LOCALE: Record<string, string> = { en: 'en_US', 'zh-CN': 'zh_CN', fr: 'fr_FR', es: 'es_ES' };

export const onRequest = defineRouteMiddleware((context) => {
  const route = context.locals.starlightRoute;
  const lang = route.lang || 'en';
  const site = context.site?.origin ?? 'https://reelfold.com';
  const image = `${site}/docs/og/${OG[lang] ?? OG.en}`;
  const head = route.head;
  const has = (prop: string) => head.some((h) => h.attrs?.property === prop || h.attrs?.name === prop);
  const meta = (key: 'property' | 'name', k: string, content: string) => {
    if (!has(k)) head.push({ tag: 'meta', attrs: { [key]: k, content }, content: '' });
  };
  meta('property', 'og:image', image);
  meta('property', 'og:image:width', '1200');
  meta('property', 'og:image:height', '630');
  meta('property', 'og:image:alt', lang === 'zh-CN' ? '千剪 Reelfold 文档' : 'Reelfold documentation');
  meta('name', 'twitter:image', image);
  const card = head.find((h) => h.attrs?.name === 'twitter:card');
  if (card) card.attrs!.content = 'summary_large_image';
  else meta('name', 'twitter:card', 'summary_large_image');
  const loc = head.find((h) => h.attrs?.property === 'og:locale');
  if (loc) loc.attrs!.content = OG_LOCALE[lang] ?? 'en_US';
  // Untranslated pages (English shown under /zh/, /fr/, /es/): keep them out of the index and point the canonical
  // at the English original, so search engines see one page, not four copies.
  if (route.isFallback) {
    head.push({ tag: 'meta', attrs: { name: 'robots', content: 'noindex, follow' }, content: '' });
    const canonical = head.find((h) => h.tag === 'link' && h.attrs?.rel === 'canonical');
    if (canonical?.attrs?.href) canonical.attrs.href = String(canonical.attrs.href).replace(/\/docs\/(zh|fr|es)\//, '/docs/');
  }
  head.push({
    tag: 'link',
    attrs: lang === 'zh-CN'
      ? { rel: 'preload', as: 'font', type: 'font/woff2', href: ZH_SERIF, crossorigin: '' }
      : { rel: 'preload', as: 'font', type: 'font/woff2', href: INSTRUMENT, crossorigin: '' },
    content: '',
  });
});

