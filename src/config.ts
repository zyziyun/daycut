// Single source of truth for values the creator must decide before publishing.
// Edit here, run `npm run build`, done. Nothing else in the codebase hard-codes these.

export const SITE = {
  /** Public URL of the deployed site (used for canonical/hreflang/OG tags). Change when you pick a domain. */
  url: 'https://example.com',

  /** Brand name shown in the header and titles. */
  name: 'video-studio',

  /** Contact email. Placeholder until you set a real inbox. */
  contactEmail: 'hello@example.com',

  /**
   * Design-partner form backend. Empty string = no backend: the form is shown as a preview
   * and visitors are asked to email `contactEmail` instead. See README "Form backend options".
   * Example values: 'https://formspree.io/f/xxxxxxx' or your own Worker URL.
   */
  formEndpoint: '',

  /** Desktop app download page (one URL for macOS and Windows; GitHub "latest release" page). */
  downloadUrl: 'https://github.com/zyziyun/video-studio-desk-releases/releases/latest',

  /** Open-source skill repository. */
  githubUrl: 'https://github.com/zyziyun/video-studio',

  /** Design-partner program size. */
  partnerSlots: 30,
} as const;
