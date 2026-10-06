import { defineConfig } from 'astro/config';
import { SITE } from './src/config.ts';

export default defineConfig({
  site: SITE.url,
  output: 'static',
  trailingSlash: 'ignore',
  build: { inlineStylesheets: 'always' },
  compressHTML: true,
  // English moved from /en/ to /. Static output writes meta-refresh pages for these (with canonical to the target).
  redirects: {
    '/en': '/',
    '/en/privacy': '/privacy',
    '/en/terms': '/terms',
  },
});
