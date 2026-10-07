// Strings added by the bug bash (qa/BUGS.md): engine crash / restart, states that showed a raw key, small labels
// that were hard-coded. One file so the big locale files stay untouched apart from the merge line.
export const qaEn = {
  'engine.stopped': 'The engine stopped',
  'engine.restarting': 'The engine stopped unexpectedly — restarting it…',
  'pub.state.filled': 'Filled in',
  'ce.selected': 'selected',
};

type QaKey = keyof typeof qaEn;

export const qaZh: Record<QaKey, string> = {
  'engine.stopped': '引擎停止了',
  'engine.restarting': '引擎意外停止了，正在重启…',
  'pub.state.filled': '已填好',
  'ce.selected': '选中',
};

export const qaFr: Record<QaKey, string> = {
  'engine.stopped': 'Le moteur s’est arrêté',
  'engine.restarting': 'Le moteur s’est arrêté de façon inattendue — redémarrage…',
  'pub.state.filled': 'Rempli',
  'ce.selected': 'sélectionné',
};
