import { defineConfig } from 'astro/config';
import { SITE } from './src/config.ts';

export default defineConfig({
  site: SITE.url,
  output: 'static',
  trailingSlash: 'ignore',
  build: { inlineStylesheets: 'always' },
  compressHTML: true,
});
