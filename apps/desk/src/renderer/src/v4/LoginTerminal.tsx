// The in-app login terminal: runs `claude auth login` / `codex login` (command chosen by the engine, API keys
// stripped from its env by main) in xterm.js, so the browser sign-in and any code paste happen inside the app.
// When the CLI exits, the provider's status is checked again. Nothing typed or shown here is stored.
import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { providerName } from '../../../shared/aiRoutes';
import { t } from '../i18n';
import { refreshStatus } from '../lib/ai';

export interface LoginReq {
  provider: 'claude-code' | 'codex';
  action: 'login' | 'logout';
  variant?: 'console' | 'sso' | 'device';
}

export function LoginTerminal({ req, onClose }: { req: LoginReq; onClose: () => void }) {
  const box = useRef<HTMLDivElement | null>(null);
  const [id, setId] = useState<string | null>(null);
  const [cmd, setCmd] = useState('');
  const [backend, setBackend] = useState<string>('pty');
  const [exit, setExit] = useState<number | null | undefined>(undefined);
  const [checked, setChecked] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const term = new Terminal({ fontSize: 12, cursorBlink: true, convertEol: false, rows: 18, cols: 88, theme: { background: '#0E1113' }, allowProposedApi: false });
    term.open(box.current);
    let sid: string | null = null;
    let alive = true;
    const offData = window.desk.on('term:data', (m) => {
      const x = m as { id: string; data: string };
      if (x.id === sid) term.write(x.data);
    });
    const offExit = window.desk.on('term:exit', (m) => {
      const x = m as { id: string; code: number | null };
      if (x.id !== sid) return;
      setExit(x.code);
      // the login changed (or not): check this provider again, with the real round-trip
      void refreshStatus({ refresh: true, providers: [req.provider] }).finally(() => alive && setChecked(true));
    });
    const input = term.onData((d) => sid && void window.desk.ai.input(sid, d));
    window.desk.ai
      .terminal({ ...req, cols: term.cols, rows: term.rows })
      .then((r) => {
        if (!alive) {
          void window.desk.ai.kill(r.id);
          return;
        }
        sid = r.id;
        setId(r.id);
        setCmd(r.display);
        setBackend(r.backend);
        term.focus();
      })
      .catch((e: Error) => setErr(e.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '')));
    return () => {
      alive = false;
      input.dispose();
      offData();
      offExit();
      if (sid) void window.desk.ai.kill(sid);
      term.dispose();
    };
    // one terminal per request
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const name = providerName(req.provider);
  const running = id && exit === undefined;
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && !running && onClose()}>
      <div className="sheet col" role="dialog" style={{ width: 'min(760px, 94vw)', gap: 10 }} data-testid="login-terminal">
        <h2 style={{ margin: 0 }}>{req.action === 'login' ? t('aiacc.term.title', { name }) : t('aiacc.term.titleLogout', { name })}</h2>
        {req.action === 'login' && <span className="muted small">{t('aiacc.term.hint')}</span>}
        {cmd && <span className="mono small faint">{t('aiacc.term.running', { cmd })}</span>}
        {backend === 'pipe' && <span className="muted small">{t('aiacc.term.basic')}</span>}
        <div ref={box} className="term" style={{ background: '#0E1113', borderRadius: 8, padding: 6, minHeight: 260 }} data-testid="term-box" />
        {err && <div className="notice">{err}</div>}
        {exit !== undefined && (
          <div className="notice accent" data-testid="term-exit">
            {checked ? t('aiacc.term.done') : t('aiacc.term.exited', { code: exit ?? '-' })}
          </div>
        )}
        <div className="row">
          <span className="sp" />
          {running ? (
            <button className="btn" onClick={() => id && void window.desk.ai.kill(id)} data-testid="term-stop">
              {t('aiacc.term.stop')}
            </button>
          ) : (
            <button className="btn primary" onClick={onClose} data-testid="term-close">
              {t('aiacc.term.close')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
