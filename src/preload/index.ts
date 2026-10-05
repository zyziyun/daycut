// Preload for the desk UI only (platform pages get no preload at all). Exposes a narrow, typed API; every call
// is re-validated in the main process.
import { contextBridge, ipcRenderer } from 'electron';
import type { DeskApi } from '../shared/deskApi';

const EVENTS = new Set(['publish:state', 'publish:fillStep', 'engine:status']);

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
  mediaUrl: (p) => `vsmedia://local/${encodeURIComponent(p)}`,
};

contextBridge.exposeInMainWorld('desk', api);
