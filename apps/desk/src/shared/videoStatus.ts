// One set of status words for a video, everywhere (2026-10 review step 7): the Studio's filters and dots, a project's
// clips, the Calendar, the Dock badge and the notifications all say the same thing. The words live in the UI
// languages under `vs.*`; older keys (status.*, hub.g.*, hub.s.*) are the same words (renderer i18n/locales/studio.ts).
export const VIDEO_STATUS = ['you', 'run', 'ready', 'scheduled', 'posted', 'stopped'] as const;
export type VideoStatus = (typeof VIDEO_STATUS)[number];

/** The i18n key of each status word. */
export const VIDEO_STATUS_KEY: Record<VideoStatus, `vs.${VideoStatus}`> = {
  you: 'vs.you',
  run: 'vs.run',
  ready: 'vs.ready',
  scheduled: 'vs.scheduled',
  posted: 'vs.posted',
  stopped: 'vs.stopped',
};

/** The filters of the Studio list, in order (all + the four groups a video can be in). */
export const STUDIO_GROUPS = ['you', 'run', 'ready', 'scheduled'] as const satisfies readonly VideoStatus[];
