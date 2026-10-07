import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import { SITE } from './src/config.ts';

// Pages left out of the sitemap: draft legal pages (noindex), the 404 page and the old /en/ redirect stubs.
const EXCLUDE = /\/(privacy|terms|404)\/?$|\/en(\/|$)/;

export default defineConfig({
  site: SITE.url,
  output: 'static',
  trailingSlash: 'always',
  build: { inlineStylesheets: 'always', format: 'directory' },
  compressHTML: true,
  integrations: [
    sitemap({
      filter: (page) => !EXCLUDE.test(new URL(page).pathname),
      // xhtml:link alternates for every language version of a page
      i18n: { defaultLocale: 'en', locales: { en: 'en', zh: 'zh-Hans', fr: 'fr', es: 'es' } },
    }),
  ],
  // English moved from /en/ to /. Static output writes meta-refresh pages for these (with canonical to the target).
  redirects: {
    '/en': '/',
    '/en/privacy': '/privacy/',
    '/en/terms': '/terms/',
  },
});
