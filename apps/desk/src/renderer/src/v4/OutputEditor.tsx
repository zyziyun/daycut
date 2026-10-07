// 二次编辑, chat-first (ux/CHAT_EDIT.md direction C) + text-based editing (ux/text-edit): the video on top, the lower
// pane under it - Transcript (Descript mode: select words, Delete = a pending cut, skipped while previewing, one Apply
// = one step) or Timeline - with a resizable split (⌘1 / ⌘2 / ⌘3, drag, double-click), and 「和 AI 一起改」 a column on
// the right (320-560 px, ⌘\ folds it) where every change is a card. A breadcrumb says where the clip lives; arriving
// from the Inbox pins the question in the chat, and "Review all in a row" adds the triage bar. Today's panels
// (裁剪 / 字幕 / 效果 / 标题与封面 / 导出) live on in the optional 「精确编辑」 drawer (E). One filled button on screen:
// Apply cuts while cuts are pending, else the newest draft's 应用, else 导出.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Check, ChevronRight, Contrast, GanttChart, Music, PanelRight, Redo2, Scissors, SkipForward, SlidersHorizontal, Sparkle, Sparkles, Square, Trash2, Type, Undo2, Upload, X, ZoomIn } from 'lucide-react';
import type { ChatDoc } from '../../../shared/chatEdit';
import { EngineError } from '../../../shared/engineClient';
import type { ClipFile, EditOp, EffectDef, OutputDoc } from '../../../shared/v04';
import { fmtClock, getLang, t, type MessageKey } from '../i18n';
import { useEngine } from '../lib/engine';
import { useHistory } from '../lib/history';
import { useInbox } from '../lib/inbox';
import { previewDoc } from '../lib/outputs';
import { snapEdge } from '../lib/timeline';
import { projectHref, triageStep, useTriageState } from '../lib/nav';
import { useRouteQuery } from '../lib/router';
import { markers, type Primary } from '../lib/chatEdit';
import { useTextCuts, draftKey } from '../lib/textCuts';
import { defaultTab, draftCount, draftOps, draftSpans, fixInCue, hasDrafts, joinWords, keepToCuts, keptSeconds, segments, wordRuns, type Drafts } from '../lib/transcript';
import { useSplit, type LowerTab } from '../lib/useSplit';
import { ChatPanel, type ChatApi } from './chat/ChatPanel';
import { Empty, media, Sk } from './kit';
import { LowerPane } from './LowerPane';
import { effectLabel, emsg, errText, setEffectLabels } from './msg';
import { PinnedQuestion } from './PinnedQuestion';
import { Player, type PlayerApi } from './Player';
import { Timeline } from './Timeline';
import { TriageBar } from './TriageBar';
import { MarksChips } from './transcript/MarksMenu';
import { PendingBar } from './transcript/PendingBar';
import { TranscriptPane, type TranscriptApi } from './transcript/TranscriptPane';
import { useStrip, useTranscribe } from '../lib/timelineMedia';
import { isTyping, useUi } from './ui';
import '../theme/uxcore.css';
import './transcript/transcript.css';

type Tab = 'trim' | 'captions' | 'effects' | 'cover' | 'export';
const TABS: [Tab, MessageKey][] = [
  ['trim', 'editor.tab.trim'],
  ['captions', 'editor.tab.captions'],
  ['effects', 'editor.tab.effects'],
  ['cover', 'editor.tab.cover'],
  ['export', 'editor.tab.export'],
];
const TARGETS = ['3:4', '9:16', '16:9'] as const;

function fixedKey(id: string, clip: string) {
  return `ce.fixed.${id}/${clip}`;
}

export function OutputEditor({ id, clip }: { id: string; clip: string }) {
  const { client, subscribe } = useEngine();
  const ui = useUi();
  const q = useRouteQuery();
  const inbox = useInbox();
  const hist = useHistory();
  const triage = useTriageState();
  const [doc, setDoc] = useState<ChatDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('trim');
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [sel, setSel] = useState<{ a: number; b: number } | null>(null);
  const [fxSel, setFxSel] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ ops: EditOp[] | null; compare: boolean }>({ ops: null, compare: false });
  const [drafts, setDrafts] = useState<{ turn: string; ops: EditOp[] }[]>([]);
  const [primary, setPrimary] = useState<Primary>('export');
  const [holdC, setHoldC] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [rendered, setRendered] = useState<{ simulated?: boolean } | null>(null);
  const [drawer, setDrawer] = useState(() => sessionStorage.getItem('ce.drawer') === '1');
  const [effects, setEffects] = useState<EffectDef[]>([]);
  const [flash, setFlash] = useState<{ secs: number; n: number } | null>(null);
  const [edl, setEdl] = useState<{ key: string; keep: [number, number][] } | null>(null);
  const [tsel, setTsel] = useState(false);
  const [find, setFind] = useState({ open: false, q: '', k: -1 });
  const [fixed, setFixed] = useState<Record<number, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem(fixedKey(id, clip)) ?? '{}') as Record<number, string>;
    } catch {
      return {};
    }
  });
  const split = useSplit();
  const cuts = useTextCuts(draftKey(id, clip));
  const pl = useRef<PlayerApi | null>(null);
  const chat = useRef<ChatApi | null>(null);
  const tp = useRef<TranscriptApi | null>(null);
  const stopAt = useRef<number | null>(null);
  const seekedFromQuery = useRef(false);
  const [n, setN] = useState(0);
  const reload = useCallback(() => setN((x) => x + 1), []);

  useEffect(() => {
    if (!client) return;
    let alive = true;
    client
      .output(id, clip)
      .then((d) => alive && (setDoc(d as ChatDoc), setErr(null)))
      .catch((e) => alive && setErr(errText(e)));
    return () => {
      alive = false;
    };
  }, [client, id, clip, n]);
  useEffect(() => {
    if (!client) return;
    void client.effects().then((r) => {
      setEffectLabels(r.effects);
      setEffects(r.effects);
    });
  }, [client]);
  useEffect(() => subscribe((e) => (e.type === 'output-edit' && e.item === id && e.clip === clip ? reload() : undefined)), [subscribe, id, clip, reload]);
  useEffect(() => sessionStorage.setItem('ce.drawer', drawer ? '1' : '0'), [drawer]);
  useEffect(() => localStorage.setItem(fixedKey(id, clip), JSON.stringify(fixed)), [fixed, id, clip]);
  useEffect(() => {
    setSel(null);
    setFxSel(null);
  }, [clip]);
  // arrived with ?t= (an inbox option, a calendar card, ⌘K): go there once the player is ready
  useEffect(() => {
    if (!doc || seekedFromQuery.current || q.t == null) return;
    seekedFromQuery.current = true;
    const at = Number(q.t);
    if (Number.isFinite(at)) window.setTimeout(() => pl.current?.seek(Math.max(0, at - 0.5)), 120);
  }, [doc, q.t]);

  const odoc = doc as unknown as OutputDoc | null;
  const lowerTab: LowerTab = split.layout.tab ?? (odoc ? defaultTab(odoc) : 'transcript');
  const words = useMemo(() => odoc?.words ?? [], [odoc]);
  const pending = hasDrafts(cuts.drafts);
  const dkey = useMemo(() => JSON.stringify(cuts.drafts), [cuts.drafts]);

  // ---------------------------------------------------------------- live skip preview of the pending cuts
  useEffect(() => {
    if (!client || !odoc || !pending) {
      setEdl(null);
      return;
    }
    const ac = new AbortController();
    const tm = window.setTimeout(() => {
      client
        .previewEdl(id, clip, draftOps(odoc.words, cuts.drafts, odoc.words_sig), ac.signal)
        .then((r) => setEdl({ key: dkey, keep: r.keep }))
        .catch(() => undefined);
    }, 100);
    return () => {
      window.clearTimeout(tm);
      ac.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, id, clip, dkey, odoc?.words_sig, odoc?.cuts]);
  const spans = useMemo(() => (odoc ? draftSpans(odoc.words, cuts.drafts) : []), [odoc, cuts.drafts]);
  const appliedKeep = useMemo(() => (odoc ? segments(odoc.duration, odoc.cuts, odoc.trim) : []), [odoc]);
  const keep = useMemo(() => {
    if (!odoc) return [];
    if (!pending) return appliedKeep;
    if (edl?.key === dkey) return edl.keep;
    return segments(odoc.duration, [...odoc.cuts, ...spans.map(([a, b]) => ({ start: a, end: b }))], odoc.trim);
  }, [odoc, pending, appliedKeep, edl, dkey, spans]);
  const speed = odoc?.speed || 1;
  const durNow = keptSeconds(appliedKeep) / speed;
  const durAfter = keptSeconds(keep) / speed;

  const edit = useCallback(
    async (ops: EditOp[], undoToast = false) => {
      if (!client) return false;
      setBusy('edit');
      try {
        const r = await client.editOutput(id, clip, ops);
        setRendered(null);
        reload();
        const w = r.warnings?.[0];
        if (w) ui.toast(emsg(w));
        else if (undoToast)
          ui.toast(r.step?.describe?.map(emsg).join(' · ') || t('editor.saved'), {
            undo: async () => {
              await client.undoOutput(id, clip);
              reload();
            },
          });
        return true;
      } catch (e) {
        ui.toast(errText(e), { error: true });
        return false;
      } finally {
        setBusy(null);
      }
    },
    [client, id, clip, reload, ui],
  );
  const undo = useCallback(
    async (steps = 1, redo = false) => {
      if (!client) return;
      try {
        await (redo ? client.redoOutput(id, clip, steps) : client.undoOutput(id, clip, steps));
        setRendered(null);
        reload();
      } catch (e) {
        ui.toast(errText(e), { error: true });
      }
    },
    [client, id, clip, reload, ui],
  );

  // ---------------------------------------------------------------- Apply the pending cuts (one step + a chat card)
  const applyCuts = useCallback(async () => {
    if (!client || !odoc || !pending || busy) return;
    const ops = draftOps(odoc.words, cuts.drafts, odoc.words_sig);
    if (!ops.length) return cuts.clear();
    setBusy('cuts');
    try {
      const r = await client.editOutput(id, clip, ops, null, { by: 'you', note: 'transcript' });
      const said = wordRuns(cuts.drafts)
        .map(([a, b]) => joinWords(odoc.words, a, b))
        .join(' / ');
      if (r.step?.id)
        await client
          .addChatTurn(id, clip, { role: 'user', card: 'transcript', status: 'applied', applied_step: r.step.id, applied_ops: ops.length, text: said.slice(0, 1800), reply: JSON.stringify({ before: Math.round(durNow * 10) / 10, after: Math.round(durAfter * 10) / 10, phrases: wordRuns(cuts.drafts).length, pauses: ops.length - wordRuns(cuts.drafts).length, secs: Math.round((durNow - durAfter) * 10) / 10 }) })
          .catch(() => undefined);
      cuts.clear();
      setRendered(null);
      reload();
      const w = r.warnings?.find((x) => x.code !== 'source-changed');
      if (w) ui.toast(emsg(w));
    } catch (e) {
      if (e instanceof EngineError && e.code === 'stale-words') {
        cuts.clear();
        reload();
      }
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(null);
    }
  }, [client, odoc, pending, busy, cuts, id, clip, durNow, durAfter, reload, ui]);
  const restoreCut = useCallback(
    async (index: number) => {
      if (!client) return;
      try {
        await client.editOutput(id, clip, [{ op: 'cut_remove', index }], null, { by: 'you', note: 'transcript' });
        reload();
      } catch (e) {
        ui.toast(errText(e), { error: true });
      }
    },
    [client, id, clip, reload, ui],
  );
  const fixWord = useCallback(
    async (i: number, text: string) => {
      if (!odoc) return false;
      const w = odoc.words[i];
      const mid = (w.t + w.te) / 2;
      const cue = odoc.captions.find((c) => !c.removed && !c.added && mid >= c.start - 0.05 && mid <= c.end + 0.05);
      const next = cue ? fixInCue(cue.text, fixed[i] ?? w.w, text) : null;
      if (!cue || next == null) {
        ui.toast(t('te.fixNoCue'), { error: true });
        return false;
      }
      const ok = await edit([{ op: 'caption_text', cue: cue.id, text: next, force: true } as unknown as EditOp], true);
      if (ok) setFixed((f) => ({ ...f, [i]: text }));
      return ok;
    },
    [odoc, fixed, edit, ui],
  );

  // ---------------------------------------------------------------- find (⌘F)
  const hits = useMemo(() => {
    const s = new Set<number>();
    const needle = find.q.trim().toLowerCase();
    if (!find.open || !needle) return s;
    let text = '';
    const owner: number[] = [];
    words.forEach((w, i) => {
      for (const ch of w.w.toLowerCase()) {
        text += ch;
        owner.push(i);
      }
    });
    let k = text.indexOf(needle);
    while (k >= 0) {
      for (let j = k; j < k + needle.length; j++) s.add(owner[j]);
      k = text.indexOf(needle, k + needle.length);
    }
    return s;
  }, [find.open, find.q, words]);
  const hitStarts = useMemo(() => [...hits].filter((i) => !hits.has(i - 1)).sort((a, b) => a - b), [hits]);

  // keys (§5.10 + text-edit §3): ⌘1/2/3 layout, ⌘\ chat, ⌘E transcript / timeline, ⌘F find, ⌘↵ apply, ⌘Z / ⇧⌘Z,
  // hold C original, E precise edit (fix text while words are selected), / the chat, Esc
  const keysRef = useRef<(e: KeyboardEvent) => void>(() => undefined);
  keysRef.current = (e: KeyboardEvent) => {
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key.toLowerCase();
    if (mod && !e.shiftKey && !e.altKey && ['1', '2', '3'].includes(e.key)) {
      e.preventDefault();
      e.stopImmediatePropagation(); // not the app's ⌘1-⌘4 navigation while editing
      split.setPreset((['watch', 'balanced', 'edit'] as const)[Number(e.key) - 1]);
      return;
    }
    if (mod && e.key === '\\') {
      e.preventDefault();
      split.toggleChat();
      return;
    }
    if (mod && k === 'e' && !e.shiftKey) {
      e.preventDefault();
      split.setTab(lowerTab === 'transcript' ? 'timeline' : 'transcript');
      return;
    }
    if (mod && k === 'f' && lowerTab === 'transcript' && words.length) {
      e.preventDefault();
      setFind((f) => ({ ...f, open: true }));
      return;
    }
    if (mod && e.key === 'Enter') {
      e.preventDefault();
      if (pending) void applyCuts();
      else chat.current?.applyLatest();
      return;
    }
    if (document.querySelector('.scrim, .ctx')) return;
    if (isTyping(e.target)) return;
    if (mod && k === 'z') {
      e.preventDefault();
      if (e.shiftKey && cuts.canRedo) cuts.redo();
      else if (!e.shiftKey && cuts.canUndo && pending) cuts.undo();
      else void undo(1, e.shiftKey);
    } else if (!mod && e.key === '/') {
      e.preventDefault();
      chat.current?.focus('/');
    } else if (!mod && !e.altKey && k === 'e') {
      if (tsel) return; // the transcript's fix-text
      setDrawer((d) => !d);
    } else if (!mod && !e.altKey && k === 'c' && !e.repeat) {
      setHoldC(true);
    } else if (e.key === 'Escape') {
      if (tsel) return;
      if (chat.current?.escape()) return;
      if (drawer) setDrawer(false);
      else {
        setSel(null);
        pl.current?.setSelection(null);
        setFxSel(null);
      }
    }
  };
  useEffect(() => {
    const down = (e: KeyboardEvent) => keysRef.current(e);
    const up = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'c') setHoldC(false);
    };
    window.addEventListener('keydown', down, true);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down, true);
      window.removeEventListener('keyup', up);
    };
  }, []);

  const render = async (quality: 'preview' | 'final' = 'preview', targets = 'primary') => {
    if (!client) return;
    setBusy('render');
    try {
      const r = await client.renderOutput(id, clip, { quality, targets });
      setRendered({ simulated: r.simulated });
      reload();
    } catch (e) {
      ui.toast(errText(e), { error: true });
    } finally {
      setBusy(null);
    }
  };
  const playRange = useCallback((a: number, b: number) => {
    pl.current?.seek(a);
    stopAt.current = b;
    pl.current?.play();
  }, []);
  const onTime = useCallback((x: number) => {
    setTime(x);
    if (stopAt.current != null && x >= stopAt.current) {
      stopAt.current = null;
      pl.current?.pause();
    }
  }, []);
  const onSkip = useCallback((secs: number) => setFlash((f) => ({ secs, n: (f?.n ?? 0) + 1 })), []);
  useEffect(() => {
    if (!flash) return;
    const tm = window.setTimeout(() => setFlash(null), 1200);
    return () => window.clearTimeout(tm);
  }, [flash]);
  const { strip, failed: stripFailed } = useStrip(client, id, clip, doc?.files[0]?.path ?? null);
  const transcribe = useTranscribe(client, subscribe, id, clip, reload);
  const onPreview = useCallback((v: { ops: EditOp[] | null; compare: boolean }) => setPreview(v), []);
  const setTextDrafts = useCallback((f: (d: Drafts) => Drafts) => cuts.set(f), [cuts]);
  const jumpWord = useCallback(
    (i: number) => {
      const w = odoc?.words[i];
      if (!w) return;
      pl.current?.seek(w.t);
      tp.current?.reveal(i);
    },
    [odoc],
  );

  const view = useMemo(() => (odoc ? previewDoc(odoc, holdC ? null : preview.ops) : null), [odoc, preview.ops, holdC]);
  const marks = useMemo(() => (odoc ? markers(odoc, drafts) : []), [odoc, drafts]);
  const project = hist.data?.items.find((x) => x.id === id);
  const pinItem = q.item ? inbox.items.find((x) => x.key === q.item) ?? null : null;
  const triageItem = triage ? inbox.items.find((x) => x.key === triage.keys[triage.i]) ?? null : null;
  if (err && !doc)
    return (
      <div className="pg">
        <a className="back" href={projectHref(id)}>
          <ArrowLeft className="ico" />
          {t('c.back')}
        </a>
        <Empty title={err} />
      </div>
    );
  if (!doc || !view || !odoc)
    return (
      <div className="ce" aria-busy="true" style={{ ['--ce-chat' as string]: `${split.layout.chatW}px` }}>
        <div className="ce-top">
          <Sk h={20} w={260} />
        </div>
        <div className="ce-main">
          <div className="ce-stage">
            <div className="sk" style={{ flex: 1, minHeight: 300, borderRadius: 10 }} />
          </div>
          <div className="ce-tl">
            <Sk h={90} />
          </div>
        </div>
        <span />
        <aside className="cc">
          <div className="cc-log">
            <Sk h={14} w="70%" />
            <Sk h={52} />
            <Sk h={52} />
          </div>
        </aside>
      </div>
    );

  const fresh = doc.renders.filter((r) => r.fresh && !r.simulated);
  // the transcript speaks in the original's seconds: while it is open (or cuts are pending) the player plays the
  // original and previews every cut by skipping it; otherwise the newest render leads
  const sourceTimes = lowerTab === 'transcript' || pending;
  const useFresh = fresh.length > 0 && !sourceTimes;
  const files: ClipFile[] = useFresh
    ? [...fresh.map((r) => ({ path: r.file, aspect: r.target === 'primary' ? (doc.files[0]?.aspect ?? '3:4') : r.target, label: t('editor.editedVersion') })), ...doc.files.map((f) => ({ ...f, label: t('c.original') }))]
    : doc.files;
  const playerCuts = useFresh ? [] : [...view.cuts, ...(pending ? keepToCuts(keep, doc.duration).filter((c) => !view.cuts.some((v) => Math.abs(v.start - c.start) < 0.01 && Math.abs(v.end - c.end) < 0.01)) : [])];
  const dirty = doc.steps.length > 0 && !doc.renders.some((r) => r.fresh);
  const capsNote = doc.caps_notes.find((m) => m.code === 'captions-add-only') ?? doc.caps_notes.find((m) => m.code === 'flattened');
  const firstWord = doc.words.find((w) => w.w.length >= 2)?.w;
  const aspect = doc.files[0]?.aspect;
  const compare = preview.compare && !holdC && preview.ops ? { effects: odoc.effects, labels: [t('ce.before'), t('ce.after')] as [string, string] } : null;
  const nPending = draftCount(cuts.drafts);
  const canFix = !!doc.caps.caption_text && doc.captions.some((c) => !c.added);
  const cutNote = doc.mode === 'flattened' && doc.caps.cut_strategy === 'snap_captions' ? t('te.note.snap') : null;
  const stageRows = `minmax(0, ${split.stage}fr) 8px minmax(${180}px, ${1 - split.stage}fr)`;

  return (
    <div className={`ce-wrap ${triage && q.triage ? 'triage' : ''}`}>
      {triage && q.triage === '1' && <TriageBar item={triageItem} items={inbox.items} />}
      <div className={`ce ${split.collapsed ? 'cc-folded' : ''}`} data-testid="editor" style={{ ['--ce-chat' as string]: `${split.collapsed ? 48 : split.layout.chatW}px` }}>
        <header className="ce-top">
          <a className="btn ghost icon sm" href={projectHref(id)} aria-label={t('c.back')} data-testid="editor-back">
            <ArrowLeft className="ico" />
          </a>
          <nav className="ux-crumbs ce-crumbs" aria-label={t('nav.where')} data-testid="editor-breadcrumb">
            <a className="crumb" href={projectHref(id)} data-testid="crumb-project">
              {project?.name ?? t('nav.projects')}
            </a>
            <ChevronRight className="ico sep" />
            <span className="crumb here">
              {doc.cover && <img src={media(doc.cover)} alt="" />}
              <h1 className="clamp1" lang="zh-CN" data-testid="editor-title">
                {doc.title}
              </h1>
            </span>
          </nav>
          <span className="meta" data-testid="editor-length">
            {pending && Math.abs(durNow - durAfter) > 0.05 ? (
              <>
                {fmtClock(durNow)} <span className="arrow">→ {fmtClock(durAfter)}</span>
              </>
            ) : (
              fmtClock(durNow || doc.duration)
            )}{' '}
            · {/^\d+:\d+$/.test(aspect ?? '') ? aspect! : t('c.original')}
          </span>
          <span className="sp" />
          <div className="grp">
            <button className="btn ghost icon sm" disabled={!doc.undo && !(pending && cuts.canUndo)} onClick={() => (pending && cuts.canUndo ? cuts.undo() : void undo())} aria-label={t('c.undo')} data-tip={`${t('c.undo')} · ⌘Z`} data-testid="editor-undo">
              <Undo2 className="ico" />
            </button>
            <button className="btn ghost icon sm" disabled={!doc.redo && !cuts.canRedo} onClick={() => (cuts.canRedo ? cuts.redo() : void undo(1, true))} aria-label={t('c.redo')} data-tip={`${t('c.redo')} · ⇧⌘Z`} data-testid="editor-redo">
              <Redo2 className="ico" />
            </button>
          </div>
          <button className={`btn ghost ${drawer ? 'toggle on' : ''}`} onClick={() => setDrawer(!drawer)} aria-pressed={drawer} data-tip={`${t('ce.preciseTip')} · E`} data-testid="toggle-precise">
            <SlidersHorizontal className="ico" />
            {t('ce.precise')}
          </button>
          <button className={`btn ${primary === 'export' && !pending ? 'primary' : ''}`} onClick={() => chat.current?.openCard('export')} disabled={doc.caps.export === false} data-testid="editor-export">
            <Upload className="ico" />
            {t('ce.export')}
          </button>
        </header>
        <main className="ce-main ce-split3" ref={split.ref} style={{ gridTemplateRows: stageRows }}>
          <section className="ce-stage">
            <Player
              ref={pl}
              key={files.map((f) => f.path).join('|')}
              files={files}
              fps={doc.fps}
              duration={doc.duration}
              captions={doc.captions.map((c) => ({ ...c }))}
              captionStyle={doc.caption_style}
              effects={view.effects}
              cuts={playerCuts}
              trim={useFresh ? null : view.trim}
              onTime={onTime}
              onPlaying={setPlaying}
              onSkip={onSkip}
              strip={strip}
              ticks={[...marks.map((m) => ({ t: m.a, b: m.b, tone: m.tone })), ...spans.map(([a, b]) => ({ t: a, b, tone: 'draft' as const }))]}
              onSelection={setSel}
              compare={compare}
              badge={holdC ? t('ce.original') : null}
              testId="editor-player"
            />
            {flash && (
              <div key={flash.n} className="ce-flash" data-testid="skip-flash">
                <SkipForward className="ico" />
                {t('te.skippedS', { s: flash.secs.toFixed(1) })}
              </div>
            )}
          </section>
          <div
            className="ce-hsplit"
            role="separator"
            aria-orientation="horizontal"
            aria-label={t('te.dividerTip')}
            data-tip={t('te.dividerTip')}
            onPointerDown={split.dragDivider}
            onDoubleClick={split.reset}
            data-testid="split-divider"
          >
            <i />
          </div>
          <LowerPane
            tab={lowerTab}
            onTab={split.setTab}
            preset={split.layout.preset}
            onPreset={split.setPreset}
            chips={words.length ? <MarksChips doc={odoc} drafts={cuts.drafts} setDrafts={setTextDrafts} onJump={jumpWord} /> : null}
            search={
              words.length
                ? {
                    open: find.open,
                    q: find.q,
                    n: hitStarts.length,
                    setOpen: (v) => setFind((f) => ({ ...f, open: v, q: v ? f.q : '' })),
                    setQ: (s) => setFind((f) => ({ ...f, q: s, k: -1 })),
                    next: () => {
                      if (!hitStarts.length) return;
                      const k = (find.k + 1) % hitStarts.length;
                      setFind((f) => ({ ...f, k }));
                      jumpWord(hitStarts[k]);
                    },
                    cutAll: () => setTextDrafts((d) => ({ words: { ...d.words, ...Object.fromEntries([...hits].map((i) => [i, d.words[i] ?? 'transcript'])) }, gaps: d.gaps })),
                  }
                : null
            }
            footer={
              pending ? (
                <PendingBar n={nPending} secs={Math.max(0, durNow - durAfter)} tooShort={durAfter < 1} note={cutNote} busy={busy === 'cuts'} onDiscard={() => cuts.clear()} onApply={() => void applyCuts()} />
              ) : null
            }
          >
            {lowerTab === 'transcript' ? (
              <TranscriptPane
                doc={odoc}
                time={time}
                playing={playing}
                drafts={cuts.drafts}
                setDrafts={setTextDrafts}
                seek={(x) => pl.current?.seek(x)}
                playFrom={(x) => {
                  pl.current?.seek(x);
                  pl.current?.play();
                }}
                fixed={fixed}
                canFix={canFix}
                fixWhyNot={doc.mode === 'flattened' ? t('te.fixBurned') : t('te.fixNoCaptions')}
                onFix={fixWord}
                onRestoreCut={(i) => void restoreCut(i)}
                transcribe={transcribe}
                hits={find.open ? hits : undefined}
                apiRef={tp}
                onSelection={setTsel}
                onDiscardAll={() => pending && window.confirm(t('te.discardAll')) && cuts.clear()}
              />
            ) : (
              <div className="ce-tl">
                <Timeline
                  doc={view}
                  time={time}
                  playing={playing}
                  selection={sel}
                  selectedFx={fxSel}
                  strip={strip}
                  stripFailed={stripFailed}
                  transcribe={transcribe}
                  defs={effects}
                  pending={spans}
                  fill
                  header={
                    marks.some((m) => m.tone === 'draft') || doc.steps.length || pending ? (
                      <>
                        <span className="lg">
                          <i className="d" />
                          {t('ce.legend.draft')}
                        </span>
                        <span className="lg">
                          <i className="a" />
                          {t('ce.legend.applied')}
                        </span>
                        {preview.compare && <span>{t('ce.holdC')}</span>}
                      </>
                    ) : doc.words.length ? (
                      <span>{t('ce.tlHint')}</span>
                    ) : null
                  }
                  markers={marks}
                  onMarker={(turn) => chat.current?.focusTurn(turn)}
                  onSeek={(x) => pl.current?.seek(x)}
                  onSelect={(s) => {
                    setSel(s);
                    pl.current?.setSelection(s);
                  }}
                  onSelectFx={(f) => {
                    setFxSel(f);
                    if (f) setTab('effects');
                  }}
                  onMoveFx={(fx, start, end) => void edit([{ op: 'effect_update', id: fx.id, start, end }])}
                  onTrim={(a, b) => void edit([{ op: 'trim', start: a, end: b }])}
                />
              </div>
            )}
          </LowerPane>
        </main>
        <div
          className="ce-split"
          role="separator"
          aria-orientation="vertical"
          aria-label={t('ce.resize')}
          onPointerDown={(e) => {
            if (split.collapsed) return;
            const x0 = e.clientX;
            const w0 = split.layout.chatW;
            const el = e.currentTarget;
            el.classList.add('on');
            const mv = (ev: PointerEvent) => split.setChatW(w0 - (ev.clientX - x0));
            const up = () => {
              el.classList.remove('on');
              window.removeEventListener('pointermove', mv);
              window.removeEventListener('pointerup', up);
            };
            window.addEventListener('pointermove', mv);
            window.addEventListener('pointerup', up);
          }}
          onDoubleClick={() => split.setChatW(400)}
          data-testid="chat-resize"
        />
        <ChatPanel
          ref={chat}
          item={id}
          clip={clip}
          doc={doc}
          defs={effects}
          time={time}
          sel={sel}
          fxSel={fxSel}
          onClearSel={() => (setSel(null), pl.current?.setSelection(null))}
          onClearFx={() => setFxSel(null)}
          seek={(x) => pl.current?.seek(x)}
          playRange={playRange}
          reload={() => (setRendered(null), reload())}
          onDrafts={setDrafts}
          onPreview={onPreview}
          onPrimary={setPrimary}
          collapsed={split.collapsed}
          onToggle={split.toggleChat}
          onShowInTranscript={(x) => {
            split.setTab('transcript');
            pl.current?.seek(x);
            window.setTimeout(() => {
              const i = odoc.words.findIndex((w) => w.te >= x);
              if (i >= 0) tp.current?.reveal(i);
            }, 80);
          }}
          pinned={
            pinItem ? (
              <PinnedQuestion
                key={pinItem.key}
                item={pinItem}
                items={inbox.items}
                clip={clip}
                seek={(x) => {
                  pl.current?.seek(Math.max(0, x - 3));
                  pl.current?.play();
                }}
                onSkip={() => (triage ? triageStep(inbox.items, 1) : history.back())}
              />
            ) : null
          }
        />
        {drawer && (
          <section className="ce-drawer" data-testid="edit-panel">
            <div className="dh">
              <b>{t('ce.drawer.title')}</b>
              <span className="sp" />
              <button className="btn ghost icon sm" onClick={() => setDrawer(false)} aria-label={t('ce.drawer.close')} data-testid="close-precise">
                <X className="ico" />
              </button>
            </div>
            <nav className="tabs4" role="tablist">
              {TABS.map(([k, label]) => (
                <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)} data-testid={`etab-${k}`}>
                  {t(label)}
                </button>
              ))}
            </nav>
            <div className="body">
              {tab === 'trim' && <TrimPanel doc={view} time={time} sel={sel} edit={edit} onClearSel={() => (setSel(null), pl.current?.setSelection(null))} />}
              {tab === 'captions' && <CaptionsPanel doc={odoc} note={capsNote ? emsg(capsNote) : null} edit={edit} time={time} sel={sel} />}
              {tab === 'effects' && <EffectsPanel doc={odoc} defs={effects} time={time} sel={sel} fxSel={fxSel} setFxSel={setFxSel} edit={edit} firstWord={firstWord} />}
              {tab === 'cover' && <CoverPanel doc={odoc} time={time} edit={edit} />}
              {tab === 'export' && <ExportPanel doc={odoc} edit={edit} onFinal={() => void render('final', 'all')} busy={busy === 'render'} />}
              <Edits doc={odoc} onUndoTo={(k) => void undo(doc.steps.length - k)} />
            </div>
            <div className="foot">
              <span className="muted sp" data-testid="render-state">
                {busy === 'render'
                  ? t('editor.rendering')
                  : rendered?.simulated
                    ? t('editor.simulated')
                    : rendered
                      ? t('editor.rendered', { v: doc.steps.length })
                      : dirty
                        ? t('editor.unrendered', { n: doc.steps.length })
                        : t('editor.upToDate')}
              </span>
              <button className="btn" disabled={busy === 'render' || !doc.steps.length} onClick={() => void render()} data-testid="render">
                {busy === 'render' ? t('editor.rendering') : t('editor.render')}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

type EditFn = (ops: EditOp[], undoToast?: boolean) => Promise<boolean>;

function TrimPanel({ doc, time, sel, edit, onClearSel }: { doc: OutputDoc; time: number; sel: { a: number; b: number } | null; edit: EditFn; onClearSel: () => void }) {
  const a = doc.trim?.start ?? 0;
  const b = doc.trim?.end ?? doc.duration;
  const snap = (x: number) => snapEdge(doc.words, x);
  return (
    <div className="col" style={{ gap: 16 }} data-testid="trim-panel">
      <div className="field4">
        <span className="lbl">{t('editor.tab.trim')}</span>
        <b style={{ fontWeight: 500 }} className="num" data-testid="trim-range">
          {t('editor.keep', { a: fmtClock(a, true), b: fmtClock(b, true) })}
        </b>
        <div className="row">
          <button className="btn" disabled={!doc.caps.trim} onClick={() => void edit([{ op: 'trim', start: snap(time), end: b }])} data-testid="trim-start-here">
            {t('editor.startHere')}
          </button>
          <button className="btn" disabled={!doc.caps.trim} onClick={() => void edit([{ op: 'trim', start: a, end: snap(time) }])} data-testid="trim-end-here">
            {t('editor.endHere')}
          </button>
          {doc.trim && (
            <button className="btn ghost" onClick={() => void edit([{ op: 'trim', start: null, end: null }])}>
              {t('editor.resetTrim')}
            </button>
          )}
        </div>
      </div>
      {doc.caps.cut !== false && (
        <div className="field4">
          <span className="lbl">{t('editor.cuts', { n: doc.cuts.length })}</span>
          <span className="muted">{t('editor.cutHint')}</span>
          <div className="row">
            <span className="muted num sp">{sel ? t('editor.selection', { a: fmtClock(sel.a, true), b: fmtClock(sel.b, true) }) : t('editor.noSelection')}</span>
            <button
              className="btn"
              disabled={!sel}
              onClick={async () => {
                if (sel && (await edit([{ op: 'cut', start: sel.a, end: sel.b }], true))) onClearSel();
              }}
              data-testid="cut-selection"
            >
              <Scissors className="ico" />
              {t('editor.cutSel')}
            </button>
          </div>
          {doc.cuts.map((c) => (
            <div key={c.index} className="row oplist">
              <span className="num sp">
                {fmtClock(c.start, true)} – {fmtClock(c.end, true)}
              </span>
              <button className="btn ghost sm" onClick={() => void edit([{ op: 'cut_remove', index: c.index }], true)} aria-label={t('c.remove')}>
                <Trash2 className="ico" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CaptionsPanel({ doc, note, edit, time, sel }: { doc: OutputDoc; note: string | null; edit: EditFn; time: number; sel: { a: number; b: number } | null }) {
  const ours = !!doc.caps.caption_text;
  const [text, setText] = useState('');
  const added = doc.captions.filter((c) => c.added);
  const style = doc.caption_style ?? {};
  return (
    <div className="col" style={{ gap: 16 }} data-testid="captions-panel">
      {!ours && <div className="note" data-testid="caps-note">{note ?? t('editor.flattened')}</div>}
      {(ours || added.length > 0) && (
        <>
          <div className="field4">
            <span className="lbl">{t('editor.capSize')}</span>
            <input type="range" min={0.6} max={1.8} step={0.05} defaultValue={style.size ?? 1} onChange={(e) => void edit([{ op: 'caption_style', style: { size: Number(e.target.value) } }])} aria-label={t('editor.capSize')} />
          </div>
          <div className="row">
            <label className="field4">
              <span className="lbl">{t('editor.capColor')}</span>
              <input type="color" defaultValue={style.color ?? '#FFFFFF'} onChange={(e) => void edit([{ op: 'caption_style', style: { color: e.target.value.toUpperCase() } }])} />
            </label>
            <label className="field4">
              <span className="lbl">{t('editor.capKeyword')}</span>
              <input type="color" defaultValue={style.highlight ?? '#FFD60A'} onChange={(e) => void edit([{ op: 'caption_style', style: { highlight: e.target.value.toUpperCase() } }])} />
            </label>
          </div>
          <div className="field4">
            <span className="lbl">{t('editor.capPos')}</span>
            <div className="seg">
              {(['bottom', 'middle', 'top'] as const).map((p) => (
                <button key={p} className={(style.position ?? 'bottom') === p ? 'on' : ''} onClick={() => void edit([{ op: 'caption_style', style: { position: p } }])}>
                  {t(`editor.pos.${p}` as MessageKey)}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
      {ours && (
        <div className="field4">
          <span className="lbl">{t('editor.capText')}</span>
          {doc.captions
            .filter((c) => !c.added)
            .map((c) => (
              <input key={c.id} className="inp" defaultValue={c.text} lang="zh-CN" onBlur={(e) => e.target.value.trim() !== c.text && void edit([{ op: 'caption_text', cue: c.id, text: e.target.value.trim() }])} />
            ))}
        </div>
      )}
      {doc.caps.caption_add && (
        <div className="field4">
          <span className="lbl">{t('editor.capAdd')}</span>
          <div className="row">
            <input className="inp sp" value={text} onChange={(e) => setText(e.target.value)} placeholder={t('editor.capAddHint')} data-testid="caption-add-text" />
            <button
              className="btn"
              disabled={!text.trim()}
              onClick={async () => {
                const a = sel?.a ?? time;
                const b = sel?.b ?? Math.min(doc.duration, time + 2.5);
                if (await edit([{ op: 'caption_add', start: a, end: b, text: text.trim() }])) setText('');
              }}
            >
              {t('editor.capAddBtn')}
            </button>
          </div>
          {added.map((c) => (
            <div key={c.id} className="row oplist">
              <span className="num faint">{fmtClock(c.start, true)}</span>
              <span className="sp clamp1" lang="zh-CN">
                {c.text}
              </span>
              <button className="btn ghost sm" onClick={() => void edit([{ op: 'caption_remove', cue: c.id }], true)} aria-label={t('c.remove')}>
                <Trash2 className="ico" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function paramLabel(key: string, sch: { 'x-zh'?: string }): string {
  const k = `fxp.${key}` as MessageKey;
  const own = t(k);
  if (own !== k) return own;
  return getLang() === 'zh-CN' && sch['x-zh'] ? sch['x-zh'].replace(/\s*[(（].*$/, '') : key;
}

function EffectsPanel({
  doc,
  defs,
  time,
  sel,
  fxSel,
  setFxSel,
  edit,
  firstWord,
}: {
  doc: OutputDoc;
  defs: EffectDef[];
  time: number;
  sel: { a: number; b: number } | null;
  fxSel: string | null;
  setFxSel: (id: string | null) => void;
  edit: EditFn;
  firstWord?: string;
}) {
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [pick, setPick] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const cats = [...new Set(defs.map((d) => d.category ?? 'other'))];
  const shown = defs.filter((d) => (!cat || d.category === cat) && (!q || `${d.label.en} ${d.label.zh} ${d.id}`.toLowerCase().includes(q.toLowerCase())));
  const def = defs.find((d) => d.id === pick);
  const inst = doc.effects.find((e) => e.id === fxSel);
  const instDef = inst ? defs.find((d) => d.id === inst.effect) : undefined;
  useEffect(() => {
    if (!def) return;
    const p: Record<string, unknown> = {};
    for (const [k, s] of Object.entries(def.params)) p[k] = s.default ?? (s.type === 'string' ? '' : null);
    if ('text' in def.params && !p.text && firstWord) p.text = firstWord;
    setParams(p);
  }, [def, firstWord]);
  const add = async (where: 'playhead' | 'sel') => {
    if (!def) return;
    const start = where === 'sel' && sel ? sel.a : time;
    const op: EditOp = { op: 'effect_add', effect: def.id, start: Math.round(start * 1000) / 1000, params: Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null)) };
    if (where === 'sel' && sel) op.end = sel.b;
    await edit([op]);
  };
  return (
    <div className="col" style={{ gap: 16 }} data-testid="effects-panel">
      {doc.caps.effects === false ? (
        <div className="note">{t('editor.fxOff')}</div>
      ) : (
        <>
          <input className="inp" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('editor.fxSearch')} aria-label={t('editor.fxSearch')} />
          <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
            <button className={`chip ${!cat ? 'on' : ''}`} onClick={() => setCat('')}>
              {t('editor.fxAll')}
            </button>
            {cats.map((c) => (
              <button key={c} className={`chip ${cat === c ? 'on' : ''}`} onClick={() => setCat(c)}>
                {t(`fx.cat.${c}` as MessageKey) === `fx.cat.${c}` ? c : t(`fx.cat.${c}` as MessageKey)}
              </button>
            ))}
          </div>
          <div className="fxgrid" data-testid="fx-catalogue">
            {shown.map((d) => (
              <button key={d.id} className={`fx ${pick === d.id ? 'on' : ''}`} onClick={() => setPick(pick === d.id ? null : d.id)} title={getLang() === 'zh-CN' ? d.description?.zh : d.description?.en} data-testid="fx-item" data-fx={d.id}>
                <span className={`pv ${previewKind(d)}`}>
                  {d.thumbnail ? <img src={window.desk.mediaUrl(d.thumbnail)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <i>{previewGlyph(d)}</i>}
                </span>
                <span className="clamp1">{effectLabel(d.id, d.label)}</span>
              </button>
            ))}
          </div>
          {def && (
            <div className="card" style={{ padding: 12 }} data-testid="fx-params">
              <b style={{ fontWeight: 500 }}>{effectLabel(def.id, def.label)}</b>
              <div className="muted">{getLang() === 'zh-CN' ? def.description?.zh : def.description?.en}</div>
              <ParamFields schema={def.params} values={params} onChange={setParams} />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn" onClick={() => void add('playhead')} data-testid="fx-add-playhead">
                  {t('editor.fxAddPlayhead')}
                </button>
                <button className="btn" disabled={!sel} onClick={() => void add('sel')}>
                  {t('editor.fxAddSel')}
                </button>
              </div>
            </div>
          )}
          <div className="field4">
            <span className="lbl">{t('editor.fxOnClip')}</span>
            {!doc.effects.length && <span className="muted">{t('editor.fxNone')}</span>}
            <div className="fxlist">
              {doc.effects.map((e) => (
                <div key={e.id} className="li" onClick={() => setFxSel(e.id)} style={{ cursor: 'pointer', fontWeight: e.id === fxSel ? 500 : 400 }} data-testid="fx-instance">
                  <span className="num faint">{fmtClock(e.start, true)}</span>
                  <span className="sp clamp1">
                    {effectLabel(e.effect, e.label)}
                    {typeof e.params?.text === 'string' && e.params.text ? ` · ${e.params.text}` : ''}
                  </span>
                  <button className="btn ghost sm" onClick={(ev) => (ev.stopPropagation(), void edit([{ op: 'effect_remove', id: e.id }], true))} aria-label={t('editor.fxRemove')}>
                    <Trash2 className="ico" />
                  </button>
                </div>
              ))}
            </div>
            {inst && instDef && (
              <div className="card" style={{ padding: 12 }}>
                <ParamFields schema={instDef.params} values={inst.params} onCommit={(k, v) => void edit([{ op: 'effect_update', id: inst.id, params: { [k]: v } }])} />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function previewGlyph(d: EffectDef) {
  const k = previewKind(d);
  const Icon = { pop: Type, zoom: ZoomIn, slide: PanelRight, bar: GanttChart, glow: Square, flash: Sparkle, pulse: Music, fade: Contrast }[k] ?? Sparkle;
  return <Icon className="ico lg" />;
}

function previewKind(d: EffectDef): string {
  if (/pop|stamp|badge|sticker|overlay/.test(d.id)) return 'pop';
  if (/punch|zoom/.test(d.id)) return 'zoom';
  if (/panel|card|callout|bubble/.test(d.id)) return 'slide';
  if (/progress/.test(d.id)) return 'bar';
  if (/box/.test(d.id)) return 'glow';
  if (/xfade|fade|flash/.test(d.id)) return 'flash';
  if (/sfx|music/.test(d.id)) return 'pulse';
  return 'fade';
}

function ParamFields({
  schema,
  values,
  onChange,
  onCommit,
}: {
  schema: EffectDef['params'];
  values: Record<string, unknown>;
  onChange?: (v: Record<string, unknown>) => void;
  onCommit?: (k: string, v: unknown) => void;
}) {
  const set = (k: string, v: unknown, commit = false) => {
    onChange?.({ ...values, [k]: v });
    if (commit) onCommit?.(k, v);
  };
  const keys = Object.keys(schema).filter((k) => !['x', 'y', 'angle', 'in_dur', 'out_dur', 'arrow_x', 'arrow_y', 'w', 'h', 'width'].includes(k));
  return (
    <div className="col" style={{ gap: 8, marginTop: 8 }}>
      {keys.map((k) => {
        const s = schema[k];
        const v = values[k];
        const label = paramLabel(k, s);
        if (s.enum)
          return (
            <label key={k} className="field4">
              <span className="lbl">{label}</span>
              <select className="inp" value={String(v ?? s.default ?? '')} onChange={(e) => set(k, e.target.value, true)}>
                {s.enum.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
          );
        if (s.type === 'number')
          return (
            <label key={k} className="field4">
              <span className="lbl">
                {label} <span className="num">{typeof v === 'number' ? Math.round(v * 100) / 100 : ''}</span>
              </span>
              <input type="range" min={s.minimum ?? 0} max={s.maximum ?? 1} step={((s.maximum ?? 1) - (s.minimum ?? 0)) / 50} value={Number(v ?? s.default ?? 0)} onChange={(e) => set(k, Number(e.target.value))} onMouseUp={(e) => onCommit?.(k, Number((e.target as HTMLInputElement).value))} />
            </label>
          );
        if (s.format === 'color')
          return (
            <label key={k} className="field4">
              <span className="lbl">{label}</span>
              <input type="color" value={typeof v === 'string' && v ? v : '#FFD60A'} onChange={(e) => set(k, e.target.value.toUpperCase(), true)} />
            </label>
          );
        return (
          <label key={k} className="field4">
            <span className="lbl">{label}</span>
            <input className="inp" value={String(v ?? '')} onChange={(e) => set(k, e.target.value)} onBlur={(e) => onCommit?.(k, e.target.value)} lang="zh-CN" data-testid={`fxp-${k}`} />
          </label>
        );
      })}
    </div>
  );
}

function CoverPanel({ doc, time, edit }: { doc: OutputDoc; time: number; edit: EditFn }) {
  const [title, setTitle] = useState(doc.cover_edit?.text ?? doc.post?.title ?? doc.title);
  const [band, setBand] = useState(doc.title_band?.text ?? '');
  const t0 = doc.cover_edit?.t;
  return (
    <div className="col" style={{ gap: 16 }} data-testid="cover-panel">
      {doc.caps.cover !== false && (
        <div className="field4">
          <span className="lbl">{t('editor.coverFrame')}</span>
          {doc.cover && <img src={window.desk.mediaUrl(doc.cover)} alt="" style={{ width: 120, borderRadius: 8 }} />}
          <span className="muted num">{t0 != null ? fmtClock(t0, true) : ''}</span>
          <label className="field4">
            <span className="lbl">{t('editor.coverTitle')}</span>
            <input className="inp" value={title} onChange={(e) => setTitle(e.target.value)} lang="zh-CN" />
          </label>
          <button className="btn" onClick={() => void edit([{ op: 'cover', t: Math.round(time * 100) / 100, text: title, style: 'card' }])} data-testid="cover-use">
            <Check className="ico" />
            {t('editor.coverUse')}
          </button>
        </div>
      )}
      {doc.caps.title_band !== false && (
        <div className="field4">
          <span className="lbl">{t('editor.titleBand')}</span>
          <div className="row">
            <input className="inp sp" value={band} onChange={(e) => setBand(e.target.value)} placeholder={t('editor.titleBandHint')} lang="zh-CN" />
            <button className="btn" onClick={() => void edit([{ op: 'title', text: band.trim() }])}>
              {t('c.save')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ExportPanel({ doc, edit, onFinal, busy }: { doc: OutputDoc; edit: EditFn; onFinal: () => void; busy: boolean }) {
  const have = new Set([...doc.files.map((f) => f.aspect), ...doc.exports.map((e) => e.target)]);
  const flattened = doc.mode === 'flattened';
  return (
    <div className="col" style={{ gap: 16 }} data-testid="export-panel">
      <div className="field4 sizes">
        <span className="lbl">{t('editor.exportSizes')}</span>
        {TARGETS.map((tg) => {
          const orig = doc.files.some((f) => f.aspect === tg);
          const on = have.has(tg);
          return (
            <label key={tg} className="li">
              <input type="checkbox" checked={on} disabled={orig || doc.caps.export === false} onChange={(e) => void edit([e.target.checked ? { op: 'export_add', target: tg, layout: flattened ? 'band' : 'auto' } : { op: 'export_remove', target: tg }])} data-testid={`export-${tg}`} />
              <span>{t(`editor.size.${tg}` as MessageKey)}</span>
            </label>
          );
        })}
        {flattened && <span className="muted">{emsg(doc.caps_notes.find((m) => m.code === 'relayout-crops-burned')) || t('editor.bandHint')}</span>}
      </div>
      <button className="btn" disabled={busy || !doc.steps.length} onClick={onFinal} data-testid="render-final">
        {t('editor.renderFinal')}
      </button>
    </div>
  );
}

function Edits({ doc, onUndoTo }: { doc: OutputDoc; onUndoTo: (k: number) => void }) {
  return (
    <div className="field4" data-testid="edits">
      <span className="lbl">{t('editor.edits')}</span>
      {!doc.steps.length && <span className="muted">{t('editor.noEdits')}</span>}
      <div className="oplist">
        {doc.steps.map((s, k) => (
          <div key={s.id} className="li" data-testid="edit-step">
            <span className="faint num">{k + 1}</span>
            <span className="sp clamp1">{s.describe.map(emsg).join(' · ')}</span>
            {s.by === 'ai' && <Sparkles className="ico faint" />}
            <button className="btn ghost sm" onClick={() => onUndoTo(k)} aria-label={t('c.undo')} data-tip={t('c.undo')}>
              <Undo2 className="ico" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
