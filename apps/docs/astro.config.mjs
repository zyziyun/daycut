// Reelfold docs: Astro Starlight, served at https://reelfold.com/docs (copied into the site's dist/docs by
// scripts/build-web.sh, so the site Worker serves both). English is the root locale; zh / fr / es are translations
// (pages that are not translated yet fall back to English with a notice).
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { sidebar } from './src/sidebar.mjs';

// Pages that exist in English only are served under /zh/, /fr/, /es/ as fallbacks (noindex, canonical = English,
// see src/routeData.ts); keep them out of the sitemap too.
const DOCS_DIR = new URL('./src/content/docs/', import.meta.url);
const LOCALES = ['zh', 'fr', 'es'];
const slugs = (dir, base = '') =>
  readdirSync(new URL(dir, DOCS_DIR)).flatMap((f) => {
    const rel = base + f;
    if (statSync(new URL(dir + f, DOCS_DIR)).isDirectory()) return LOCALES.includes(rel) && !base ? [] : slugs(dir + f + '/', rel + '/');
    return /\.mdx?$/.test(f) ? [rel.replace(/(^|\/)index\.mdx?$/, '$1').replace(/\.mdx?$/, '/')] : [];
  });
const translated = (loc) => new Set(existsSync(new URL(loc + '/', DOCS_DIR)) ? slugs(loc + '/') : []);
const fallbackUrls = new Set(
  LOCALES.flatMap((loc) => {
    const have = translated(loc);
    return slugs('').filter((s) => !have.has(s)).map((s) => `https://reelfold.com/docs/${loc}/${s}`);
  }),
);

export default defineConfig({
  site: 'https://reelfold.com',
  base: '/docs',
  trailingSlash: 'ignore',
  build: { format: 'directory' },
  compressHTML: true,
  // Markdown images get a srcset (no 1600 px image on a phone).
  image: { layout: 'constrained' },
  integrations: [
    sitemap({ filter: (page) => !fallbackUrls.has(page) }),
    starlight({
      title: { en: 'Reelfold Docs', 'zh-CN': '千剪 Reelfold 文档', fr: 'Documentation Reelfold', es: 'Documentación de Reelfold' },
      description: 'Reelfold (千剪) documentation: install the free Mac app or the Claude Code skill, and turn one recording into every cut for every platform.',
      logo: {
        light: './src/assets/wordmark-on-light.svg',
        dark: './src/assets/wordmark-on-dark.svg',
        replacesTitle: true,
        alt: 'Reelfold',
      },
      favicon: '/favicon.svg',
      defaultLocale: 'root',
      locales: {
        root: { label: 'English', lang: 'en' },
        zh: { label: '简体中文', lang: 'zh-CN' },
        fr: { label: 'Français', lang: 'fr' },
        es: { label: 'Español', lang: 'es' },
      },
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/zyziyun/reelfold' }],
      editLink: { baseUrl: 'https://github.com/zyziyun/reelfold/edit/main/apps/docs/' },
      lastUpdated: false,
      pagination: true,
      customCss: ['./src/styles/fonts.css', './src/styles/paper.css'],
      components: {
        SocialIcons: './src/components/SocialIcons.astro',
      },
      routeMiddleware: './src/routeData.ts',
      head: [
        { tag: 'meta', attrs: { name: 'theme-color', content: '#F4F0E8' } },
        { tag: 'link', attrs: { rel: 'apple-touch-icon', href: '/docs/apple-touch-icon.png' } },
      ],
      sidebar,
      expressiveCode: {
        themes: ['github-light', 'github-dark'],
        styleOverrides: {
          borderRadius: '6px',
          borderColor: 'var(--rf-rule)',
          codeFontFamily: 'var(--sl-font-mono)',
          frames: { shadowColor: 'transparent' },
        },
      },
    }),
  ],
});
