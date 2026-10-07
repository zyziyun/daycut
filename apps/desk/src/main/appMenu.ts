// Application menu + About panel, always labelled "Reelfold" (every label is explicit, none is left to Electron's
// role defaults). About strings come from the i18n adapter (en / zh-CN / fr). Rebuilt when the UI language changes.
import fs from 'node:fs';
import path from 'node:path';
import { app, dialog, Menu, nativeImage, shell, type BrowserWindow, type MenuItemConstructorOptions } from 'electron';
import { aboutStrings, type AboutStrings } from '../renderer/src/i18n/locales/about';
import { APP_NAME, APP_NAME_ZH, REPO_URL } from './identity';

type Lang = 'en' | 'zh-CN' | 'fr';

const L = {
  en: {
    hide: `Hide ${APP_NAME}`,
    hideOthers: 'Hide Others',
    showAll: 'Show All',
    quit: `Quit ${APP_NAME}`,
    file: 'File',
    edit: 'Edit',
    view: 'View',
    window: 'Window',
    help: 'Help',
    services: 'Services',
    undo: 'Undo',
    redo: 'Redo',
    cut: 'Cut',
    copy: 'Copy',
    paste: 'Paste',
    pasteMatch: 'Paste and Match Style',
    del: 'Delete',
    selectAll: 'Select All',
    actualSize: 'Actual Size',
    zoomIn: 'Zoom In',
    zoomOut: 'Zoom Out',
    fullScreen: 'Toggle Full Screen',
    minimize: 'Minimize',
    zoom: 'Zoom',
    front: 'Bring All to Front',
    close: 'Close Window',
  },
  'zh-CN': {
    hide: `隐藏 ${APP_NAME_ZH} ${APP_NAME}`,
    hideOthers: '隐藏其他',
    showAll: '全部显示',
    quit: `退出 ${APP_NAME_ZH} ${APP_NAME}`,
    file: '文件',
    edit: '编辑',
    view: '显示',
    window: '窗口',
    help: '帮助',
    services: '服务',
    undo: '撤销',
    redo: '重做',
    cut: '剪切',
    copy: '拷贝',
    paste: '粘贴',
    pasteMatch: '粘贴并匹配样式',
    del: '删除',
    selectAll: '全选',
    actualSize: '实际大小',
    zoomIn: '放大',
    zoomOut: '缩小',
    fullScreen: '切换全屏',
    minimize: '最小化',
    zoom: '缩放',
    front: '全部置于前台',
    close: '关闭窗口',
  },
  fr: {
    hide: `Masquer ${APP_NAME}`,
    hideOthers: 'Masquer les autres',
    showAll: 'Tout afficher',
    quit: `Quitter ${APP_NAME}`,
    file: 'Fichier',
    edit: 'Édition',
    view: 'Présentation',
    window: 'Fenêtre',
    help: 'Aide',
    services: 'Services',
    undo: 'Annuler',
    redo: 'Rétablir',
    cut: 'Couper',
    copy: 'Copier',
    paste: 'Coller',
    pasteMatch: 'Coller et adapter le style',
    del: 'Supprimer',
    selectAll: 'Tout sélectionner',
    actualSize: 'Taille réelle',
    zoomIn: 'Zoom avant',
    zoomOut: 'Zoom arrière',
    fullScreen: 'Activer/désactiver le plein écran',
    minimize: 'Placer dans le Dock',
    zoom: 'Réduire/agrandir',
    front: 'Tout ramener au premier plan',
    close: 'Fermer la fenêtre',
  },
} satisfies Record<Lang, Record<string, string>>;

export interface MenuDeps {
  lang: Lang;
  /** resources root (process.resourcesPath when packaged, the repo in development) */
  res: string;
  win: () => BrowserWindow | null;
  iconPath?: string;
}

function licencesFile(res: string): string | null {
  const f = path.join(res, 'THIRD_PARTY_LICENSES.md');
  return fs.existsSync(f) ? f : null;
}

const COPYRIGHT_YEAR = 2026; // electron-builder.config.cjs: copyright

/** "Reelfold" (en / fr) or "千剪 Reelfold" (zh): the name the About panel shows. */
export function displayName(lang: string): string {
  return lang.startsWith('zh') ? `${APP_NAME_ZH} ${APP_NAME}` : APP_NAME;
}

/** About strings for the UI language, from the i18n adapter (src/renderer/src/i18n/locales/about.ts). */
export function aboutText(lang: string, version = app.getVersion(), versions: { electron: string; chrome: string; node: string } = process.versions): AboutStrings {
  return aboutStrings(lang, { app: displayName(lang), version, url: REPO_URL, year: COPYRIGHT_YEAR, versions });
}

/** The panel body under the name / version: open-source repo, runtime versions, where the licences are. */
export function aboutCredits(lang: string, version = app.getVersion(), versions?: { electron: string; chrome: string; node: string }): string {
  const a = aboutText(lang, version, versions);
  return [a['about.openSource'], a['about.platforms'], '', a['about.runtime'], a['about.licencesHint']].join('\n');
}

function setAbout(d: MenuDeps) {
  const a = aboutText(d.lang);
  app.setAboutPanelOptions({
    applicationName: displayName(d.lang),
    applicationVersion: app.getVersion(), // macOS / Linux show it as "Version x.y.z" under the name
    version: '', // no "(build)" suffix: CFBundleVersion repeats the version
    copyright: a['about.copyright'],
    credits: aboutCredits(d.lang),
    website: REPO_URL,
    // macOS takes the icon from the bundle (packaged: icon.icns; dev: the Reelfold.app copy + app.dock.setIcon)
    ...(d.iconPath && process.platform !== 'darwin' ? { iconPath: d.iconPath } : {}),
  });
}

/** Windows: a message box with the same content (Reelfold icon, "Reelfold · Version x.y.z", repo, versions, licences). */
function showAbout(d: MenuDeps) {
  if (process.platform !== 'win32') return app.showAboutPanel();
  const a = aboutText(d.lang);
  const w = d.win();
  const opts = {
    type: 'none' as const,
    title: a['about.menu'],
    message: a['about.heading'],
    detail: [a['about.openSource'], '', a['about.runtime'], '', a['about.copyright']].join('\n'),
    buttons: ['OK', a['about.licences']],
    defaultId: 0,
    cancelId: 0,
    ...(d.iconPath ? { icon: nativeImage.createFromPath(d.iconPath) } : {}),
  };
  void (w ? dialog.showMessageBox(w, opts) : dialog.showMessageBox(opts)).then((r) => {
    if (r.response === 1) openLicences(d);
  });
}

function openLicences(d: MenuDeps) {
  const f = licencesFile(d.res);
  if (f) void shell.openPath(f);
}

export function installAppMenu(d: MenuDeps) {
  const t = L[d.lang] ?? L.en;
  const a = aboutText(d.lang);
  setAbout(d);
  const mac = process.platform === 'darwin';
  const dev = !app.isPackaged;
  const help: MenuItemConstructorOptions = {
    label: t.help,
    role: 'help',
    submenu: [
      ...(mac ? [] : [{ label: a['about.menu'], click: () => showAbout(d) }, { type: 'separator' as const }]),
      { label: a['about.licences'], click: () => openLicences(d), enabled: Boolean(licencesFile(d.res)) },
      { label: a['about.repo'], click: () => void shell.openExternal(REPO_URL) },
    ],
  };
  const template: MenuItemConstructorOptions[] = [
    ...(mac
      ? [
          {
            label: APP_NAME,
            submenu: [
              { label: a['about.menu'], click: () => showAbout(d) },
              { type: 'separator' },
              { label: t.services, role: 'services', submenu: [] },
              { type: 'separator' },
              { label: t.hide, role: 'hide' },
              { label: t.hideOthers, role: 'hideOthers' },
              { label: t.showAll, role: 'unhide' },
              { type: 'separator' },
              { label: t.quit, role: 'quit' },
            ],
          } satisfies MenuItemConstructorOptions,
        ]
      : [{ label: t.file, submenu: [{ label: t.quit, role: 'quit' }] } satisfies MenuItemConstructorOptions]),
    {
      label: t.edit,
      submenu: [
        { label: t.undo, role: 'undo' },
        { label: t.redo, role: 'redo' },
        { type: 'separator' },
        { label: t.cut, role: 'cut' },
        { label: t.copy, role: 'copy' },
        { label: t.paste, role: 'paste' },
        ...(mac ? [{ label: t.pasteMatch, role: 'pasteAndMatchStyle' as const }] : []),
        { label: t.del, role: 'delete' },
        { label: t.selectAll, role: 'selectAll' },
      ],
    },
    {
      label: t.view,
      submenu: [
        ...(dev ? ([{ role: 'reload' }, { role: 'forceReload' }, { role: 'toggleDevTools' }, { type: 'separator' }] as MenuItemConstructorOptions[]) : []),
        { label: t.actualSize, role: 'resetZoom' },
        { label: t.zoomIn, role: 'zoomIn' },
        { label: t.zoomOut, role: 'zoomOut' },
        { type: 'separator' },
        { label: t.fullScreen, role: 'togglefullscreen' },
      ],
    },
    {
      label: t.window,
      role: 'window',
      submenu: [
        { label: t.minimize, role: 'minimize' },
        { label: t.zoom, role: 'zoom' },
        ...(mac ? ([{ type: 'separator' }, { label: t.front, role: 'front' }] as MenuItemConstructorOptions[]) : [{ label: t.close, role: 'close' as const }]),
      ],
    },
    help,
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
