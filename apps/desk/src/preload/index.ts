// Preload for the desk UI only (platform pages get no preload at all). Exposes a narrow, typed API; every call
// is re-validated in the main process.
import { contextBridge, ipcRenderer, webUtils } from 'electron';
import type { DeskApi } from '../shared/deskApi';

const EVENTS = new Set(['publish:state', 'publish:fillStep', 'engine:status', 'assets:progress', 'update:state', 'history:changed', 'notify:open', 'term:data', 'term:exit', 'ai:routes', 'publish:due', 'publish:posted', 'publish:channels', 'support:problem', 'support:open']);

const call = (channel: string, payload?: unknown) => ipcRenderer.invoke(channel, payload);

const api: DeskApi = {
  engineInfo: () => call('engine:info'),
  restartEngine: () => call('engine:restart'),
  openFile: (kind) => call('dialog:openFile', { kind }),
  openFolder: () => call('dialog:openFolder'),
  openExternal: (url) => call('shell:openExternal', { url }),
  support: {
    env: () => call('support:env'),
    problems: () => call('support:problems'),
    dismiss: (id) => call('support:dismiss', id ? { id } : {}),
    report: (p) => call('support:report', p),
    setAuto: (on) => call('support:setAuto', { on }),
  },
  showItem: (path) => call('shell:showItem', { path }),
  openLogs: () => call('shell:openLogs'),
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
  usage: {
    status: () => call('usage:status'),
    track: (ev, n) => call('usage:track', n ? { ev, n } : { ev }),
    resetId: () => call('usage:resetId'),
    deleteData: () => call('usage:delete'),
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
    channels: () => call('publish:channels'),
    updateChannel: (adapterId, account, patch) => call('publish:updateChannel', { adapterId, account, ...patch }),
    removeAccount: (adapterId, account, signOut) => call('publish:removeAccount', { adapterId, account, signOut }),
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
    due: () => call('publish:due'),
    fillPost: (postId, account) => call('publish:fillPost', account ? { postId, account } : { postId }),
    capture: () => call('publish:capture'),
    api: {
      status: () => call('publish:apiStatus'),
      setClient: (clientId, clientSecret) => call('publish:apiClient', { id: 'youtube', clientId, clientSecret }),
      connect: () => call('publish:apiConnect', { id: 'youtube' }),
      disconnect: (forgetClient) => call('publish:apiDisconnect', forgetClient ? { id: 'youtube', forgetClient } : { id: 'youtube' }),
      setAuto: (auto) => call('publish:apiAuto', { id: 'youtube', auto }),
    },
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
    get: () => call('update:get'),
    check: () => call('update:check'),
    install: () => call('update:install'),
  },
  watchHistory: (roots) => call('history:watch', { roots }),
  grantAccess: (paths) => call('access:grant', { paths }),
  rec: {
    status: () => call('rec:status'),
    ask: (kind) => call('rec:ask', { kind }),
    openPrivacy: (pane) => call('rec:openPrivacy', { pane }),
    begin: (req) => call('rec:begin', req),
    chunk: (req) => call('rec:chunk', req),
    mark: (req) => call('rec:mark', req),
    end: (sessionId, secs) => call('rec:end', secs === undefined ? { sessionId } : { sessionId, secs }),
    list: (group) => call('rec:list', { group }),
    recover: () => call('rec:recover'),
    discard: (sessionId) => call('rec:discard', { sessionId }),
    screens: () => call('rec:screens'),
    screenPick: (id) => call('rec:screenPick', { id }),
  },
  ai: {
    status: (opts) => call('ai:status', opts ?? {}),
    test: (provider) => call('ai:test', { provider }),
    terminal: (req) => call('ai:terminal', req),
    input: (id, data) => call('term:input', { id, data }),
    resize: (id, cols, rows) => call('term:resize', { id, cols, rows }),
    kill: (id) => call('term:kill', { id }),
    routes: () => call('ai:routes'),
    setRoutes: (routes) => call('ai:setRoutes', { routes }),
  },
  confirmCleanup: (batchId) => call('cleanup:confirm', { batchId }),
  mediaUrl: (p) => `vsmedia://local/${encodeURIComponent(p)}`,
};

contextBridge.exposeInMainWorld('desk', api);
