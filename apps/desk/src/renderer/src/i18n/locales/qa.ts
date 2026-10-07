// Strings added by the bug bash (qa/BUGS.md): engine crash / restart, states that showed a raw key, small labels
// that were hard-coded. One file so the big locale files stay untouched apart from the merge line.
export const qaEn = {
  'engine.stopped': 'The engine stopped',
  'engine.restarting': 'The engine stopped unexpectedly — restarting it…',
  'pub.state.filled': 'Filled in',
  'ce.selected': 'selected',
  'project.noPlatforms': 'No platform to post to: choose your platforms in Settings › General first.',
  'project.editInterrupted': 'An edit was cut off before it finished ({what}). Open that clip and ask again to redo it.',
  'project.editFailed': 'An edit did not finish ({what}). Open that clip and ask again to redo it.',
  'fail.reason.intake': 'The planner didn’t answer, so nothing was made. Try again; if it keeps happening, restart Reelfold.',
  'plan.took': 'planned from {n, plural, one {# file} other {# files}} in {s} s',
};

type QaKey = keyof typeof qaEn;

export const qaZh: Record<QaKey, string> = {
  'engine.stopped': '引擎停止了',
  'engine.restarting': '引擎意外停止了，正在重启…',
  'pub.state.filled': '已填好',
  'ce.selected': '选中',
  'project.noPlatforms': '还没有要发的平台：先在「设置 › 通用」里选好平台。',
  'project.editInterrupted': '有一次修改没做完就中断了（{what}）。打开那条视频再说一次就能重做。',
  'project.editFailed': '有一次修改没做成（{what}）。打开那条视频再说一次就能重做。',
  'fail.reason.intake': '做方案的程序没有响应，所以什么都没做。再试一次；一直这样就重启千剪。',
  'plan.took': '读了 {n} 个文件，做方案用时 {s} 秒',
};

export const qaFr: Record<QaKey, string> = {
  'engine.stopped': 'Le moteur s’est arrêté',
  'engine.restarting': 'Le moteur s’est arrêté de façon inattendue — redémarrage…',
  'pub.state.filled': 'Rempli',
  'ce.selected': 'sélectionné',
  'project.noPlatforms': 'Aucune plateforme où publier : choisissez d’abord vos plateformes dans Réglages › Général.',
  'project.editInterrupted': 'Une modification s’est arrêtée avant la fin ({what}). Ouvrez ce clip et redemandez-la.',
  'project.editFailed': 'Une modification n’a pas abouti ({what}). Ouvrez ce clip et redemandez-la.',
  'fail.reason.intake': 'Le planificateur n’a pas répondu, rien n’a été créé. Réessayez ; si cela se reproduit, redémarrez Reelfold.',
  'plan.took': 'plan établi à partir de {n, plural, one {# fichier} other {# fichiers}} en {s} s',
};
