// From the 2026-10 product review (one title per clip, plain words instead of engine words, real progress,
// requests honoured). English, 简体中文, Français. Spread into sessionFixes so the locale roots stay untouched.

export const reviewEn = {
  // ---------------------------------------------------------------- one title per clip (editor header)
  'ct.label': 'Rename this clip',
  'ct.hint': 'Rename — every post of this clip follows, unless you gave a platform its own title',
  'ct.placeholder': 'Empty = the AI’s title',
  'ct.saved': 'Renamed — the posts follow',
};

export const reviewZh: Record<keyof typeof reviewEn, string> = {
  'ct.label': '改这条的标题',
  'ct.hint': '改标题 —— 这条的各平台发布标题都会跟着变（单独改过的平台除外）',
  'ct.placeholder': '留空 = 用 AI 写的标题',
  'ct.saved': '标题改好了，发布标题已跟着改',
};

export const reviewFr: Record<keyof typeof reviewEn, string> = {
  'ct.label': 'Renommer ce clip',
  'ct.hint': 'Renommer — chaque publication de ce clip suit, sauf une plateforme à qui vous avez donné son propre titre',
  'ct.placeholder': 'Vide = le titre de l’IA',
  'ct.saved': 'Renommé — les publications suivent',
};
