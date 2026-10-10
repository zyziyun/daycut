// Create recorder (main side): camera / mic / screen permission policy and crash-safe recording sessions.
//
// Sessions live in $VSTUDIO_HOME/recordings/<yyyymmdd-hhmmss>-<slug>/ (the engine's `vstudio.create record ingest`
// reads them): session.json, <track>.webm (1 s chunks appended as they arrive, fsync every 5 s), takes.json (line /
// retake marks), recording.lock while live (left behind = the app quit mid-take; the engine remuxes on recover).
// Permissions: deny by default stays; 'media' (video/audio only) is allowed for the app's own window and origin
// while the Create flag is on. Screen capture: the app's own picker (rec:screens lists screens / windows through
// desktopCapturer, she picks one, rec:screenPick arms it) and the display-media handler shares exactly that source,
// once. Not the macOS system picker (useSystemPicker): Chromium gives up on its video source 10 s after the picker
// opens (AbortError "Timeout starting video source") while the picker stays on screen, so a slower pick did nothing.
// macOS needs Screen Recording access for desktopCapturer: the first rec:screens asks (the OS prompt adds Reelfold to
// System Settings > Privacy & Security > Screen & System Audio Recording); while it is off she gets 'denied' and the
// page explains how to turn it on, with a button that opens that pane.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { desktopCapturer, shell, systemPreferences, type DesktopCapturerSource, type IpcMainInvokeEvent, type Session, type WebContents } from 'electron';
import type { IpcChannel, IpcPayload } from '../shared/ipc';
import { allowMedia, REC_TRACKS, type RecTrack, type ScreenSource, type ScreensReply, type TakeInfo } from '../shared/recIpc';

type Handle = <C extends IpcChannel>(channel: C, fn: (p: IpcPayload<C>, e: IpcMainInvokeEvent) => unknown) => void;

export function recordingsRoot(env: NodeJS.ProcessEnv = process.env): string {
  const home = env.VSTUDIO_HOME ? path.resolve(env.VSTUDIO_HOME.replace(/^~(?=$|\/)/, os.homedir())) : path.join(os.homedir(), '.config', 'vstudio');
  return path.join(home, 'recordings');
}

interface Live {
  dir: string;
  fds: Partial<Record<RecTrack, number>>;
  seq: Partial<Record<RecTrack, number>>;
  start: Partial<Record<RecTrack, number>>;
  lastSync: number;
  marks: { t: number; kind: string; line: number }[];
}

function stamp(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function writeJson(file: string, obj: unknown) {
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 1));
  fs.renameSync(tmp, file);
}

export class Recorder {
  private live = new Map<string, Live>();
  constructor(private root: string) {}

  begin(p: IpcPayload<'rec:begin'>) {
    fs.mkdirSync(this.root, { recursive: true });
    let id = `${stamp()}-${p.slug}`;
    for (let n = 2; fs.existsSync(path.join(this.root, id)); n++) id = `${stamp()}-${p.slug}-${n}`.slice(0, 56);
    const dir = path.join(this.root, id);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'recording.lock'), String(process.pid));
    const tracks: Record<string, { file: string; mime?: string }> = {};
    for (const t of p.tracks) tracks[t] = { file: `${t}.webm`, mime: p.mime?.[t] };
    writeJson(path.join(dir, 'session.json'), {
      id,
      slug: p.slug,
      title: p.title ?? p.slug,
      created: new Date().toISOString(),
      script: p.script,
      tracks,
      series: p.series,
      episode: p.episode,
      shot: p.shot,
      studio: p.studio ?? true,
      ...(p.group ? { group: p.group } : {}),
      ...(p.pickup ? { pickup: true } : {}),
    });
    writeJson(path.join(dir, 'takes.json'), []);
    this.live.set(id, { dir, fds: {}, seq: {}, start: {}, lastSync: Date.now(), marks: [] });
    return { sessionId: id, dir };
  }

  private need(id: string): Live {
    const s = this.live.get(id);
    if (!s) throw new Error('rec.no-session');
    return s;
  }

  chunk(p: IpcPayload<'rec:chunk'>) {
    const s = this.need(p.sessionId);
    const want = s.seq[p.track] ?? 0;
    if (p.seq !== want) throw new Error(`rec.gap: ${p.track} expected ${want}, got ${p.seq}`);
    let fd = s.fds[p.track];
    if (fd === undefined) {
      fd = fs.openSync(path.join(s.dir, `${p.track}.webm`), 'a');
      s.fds[p.track] = fd;
      s.start[p.track] = p.startMs ?? Date.now();
    }
    fs.writeSync(fd, p.data);
    s.seq[p.track] = want + 1;
    if (Date.now() - s.lastSync > 5000) {
      for (const f of Object.values(s.fds)) if (f !== undefined) fs.fsyncSync(f);
      s.lastSync = Date.now();
    }
    return { ok: true, seq: p.seq };
  }

  mark(p: IpcPayload<'rec:mark'>) {
    const s = this.need(p.sessionId);
    s.marks.push({ t: p.t, kind: p.kind, line: p.line });
    writeJson(path.join(s.dir, 'takes.json'), s.marks);
    return { ok: true, n: s.marks.length };
  }

  end(p: IpcPayload<'rec:end'>) {
    const s = this.need(p.sessionId);
    const secs = p.secs;
    for (const f of Object.values(s.fds)) {
      if (f === undefined) continue;
      fs.fsyncSync(f);
      fs.closeSync(f);
    }
    const sessFile = path.join(s.dir, 'session.json');
    const sess = JSON.parse(fs.readFileSync(sessFile, 'utf8'));
    for (const t of REC_TRACKS) if (sess.tracks?.[t]) sess.tracks[t].start_ms = s.start[t] ?? null;
    sess.ended = new Date().toISOString();
    if (typeof secs === 'number') sess.secs = Math.round(secs * 10) / 10;
    writeJson(sessFile, sess);
    fs.rmSync(path.join(s.dir, 'recording.lock'), { force: true });
    this.live.delete(p.sessionId);
    const tracks = REC_TRACKS.filter((t) => fs.existsSync(path.join(s.dir, `${t}.webm`)));
    return { dir: s.dir, tracks, marks: s.marks.length };
  }

  /** A finished take she deleted -> the Trash (the folder stays recoverable). Never a live one, never outside root. */
  async discard(p: IpcPayload<'rec:discard'>, trash: (dir: string) => Promise<void>) {
    if (this.live.has(p.sessionId)) throw new Error('rec.live');
    const dir = path.join(this.root, p.sessionId);
    if (path.dirname(dir) !== path.resolve(this.root) || !fs.existsSync(path.join(dir, 'session.json'))) throw new Error('rec.no-session');
    await trash(dir);
    return { ok: true };
  }

  /** The finished takes of one Record visit (not pickups), newest first. */
  list(group: string): TakeInfo[] {
    if (!fs.existsSync(this.root)) return [];
    const out: TakeInfo[] = [];
    for (const id of fs.readdirSync(this.root)) {
      const dir = path.join(this.root, id);
      if (this.live.has(id) || fs.existsSync(path.join(dir, 'recording.lock'))) continue;
      let sess: { group?: string; pickup?: boolean; created?: string; ended?: string; secs?: number; script?: unknown[] } | null;
      try {
        sess = JSON.parse(fs.readFileSync(path.join(dir, 'session.json'), 'utf8'));
      } catch {
        continue;
      }
      if (!sess || sess.group !== group || sess.pickup || !sess.ended) continue;
      const secs = typeof sess.secs === 'number' ? sess.secs : sess.created ? Math.max(0, (Date.parse(sess.ended) - Date.parse(sess.created)) / 1000) : 0;
      let marks: { kind?: string; line?: number }[];
      try {
        marks = JSON.parse(fs.readFileSync(path.join(dir, 'takes.json'), 'utf8'));
      } catch {
        marks = [];
      }
      const total = Array.isArray(sess.script) ? sess.script.length : 0;
      const reached = marks.reduce((m, x) => Math.max(m, typeof x.line === 'number' ? x.line + 1 : 0), 0);
      const retakes = new Set(marks.filter((x) => x.kind === 'retake').map((x) => x.line)).size;
      out.push({ id, dir, created: sess.created ?? null, secs, edited: fs.existsSync(path.join(dir, 'final', 'recording.mp4')), lines: Math.min(total, reached), total, retakes });
    }
    return out.sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''));
  }

  /** Sessions with a lock no live recording owns (the app quit mid-take). */
  recover() {
    if (!fs.existsSync(this.root)) return [];
    return fs
      .readdirSync(this.root)
      .filter((d) => !this.live.has(d) && fs.existsSync(path.join(this.root, d, 'recording.lock')))
      .map((d) => ({ id: d, dir: path.join(this.root, d) }));
  }

  /** App quit: close what is open; the lock stays so the next start offers recovery. */
  closeAll() {
    for (const s of this.live.values()) for (const f of Object.values(s.fds)) if (f !== undefined) fs.closeSync(f);
    this.live.clear();
  }
}

/** The source she picked in the app's screen picker, handed to the next getDisplayMedia (once, within 30 s). */
export class ScreenPick {
  private armed: { id: string; until: number } | null = null;
  constructor(private ttlMs = 30_000) {}
  arm(id: string, now = Date.now()) {
    this.armed = { id, until: now + this.ttlMs };
  }
  take(now = Date.now()): string | null {
    const a = this.armed;
    this.armed = null;
    return a && now <= a.until ? a.id : null;
  }
}

/** desktopCapturer sources -> what the picker shows: screens first, then windows; never Reelfold's own windows. */
export function toScreenSources(list: Pick<DesktopCapturerSource, 'id' | 'name' | 'thumbnail'>[], own: string[] = []): ScreenSource[] {
  const rows = list
    .filter((s) => !own.includes(s.id))
    .map((s) => ({ id: s.id, name: s.name, kind: (s.id.startsWith('screen:') ? 'screen' : 'window') as ScreenSource['kind'], thumb: s.thumbnail && !s.thumbnail.isEmpty() ? s.thumbnail.toDataURL() : '' }));
  return [...rows.filter((r) => r.kind === 'screen'), ...rows.filter((r) => r.kind === 'window')];
}

/** Screen Recording access as macOS reports it ('granted' elsewhere: Windows / Linux need none). */
export function screenAccess(status: string, platform = process.platform): 'granted' | 'denied' {
  return platform !== 'darwin' || status === 'granted' ? 'granted' : 'denied';
}

const PRIVACY: Record<string, string> = {
  camera: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Camera',
  microphone: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone',
  screen: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
};
/** Windows Settings › Privacy (no per-app screen-capture page there) */
const PRIVACY_WIN: Record<string, string> = {
  camera: 'ms-settings:privacy-webcam',
  microphone: 'ms-settings:privacy-microphone',
};

export interface RecorderDeps {
  flag: () => boolean;
  /** tests (DESK_E2E_FAKE_MEDIA=1): fake devices, report access as granted, never show the OS prompt */
  fakeMedia: boolean;
  /** tests: DESK_E2E_SCREEN=denied (Screen Recording off) */
  fakeScreen?: 'granted' | 'denied';
  /** shared with the display-media handler (installDisplayMedia) */
  pick: ScreenPick;
  /** Reelfold's own windows (never offered in the screen picker) */
  ownSources?: () => string[];
  root?: string;
}

/** The test devices' only screen source: the app's own window (its frame is what the display handler shares). */
export const FAKE_SCREEN_ID = 'window:fake:app';

export function registerRecorderIpc(handle: Handle, deps: RecorderDeps): Recorder {
  const rec = new Recorder(deps.root ?? recordingsRoot());
  const pick = deps.pick;
  const gate = () => {
    if (!deps.flag()) throw new Error('the Create page is off');
  };
  const status = (kind: 'camera' | 'microphone' | 'screen') => {
    if (deps.fakeMedia || process.platform !== 'darwin') return 'granted';
    try {
      return systemPreferences.getMediaAccessStatus(kind);
    } catch {
      return 'unknown';
    }
  };
  handle('rec:status', async () => {
    gate();
    return { camera: status('camera'), microphone: status('microphone'), screen: status('screen'), platform: process.platform, release: os.release() };
  });
  handle('rec:screens', async (): Promise<ScreensReply> => {
    gate();
    if (deps.fakeMedia) {
      return deps.fakeScreen === 'denied' ? { access: 'denied', sources: [] } : { access: 'granted', sources: [{ id: FAKE_SCREEN_ID, name: 'Reelfold', kind: 'window', thumb: '' }] };
    }
    let list: DesktopCapturerSource[] = [];
    let failed = false;
    try {
      // the first call is what makes macOS ask (and list Reelfold under Screen & System Audio Recording)
      list = await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 320, height: 200 }, fetchWindowIcons: false });
    } catch {
      failed = true;
    }
    if (screenAccess(status('screen')) === 'denied' || (failed && process.platform === 'darwin')) return { access: 'denied', sources: [] };
    if (failed) throw new Error('rec.screens-failed');
    return { access: 'granted', sources: toScreenSources(list, deps.ownSources?.() ?? []) };
  });
  handle('rec:screenPick', async (p) => {
    gate();
    pick.arm(p.id);
    return { ok: true };
  });
  handle('rec:ask', async (p) => {
    gate();
    if (deps.fakeMedia || process.platform !== 'darwin') return true;
    return systemPreferences.askForMediaAccess(p.kind);
  });
  handle('rec:openPrivacy', async (p) => {
    gate();
    const url = process.platform === 'darwin' ? PRIVACY[p.pane] : process.platform === 'win32' ? PRIVACY_WIN[p.pane] : undefined;
    if (url) await shell.openExternal(url);
  });
  handle('rec:begin', async (p) => (gate(), rec.begin(p)));
  handle('rec:chunk', async (p) => (gate(), rec.chunk(p)));
  handle('rec:mark', async (p) => (gate(), rec.mark(p)));
  handle('rec:end', async (p) => (gate(), rec.end(p)));
  handle('rec:recover', async () => (gate(), rec.recover()));
  handle('rec:list', async (p) => (gate(), rec.list(p.group)));
  handle('rec:discard', async (p) => (gate(), rec.discard(p, (d) => shell.trashItem(d))));
  return rec;
}

/** getDisplayMedia -> the source she picked (once); nothing without a pick or with Create off. */
export function installDisplayMedia(ses: Session, o: { flag: () => boolean; pick: ScreenPick; fakeMedia: boolean }) {
  ses.setDisplayMediaRequestHandler((req, cb) => {
    const id = o.flag() ? o.pick.take() : null;
    if (!id) return cb({});
    if (o.fakeMedia && id === FAKE_SCREEN_ID) return req.frame ? cb({ video: req.frame }) : cb({});
    desktopCapturer
      .getSources({ types: ['screen', 'window'], thumbnailSize: { width: 0, height: 0 }, fetchWindowIcons: false })
      .then((list) => {
        const src = list.find((s) => s.id === id);
        cb(src ? { video: src } : {});
      })
      .catch(() => cb({}));
  });
}

/** Replace the default session's deny-all permission handlers with deny-all-but-recorder-media. */
export function installMediaPermissions(ses: Session, o: { flag: () => boolean; mainWebContents: () => WebContents | null; isApp: (url: string) => boolean }) {
  ses.setPermissionRequestHandler((wc, permission, cb, details) => {
    const d = details as { mediaTypes?: string[]; requestingUrl?: string };
    cb(
      allowMedia({
        flag: o.flag(),
        fromMainWindow: !!wc && wc === o.mainWebContents(),
        isAppUrl: o.isApp(d.requestingUrl ?? wc?.getURL() ?? ''),
        permission,
        mediaTypes: d.mediaTypes,
      }),
    );
  });
  ses.setPermissionCheckHandler((wc, permission, requestingOrigin, details) => {
    const d = details as { mediaType?: string };
    return allowMedia({
      flag: o.flag(),
      fromMainWindow: !!wc && wc === o.mainWebContents(),
      isAppUrl: o.isApp(requestingOrigin),
      permission,
      mediaTypes: d.mediaType ? [d.mediaType] : [],
    });
  });
}
