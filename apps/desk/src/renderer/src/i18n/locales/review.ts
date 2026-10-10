// From the 2026-10 product review (one title per clip, plain words instead of engine words, real progress,
// requests honoured). English, 简体中文, Français. Spread into sessionFixes so the locale roots stay untouched.

export const reviewEn = {
  // ---------------------------------------------------------------- one title per clip (editor header)
  'ct.label': 'Rename this clip',
  'ct.hint': 'Rename — every post of this clip follows, unless you gave a platform its own title',
  'ct.placeholder': 'Empty = the AI’s title',
  'ct.saved': 'Renamed — the posts follow',

  // ---------------------------------------------------------------- the engine's status line, in words
  'live.c.jobs': 'Clip {k} of {n}',
  'live.c.jobsDone': '{done} of {n} clips made',
  'live.c.finished': '{n, plural, one {# clip made} other {# clips made}}',
  'live.c.someFailed': '{n, plural, one {# clip made, some stopped} other {# clips made, some stopped}}',
  'live.c.itemsFailed': '{n, plural, one {# clip stopped} other {# clips stopped}}',
  'live.c.checkpoint': 'Waiting for you: {what}',
  'live.c.waiting': 'Waiting for you',
  'live.c.pilot': 'The first clip is ready — have a look, then let the rest run',
  'live.c.overBudget': 'Stopped before starting: over the budget you set',
  'live.c.done': 'Done',
  // ---------------------------------------------------------------- clips named, not numbered by id
  'hub.clipFailed': 'Didn’t finish',
  'hub.clipNamed': '“{title}”',
  'hub.clipN': 'clip {n}',
  'hub.decisionOther': 'A choice',
};

export const reviewZh: Record<keyof typeof reviewEn, string> = {
  'ct.label': '改这条的标题',
  'ct.hint': '改标题 —— 这条的各平台发布标题都会跟着变（单独改过的平台除外）',
  'ct.placeholder': '留空 = 用 AI 写的标题',
  'ct.saved': '标题改好了，发布标题已跟着改',

  'live.c.jobs': '第 {k}/{n} 条',
  'live.c.jobsDone': '{n} 条里做好 {done} 条',
  'live.c.finished': '做好了 {n} 条',
  'live.c.someFailed': '做好了 {n} 条，有几条停下了',
  'live.c.itemsFailed': '{n} 条停下了',
  'live.c.checkpoint': '等你：{what}',
  'live.c.waiting': '等你看一下',
  'live.c.pilot': '第 1 条做好了，先看一眼，再让剩下的接着做',
  'live.c.overBudget': '没开始：超出了你设的预算',
  'live.c.done': '做完了',
  'hub.clipFailed': '没做成',
  'hub.clipNamed': '「{title}」',
  'hub.clipN': '第 {n} 条',
  'hub.decisionOther': '一个选择',
};

export const reviewFr: Record<keyof typeof reviewEn, string> = {
  'ct.label': 'Renommer ce clip',
  'ct.hint': 'Renommer — chaque publication de ce clip suit, sauf une plateforme à qui vous avez donné son propre titre',
  'ct.placeholder': 'Vide = le titre de l’IA',
  'ct.saved': 'Renommé — les publications suivent',

  'live.c.jobs': 'Clip {k} sur {n}',
  'live.c.jobsDone': '{done} clips prêts sur {n}',
  'live.c.finished': '{n, plural, one {# clip prêt} other {# clips prêts}}',
  'live.c.someFailed': '{n, plural, one {# clip prêt, certains se sont arrêtés} other {# clips prêts, certains se sont arrêtés}}',
  'live.c.itemsFailed': '{n, plural, one {# clip arrêté} other {# clips arrêtés}}',
  'live.c.checkpoint': 'Vous attend : {what}',
  'live.c.waiting': 'Vous attend',
  'live.c.pilot': 'Le premier clip est prêt — regardez-le, puis laissez faire le reste',
  'live.c.overBudget': 'Pas lancé : au-delà du budget fixé',
  'live.c.done': 'Terminé',
  'hub.clipFailed': 'Pas terminé',
  'hub.clipNamed': '« {title} »',
  'hub.clipN': 'clip {n}',
  'hub.decisionOther': 'Un choix',
};
