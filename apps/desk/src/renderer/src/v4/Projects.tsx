// 全部项目: a thumbnail grid (whole card clickable), one filter row (全部 / 运行中 / 需要你 / 已完成), search, type,
// multi-select with bulk actions, inline rename, right-click menu, and the watched folders folded at the bottom.
import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckSquare, Copy, Eye, FolderOpen, FolderPlus, Pencil, Plus, Square, Trash2, Users } from 'lucide-react';
import { PromptModal } from '../components/ui';
import { useAgencyMode } from '../lib/prefs';
import type { HistoryItem } from '../../../shared/v02';
import { t, tk } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { go, href } from '../lib/router';
import { bucket } from '../lib/status';
import { ProjectTile } from './Home';
import { Empty, More, Seg, SkGrid } from './kit';
import { useUi } from './ui';

type F = 'all' | 'running' | 'you' | 'done' | 'failed';
const OWN = '\u0000own';
const TYPES = ['talkinghead', 'slices', 'explainer', 'photo-story', 'vlog', 'podcast', 'aigc', 'script', 'batch', 'promo', 'slides', 'other'];

export function Projects() {
  const { data, reload } = useHistory();
  const { client } = useEngine();
  const ui = useUi();
  const [f, setF] = useState<F>(() => (sessionStorage.getItem('v4.pf') as F) || 'all');
  const [q, setQ] = useState('');
  const [type, setType] = useState('');
  const [selecting, setSelecting] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [renaming, setRenaming] = useState<string | null>(null);
  // agency mode only (Settings -> 「我在帮别人做视频」): filter by client, set a project's client
  const agency = useAgencyMode();
  const [clientF, setClientF] = useState(''); // '' all · OWN her own · else the client name
  const [clientFor, setClientFor] = useState<HistoryItem | null>(null);
  useEffect(() => sessionStorage.setItem('v4.pf', f), [f]);
  // the page is shown: the list is read again (a project registered while she was elsewhere is in it at once)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => reload(), []);
  const items = useMemo(() => data?.items ?? [], [data]);
  // the tiles say 「需要你」 when the Inbox holds a decision: the filter row counts the same way
  const inbox = useInbox();
  const deciding = useMemo(() => new Set(inbox.items.filter((x) => x.kind !== 'failed' && x.project.id).map((x) => x.project.id!)), [inbox.items]);
  const bucketOf = (i: HistoryItem) => bucket(i, deciding.has(i.id));
  const counts = useMemo(() => {
    const c = { all: items.length, running: 0, you: 0, done: 0, failed: 0 };
    for (const i of items) {
      const b = bucket(i, deciding.has(i.id));
      if (b !== 'other') c[b]++;
    }
    return c;
  }, [items, deciding]);
  const clientNames = useMemo(() => [...new Set(items.map((i) => i.client).filter((c): c is string => !!c))].sort(), [items]);
  const clientOk = (i: HistoryItem) => !agency || !clientF || (clientF === OWN ? !i.client : i.client === clientF);
  const shown = items.filter((i) => (f === 'all' || bucketOf(i) === f) && (!type || (i.type ?? 'other') === type) && clientOk(i) && (!q || `${i.name} ${i.recipe ?? ''} ${agency ? (i.client ?? '') : ''}`.toLowerCase().includes(q.toLowerCase())));
  const saveClient = async (i: HistoryItem, name: string) => {
    setClientFor(null);
    if (!client) return;
    await client.setHistoryClient(i.dir, name.trim());
    reload();
    ui.toast(t('editor.saved'));
  };

  const remove = async (list: HistoryItem[]) => {
    if (!client || !list.length) return;
    for (const i of list) await client.hideHistory(i.dir);
    setSel(new Set());
    reload();
    ui.toast(`${t('projects.removed', { n: list.length })} ${t('projects.removeHint')}`, {
      undo: async () => {
        for (const i of list) await client.unhideOne(i.dir);
        reload();
      },
    });
  };
  const rename = async (i: HistoryItem, name: string) => {
    setRenaming(null);
    if (!client || !name.trim() || name.trim() === i.name) return;
    const old = i.name;
    await client.renameHistory(i.dir, name.trim());
    reload();
    ui.toast(t('editor.saved'), {
      undo: async () => {
        await client.renameHistory(i.dir, old);
        reload();
      },
    });
  };
  const again = (i: HistoryItem) => {
    ui.setPrefill(t('projects.againPrompt', { name: i.name }));
    go({ name: 'home' });
  };
  const menu = (i: HistoryItem) => (e: React.MouseEvent) =>
    ui.menu(e, [
      { label: t('c.open'), icon: <Eye className="ico" />, run: () => go({ name: 'project', id: i.id }) },
      { label: t('c.rename'), icon: <Pencil className="ico" />, run: () => setRenaming(i.id), testId: 'menu-rename' },
      { label: t('projects.again'), icon: <Copy className="ico" />, run: () => again(i) },
      ...(agency ? [{ label: t('projects.setClient'), icon: <Users className="ico" />, run: () => setClientFor(i), testId: 'menu-client' }] : []),
      { label: t('c.reveal'), icon: <FolderOpen className="ico" />, run: () => window.desk.showItem(i.dir) },
      { label: '', sep: true, run: () => undefined },
      { label: t('c.remove'), icon: <Trash2 className="ico" />, run: () => remove([i]), testId: 'menu-remove' },
    ]);

  return (
    <div className="scroll" data-testid="projects">
      <div className="pg">
        <div className="ph">
          <div>
            <h1>{t('projects.title')}</h1>
            <p>{t('projects.subtitle')}</p>
          </div>
          <span className="sp" />
          <button className="btn primary" onClick={() => go({ name: 'home' })} data-tip="⌘N">
            <Plus className="ico" />
            {t('projects.new')}
          </button>
        </div>
        <div className="tools">
          <Seg
            value={f}
            onChange={setF}
            testId="projects-filter"
            options={[
              { v: 'all', label: t('projects.f.all', { n: counts.all }) },
              { v: 'running', label: t('projects.f.running', { n: counts.running }) },
              { v: 'you', label: t('projects.f.you', { n: counts.you }) },
              { v: 'done', label: t('projects.f.done', { n: counts.done }) },
              // only when something failed: a calm row otherwise
              ...(counts.failed || f === 'failed' ? [{ v: 'failed' as const, label: t('projects.f.failed', { n: counts.failed }) }] : []),
            ]}
          />
          <span className="sp" />
          <input className="inp" data-search value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('projects.search')} aria-label={t('c.search')} data-testid="projects-search" />
          {agency && (
            <select className="inp" value={clientF} onChange={(e) => setClientF(e.target.value)} aria-label={t('projects.client')} data-testid="projects-client">
              <option value="">{t('projects.clientAll')}</option>
              <option value={OWN}>{t('projects.clientOwn')}</option>
              {clientNames.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          )}
          <select className="inp" value={type} onChange={(e) => setType(e.target.value)} aria-label={t('projects.type')} data-testid="projects-type">
            <option value="">{t('projects.anyType')}</option>
            {TYPES.map((ty) => (
              <option key={ty} value={ty}>
                {tk(`type.${ty}`)}
              </option>
            ))}
          </select>
          <button className={`btn ${selecting ? '' : 'ghost'}`} onClick={() => (setSelecting(!selecting), setSel(new Set()))} aria-pressed={selecting} data-testid="projects-select">
            <CheckSquare className="ico" />
            {t('c.select')}
          </button>
        </div>
        {!data ? (
          <SkGrid />
        ) : !items.length ? (
          <Empty
            title={t('projects.empty')}
            hint={t('projects.emptyHint')}
            action={
              <a className="btn primary" href={href({ name: 'home' })}>
                {t('projects.goHome')}
              </a>
            }
          />
        ) : !shown.length ? (
          <Empty title={t('projects.noMatch', { q: q || tk(`type.${type}`) })} />
        ) : (
          <div className="pgrid" data-testid="projects-grid">
            {shown.map((i) =>
              selecting ? (
                <div key={i.id} className={`pcard ${sel.has(i.id) ? 'sel' : ''}`} onClick={() => toggle(sel, setSel, i.id)} data-testid="project-card" role="checkbox" aria-checked={sel.has(i.id)}>
                  <span className="pick">{sel.has(i.id) ? <CheckSquare className="ico" /> : <Square className="ico" />}</span>
                  <div style={{ pointerEvents: 'none' }}>
                    <ProjectTile i={i} />
                  </div>
                </div>
              ) : renaming === i.id ? (
                <div key={i.id} className="pcard">
                  <ProjectTileRename i={i} onDone={(n) => void rename(i, n)} />
                </div>
              ) : (
                <ProjectTile key={i.id} i={i} onContext={menu(i)} />
              ),
            )}
          </div>
        )}
        {selecting && sel.size > 0 && (
          <div className="bulk" data-testid="projects-bulk">
            <b style={{ fontWeight: 500 }}>{t('c.selected', { n: sel.size })}</b>
            <button className="btn ghost" onClick={() => setSel(new Set(shown.map((i) => i.id)))}>
              {t('c.selectAll')}
            </button>
            <span className="sp" />
            <button className="btn" onClick={() => items.filter((i) => sel.has(i.id)).slice(0, 5).forEach((i) => void window.desk.showItem(i.dir))}>
              <FolderOpen className="ico" />
              {t('c.reveal')}
            </button>
            <button className="btn danger" onClick={() => void remove(items.filter((i) => sel.has(i.id)))} data-testid="projects-bulk-remove">
              <Trash2 className="ico" />
              {t('c.remove')}
            </button>
          </div>
        )}
        <Watched />
      </div>
      {clientFor && (
        <PromptModal title={t('projects.setClientTitle', { name: clientFor.name })} placeholder={clientFor.client || t('projects.setClientNone')} okLabel={t('ch.save')} onOk={(v) => void saveClient(clientFor, v)} onCancel={() => setClientFor(null)} />
      )}
    </div>
  );
}

function toggle(sel: Set<string>, setSel: (s: Set<string>) => void, id: string) {
  const n = new Set(sel);
  if (n.has(id)) n.delete(id);
  else n.add(id);
  setSel(n);
}

function ProjectTileRename({ i, onDone }: { i: HistoryItem; onDone: (name: string) => void }) {
  const [v, setV] = useState(i.name);
  const ref = useRef<HTMLInputElement | null>(null);
  useEffect(() => ref.current?.select(), []);
  return (
    <>
      <div style={{ pointerEvents: 'none', opacity: 0.6 }}>
        <ProjectTile i={i} />
      </div>
      <input
        ref={ref}
        className="inp rename"
        value={v}
        maxLength={80}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => onDone(v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onDone(v);
          if (e.key === 'Escape') onDone(i.name);
        }}
        aria-label={t('c.rename')}
        data-testid="rename-input"
      />
    </>
  );
}

function Watched() {
  const { client } = useEngine();
  const { reload } = useHistory();
  const { data, reload: again } = useLoad((c) => c.historyConfig(), []);
  const add = async () => {
    const d = await window.desk.openFolder();
    if (!d || !client || !data) return;
    await client.setHistoryWatch([...data.watch, d]);
    again();
    reload();
  };
  return (
    <More summary={t('projects.missing')} testId="watched">
      <p className="muted">{t('projects.watchHint')}</p>
      <div className="col">
        {(data?.watch ?? []).map((w) => (
          <div key={w} className="row">
            <FolderOpen className="ico muted" />
            <span className="clamp1" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              {w}
            </span>
          </div>
        ))}
      </div>
      <button className="btn" style={{ marginTop: 12 }} onClick={() => void add()}>
        <FolderPlus className="ico" />
        {t('projects.addFolder')}
      </button>
    </More>
  );
}
