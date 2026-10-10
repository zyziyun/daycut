// Copy that names a macOS place (Finder, System Settings, Homebrew, a macOS version) reads from here on Windows and
// Linux instead (i18n/index.ts picks it by platform). Everything else is worded for any computer in the locale files
// themselves. Every locale lists the same keys (tests/unit/i18n.test.ts).
import type { MessageKey } from './en';

type OffMac = Partial<Record<MessageKey, string>>;

export const offMacEn: OffMac = {
  'c.reveal': 'Show in folder',
  'share.reveal': 'Show in folder',
  's2.engine.showInFinder': 'Show in folder',
  'deliver.show': 'Show in folder',
  'history.reveal': 'Show in folder',
  'pub.showFile': 'Show in folder',
  'pub.adapterTodo': 'Assisted fill is not built for this platform yet (TODO). Upload by hand in the built-in browser: "Show in folder" + "Copy caption".',
  'pl.post.cover': 'Show cover in folder',
  'pl.capture.saved': 'Page captured ({n} elements). Shown in its folder.',
  'rec.permOpen': 'Open privacy settings',
  'rec.screenUnavailable': 'Screen sharing isn’t available on this computer yet.',
  'fail.fix.install-ffmpeg': 'Install ffmpeg (from ffmpeg.org, or “winget install ffmpeg” on Windows), then try again.',
};

export const offMacZh: OffMac = {
  'c.reveal': '在文件夹中显示',
  'share.reveal': '在文件夹中显示',
  's2.engine.showInFinder': '在文件夹中显示',
  'deliver.show': '在文件夹中显示',
  'history.reveal': '在文件夹中显示',
  'pub.showFile': '在文件夹中显示',
  'pub.adapterTodo': '这个平台的自动填写还没做（TODO）。可以在内置浏览器里手动上传：「在文件夹中显示」+「复制文案」。',
  'pl.post.cover': '在文件夹中显示封面',
  'pl.capture.saved': '已抓取页面（{n} 个元素），已在文件夹中显示。',
  'rec.permOpen': '打开隐私设置',
  'rec.screenUnavailable': '这台电脑暂时还不能录屏幕。',
  'fail.fix.install-ffmpeg': '安装 ffmpeg（从 ffmpeg.org 下载，Windows 上也可以运行「winget install ffmpeg」），再试一次。',
};

export const offMacFr: OffMac = {
  'c.reveal': 'Afficher dans le dossier',
  'share.reveal': 'Afficher dans le dossier',
  's2.engine.showInFinder': 'Afficher dans le dossier',
  'deliver.show': 'Afficher dans le dossier',
  'history.reveal': 'Afficher dans le dossier',
  'pub.showFile': 'Afficher dans le dossier',
  'pub.adapterTodo': 'Le remplissage assisté n’existe pas encore pour cette plateforme (TODO). Mettez en ligne à la main dans le navigateur intégré : « Afficher dans le dossier » + « Copier la légende ».',
  'pl.post.cover': 'Afficher la couverture dans le dossier',
  'pl.capture.saved': 'Page capturée ({n} éléments). Affichée dans son dossier.',
  'rec.permOpen': 'Ouvrir les paramètres de confidentialité',
  'rec.screenUnavailable': 'Le partage d’écran n’est pas encore disponible sur cet ordinateur.',
  'fail.fix.install-ffmpeg': 'Installez ffmpeg (depuis ffmpeg.org, ou « winget install ffmpeg » sous Windows), puis réessayez.',
};
