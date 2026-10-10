// The in-app update, where she sees it (state machine: shared/update.ts, fed by main/updater.ts):
//   - a pill in the sidebar footer: download progress, then "Update ready · Restart"; failures in plain words;
//   - a one-time card when an update is ready: "Reelfold 0.2.5 is ready — Restart to update" · What's new · Later
//     ("Later" lasts for this launch; it comes back next time, and the update installs itself when she quits);
//   - What's new: the release notes from the feed, as text;
//   - projects running: "restart when they finish" or "restart now" instead of cutting them off unasked;
//   - Settings › General › Updates (UpdateSettingsGroup): version, last checked, Check for updates.
// Nothing here in the Mac App Store build (the store updates it): main reports the state "disabled" there.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, ArrowDownCircle, RefreshCw, Sparkles, X } from 'lucide-react';
import { fmtAgo, fmtDate, t } from '../i18n';
import { useHistory } from '../lib/history';
import { errorKey, restartPlan, restartWhenDoneDue, shouldShowCard, type UpdateStateMsg } from '../../../shared/update';
import { Modal } from './ui';
import './update.css';

export const RELEASES_URL = 'https://github.com/zyziyun/reelfold/releases/latest';

interface UpdateCtx {
  u: UpdateStateMsg | null;
  running: number;
  /** waiting for the running projects before restarting ("Restart when done") */
  pending: boolean;
  restarting: boolean;
  checking: boolean;
  /** "Restart to update": at once when nothing runs, otherwise asks first */
  restart(): void;
  check(): Promise<void>;
  cancelPending(): void;
  showNotes(): void;
  goSettings(): void;
}

const Ctx = createContext<UpdateCtx | null>(null);

export function useUpdate(): UpdateCtx | null {
  return useContext(Ctx);
}

function useRunningCount(): number {
  const { live } = useHistory();
  return live.filter((i) => i.live?.state === 'running').length;
}

// per launch (module state, not React state: the Shell remounts on a language change)
const laterFor = new Set<string>();
const cardShown = new Set<string>();

export function UpdateProvider({ children }: { children: ReactNode }) {
  const [u, setU] = useState<UpdateStateMsg | null>(null);
  const [pending, setPending] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [ask, setAsk] = useState(false);
  const [notes, setNotes] = useState(false);
  const [card, setCard] = useState(false);
  const running = useRunningCount();

  useEffect(() => {
    let live = true;
    const off = window.desk.on('update:state', (d) => setU(d as UpdateStateMsg));
    // the state may have been set before this window loaded (a download that finished while it was closed)
    void window.desk.update
      .get()
      .then((s) => live && setU((cur) => cur ?? s))
      .catch(() => undefined);
    return () => {
      live = false;
      off();
    };
  }, []);

  // the one-time card
  useEffect(() => {
    if (shouldShowCard(u, laterFor, cardShown)) {
      cardShown.add(u!.version!);
      setCard(true);
    }
    if (u?.state !== 'ready') setCard(false);
    if (u?.state === 'error') setRestarting(false);
  }, [u]);

  const install = useCallback(() => {
    setAsk(false);
    setCard(false);
    setPending(false);
    setRestarting(true);
    void window.desk.update
      .install()
      .then((s) => {
        setU(s);
        if (s.state !== 'ready') setRestarting(false);
      })
      .catch(() => setRestarting(false));
  }, []);

  // "Restart when done"
  useEffect(() => {
    if (restartWhenDoneDue(pending, running, u)) install();
  }, [pending, running, u, install]);

  const restart = useCallback(() => {
    if (restartPlan(running) === 'now') install();
    else {
      setCard(false);
      setAsk(true);
    }
  }, [running, install]);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      setU(await window.desk.update.check());
    } finally {
      setChecking(false);
    }
  }, []);

  const later = useCallback(() => {
    if (u?.version) laterFor.add(u.version);
    setCard(false);
  }, [u]);

  const ctx = useMemo<UpdateCtx>(
    () => ({
      u,
      running,
      pending,
      restarting,
      checking,
      restart,
      check,
      cancelPending: () => setPending(false),
      showNotes: () => setNotes(true),
      goSettings: () => (location.hash = '#/settings/general'),
    }),
    [u, running, pending, restarting, checking, restart, check],
  );

  return (
    <Ctx.Provider value={ctx}>
      {children}
      {card && u?.state === 'ready' && !ask && !notes && (
        <div className="upd-card" role="dialog" aria-label={t('upd.card.title', { version: u.version ?? '' })} data-testid="update-card">
          <div className="upd-card-icon">
            <Sparkles className="ico" />
          </div>
          <div className="upd-card-text">
            <b>{t('upd.card.title', { version: u.version ?? '' })}</b>
            <span>{t('upd.card.body')}</span>
            <div className="upd-card-actions">
              <button className="btn primary" onClick={restart} disabled={restarting} data-testid="update-card-restart">
                {restarting ? t('upd.restarting') : t('upd.restart')}
              </button>
              <button className="btn" onClick={() => setNotes(true)} data-testid="update-card-notes">
                {t('upd.whatsNew')}
              </button>
              <button className="btn ghost" onClick={later} data-testid="update-card-later">
                {t('upd.later')}
              </button>
            </div>
          </div>
          <button className="upd-card-x" onClick={later} aria-label={t('upd.later')}>
            <X className="ico" />
          </button>
        </div>
      )}
      {notes && u?.version && (
        <Modal title={t('upd.notes.title', { version: u.version })} onClose={() => setNotes(false)}>
          <div className="upd-notes" data-testid="update-notes">
            {u.notes ? <NotesText text={u.notes} /> : <p className="muted">{t('upd.notes.empty')}</p>}
          </div>
          <div className="upd-modal-actions">
            <button className="btn" onClick={() => setNotes(false)} data-testid="update-notes-close">
              {t('upd.close')}
            </button>
            {u.state === 'ready' && (
              <button
                className="btn primary"
                onClick={() => {
                  setNotes(false);
                  restart();
                }}
                data-testid="update-notes-restart"
              >
                {t('upd.restart')}
              </button>
            )}
          </div>
        </Modal>
      )}
      {ask && (
        <Modal title={t('upd.running.title', { n: running })} onClose={() => setAsk(false)}>
          <div data-testid="update-running">
            <p className="upd-prose">{t('upd.running.body', { n: running })}</p>
            <div className="upd-modal-actions">
              <button className="btn ghost" onClick={() => setAsk(false)} data-testid="update-running-cancel">
                {t('upd.cancel')}
              </button>
              <button className="btn" onClick={install} data-testid="update-running-now">
                {t('upd.running.now')}
              </button>
              <button
                className="btn primary"
                onClick={() => {
                  setAsk(false);
                  setPending(true);
                }}
                data-testid="update-running-later"
              >
                {t('upd.running.whenDone')}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </Ctx.Provider>
  );
}

/** Release notes as text: a line starting with "• " is a list item, a short line followed by more is a heading. */
function NotesText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((b, i) => {
        const lines = b.split('\n').filter(Boolean);
        const items = lines.filter((l) => l.startsWith('• '));
        const head = lines.length > 1 && !lines[0].startsWith('• ') && lines[0].length <= 80 ? lines[0] : null;
        const rest = head ? lines.slice(1) : lines;
        return (
          <section key={i}>
            {head && <h4>{head}</h4>}
            {items.length === rest.length && items.length ? (
              <ul>
                {items.map((l, j) => (
                  <li key={j}>{l.slice(2)}</li>
                ))}
              </ul>
            ) : (
              rest.map((l, j) => <p key={j}>{l.startsWith('• ') ? `· ${l.slice(2)}` : l}</p>)
            )}
          </section>
        );
      })}
    </>
  );
}

/** The sidebar footer pill: only while something is happening (downloading / ready / waiting / failed). Stacked
 * (the sidebar is narrow): what is happening, then the one action under it. */
export function UpdatePill() {
  const c = useUpdate();
  const u = c?.u;
  if (!c || !u) return null;
  if (c.pending && u.state === 'ready') {
    return (
      <div className="upd-pill wait" data-testid="update-pill" data-state="waiting">
        <div className="upd-pill-head">
          <RefreshCw className="ico" />
          <b>{t('upd.pill.waiting', { n: c.running })}</b>
        </div>
        <button className="upd-pill-btn" onClick={c.cancelPending} data-testid="update-pill-cancel">
          {t('upd.cancel')}
        </button>
      </div>
    );
  }
  if (u.state === 'downloading' || u.state === 'available') {
    const pct = u.percent ?? 0;
    return (
      <div className="upd-pill dl" data-testid="update-pill" data-state="downloading">
        <div className="upd-pill-head">
          <ArrowDownCircle className="ico" />
          <b>{t('upd.pill.downloading')}</b>
          <span className="upd-pct" data-testid="update-percent">
            {pct}%
          </span>
        </div>
        <i className="upd-bar" aria-hidden="true">
          <i style={{ width: `${pct}%` }} />
        </i>
      </div>
    );
  }
  if (u.state === 'ready') {
    return (
      <div className="upd-pill ready" data-testid="update-pill" data-state="ready">
        <button className="upd-pill-head link" onClick={c.showNotes} title={t('upd.whatsNew')} data-testid="update-pill-notes">
          <Sparkles className="ico" />
          <span className="upd-pill-text">
            <b>{t('upd.pill.ready')}</b>
            <span>{t('upd.pill.readySub', { version: u.version ?? '' })}</span>
          </span>
        </button>
        <button className="upd-pill-btn primary" onClick={c.restart} disabled={c.restarting} data-testid="update-ready">
          {c.restarting ? t('upd.restarting') : t('upd.restart')}
        </button>
      </div>
    );
  }
  // a failed background check (offline) only shows in Settings; a failed download / install shows here too
  if (u.state === 'error' && u.errorStage !== 'check') {
    return (
      <div className="upd-pill err" data-testid="update-pill" data-state="error">
        <div className="upd-pill-head">
          <AlertTriangle className="ico" />
          <b>{t(u.errorStage === 'download' ? 'upd.pill.failedDownload' : 'upd.pill.failed')}</b>
        </div>
        <button className="upd-pill-btn" onClick={c.goSettings} data-testid="update-pill-see">
          {t('upd.pill.see')}
        </button>
      </div>
    );
  }
  return null;
}

function checkedWhen(ts: number): string {
  return Date.now() - ts < 3600_000 ? fmtAgo(ts) : fmtDate(ts, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** Settings › General › Updates. */
export function UpdateSettingsGroup({ version }: { version: string }) {
  const c = useUpdate();
  const [, tick] = useState(0);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    timer.current = window.setInterval(() => tick((n) => n + 1), 30_000); // "Last checked 2 min ago" stays true
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);
  const u = c?.u;
  if (!c || !u) return null;
  const off = u.state === 'disabled';
  const busy = c.checking || u.state === 'checking';
  let status: ReactNode = null;
  if (busy) status = t('upd.set.checking');
  else if (u.state === 'none') status = t('upd.set.upToDate');
  else if (u.state === 'available' || u.state === 'downloading') status = t('upd.set.downloading', { version: u.version ?? '', percent: u.percent ?? 0 });
  else if (u.state === 'ready') status = t('upd.set.ready', { version: u.version ?? '' });
  return (
    <div className="s2-group" data-testid="settings-updates">
      <div className="s2-gtitle">{t('upd.set.title')}</div>
      <div className="s2-card">
        <div className="s2-row upd-row">
          <div className="s2-rtext">
            <span className="s2-rlabel" data-testid="update-version">
              {t('upd.set.version', { version: u.current || version })}
            </span>
            <span className="s2-rhint" data-testid="update-checked">
              {off ? t('upd.set.off') : u.checkedAt ? t('upd.set.checked', { when: checkedWhen(u.checkedAt) }) : t('upd.set.never')}
            </span>
          </div>
          {!off && (
            <div className="upd-row-actions">
              {u.state === 'ready' ? (
                <>
                  <button className="s2-link" onClick={c.showNotes} data-testid="update-settings-notes">
                    {t('upd.whatsNew')}
                  </button>
                  <button className="btn primary" onClick={c.restart} disabled={c.restarting} data-testid="update-settings-restart">
                    {c.restarting ? t('upd.restarting') : t('upd.restart')}
                  </button>
                </>
              ) : (
                <button className="btn" onClick={() => void c.check()} disabled={busy || u.state === 'downloading'} data-testid="update-check">
                  {t('upd.set.check')}
                </button>
              )}
            </div>
          )}
        </div>
        {!off && (status || u.state === 'error') && (
          <div className={`s2-row upd-status ${u.state === 'error' ? 'err' : ''}`} data-testid="update-status" data-state={busy ? 'checking' : u.state}>
            {u.state === 'error' && !busy ? (
              <div className="s2-rtext">
                <span className="s2-rlabel">
                  <AlertTriangle className="ico" /> {t(errorKey(u.errorStage))}
                </span>
                {u.error && <span className="s2-rhint upd-raw">{u.error}</span>}
                <span className="upd-row-actions">
                  <button className="s2-link" onClick={() => void c.check()} data-testid="update-retry">
                    {t('upd.retry')}
                  </button>
                  <button className="s2-link" onClick={() => void window.desk.openExternal(RELEASES_URL)} data-testid="update-download">
                    {t('upd.download')}
                  </button>
                </span>
              </div>
            ) : (
              <span className="s2-rhint">{status}</span>
            )}
            {(u.state === 'downloading' || u.state === 'available') && (
              <i className="upd-bar wide" aria-hidden="true">
                <i style={{ width: `${u.percent ?? 0}%` }} />
              </i>
            )}
          </div>
        )}
        {!off && <p className="s2-rhint upd-auto">{t('upd.set.auto')}</p>}
      </div>
    </div>
  );
}
