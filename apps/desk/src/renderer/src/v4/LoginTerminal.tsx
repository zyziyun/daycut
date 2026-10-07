// The in-app sign-in sheet (ux/settings-redesign A3): what to do in the browser, a waiting line, a box to paste a
// code, and the terminal itself folded under "Show details". The in-app login terminal: runs `claude auth login` / `codex login` (command chosen by the engine, API keys
// stripped from its env by main) in xterm.js, so the browser sign-in and any code paste happen inside the app.
// When the CLI exits, the provider's status is checked again. Nothing typed or shown here is stored.
import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { providerName } from '../../../shared/aiRoutes';
import { AlertTriangle, Check, ChevronDown, ChevronRight, Sparkles, TerminalSquare } from 'lucide-react';
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
  const [code, setCode] = useState('');
  const [details, setDetails] = useState(false);

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
  const failed = exit !== undefined && exit !== 0 && exit !== null;
  const login = req.action === 'login';
  const send = () => {
    if (!id || !code.trim()) return;
    void window.desk.ai.input(id, `${code.trim()}\r`);
    setCode('');
  };
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && !running && onClose()}>
      <div className="sheet col s2-signin" role="dialog" aria-label={login ? t('s2.si.title', { name }) : t('s2.si.titleOut', { name })} data-testid="login-terminal">
        <span className={`s2-pico ${req.provider}`}>{req.provider === 'codex' ? <TerminalSquare className="ico" /> : <Sparkles className="ico" />}</span>
        <h2>{login ? t('s2.si.title', { name }) : t('s2.si.titleOut', { name })}</h2>
        {login && <p className="muted">{t('s2.si.body')}</p>}
        <div className={`s2-wait ${exit !== undefined ? (failed ? 'bad' : 'ok') : ''}`} data-testid={exit !== undefined ? 'term-exit' : 'term-wait'}>
          {exit === undefined ? (
            <>
              <i className="s2-spin" />
              {!id ? t('s2.si.starting') : login ? t('s2.si.wait') : t('s2.si.waitOut')}
            </>
          ) : failed ? (
            <>
              <AlertTriangle className="ico" />
              {t('s2.si.failed')}
            </>
          ) : (
            <>
              <Check className="ico" />
              {checked ? t('s2.si.done', { name }) : t('aiacc.term.exited', { code: exit ?? '-' })}
            </>
          )}
        </div>
        {login && running && (
          <label className="col" style={{ gap: 8 }}>
            <span className="muted">{t('s2.si.code')}</span>
            <span className="row" style={{ gap: 8 }}>
              <input
                className="input s2-code"
                value={code}
                placeholder={t('s2.si.codePh')}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && send()}
                autoComplete="off"
                spellCheck={false}
                data-testid="signin-code"
              />
              {code.trim() && (
                <button className="btn" onClick={send} data-testid="signin-send">
                  {t('s2.si.send')}
                </button>
              )}
            </span>
          </label>
        )}
        <div className={`s2-term ${details ? 'open' : ''}`} aria-hidden={!details}>
          {cmd && <span className="mono small faint">{t('aiacc.term.running', { cmd })}</span>}
          {backend === 'pipe' && <span className="muted small">{t('aiacc.term.basic')}</span>}
          <div ref={box} className="term" style={{ background: '#0E1113', borderRadius: 8, padding: 6, minHeight: 260 }} data-testid="term-box" />
        </div>
        {err && <div className="notice">{err}</div>}
        <div className="row">
          <button className="s2-link" onClick={() => setDetails(!details)} data-testid="signin-details" aria-expanded={details}>
            {details ? <ChevronDown className="ico" /> : <ChevronRight className="ico" />}
            {details ? t('s2.si.hide') : t('s2.si.details')}
          </button>
          <span className="sp" />
          {running ? (
            <button className="btn" onClick={() => id && void window.desk.ai.kill(id)} data-testid="term-stop">
              {t('s2.si.cancel')}
            </button>
          ) : (
            <button className={`btn ${exit !== undefined ? 'primary' : ''}`} onClick={onClose} data-testid="term-close">
              {exit !== undefined ? t('s2.done') : t('s2.si.cancel')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
