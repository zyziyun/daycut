// About panel + its Help-menu entries. The main process (src/main/appMenu.ts) formats these through aboutStrings()
// in the active UI language; en / zh-CN are also merged into the renderer locales. fr is ready for when the French
// UI locale is registered (main falls back to en for any language it does not have).
import { formatMessage } from '../icu';

export const aboutEn = {
  'about.menu': 'About {app}',
  'about.heading': '{app} · Version {version}',
  'about.openSource': 'Open source: {url}',
  'about.runtime': 'Electron {electron} · Chromium {chromium} · Node.js {node}',
  'about.licences': 'Third-party Licences',
  'about.licencesHint': 'Licences: Help → Third-party Licences',
  'about.repo': '{app} on GitHub',
  'about.copyright': 'Copyright © {year} zyziyun',
};

type AboutKey = keyof typeof aboutEn;

export const aboutZh: Record<AboutKey, string> = {
  'about.menu': '关于 {app}',
  'about.heading': '{app} · 版本 {version}',
  'about.openSource': '开源地址：{url}',
  'about.runtime': 'Electron {electron} · Chromium {chromium} · Node.js {node}',
  'about.licences': '第三方许可',
  'about.licencesHint': '开源许可：帮助 → 第三方许可',
  'about.repo': 'GitHub 上的 {app}',
  'about.copyright': '版权所有 © {year} zyziyun',
};

export const aboutFr: Record<AboutKey, string> = {
  'about.menu': 'À propos de {app}',
  'about.heading': '{app} · Version {version}',
  'about.openSource': 'Open source : {url}',
  'about.runtime': 'Electron {electron} · Chromium {chromium} · Node.js {node}',
  'about.licences': 'Licences tierces',
  'about.licencesHint': 'Licences : Aide → Licences tierces',
  'about.repo': '{app} sur GitHub',
  'about.copyright': 'Copyright © {year} zyziyun',
};

export interface AboutInfo {
  /** display name: "Daycut" (en / fr) or "日剪 Daycut" (zh) */
  app: string;
  version: string;
  url: string;
  year: number;
  versions: { electron: string; chrome: string; node: string };
}

export type AboutStrings = Record<AboutKey, string>;

/** Every About string in `lang` ('en', 'zh-CN' / 'zh…', 'fr…'; anything else is en), placeholders filled. */
export function aboutStrings(lang: string, info: AboutInfo): AboutStrings {
  const [table, intl] = lang.startsWith('zh') ? [aboutZh, 'zh-CN'] : lang.startsWith('fr') ? [aboutFr, 'fr'] : [aboutEn, 'en'];
  const vars = {
    app: info.app,
    version: info.version,
    url: info.url.replace(/^https?:\/\//, ''),
    year: String(info.year),
    electron: info.versions.electron,
    chromium: info.versions.chrome.split('.')[0],
    node: info.versions.node.split('.')[0],
  };
  return Object.fromEntries((Object.keys(aboutEn) as AboutKey[]).map((k) => [k, formatMessage(table[k], intl, vars)])) as AboutStrings;
}
