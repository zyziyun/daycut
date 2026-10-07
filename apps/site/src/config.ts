// Single source of truth for values the creator must decide before publishing.
// Edit here, run `npm run build`, done. Nothing else in the codebase hard-codes these.

export const SITE = {
  /** Public URL of the deployed site (canonical, hreflang, sitemap, OG tags). `astro.config.mjs` reads it. */
  url: 'https://reelfold.com',

  /** Brand name. English, French and Spanish pages use `name`; the 中文 pages use `nameZh`. */
  name: 'Reelfold',
  nameZh: '千剪',

  /** Contact email (legal pages). Placeholder until you set a real inbox. */
  contactEmail: 'hello@example.com',

  /** Open-source repository (desktop app, video-studio skill + engine, and this site). */
  githubUrl: 'https://github.com/zyziyun/reelfold',

  /** macOS download: the latest GitHub release of the main repo. */
  downloadUrl: 'https://github.com/zyziyun/reelfold/releases/latest',

  /**
   * THE "coming soon" switch. `false` (default) until the first macOS release exists: no download link anywhere;
   * the main button becomes "Star on GitHub", the second one "Build from source", and the fine print says the
   * macOS app is coming soon. Set to `true` once https://github.com/zyziyun/reelfold/releases/latest has a release:
   * every button on every page and language switches to "Download for macOS".
   */
  downloadReady: false,
} as const;

export const site = SITE.url.replace(/\/$/, '');
export const discussionsUrl = `${SITE.githubUrl}/discussions`;
export const releasesUrl = `${SITE.githubUrl}/releases`;
export const licenseUrl = `${SITE.githubUrl}/blob/main/LICENSE`;
export const contributingUrl = `${SITE.githubUrl}/issues`;
export const buildFromSourceUrl = `${SITE.githubUrl}#install`;
export const platformsDocUrl = `${SITE.githubUrl}/blob/main/references/PLATFORMS.md`;

/**
 * Docs: a separate Starlight site (apps/docs), copied into dist/docs at deploy time and served by this site's
 * Worker. This site never builds anything under /docs and has no redirect for it.
 * Locale paths: /docs/ (en), /docs/zh-cn/, /docs/fr/, /docs/es/.
 */
export const DOCS_PATH = { en: '/docs/', zh: '/docs/zh-cn/', fr: '/docs/fr/', es: '/docs/es/' } as const;

/** Claude Code skill install (same text as the repo README). */
export const SKILL_CMD = [
  `git clone ${SITE.githubUrl} ~/.claude/skills/video-studio`,
  '~/.claude/skills/video-studio/install.sh',
];
