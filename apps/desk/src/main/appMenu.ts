// Application menu + About panel, always labelled "Daycut" (the internal app name may still be the legacy one, see
// identity.ts, so no role label is left to Electron's defaults). Rebuilt when the UI language changes.
import fs from 'node:fs';
import path from 'node:path';
import { app, dialog, Menu, shell, type BrowserWindow, type MenuItemConstructorOptions } from 'electron';
import { APP_NAME, APP_NAME_ZH, ENGINE_REPO_URL } from './identity';

type Lang = 'en' | 'zh-CN';

const L = {
  en: {
    about: `About ${APP_NAME}`,
    hide: `Hide ${APP_NAME}`,
    hideOthers: 'Hide Others',
    showAll: 'Show All',
    quit: `Quit ${APP_NAME}`,
    file: 'File',
    edit: 'Edit',
    view: 'View',
    window: 'Window',
    help: 'Help',
    licences: 'Third-party Licences',
    engine: 'video-studio Engine on GitHub',
    builtOn: 'Built on the open-source video-studio engine.',
    version: 'Version',
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
    about: `关于 ${APP_NAME_ZH} ${APP_NAME}`,
    hide: `隐藏 ${APP_NAME_ZH} ${APP_NAME}`,
    hideOthers: '隐藏其他',
    showAll: '全部显示',
    quit: `退出 ${APP_NAME_ZH} ${APP_NAME}`,
    file: '文件',
    edit: '编辑',
    view: '显示',
    window: '窗口',
    help: '帮助',
    licences: '第三方许可',
    engine: 'GitHub 上的 video-studio 引擎',
    builtOn: '基于开源的 video-studio 引擎。',
    version: '版本',
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

export function aboutCredits(lang: Lang): string {
  const chromium = process.versions.chrome.split('.')[0];
  return [
    L[lang].builtOn,
    ENGINE_REPO_URL.replace('https://', ''),
    '',
    `Electron ${process.versions.electron} · Chromium ${chromium} · Node.js ${process.versions.node.split('.')[0]}`,
    lang === 'en' ? 'Licences: Help → Third-party Licences' : '开源许可：帮助 → 第三方许可',
  ].join('\n');
}

function setAbout(d: MenuDeps) {
  app.setAboutPanelOptions({
    applicationName: d.lang === 'en' ? APP_NAME : `${APP_NAME_ZH} ${APP_NAME}`,
    applicationVersion: app.getVersion(),
    version: '', // no "(build)" suffix: CFBundleVersion repeats the version
    copyright: 'Copyright © 2026 zyziyun',
    credits: aboutCredits(d.lang),
    website: ENGINE_REPO_URL,
    ...(d.iconPath && process.platform === 'linux' ? { iconPath: d.iconPath } : {}),
  });
}

/** Windows has no native About panel: a message box with the same content. */
function showAbout(d: MenuDeps) {
  if (process.platform !== 'win32') return app.showAboutPanel();
  const w = d.win();
  const opts = {
    type: 'none' as const,
    title: L[d.lang].about,
    message: `${d.lang === 'en' ? APP_NAME : `${APP_NAME_ZH} ${APP_NAME}`}`,
    detail: `${L[d.lang].version} ${app.getVersion()}\n\n${aboutCredits(d.lang).split('\n').slice(0, -1).join('\n')}\n\nCopyright © 2026 zyziyun`,
    buttons: ['OK', L[d.lang].licences],
    defaultId: 0,
    cancelId: 0,
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
  const t = L[d.lang];
  setAbout(d);
  const mac = process.platform === 'darwin';
  const dev = !app.isPackaged;
  const help: MenuItemConstructorOptions = {
    label: t.help,
    role: 'help',
    submenu: [
      ...(mac ? [] : [{ label: t.about, click: () => showAbout(d) }, { type: 'separator' as const }]),
      { label: t.licences, click: () => openLicences(d), enabled: Boolean(licencesFile(d.res)) },
      { label: t.engine, click: () => void shell.openExternal(ENGINE_REPO_URL) },
    ],
  };
  const template: MenuItemConstructorOptions[] = [
    ...(mac
      ? [
          {
            label: APP_NAME,
            submenu: [
              { label: t.about, click: () => showAbout(d) },
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
