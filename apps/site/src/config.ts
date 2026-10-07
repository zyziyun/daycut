// Single source of truth for values the creator must decide before publishing.
// Edit here, run `npm run build`, done. Nothing else in the codebase hard-codes these.

export const SITE = {
  /** Public URL of the deployed site (used for canonical/hreflang/OG tags). */
  url: 'https://reelfold.com',

  /** Brand name shown in titles (logo: assets/brand, favicons + OG: scripts/brand.mjs). */
  name: 'Reelfold',
  /** Chinese name, shown next to the wordmark on the 中文 pages. French pages use `name`. */
  nameZh: '千剪',

  /** Contact email (footer, legal pages). Placeholder until you set a real inbox. */
  contactEmail: 'hello@example.com',

  /** Open-source repository (the desktop app, the video-studio skill + engine, and this site). */
  githubUrl: 'https://github.com/zyziyun/reelfold',

  /** macOS download: the latest GitHub release of the main repo. */
  downloadUrl: 'https://github.com/zyziyun/reelfold/releases/latest',

  /**
   * false until the first macOS release is published. While false, every "Download for macOS" button is replaced by
   * a "coming soon" state that points to "Star on GitHub" and "Build from source" instead of a dead link
   * (hero, header and the Mac app section). Set to true once the release exists.
   */
  downloadReady: false,
} as const;

export const discussionsUrl = `${SITE.githubUrl}/discussions`;
