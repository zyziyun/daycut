// App-wide overlays: undo toasts, right-click menus, the ⌘K command palette, the ? shortcut sheet, drop-anywhere
// (files dropped on the window start a new request on Home), and the global keyboard shortcuts.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, Bot, Calendar, CalendarClock, Clapperboard, FolderOpen, Home, Inbox, Keyboard, Languages, LayoutGrid, Moon, Pause, Search, Send, Settings, Sparkles, Sun, Undo2, Video } from 'lucide-react';
import { LANGS, LOCALES, fmtTime as fmtTimeOf, getLang, t, type MessageKey } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { postHref, useBackForwardKeys } from '../lib/nav';
import { go, type Route } from '../lib/router';
import { keyHint } from '../lib/keys';
import { studioEnabled } from '../lib/studioFlag';
import { rowHref, useStudioData } from '../lib/studioData';

// ---------------------------------------------------------------- toasts
interface Toast {
  id: number;
  text: string;
  undo?: () => unknown;
  error?: boolean;
  action?: { label: string; href: string };
}

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  run: () => unknown;
  sep?: boolean;
  testId?: string;
}

export interface Ui {
  /** ``action``: one link on the toast ("Open" the project just sent) */
  toast(text: string, opts?: { undo?: () => unknown; error?: boolean; ms?: number; action?: { label: string; href: string } }): void;
  menu(e: { clientX: number; clientY: number; preventDefault?: () => void }, items: MenuItem[]): void;
  openPalette(): void;
  openSheet(): void;
  /** files dropped anywhere / handed to Home's composer */
  dropped: string[];
  takeDropped(): string[];
  setDropped(paths: string[]): void;
  prefill: string | null;
  setPrefill(s: string | null): void;
  setTheme(theme: 'studio-dark' | 'notebook-light'): void;
  setLanguage(l: string): void;
  theme: 'studio-dark' | 'notebook-light';
}

const UiCtx = createContext<Ui | null>(null);

export function useUi(): Ui {
  const c = useContext(UiCtx);
  if (!c) throw new Error('UiProvider missing');
  return c;
}

let toastSeq = 0;

export function UiProvider({
  children,
  theme,
  onTheme,
  onLang,
}: {
  children: ReactNode;
  theme: 'studio-dark' | 'notebook-light';
  onTheme: (t: 'studio-dark' | 'notebook-light') => void;
  onLang: (l: string) => void;
}) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const [palette, setPalette] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [dropped, setDroppedS] = useState<string[]>([]);
  const [prefill, setPrefill] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const droppedRef = useRef<string[]>([]);

  const toast = useCallback<Ui['toast']>((text, opts = {}) => {
    const id = ++toastSeq;
    setToasts((x) => [...x.slice(-2), { id, text, undo: opts.undo, error: opts.error, action: opts.action }]);
    setTimeout(() => setToasts((x) => x.filter((y) => y.id !== id)), opts.ms ?? (opts.undo ? 8000 : 4000));
  }, []);
  const openMenu = useCallback<Ui['menu']>((e, items) => {
    e.preventDefault?.();
    setMenu({ x: Math.min(e.clientX, window.innerWidth - 240), y: Math.min(e.clientY, window.innerHeight - items.length * 34 - 16), items });
  }, []);
  const setDropped = useCallback((p: string[]) => {
    droppedRef.current = p;
    setDroppedS(p);
  }, []);
  const takeDropped = useCallback(() => {
    const p = droppedRef.current;
    droppedRef.current = [];
    setDroppedS([]);
    return p;
  }, []);

  // tooltips (CSS [data-tip]) flip below / to the side near the window edges instead of being clipped
  useEffect(() => {
    const over = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest?.('[data-tip]') as HTMLElement | null;
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.toggleAttribute('data-tip-below', r.top < 40);
      const mid = r.left + r.width / 2;
      el.setAttribute('data-tip-x', mid < 140 ? 'start' : window.innerWidth - mid < 140 ? 'end' : 'mid');
    };
    document.addEventListener('mouseover', over, true);
    return () => document.removeEventListener('mouseover', over, true);
  }, []);

  // drop files anywhere -> Home composer
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes('Files');
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth++;
      setOver(true);
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) setOver(false);
    };
    const overFn = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const drop = (e: DragEvent) => {
      depth = 0;
      setOver(false);
      if (!hasFiles(e)) return;
      if ((e.target as HTMLElement | null)?.closest?.('[data-own-drop]')) return; // the composer handles its own
      e.preventDefault();
      const paths = [...(e.dataTransfer?.files ?? [])].map((f) => window.desk.pathForFile?.(f) ?? '').filter(Boolean);
      if (paths.length) {
        setDropped([...droppedRef.current, ...paths]);
        go({ name: 'home' });
      }
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', overFn);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', overFn);
      window.removeEventListener('drop', drop);
    };
  }, [setDropped]);

  useBackForwardKeys();
  // global shortcuts
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const typing = isTyping(e.target);
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPalette((p) => !p);
        return;
      }
      if (mod && !e.shiftKey && !e.altKey && ['1', '2', '3', '4'].includes(e.key)) {
        // with the Studio the app has two places (+ Settings ⌘,): ⌘1 the Studio, ⌘2 the Calendar (in the Studio
        // itself ⌘1–9 pick a video: its own handler runs first)
        const r: Route[] = studioEnabled() ? [{ name: 'studio' }, { name: 'calendar' }] : [{ name: 'home' }, { name: 'inbox' }, { name: 'projects' }, { name: 'calendar' }];
        const to = r[Number(e.key) - 1];
        if (!to) return;
        e.preventDefault();
        go(to);
        return;
      }
      if (mod && e.key === ',') {
        e.preventDefault();
        go({ name: 'settings' });
        return;
      }
      if (mod && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        newVideo();
        return;
      }
      if (e.key === 'Escape') {
        setMenu(null);
        setSheet(false);
        setPalette(false);
      }
      if (!typing && e.key === '?' && !mod) {
        e.preventDefault();
        setSheet((s) => !s);
      }
      if (!typing && e.key === '/' && !mod) {
        const s = document.querySelector<HTMLInputElement>('[data-search]');
        if (s) {
          e.preventDefault();
          s.focus();
        }
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    // attach after the opening click has finished bubbling, or that same click closes the menu at once
    const id = window.setTimeout(() => window.addEventListener('click', close), 0);
    window.addEventListener('blur', close);
    window.addEventListener('resize', close);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener('click', close);
      window.removeEventListener('blur', close);
      window.removeEventListener('resize', close);
    };
  }, [menu]);

  const value = useMemo<Ui>(
    () => ({
      toast,
      menu: openMenu,
      openPalette: () => setPalette(true),
      openSheet: () => setSheet(true),
      dropped,
      takeDropped,
      setDropped,
      prefill,
      setPrefill,
      setTheme: onTheme,
      setLanguage: onLang,
      theme,
    }),
    [toast, openMenu, dropped, takeDropped, setDropped, prefill, onTheme, onLang, theme],
  );

  return (
    <UiCtx.Provider value={value}>
      {children}
      {over && (
        <div className="dropzone" data-testid="dropzone">
          {/* 发布: dropped footage becomes a week of posts (publish/PublishBoard.tsx) */}
          <div>{t(location.hash.startsWith('#/publish') ? 'wp.dropHere' : 'home.dropHere')}</div>
        </div>
      )}
      {menu && (
        <div className="ctx" role="menu" style={{ left: menu.x, top: menu.y }} data-testid="context-menu" onClick={(e) => e.stopPropagation()}>
          {menu.items.map((it, i) =>
            it.sep ? (
              <hr key={i} />
            ) : (
              <button
                key={i}
                role="menuitem"
                data-testid={it.testId}
                onClick={() => {
                  setMenu(null);
                  void it.run();
                }}
              >
                {it.icon}
                {it.label}
              </button>
            ),
          )}
        </div>
      )}
      <div className="toasts" aria-live="polite">
        {toasts.map((x) => (
          <div key={x.id} className={`toast ${x.error ? 'err' : ''}`} data-testid="toast">
            <span>{x.text}</span>
            {x.action && (
              <a className="btn sm" href={x.action.href} data-testid="toast-action" onClick={() => setToasts((y) => y.filter((z) => z.id !== x.id))}>
                {x.action.label}
              </a>
            )}
            {x.undo && (
              <button
                className="btn sm"
                data-testid="toast-undo"
                onClick={() => {
                  setToasts((y) => y.filter((z) => z.id !== x.id));
                  void x.undo?.();
                }}
              >
                <Undo2 className="ico" />
                {t('c.undo')}
              </button>
            )}
          </div>
        ))}
      </div>
      {palette && <Palette onClose={() => setPalette(false)} openSheet={() => setSheet(true)} theme={theme} onTheme={onTheme} onLang={onLang} />}
      {sheet && <Sheet onClose={() => setSheet(false)} />}
    </UiCtx.Provider>
  );
}

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

/** ＋ New video (⌘N, ⌘K): the Studio's composer, open and focused; without the Studio, Home's. */
export function newVideo() {
  if (studioEnabled()) {
    sessionStorage.setItem('studio.compose', '1');
    go({ name: 'studio' });
    window.dispatchEvent(new Event('studio:compose'));
    return;
  }
  go({ name: 'home' });
  setTimeout(() => document.querySelector<HTMLTextAreaElement>('[data-testid=composer-input]')?.focus(), 50);
}

// ---------------------------------------------------------------- ⌘K
interface Cmd {
  id: string;
  group: 'go' | 'actions' | 'projects' | 'clips' | 'posts' | 'settings';
  label: string;
  hint?: string;
  icon: ReactNode;
  run: () => unknown;
}

function Palette({ onClose, openSheet, theme, onTheme, onLang }: { onClose: () => void; openSheet: () => void; theme: string; onTheme: (t: 'studio-dark' | 'notebook-light') => void; onLang: (l: string) => void }) {
  const [q, setQ] = useState('');
  const [i, setI] = useState(0);
  const { data } = useHistory();
  const { client } = useEngine();
  const [posts, setPosts] = useState<{ id: string; title: string; at: string; platform: string }[]>([]);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    void client
      .calendar()
      .then((c) => alive && setPosts(c.posts.slice(0, 60)))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [client]);
  const cmds = useMemo<Cmd[]>(() => {
    const goC = (id: string, key: MessageKey, r: Route, icon: ReactNode, hint?: string): Cmd => ({ id, group: 'go', label: t(key), icon, run: () => go(r), hint });
    const other = theme === 'studio-dark' ? 'notebook-light' : 'studio-dark';
    const list: Cmd[] = [
      ...(studioEnabled()
        ? [goC('studio', 'st.nav', { name: 'studio' }, <Clapperboard className="ico" />, keyHint('⌘1')), goC('publish', 'nav.publishTop', { name: 'calendar' }, <Calendar className="ico" />, keyHint('⌘2'))]
        : [
            goC('home', 'nav.home', { name: 'home' }, <Home className="ico" />, keyHint('⌘1')),
            goC('inbox', 'nav.inbox', { name: 'inbox' }, <Inbox className="ico" />, keyHint('⌘2')),
            goC('projects', 'nav.projects', { name: 'projects' }, <LayoutGrid className="ico" />, keyHint('⌘3')),
            goC('publish', 'nav.publishTop', { name: 'calendar' }, <Calendar className="ico" />, keyHint('⌘4')),
          ]),
      goC('settings', 'nav.settings', { name: 'settings' }, <Settings className="ico" />, keyHint('⌘,')),
      {
        id: 'new',
        group: 'actions',
        label: t('palette.newPrompt'),
        icon: <Sparkles className="ico" />,
        hint: keyHint('⌘N'),
        run: newVideo,
      },
      ...LANGS.filter((l) => l !== getLang()).map<Cmd>((l) => ({ id: `lang-${l}`, group: 'actions', label: t('palette.lang', { l: LOCALES[l].label }), icon: <Languages className="ico" />, run: () => onLang(l) })),
      { id: 'theme', group: 'actions', label: t('palette.theme', { th: t(other === 'studio-dark' ? 'set.theme.studio-dark' : 'set.theme.notebook-light') }), icon: other === 'studio-dark' ? <Moon className="ico" /> : <Sun className="ico" />, run: () => onTheme(other) },
      { id: 'keys', group: 'actions', label: t('palette.shortcuts'), icon: <Keyboard className="ico" />, hint: '?', run: openSheet },
      { id: 'set-general', group: 'settings', label: t('palette.set.general'), icon: <Settings className="ico" />, hint: keyHint('⌘,'), run: () => go({ name: 'settings' }) },
      { id: 'set-ai', group: 'settings', label: t('palette.set.ai'), icon: <Bot className="ico" />, run: () => go({ name: 'aiAccounts' }) },
      { id: 'set-accounts', group: 'settings', label: t('palette.set.accounts'), icon: <Send className="ico" />, run: () => go({ name: 'channels' }) },
    ];
    for (const p of posts)
      list.push({ id: `post-${p.id}`, group: 'posts', label: p.title, hint: `${fmtTimeOf(p.at)} · ${t(`pf.${p.platform.split(':')[0]}` as MessageKey)}`, icon: <CalendarClock className="ico" />, run: () => (location.hash = postHref(p.id)) });
    for (const it of data?.items ?? []) {
      if (it.live?.state === 'running' && it.openable && client)
        list.push({ id: `pause-${it.id}`, group: 'actions', label: t('palette.pause', { name: it.name }), icon: <Pause className="ico" />, run: () => client.cancel(it.id).catch(() => undefined) });
      list.push({ id: `p-${it.id}`, group: 'projects', label: it.name, icon: <FolderOpen className="ico" />, run: () => go({ name: 'project', id: it.id }) });
    }
    return list;
  }, [data, client, theme, onTheme, onLang, openSheet, posts]);
  const [clipHits, setClipHits] = useState<Cmd[]>([]);
  // with the Studio: every video it lists, by title or project (no wait - the rows are loaded)
  const studio = useStudioData();
  const videoCmds = useMemo<Cmd[]>(
    () =>
      studio.rows
        .filter((r) => r.kind === 'clip')
        .map((r) => ({ id: `v-${r.key}`, group: 'clips' as const, label: r.title, hint: [r.project, r.pos ? `${r.pos[0]}/${r.pos[1]}` : null].filter(Boolean).join(' · '), icon: <Video className="ico" />, run: () => (location.hash = rowHref(r)) })),
    [studio.rows],
  );
  useEffect(() => {
    // clip titles: search the recent finished projects' clips (lazy, only while typing)
    if (studioEnabled() || !client || q.trim().length < 2) {
      setClipHits([]);
      return;
    }
    let alive = true;
    const items = (data?.items ?? []).filter((x) => x.status === 'done' || x.status === 'delivered' || x.status === 'packaged').slice(0, 12);
    void Promise.all(items.map((x) => client.clips(x.id).then((d) => d.clips.map((c) => ({ x, c }))).catch(() => []))).then((rows) => {
      if (!alive) return;
      const ql = q.toLowerCase();
      setClipHits(
        rows
          .flat()
          .filter(({ c }) => c.title.toLowerCase().includes(ql) || c.id.toLowerCase().includes(ql))
          .slice(0, 8)
          .map(({ x, c }) => ({ id: `c-${x.id}-${c.id}`, group: 'clips', label: c.title, hint: x.name, icon: <Video className="ico" />, run: () => go({ name: 'clip', id: x.id, clip: c.id }) })),
      );
    });
    return () => {
      alive = false;
    };
  }, [q, client, data]);
  const ql = q.trim().toLowerCase();
  const videos = studioEnabled() ? videoCmds.filter((c) => !ql || c.label.toLowerCase().includes(ql) || (c.hint ?? '').toLowerCase().includes(ql)).slice(0, ql ? 12 : 8) : [];
  const shown = [...cmds.filter((c) => !ql || c.label.toLowerCase().includes(ql) || c.id.includes(ql)), ...videos, ...clipHits].slice(0, 40);
  const groups: Cmd['group'][] = studioEnabled() ? ['go', 'clips', 'projects', 'posts', 'actions', 'settings'] : ['go', 'projects', 'clips', 'posts', 'actions', 'settings'];
  const ordered = groups.flatMap((g) => shown.filter((c) => c.group === g));
  const pick = (c: Cmd | undefined) => {
    if (!c) return;
    onClose();
    void c.run();
  };
  return (
    <div className="scrim" onMouseDown={onClose} data-testid="palette">
      <div className="palette" onMouseDown={(e) => e.stopPropagation()}>
        <div className="row" style={{ paddingLeft: 16 }}>
          <Search className="ico muted" />
          <input
            autoFocus
            value={q}
            placeholder={t('palette.jump')}
            onChange={(e) => {
              setQ(e.target.value);
              setI(0);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setI((x) => Math.min(ordered.length - 1, x + 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setI((x) => Math.max(0, x - 1));
              } else if (e.key === 'Enter') pick(ordered[i]);
              else if (e.key === 'Escape') onClose();
            }}
            data-testid="palette-input"
          />
        </div>
        <div className="list">
          {!ordered.length && <div className="grp">{t('palette.empty')}</div>}
          {groups.map((g) => {
            const rows = ordered.filter((c) => c.group === g);
            if (!rows.length) return null;
            return (
              <div key={g}>
                <div className="grp">{t(`palette.${g}` as MessageKey)}</div>
                {rows.map((c) => {
                  const k = ordered.indexOf(c);
                  return (
                    <div key={c.id} className={`it ${k === i ? 'on' : ''}`} onMouseEnter={() => setI(k)} onClick={() => pick(c)} data-testid="palette-item">
                      {c.icon}
                      <span className="sp clamp1">{c.label}</span>
                      {c.hint && <span className="muted clamp1" style={{ maxWidth: 200 }}>{c.hint}</span>}
                      {k === i && <ArrowRight className="ico muted" />}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- ? cheat sheet
export const SHORTCUTS: [MessageKey, string][] = [
  ['keys.palette', keyHint('⌘K')],
  ['keys.backForward', keyHint('⌘[ · ⌘]')],
  ['keys.help', '?'],
  ['keys.go', keyHint('⌘1 – ⌘4')],
  ['keys.studioPick', `${keyHint('⌘1 – ⌘9')} · ↑ ↓`],
  ['keys.newPrompt', keyHint('⌘N')],
  ['keys.search', '/'],
  ['keys.play', 'Space · K'],
  ['keys.shuttle', 'J · K · L'],
  ['keys.frame', '← →'],
  ['keys.mark', 'I · O'],
  ['keys.loop', 'Shift L'],
  ['keys.full', 'F'],
  ['keys.exit', 'Esc'],
  ['keys.approve', 'Space · X · E'],
  ['keys.undo', keyHint('⌘Z')],
];

function Sheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="scrim" onMouseDown={onClose} data-testid="shortcuts">
      <div className="sheet" onMouseDown={(e) => e.stopPropagation()}>
        <h2>{t('keys.title')}</h2>
        <div className="k">
          {SHORTCUTS.map(([k, v]) => (
            <div key={k} style={{ display: 'contents' }}>
              <span>{t(k)}</span>
              <span className="kbd" style={{ justifySelf: 'end' }}>
                {v}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
