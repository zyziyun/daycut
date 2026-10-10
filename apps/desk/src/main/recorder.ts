// Create recorder (main side): camera / mic / screen permission policy and crash-safe recording sessions.
//
// Sessions live in $VSTUDIO_HOME/recordings/<yyyymmdd-hhmmss>-<slug>/ (the engine's `vstudio.create record ingest`
// reads them): session.json, <track>.webm (1 s chunks appended as they arrive, fsync every 5 s), takes.json (line /
// retake marks), recording.lock while live (left behind = the app quit mid-take; the engine remuxes on recover).
// Permissions: deny by default stays; 'media' (video/audio only) is allowed for the app's own window and origin
// while the Create flag is on. Screen capture uses the system picker (macOS 15+), also only with the flag on.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { shell, systemPreferences, type IpcMainInvokeEvent, type Session, type WebContents } from 'electron';
import type { IpcChannel, IpcPayload } from '../shared/ipc';
import { allowMedia, REC_TRACKS, type RecTrack } from '../shared/recIpc';

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
    for (const f of Object.values(s.fds)) {
      if (f === undefined) continue;
      fs.fsyncSync(f);
      fs.closeSync(f);
    }
    const sessFile = path.join(s.dir, 'session.json');
    const sess = JSON.parse(fs.readFileSync(sessFile, 'utf8'));
    for (const t of REC_TRACKS) if (sess.tracks?.[t]) sess.tracks[t].start_ms = s.start[t] ?? null;
    sess.ended = new Date().toISOString();
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

/** Screen sharing has a picker: the macOS system picker (15+, Darwin 24); tests share the app's own window. */
export function screenPickerAvailable(fakeMedia: boolean, platform = process.platform, release = os.release()): boolean {
  return fakeMedia || (platform === 'darwin' && Number(release.split('.')[0]) >= 24);
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
  root?: string;
}

export function registerRecorderIpc(handle: Handle, deps: RecorderDeps): Recorder {
  const rec = new Recorder(deps.root ?? recordingsRoot());
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
    return { camera: status('camera'), microphone: status('microphone'), screen: status('screen'), platform: process.platform, release: os.release(), screenPicker: screenPickerAvailable(deps.fakeMedia) };
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
  handle('rec:discard', async (p) => (gate(), rec.discard(p, (d) => shell.trashItem(d))));
  return rec;
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
