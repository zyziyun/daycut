// An in-app terminal for CLI logins (`claude auth login`, `codex login`): a real PTY through node-pty (optional
// dependency, N-API prebuilds), else `script -q /dev/null <cmd>` on macOS / Linux, else a plain pipe. The OAuth
// browser flow and any code the user pastes happen in this terminal; nothing it shows or receives is logged or stored.
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export interface TermHandlers {
  onData(data: string): void;
  onExit(code: number | null): void;
}

export interface TermSession {
  id: string;
  backend: 'pty' | 'python' | 'script' | 'pipe';
  write(data: string): void;
  resize(cols: number, rows: number): void;
  kill(): void;
}

interface PtyModule {
  spawn(
    file: string,
    args: string[],
    opts: { name: string; cols: number; rows: number; cwd: string; env: Record<string, string> },
  ): {
    onData(cb: (d: string) => void): void;
    onExit(cb: (e: { exitCode: number }) => void): void;
    write(d: string): void;
    resize(c: number, r: number): void;
    kill(): void;
  };
}

let ptyCache: PtyModule | null | undefined;
/** why node-pty was not used last time (diagnostics only; never terminal content) */
export let ptyProblem: string | null = null;
/** node-pty when it loads (DESK_NO_PTY=1 forces the fallback: tests). */
export function loadPty(): PtyModule | null {
  if (ptyCache !== undefined) return ptyCache;
  ptyCache = null;
  if (process.env.DESK_NO_PTY === '1') return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('node-pty') as PtyModule;
    // node-pty 1.1.0 ships spawn-helper without +x (posix_spawnp failed): fix it where the file is writable
    try {
      const dir = path.join(path.dirname(require.resolve('node-pty/package.json')), 'prebuilds', `${process.platform}-${process.arch}`).replace('app.asar', 'app.asar.unpacked');
      const helper = path.join(dir, 'spawn-helper');
      if (fs.existsSync(helper) && !(fs.statSync(helper).mode & 0o111)) fs.chmodSync(helper, 0o755);
    } catch {
      /* read-only bundle: spawn may still work */
    }
    ptyCache = mod;
  } catch (e) {
    ptyCache = null;
    ptyProblem = `load: ${(e as Error).message}`;
  }
  return ptyCache;
}

/** The command a fallback without node-pty runs: `script` gives the CLI a TTY (macOS / Linux syntax differ). */
export function scriptCommand(cmd: string[], platform: NodeJS.Platform = process.platform): string[] | null {
  if (platform === 'darwin' && fs.existsSync('/usr/bin/script')) return ['/usr/bin/script', '-q', '/dev/null', ...cmd];
  if (platform === 'linux' && fs.existsSync('/usr/bin/script')) {
    const q = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`;
    return ['/usr/bin/script', '-q', '-e', '-c', cmd.map(q).join(' '), '/dev/null'];
  }
  return null;
}

/** A PTY through Python's pty module (the engine's Python is always there): works with piped stdio, unlike
 * `script`, which needs a terminal on its own stdin. Exit code passed through. */
export const PY_PTY = [
  'import fcntl,os,pty,select,struct,sys,termios',
  'cols,rows=int(sys.argv[1]),int(sys.argv[2]);cmd=sys.argv[3:]',
  'pid,fd=pty.fork()',
  'if pid==0:',
  ' os.execvp(cmd[0],cmd)',
  'fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack("HHHH",rows,cols,0,0))',
  'inp=sys.stdin.fileno();out=sys.stdout.fileno();fds=[fd,inp]',
  'while True:',
  ' r,_,_=select.select(fds,[],[])',
  ' if fd in r:',
  '  try: d=os.read(fd,4096)',
  '  except OSError: d=b""',
  '  if not d: break',
  '  os.write(out,d)',
  ' if inp in r:',
  '  d=os.read(inp,4096)',
  '  if d: os.write(fd,d)',
  '  else: fds=[fd]',
  '_,st=os.waitpid(pid,0)',
  'sys.exit(os.waitstatus_to_exitcode(st))',
].join('\n');

export function startTerminal(
  cmd: string[],
  env: Record<string, string>,
  size: { cols: number; rows: number },
  h: TermHandlers,
  cwd: string,
  python?: string | null,
): TermSession {
  const id = crypto.randomBytes(6).toString('hex');
  const pty = process.env.DESK_NO_PTY === '1' ? null : loadPty();
  if (pty) {
    try {
      const p = pty.spawn(cmd[0], cmd.slice(1), { name: 'xterm-256color', cols: size.cols, rows: size.rows, cwd, env });
      p.onData((d) => h.onData(d));
      p.onExit((e) => h.onExit(e.exitCode));
      return {
        id,
        backend: 'pty',
        write: (d) => p.write(d),
        resize: (c, r) => {
          try {
            p.resize(c, r);
          } catch {
            /* exited */
          }
        },
        kill: () => {
          try {
            p.kill();
          } catch {
            /* gone */
          }
        },
      };
    } catch (e) {
      ptyProblem = `spawn: ${(e as Error).message}`; // fall through to `script`
    }
  }
  const viaPython = python && process.platform !== 'win32' && fs.existsSync(python) ? [python, '-c', PY_PTY, String(size.cols), String(size.rows), ...cmd] : null;
  const viaScript = viaPython ? null : scriptCommand(cmd);
  const run = viaPython ?? viaScript ?? cmd;
  const child = spawn(run[0], run.slice(1), { cwd, env: { ...env, COLUMNS: String(size.cols), LINES: String(size.rows) }, stdio: ['pipe', 'pipe', 'pipe'] });
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (d: string) => h.onData(d));
  child.stderr.on('data', (d: string) => h.onData(d));
  let done = false;
  const finish = (code: number | null) => {
    if (done) return;
    done = true;
    h.onExit(code);
  };
  child.on('exit', (code) => finish(code));
  child.on('error', (e) => {
    h.onData(`\r\n${e.message}\r\n`);
    finish(127);
  });
  return {
    id,
    backend: viaPython ? 'python' : viaScript ? 'script' : 'pipe',
    // a pipe has no line discipline: echo nothing extra, turn the Enter key's CR into the newline the CLI reads
    write: (d) => {
      try {
        child.stdin.write(viaPython || viaScript ? d : d.replace(/\r/g, '\n'));
      } catch {
        /* exited */
      }
    },
    resize: () => {},
    kill: () => {
      try {
        child.kill('SIGTERM');
      } catch {
        /* gone */
      }
    },
  };
}
