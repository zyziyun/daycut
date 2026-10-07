// Strings added by the bug bash (qa/BUGS.md): engine crash / restart, states that showed a raw key, small labels
// that were hard-coded. One file so the big locale files stay untouched apart from the merge line.
export const qaEn = {
  'engine.stopped': 'The engine stopped',
  'engine.restarting': 'The engine stopped unexpectedly — restarting it…',
  'pub.state.filled': 'Filled in',
  'ce.selected': 'selected',
  'project.noPlatforms': 'No platform to post to: choose your platforms in Settings › General first.',
};

type QaKey = keyof typeof qaEn;

export const qaZh: Record<QaKey, string> = {
  'engine.stopped': '引擎停止了',
  'engine.restarting': '引擎意外停止了，正在重启…',
  'pub.state.filled': '已填好',
  'ce.selected': '选中',
  'project.noPlatforms': '还没有要发的平台：先在「设置 › 通用」里选好平台。',
};

export const qaFr: Record<QaKey, string> = {
  'engine.stopped': 'Le moteur s’est arrêté',
  'engine.restarting': 'Le moteur s’est arrêté de façon inattendue — redémarrage…',
  'pub.state.filled': 'Rempli',
  'ce.selected': 'sélectionné',
  'project.noPlatforms': 'Aucune plateforme où publier : choisissez d’abord vos plateformes dans Réglages › Général.',
};
