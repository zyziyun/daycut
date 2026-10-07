// "Open at login" + the menu-bar (tray) presence that goes with it: Reelfold starts hidden at login so the publish
// loop's clock runs (scheduled posts get their "Time to post" notification), and the menu-bar icon lists what is due.
import { app, Menu, nativeImage, Tray } from 'electron';
import type { CalendarPost } from '../shared/v04';

export const HIDDEN_ARG = '--hidden';

/** Started by the OS at login (hidden): no window until she opens one. */
export function startedHidden(argv = process.argv): boolean {
  if (argv.includes(HIDDEN_ARG)) return true;
  try {
    return process.platform === 'darwin' && app.getLoginItemSettings().wasOpenedAtLogin === true;
  } catch {
    return false;
  }
}

export function applyLoginItem(on: boolean) {
  if (!app.isPackaged) return; // a dev build would register the bare Electron binary
  app.setLoginItemSettings({ openAtLogin: on, args: on ? [HIDDEN_ARG] : [] });
}

export interface TrayCopy {
  open: string;
  quit: string;
  nothingDue: string;
  due: (n: number) => string;
  item: (p: CalendarPost) => string;
}

export class AppTray {
  private tray: Tray | null = null;
  private due: CalendarPost[] = [];

  constructor(
    private icon: string | undefined,
    private copy: () => TrayCopy,
    private actions: { open: (route?: string) => void; quit: () => void },
  ) {}

  set(on: boolean) {
    if (on && !this.tray) {
      let img = this.icon ? nativeImage.createFromPath(this.icon) : nativeImage.createEmpty();
      if (!img.isEmpty()) img = img.resize({ width: 18, height: 18 });
      this.tray = new Tray(img);
      this.tray.setToolTip(app.getName());
      if (img.isEmpty()) this.tray.setTitle?.(app.getName());
      this.tray.on('click', () => this.tray?.popUpContextMenu());
      this.render();
    } else if (!on && this.tray) {
      this.tray.destroy();
      this.tray = null;
    }
  }

  get active() {
    return this.tray !== null;
  }

  update(due: CalendarPost[]) {
    this.due = due;
    this.render();
  }

  private render() {
    if (!this.tray) return;
    const c = this.copy();
    const items: Electron.MenuItemConstructorOptions[] = [];
    items.push({ label: this.due.length ? c.due(this.due.length) : c.nothingDue, enabled: false });
    for (const p of this.due.slice(0, 8)) items.push({ label: c.item(p), click: () => this.actions.open(`#/publish/post/${p.id}`) });
    items.push({ type: 'separator' }, { label: c.open, click: () => this.actions.open() }, { label: c.quit, click: () => this.actions.quit() });
    this.tray.setContextMenu(Menu.buildFromTemplate(items));
    if (process.platform === 'darwin') this.tray.setTitle(this.due.length ? String(this.due.length) : '');
  }
}
