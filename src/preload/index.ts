// Preload for the desk UI only (platform pages get no preload at all). Exposes a narrow, typed API; every call
// is re-validated in the main process.
import { contextBridge, ipcRenderer, webUtils } from 'electron';
import type { DeskApi } from '../shared/deskApi';

const EVENTS = new Set(['publish:state', 'publish:fillStep', 'engine:status', 'assets:progress', 'update:state', 'history:changed', 'notify:open']);

const call = (channel: string, payload?: unknown) => ipcRenderer.invoke(channel, payload);

const api: DeskApi = {
  engineInfo: () => call('engine:info'),
  restartEngine: () => call('engine:restart'),
  openFile: (kind) => call('dialog:openFile', { kind }),
  openFolder: () => call('dialog:openFolder'),
  openExternal: (url) => call('shell:openExternal', { url }),
  showItem: (path) => call('shell:showItem', { path }),
  copyText: (text) => call('clipboard:write', { text }),
  getSettings: () => call('settings:get'),
  setSettings: (patch) => call('settings:set', patch),
  openFiles: (kind) => call('dialog:openFiles', { kind }),
  pathForFile: (file) => {
    try {
      return webUtils.getPathForFile(file);
    } catch {
      return '';
    }
  },
  notify: (title, body, route) => call('notify:show', route ? { title, body, route } : { title, body }),
  saveText: (defaultName, text) => call('file:saveText', { defaultName, text }),
  firstRun: {
    complete: (defaultPlatforms, skipped) => call('firstRun:complete', skipped === undefined ? { defaultPlatforms } : { defaultPlatforms, skipped }),
  },
  secrets: {
    status: () => call('secrets:status'),
    set: (name, value) => call('secrets:set', { name, value }),
    clear: (name) => call('secrets:clear', { name }),
  },
  persona: {
    import: (path) => call('persona:import', { path }),
    clear: () => call('persona:clear'),
  },
  publish: {
    adapters: () => call('publish:adapters'),
    accounts: () => call('publish:accounts'),
    addAccount: (adapterId, account) => call('publish:addAccount', { adapterId, account }),
    open: (adapterId, account, page) => call('publish:open', { adapterId, account, page }),
    setBounds: (b) => call('publish:setBounds', b),
    hide: () => call('publish:hide'),
    navigate: (action) => call('publish:navigate', { action }),
    confirmPackage: (batchId, code) => call('publish:confirmPackage', { batchId, code }),
    confirmations: (batchId) => call('publish:confirmations', { batchId }),
    fill: (req) => call('publish:fill', req),
    markPosted: (req) => call('publish:markPosted', req),
    caption: (batchId, job, platform) => call('publish:caption', { batchId, job, platform }),
    postedLog: (batchId) => call('publish:postedLog', { batchId }),
  },
  on: (event, cb) => {
    if (!EVENTS.has(event)) throw new Error(`unknown event ${event}`);
    const fn = (_e: unknown, data: unknown) => cb(data);
    ipcRenderer.on(event, fn);
    return () => ipcRenderer.removeListener(event, fn);
  },
  assets: {
    status: () => call('assets:status'),
    install: (ids) => call('assets:install', { ids }),
    cancel: (id) => call('assets:cancel', id ? { id } : undefined),
  },
  update: {
    check: () => call('update:check'),
    install: () => call('update:install'),
  },
  watchHistory: (roots) => call('history:watch', { roots }),
  confirmCleanup: (batchId) => call('cleanup:confirm', { batchId }),
  mediaUrl: (p) => `vsmedia://local/${encodeURIComponent(p)}`,
};

contextBridge.exposeInMainWorld('desk', api);
